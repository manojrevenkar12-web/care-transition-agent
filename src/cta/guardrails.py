"""Deterministic guardrails: instructions hidden in documents, out-of-scope questions, clinical advice in output.

These run before and after the model and do not depend on it: a model can be talked out of its instructions, a regular
expression cannot. They are deliberately narrow; what they miss is caught downstream (the verifier rejects evidence from
flagged text, and nothing leaves without a clinician's release).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import config
from .grounding import sentences


@dataclass(frozen=True)
class Guards:
    injection: tuple[re.Pattern[str], ...]
    out_of_scope: tuple[re.Pattern[str], ...]
    clinical_advice: tuple[re.Pattern[str], ...]
    refusal: str


def load() -> Guards:
    g = config.load("guardrails")
    c = lambda key: tuple(re.compile(p, re.IGNORECASE | re.MULTILINE) for p in g[key])  # noqa: E731
    return Guards(c("injection"), c("out_of_scope"), c("clinical_advice"), " ".join(g["refusal"].split()))


def injection_spans(text: str, guards: Guards | None = None) -> list[tuple[int, int]]:
    """Spans (code points) of sentences that address an AI."""
    guards = guards or load()
    out = []
    for s, e, t in sentences(text):
        if any(r.search(t) for r in guards.injection):
            out.append((s, e))
    return out


def out_of_scope(question: str, guards: Guards | None = None) -> bool:
    guards = guards or load()
    return any(r.search(question) for r in guards.out_of_scope)


def clinical_advice(text: str, guards: Guards | None = None) -> list[str]:
    """Phrases in model output that read as clinical advice."""
    guards = guards or load()
    return [m.group(0) for r in guards.clinical_advice for m in r.finditer(text)]
