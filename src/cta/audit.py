"""Append-only, hash-chained audit trail per tenant. The database refuses updates and deletes; the chain makes a gap or
an edit made by someone with database superuser rights visible when it is verified."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

from .db import J

GENESIS = "0" * 64


def _digest(prev: str, tenant: str, actor: str, action: str, obj: str, detail: dict[str, Any]) -> str:
    payload = json.dumps([prev, tenant, actor, action, obj, detail], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def append(
    c: psycopg.Connection[Any], tenant: str, actor: str, action: str, obj: str, detail: dict[str, Any] | None = None
) -> str:
    detail = detail or {}
    c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("audit|" + tenant,))
    row = c.execute("SELECT hash FROM audit WHERE tenant_id = %s ORDER BY id DESC LIMIT 1", (tenant,)).fetchone()
    prev = row["hash"] if row else GENESIS
    h = _digest(prev, tenant, actor, action, obj, detail)
    c.execute(
        "INSERT INTO audit (tenant_id, actor, action, object, detail, prev_hash, hash) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (tenant, actor, action, obj, J(detail), prev, h),
    )
    return h


def verify(c: psycopg.Connection[Any], tenant: str) -> tuple[bool, int]:
    prev, n = GENESIS, 0
    for r in c.execute("SELECT * FROM audit WHERE tenant_id = %s ORDER BY id", (tenant,)):
        if (
            r["prev_hash"] != prev
            or _digest(prev, tenant, r["actor"], r["action"], r["object"], r["detail"]) != r["hash"]
        ):
            return False, n
        prev, n = r["hash"], n + 1
    return True, n
