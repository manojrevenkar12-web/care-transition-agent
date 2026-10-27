"""cta: the platform's command line.

cta migrate                                        create or update the schema
cta serve [--host --port]                          the API and the clinician console
cta case import --tenant T bundle.json             a FHIR Bundle in
cta draft --tenant T --case C                      run the profile drafter on a case
cta eval offline --set dev --candidate v2@sim-careful --baseline v1@sim-careful [--local-stack]
cta eval judge --set dev [--local-stack]           judge agreement with clinician labels
cta eval online --tenant T                         what clinicians did with the drafts
cta prompts list|deploy|withdraw ...               which prompt version serves whom
cta retention purge --tenant T                     crypto-shred documents past retention
cta fhir questionnaire                             the profile as a FHIR Questionnaire
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import config


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


@contextlib.contextmanager
def _platform(local_stack: bool) -> Iterator[dict[str, Any]]:
    from .cases import CaseStore
    from .crypto import Keyring
    from .db import DB
    from .gateway import Gateway

    with contextlib.ExitStack() as stack:
        if local_stack:
            from ctasim.stack import local_stack as ls

            s = stack.enter_context(ls())
            gw = Gateway(s["gateway_url"], s["token"])
        else:
            gw = Gateway()
        if not os.environ.get("CTA_KEYRING"):
            if not local_stack:
                raise SystemExit("CTA_KEYRING is not set")
            os.environ["CTA_KEYRING"] = Keyring.generate(["eval", "klinikum-nord", "st-elisabeth", "dev"])
        db = DB()
        db.migrate()
        stack.callback(db.close)
        yield {"db": db, "gw": gw, "cases": CaseStore(db, gw, Keyring.from_env())}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cta")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--local-stack", action="store_true", help="start the simulated model and the gateway too")
    c = sub.add_parser("case")
    c.add_argument("action", choices=["import"])
    c.add_argument("--tenant", required=True)
    c.add_argument("bundle")
    d = sub.add_parser("draft")
    d.add_argument("--tenant", required=True)
    d.add_argument("--case", required=True)
    e = sub.add_parser("eval")
    e.add_argument("kind", choices=["offline", "judge", "online"])
    e.add_argument("--set", default="dev")
    e.add_argument("--candidate", default="v2@sim-careful")
    e.add_argument("--baseline", default="")
    e.add_argument("--tenant", default="")
    e.add_argument("--limit", type=int, default=0)
    e.add_argument("--local-stack", action="store_true")
    e.add_argument("--out", default="")
    pr = sub.add_parser("prompts")
    pr.add_argument("action", choices=["list", "deploy", "withdraw"])
    pr.add_argument("--tenant", default="*")
    pr.add_argument("--prompt", default="profile_drafter")
    pr.add_argument("--version", default="")
    pr.add_argument("--model", default="sim-careful")
    pr.add_argument("--share", type=float, default=1.0)
    r = sub.add_parser("retention")
    r.add_argument("action", choices=["purge"])
    r.add_argument("--tenant", required=True)
    h = sub.add_parser("heldout")
    h.add_argument("action", choices=["run", "rescore", "score"])
    h.add_argument("--reason", default="")
    h.add_argument("--set", required=True)
    h.add_argument("--local-stack", action="store_true")
    f = sub.add_parser("fhir")
    f.add_argument("what", choices=["questionnaire"])
    a = p.parse_args(argv)

    if a.cmd == "fhir":
        from .profile import questionnaire

        _print(questionnaire())
        return 0
    if a.cmd == "migrate":
        from .db import DB

        db = DB()
        db.migrate()
        for t, name in (("klinikum-nord", "Klinikum Nord"), ("st-elisabeth", "St. Elisabeth"), ("dev", "Development")):
            db.ensure_tenant(t, name)
        print("migrated")
        return 0
    if a.cmd == "serve":
        import uvicorn

        from .api import create_app

        with contextlib.ExitStack() as stack:
            if a.local_stack:
                from ctasim.stack import local_stack as ls

                s = stack.enter_context(ls())
                os.environ["CTA_GATEWAY_URL"], os.environ["CTA_GATEWAY_TOKEN"] = s["gateway_url"], s["token"]
            uvicorn.run(create_app(), host=a.host, port=a.port, log_level="warning")
        return 0
    if a.cmd == "eval":
        return _eval(a)
    if a.cmd == "heldout":
        from . import heldout
        from .gateway import Gateway

        with contextlib.ExitStack() as stack:
            if a.local_stack:
                from ctasim.stack import local_stack as ls

                s = stack.enter_context(ls())
                gw = Gateway(s["gateway_url"], s["token"])
            else:
                gw = Gateway()
            if a.action == "rescore":
                if not a.reason:
                    raise SystemExit("--reason is required: say what was wrong with the scorer")
                res = heldout.rescore(a.set, gw, a.reason)
            elif a.action == "score":
                res = heldout.score(a.set, gw)
            else:
                res = heldout.run(a.set, gw)
        _print(
            {k: v for k, v in res.items() if k not in ("pii",)}
            | {"pii": {k: v for k, v in res.get("pii", {}).items() if k != "misses"}}
        )
        return 0
    with _platform(False) as P:
        if a.cmd == "case":
            bundle = json.loads(Path(a.bundle).read_text(encoding="utf-8"))
            _print({"case": P["cases"].create(a.tenant, bundle, actor="cli")})
        elif a.cmd == "draft":
            from .agent.runner import Agent
            from .drafts import Drafts
            from .grounding import Verifier
            from .profile import load

            prof = load()
            v = Verifier(prof)
            agent = Agent(P["db"], P["gw"], P["cases"], Drafts(P["db"], prof, P["cases"], v), prof, v)
            _print(agent.draft_profile(a.tenant, a.case, "cli"))
        elif a.cmd == "prompts":
            from . import prompts

            if a.action == "list":
                _print(
                    {
                        "files": {
                            n: prompts.versions(n) for n in ("profile_drafter", "router", "case_chat", "summary_judge")
                        },
                        "deployments": prompts.table(P["db"], a.tenant),
                    }
                )
            elif a.action == "deploy":
                prompts.deploy(P["db"], a.tenant, a.prompt, a.version, a.model, a.share)
                _print(prompts.table(P["db"], a.tenant))
            else:
                prompts.withdraw(P["db"], a.tenant, a.prompt, a.version)
                _print(prompts.table(P["db"], a.tenant))
        elif a.cmd == "retention":
            _print({"purged": P["cases"].purge_expired(a.tenant, dt.date.today())})
    return 0


def _eval(a: argparse.Namespace) -> int:
    from . import evaluation as E

    if a.kind == "online":
        with _platform(False) as P:
            _print(E.online(P["db"], a.tenant))
        return 0
    set_dir = config.root() / "eval" / "golden" / a.set
    golden = E.load_golden(set_dir)
    if a.limit:
        golden = golden[: a.limit]
    with _platform(a.local_stack) as P:
        ev = E.Evaluator(P["db"], P["gw"], P["cases"])
        tag = "e" + uuid.uuid4().hex[:6]
        try:
            if a.kind == "judge":
                result = ev.calibrate_judge(set_dir, golden, tag)
                eid = ev.store("judge", {"set": a.set}, None, result, None)
                out: dict[str, Any] = {"eval_id": eid, "judge": result}
            else:
                cand, cand_res = ev.run(golden, a.candidate, tag + "c")
                out = {"set": a.set, "candidate": a.candidate, "metrics": cand}
                gate_result = None
                if a.baseline:
                    base, base_res = ev.run(golden, a.baseline, tag + "b")
                    paired = E.paired_bootstrap(
                        E.per_case_accuracy(cand_res),
                        E.per_case_accuracy(base_res),
                        config.load("evaluation")["offline"]["bootstrap_samples"],
                        config.load("evaluation")["offline"]["confidence"],
                    )
                    gate_result = E.gate(cand, base, paired, None)
                    out.update(
                        {
                            "baseline": a.baseline,
                            "baseline_metrics": base,
                            "paired_accuracy": paired,
                            "gate": gate_result,
                        }
                    )
                out["eval_id"] = ev.store(
                    "offline",
                    {"set": a.set, "drafter": a.candidate},
                    {"drafter": a.baseline} if a.baseline else None,
                    {k: v for k, v in out.items() if k.endswith("metrics")},
                    gate_result,
                )
        finally:
            ev.cleanup(tag + "c")
            ev.cleanup(tag + "b")
            ev.cleanup(tag)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    _print(out if a.kind == "judge" else {k: v for k, v in out.items() if k != "baseline_metrics"})
    return 0 if not out.get("gate") or out["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
