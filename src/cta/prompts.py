"""Prompt registry. Prompts are versioned files (prompts/<name>/<version>.yaml), reviewed like code; what serves which
tenant is a row in prompt_deployments (a version, a model, a share). A version in canary gets a stable slice of cases
(hash of the case id), so a case keeps its prompt across runs and online metrics compare like with like."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import config
from .db import DB


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str
    tools: tuple[str, ...]
    description: str
    sha256: str


def path(name: str, version: str) -> Path:
    return config.root() / "prompts" / name / f"{version}.yaml"


def load(name: str, version: str) -> Prompt:
    raw = path(name, version).read_text(encoding="utf-8")
    d = yaml.safe_load(raw)
    if d["name"] != name or d["version"] != version:
        raise ValueError(f"prompt file {name}/{version} declares {d['name']}/{d['version']}")
    return Prompt(
        name,
        version,
        d["system"].strip(),
        tuple(d.get("tools", [])),
        " ".join(str(d.get("description", "")).split()),
        hashlib.sha256(raw.encode()).hexdigest()[:12],
    )


def versions(name: str) -> list[str]:
    d = config.root() / "prompts" / name
    return sorted(p.stem for p in d.glob("*.yaml"))


@dataclass(frozen=True)
class Assignment:
    prompt: Prompt
    model: str
    arm: str  # production | canary | override


def _bucket(case_id: str, prompt: str) -> float:
    h = hashlib.sha256(f"{prompt}|{case_id}".encode()).digest()
    return int.from_bytes(h[:4], "big") / 2**32


def resolve(db: DB | None, tenant: str, name: str, case_id: str, override: dict[str, str] | None = None) -> Assignment:
    """Which prompt version and model serve this case: an explicit override (evaluation), else the deployments for the
    tenant (or '*'), else the defaults in config/agent.yaml."""
    if override and name in override:
        version, _, model = override[name].partition("@")
        return Assignment(load(name, version), model or config.load("agent")["defaults"][name]["model"], "override")
    rows: list[dict[str, Any]] = []
    if db is not None:
        with db.tenant(tenant) as c:
            rows = c.execute(
                "SELECT * FROM prompt_deployments WHERE prompt = %s ORDER BY (tenant_id = '*'), share", (name,)
            ).fetchall()
    if rows:
        tenant_rows = [r for r in rows if r["tenant_id"] == tenant] or rows
        canaries = [r for r in tenant_rows if r["share"] < 1.0]
        production = [r for r in tenant_rows if r["share"] >= 1.0]
        b = _bucket(case_id, name)
        acc = 0.0
        for r in canaries:
            acc += float(r["share"])
            if b < acc:
                return Assignment(load(name, r["version"]), r["model"], "canary")
        if production:
            r = production[0]
            return Assignment(load(name, r["version"]), r["model"], "production")
    d = config.load("agent")["defaults"][name]
    return Assignment(load(name, d["version"]), d["model"], "production")


def deploy(db: DB, tenant: str, name: str, version: str, model: str, share: float) -> None:
    load(name, version)  # must exist
    with db.tenant(tenant) as c:
        if share >= 1.0:
            c.execute("DELETE FROM prompt_deployments WHERE tenant_id = %s AND prompt = %s", (tenant, name))
        c.execute(
            "INSERT INTO prompt_deployments (tenant_id, prompt, version, model, share) VALUES (%s,%s,%s,%s,%s)"
            " ON CONFLICT (tenant_id, prompt, version) DO UPDATE SET model = EXCLUDED.model, share = EXCLUDED.share, since = now()",
            (tenant, name, version, model, share),
        )


def withdraw(db: DB, tenant: str, name: str, version: str) -> None:
    with db.tenant(tenant) as c:
        c.execute(
            "DELETE FROM prompt_deployments WHERE tenant_id = %s AND prompt = %s AND version = %s",
            (tenant, name, version),
        )


def table(db: DB, tenant: str) -> list[dict[str, Any]]:
    with db.tenant(tenant) as c:
        return list(c.execute("SELECT * FROM prompt_deployments ORDER BY prompt, share DESC").fetchall())
