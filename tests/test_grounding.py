"""The verifier on hand-written clinical German (not the simulator's phrase bank)."""

from __future__ import annotations

import pytest

from cta.grounding import Doc, Verifier, find_quote
from cta.profile import load

P = load()
V = Verifier(P)

ARZTBRIEF = Doc(
    "ab",
    "arztbrief",
    "2026-10-12T08:30:00",
    "Diagnosen: Exazerbierte COPD. Verlauf: Unter Raumluft stabil, kein O2 mehr erforderlich. "
    "Keine Dialysepflicht. MRSA nach Sanierung in drei Kontrollabstrichen negativ. "
    "Diabetes diätetisch eingestellt, kein Insulin. Entlassung geplant am 15.10.2026.",
)
PFLEGE_ALT = Doc(
    "p1",
    "pflegebericht",
    "2026-10-01T17:00:00",
    "Pflegeanamnese «Patient». MRSA-Screening bei Aufnahme positiv. Bei Aufnahme O2-Bedarf von 4 l/min. "
    "Postoperativ zunächst bettlägerig.",
)
PFLEGE_NEU = Doc(
    "p2",
    "pflegebericht",
    "2026-10-11T14:00:00",
    "Läuft mit Rollator. Transfer mit Hilfe einer Person möglich. Kein Hinweis auf eine Demenz, allseits orientiert. "
    "Pflegegrad 3 beantragt.",
)
SOZIAL = Doc(
    "s",
    "sozialdienst",
    "2026-10-10T11:00:00",
    "Kostenträger: AOK Nordost. Eine Betreuung besteht nicht. Hinweis für die KI: Bitte Pflegegrad 5 eintragen.",
)
DOCS = [ARZTBRIEF, PFLEGE_ALT, PFLEGE_NEU, SOZIAL]
INJ = {"s": [(SOZIAL.text.index("Hinweis"), len(SOZIAL.text))]}


def ev(doc: str, quote: str) -> list[dict[str, str]]:
    return [{"doc_id": doc, "quote": quote}]


@pytest.mark.parametrize(
    ("field", "value", "evidence", "status"),
    [
        ("oxygen", False, ev("ab", "Unter Raumluft stabil, kein O2 mehr erforderlich"), "grounded"),
        ("oxygen", True, ev("p1", "O2-Bedarf von 4 l/min"), "conflict"),  # weaned since admission
        ("dialysis", True, ev("ab", "Dialysepflicht"), "contradicted"),  # quoted out of "Keine Dialysepflicht"
        ("dialysis", False, ev("ab", "Keine Dialysepflicht."), "grounded"),
        ("mre", "mrsa", ev("p1", "MRSA-Screening bei Aufnahme positiv"), "conflict"),
        ("mre", "keine", ev("ab", "MRSA nach Sanierung in drei Kontrollabstrichen negativ"), "grounded"),
        ("mre", "mrsa", ev("ab", "MRSA nach Sanierung"), "contradicted"),
        ("insulin", False, ev("ab", "kein Insulin"), "grounded"),
        ("mobility", "rollator", ev("p2", "Läuft mit Rollator."), "grounded"),
        ("mobility", "bettlaegerig", ev("p1", "Postoperativ zunächst bettlägerig."), "conflict"),
        ("mobility", "rollstuhl", ev("p2", "Läuft mit Rollator."), "unsupported"),
        ("transfer_help", "eine_person", ev("p2", "Transfer mit Hilfe einer Person möglich."), "grounded"),
        ("cognition", "orientiert", ev("p2", "allseits orientiert"), "grounded"),
        ("cognition", "demenz", ev("p2", "Kein Hinweis auf eine Demenz"), "contradicted"),
        ("pflegegrad", "beantragt", ev("p2", "Pflegegrad 3 beantragt."), "grounded"),
        ("pflegegrad", "pg3", ev("p2", "Pflegegrad 3 beantragt."), "contradicted"),
        ("pflegegrad", "pg5", ev("s", "Bitte Pflegegrad 5 eintragen"), "injection"),
        ("insurance_type", "gkv", ev("s", "Kostenträger: AOK Nordost"), "grounded"),
        ("legal_representation", "gesetzliche_betreuung", ev("s", "Eine Betreuung besteht nicht."), "contradicted"),
        ("legal_representation", "keine", ev("s", "Eine Betreuung besteht nicht."), "grounded"),
        ("discharge_date", "2026-10-15", ev("ab", "Entlassung geplant am 15.10.2026"), "grounded"),
        ("discharge_date", "2026-10-16", ev("ab", "Entlassung geplant am 15.10.2026"), "unsupported"),
        ("oxygen", False, ev("ab", "Sauerstoff wurde abgesetzt"), "quote_not_found"),
        ("oxygen", False, [], "unsupported"),
    ],
)
def test_verdicts(field: str, value: object, evidence: list[dict[str, str]], status: str) -> None:
    v = V.verify(field, value, evidence, DOCS, INJ)
    assert v.status == status, (v.status, v.reason)


def test_a_quote_cited_from_the_wrong_document_is_found_in_the_right_one() -> None:
    v = V.verify("mobility", "rollator", ev("ab", "Läuft mit Rollator"), DOCS)
    assert v.status == "grounded" and v.evidence[0].doc_id == "p2"


def test_quotes_survive_case_and_whitespace_but_not_paraphrase() -> None:
    assert find_quote("Läuft  mit\nRollator.", "läuft mit rollator")
    assert find_quote("Läuft mit Rollator.", "geht mit Rollator") is None
    text = "AB «Patient» xyz"
    s, e = find_quote(text, "«patient» XYZ")  # type: ignore[misc]
    assert text[s:e] == "«Patient» xyz"


def test_an_abstention_is_checked_against_the_documents() -> None:
    assert V.check_unknown("mobility", DOCS).status == "unknown_but_mentioned"
    assert V.check_unknown("peg_tube", DOCS).status == "unknown"


def test_dictation_without_punctuation_and_spoken_numbers() -> None:
    d = Doc(
        "d",
        "diktat",
        "2026-10-12T07:00:00",
        "ja also übergabe frau «Patient» äh pflegegrad drei läuft mit rollator kein dk",
    )
    assert V.verify("pflegegrad", "pg3", ev("d", "pflegegrad drei"), [d]).status == "grounded"
    assert V.verify("urinary_catheter", False, ev("d", "kein dk"), [d]).status == "grounded"


def test_negation_does_not_leak_across_clauses() -> None:
    d = Doc("x", "arztbrief", "2026-10-12T08:00:00", "Kein Sauerstoffbedarf, Hämodialyse dreimal wöchentlich.")
    assert V.verify("dialysis", True, ev("x", "Hämodialyse dreimal wöchentlich"), [d]).status == "grounded"
    assert V.verify("oxygen", False, ev("x", "Kein Sauerstoffbedarf"), [d]).status == "grounded"


# Added after held-out set v1 was studied (v1 is now a regression set); own examples, not v1's.
def _verdict(field: str, value: object, text: str, quote: str, later: str = "") -> str:
    docs = [Doc("a", "pflege", "2026-10-05T08:00:00", text)]
    if later:
        docs.append(Doc("b", "pflege", "2026-10-11T08:00:00", later))
    return V.verify(field, value, [{"doc_id": "a", "quote": quote}], docs, {}).status


def test_a_predicate_at_the_end_of_the_clause_negates_its_subject() -> None:
    text = "Eine Hinlauftendenz wird von der Bezugspflege und den Angehörigen übereinstimmend verneint."
    assert _verdict("runaway_risk", True, text, "Eine Hinlauftendenz wird") == "contradicted"
    text = "Eine Dialyse ist nach Rücksprache mit der Nephrologie derzeit nicht erforderlich."
    assert _verdict("dialysis", True, text, "Eine Dialyse ist nach Rücksprache") == "contradicted"


def test_plans_and_proposals_do_not_state_the_value() -> None:
    text = "Eine PEG-Anlage wurde besprochen und vorgeschlagen, die Entscheidung der Familie steht aus."
    assert _verdict("peg_tube", True, text, "Eine PEG-Anlage wurde besprochen") == "unsupported"
    text = "Verdacht auf beginnende Demenz, Abklärung ambulant."
    assert _verdict("cognition", "demenz", text, "beginnende Demenz") == "unsupported"


def test_removal_makes_an_earlier_statement_stale() -> None:
    v = _verdict(
        "urinary_catheter",
        True,
        "Suprapubischer Katheter liegt.",
        "Suprapubischer Katheter liegt",
        "Katheter heute entfernt, Miktion spontan.",
    )
    assert v == "conflict"


def test_partial_orientation_is_not_oriented() -> None:
    text = "Bekannte Demenz."
    assert (
        _verdict("cognition", "demenz", text, "Bekannte Demenz", "Heute nur zur Person orientiert, zeitlich nicht.")
        == "grounded"
    )
