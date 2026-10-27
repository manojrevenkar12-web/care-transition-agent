"""PostgreSQL access. Patient data is only reachable through `DB.tenant(t)`, which switches to the row-level-security
role and sets the tenant for the transaction; `DB.admin()` is for schema setup and tables without patient data."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

APP_ROLE = "cta_app"


def url() -> str:
    return os.environ.get("CTA_DATABASE_URL", "postgresql://ptp:ptp@127.0.0.1:5432/cta")


class DB:
    def __init__(self, dsn: str | None = None, min_size: int = 1, max_size: int = 8):
        self.dsn = dsn or url()
        self.pool = ConnectionPool(
            self.dsn, min_size=min_size, max_size=max_size, kwargs={"row_factory": dict_row}, open=True
        )

    def close(self) -> None:
        self.pool.close()

    def migrate(self) -> None:
        sql = resources.files("cta").joinpath("sql/schema.sql").read_text(encoding="utf-8")
        with self.pool.connection() as c:
            c.execute("SELECT pg_advisory_lock(711)")
            try:
                c.execute(sql)
            finally:
                c.execute("SELECT pg_advisory_unlock(711)")

    @contextmanager
    def tenant(self, tenant_id: str) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        if not tenant_id:
            raise ValueError("a tenant is required")
        with self.pool.connection() as c, c.transaction():
            c.execute(f"SET LOCAL ROLE {APP_ROLE}")
            c.execute("SELECT set_config('app.tenant', %s, true)", (tenant_id,))
            yield c  # type: ignore[misc]  # the pool sets row_factory=dict_row

    @contextmanager
    def admin(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        with self.pool.connection() as c, c.transaction():
            yield c  # type: ignore[misc]

    def ensure_tenant(self, tenant_id: str, name: str, retention_days: int = 30) -> None:
        with self.admin() as c:
            c.execute(
                "INSERT INTO tenants (id, name, retention_days) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (tenant_id, name, retention_days),
            )


def J(v: Any) -> Jsonb:
    return Jsonb(v)
