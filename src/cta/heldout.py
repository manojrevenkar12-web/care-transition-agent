"""Held-out sets for the deterministic safety components: pseudonymisation (via the gateway), the grounding verifier and
the guardrails. Each set is written blind from heldout/WRITING_GUIDE.md and run once: its first run is recorded in
reports/heldout/<set>/first_run.json, pinned by heldout/first_run.sha256, and never rewritten."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import config, guardrails
from .gateway import Gateway
from .grounding import Doc, Verifier
from .profile import load as load_profile

VERDICT_TO_LABEL = {
    "grounded": "supported",
    "contradicted": "contradicted",
    "unsupported": "unsupported",
    "conflict": "stale",
    "quote_not_found": "not_found",
    "injection": "unsupported",
    "invalid": "unsupported",
}


def _read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _is_word(ch: str) -> bool:
    return ch.isalnum()


def _occurrences(text: str, sub: str, inside: list[tuple[int, int]] | None = None) -> list[tuple[int, int]]:
    """Whole-word occurrences of sub ("Stern" in "Hr. Stern", not in "Sternotomie"), outside the given spans."""
    out, i = [], text.find(sub)
    while i >= 0 and sub:
        j = i + len(sub)
        left_ok = not (_is_word(sub[0]) and i > 0 and _is_word(text[i - 1]))
        right_ok = not (_is_word(sub[-1]) and j < len(text) and _is_word(text[j]))
        if left_ok and right_ok and not any(a <= i and j <= b for a, b in inside or []):
            out.append((i, j))
        i = text.find(sub, i + 1)
    return out


def run_pii(items: list[dict[str, Any]], gw: Gateway) -> dict[str, Any]:
    by_kind: dict[str, Counter[str]] = defaultdict(Counter)
    listed: Counter[str] = Counter()
    keep: Counter[str] = Counter()
    over = 0
    refused = 0
    leaked_listed: list[str] = []
    misses: list[dict[str, Any]] = []
    for i, it in enumerate(items):
        ident = {**it["identity"], "tenant": "eval", "case": f"heldout-pii-{i}"}
        token = gw.seal(ident)
        res = gw.pseudonymize("eval", ident["case"], token, [it["text"]])[0]
        spans = [(r["start"], r["end"]) for r in res.replacements]
        keep_spans = [o for k in it.get("must_keep", []) for o in _occurrences(it["text"], k)]
        annotated: list[tuple[int, int]] = []
        listed_spans: list[tuple[int, int]] = []
        seen: set[str] = set()
        for idf in it.get("identifiers", []):
            if idf["text"] in seen:  # one entry per occurrence: score each occurrence once
                continue
            seen.add(idf["text"])
            occ = _occurrences(it["text"], idf["text"], keep_spans)
            annotated += occ
            key = "listed" if idf.get("listed") else "unlisted"
            if idf.get("listed"):
                listed_spans += occ
            for s, e in occ:
                covered = any(rs < e and re_ > s for rs, re_ in spans)
                by_kind[idf["kind"]][f"{key}_{'caught' if covered else 'missed'}"] += 1
                listed[f"{key}_{'caught' if covered else 'missed'}"] += 1
                if not covered:
                    misses.append({"id": it["id"], "kind": idf["kind"], "listed": bool(idf.get("listed"))})
        if res.leaks:
            refused += 1
        elif any(not any(rs < e and re_ > s for rs, re_ in spans) for s, e in listed_spans):
            leaked_listed.append(it["id"])
        for k in it.get("must_keep", []):
            keep["kept" if k in res.text else "destroyed"] += 1
        over += sum(1 for rs, re_ in spans if not any(rs < e and re_ > s for s, e in annotated))

    def rate(c: Counter[str], key: str) -> float:
        n = c[f"{key}_caught"] + c[f"{key}_missed"]
        return round(c[f"{key}_caught"] / n, 4) if n else 1.0

    return {
        "documents": len(items),
        "listed_recall": rate(listed, "listed"),
        "unlisted_recall": rate(listed, "unlisted"),
        "counts": dict(listed),
        "by_kind": {
            k: {"listed_recall": rate(v, "listed"), "unlisted_recall": rate(v, "unlisted"), **dict(v)}
            for k, v in sorted(by_kind.items())
        },
        "documents_refused_by_leak_check": refused,
        "documents_with_listed_identifier_reaching_model": len(leaked_listed),
        "must_keep_destroyed": keep["destroyed"],
        "must_keep_total": keep["kept"] + keep["destroyed"],
        "over_redactions": over,
        "misses": misses,
    }


def run_grounding(items: list[dict[str, Any]]) -> dict[str, Any]:
    v = Verifier(load_profile())
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    wrongly_grounded = []
    for it in items:
        docs = [Doc(d["id"], d.get("kind", "dokument"), d["authored_at"], d["text"]) for d in it["documents"]]
        inj = {d.id: guardrails.injection_spans(d.text) for d in docs}
        verdict = v.verify(it["field"], it["value"], it["evidence"], docs, inj)
        got = VERDICT_TO_LABEL.get(verdict.status, verdict.status)
        confusion[it["label"]][got] += 1
        if got == "supported" and it["label"] != "supported":
            wrongly_grounded.append({"id": it["id"], "label": it["label"], "field": it["field"]})
    total = sum(sum(c.values()) for c in confusion.values())
    correct = sum(confusion[k][k] for k in confusion)
    sup = confusion.get("supported", Counter())
    return {
        "items": total,
        "accuracy": round(correct / max(total, 1), 4),
        "supported_recall": round(sup["supported"] / max(sum(sup.values()), 1), 4),
        "wrongly_grounded": len(wrongly_grounded),
        "wrongly_grounded_share_of_unsupportable": round(len(wrongly_grounded) / max(total - sum(sup.values()), 1), 4),
        "confusion": {k: dict(c) for k, c in sorted(confusion.items())},
        "wrongly_grounded_items": wrongly_grounded,
    }


def run_guards(items: list[dict[str, Any]]) -> dict[str, Any]:
    g = guardrails.load()
    out: dict[str, Any] = {}
    for kind in ("injection", "scope", "advice"):
        c: Counter[str] = Counter()
        for it in (x for x in items if x["kind"] == kind):
            if kind == "injection":
                pred = bool(guardrails.injection_spans(it["text"], g))
            elif kind == "scope":
                pred = guardrails.out_of_scope(it["text"], g)
            else:
                pred = bool(guardrails.clinical_advice(it["text"], g))
            c[("t" if pred == it["label"] else "f") + ("p" if pred else "n")] += 1
        n = sum(c.values())
        out[kind] = {
            "items": n,
            "accuracy": round((c["tp"] + c["tn"]) / max(n, 1), 4),
            "recall": round(c["tp"] / max(c["tp"] + c["fn"], 1), 4),
            "precision": round(c["tp"] / max(c["tp"] + c["fp"], 1), 4),
            **dict(c),
        }
    return out


SCORED_CODE = ["gateway", "config", "src/cta/grounding.py", "src/cta/guardrails.py", "src/cta/profile.py"]


def rescore(set_name: str, gw: Gateway, reason: str) -> dict[str, Any]:
    """Score the first run again after a fix to the scorer only. Allowed only while the components under test are
    byte-identical to the first run's commit, so the numbers are what that code did on unseen data. The first run
    stays as recorded; the rescored file sits next to it and is pinned too."""
    import subprocess

    root = config.root()
    first = json.loads((root / "reports" / "heldout" / set_name / "first_run.json").read_text(encoding="utf-8"))
    diff = subprocess.run(
        ["git", "diff", "--stat", first["code_commit"], "--", *SCORED_CODE], cwd=root, capture_output=True, text=True
    )
    if diff.returncode != 0 or diff.stdout.strip():
        raise SystemExit(
            "the components under test changed since the first run; rescoring is not allowed:\n" + diff.stdout
        )
    d = root / "heldout" / set_name
    out = root / "reports" / "heldout" / set_name / "first_run_rescored.json"
    if out.exists():
        raise SystemExit(f"{out} exists and is not rewritten")
    result = {
        "set": set_name,
        "code_commit": first["code_commit"],
        "rescored_because": reason,
        "pii": run_pii(_read(d / "pii.jsonl"), gw),
        "grounding": run_grounding(_read(d / "grounding.jsonl")),
        "guards": run_guards(_read(d / "guards.jsonl")),
    }
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    pin = root / "heldout" / "first_run.sha256"
    pin.write_text(
        pin.read_text()
        + f"{hashlib.sha256(out.read_bytes()).hexdigest()}  reports/heldout/{set_name}/first_run_rescored.json\n"
    )
    return result


def run(set_name: str, gw: Gateway | None) -> dict[str, Any]:
    root = config.root()
    d = root / "heldout" / set_name
    report_dir = root / "reports" / "heldout" / set_name
    first = report_dir / "first_run.json"
    if first.exists():
        raise SystemExit(f"{first} exists: a held-out set's first run is recorded once and never rewritten")
    status = (d / "STATUS").read_text().strip() if (d / "STATUS").exists() else "held-out"
    result: dict[str, Any] = {"set": set_name, "status_at_run": status}
    if gw is not None:
        result["pii"] = run_pii(_read(d / "pii.jsonl"), gw)
    result["grounding"] = run_grounding(_read(d / "grounding.jsonl"))
    result["guards"] = run_guards(_read(d / "guards.jsonl"))
    import subprocess

    result["code_commit"] = (
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip() or None
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    first.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    pin = root / "heldout" / "first_run.sha256"
    lines = pin.read_text().splitlines() if pin.exists() else []
    lines.append(f"{hashlib.sha256(first.read_bytes()).hexdigest()}  reports/heldout/{set_name}/first_run.json")
    pin.write_text("\n".join(lines) + "\n")
    return result
