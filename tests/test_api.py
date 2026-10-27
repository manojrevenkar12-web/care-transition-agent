"""The HTTP API: authentication, role permissions, tenant isolation, and a case from import to release."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cta.api import Services, create_app
from ctasim.world import fhir_bundle, generate_case

pytestmark = [pytest.mark.db, pytest.mark.gateway]

TOKENS = {
    "t-clin": {"user": "dr.weber", "tenant": "klinikum-nord", "role": "clinician"},
    "t-coord": {"user": "sozialdienst.kaya", "tenant": "klinikum-nord", "role": "coordinator"},
    "t-qual": {"user": "ml.team", "tenant": "klinikum-nord", "role": "quality"},
    "t-other": {"user": "dr.lang", "tenant": "st-elisabeth", "role": "clinician"},
}


def H(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def api(system: dict[str, Any], keyring: Any, tmp_path: Any) -> TestClient:
    s = Services(system["db"], system["gw"], keyring, TOKENS)
    return TestClient(create_app(s, static_dir=tmp_path))


def import_case(api: TestClient, seed: int, token: str = "t-coord") -> tuple[str, Any]:
    sim = generate_case(seed, "klinikum-nord", dt.date(2026, 10, 12))
    r = api.post("/api/cases", json=fhir_bundle(sim), headers=H(token))
    assert r.status_code == 201, r.text
    return r.json()["case_id"], sim


def test_requests_need_a_known_token(api: TestClient) -> None:
    assert api.get("/api/cases").status_code == 401
    assert api.get("/api/cases", headers=H("nope")).status_code == 401
    me = api.get("/api/me", headers=H("t-clin")).json()
    assert me["role"] == "clinician" and me["tenant"] == "klinikum-nord"
    assert api.get("/healthz").json() == {"status": "ok"}
    assert api.get("/readyz").status_code == 200
    assert "cta_runs_total" in api.get("/metrics").text or api.get("/metrics").status_code == 200


def test_bad_bundles_are_rejected_with_a_reason(api: TestClient) -> None:
    r = api.post("/api/cases", content=b"{not json", headers=H("t-coord"))
    assert r.status_code == 422 and "not JSON" in r.json()["detail"]
    r = api.post("/api/cases", json={"resourceType": "Patient"}, headers=H("t-coord"))
    assert r.status_code == 422


def test_from_import_to_release_over_http(api: TestClient) -> None:
    case_id, _ = import_case(api, 11)
    cases = api.get("/api/cases", headers=H("t-clin")).json()
    assert [c["id"] for c in cases] == [case_id] and cases[0]["documents"] >= 4

    docs = api.get(f"/api/cases/{case_id}/documents", headers=H("t-clin")).json()
    assert all("«" not in d["text"] for d in docs) and any("«Patient»" in d["pseudo"] for d in docs)

    run = api.post(f"/api/cases/{case_id}/drafts", headers=H("t-coord"))
    assert run.status_code == 201, run.text
    draft_id = run.json()["draft_id"]
    trace = api.get(f"/api/runs/{run.json()['run_id']}", headers=H("t-qual")).json()
    assert trace["steps"] and all("quote" not in s["detail"] for s in trace["steps"])

    d = api.get(f"/api/drafts/{draft_id}", headers=H("t-clin")).json()
    assert d["blocking"]
    assert api.post(f"/api/drafts/{draft_id}/release", headers=H("t-clin")).status_code == 409
    accepted = api.post(f"/api/drafts/{draft_id}/accept-grounded", headers=H("t-clin")).json()["accepted"]
    assert accepted >= 8

    d = api.get(f"/api/drafts/{draft_id}", headers=H("t-clin")).json()
    for b in d["blocking"]:
        f = next(x for x in d["fields"] if x["field"] == b["field"])
        value = {
            "enum": f["options"][0]["value"] if f["options"] else None,
            "boolean": False,
            "date": "2026-10-20",
            "text": "keine Angabe",
            "summary": "Patientin benötigt Kurzzeitpflege.",
        }[f["type"]]
        action = "edit" if f["agent_value"] is not None else "answer"
        r = api.post(
            f"/api/drafts/{draft_id}/fields/{f['field']}",
            json={"action": action, "value": value, "seconds": 4},
            headers=H("t-clin"),
        )
        assert r.status_code == 200, r.text
    bad = api.post(
        f"/api/drafts/{draft_id}/fields/oxygen", json={"action": "edit", "value": "vielleicht"}, headers=H("t-clin")
    )
    assert bad.status_code == 409 and "true or false" in bad.json()["detail"]

    assert api.post(f"/api/drafts/{draft_id}/release", headers=H("t-coord")).status_code == 403
    qr = api.post(f"/api/drafts/{draft_id}/release", headers=H("t-clin"))
    assert qr.status_code == 200, qr.text
    assert qr.json()["resourceType"] == "QuestionnaireResponse" and qr.json()["status"] == "completed"
    assert api.get(f"/api/drafts/{draft_id}", headers=H("t-clin")).json()["status"] == "released"

    online = api.get("/api/quality/online", headers=H("t-qual")).json()
    assert online["events"] >= accepted
    assert api.get("/api/audit/verify", headers=H("t-qual")).json()["intact"] is True


def test_roles_limit_what_each_person_sees(api: TestClient) -> None:
    case_id, _ = import_case(api, 12)
    assert api.get(f"/api/cases/{case_id}/documents", headers=H("t-qual")).status_code == 403
    assert api.post(f"/api/cases/{case_id}/drafts", headers=H("t-qual")).status_code == 403
    assert api.get("/api/quality/evals", headers=H("t-clin")).status_code == 403
    assert (
        api.post(
            "/api/prompts/deploy",
            json={"prompt": "profile_drafter", "version": "v2", "model": "sim-careful", "share": 1},
            headers=H("t-clin"),
        ).status_code
        == 403
    )
    draft_id = api.post(f"/api/cases/{case_id}/drafts", headers=H("t-coord")).json()["draft_id"]
    d = api.get(f"/api/drafts/{draft_id}", headers=H("t-qual")).json()
    assert all("quote" not in e for f in d["fields"] for e in f["evidence"]), "the AI team never sees document text"


def test_another_hospital_sees_nothing(api: TestClient) -> None:
    case_id, _ = import_case(api, 13)
    assert api.get("/api/cases", headers=H("t-other")).json() == []
    assert api.get(f"/api/cases/{case_id}", headers=H("t-other")).status_code == 404
    assert api.get(f"/api/cases/{case_id}/documents", headers=H("t-other")).status_code == 404
    assert api.post(f"/api/cases/{case_id}/drafts", headers=H("t-other")).status_code == 404


def test_chat_and_out_of_scope_questions(api: TestClient) -> None:
    case_id, _ = import_case(api, 14)
    r = api.post(
        f"/api/cases/{case_id}/chat", json={"message": "Welche Dosis Furosemid soll ich geben?"}, headers=H("t-clin")
    )
    assert r.status_code == 200 and r.json()["kind"] == "refusal"
    r = api.post(
        f"/api/cases/{case_id}/chat", json={"message": "Braucht die Patientin Sauerstoff?"}, headers=H("t-clin")
    )
    assert r.status_code == 200, r.text
    hist = api.get(f"/api/cases/{case_id}/chat", headers=H("t-clin")).json()
    assert [m["role"] for m in hist][:2] == ["user", "assistant"]
    answer = next(m for m in hist if m["role"] == "assistant")
    assert (
        api.post(f"/api/chat/{answer['id']}/feedback", json={"feedback": "helpful"}, headers=H("t-clin")).status_code
        == 200
    )


def test_prompt_canary_deploy_and_withdraw(api: TestClient) -> None:
    body = {"prompt": "profile_drafter", "version": "v1", "model": "sim-careful", "share": 0.2}
    rows = api.post("/api/prompts/deploy", json=body, headers=H("t-qual")).json()
    assert any(r["version"] == "v1" and r["share"] == pytest.approx(0.2) for r in rows)
    assert api.post("/api/prompts/deploy", json={**body, "version": "v9"}, headers=H("t-qual")).status_code == 404
    rows = api.post(
        "/api/prompts/withdraw", json={"prompt": "profile_drafter", "version": "v1"}, headers=H("t-qual")
    ).json()
    assert not any(r["version"] == "v1" for r in rows)
    table = api.get("/api/prompts", headers=H("t-qual")).json()
    assert {v["version"] for v in table["files"]["profile_drafter"]} >= {"v1", "v2"}
