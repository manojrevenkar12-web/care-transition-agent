"""The agent: a LangGraph router in front of three workflows, each a tool-calling loop.

    guard ──► route ──► draft_profile ──► (model ⇄ tools)* ──► verified draft
                   ├──► answer_question ─► (model ⇄ tools)* ──► answer with checked quotes
                   ├──► find_providers ───► provider search on the released profile (no model)
                   └──► out_of_scope ─────► refusal

The deterministic guard runs before any model call: a question asking for a dose, a diagnosis or a treatment decision
never reaches the model. Context management: documents are listed first and read on demand in chunks, search works at
sentence level, and document text read more than `compact_after_turns` turns ago is replaced by a note (the model can
read it again), so long cases stay inside the context budget.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .. import config, guardrails
from .. import observability as obs
from ..cases import CaseStore, CaseView
from ..db import DB, J
from ..drafts import Drafts
from ..gateway import Gateway, GatewayError
from ..grounding import Verifier, find_quote
from ..profile import Profile
from ..profile import load as load_profile
from ..prompts import Assignment, resolve
from .model import BudgetExceeded, ModelClient, RunLog
from .tools import DraftRecorder, Toolbox, schemas, tool_result_text


class LoopState(TypedDict):
    messages: list[dict[str, Any]]
    turns: int
    done: bool


class ChatState(TypedDict, total=False):
    message: str
    workflow: str
    result: dict[str, Any]


def compact(messages: list[dict[str, Any]], keep_turns: int) -> list[dict[str, Any]]:
    """Replace the text of document reads older than the last keep_turns assistant turns with a short note."""
    names: dict[str, str] = {}
    for m in messages:
        if m["role"] == "assistant":
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    names[b["id"]] = b["name"]
    assistant_idx = [i for i, m in enumerate(messages) if m["role"] == "assistant"]
    if len(assistant_idx) <= keep_turns:
        return messages
    cutoff = assistant_idx[-keep_turns]
    out = []
    for i, m in enumerate(messages):
        if i < cutoff and m["role"] == "user" and isinstance(m["content"], list):
            blocks = []
            for b in m["content"]:
                if b.get("type") == "tool_result" and names.get(b["tool_use_id"]) == "read_document":
                    b = {
                        **b,
                        "content": '{"note": "document text read earlier was removed to save context; call read_document again if you need it"}',
                    }
                blocks.append(b)
            m = {**m, "content": blocks}
        out.append(m)
    return out


class Agent:
    def __init__(
        self,
        db: DB,
        gateway: Gateway,
        cases: CaseStore,
        drafts: Drafts,
        profile: Profile | None = None,
        verifier: Verifier | None = None,
        override: dict[str, str] | None = None,
        providers: Any = None,
    ):
        self.db, self.gw, self.cases, self.drafts = db, gateway, cases, drafts
        self.profile = profile or load_profile()
        self.v = verifier or Verifier(self.profile)
        self.override = override
        self.providers = providers
        cfg = config.load("agent")
        self.limits, self.ctx = cfg["limits"], cfg["context"]
        self.schemas = schemas(self.profile)

    # ---- the loop -----------------------------------------------------------------------------------------------
    def _loop(self, client: ModelClient, tb: Toolbox, a: Assignment, first_user: str, run: RunLog) -> LoopState:
        tools = [self.schemas[n] for n in a.prompt.tools]
        keep = int(self.ctx["compact_after_turns"])

        def model_node(s: LoopState) -> LoopState:
            resp = client.call(a.model, a.prompt.system, compact(s["messages"], keep), tools)
            msgs = s["messages"] + [{"role": "assistant", "content": resp.get("content", [])}]
            uses = [b for b in resp.get("content", []) if b.get("type") == "tool_use"]
            return {"messages": msgs, "turns": s["turns"] + 1, "done": not uses}

        def tools_node(s: LoopState) -> LoopState:
            uses = [b for b in s["messages"][-1]["content"] if b.get("type") == "tool_use"]
            results = []
            for u in uses:
                started, t0 = dt.datetime.now(dt.UTC), time.monotonic()
                with obs.span(
                    f"execute_tool {u['name']}",
                    {
                        "gen_ai.operation.name": "execute_tool",
                        "gen_ai.tool.name": u["name"],
                        "gen_ai.tool.call.id": u["id"],
                        "gen_ai.tool.type": "function",
                    },
                ) as span:
                    if run.tool_calls >= int(self.limits["max_tool_calls"]):
                        res: dict[str, Any] = {"error": "tool call budget for this run is used up"}
                    else:
                        res = tb.call(u["name"], u.get("input") or {})
                    status = str(res.get("status") or ("error" if "error" in res else "ok"))
                    span.set_attribute("cta.tool.status", status)
                    if "field" in (u.get("input") or {}):
                        span.set_attribute("cta.field", str(u["input"]["field"]))
                run.tool_calls += 1
                detail = {"field": (u.get("input") or {}).get("field")} if "field" in (u.get("input") or {}) else {}
                run.add("tool", u["name"], started, int((time.monotonic() - t0) * 1000), status, detail=detail)
                obs.TOOL_CALLS.labels(u["name"], status).inc()
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": tool_result_text(res)})
            return {
                "messages": s["messages"] + [{"role": "user", "content": results}],
                "turns": s["turns"],
                "done": tb.finished,
            }

        g: StateGraph[LoopState] = StateGraph(LoopState)
        g.add_node("model", model_node)  # type: ignore[call-overload]
        g.add_node("tools", tools_node)  # type: ignore[call-overload]
        g.add_edge(START, "model")
        g.add_conditional_edges("model", lambda s: END if s["done"] else "tools", {"tools": "tools", END: END})
        g.add_conditional_edges("tools", lambda s: END if s["done"] else "model", {"model": "model", END: END})
        app = g.compile()
        init: LoopState = {"messages": [{"role": "user", "content": first_user}], "turns": 0, "done": False}
        return app.invoke(init, {"recursion_limit": 4 * int(self.limits["max_model_calls"]) + 4})  # type: ignore[return-value]

    # ---- runs ---------------------------------------------------------------------------------------------------
    def _start(self, case: CaseView, workflow: str, a: Assignment | None, run: RunLog) -> None:
        with self.db.tenant(case.tenant) as c:
            c.execute(
                "INSERT INTO runs (id, tenant_id, case_id, workflow, status, prompt, prompt_version, model) VALUES (%s,%s,%s,%s,'running',%s,%s,%s)",
                (
                    run.run_id,
                    case.tenant,
                    case.case_id,
                    workflow,
                    a.prompt.name if a else None,
                    a.prompt.version if a else None,
                    a.model if a else None,
                ),
            )

    def _finish(self, case: CaseView, workflow: str, run: RunLog, status: str, error: str | None = None) -> None:
        with self.db.tenant(case.tenant) as c:
            c.execute(
                "UPDATE runs SET status=%s, finished_at=now(), input_tokens=%s, output_tokens=%s, model_calls=%s, tool_calls=%s,"
                " upstream=%s, error=%s WHERE id=%s",
                (
                    status,
                    run.input_tokens,
                    run.output_tokens,
                    run.model_calls,
                    run.tool_calls,
                    run.upstream,
                    error,
                    run.run_id,
                ),
            )
            for s in run.steps:
                c.execute(
                    "INSERT INTO run_steps (run_id, seq, tenant_id, kind, name, started_at, duration_ms, input_tokens, output_tokens, status, detail)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        run.run_id,
                        s.seq,
                        case.tenant,
                        s.kind,
                        s.name,
                        s.started_at,
                        s.duration_ms,
                        s.input_tokens,
                        s.output_tokens,
                        s.status,
                        J(s.detail),
                    ),
                )
        obs.RUNS.labels(workflow, status).inc()
        obs.RUN_SECONDS.labels(workflow).observe(time.monotonic() - run.started)
        obs.event(
            "run.finished",
            run=run.run_id,
            case=case.case_id,
            tenant=case.tenant,
            workflow=workflow,
            status=status,
            tokens_in=run.input_tokens,
            tokens_out=run.output_tokens,
            count=run.model_calls,
        )

    def draft_profile(self, tenant: str, case_id: str, actor: str) -> dict[str, Any]:
        case = self.cases.load(tenant, case_id)
        a = resolve(self.db, tenant, "profile_drafter", case_id, self.override)
        run = RunLog()
        self._start(case, "draft_profile", a, run)
        rec = DraftRecorder(self.profile, self.v, case)
        tb = Toolbox(case, rec, int(self.ctx["read_chunk_chars"]), int(self.ctx["search_top_k"]))
        client = ModelClient(self.gw, case, run, self.limits, "profile_drafter", a.prompt.version)
        status, error = "completed", None
        with obs.span(
            "invoke_agent profile_drafter",
            {
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": "profile_drafter",
                "gen_ai.agent.version": a.prompt.version,
                "gen_ai.request.model": a.model,
                "gen_ai.conversation.id": run.run_id,
                "cta.arm": a.arm,
                "cta.tenant": tenant,
            },
        ) as span:
            try:
                note = "Prepare the transfer profile for this patient. " + (
                    f"{len(case.blocked)} document(s) were withheld because identifiers could not be removed. "
                    if case.blocked
                    else ""
                )
                self._loop(client, tb, a, note, run)
                if not tb.finished:
                    status = "incomplete"
            except BudgetExceeded as e:
                status, error = "budget_exceeded", str(e)
            except GatewayError as e:
                status, error = f"gateway_{e.kind}", str(e)
                obs.event("run.gateway_error", run=run.run_id, error_type=e.kind, status=str(e.status))
            span.set_attribute("cta.status", status)
            span.set_attribute("gen_ai.usage.input_tokens", run.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", run.output_tokens)
        draft_id = None
        if rec.fields or rec.unknown:
            draft_id = self.drafts.save(tenant, case_id, run.run_id, rec, a.prompt.version, a.model, actor)
        else:
            status = status if status != "completed" else "empty"
        self._finish(case, "draft_profile", run, status, error)
        return {
            "run_id": run.run_id,
            "draft_id": draft_id,
            "status": status,
            "prompt_version": a.prompt.version,
            "model": a.model,
            "arm": a.arm,
            "model_calls": run.model_calls,
            "tool_calls": run.tool_calls,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
        }

    # ---- chat: the router graph ---------------------------------------------------------------------------------
    def chat(self, tenant: str, case_id: str, message: str, actor: str) -> dict[str, Any]:
        case = self.cases.load(tenant, case_id)
        guards = guardrails.load()
        run = RunLog()
        self._start(case, "chat", None, run)
        message = " ".join(message.split())[:2000]

        def guard(s: ChatState) -> ChatState:
            if guardrails.out_of_scope(s["message"], guards):
                obs.GUARDS.labels("out_of_scope").inc()
                run.add("guard", "out_of_scope", dt.datetime.now(dt.UTC), 0, "refused")
                return {"workflow": "out_of_scope"}
            return {}

        def route(s: ChatState) -> ChatState:
            if s.get("workflow"):
                return {}
            a = resolve(self.db, tenant, "router", case_id, self.override)
            tb = Toolbox(case, None, int(self.ctx["read_chunk_chars"]), int(self.ctx["search_top_k"]))
            client = ModelClient(self.gw, case, run, self.limits, "router", a.prompt.version)
            self._loop(client, tb, a, s["message"], run)
            return {"workflow": (tb.route or {}).get("workflow", "answer_question")}

        def answer(s: ChatState) -> ChatState:
            a = resolve(self.db, tenant, "case_chat", case_id, self.override)
            tb = Toolbox(case, None, int(self.ctx["read_chunk_chars"]), int(self.ctx["search_top_k"]))
            client = ModelClient(self.gw, case, run, self.limits, "case_chat", a.prompt.version)
            self._loop(client, tb, a, s["message"], run)
            ans = tb.answer or {"text": "", "citations": []}
            return {"result": self._check_answer(case, ans)}

        def draft(s: ChatState) -> ChatState:
            return {"result": {"kind": "draft", **self.draft_profile(tenant, case_id, actor)}}

        def providers(s: ChatState) -> ChatState:
            if self.providers is None:
                return {"result": {"kind": "error", "text": "provider search is not configured"}}
            draft_id = self.drafts.latest(tenant, case_id)
            return {"result": {"kind": "providers", **self.providers.search_for_draft(tenant, draft_id)}}

        def refuse(s: ChatState) -> ChatState:
            return {"result": {"kind": "refusal", "text": guards.refusal}}

        g: StateGraph[ChatState] = StateGraph(ChatState)
        for name, fn in [
            ("guard", guard),
            ("route", route),
            ("answer_question", answer),
            ("draft_profile", draft),
            ("find_providers", providers),
            ("out_of_scope", refuse),
        ]:
            g.add_node(name, fn)  # type: ignore[call-overload]
        g.add_edge(START, "guard")
        g.add_edge("guard", "route")
        g.add_conditional_edges(
            "route",
            lambda s: s["workflow"],
            {w: w for w in ("answer_question", "draft_profile", "find_providers", "out_of_scope")},
        )
        for w in ("answer_question", "draft_profile", "find_providers", "out_of_scope"):
            g.add_edge(w, END)
        status, error = "completed", None
        out: dict[str, Any] = {}
        with obs.span(
            "invoke_workflow case_chat",
            {
                "gen_ai.operation.name": "invoke_workflow",
                "gen_ai.workflow.name": "case_chat",
                "gen_ai.conversation.id": run.run_id,
                "cta.tenant": tenant,
            },
        ):
            try:
                out = g.compile().invoke({"message": message})
            except BudgetExceeded as e:
                status, error = "budget_exceeded", str(e)
            except GatewayError as e:
                status, error = f"gateway_{e.kind}", str(e)
        result = out.get("result", {"kind": "error", "text": "the assistant could not answer"})
        workflow = out.get("workflow", "")
        with self.db.tenant(tenant) as c:
            c.execute(
                "INSERT INTO chat_messages (tenant_id, case_id, run_id, role, text) VALUES (%s,%s,%s,'user',%s)",
                (tenant, case_id, run.run_id, message),
            )
            if result.get("kind") in ("answer", "refusal"):
                c.execute(
                    "INSERT INTO chat_messages (tenant_id, case_id, run_id, role, text, citations, status) VALUES (%s,%s,%s,'assistant',%s,%s,%s)",
                    (
                        tenant,
                        case_id,
                        run.run_id,
                        result.get("text", ""),
                        J(result.get("citations", [])),
                        result.get("status", "ok"),
                    ),
                )
        self._finish(case, "chat", run, status, error)
        if result.get("kind") == "answer" and result.get("text"):
            result["display_text"] = self.gw.reidentify(tenant, case_id, case.token, [result["text"]])[0]
        return {"run_id": run.run_id, "workflow": workflow, "status": status, **result}

    def _check_answer(self, case: CaseView, ans: dict[str, Any]) -> dict[str, Any]:
        """An answer is shown as verified only if every citation is a real quote; advice is held back."""
        by_id = {d.id: d for d in case.docs}
        checked, ok = [], True
        for c in ans.get("citations", []):
            d = by_id.get(str(c.get("doc_id")))
            span = find_quote(d.text, str(c.get("quote", ""))) if d else None
            if span is None:
                span = next(((x.id, s) for x in case.docs if (s := find_quote(x.text, str(c.get("quote", ""))))), None)  # type: ignore[assignment]
                if span is not None:
                    c = {**c, "doc_id": span[0]}  # type: ignore[index]
                    span = span[1]  # type: ignore[index]
            ok = ok and span is not None
            checked.append(
                {**c, "found": span is not None, "start": span[0] if span else -1, "end": span[1] if span else -1}
            )
        advice = guardrails.clinical_advice(ans.get("text", ""))
        status = "verified" if checked and ok and not advice else ("advice_held" if advice else "unverified")
        if advice:
            obs.GUARDS.labels("clinical_advice").inc()
        text = (
            ans.get("text", "")
            if not advice
            else "Die Antwort enthielt eine medizinische Empfehlung und wird nicht angezeigt."
        )
        return {"kind": "answer", "text": text, "citations": checked, "status": status}
