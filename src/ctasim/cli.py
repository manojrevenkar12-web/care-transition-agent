"""ctasim: the simulator's command line.

ctasim golden --set dev --n 60 --seed 1000      write eval/golden/dev (cases, labels, judge labels)
ctasim serve-model --port 8071                   the simulated model over HTTP (for the gateway)
ctasim season scenarios/dev/season.yaml          a simulated month of a hospital using the agent
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cta import config


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ctasim")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("golden")
    g.add_argument("--set", required=True)
    g.add_argument("--n", type=int, default=60)
    g.add_argument("--seed", type=int, default=1000)
    s = sub.add_parser("serve-model")
    s.add_argument("--port", type=int, default=8071)
    s.add_argument("--host", default="127.0.0.1")
    se = sub.add_parser("season")
    se.add_argument("scenario")
    se.add_argument("--out")
    a = p.parse_args(argv)
    if a.cmd == "golden":
        from .golden import export

        out = config.root() / "eval" / "golden" / a.set
        n = export(out, a.n, a.seed)
        print(json.dumps({"set": a.set, "cases": n, "dir": str(out)}))
        return 0
    if a.cmd == "serve-model":
        import uvicorn

        from .model import app

        uvicorn.run(app(), host=a.host, port=a.port, log_level="warning")
        return 0
    if a.cmd == "season":
        from .season import run_season

        result = run_season(Path(a.scenario), Path(a.out) if a.out else None)
        print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
