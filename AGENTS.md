# Working in this repository

## Fast feedback

| What | Command | Needs |
|---|---|---|
| Gateway (Go, stdlib only) | `cd gateway && go test -race ./...` | Go 1.24 |
| Platform | `pytest -q` | PostgreSQL in `CTA_TEST_DATABASE_URL`, Go (the tests build and start the real gateway) |
| Lint and types | `ruff check src tests && ruff format --check src tests && mypy src` | |
| Console | `cd web && npm run typecheck && npm test` | Node 22 |
| End to end | `scripts/e2e.sh` | all of the above; runs Playwright against `cta serve --local-stack` |
| Evaluation gate | `cta eval offline --set dev --candidate v2@sim-careful --baseline v1@sim-careful --local-stack` | exits 1 when the gate fails |

## Invariants (each has a test)

- **Every model call leaves through the gateway.** The agent has no model credentials and no route to a provider;
  the gateway replaces identifiers before the request goes out and refuses one that still contains a known
  identifier (`tests/test_agent_flow.py`, `gateway/internal/server`).
- **The leak check is not the replacer run again.** It searches without the replacer's context rules and reads
  digit runs as substrings, so a replacer miss is refused rather than sent (`views_test.go`).
- **A hospital reaches only the processors its contract names** (`config/gateway.json`, `internal/config`).
- **Every output is a draft until a clinician releases it.** Only the `clinician` role releases, and only when no
  required field is undecided (`tests/test_api.py`).
- **Values are shown as grounded only when the verifier finds them in the documents.** The model proposes, code
  checks (`src/cta/grounding.py`); evidence from text addressed to an AI is never grounding.
- **Tenants are isolated in PostgreSQL** by row-level security with `FORCE`; the application connects as a role that
  cannot bypass it (`test_another_hospital_sees_nothing`).
- **The audit log is append-only and hash-chained** (`test_audit_is_immutable`).
- **Health text never reaches a log or a trace.** Logs keep an allow-list of keys and scrub long digit runs; spans
  carry ids, models, token counts and statuses only.
- **Settings live in `config/`**, prompts in `prompts/` (versioned files with a hash), not in code.

## Held-out sets

`heldout/<set>/` is written blind, by someone who has read only `heldout/WRITING_GUIDE.md`, and run once with
`cta heldout run --set <set>`. The first run (`reports/heldout/<set>/first_run.json`) is pinned in
`heldout/first_run.sha256`, checked in CI, and never rewritten.

- Never change the gateway, the verifier or the guards to pass a held-out set before its first run is recorded.
- If you study a set's failures, write `regression` to `heldout/<set>/STATUS`. A regression set can be scored with
  `cta heldout score`; a held-out set cannot.
- Then have someone who has not seen the code write a new set from the guide only.
- A fix to the scorer alone may be applied to a first run with `cta heldout rescore`, which refuses unless the
  components under test are byte-identical to the first run's commit. The rescored file sits next to the first run.
