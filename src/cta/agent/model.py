"""Model calls through the gateway, with GenAI-convention spans, metrics and a content-free step log."""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .. import observability as obs
from ..cases import CaseView
from ..gateway import Gateway, GatewayError


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Step:
    seq: int
    kind: str
    name: str
    started_at: dt.datetime
    duration_ms: int
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunLog:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    steps: list[Step] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    upstream: str = ""
    started: float = field(default_factory=time.monotonic)

    def add(self, kind: str, name: str, started: dt.datetime, ms: int, status: str, **kw: Any) -> None:
        self.steps.append(Step(len(self.steps) + 1, kind, name, started, ms, status, **kw))


def estimate_tokens(system: str, messages: list[dict[str, Any]]) -> int:
    return int((len(system) + len(json.dumps(messages, ensure_ascii=False))) / 3.5)


class ModelClient:
    def __init__(
        self,
        gateway: Gateway,
        case: CaseView,
        run: RunLog,
        limits: dict[str, Any],
        agent_name: str,
        prompt_version: str,
    ):
        self.gw, self.case, self.run, self.limits = gateway, case, run, limits
        self.agent_name, self.prompt_version = agent_name, prompt_version

    def call(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if self.run.model_calls >= int(self.limits["max_model_calls"]):
            raise BudgetExceeded("model call budget for this run is used up")
        if time.monotonic() - self.run.started > float(self.limits["run_seconds"]):
            raise BudgetExceeded("time budget for this run is used up")
        est = estimate_tokens(system, messages)
        if est > int(self.limits["max_input_tokens"]):
            raise BudgetExceeded(f"context of ~{est} tokens exceeds the limit")
        body = {
            "model": model,
            "system": system,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens or int(self.limits["max_output_tokens"]),
        }
        started = dt.datetime.now(dt.UTC)
        t0 = time.monotonic()
        attrs = {
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": model,
            "gen_ai.agent.name": self.agent_name,
            "gen_ai.agent.version": self.prompt_version,
            "gen_ai.conversation.id": self.run.run_id,
            "cta.tenant": self.case.tenant,
            "cta.estimated_input_tokens": est,
        }
        with obs.span(f"chat {model}", attrs) as span:
            try:
                resp, meta = self.gw.messages(
                    self.case.tenant, self.case.case_id, self.case.token, body, run_id=self.run.run_id
                )
            except GatewayError as e:
                ms = int((time.monotonic() - t0) * 1000)
                self.run.add("model", model, started, ms, f"error:{e.kind}")
                obs.MODEL_CALLS.labels(model, "", e.kind).inc()
                span.set_attribute("error.type", e.kind)
                raise
            usage = resp.get("usage", {})
            tin, tout = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
            span.set_attribute("gen_ai.provider.name", "cta-gateway/" + meta.get("upstream", ""))
            span.set_attribute("gen_ai.response.model", str(resp.get("model", model)))
            span.set_attribute("gen_ai.usage.input_tokens", tin)
            span.set_attribute("gen_ai.usage.output_tokens", tout)
            span.set_attribute("gen_ai.response.finish_reasons", [str(resp.get("stop_reason", ""))])
        ms = int((time.monotonic() - t0) * 1000)
        self.run.model_calls += 1
        self.run.input_tokens += tin
        self.run.output_tokens += tout
        self.run.upstream = meta.get("upstream", "")
        tools_called = [b.get("name") for b in resp.get("content", []) if b.get("type") == "tool_use"]
        self.run.add(
            "model",
            model,
            started,
            ms,
            "ok",
            input_tokens=tin,
            output_tokens=tout,
            detail={"stop_reason": resp.get("stop_reason"), "tool_calls": tools_called},
        )
        obs.MODEL_CALLS.labels(model, meta.get("upstream", ""), "ok").inc()
        obs.TOKENS.labels(model, "input").inc(tin)
        obs.TOKENS.labels(model, "output").inc(tout)
        return resp
