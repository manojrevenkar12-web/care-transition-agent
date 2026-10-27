"""Settings live in config/*.yaml (and config/gateway.json for the Go gateway). ${VAR} and ${VAR:-default} are expanded
from the environment when a file is loaded."""

from __future__ import annotations

import functools
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def root() -> Path:
    env = os.environ.get("CTA_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "config" / "profile.yaml").exists():
            return p
    return Path.cwd()


def expand(text: str) -> str:
    return _ENV.sub(lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""), text)


@functools.lru_cache(maxsize=64)
def _load(path: str, mtime: float) -> Any:
    raw = expand(Path(path).read_text(encoding="utf-8"))
    return json.loads(raw) if path.endswith(".json") else yaml.safe_load(raw)


def load(name: str) -> Any:
    """config/<name>.yaml (or .json). Cached until the file changes."""
    base = root() / "config"
    path = base / f"{name}.yaml"
    if not path.exists():
        path = base / f"{name}.json"
    return _load(str(path), path.stat().st_mtime)


def data_dir() -> Path:
    return Path(os.environ.get("CTA_DATA", str(root() / "data")))
