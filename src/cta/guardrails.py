"""Deterministic guardrails: instructions hidden in documents, out-of-scope questions, clinical advice in output.

These run before and after the model and do not depend on it: a model can be talked out of its instructions, a regular
expression cannot. They are a flag and a filter, not the defence; what they miss is caught downstream (documents are
always data to the model, the verifier rejects evidence from flagged text, and nothing leaves without a clinician's
release). Each rule combines cues (who is addressed and what they are told; a decision asked for and not a report
asked for) so ordinary clinical language does not trip it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import config
from .grounding import sentences

Patterns = tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class Guards:
    injection_always: Patterns
    injection_audience: Patterns
    injection_directive: Patterns
    scope_decision: Patterns
    scope_maybe: Patterns
    scope_report: Patterns
    advice: Patterns
    advice_report: Patterns
    refusal: str


def _c(pats: list[str]) -> Patterns:
    return tuple(re.compile(p, re.IGNORECASE | re.MULTILINE) for p in pats)


def load() -> Guards:
    g = config.load("guardrails")
    inj, oos, adv = g["injection"], g["out_of_scope"], g["clinical_advice"]
    return Guards(
        _c(inj["always"]),
        _c(inj["audience"]),
        _c(inj["directive"]),
        _c(oos["decision"]),
        _c(oos["maybe"]),
        _c(oos["report"]),
        _c(adv["advice"]),
        _c(adv["report"]),
        " ".join(g["refusal"].split()),
    )


def _any(pats: Patterns, text: str) -> bool:
    return any(r.search(text) for r in pats)


def is_injection(sentence: str, guards: Guards) -> bool:
    s = sentence.lower()
    return _any(guards.injection_always, s) or (
        _any(guards.injection_audience, s) and _any(guards.injection_directive, s)
    )


def injection_spans(text: str, guards: Guards | None = None) -> list[tuple[int, int]]:
    """Spans (code points) of sentences that address an AI."""
    guards = guards or load()
    return [(s, e) for s, e, t in sentences(text) if is_injection(t, guards)]


def out_of_scope(question: str, guards: Guards | None = None) -> bool:
    guards = guards or load()
    q = question.lower()
    if _any(guards.scope_decision, q):
        return True
    return _any(guards.scope_maybe, q) and not _any(guards.scope_report, q)


def clinical_advice(text: str, guards: Guards | None = None) -> list[str]:
    """Sentences in model output that read as clinical advice (and are not attributed to the documents)."""
    guards = guards or load()
    out = []
    for _s, _e, t in sentences(text):
        low = t.lower()
        if _any(guards.advice, low) and not _any(guards.advice_report, low):
            out.append(t.strip())
    return out
