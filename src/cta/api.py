"""The HTTP API and the clinician console. Every request carries a bearer token that maps to one user, one hospital
(tenant) and one role (config/access.yaml); every query runs inside that tenant's row-level-security scope.

Roles decide what a person sees: clinicians and coordinators see the original documents, the AI team sees quality,
traces and prompts but never document text. Only a clinician releases a profile."""

from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from . import audit, config, prompts
from . import evaluation as E
from . import observability as obs
from .agent.runner import Agent
from .cases import CaseNotFound, CaseStore
from .crypto import Keyring
from .db import DB
from .drafts import Drafts, ReviewError
from .fhir import BundleError
from .gateway import Gateway, GatewayError
from .grounding import Verifier
from .profile import load as load_profile
from .profile import questionnaire


@dataclass(frozen=True)
class User:
    id: str
    tenant: str
    role: str
    permissions: frozenset[str]


class Services:
    def __init__(self, db: DB, gw: Gateway, keyring: Keyring, tokens: dict[str, dict[str, str]]):
        self.db, self.gw = db, gw
        self.profile = load_profile()
        self.verifier = Verifier(self.profile)
        self.cases = CaseStore(db, gw, keyring)
        self.drafts = Drafts(db, self.profile, self.cases, self.verifier)
        self.agent = Agent(db, gw, self.cases, self.drafts, self.profile, self.verifier)
        access = config.load("access")
        self.roles = {r: frozenset(p) for r, p in access["roles"].items()}
        self.max_bundle = int(access["max_bundle_bytes"])
        self.users: dict[str, User] = {}
        for token, u in tokens.items():
            if u["role"] not in self.roles:
                raise ValueError(f"unknown role {u['role']}")
            self.users[token] = User(u["user"], u["tenant"], u["role"], self.roles[u["role"]])


# ---- request bodies ------------------------------------------------------------------------------------------------
class ReviewBody(BaseModel):
    action: str = Field(pattern="^(accept|edit|answer|reject)$")
    value: Any = None
    seconds: float | None = Field(default=None, ge=0, le=3600)


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class DeployBody(BaseModel):
    prompt: str
    version: str
    model: str
    share: float = Field(gt=0, le=1)
    scope: str = Field(default="tenant", pattern="^(tenant|all)$")


class WithdrawBody(BaseModel):
    prompt: str
    version: str
    scope: str = Field(default="tenant", pattern="^(tenant|all)$")


class FeedbackBody(BaseModel):
    feedback: str = Field(pattern="^(helpful|wrong|incomplete)$")


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, dt.datetime | dt.date) else v


def _row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (str(v) if k.endswith("id") and v is not None and not isinstance(v, str) else _iso(v)) for k, v in r.items()
    }


def create_app(services: Services | None = None, static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="care-transition-agent", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    state: dict[str, Services] = {}

    def svc() -> Services:
        if "s" not in state:
            if services is not None:
                state["s"] = services
            else:
                tokens = json.loads(os.environ.get(config.load("access")["tokens_env"], "{}"))
                state["s"] = Services(DB(), Gateway(), Keyring.from_env(), tokens)
        return state["s"]

    def user(request: Request) -> User:
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
        u = svc().users.get(token)
        if u is None:
            raise HTTPException(401, "sign in: a valid bearer token is required")
        return u

    def need(permission: str) -> Callable[[User], User]:
        def check(u: User = Depends(user)) -> User:
            if permission not in u.permissions:
                raise HTTPException(403, f"your role ({u.role}) may not {permission.replace('.', ' ')}")
            return u

        return check

    # ---- errors ----------------------------------------------------------------------------------------------------
    @app.exception_handler(CaseNotFound)
    def _nf(_: Request, e: CaseNotFound) -> JSONResponse:
        return JSONResponse({"detail": f"no case {e}"}, 404)

    @app.exception_handler(ReviewError)
    def _re(_: Request, e: ReviewError) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, 409)

    @app.exception_handler(BundleError)
    def _be(_: Request, e: BundleError) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, 422)

    @app.exception_handler(GatewayError)
    def _ge(_: Request, e: GatewayError) -> JSONResponse:
        obs.event("api.gateway_error", kind=e.kind, status=e.status)
        return JSONResponse({"detail": f"model gateway: {e.kind}", "kind": e.kind}, 502)

    # ---- health and metrics ----------------------------------------------------------------------------------------
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        s = svc()
        checks: dict[str, str] = {}
        try:
            with s.db.admin() as c:
                c.execute("SELECT 1")
            checks["database"] = "ok"
        except Exception as e:  # readiness reports, it does not raise
            checks["database"] = type(e).__name__
        try:
            s.gw.health()
            checks["gateway"] = "ok"
        except Exception as e:
            checks["gateway"] = type(e).__name__
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"ready": ok, **checks}, 200 if ok else 503)

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(obs.REGISTRY), media_type=CONTENT_TYPE_LATEST)

    # ---- who am I, the profile ----------------------------------------------------------------------------------
    @app.get("/api/me")
    def me(u: User = Depends(user)) -> dict[str, Any]:
        with svc().db.admin() as c:
            t = c.execute("SELECT name FROM tenants WHERE id = %s", (u.tenant,)).fetchone()
        return {
            "user": u.id,
            "tenant": u.tenant,
            "tenant_name": t["name"] if t else u.tenant,
            "role": u.role,
            "permissions": sorted(u.permissions),
        }

    @app.get("/api/profile")
    def profile(u: User = Depends(user)) -> dict[str, Any]:
        return questionnaire()

    # ---- cases --------------------------------------------------------------------------------------------------
    @app.get("/api/cases")
    def list_cases(u: User = Depends(need("cases.read")), limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with svc().db.tenant(u.tenant) as c:
            rows = c.execute(
                """
                SELECT c.id, c.external_ref, c.as_of, c.created_at, c.status, c.patient_sex,
                       (SELECT count(*) FROM documents d WHERE d.case_id = c.id) AS documents,
                       (SELECT count(*) FROM documents d WHERE d.case_id = c.id AND d.leak_kinds <> '[]') AS blocked,
                       dr.id AS draft_id, dr.status AS draft_status, dr.created_at AS draft_at,
                       (SELECT count(*) FROM draft_fields f WHERE f.draft_id = dr.id AND f.review = 'pending') AS pending,
                       (SELECT count(*) FROM draft_fields f WHERE f.draft_id = dr.id
                          AND f.agent_status NOT IN ('grounded','missing') AND f.review = 'pending') AS flagged
                FROM cases c
                LEFT JOIN LATERAL (SELECT * FROM drafts d WHERE d.case_id = c.id AND d.status IN ('draft','released')
                                   ORDER BY created_at DESC LIMIT 1) dr ON true
                WHERE c.purged_at IS NULL
                ORDER BY c.created_at DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [_row(r) for r in rows]

    @app.post("/api/cases", status_code=201)
    async def import_case(request: Request, u: User = Depends(need("cases.import"))) -> dict[str, Any]:
        body = await request.body()
        if len(body) > svc().max_bundle:
            raise HTTPException(413, "the bundle is too large")
        try:
            bundle = json.loads(body)
        except json.JSONDecodeError as e:
            raise HTTPException(422, f"not JSON: {e.msg}") from e
        case_id = svc().cases.create(u.tenant, bundle, actor=u.id)
        return {"case_id": case_id}

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str, u: User = Depends(need("cases.read"))) -> dict[str, Any]:
        s = svc()
        with s.db.tenant(u.tenant) as c:
            r = c.execute(
                "SELECT id, external_ref, as_of, created_at, status, patient_sex, retention_until FROM cases"
                " WHERE id = %s AND purged_at IS NULL",
                (case_id,),
            ).fetchone()
            if r is None:
                raise CaseNotFound(case_id)
            docs = c.execute(
                "SELECT id, kind, title, authored_at, author_role, leak_kinds,"
                " jsonb_array_length(replacements) AS replaced, jsonb_array_length(injection_spans) AS injections"
                " FROM documents WHERE case_id = %s ORDER BY authored_at, id",
                (case_id,),
            ).fetchall()
            drafts = c.execute(
                "SELECT id, status, prompt_version, model, created_at, released_at, released_by FROM drafts"
                " WHERE case_id = %s ORDER BY created_at DESC",
                (case_id,),
            ).fetchall()
        return {**_row(r), "documents": [_row(d) for d in docs], "drafts": [_row(d) for d in drafts]}

    @app.get("/api/cases/{case_id}/documents")
    def documents(case_id: str, u: User = Depends(need("documents.original"))) -> list[dict[str, Any]]:
        """Each document as written and as the model saw it, with the replaced spans and AI-addressed spans."""
        docs = svc().cases.originals(u.tenant, case_id)
        if not docs:
            raise CaseNotFound(case_id)
        with svc().db.tenant(u.tenant) as c:
            audit.append(c, u.tenant, u.id, "documents.read", f"case/{case_id}", {"documents": len(docs)})
        return docs

    # ---- drafts -------------------------------------------------------------------------------------------------
    @app.post("/api/cases/{case_id}/drafts", status_code=201)
    def run_draft(case_id: str, u: User = Depends(need("drafts.run"))) -> dict[str, Any]:
        svc().cases.load(u.tenant, case_id)
        return svc().agent.draft_profile(u.tenant, case_id, u.id)

    @app.get("/api/drafts/{draft_id}")
    def get_draft(draft_id: str, u: User = Depends(need("cases.read"))) -> dict[str, Any]:
        d = svc().drafts.get(u.tenant, draft_id)
        if "documents.original" not in u.permissions:
            for f in d["fields"]:
                for e in f["evidence"] + f["counter"]:
                    e.pop("quote", None)
                if f["type"] == "summary":
                    f["agent_value"] = f["final_value"] = None
        return d

    @app.post("/api/drafts/{draft_id}/fields/{field}")
    def review_field(
        draft_id: str, field: str, body: ReviewBody, u: User = Depends(need("drafts.review"))
    ) -> dict[str, Any]:
        try:
            svc().profile.get(field)
        except KeyError as e:
            raise HTTPException(404, f"no field {field}") from e
        return svc().drafts.review(u.tenant, draft_id, field, body.action, u.id, body.value, body.seconds)

    @app.post("/api/drafts/{draft_id}/accept-grounded")
    def accept_grounded(draft_id: str, u: User = Depends(need("drafts.review"))) -> dict[str, int]:
        return {"accepted": svc().drafts.accept_grounded(u.tenant, draft_id, u.id)}

    @app.post("/api/drafts/{draft_id}/release")
    def release(draft_id: str, u: User = Depends(need("drafts.review"))) -> dict[str, Any]:
        if "drafts.release" not in u.permissions:
            raise HTTPException(403, "only a clinician can release a profile")
        return svc().drafts.release(u.tenant, draft_id, u.id, u.role)

    # ---- chat ---------------------------------------------------------------------------------------------------
    @app.get("/api/cases/{case_id}/chat")
    def chat_history(case_id: str, u: User = Depends(need("chat"))) -> list[dict[str, Any]]:
        s = svc()
        view = s.cases.load(u.tenant, case_id)
        with s.db.tenant(u.tenant) as c:
            rows = c.execute(
                "SELECT id, run_id, role, text, citations, status, feedback, at FROM chat_messages"
                " WHERE case_id = %s ORDER BY at, id",
                (case_id,),
            ).fetchall()
        assistant = [r for r in rows if r["role"] == "assistant"]
        shown = s.gw.reidentify(u.tenant, case_id, view.token, [r["text"] for r in assistant]) if assistant else []
        texts = {r["id"]: t for r, t in zip(assistant, shown, strict=True)}
        return [_row({**r, "text": texts.get(r["id"], r["text"])}) for r in rows]

    @app.post("/api/cases/{case_id}/chat")
    def chat(case_id: str, body: ChatBody, u: User = Depends(need("chat"))) -> dict[str, Any]:
        return svc().agent.chat(u.tenant, case_id, body.message, u.id)

    @app.post("/api/chat/{message_id}/feedback")
    def chat_feedback(message_id: int, body: FeedbackBody, u: User = Depends(need("chat"))) -> dict[str, str]:
        with svc().db.tenant(u.tenant) as c:
            r = c.execute(
                "UPDATE chat_messages SET feedback = %s WHERE id = %s AND role = 'assistant' RETURNING id",
                (body.feedback, message_id),
            ).fetchone()
        if r is None:
            raise HTTPException(404, "no such answer")
        return {"feedback": body.feedback}

    # ---- runs and traces (content-free) -------------------------------------------------------------------------
    @app.get("/api/runs")
    def runs(u: User = Depends(need("runs.read")), case_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        q = "SELECT * FROM runs" + (" WHERE case_id = %s" if case_id else "") + " ORDER BY started_at DESC LIMIT %s"
        with svc().db.tenant(u.tenant) as c:
            rows = c.execute(q, ((case_id, limit) if case_id else (limit,))).fetchall()
        return [_row(r) for r in rows]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str, u: User = Depends(need("runs.read"))) -> dict[str, Any]:
        with svc().db.tenant(u.tenant) as c:
            r = c.execute("SELECT * FROM runs WHERE id::text = %s", (run_id,)).fetchone()
            if r is None:
                raise HTTPException(404, "no such run")
            steps = c.execute("SELECT * FROM run_steps WHERE run_id::text = %s ORDER BY seq", (run_id,)).fetchall()
        return {**_row(r), "steps": [_row(s) for s in steps]}

    # ---- quality --------------------------------------------------------------------------------------------------
    @app.get("/api/quality/evals")
    def evals(u: User = Depends(need("quality.read")), limit: int = 50) -> list[dict[str, Any]]:
        with svc().db.admin() as c:
            rows = c.execute(
                "SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT %s", (max(1, min(limit, 200)),)
            ).fetchall()
        return [_row(r) for r in rows]

    @app.get("/api/quality/online")
    def online(u: User = Depends(need("quality.read")), days: int | None = None) -> dict[str, Any]:
        days = days or int(config.load("evaluation")["online"]["window_days"])
        since = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).isoformat()
        return {"window_days": days, **E.online(svc().db, u.tenant, since)}

    @app.get("/api/quality/reports")
    def reports(u: User = Depends(need("quality.read"))) -> dict[str, Any]:
        """The committed offline reports (synthetic golden set, no patient data) and the held-out first runs."""
        root = config.root() / "reports"
        out: dict[str, Any] = {"eval": {}, "heldout": {}}
        for p in sorted((root / "eval").glob("*.json")):
            out["eval"][p.stem] = json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((root / "heldout").glob("*/first_run*.json")):
            key = p.parent.name + (" (rescored)" if p.stem.endswith("rescored") else "")
            out["heldout"][key] = json.loads(p.read_text(encoding="utf-8"))
        return out

    # ---- prompts ----------------------------------------------------------------------------------------------------
    @app.get("/api/prompts")
    def prompt_table(u: User = Depends(need("prompts.read"))) -> dict[str, Any]:
        names = ("profile_drafter", "router", "case_chat", "summary_judge")
        defaults = config.load("agent")["defaults"]
        files = {}
        for n in names:
            files[n] = [
                {"version": v, "sha": prompts.load(n, v).sha256, "default": defaults[n]["version"] == v}
                for v in prompts.versions(n)
            ]
        return {
            "files": files,
            "defaults": defaults,
            "deployments": [_row(r) for r in prompts.table(svc().db, u.tenant)],
        }

    @app.post("/api/prompts/deploy")
    def deploy(body: DeployBody, u: User = Depends(need("prompts.deploy"))) -> list[dict[str, Any]]:
        tenant = "*" if body.scope == "all" else u.tenant
        try:
            prompts.deploy(svc().db, tenant, body.prompt, body.version, body.model, body.share)
        except FileNotFoundError as e:
            raise HTTPException(404, f"no prompt {body.prompt} {body.version}") from e
        with svc().db.tenant(u.tenant) as c:
            audit.append(
                c, u.tenant, u.id, "prompt.deployed", f"prompt/{body.prompt}/{body.version}", body.model_dump()
            )
        return [_row(r) for r in prompts.table(svc().db, u.tenant)]

    @app.post("/api/prompts/withdraw")
    def withdraw(body: WithdrawBody, u: User = Depends(need("prompts.deploy"))) -> list[dict[str, Any]]:
        tenant = "*" if body.scope == "all" else u.tenant
        prompts.withdraw(svc().db, tenant, body.prompt, body.version)
        with svc().db.tenant(u.tenant) as c:
            audit.append(
                c, u.tenant, u.id, "prompt.withdrawn", f"prompt/{body.prompt}/{body.version}", body.model_dump()
            )
        return [_row(r) for r in prompts.table(svc().db, u.tenant)]

    @app.get("/api/audit/verify")
    def audit_verify(u: User = Depends(need("audit.verify"))) -> dict[str, Any]:
        with svc().db.tenant(u.tenant) as c:
            ok, n = audit.verify(c, u.tenant)
        return {"intact": ok, "entries": n}

    @app.get("/api/policy")
    def policy(u: User = Depends(user)) -> dict[str, Any]:
        """Which processors this hospital's data may reach (from the gateway)."""
        return svc().gw.policy(u.tenant)

    # ---- the console ------------------------------------------------------------------------------------------------
    web = static_dir or config.root() / "web" / "dist"
    if (web / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404, "no such endpoint")
            f = web / path
            return FileResponse(
                f if path and f.is_file() and f.resolve().is_relative_to(web.resolve()) else web / "index.html"
            )

    return app
