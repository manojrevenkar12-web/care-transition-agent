"""Offline evaluation on a golden set, judge calibration, the release gate for prompt and model changes, and online
metrics from clinician reviews.

What counts is what a clinician would be shown: a field the verifier marks ready ("grounded") is accepted with one click,
so a wrong value marked ready is the error that matters (`wrong_ready`, and `major_wrong_ready` for the fields that decide
whether a provider can take the patient at all). A wrong value the verifier flags costs review time but is caught.
Wrong values are classified with the CREOLA taxonomy: fabrication, negation, contextual (a stale or other statement in
the case), other; missing values are omissions, and an omission of a positive major fact on an optional field is silent
(nothing asks the clinician about it).
"""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from . import config
from .agent.model import ModelClient, RunLog
from .agent.runner import Agent
from .agent.tools import Toolbox, schemas
from .cases import CaseStore, CaseView
from .db import DB, J
from .drafts import Drafts
from .gateway import Gateway, GatewayError
from .grounding import FLAGGED, Verifier
from .profile import Profile
from .profile import load as load_profile
from .prompts import resolve


def load_golden(set_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((set_dir / "cases").glob("*.json"))]


def _polarity(field_id: str, v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if field_id in ("mre", "ventilation"):
        return v != "keine"
    if field_id == "cognition":
        return v == "demenz"
    return None


def classify(f_id: str, value: Any, status: str, label: Any, statement_values: set[str]) -> str:
    """One field's outcome against its label."""
    ready = status == "grounded"
    if value is None:
        if label is None:
            return "abstain_ok"
        return "omission_asked" if status in ("unknown", "unknown_but_mentioned") else "omission_missing"
    if label is not None and value == label:
        return "correct_ready" if ready else "correct_flagged"
    if label is None:
        kind = "fabrication"
    elif _polarity(f_id, value) is not None and _polarity(f_id, value) != _polarity(f_id, label):
        kind = "negation"
    elif json.dumps(value) in statement_values:
        kind = "contextual"
    else:
        kind = "other"
    return f"wrong_{kind}_{'ready' if ready else 'flagged'}"


@dataclass
class CaseResult:
    case_id: str
    outcomes: dict[str, str]
    tokens: int
    model_calls: int
    seconds: float
    status: str
    summary: str | None
    summary_status: str
    silent_major_omissions: list[str] = field(default_factory=list)


def score_case(
    profile: Profile,
    verifier: Verifier,
    golden: dict[str, Any],
    draft: dict[str, Any],
    view: CaseView,
    run: dict[str, Any],
    seconds: float,
) -> CaseResult:
    labels = golden["labels"]
    outcomes = {}
    silent = []
    summary, summary_status = None, "missing"
    for f in draft["fields"]:
        if f["type"] == "summary":
            summary, summary_status = f["agent_value"], f["agent_status"]
            continue
        st_vals = {
            json.dumps(v)
            for _, vals in verifier.statements(profile.get(f["field"]), view.docs, view.injections)
            for v, ok in vals.items()
            if ok
        }
        oc = classify(f["field"], f["agent_value"], f["agent_status"], labels.get(f["field"]), st_vals)
        outcomes[f["field"]] = oc
        pf = profile.get(f["field"])
        if (
            oc == "omission_missing"
            and pf.severity == "major"
            and not pf.required
            and _polarity(f["field"], labels.get(f["field"])) is True
        ):
            silent.append(f["field"])
    return CaseResult(
        golden["case_id"],
        outcomes,
        int(run["input_tokens"]) + int(run["output_tokens"]),
        int(run["model_calls"]),
        seconds,
        run["status"],
        summary,
        summary_status,
        silent,
    )


def aggregate(profile: Profile, results: list[CaseResult]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    by_field: dict[str, Counter[str]] = defaultdict(Counter)
    for r in results:
        for fid, oc in r.outcomes.items():
            counts[oc] += 1
            by_field[fid][oc] += 1
    labelled = sum(v for k, v in counts.items() if k != "abstain_ok" and not k.startswith("wrong_fabrication"))
    correct = counts["correct_ready"] + counts["correct_flagged"]
    ready = sum(v for k, v in counts.items() if k.endswith("ready"))
    wrong_ready = sum(v for k, v in counts.items() if k.startswith("wrong_") and k.endswith("_ready"))
    major = {f.id for f in profile.fields if f.severity == "major"}
    major_wrong_ready = sum(
        1
        for r in results
        for fid, oc in r.outcomes.items()
        if fid in major and oc.startswith("wrong_") and oc.endswith("_ready")
    )
    total_fields = sum(counts.values())
    review_load = sum(v for k, v in counts.items() if not k.endswith("_ready") and k != "abstain_ok") / max(
        total_fields, 1
    )
    creola: Counter[str] = Counter()
    for k, v in counts.items():
        if k.startswith("wrong_"):
            creola[k.split("_")[1]] += v
        elif k.startswith("omission"):
            creola["omission"] += v
    caught = sum(v for k, v in counts.items() if k.startswith("wrong_") and k.endswith("_flagged"))
    wrong = caught + wrong_ready
    return {
        "cases": len(results),
        "fields": total_fields,
        "field_accuracy": round(correct / max(labelled, 1), 4),
        "ready_share": round(ready / max(total_fields, 1), 4),
        "ready_precision": round(counts["correct_ready"] / max(ready, 1), 4),
        "wrong_ready": wrong_ready,
        "wrong_ready_rate": round(wrong_ready / max(total_fields, 1), 5),
        "major_wrong_ready": major_wrong_ready,
        "wrong_values_caught": round(caught / max(wrong, 1), 4) if wrong else 1.0,
        "review_load": round(review_load, 4),
        "silent_major_omissions": sum(len(r.silent_major_omissions) for r in results),
        "creola": dict(creola),
        "outcomes": dict(counts),
        "by_field": {k: dict(v) for k, v in sorted(by_field.items())},
        "tokens_per_case": round(float(np.mean([r.tokens for r in results])) if results else 0.0, 1),
        "model_calls_per_case": round(float(np.mean([r.model_calls for r in results])) if results else 0.0, 2),
        "seconds_per_case": round(float(np.mean([r.seconds for r in results])) if results else 0.0, 2),
        "run_status": dict(Counter(r.status for r in results)),
        "summary_flagged": sum(1 for r in results if r.summary_status != "grounded"),
    }


def per_case_accuracy(results: list[CaseResult]) -> dict[str, float]:
    out = {}
    for r in results:
        lab = [oc for oc in r.outcomes.values() if oc != "abstain_ok" and not oc.startswith("wrong_fabrication")]
        out[r.case_id] = sum(oc.startswith("correct") for oc in lab) / max(len(lab), 1)
    return out


def paired_bootstrap(a: dict[str, float], b: dict[str, float], n: int, conf: float, seed: int = 0) -> dict[str, float]:
    keys = sorted(set(a) & set(b))
    d = np.array([a[k] - b[k] for k in keys])
    if len(d) == 0:
        return {"delta": 0.0, "low": 0.0, "high": 0.0, "n": 0}
    rng = np.random.default_rng(seed)
    means = d[rng.integers(0, len(d), size=(n, len(d)))].mean(axis=1)
    lo, hi = np.quantile(means, [(1 - conf) / 2, 1 - (1 - conf) / 2])
    return {"delta": round(float(d.mean()), 4), "low": round(float(lo), 4), "high": round(float(hi), 4), "n": len(d)}


def gate(
    cand: dict[str, Any], base: dict[str, Any], paired: dict[str, float], judge: dict[str, Any] | None
) -> dict[str, Any]:
    g = config.load("evaluation")["gate"]
    checks = [
        {
            "check": "no major field wrong yet ready",
            "passed": cand["major_wrong_ready"] <= g["max_major_wrong_ready"],
            "value": cand["major_wrong_ready"],
        },
        {
            "check": "wrong-but-ready not more common",
            "passed": cand["wrong_ready_rate"] <= base["wrong_ready_rate"] + g["max_wrong_ready_rate_increase"],
            "value": f"{cand['wrong_ready_rate']:.4f} vs {base['wrong_ready_rate']:.4f}",
        },
        {
            "check": "field accuracy not worse",
            "passed": paired["low"] >= -g["accuracy_margin"],
            "value": f"{paired['delta']:+.3f} ({paired['low']:+.3f} to {paired['high']:+.3f})",
        },
        {
            "check": "review load",
            "passed": cand["review_load"] <= base["review_load"] + g["max_review_load_increase"],
            "value": f"{cand['review_load']:.3f} vs {base['review_load']:.3f}",
        },
        {
            "check": "tokens per case",
            "passed": cand["tokens_per_case"] <= base["tokens_per_case"] * (1 + g["max_token_increase"]),
            "value": f"{cand['tokens_per_case']:.0f} vs {base['tokens_per_case']:.0f}",
        },
        {
            "check": "no identifier reached a provider",
            "passed": cand["run_status"].get("gateway_identifier_leak", 0) <= g["pii_leaks"],
            "value": cand["run_status"].get("gateway_identifier_leak", 0),
        },
    ]
    if judge:
        for crit, m in judge.get("trusted", {}).items():
            checks.append(
                {
                    "check": f"judge: {crit}",
                    "passed": m["candidate"] >= m["baseline"] - 0.05,
                    "value": f"{m['candidate']:.2f} vs {m['baseline']:.2f}",
                }
            )
    return {"passed": all(c["passed"] for c in checks), "checks": checks}


class Evaluator:
    def __init__(self, db: DB, gateway: Gateway, cases: CaseStore, profile: Profile | None = None):
        self.db, self.gw, self.cases = db, gateway, cases
        self.profile = profile or load_profile()
        self.v = Verifier(self.profile)
        self.drafts = Drafts(db, self.profile, cases, self.v)
        self.tenant = config.load("evaluation")["offline"]["tenant"]
        db.ensure_tenant(self.tenant, "Offline evaluation (synthetic cases)", 1)

    def run(self, golden: list[dict[str, Any]], candidate: str, tag: str) -> tuple[dict[str, Any], list[CaseResult]]:
        """candidate: '<version>@<model>' for the profile drafter."""
        agent = Agent(
            self.db, self.gw, self.cases, self.drafts, self.profile, self.v, override={"profile_drafter": candidate}
        )
        results = []
        for g in golden:
            case_id = f"{tag}-{g['case_id']}"
            self.cases.create(
                self.tenant, g["bundle"], actor="evaluation", as_of=dt.date.fromisoformat(g["as_of"]), case_id=case_id
            )
            t0 = time.monotonic()
            out = agent.draft_profile(self.tenant, case_id, "evaluation")
            secs = time.monotonic() - t0
            view = self.cases.load(self.tenant, case_id)
            if out["draft_id"]:
                draft = self.drafts.get(self.tenant, out["draft_id"])
            else:
                draft = {
                    "fields": [
                        {"field": f.id, "type": f.type, "agent_value": None, "agent_status": "missing"}
                        for f in self.profile.fields
                    ]
                }
            results.append(
                score_case(
                    self.profile,
                    self.v,
                    g,
                    draft,
                    view,
                    {
                        "input_tokens": out["input_tokens"],
                        "output_tokens": out["output_tokens"],
                        "model_calls": out["model_calls"],
                        "status": out["status"],
                    },
                    secs,
                )
            )
        return aggregate(self.profile, results), results

    # ---- LLM-as-a-judge -------------------------------------------------------------------------------------------
    def judge(self, view: CaseView, summary: str, model_override: str | None = None) -> dict[str, Any] | None:
        a = resolve(
            None,
            self.tenant,
            "summary_judge",
            view.case_id,
            {"summary_judge": model_override} if model_override else None,
        )
        run = RunLog()
        tb = Toolbox(view, None, 6000, 5)
        client = ModelClient(self.gw, view, run, config.load("agent")["limits"], "summary_judge", a.prompt.version)
        docs = "\n\n".join(f"[{d.id} {d.kind} {d.authored_at}]\n{d.text}" for d in view.docs)
        msgs: list[dict[str, Any]] = [{"role": "user", "content": f"SUMMARY: {summary}\n\nDOCUMENTS:\n{docs}"}]
        tools = [schemas(self.profile)["grade_summary"]]
        try:
            resp = client.call(a.model, a.prompt.system, msgs, tools)
        except GatewayError:
            return None
        for b in resp.get("content", []):
            if b.get("type") == "tool_use" and b.get("name") == "grade_summary":
                tb.call("grade_summary", b.get("input") or {})
        return tb.grades

    def calibrate_judge(self, golden_dir: Path, golden: list[dict[str, Any]], tag: str) -> dict[str, Any]:
        """Agreement of the judge with clinician labels, per criterion (accuracy and Cohen's kappa)."""
        labels = [
            json.loads(line)
            for line in (golden_dir / "judge.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        by_case = {g["case_id"]: g for g in golden}
        pairs: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
        for item in labels:
            g = by_case.get(item["case_id"])
            if g is None:
                continue
            case_id = f"{tag}-j-{g['case_id']}"
            self.cases.create(
                self.tenant, g["bundle"], actor="evaluation", as_of=dt.date.fromisoformat(g["as_of"]), case_id=case_id
            )
            view = self.cases.load(self.tenant, case_id)
            # the judge reads what providers would read: the pseudonymised summary
            summary = self.gw.pseudonymize(self.tenant, case_id, view.token, [item["summary"]])[0].text
            grades = self.judge(view, summary)
            if grades is None:
                continue
            for crit, human in item["labels"].items():
                pairs[crit].append((bool(grades.get(crit)), bool(human)))
        min_kappa = float(config.load("evaluation")["judge"]["min_kappa"])
        out = {}
        for crit, ps in pairs.items():
            out[crit] = {**agreement(ps), "trusted": False}
            out[crit]["trusted"] = out[crit]["kappa"] >= min_kappa
        return out

    def store(
        self,
        kind: str,
        candidate: dict[str, Any],
        baseline: dict[str, Any] | None,
        metrics: dict[str, Any],
        gate_result: dict[str, Any] | None,
    ) -> str:
        eid = str(uuid.uuid4())
        with self.db.admin() as c:
            c.execute(
                "INSERT INTO eval_runs (id, kind, candidate, baseline, metrics, gate, passed) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    eid,
                    kind,
                    J(candidate),
                    J(baseline),
                    J(metrics),
                    J(gate_result),
                    gate_result["passed"] if gate_result else None,
                ),
            )
        return eid

    def cleanup(self, tag: str) -> None:
        with self.db.tenant(self.tenant) as c:
            c.execute("DELETE FROM cases WHERE id LIKE %s", (tag + "-%",))


def agreement(pairs: list[tuple[bool, bool]]) -> dict[str, float]:
    n = len(pairs)
    if n == 0:
        return {"n": 0, "accuracy": 0.0, "kappa": 0.0}
    agree = sum(a == b for a, b in pairs) / n
    pj = sum(a for a, _ in pairs) / n
    ph = sum(b for _, b in pairs) / n
    pe = pj * ph + (1 - pj) * (1 - ph)
    kappa = (agree - pe) / (1 - pe) if pe < 1 else 1.0
    # how often the judge catches a real failure (human says "no")
    fails = [(a, b) for a, b in pairs if not b]
    recall_fail = sum(not a for a, _ in fails) / len(fails) if fails else 1.0
    return {
        "n": n,
        "accuracy": round(agree, 3),
        "kappa": round(kappa, 3),
        "fail_recall": round(recall_fail, 3),
        "fail_n": len(fails),
    }


# ---- online metrics (no labels: what clinicians did with the drafts) ----------------------------------------------
def online(db: DB, tenant: str, since: str | None = None) -> dict[str, Any]:
    with db.tenant(tenant) as c:
        q = "SELECT * FROM review_events" + (" WHERE at >= %s" if since else "") + " ORDER BY at"
        rows = c.execute(q, (since,) if since else ()).fetchall()
        chats = c.execute("SELECT status, feedback FROM chat_messages WHERE role = 'assistant'").fetchall()
    arms: dict[str, Counter[str]] = defaultdict(Counter)
    by_status: dict[str, Counter[str]] = defaultdict(Counter)
    by_field: dict[str, Counter[str]] = defaultdict(Counter)
    secs: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        arm = f"{r['prompt_version']}@{r['model']}"
        arms[arm][r["action"]] += 1
        by_status[r["agent_status"]][r["action"]] += 1
        by_field[r["field"]][r["action"]] += 1
        if r["seconds_on_field"] is not None:
            secs[arm].append(float(r["seconds_on_field"]))

    def rates(c: Counter[str]) -> dict[str, Any]:
        n = sum(c.values())
        return {"n": n, **{k: round(v / n, 4) for k, v in c.items()}} if n else {"n": 0}

    ready = by_status.get("grounded", Counter())
    flagged: Counter[str] = Counter()
    for s in FLAGGED:
        flagged.update(by_status.get(s, Counter()))
    return {
        "events": len(rows),
        "ready_accepted": rates(ready).get("accepted", 0.0),
        "ready_edited": rates(ready).get("edited", 0.0),
        "flag_precision": round(
            (flagged["edited"] + flagged["rejected"] + flagged["answered"]) / max(sum(flagged.values()), 1), 4
        ),
        "by_arm": {
            k: {**rates(v), "seconds_per_field": round(float(np.mean(secs[k])), 1) if secs[k] else None}
            for k, v in arms.items()
        },
        "by_status": {k: rates(v) for k, v in by_status.items()},
        "most_edited_fields": sorted(
            ((k, rates(v).get("edited", 0.0)) for k, v in by_field.items()), key=lambda x: -x[1]
        )[:5],
        "chat": dict(Counter(r["status"] for r in chats)),
    }
