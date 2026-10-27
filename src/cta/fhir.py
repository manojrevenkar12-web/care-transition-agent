"""FHIR R4 in and out. In: the transaction Bundle a hospital information system sends when discharge planning starts
(Patient, RelatedPerson, Practitioner, Encounter, DocumentReference with text attachments). Out: the released profile as
a QuestionnaireResponse, and the pseudonymised version that goes to providers."""

from __future__ import annotations

import base64
import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from .profile import Profile, label, questionnaire

KVID = "http://fhir.de/sid/gkv/kvid-10"


class BundleError(ValueError):
    pass


@dataclass
class IncomingDocument:
    id: str
    kind: str
    title: str
    authored_at: str
    author_role: str
    text: str


@dataclass
class IncomingCase:
    external_ref: str
    identity: dict[str, Any]
    documents: list[IncomingDocument] = field(default_factory=list)
    patient_sex: str = ""


def _name(n: dict[str, Any]) -> tuple[str, str]:
    return " ".join(n.get("given", [])), n.get("family", "")


def parse_bundle(bundle: dict[str, Any], tenant: str, case_id: str, as_of: dt.date) -> IncomingCase:
    if bundle.get("resourceType") != "Bundle":
        raise BundleError("a FHIR Bundle is expected")
    res = [e.get("resource", {}) for e in bundle.get("entry", [])]
    patients = [r for r in res if r.get("resourceType") == "Patient"]
    if len(patients) != 1:
        raise BundleError("the Bundle must contain exactly one Patient")
    pat = patients[0]
    persons: list[dict[str, Any]] = []
    phones: list[str] = []
    emails: list[str] = []
    for n in pat.get("name", [])[:1]:
        g, f = _name(n)
        persons.append({"role": "patient", "given": g, "family": f})
    for t in pat.get("telecom", []):
        (phones if t.get("system") == "phone" else emails if t.get("system") == "email" else []).append(
            t.get("value", "")
        )
    kvnr = next((i["value"] for i in pat.get("identifier", []) if i.get("system") == KVID), "")
    addresses = [
        {"street": " ".join(a.get("line", [])), "postal_code": a.get("postalCode", ""), "city": a.get("city", "")}
        for a in pat.get("address", [])
    ]
    case_numbers: list[str] = []
    external_ref = ""
    for r in res:
        rt = r.get("resourceType")
        if rt == "RelatedPerson":
            for n in r.get("name", [])[:1]:
                g, f = _name(n)
                persons.append({"role": "relative", "given": g, "family": f})
            for t in r.get("telecom", []):
                (phones if t.get("system") == "phone" else emails if t.get("system") == "email" else []).append(
                    t.get("value", "")
                )
        elif rt == "Practitioner":
            for n in r.get("name", [])[:1]:
                g, f = _name(n)
                persons.append({"role": "physician", "given": g, "family": f})
        elif rt == "Encounter":
            case_numbers += [i["value"] for i in r.get("identifier", []) if i.get("value")]
            external_ref = external_ref or r.get("id", "")
    docs = []
    for r in res:
        if r.get("resourceType") != "DocumentReference":
            continue
        att = (r.get("content") or [{}])[0].get("attachment", {})
        if not str(att.get("contentType", "")).startswith("text/plain"):
            raise BundleError(
                f"DocumentReference {r.get('id')}: only text/plain attachments are accepted (OCR happens upstream)"
            )
        try:
            text = base64.b64decode(att.get("data", "")).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as e:
            raise BundleError(f"DocumentReference {r.get('id')}: attachment is not UTF-8 text") from e
        docs.append(
            IncomingDocument(
                id=str(r.get("id", "")),
                kind=((r.get("category") or [{}])[0].get("text") or "dokument"),
                title=(r.get("type") or {}).get("text") or att.get("title") or "Dokument",
                authored_at=str(r.get("date", "")) or dt.datetime.now(dt.UTC).isoformat(),
                author_role=((r.get("author") or [{}])[0].get("display") or ""),
                text=text,
            )
        )
    if not docs:
        raise BundleError("the Bundle contains no documents")
    # short, meaningless ids in time order: the model cites "d3", not a hospital system's resource id
    docs.sort(key=lambda d: d.authored_at)
    for i, d in enumerate(docs, 1):
        d.id = f"d{i}"
    identity = {
        "tenant": tenant,
        "case": case_id,
        "as_of": as_of.isoformat(),
        "persons": persons,
        "birth_date": pat.get("birthDate", ""),
        "kvnr": kvnr,
        "case_numbers": case_numbers,
        "addresses": addresses,
        "phones": [p for p in phones if p],
        "emails": [e for e in emails if e],
    }
    sex = {"female": "f", "male": "m"}.get(pat.get("gender", ""), "")
    return IncomingCase(external_ref=external_ref, identity=identity, documents=docs, patient_sex=sex)


def questionnaire_response(
    profile: Profile, case_id: str, values: dict[str, Any], released_by: str, released_at: str
) -> dict[str, Any]:
    q = questionnaire(profile)
    items = []
    for s in profile.sections:
        group: dict[str, Any] = {"linkId": s["id"], "item": []}
        for f in (x for x in profile.fields if x.section == s["id"]):
            v = values.get(f.id)
            if v is None:
                continue
            if f.type == "enum":
                ans: dict[str, Any] = {"valueCoding": {"code": v, "display": label(f, v)}}
            elif f.type == "boolean":
                ans = {"valueBoolean": bool(v)}
            elif f.type == "date":
                ans = {"valueDate": v}
            else:
                ans = {"valueString": v}
            group["item"].append({"linkId": f.id, "text": f.label_de, "answer": [ans]})
        if group["item"]:
            items.append(group)
    return {
        "resourceType": "QuestionnaireResponse",
        "status": "completed",
        "questionnaire": q["url"] + "|" + q["version"],
        "subject": {"reference": f"Patient/{case_id}"},
        "authored": released_at,
        "author": {"display": released_by},
        "item": items,
    }
