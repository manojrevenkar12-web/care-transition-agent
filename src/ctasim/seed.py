"""Fill a running console with simulated cases: imported over the API as a coordinator would, drafted, and some of them
reviewed and released by a clinician, so every screen has something on it. Only for the local stack."""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from .world import fhir_bundle, generate_case


def seed(api: str, n: int = 8, seed0: int = 4000, as_of: dt.date | None = None) -> dict[str, Any]:
    as_of = as_of or dt.date(2026, 10, 12)
    coord = {"Authorization": "Bearer demo-coordinator"}
    clin = {"Authorization": "Bearer demo-clinician"}
    qual = {"Authorization": "Bearer demo-quality"}
    c = httpx.Client(base_url=api.rstrip("/"), timeout=120)
    c.post(
        "/api/prompts/deploy",
        headers=qual,
        json={"prompt": "profile_drafter", "version": "v1", "model": "sim-careful", "share": 0.2},
    )
    out: dict[str, Any] = {"cases": [], "released": 0, "reviewed": 0}
    for i in range(n):
        sim = generate_case(seed0 + i, "klinikum-nord", as_of)
        r = c.post("/api/cases", headers=coord, json=fhir_bundle(sim))
        r.raise_for_status()
        case_id = r.json()["case_id"]
        out["cases"].append(case_id)
        if i == n - 1:
            continue  # one case without a draft
        d = c.post(f"/api/cases/{case_id}/drafts", headers=coord)
        d.raise_for_status()
        draft_id = d.json()["draft_id"]
        if i % 3 == 0:
            c.post(f"/api/drafts/{draft_id}/accept-grounded", headers=clin).raise_for_status()
            out["reviewed"] += 1
            draft = c.get(f"/api/drafts/{draft_id}", headers=clin).json()
            for b in draft["blocking"]:
                f = next(x for x in draft["fields"] if x["field"] == b["field"])
                truth = sim.truth.get(f["field"])
                if f["type"] == "summary":
                    truth = "Patientin benötigt eine weitere Versorgung nach dem Krankenhausaufenthalt."
                if truth is None:
                    continue
                action = "edit" if f["agent_value"] is not None else "answer"
                c.post(
                    f"/api/drafts/{draft_id}/fields/{f['field']}",
                    headers=clin,
                    json={"action": action, "value": truth, "seconds": 6 + (i % 5) * 3},
                )
            if c.post(f"/api/drafts/{draft_id}/release", headers=clin).status_code == 200:
                out["released"] += 1
    c.post(
        f"/api/cases/{out['cases'][1]}/chat", headers=clin, json={"message": "Ist eine MRSA-Besiedlung dokumentiert?"}
    )
    c.post(
        f"/api/cases/{out['cases'][1]}/chat",
        headers=clin,
        json={"message": "Welche Dosis Furosemid soll die Einrichtung geben?"},
    )
    return out
