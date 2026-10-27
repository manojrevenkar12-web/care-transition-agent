"""A case through the whole system: FHIR in, the real Go gateway, the simulated model, the verifier, review, release."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from cta import audit
from cta.drafts import ReviewError
from ctasim.world import fhir_bundle, generate_case

pytestmark = [pytest.mark.db, pytest.mark.gateway]

AS_OF = dt.date(2026, 10, 12)


def create(system: dict[str, Any], seed: int, tenant: str = "klinikum-nord") -> tuple[str, Any]:
    sim = generate_case(seed, tenant, AS_OF)
    case_id = system["cases"].create(
        tenant, fhir_bundle(sim), actor="sozialdienst@test", as_of=AS_OF, case_id=sim.case_id
    )
    return case_id, sim


def test_identifiers_never_reach_the_model_and_documents_are_encrypted(system: dict[str, Any]) -> None:
    case_id, sim = create(system, 2)
    view = system["cases"].load("klinikum-nord", case_id)
    pat = sim.identity["persons"][0]
    text = " ".join(d.text for d in view.docs)
    for ident in (
        pat["family"],
        pat["given"],
        sim.identity["kvnr"],
        sim.identity["case_numbers"][0],
        sim.identity["phones"][0],
    ):
        assert ident not in text, ident
    assert "«Patient»" in text
    with system["db"].admin() as c:
        raw = c.execute("SELECT text_enc FROM documents WHERE case_id = %s", (case_id,)).fetchone()
    assert pat["family"].encode() not in bytes(raw["text_enc"])


def test_a_draft_is_grounded_reviewed_and_released_by_a_clinician(system: dict[str, Any]) -> None:
    case_id, sim = create(system, 7)
    out = system["agent"].draft_profile("klinikum-nord", case_id, "sozialdienst@test")
    assert out["status"] == "completed" and out["draft_id"], out
    d = system["drafts"].get("klinikum-nord", out["draft_id"])
    statuses = {f["field"]: f["agent_status"] for f in d["fields"]}
    assert sum(s == "grounded" for s in statuses.values()) >= 8, statuses
    for f in d["fields"]:
        if f["agent_status"] in ("grounded", "conflict", "contradicted", "unsupported"):
            for e in f["evidence"]:
                assert e["start"] >= 0 and e["orig_start"] >= 0  # the UI can highlight it in the original document
    with pytest.raises(ReviewError):
        system["drafts"].release("klinikum-nord", out["draft_id"], "sozialdienst@test", "coordinator")
    assert d["blocking"], "nothing is released before review"
    system["drafts"].accept_grounded("klinikum-nord", out["draft_id"], "dr.weber@test")
    d = system["drafts"].get("klinikum-nord", out["draft_id"])
    for f in d["fields"]:
        if any(b["field"] == f["field"] for b in d["blocking"]):
            truth = sim.truth.get(f["field"]) if f["field"] != "summary" else "Patientin benötigt Pflege."
            if truth is None:
                truth = {
                    "enum": f["options"][0]["value"] if f["options"] else None,
                    "boolean": False,
                    "date": "2026-10-20",
                    "text": "keine Angabe",
                    "summary": "Kurzbeschreibung",
                }[f["type"]]
            system["drafts"].review(
                "klinikum-nord",
                out["draft_id"],
                f["field"],
                "edit" if f["agent_value"] is not None else "answer",
                "dr.weber@test",
                value=truth,
            )
    qr = system["drafts"].release("klinikum-nord", out["draft_id"], "dr.weber@test", "clinician")
    assert qr["resourceType"] == "QuestionnaireResponse" and qr["status"] == "completed"
    with system["db"].tenant("klinikum-nord") as c:
        ok, n = audit.verify(c, "klinikum-nord")
    assert ok and n >= 3


def test_another_tenant_sees_nothing(system: dict[str, Any]) -> None:
    case_id, _ = create(system, 3, "klinikum-nord")
    with system["db"].tenant("st-elisabeth") as c:
        assert c.execute("SELECT count(*) AS n FROM cases").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 0
    with pytest.raises(LookupError):
        system["cases"].load("st-elisabeth", case_id)


def test_out_of_scope_questions_never_reach_a_model(system: dict[str, Any]) -> None:
    case_id, _ = create(system, 4)
    out = system["agent"].chat("klinikum-nord", case_id, "Welche Dosis Morphin soll das Hospiz geben?", "pflege@test")
    assert out["kind"] == "refusal" and out["workflow"] == "out_of_scope"
    with system["db"].tenant("klinikum-nord") as c:
        run = c.execute("SELECT model_calls FROM runs WHERE id = %s", (out["run_id"],)).fetchone()
    assert run["model_calls"] == 0


def test_questions_are_answered_with_checked_quotes(system: dict[str, Any]) -> None:
    case_id, _ = create(system, 5)
    out = system["agent"].chat("klinikum-nord", case_id, "Was steht zur Mobilität?", "pflege@test")
    assert out["kind"] == "answer" and out["citations"], out
    assert out["status"] in ("verified", "unverified", "advice_held")


def test_the_audit_trail_cannot_be_edited(system: dict[str, Any]) -> None:
    create(system, 6)
    with pytest.raises(Exception), system["db"].admin() as c:  # noqa: B017
        c.execute("UPDATE audit SET actor = 'someone-else'")
