"""Drafts, clinician review and release. Every agent output is a draft: a clinician accepts, edits, answers or rejects
each field, and only a clinician can release. Release produces the FHIR QuestionnaireResponse and the pseudonymised
profile that providers receive. Each review action is an event (the online evaluation reads them) and an audit entry."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from . import audit
from . import observability as obs
from .agent.tools import DraftRecorder
from .cases import CaseStore
from .db import DB, J
from .fhir import questionnaire_response
from .gateway import to_original_span
from .grounding import FLAGGED, Verifier
from .profile import InvalidValue, Profile, label, normalize

REVIEWED = {"accepted", "edited", "answered"}


class ReviewError(ValueError):
    pass


class Drafts:
    def __init__(self, db: DB, profile: Profile, cases: CaseStore, verifier: Verifier):
        self.db, self.profile, self.cases, self.v = db, profile, cases, verifier

    def save(
        self, tenant: str, case_id: str, run_id: str, rec: DraftRecorder, prompt_version: str, model: str, actor: str
    ) -> str:
        draft_id = str(uuid.uuid4())
        rows: list[tuple[str, Any, str, str | None, list[dict[str, Any]], list[dict[str, Any]], str | None]] = []
        for f in self.profile.fields:
            if f.type == "summary":
                status = (
                    "grounded"
                    if rec.summary and not rec.summary_issues
                    else ("missing" if not rec.summary else "unsupported")
                )
                rows.append((f.id, rec.summary, status, ", ".join(rec.summary_issues) or None, [], [], None))
            elif f.id in rec.fields:
                a = rec.fields[f.id]
                rows.append(
                    (
                        f.id,
                        a.value,
                        a.verdict.status,
                        a.verdict.reason,
                        [e.to_dict() for e in a.verdict.evidence],
                        [e.to_dict() for e in a.verdict.counter],
                        None,
                    )
                )
            elif f.id in rec.unknown:
                u = rec.unknown[f.id]
                rows.append(
                    (
                        f.id,
                        None,
                        u.verdict.status,
                        u.verdict.reason,
                        [],
                        [e.to_dict() for e in u.verdict.counter],
                        u.question,
                    )
                )
            else:
                chk = self.v.check_unknown(f.id, rec.case.docs, rec.case.injections)
                rows.append(
                    (
                        f.id,
                        None,
                        "missing" if chk.status == "unknown" else "unknown_but_mentioned",
                        "the agent did not record this field",
                        [],
                        [e.to_dict() for e in chk.counter],
                        None,
                    )
                )
        with self.db.tenant(tenant) as c:
            c.execute("UPDATE drafts SET status = 'superseded' WHERE case_id = %s AND status = 'draft'", (case_id,))
            c.execute(
                "INSERT INTO drafts (id, tenant_id, case_id, run_id, status, profile_version, prompt_version, model)"
                " VALUES (%s,%s,%s,%s,'draft',%s,%s,%s)",
                (draft_id, tenant, case_id, run_id, self.profile.version, prompt_version, model),
            )
            for fid, value, status, reason, ev, counter, question in rows:
                c.execute(
                    "INSERT INTO draft_fields (draft_id, tenant_id, field, agent_value, agent_status, reason, evidence, counter, question)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (draft_id, tenant, fid, J(value), status, reason, J(ev), J(counter), question),
                )
                obs.VERDICTS.labels(fid, status).inc()
            audit.append(
                c,
                tenant,
                actor,
                "draft.created",
                f"draft/{draft_id}",
                {"case": case_id, "run": run_id, "flagged": sum(1 for r in rows if r[2] in FLAGGED)},
            )
        return draft_id

    # ---- reading ------------------------------------------------------------------------------------------------
    def get(self, tenant: str, draft_id: str) -> dict[str, Any]:
        with self.db.tenant(tenant) as c:
            d = c.execute("SELECT * FROM drafts WHERE id = %s", (draft_id,)).fetchone()
            if d is None:
                raise ReviewError("no such draft")
            fields = {r["field"]: r for r in c.execute("SELECT * FROM draft_fields WHERE draft_id = %s", (draft_id,))}
            reps = {
                r["id"]: r["replacements"]
                for r in c.execute("SELECT id, replacements FROM documents WHERE case_id = %s", (d["case_id"],))
            }
        out_fields = []
        for f in self.profile.fields:
            r = fields[f.id]
            final = r["final_value"] if r["review"] in REVIEWED else r["agent_value"]
            ev = [self._with_original(e, reps) for e in r["evidence"]]
            counter = [self._with_original(e, reps) for e in r["counter"]]
            out_fields.append(
                {
                    "field": f.id,
                    "section": f.section,
                    "label": {"de": f.label_de, "en": f.label_en},
                    "type": f.type,
                    "options": [{"value": o, "label": label(f, o)} for o in f.options],
                    "required": f.required,
                    "required_if": f.required_if,
                    "severity": f.severity,
                    "agent_value": r["agent_value"],
                    "agent_label": label(f, r["agent_value"]),
                    "agent_status": r["agent_status"],
                    "reason": r["reason"],
                    "evidence": ev,
                    "counter": counter,
                    "question": r["question"],
                    "review": r["review"],
                    "final_value": r["final_value"],
                    "final_label": label(f, final) if final is not None else "",
                    "reviewed_by": r["reviewed_by"],
                }
            )
        d = dict(d)
        d["fields"] = out_fields
        d["blocking"] = self._blocking(d["status"], out_fields)
        for k in ("created_at", "released_at"):
            d[k] = d[k].isoformat() if d.get(k) else None
        d["id"], d["run_id"] = str(d["id"]), str(d["run_id"]) if d["run_id"] else None
        return d

    @staticmethod
    def _with_original(e: dict[str, Any], reps: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        e = dict(e)
        if e.get("start", -1) >= 0 and e.get("doc_id") in reps:
            e["orig_start"], e["orig_end"] = to_original_span(e["start"], e["end"], reps[e["doc_id"]])
        return e

    def _blocking(self, status: str, fields: list[dict[str, Any]]) -> list[dict[str, str]]:
        if status != "draft":
            return [{"field": "", "reason": f"draft is {status}"}]
        values = {f["field"]: (f["final_value"] if f["review"] in REVIEWED else None) for f in fields}
        out = []
        for f in fields:
            pf = self.profile.get(f["field"])
            required = self.profile.is_required(pf, values)
            if f["review"] == "pending" and (required or f["agent_value"] is not None):
                why = "needs a decision" if f["agent_value"] is not None else "needs an answer"
                out.append({"field": f["field"], "reason": why})
            elif required and f["review"] == "rejected":
                out.append({"field": f["field"], "reason": "required: enter the right value"})
        return out

    # ---- review -------------------------------------------------------------------------------------------------
    def review(
        self,
        tenant: str,
        draft_id: str,
        field_id: str,
        action: str,
        actor: str,
        value: Any = None,
        seconds: float | None = None,
    ) -> dict[str, Any]:
        f = self.profile.get(field_id)
        if action not in ("accept", "edit", "answer", "reject"):
            raise ReviewError(f"unknown action {action}")
        with self.db.tenant(tenant) as c:
            d = c.execute("SELECT * FROM drafts WHERE id = %s FOR UPDATE", (draft_id,)).fetchone()
            if d is None or d["status"] != "draft":
                raise ReviewError("only an open draft can be reviewed")
            r = c.execute(
                "SELECT * FROM draft_fields WHERE draft_id = %s AND field = %s", (draft_id, field_id)
            ).fetchone()
            if r is None:
                raise ReviewError(f"the draft has no field {field_id}")
            if action == "accept":
                if r["agent_value"] is None:
                    raise ReviewError("there is no value to accept; answer instead")
                final, review = r["agent_value"], "accepted"
            elif action in ("edit", "answer"):
                try:
                    final = normalize(f, value)
                except InvalidValue as e:
                    raise ReviewError(str(e)) from e
                review = "edited" if action == "edit" else "answered"
                if action == "edit" and r["agent_value"] is not None and final == r["agent_value"]:
                    review = "accepted"
            else:
                final, review = None, "rejected"
            c.execute(
                "UPDATE draft_fields SET review = %s, final_value = %s, reviewed_by = %s, reviewed_at = now()"
                " WHERE draft_id = %s AND field = %s",
                (review, J(final), actor, draft_id, field_id),
            )
            c.execute(
                "INSERT INTO review_events (tenant_id, draft_id, field, action, actor, agent_status, agent_value, final_value,"
                " prompt_version, model, seconds_on_field) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    tenant,
                    draft_id,
                    field_id,
                    review,
                    actor,
                    r["agent_status"],
                    J(r["agent_value"]),
                    J(final),
                    d["prompt_version"],
                    d["model"],
                    seconds,
                ),
            )
            audit.append(
                c, tenant, actor, f"field.{review}", f"draft/{draft_id}/{field_id}", {"agent_status": r["agent_status"]}
            )
        obs.REVIEWS.labels(review, r["agent_status"]).inc()
        return {"field": field_id, "review": review, "final_value": final}

    def accept_grounded(self, tenant: str, draft_id: str, actor: str) -> int:
        """Accept every field the verifier found grounded and nobody has touched yet (one click, one audit entry each)."""
        d = self.get(tenant, draft_id)
        n = 0
        for f in d["fields"]:
            if f["review"] == "pending" and f["agent_status"] == "grounded" and f["agent_value"] is not None:
                self.review(tenant, draft_id, f["field"], "accept", actor)
                n += 1
        return n

    def release(self, tenant: str, draft_id: str, actor: str, role: str) -> dict[str, Any]:
        if role != "clinician":
            raise ReviewError("only a clinician can release a profile")
        d = self.get(tenant, draft_id)
        if d["blocking"]:
            raise ReviewError("not ready: " + ", ".join(f"{b['field']} ({b['reason']})" for b in d["blocking"]))
        values = {f["field"]: f["final_value"] for f in d["fields"] if f["review"] in REVIEWED}
        now = dt.datetime.now(dt.UTC).isoformat()
        qr = questionnaire_response(self.profile, d["case_id"], values, actor, now)
        with self.db.tenant(tenant) as c:
            c.execute(
                "UPDATE drafts SET status = 'released', released_at = now(), released_by = %s, fhir = %s WHERE id = %s AND status = 'draft'",
                (actor, J(qr), draft_id),
            )
            audit.append(c, tenant, actor, "draft.released", f"draft/{draft_id}", {"fields": len(values)})
        obs.RELEASES.labels(d["prompt_version"] or "").inc()
        return qr

    def latest(self, tenant: str, case_id: str) -> str | None:
        with self.db.tenant(tenant) as c:
            r = c.execute(
                "SELECT id FROM drafts WHERE case_id = %s AND status IN ('draft','released') ORDER BY created_at DESC LIMIT 1",
                (case_id,),
            ).fetchone()
        return str(r["id"]) if r else None
