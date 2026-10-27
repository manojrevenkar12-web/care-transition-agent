"""Field-level grounding: does the sentence the agent quoted say what the agent put in the field?

The agent fills each field with a value and the exact words it read ("evidence"). The verifier:

1. finds the quote in the (pseudonymised) document it cites, or in any document of the case if it cited the wrong one;
   a quote that is in no document is fabricated evidence (`quote_not_found`);
2. refuses evidence that comes from text addressed to an AI ("Hinweis für die KI: ...") (`injection`);
3. reads the whole clause around the quote, so "Dialysepflicht" quoted out of "Keine Dialysepflicht" is read as a
   negation, and decides whether the clause supports, negates, or does not speak to the value
   (`grounded` / `contradicted` / `unsupported`);
4. looks for a later statement about the same field that says something else ("MRSA positiv" on admission, "MRSA nach
   Sanierung negativ" in the discharge letter), and marks the field `conflict` with that statement attached.

It also checks abstentions: a field the agent left unknown although a document speaks to it is `unknown_but_mentioned`.
The error taxonomy follows Asgari et al. (2024): fabrication, negation, contextual (a stale or other statement) and
omission.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from . import config
from .profile import Field, Profile


@dataclass
class Doc:
    id: str
    kind: str
    authored_at: str
    text: str  # what the model saw (pseudonymised)


@dataclass
class Evidence:
    doc_id: str
    quote: str
    start: int = -1
    end: int = -1
    sentence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "quote": self.quote,
            "start": self.start,
            "end": self.end,
            "sentence": self.sentence,
        }


@dataclass
class Verdict:
    status: str
    reason: str
    evidence: list[Evidence] = field(default_factory=list)
    counter: list[Evidence] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "grounded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "evidence": [e.to_dict() for e in self.evidence],
            "counter": [e.to_dict() for e in self.counter],
        }


FLAGGED = {"quote_not_found", "unsupported", "contradicted", "injection", "conflict", "invalid"}

_WS = re.compile(r"\s+")
_DATE = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4}|\d{2})\b")
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ«(\d])")
_CLAUSE = re.compile(r"[,;()]|\s[-–]\s")
_TOKEN = re.compile(r"[\wäöüß/\-.]+", re.UNICODE)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s).replace(" ", " ").replace("–", "-").replace("„", '"').replace("“", '"')
    return _WS.sub(" ", s).strip().lower()


def find_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Locate quote in text ignoring case and whitespace; returns code-point offsets in text."""
    q = _norm(quote).strip(' ."')
    if len(q) < 3:
        return None
    # build a normalised copy with a map back to original offsets
    norm_chars: list[str] = []
    back: list[int] = []
    prev_space = False
    for i, ch in enumerate(unicodedata.normalize("NFC", text)):
        c = ch.lower()
        if c in " ":
            c = " "
        if c == "–":
            c = "-"
        if c in "„“":
            c = '"'
        if c.isspace():
            if prev_space:
                continue
            c, prev_space = " ", True
        else:
            prev_space = False
        norm_chars.append(c)
        back.append(i)
    hay = "".join(norm_chars)
    k = hay.find(q)
    if k < 0:
        return None
    return back[k], back[k + len(q) - 1] + 1


def sentences(text: str) -> list[tuple[int, int, str]]:
    """Sentence spans (start, end, text). Unpunctuated dictation becomes one long sentence."""
    out, start = [], 0
    for m in _SENT_END.finditer(text):
        out.append((start, m.start(), text[start : m.start()]))
        start = m.end()
    out.append((start, len(text), text[start:]))
    return [s for s in out if s[2].strip()]


def _sentence_around(text: str, start: int, end: int) -> tuple[int, int, str]:
    for s, e, _t in sentences(text):
        if s <= start < e or (start <= s < end):
            return s, max(e, end), text[s : max(e, end)]
    return start, end, text[start:end]


def _parse_dt(s: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return dt.datetime.min


class Verifier:
    def __init__(self, profile: Profile, lexicon: dict[str, Any] | None = None):
        self.profile = profile
        lex = lexicon or config.load("grounding")
        self.neg_before = [re.compile(rf"^{p}$") for p in lex["negation"]["before"]]
        self.neg_after = [re.compile(rf"^{p}$") for p in lex["negation"]["after"]]
        self.window = int(lex["negation"]["window"])
        self.closers = set(lex["negation"].get("closers", []))
        self.spoken = {k: int(v) for k, v in lex["spoken_numbers"].items()}
        self.fields: dict[str, dict[str, Any]] = {}
        for fid, spec in lex["fields"].items():
            c: dict[str, Any] = {"special": spec.get("special")}
            c["concept"] = [re.compile(p) for p in spec.get("concept", [])]
            c["options"] = {k: [re.compile(p) for p in v] for k, v in (spec.get("options") or {}).items()}
            c["false"] = [re.compile(p) for p in spec.get("false_patterns", [])]
            c["none"] = [re.compile(p) for p in spec.get("none_patterns", [])]
            c["context"] = [re.compile(p) for p in spec.get("text_context", [])]
            self.fields[fid] = c
        self.conflict_check = bool(lex.get("conflict_check", True))
        self.not_about = [re.compile(p) for p in lex.get("not_about_patient", [])]
        every = [p for spec in lex["fields"].values() for p in spec.get("concept", [])]
        every += [p for spec in lex["fields"].values() for pats in (spec.get("options") or {}).values() for p in pats]
        self._any_concept = re.compile("|".join(f"(?:{p})" for p in every))

    # ---- reading a clause ---------------------------------------------------------------------------------------
    def _negated(self, clause: str, start: int, end: int) -> bool:
        before = [(m.start(), m.group(0).strip(".")) for m in _TOKEN.finditer(clause[:start])][-self.window :]
        after = [(m.start() + end, m.group(0).strip(".")) for m in _TOKEN.finditer(clause[end:])][: self.window]
        for i, (pos, tok) in enumerate(before):
            nxt = before[i + 1][1] if i + 1 < len(before) else ""
            if nxt in self.closers:
                continue
            if any(r.match(tok) for r in self.neg_before) and not self._blocked(clause[pos:start]):
                return True
        for pos, tok in after:
            if any(r.match(tok) for r in self.neg_after) and not self._blocked(clause[end:pos]):
                return True
        return False

    def _blocked(self, gap: str) -> bool:
        """Another field's concept between a negation cue and this concept ends the cue's scope."""
        return bool(self._any_concept.search(gap))

    @staticmethod
    def _clauses(sentence: str) -> list[str]:
        parts = [p for p in _CLAUSE.split(sentence.lower()) if p.strip()]
        return parts or [sentence.lower()]

    def _concept_polarity(self, pats: list[re.Pattern[str]], clause: str) -> set[bool]:
        out = set()
        for r in pats:
            for m in r.finditer(clause):
                out.add(not self._negated(clause, m.start(), m.end()))
        return out

    def values_in(self, f: Field, sentence: str) -> dict[Any, bool]:
        """Values this sentence speaks to: {value: True (supported) / False (negated)}."""
        spec = self.fields.get(f.id)
        if spec is None:
            return {}
        out: dict[Any, bool] = {}
        for clause in self._clauses(sentence):
            if spec["special"] == "pflegegrad":
                out.update(self._pflegegrad(clause))
                continue
            if spec["special"] == "date":
                if spec["context"] and not any(r.search(sentence.lower()) for r in spec["context"]):
                    continue
                for m in _DATE.finditer(clause):
                    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    y = y + 2000 if y < 100 else y
                    with contextlib.suppress(ValueError):
                        out[dt.date(y, mo, d).isoformat()] = True
                continue
            if f.type == "boolean":
                pol = self._concept_polarity(spec["concept"], clause)
                if any(r.search(clause) for r in spec["false"]):
                    pol.add(False)
                for p in pol:
                    out[p] = True
                continue
            if f.type == "enum":
                matched_option = False
                for opt, pats in spec["options"].items():
                    for r in pats:
                        for m in r.finditer(clause):
                            matched_option = True
                            neg = self._negated(clause, m.start(), m.end())
                            out[opt] = out.get(opt, True) and not neg
                            if neg and "keine" in f.options:
                                out["keine"] = True
                if "keine" in f.options and spec["concept"]:
                    pol = self._concept_polarity(spec["concept"], clause)
                    if False in pol and not any(v for k, v in out.items() if k != "keine"):
                        out["keine"] = True
                if "keine" in f.options and any(r.search(clause) for r in spec["none"]):
                    out["keine"] = True
                if not matched_option and not spec["concept"]:
                    continue
        return out

    def _pflegegrad(self, clause: str) -> dict[Any, bool]:
        out: dict[Any, bool] = {}
        applied = re.search(r"beantragt|antrag", clause)
        if re.search(r"kein(en)? pflegegrad|pflegegrad (liegt|ist) (noch )?nicht|ohne pflegegrad", clause):
            out["keiner"] = True
        for m in re.finditer(r"(?:pflegegrad|\bpg)\s*[:\-]?\s*(?:\[x\]\s*)?([1-5]|eins|zwei|drei|vier|fünf)\b", clause):
            n = m.group(1)
            level = int(n) if n.isdigit() else self.spoken[n]
            if applied:
                out[f"pg{level}"] = False
            else:
                out[f"pg{level}"] = True
        if applied and "pflegegrad" in clause:
            out["beantragt"] = True
        return out

    def support(self, f: Field, value: Any, sentence: str) -> str:
        """'supports', 'negates' or 'silent'."""
        if f.type in ("text", "summary"):
            spec = self.fields.get(f.id, {})
            low = sentence.lower()
            if str(value).lower() in low and (not spec.get("context") or any(r.search(low) for r in spec["context"])):
                return "supports"
            return "silent"
        vals = self.values_in(f, sentence)
        if value in vals:
            return "supports" if vals[value] else "negates"
        if f.type == "boolean" and (not value) in vals:
            return "negates"
        if f.type == "enum" and value != "keine" and vals.get("keine") is True:
            return "negates"  # "kein Nachweis multiresistenter Erreger" contradicts "MRSA"
        return "silent"

    # ---- the verdict --------------------------------------------------------------------------------------------
    def verify(
        self,
        field_id: str,
        value: Any,
        evidence: list[dict[str, Any]] | list[Evidence],
        docs: list[Doc],
        injection_spans: dict[str, list[tuple[int, int]]] | None = None,
    ) -> Verdict:
        f = self.profile.get(field_id)
        injection_spans = injection_spans or {}
        evs = [
            e if isinstance(e, Evidence) else Evidence(str(e.get("doc_id", "")), str(e.get("quote", "")))
            for e in evidence
        ]
        if not evs:
            return Verdict("unsupported", "no evidence was given")
        by_id = {d.id: d for d in docs}
        located: list[Evidence] = []
        for e in evs:
            order = [by_id[e.doc_id]] if e.doc_id in by_id else []
            order += [d for d in docs if d.id != e.doc_id]
            for d in order:
                span = find_quote(d.text, e.quote)
                if span:
                    s, end, sent = _sentence_around(d.text, *span)
                    located.append(Evidence(d.id, e.quote, span[0], span[1], sent))
                    break
            else:
                return Verdict("quote_not_found", "the quoted words are in none of the case's documents", evidence=evs)
        for e in located:
            for s, end in injection_spans.get(e.doc_id, []):
                if e.start < end and e.end > s:
                    return Verdict(
                        "injection", "the evidence is text addressed to an AI, not a clinical statement", located
                    )
        if all(self._not_about_patient(e.sentence) for e in located):
            return Verdict("unsupported", "the quoted statement is about someone else or the past", located)
        readings = [self.support(f, value, e.sentence) for e in located]
        if "negates" in readings:
            return Verdict("contradicted", "the quoted statement says the opposite", located)
        if "supports" not in readings:
            return Verdict("unsupported", "the quoted statement does not say this", located)
        if self.conflict_check and f.type not in ("text", "summary"):
            latest = self.latest_statement(f, docs, injection_spans)
            if latest is not None:
                lat_ev, lat_vals = latest
                cited = {(e.doc_id, e.start) for e in located}
                newer_than_cited = all(self._later(lat_ev, e, by_id) for e in located)
                says_else = lat_vals.get(value) is False or any(v is True for k, v in lat_vals.items() if k != value)
                if (
                    (lat_ev.doc_id, lat_ev.start) not in cited
                    and newer_than_cited
                    and says_else
                    and lat_vals.get(value) is not True
                ):
                    return Verdict("conflict", "a later statement says something else", located, [lat_ev])
        return Verdict("grounded", "the quoted statement supports the value", located)

    def _not_about_patient(self, sentence: str) -> bool:
        low = sentence.lower().strip()
        return any(r.search(low) for r in self.not_about)

    @staticmethod
    def _later(a: Evidence, b: Evidence, by_id: dict[str, Doc]) -> bool:
        ka = (_parse_dt(by_id[a.doc_id].authored_at), a.start)
        kb = (_parse_dt(by_id[b.doc_id].authored_at), b.start)
        return ka > kb

    def statements(
        self, f: Field, docs: list[Doc], injection_spans: dict[str, list[tuple[int, int]]] | None = None
    ) -> list[tuple[Evidence, dict[Any, bool]]]:
        """Every sentence of the case that speaks to the field, oldest first."""
        injection_spans = injection_spans or {}
        out = []
        for d in sorted(docs, key=lambda d: _parse_dt(d.authored_at)):
            for s, e, t in sentences(d.text):
                if any(s < ie and e > is_ for is_, ie in injection_spans.get(d.id, [])):
                    continue
                if self._not_about_patient(t):
                    continue
                vals = self.values_in(f, t)
                if vals:
                    out.append((Evidence(d.id, t.strip(), s, e, t), vals))
        return out

    def latest_statement(
        self, f: Field, docs: list[Doc], injection_spans: dict[str, list[tuple[int, int]]] | None = None
    ) -> tuple[Evidence, dict[Any, bool]] | None:
        st = self.statements(f, docs, injection_spans)
        return st[-1] if st else None

    def check_unknown(
        self, field_id: str, docs: list[Doc], injection_spans: dict[str, list[tuple[int, int]]] | None = None
    ) -> Verdict:
        f = self.profile.get(field_id)
        if f.type in ("text", "summary"):
            return Verdict("unknown", "not checked")
        st = self.statements(f, docs, injection_spans)
        if st:
            return Verdict("unknown_but_mentioned", "a document speaks to this field", counter=[st[-1][0]])
        return Verdict("unknown", "no document speaks to this field")
