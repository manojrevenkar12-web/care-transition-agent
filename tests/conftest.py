"""Fixtures: a PostgreSQL database (CTA_TEST_DATABASE_URL), the simulated model over HTTP, and the real Go gateway
built from gateway/ and started as a subprocess in front of it. Tests that need them are marked db / gateway."""

from __future__ import annotations

import base64
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
TENANTS = ["klinikum-nord", "st-elisabeth", "dev"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_http(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"{url} did not come up")


@pytest.fixture(scope="session")
def sim_url() -> Iterator[str]:
    import uvicorn

    from ctasim.model import app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app(), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"
    wait_http(url + "/healthz")
    yield url
    server.should_exit = True


@pytest.fixture(scope="session")
def gateway_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("go") is None:
        pytest.skip("go is not installed")
    out = tmp_path_factory.mktemp("bin") / "gateway"
    subprocess.run(["go", "build", "-o", str(out), "./cmd/gateway"], cwd=ROOT / "gateway", check=True)
    return out


@pytest.fixture(scope="session")
def gateway(gateway_bin: Path, sim_url: str) -> Iterator[dict[str, Any]]:
    port = free_port()
    env = {
        **os.environ,
        "CTA_GATEWAY_LISTEN": f"127.0.0.1:{port}",
        "CTA_SIM_MODEL_URL": sim_url,
        "CTA_GATEWAY_SEAL_KEY": base64.b64encode(b"s" * 32).decode(),
        "CTA_GATEWAY_SURROGATE_KEY": base64.b64encode(b"h" * 32).decode(),
        "CTA_GATEWAY_SERVICE_TOKENS": "test-token",
    }
    proc = subprocess.Popen(
        [str(gateway_bin), "-config", str(ROOT / "config" / "gateway.json")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        wait_http(url + "/healthz")
        yield {"url": url, "token": "test-token", "proc": proc}
    finally:
        proc.terminate()
        proc.wait(5)


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("CTA_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CTA_TEST_DATABASE_URL is not set")
    return url


@pytest.fixture()
def db(database_url: str) -> Iterator[Any]:
    from cta.db import DB

    d = DB(database_url, max_size=4)
    with d.admin() as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO public;")
    d.migrate()
    for t in TENANTS:
        d.ensure_tenant(t, t.replace("-", " ").title())
    yield d
    d.close()


@pytest.fixture()
def keyring() -> Any:
    import json

    from cta.crypto import Keyring

    return Keyring({t: base64.b64decode(k) for t, k in json.loads(Keyring.generate(TENANTS)).items()})


@pytest.fixture()
def system(db: Any, gateway: dict[str, Any], keyring: Any) -> dict[str, Any]:
    from cta.agent.runner import Agent
    from cta.cases import CaseStore
    from cta.drafts import Drafts
    from cta.gateway import Gateway
    from cta.grounding import Verifier
    from cta.profile import load

    gw = Gateway(gateway["url"], gateway["token"])
    profile = load()
    verifier = Verifier(profile)
    cases = CaseStore(db, gw, keyring)
    drafts = Drafts(db, profile, cases, verifier)
    agent = Agent(db, gw, cases, drafts, profile, verifier)
    return {
        "db": db,
        "gw": gw,
        "cases": cases,
        "drafts": drafts,
        "agent": agent,
        "profile": profile,
        "verifier": verifier,
    }
