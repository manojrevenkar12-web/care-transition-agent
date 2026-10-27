"""Start the simulated model and the Go gateway locally (for the CLI, evaluation and seasons; tests have fixtures)."""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import uvicorn

from cta import config

from .model import app

# Demo users for `cta serve --local-stack` and the end-to-end tests. Never used outside the local stack.
DEMO_TOKENS = {
    "demo-clinician": {"user": "dr.weber", "tenant": "klinikum-nord", "role": "clinician"},
    "demo-coordinator": {"user": "sozialdienst.kaya", "tenant": "klinikum-nord", "role": "coordinator"},
    "demo-quality": {"user": "ki-team", "tenant": "klinikum-nord", "role": "quality"},
    "demo-other-hospital": {"user": "dr.lang", "tenant": "st-elisabeth", "role": "clinician"},
}


def _local_key(purpose: str) -> str:
    """A key for the local stack only (simulated data). Real deployments read keys from the secret store."""
    return base64.b64encode(hashlib.sha256(f"cta-local-stack|{purpose}".encode()).digest()).decode()


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"{url} did not come up")


def build_gateway(out: Path | None = None) -> Path:
    if shutil.which("go") is None:
        raise RuntimeError("go is required to build the gateway")
    out = out or Path(tempfile.mkdtemp()) / "gateway"
    subprocess.run(["go", "build", "-o", str(out), "./cmd/gateway"], cwd=config.root() / "gateway", check=True)
    return out


@contextmanager
def local_stack(token: str = "local-token") -> Iterator[dict[str, str]]:
    sim_port, gw_port = _port(), _port()
    server = uvicorn.Server(uvicorn.Config(app(), host="127.0.0.1", port=sim_port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    sim_url = f"http://127.0.0.1:{sim_port}"
    _wait(sim_url + "/healthz")
    binary = Path(os.environ["CTA_GATEWAY_BIN"]) if os.environ.get("CTA_GATEWAY_BIN") else build_gateway()
    env = {
        **os.environ,
        "CTA_GATEWAY_LISTEN": f"127.0.0.1:{gw_port}",
        "CTA_SIM_MODEL_URL": sim_url,
        # fixed local keys: the tags of unlisted people (and so the text the simulated model sees, which seeds its
        # randomness) are the same on every run, so an evaluation of the same code gives the same numbers
        "CTA_GATEWAY_SEAL_KEY": os.environ.get("CTA_GATEWAY_SEAL_KEY", _local_key("seal")),
        "CTA_GATEWAY_SURROGATE_KEY": os.environ.get("CTA_GATEWAY_SURROGATE_KEY", _local_key("surrogate")),
        "CTA_GATEWAY_SERVICE_TOKENS": token,
    }
    proc = subprocess.Popen(
        [str(binary), "-config", str(config.root() / "config" / "gateway.json")],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{gw_port}"
    try:
        _wait(url + "/healthz")
        yield {"gateway_url": url, "token": token, "sim_url": sim_url}
    finally:
        proc.terminate()
        proc.wait(5)
        server.should_exit = True
