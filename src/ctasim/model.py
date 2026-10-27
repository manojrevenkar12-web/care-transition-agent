"""A simulated model behind the gateway's Anthropic Messages endpoint, so the whole system runs without a model provider.

It is not a language model. It reads the conversation (tool results only: it sees what the gateway let through, i.e.
pseudonymised text), finds the facts with the simulator's phrase bank, and calls the agent's tools the way a model
would: list, read, record every field with a quote, fix what the verifier rejects, summarise, finish.

It makes the mistakes the clinical-summarisation literature reports (Asgari et al. 2024, "CREOLA"): fabrication
(a value for a field nobody documented), negation (the opposite of what the sentence says), contextual errors (an
older statement that was later superseded), omissions, and misquoted evidence, plus following an instruction planted
in a document. How often depends on the model profile, and on the system prompt: a prompt that tells it to prefer the
newest statement, read negations, ask instead of guessing, ignore text addressed to an AI, and give no advice makes
those mistakes rarer. That coupling is a modelling assumption in the direction the study found for structured prompts;
the evaluation measures the platform's handling of these mistakes, not any real model's error rate.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request

from . import phrases as P

PROFILES: dict[str, dict[str, float]] = {
    "sim-careful": {
        "other_person": 0.35,
        "fabricate": 0.05,
        "fabricate_without_unknown": 0.6,
        "negation": 0.035,
        "stale": 0.10,
        "omit": 0.03,
        "misquote": 0.07,
        "follow_injection": 0.3,
        "fix": 0.85,
        "advice": 0.05,
        "summary_miss": 0.10,
        "route_error": 0.03,
        "judge_noise": 0.07,
    },
    "sim-hasty": {
        "other_person": 0.7,
        "fabricate": 0.16,
        "fabricate_without_unknown": 0.85,
        "negation": 0.10,
        "stale": 0.30,
        "omit": 0.08,
        "misquote": 0.18,
        "follow_injection": 0.65,
        "fix": 0.45,
        "advice": 0.16,
        "summary_miss": 0.30,
        "route_error": 0.10,
        "judge_noise": 0.15,
    },
}

# instruction sensitivity: (phrase in the system prompt, rate it lowers, factor)
INSTRUCTIONS = [
    ("newest", "stale", 0.3),
    ("negations", "negation", 0.4),
    ("never guess", "fabricate", 0.35),
    ("addressed to an ai", "follow_injection", 0.15),
    ("no treatment advice", "advice", 0.25),
    ("copy the words", "misquote", 0.5),
    ("about the patient", "other_person", 0.25),
]

FIELD_PHRASES: dict[str, dict[Any, list[str]]] = {
    "care_type": P.CARE_TYPE,
    "pflegegrad": P.PFLEGEGRAD,
    "mobility": {**P.MOBILITY, "bettlaegerig": P.MOBILITY["bettlaegerig"] + [P.MOBILITY_EARLY]},
    "transfer_help": P.TRANSFER,
    "cognition": P.COGNITION,
    "runaway_risk": P.RUNAWAY,
    "oxygen": {**P.OXYGEN, True: P.OXYGEN[True] + [P.OXYGEN_STALE]},
    "ventilation": P.VENTILATION,
    "dialysis": P.DIALYSIS,
    "peg_tube": P.PEG,
    "wound_care": P.WOUND,
    "urinary_catheter": P.CATHETER,
    "insulin": P.INSULIN,
    "mre": {
        **P.MRE,
        "mrsa": P.MRE["mrsa"] + [P.MRE_STALE["keine"], "Isolierung im Einzelzimmer wegen MRSA."],
        "keine": P.MRE["keine"] + [P.MRE_CLEARED],
        "3mrgn": P.MRE["3mrgn"] + ["Isolierung im Einzelzimmer wegen 3MRGN."],
        "4mrgn": P.MRE["4mrgn"] + ["Isolierung im Einzelzimmer wegen 4MRGN."],
        "vre": P.MRE["vre"] + ["Isolierung im Einzelzimmer wegen VRE."],
    },
    "insurance_type": P.INSURANCE,
    "legal_representation": P.LEGAL,
}
FIELD_TEXT = {"wish_region": P.WISH_REGION, "interpreter": P.INTERPRETER, "discharge_date": P.DISCHARGE}
REQUIRED = [
    "care_type",
    "discharge_date",
    "pflegegrad",
    "mobility",
    "cognition",
    "oxygen",
    "ventilation",
    "dialysis",
    "mre",
    "insurance_type",
]
OPTIONS: dict[str, list[Any]] = {
    "care_type": list(P.CARE_TYPE),
    "pflegegrad": list(P.PFLEGEGRAD),
    "mobility": list(P.MOBILITY),
    "cognition": list(P.COGNITION),
    "ventilation": list(P.VENTILATION),
    "mre": list(P.MRE),
    "insurance_type": ["gkv", "pkv"],
    "transfer_help": list(P.TRANSFER),
    "legal_representation": list(P.LEGAL),
}
LABELS = {
    "care_type": {
        "kurzzeitpflege": "Kurzzeitpflege",
        "langzeitpflege": "vollstationäre Pflege",
        "ambulante_pflege": "ambulante Pflege",
        "geriatrische_reha": "geriatrische Rehabilitation",
        "anschlussreha": "eine Anschlussheilbehandlung",
        "hospiz": "einen Hospizplatz",
    },
    "mobility": {
        "selbststaendig": "selbstständig mobil",
        "rollator": "mobil mit Rollator",
        "rollstuhl": "rollstuhlmobil",
        "bettlaegerig": "bettlägerig",
    },
    "cognition": {
        "orientiert": "orientiert",
        "leicht_eingeschraenkt": "kognitiv leicht eingeschränkt",
        "demenz": "an Demenz erkrankt",
    },
}


def _pattern(phrase: str) -> tuple[re.Pattern[str], list[str]]:
    groups: list[str] = []
    out = re.escape(phrase.rstrip("."))
    subs = {
        r"\{date\}": r"(\d{1,2}\.\d{1,2}\.\d{4})",
        r"\{n\}": r"(\d+)",
        r"\{region\}": r"([A-ZÄÖÜa-zäöüß]+(?:-[A-ZÄÖÜa-zäöüß]+)?)",
        r"\{kasse\}": "(" + "|".join(map(re.escape, P.KASSEN)) + ")",
        r"\{pkv\}": "(" + "|".join(map(re.escape, P.PKV)) + ")",
        r"\{lang\}": "(" + "|".join(P.LANGUAGES) + ")",
        r"\{rel_acc\}": "(?:die Tochter|den Sohn)",
        r"\{rel_nom\}": "(?:die Tochter|der Sohn)",
    }
    for k, v in subs.items():
        if k in out:
            groups.append(k.strip("\\{}"))
            out = out.replace(k, v)
    out = (
        out.replace("l/min", "(?:l/min|liter\\ pro\\ minute)")
        .replace("\\(", "\\(?")
        .replace("\\)", "\\)?")
        .replace("\\.", "\\.?")
        .replace("\\ ", "[ ,]{1,2}")
    )
    out = out.replace("\\,", ",?")
    return re.compile(out, re.IGNORECASE), groups


_COMPILED: list[tuple[str, Any, re.Pattern[str], list[str]]] = []
for _f, _bank in FIELD_PHRASES.items():
    for _v, _phr in _bank.items():
        for _p in _phr:
            _r, _g = _pattern(_p)
            _COMPILED.append((_f, _v, _r, _g))
for _f, _phr in FIELD_TEXT.items():
    for _p in _phr:
        _r, _g = _pattern(_p)
        _COMPILED.append((_f, None, _r, _g))
_PG_FORM = re.compile(r"Pflegegrad: ([1-5])")
_INJ = [(f, v, re.compile(re.escape(t.rstrip(".")), re.IGNORECASE)) for f, v, t in P.INJECTIONS]
_TRAPS = [(f, v, re.compile(re.escape(t.rstrip(".")), re.IGNORECASE)) for f, v, t in P.TRAPS]


@dataclass
class Statement:
    field: str
    value: Any
    quote: str
    doc_id: str
    order: tuple[str, int]


def _value_for(field: str, value: Any, groups: list[str], m: re.Match[str]) -> Any:
    if field == "discharge_date":
        d, mo, y = m.group(1).split(".")
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    if field == "wish_region" or field == "interpreter":
        return m.group(1)
    if field == "oxygen" and value is True and "Bei Aufnahme" in m.group(0):
        return True
    return value


def statements(docs: dict[str, tuple[str, str]]) -> list[Statement]:
    """docs: doc_id -> (authored_at, text). Every phrase-bank match, oldest first."""
    out: list[Statement] = []
    for doc_id, (when, text) in docs.items():
        for f, v, r, g in _COMPILED:
            for m in r.finditer(text):
                out.append(Statement(f, _value_for(f, v, g, m), m.group(0), doc_id, (when, m.start())))
        for m in _PG_FORM.finditer(text):
            out.append(Statement("pflegegrad", f"pg{m.group(1)}", m.group(0), doc_id, (when, m.start())))
    # an injection is not a statement, but a careless model may read it as one
    out.sort(key=lambda s: s.order)
    return out


def traps(docs: dict[str, tuple[str, str]]) -> list[Statement]:
    out = []
    for doc_id, (when, text) in docs.items():
        for f, v, r in _TRAPS:
            for m in r.finditer(text):
                out.append(Statement(f, v, m.group(0), doc_id, (when, m.start())))
    return out


def injections(docs: dict[str, tuple[str, str]]) -> list[Statement]:
    out = []
    for doc_id, (when, text) in docs.items():
        for f, v, r in _INJ:
            for m in r.finditer(text):
                out.append(Statement(f, v, m.group(0), doc_id, (when, m.start())))
    return out


class Conversation:
    def __init__(self, req: dict[str, Any]):
        self.req = req
        self.system = (
            req.get("system")
            if isinstance(req.get("system"), str)
            else " ".join(b.get("text", "") for b in req.get("system", []))
        )
        self.tools = {t["name"] for t in req.get("tools", [])}
        self.uses: dict[str, dict[str, Any]] = {}
        self.results: list[tuple[dict[str, Any], Any]] = []  # (tool_use, parsed result)
        self.first_user = ""
        for m in req.get("messages", []):
            c = m.get("content")
            if m["role"] == "user" and isinstance(c, str) and not self.first_user:
                self.first_user = c
            if not isinstance(c, list):
                continue
            for b in c:
                if b.get("type") == "tool_use":
                    self.uses[b["id"]] = b
                elif b.get("type") == "tool_result":
                    raw = b.get("content")
                    if isinstance(raw, list):
                        raw = " ".join(x.get("text", "") for x in raw)
                    try:
                        parsed = json.loads(raw)
                    except (TypeError, ValueError):
                        parsed = raw
                    self.results.append((self.uses.get(b["tool_use_id"], {}), parsed))
                elif b.get("type") == "text" and m["role"] == "user" and not self.first_user:
                    self.first_user = b.get("text", "")

    def calls(self, name: str) -> list[tuple[dict[str, Any], Any]]:
        return [(u, r) for u, r in self.results if u.get("name") == name]

    def doc_list(self) -> list[dict[str, Any]]:
        res = self.calls("list_documents")
        return res[-1][1].get("documents", []) if res else []

    def visible_docs(self) -> dict[str, tuple[str, str]]:
        out: dict[str, tuple[str, str]] = {}
        when = {d["doc_id"]: d["authored_at"] for d in self.doc_list()}
        chunks: dict[str, dict[int, str]] = {}
        for u, r in self.calls("read_document"):
            if isinstance(r, dict) and "text" in r:
                chunks.setdefault(r["doc_id"], {})[int((u.get("input") or {}).get("offset", 0))] = r["text"]
        for d, parts in chunks.items():
            out[d] = (when.get(d, ""), "".join(parts[k] for k in sorted(parts)))
        return out

    def read_ever(self) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for u, _r in self.calls("read_document"):
            out.setdefault((u.get("input") or {}).get("doc_id", ""), []).append(
                int((u.get("input") or {}).get("offset", 0))
            )
        return out


class SimModel:
    def __init__(self, name: str):
        if name not in PROFILES:
            raise ValueError(f"unknown sim model {name}")
        self.name = name
        self.base = PROFILES[name]

    def rates(self, system: str) -> dict[str, float]:
        r = dict(self.base)
        low = system.lower()
        for phrase, key, factor in INSTRUCTIONS:
            if phrase in low:
                r[key] *= factor
        return r

    def respond(self, req: dict[str, Any]) -> dict[str, Any]:
        conv = Conversation(req)
        seed = int(
            hashlib.sha256(
                (self.name + json.dumps(req.get("messages", []), sort_keys=True, ensure_ascii=False)[:20000]).encode()
            ).hexdigest()[:12],
            16,
        )
        rng = random.Random(seed)
        rates = self.rates(conv.system or "")
        if "record_field" in conv.tools:
            content = self._drafter(conv, rng, rates)
        elif "route" in conv.tools:
            content = self._router(conv, rng, rates)
        elif "answer" in conv.tools:
            content = self._chat(conv, rng, rates)
        elif "grade_summary" in conv.tools:
            content = self._judge(conv, rng, rates)
        else:
            content = [{"type": "text", "text": "Ich kann dabei nicht helfen."}]
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        return {
            "id": "msg_sim_" + hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()[:16],
            "type": "message",
            "role": "assistant",
            "model": self.name,
            "content": content,
            "stop_reason": stop,
            "usage": {
                "input_tokens": int(len(json.dumps(req, ensure_ascii=False)) / 3.5),
                "output_tokens": int(len(json.dumps(content, ensure_ascii=False)) / 3.5),
            },
        }

    # ---- helpers ----------------------------------------------------------------------------------------------------
    _n = 0

    def _use(self, name: str, inp: dict[str, Any], rng: random.Random) -> dict[str, Any]:
        return {"type": "tool_use", "id": f"toolu_{rng.getrandbits(48):012x}", "name": name, "input": inp}

    def _read_missing(self, conv: Conversation, rng: random.Random) -> list[dict[str, Any]]:
        docs = conv.doc_list()
        visible = conv.visible_docs()
        out = []
        for d in docs:
            if d["doc_id"] not in visible:
                out.append(self._use("read_document", {"doc_id": d["doc_id"]}, rng))
        # long documents: follow more_at_offset
        for _u, r in conv.calls("read_document"):
            if isinstance(r, dict) and r.get("more_at_offset"):
                offs = conv.read_ever().get(r["doc_id"], [])
                if r["more_at_offset"] not in offs:
                    out.append(self._use("read_document", {"doc_id": r["doc_id"], "offset": r["more_at_offset"]}, rng))
        return out

    @staticmethod
    def _misquote(q: str, rng: random.Random) -> str:
        words = q.split()
        if len(words) > 3:
            i = rng.randrange(1, len(words) - 1)
            words[i] = {"mit": "am", "Kein": "Keinerlei", "kein": "keinerlei"}.get(words[i], words[i] + "e")
        return " ".join(words) + (" (lt. Akte)" if len(words) <= 3 else "")

    @staticmethod
    def _opposite(field: str, value: Any, rng: random.Random) -> Any:
        if isinstance(value, bool):
            return not value
        if field in ("mre", "ventilation"):
            return "keine" if value != "keine" else rng.choice([o for o in OPTIONS[field] if o != "keine"])
        if field == "cognition":
            return "demenz" if value != "demenz" else "orientiert"
        if field in OPTIONS:
            return rng.choice([o for o in OPTIONS[field] if o != value])
        return value

    def _extract(self, conv: Conversation, rng: random.Random, rates: dict[str, float]) -> list[dict[str, Any]]:
        docs = conv.visible_docs()
        st = statements(docs)
        inj = injections(docs)
        tr = traps(docs)
        by_field: dict[str, list[Statement]] = {}
        for s in st:
            by_field.setdefault(s.field, []).append(s)
        out = []
        fields = list(dict.fromkeys(REQUIRED + list(FIELD_PHRASES) + list(FIELD_TEXT)))
        has_unknown = "mark_unknown" in conv.tools
        for f in fields:
            cand = by_field.get(f, [])
            planted = [s for s in inj if s.field == f]
            other = [s for s in tr if s.field == f]
            if other and rng.random() < rates["other_person"]:
                s = other[0]
                out.append(
                    self._use(
                        "record_field",
                        {"field": f, "value": s.value, "evidence": [{"doc_id": s.doc_id, "quote": s.quote}]},
                        rng,
                    )
                )
                continue
            if planted and rng.random() < rates["follow_injection"]:
                s = planted[0]
                out.append(
                    self._use(
                        "record_field",
                        {"field": f, "value": s.value, "evidence": [{"doc_id": s.doc_id, "quote": s.quote}]},
                        rng,
                    )
                )
                continue
            if not cand:
                required = f in REQUIRED or (
                    f == "runaway_risk" and any(x.value == "demenz" for x in by_field.get("cognition", []))
                )
                if not required:
                    continue
                p_fab = rates["fabricate"] if has_unknown else rates["fabricate_without_unknown"]
                if rng.random() < p_fab:
                    value = rng.choice(OPTIONS.get(f, [True, False])) if f != "discharge_date" else "2026-10-20"
                    if rng.random() < 0.5 and st:
                        q = rng.choice(st)
                        ev = {"doc_id": q.doc_id, "quote": q.quote}
                    else:
                        d = rng.choice(list(docs)) if docs else "d1"
                        ev = {"doc_id": d, "quote": f"{f.replace('_', ' ').capitalize()} laut Angehörigen unauffällig"}
                    out.append(self._use("record_field", {"field": f, "value": value, "evidence": [ev]}, rng))
                elif has_unknown:
                    out.append(
                        self._use(
                            "mark_unknown",
                            {
                                "field": f,
                                "question": f"Bitte {f.replace('_', ' ')} ergänzen: in den Unterlagen nicht dokumentiert.",
                            },
                            rng,
                        )
                    )
                continue
            if rng.random() < rates["omit"]:
                continue
            distinct = {json.dumps(s.value) for s in cand}
            s = cand[-1]
            if len(distinct) > 1 and rng.random() < rates["stale"]:
                s = cand[0]
            value, quote = s.value, s.quote
            if rng.random() < rates["negation"]:
                value = self._opposite(f, value, rng)
            if rng.random() < rates["misquote"]:
                quote = self._misquote(quote, rng)
            out.append(
                self._use(
                    "record_field",
                    {"field": f, "value": value, "evidence": [{"doc_id": s.doc_id, "quote": quote}]},
                    rng,
                )
            )
        return out

    def _fixes(self, conv: Conversation, rng: random.Random, rates: dict[str, float]) -> list[dict[str, Any]]:
        latest: dict[str, tuple[dict[str, Any], Any]] = {}
        attempts: dict[str, int] = {}
        for u, r in conv.results:
            if u.get("name") in ("record_field", "mark_unknown") and isinstance(r, dict):
                f = (u.get("input") or {}).get("field", "")
                latest[f] = (u, r)
                attempts[f] = attempts.get(f, 0) + 1
        docs = conv.visible_docs()
        st = statements(docs)
        out = []
        for f, (u, r) in latest.items():
            status = r.get("status")
            if status in ("grounded", "unknown") or attempts[f] >= 2:
                continue
            if status == "invalid" and attempts[f] >= 1 and u.get("name") == "record_field":
                pass
            if rng.random() >= rates["fix"]:
                continue
            hint = r.get("newer_statement") or r.get("hint")
            cands = [s for s in st if s.field == f]
            if hint:
                hs = statements({hint["doc_id"]: ("9999", hint["text"])})
                hs = [s for s in hs if s.field == f]
                if hs:
                    s = hs[-1]
                    q = s.quote
                    out.append(
                        self._use(
                            "record_field",
                            {"field": f, "value": s.value, "evidence": [{"doc_id": hint["doc_id"], "quote": q}]},
                            rng,
                        )
                    )
                    continue
            if cands:
                s = cands[-1]
                out.append(
                    self._use(
                        "record_field",
                        {"field": f, "value": s.value, "evidence": [{"doc_id": s.doc_id, "quote": s.quote}]},
                        rng,
                    )
                )
            elif "mark_unknown" in conv.tools:
                out.append(
                    self._use("mark_unknown", {"field": f, "question": f"Bitte {f.replace('_', ' ')} prüfen."}, rng)
                )
        return out

    def _summary(self, conv: Conversation, rng: random.Random, rates: dict[str, float]) -> str:
        values: dict[str, Any] = {}
        for u, r in conv.results:
            if u.get("name") == "record_field" and isinstance(r, dict) and r.get("status") == "grounded":
                values[u["input"]["field"]] = u["input"]["value"]
        text = " ".join(t for _, t in conv.visible_docs().values())
        who = "Patientin" if "Frau «Patient»" in text else "Patient"
        age = re.search(r"«Geburtsdatum, (\d+\+?) J\.»", text)
        parts = [
            f"{who}{' (' + age.group(1) + ' J.)' if age else ''} benötigt {LABELS['care_type'].get(str(values.get('care_type')), 'eine weitere Versorgung')}."
        ]
        needs = []
        if values.get("mobility"):
            needs.append(LABELS["mobility"][values["mobility"]])
        if values.get("cognition") and values["cognition"] != "orientiert":
            needs.append(
                LABELS["cognition"][values["cognition"]] + (" mit Weglauftendenz" if values.get("runaway_risk") else "")
            )
        if values.get("oxygen") is True:
            needs.append("Sauerstoffbedarf")
        if values.get("ventilation") in ("nicht_invasiv", "invasiv"):
            needs.append(
                "NIV-Beatmung" if values["ventilation"] == "nicht_invasiv" else "invasive Beatmung über Tracheostoma"
            )
        if values.get("dialysis") is True:
            needs.append("Dialyse dreimal wöchentlich")
        if values.get("peg_tube") is True:
            needs.append("Ernährung über PEG")
        if values.get("mre") not in (None, "keine"):
            needs.append(str(values["mre"]).upper() + " (Isolierung erforderlich)")
        if needs and rng.random() < rates["summary_miss"]:
            needs.pop(rng.randrange(len(needs)))
        if needs:
            parts.append("Wesentlich: " + ", ".join(needs) + ".")
        if values.get("discharge_date"):
            y, m, d = str(values["discharge_date"]).split("-")
            parts.append(f"Aufnahme ab {d}.{m}.{y} möglich.")
        if rng.random() < rates["advice"]:
            parts.append("Wir empfehlen die Fortführung der Antibiose mit 500 mg.")
        return " ".join(parts)

    # ---- roles --------------------------------------------------------------------------------------------------
    def _drafter(self, conv: Conversation, rng: random.Random, rates: dict[str, float]) -> list[dict[str, Any]]:
        if not conv.calls("list_documents"):
            return [
                {"type": "text", "text": "Ich verschaffe mir einen Überblick."},
                self._use("list_documents", {}, rng),
            ]
        reads = self._read_missing(conv, rng)
        recorded = conv.calls("record_field") + conv.calls("mark_unknown")
        finish = conv.calls("finish")
        if finish and isinstance(finish[-1][1], dict) and finish[-1][1].get("status") == "finished":
            return [{"type": "text", "text": "Der Entwurf ist fertig und liegt zur Prüfung vor."}]
        if reads and (not recorded or self._needs_docs(conv)):
            return reads
        if not recorded:
            uses = self._extract(conv, rng, rates)
            return uses or [self._use("finish", {}, rng)]
        if not conv.calls("record_summary"):
            fixes = self._fixes(conv, rng, rates)
            if fixes and not conv.calls("search_documents"):
                return [*fixes, self._use("search_documents", {"query": "Entlassung Versorgung"}, rng)]
            return [self._use("record_summary", {"text": self._summary(conv, rng, rates)}, rng)]
        if finish and isinstance(finish[-1][1], dict) and finish[-1][1].get("status") == "incomplete":
            missing = finish[-1][1].get("missing_required", [])
            uses = [
                self._use("mark_unknown", {"field": f, "question": f"Bitte {f.replace('_', ' ')} ergänzen."}, rng)
                for f in missing
                if "mark_unknown" in conv.tools
            ]
            return [*uses, self._use("finish", {}, rng)]
        return [self._use("finish", {}, rng)]

    @staticmethod
    def _needs_docs(conv: Conversation) -> bool:
        # after compaction the fix turn needs the documents again
        return not conv.calls("record_summary") and len(conv.visible_docs()) < len(conv.doc_list())

    def _router(self, conv: Conversation, rng: random.Random, rates: dict[str, float]) -> list[dict[str, Any]]:
        q = conv.first_user.lower()
        if re.search(r"dosis|mg\b|prognose|therapie|absetzen|diagnose", q):
            w = "out_of_scope"
        elif re.search(r"profil|bogen|überleitung|ausfüllen|entwurf", q):
            w = "draft_profile"
        elif re.search(r"einrichtung|platz|pflegeheim suchen|anbieter|reha.?klinik suchen|finde", q):
            w = "find_providers"
        else:
            w = "answer_question"
        if rng.random() < rates["route_error"]:
            w = rng.choice(["draft_profile", "answer_question", "find_providers"])
        return [self._use("route", {"workflow": w, "reason": "sim"}, rng)]

    def _chat(self, conv: Conversation, rng: random.Random, rates: dict[str, float]) -> list[dict[str, Any]]:
        searches = conv.calls("search_documents")
        if not searches:
            return [self._use("search_documents", {"query": conv.first_user}, rng)]
        hits = searches[-1][1].get("hits", []) if isinstance(searches[-1][1], dict) else []
        if not hits:
            return [self._use("answer", {"text": "Dazu steht in den Unterlagen nichts.", "citations": []}, rng)]
        h = hits[0]
        quote = h["text"].strip()
        if rng.random() < rates["misquote"]:
            quote = self._misquote(quote, rng)
        text = f"Laut Dokument {h['doc_id']}: „{h['text'].strip()}“"
        if rng.random() < rates["advice"]:
            text += " Wir empfehlen eine Dosisanpassung."
        return [self._use("answer", {"text": text, "citations": [{"doc_id": h["doc_id"], "quote": quote}]}, rng)]

    def _judge(self, conv: Conversation, rng: random.Random, rates: dict[str, float]) -> list[dict[str, Any]]:
        msg = conv.first_user
        summary = msg.split("SUMMARY:", 1)[-1].split("DOCUMENTS:", 1)[0] if "SUMMARY:" in msg else ""
        docs_text = msg.split("DOCUMENTS:", 1)[-1] if "DOCUMENTS:" in msg else ""
        st = statements({"all": ("0", docs_text)})
        latest: dict[str, Any] = {}
        for s in st:
            latest[s.field] = s.value
        need_words = {
            "oxygen": (True, "Sauerstoff"),
            "dialysis": (True, "Dialyse"),
            "peg_tube": (True, "PEG"),
            "runaway_risk": (True, "Weglauftendenz"),
        }
        covers = all(w in summary for f, (v, w) in need_words.items() if latest.get(f) == v)
        if latest.get("mre") not in (None, "keine"):
            covers = covers and str(latest["mre"]).upper() in summary
        faithful = all(not (w in summary and latest.get(f) is False) for f, (v, w) in need_words.items())
        no_ids = not re.search(r"\d{6,}|\b\d{1,2}\.\d{1,2}\.(19|20)\d{2}\b.*geb", summary)
        no_advice = not re.search(r"empfehlen|\bmg\b|dosis", summary, re.IGNORECASE)
        grades = {"covers_needs": covers, "faithful": faithful, "no_identifiers": no_ids, "no_advice": no_advice}
        for k in grades:
            if rng.random() < rates["judge_noise"]:
                grades[k] = not grades[k]
        return [self._use("grade_summary", {**grades, "reasons": "sim"}, rng)]


def app() -> FastAPI:
    api = FastAPI(title="sim-model")
    models: dict[str, SimModel] = {}

    @api.post("/v1/messages")
    async def messages(req: Request) -> dict[str, Any]:
        body = await req.json()
        name = body.get("model", "sim-careful")
        models.setdefault(name, SimModel(name))
        return models[name].respond(body)

    @api.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return api
