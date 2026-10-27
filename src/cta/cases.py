"""Cases: a FHIR Bundle comes in, its identifiers are sealed by the gateway, its documents are pseudonymised once and
stored twice (original and pseudonymised, both encrypted with the tenant's key). Agent runs read only the pseudonymised
text; clinicians see the original."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import audit, guardrails
from .crypto import Keyring
from .db import DB, J
from .fhir import parse_bundle
from .gateway import Gateway
from .grounding import Doc


class CaseNotFound(LookupError):
    pass


@dataclass
class CaseView:
    case_id: str
    tenant: str
    token: str
    as_of: str
    docs: list[Doc]
    injections: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    replacements: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)  # documents whose pseudonymisation left a known identifier
    patient_sex: str = ""


class CaseStore:
    def __init__(self, db: DB, gateway: Gateway, keyring: Keyring):
        self.db, self.gw, self.keys = db, gateway, keyring

    def create(
        self,
        tenant: str,
        bundle: dict[str, Any],
        *,
        actor: str,
        as_of: dt.date | None = None,
        case_id: str | None = None,
    ) -> str:
        case_id = case_id or uuid.uuid4().hex[:16]
        as_of = as_of or dt.date.today()
        inc = parse_bundle(bundle, tenant, case_id, as_of)
        token = self.gw.seal(inc.identity)
        pseudo = self.gw.pseudonymize(tenant, case_id, token, [d.text for d in inc.documents])
        guards = guardrails.load()
        with self.db.tenant(tenant) as c:
            row = c.execute("SELECT retention_days FROM tenants WHERE id = %s", (tenant,)).fetchone()
            if row is None:
                raise CaseNotFound(f"unknown tenant {tenant}")
            days = int(row["retention_days"])
            ienc, inonce = self.keys.seal(tenant, f"{case_id}|identity", json.dumps(inc.identity, ensure_ascii=False))
            c.execute(
                "INSERT INTO cases (id, tenant_id, external_ref, as_of, identity_token, identity_enc, identity_nonce, patient_sex, retention_until)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    case_id,
                    tenant,
                    inc.external_ref,
                    as_of,
                    token,
                    ienc,
                    inonce,
                    inc.patient_sex,
                    as_of + dt.timedelta(days=days),
                ),
            )
            for d, p in zip(inc.documents, pseudo, strict=True):
                tenc, tnonce = self.keys.seal(tenant, f"{case_id}|{d.id}|text", d.text)
                penc, pnonce = self.keys.seal(tenant, f"{case_id}|{d.id}|pseudo", p.text)
                inj = guardrails.injection_spans(p.text, guards)
                c.execute(
                    "INSERT INTO documents (case_id, id, tenant_id, kind, title, authored_at, author_role, text_enc, text_nonce,"
                    " pseudo_enc, pseudo_nonce, replacements, injection_spans, leak_kinds)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        case_id,
                        d.id,
                        tenant,
                        d.kind,
                        d.title,
                        d.authored_at,
                        d.author_role,
                        tenc,
                        tnonce,
                        penc,
                        pnonce,
                        J(p.replacements),
                        J([list(s) for s in inj]),
                        J(p.leaks),
                    ),
                )
            audit.append(
                c,
                tenant,
                actor,
                "case.created",
                f"case/{case_id}",
                {
                    "documents": len(inc.documents),
                    "replaced": sum(len(p.replacements) for p in pseudo),
                    "blocked": [d.id for d, p in zip(inc.documents, pseudo, strict=True) if p.leaks],
                },
            )
        return case_id

    def load(self, tenant: str, case_id: str) -> CaseView:
        with self.db.tenant(tenant) as c:
            case = c.execute("SELECT * FROM cases WHERE id = %s", (case_id,)).fetchone()
            if case is None or case["purged_at"] is not None:
                raise CaseNotFound(case_id)
            rows = c.execute(
                "SELECT * FROM documents WHERE case_id = %s ORDER BY authored_at, id", (case_id,)
            ).fetchall()
        docs, inj, reps, blocked = [], {}, {}, []
        for r in rows:
            if r["leak_kinds"]:
                blocked.append(r["id"])
                continue
            text = self.keys.open(tenant, f"{case_id}|{r['id']}|pseudo", r["pseudo_enc"], r["pseudo_nonce"])
            docs.append(Doc(r["id"], r["kind"], r["authored_at"].replace(tzinfo=None).isoformat(), text))
            inj[r["id"]] = [tuple(s) for s in r["injection_spans"]]
            reps[r["id"]] = r["replacements"]
        return CaseView(
            case_id,
            tenant,
            case["identity_token"],
            case["as_of"].isoformat(),
            docs,
            inj,
            reps,
            blocked,
            case["patient_sex"] or "",
        )

    def originals(self, tenant: str, case_id: str) -> list[dict[str, Any]]:
        with self.db.tenant(tenant) as c:
            rows = c.execute(
                "SELECT * FROM documents WHERE case_id = %s ORDER BY authored_at, id", (case_id,)
            ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "title": r["title"],
                    "authored_at": r["authored_at"].isoformat(),
                    "author_role": r["author_role"],
                    "blocked": bool(r["leak_kinds"]),
                    "text": self.keys.open(tenant, f"{case_id}|{r['id']}|text", r["text_enc"], r["text_nonce"]),
                    "pseudo": self.keys.open(tenant, f"{case_id}|{r['id']}|pseudo", r["pseudo_enc"], r["pseudo_nonce"]),
                    "replacements": r["replacements"],
                    "injection_spans": r["injection_spans"],
                }
            )
        return out

    def purge_expired(self, tenant: str, today: dt.date, actor: str = "retention") -> int:
        """Crypto-shred and delete documents of cases past retention; the case row and audit trail stay."""
        with self.db.tenant(tenant) as c:
            rows = c.execute(
                "SELECT id FROM cases WHERE retention_until < %s AND purged_at IS NULL", (today,)
            ).fetchall()
            for r in rows:
                c.execute("DELETE FROM documents WHERE case_id = %s", (r["id"],))
                c.execute(
                    "UPDATE cases SET purged_at = now(), identity_enc = '', identity_nonce = '', identity_token = '' WHERE id = %s",
                    (r["id"],),
                )
                audit.append(c, tenant, actor, "case.purged", f"case/{r['id']}", {"reason": "retention"})
        return len(rows)
