# 0002: The model proposes, a deterministic verifier decides what is shown as grounded

**Decision.** The drafter must give the exact words for every value. A rule-based verifier locates them in the
documents and reads negation, predicates, history, other persons, plans and later statements. Only values it finds
grounded are shown as ready; the rest are flagged with the reason and the counter evidence.

**Why.** Evaluation of clinical extraction (CREOLA) shows fabrication, negation and context errors are what matters.
Those are checkable against the source. A reviewer who trusts "ready" fields must be able to: a verifier that never
lets a wrong value through as grounded matters more than one that lets every right value through.

**Measured.** On the golden set, no value marked ready by drafter v2 was wrong (0 of 2,622); with the older prompt or a hastier model, one was. On blind set v2 the
verifier marked 5 of 36 unsupportable claims as grounded; that number, not the golden set's, is the one to improve.
