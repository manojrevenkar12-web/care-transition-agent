"""Tracing, metrics and logs for the agent, without patient content.

Traces follow the OpenTelemetry GenAI semantic conventions (development status in 2026): an `invoke_agent` span per run,
a `chat {model}` span per model call with token usage, an `execute_tool {tool}` span per tool call. Prompt and completion
content is never put on spans (the conventions make it opt-in for this reason); spans carry ids, counts, statuses and
the prompt version, so a trace answers "which prompt, which model, how many tokens, which tool failed" and nothing
about the patient. Metrics are Prometheus; logs are JSON lines with an allow-list of keys.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Span, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Status, StatusCode, Tracer
from prometheus_client import CollectorRegistry, Counter, Histogram

_provider = TracerProvider(resource=Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "cta-agent")}))
if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))


def add_exporter(exporter: SpanExporter) -> None:
    _provider.add_span_processor(SimpleSpanProcessor(exporter))


def tracer() -> Tracer:
    return _provider.get_tracer("cta", "0.1.0")


REGISTRY = CollectorRegistry()
RUNS = Counter("cta_agent_runs_total", "Agent runs by workflow and outcome.", ["workflow", "status"], registry=REGISTRY)
RUN_SECONDS = Histogram(
    "cta_agent_run_seconds",
    "Agent run duration.",
    ["workflow"],
    registry=REGISTRY,
    buckets=(1, 2, 5, 10, 20, 40, 80, 160),
)
MODEL_CALLS = Counter(
    "cta_agent_model_calls_total",
    "Model calls by model, upstream and outcome.",
    ["model", "upstream", "outcome"],
    registry=REGISTRY,
)
TOKENS = Counter("cta_agent_tokens_total", "Tokens by model and direction.", ["model", "direction"], registry=REGISTRY)
TOOL_CALLS = Counter(
    "cta_agent_tool_calls_total", "Tool calls by tool and result.", ["tool", "status"], registry=REGISTRY
)
VERDICTS = Counter(
    "cta_field_verdicts_total", "Verifier verdicts on recorded fields.", ["field", "status"], registry=REGISTRY
)
GUARDS = Counter("cta_guardrail_events_total", "Guardrail events.", ["kind"], registry=REGISTRY)
REVIEWS = Counter(
    "cta_review_actions_total",
    "Clinician review actions by the agent's verdict.",
    ["action", "agent_status"],
    registry=REGISTRY,
)
RELEASES = Counter("cta_releases_total", "Profiles released by a clinician.", ["prompt_version"], registry=REGISTRY)


# ---- logs ---------------------------------------------------------------------------------------------------------
ALLOWED_LOG_KEYS = {
    "event",
    "tenant",
    "case",
    "run",
    "draft",
    "workflow",
    "field",
    "status",
    "tool",
    "model",
    "upstream",
    "prompt",
    "version",
    "arm",
    "tokens_in",
    "tokens_out",
    "ms",
    "count",
    "error_type",
    "action",
    "actor_role",
    "fields",
    "flagged",
    "seconds",
    "outcome",
    "kinds",
}
_DIGITS = re.compile(r"\d{6,}")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = getattr(record, "cta", {})
        out = {"ts": round(record.created, 3), "level": record.levelname.lower(), "msg": record.getMessage()}
        for k, v in data.items():
            if k in ALLOWED_LOG_KEYS:
                out[k] = v if not isinstance(v, str) else _DIGITS.sub("<n>", v)[:120]
        return json.dumps(out, ensure_ascii=False)


log = logging.getLogger("cta")
if not log.handlers:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(JsonFormatter())
    log.addHandler(h)
    log.setLevel(os.environ.get("CTA_LOG_LEVEL", "INFO"))
    log.propagate = False


def event(name: str, level: int = logging.INFO, **fields: Any) -> None:
    """Log an event with allow-listed keys only; anything else is dropped, not redacted."""
    log.log(level, name, extra={"cta": {"event": name, **fields}})


@contextmanager
def span(name: str, attributes: dict[str, Any]) -> Iterator[Span]:
    start = time.monotonic()
    with tracer().start_as_current_span(name, attributes={k: v for k, v in attributes.items() if v is not None}) as s:
        try:
            yield s  # type: ignore[misc]
        except Exception as e:
            s.set_status(Status(StatusCode.ERROR, type(e).__name__))
            s.set_attribute("error.type", type(e).__name__)
            raise
        finally:
            s.set_attribute("cta.duration_ms", int((time.monotonic() - start) * 1000))
