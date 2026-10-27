# care-transition-agent

An AI agent that drafts a patient's care-transfer profile (Überleitungsprofil) from German hospital documents, shows
every value next to the words it came from, and leaves the release to a clinician. Model calls leave the hospital only
through a pseudonymising gateway, and the parts that keep patients safe are measured on blind test sets.

![Review workspace: the profile beside the source documents](docs/screenshots/02-review.png)

## What it does

1. **Import** a case from the hospital system as a FHIR R4 Bundle (patient, relatives, physicians, encounter, text
   documents: scanned admission forms, nursing and social-services notes, discharge letters, dictations).
2. **Draft** the profile with a LangGraph agent: it lists and reads the documents in chunks, searches them, records
   each field with the exact words it read, marks what is not documented as unknown, and writes a short summary.
3. **Verify** every value against the documents with deterministic rules (negation, removal, history, other people,
   plans, later statements, text addressed to an AI). Only grounded values are shown as ready.
4. **Review** in the console: the profile beside the documents, evidence highlighted in the original, a switch to
   see the text as the model saw it, accept / change / enter / reject per field, questions about the case in a chat
   that cites the documents and refuses clinical decisions.
5. **Release** (clinicians only, nothing undecided) as a FHIR QuestionnaireResponse for the provider.

![The same document as the model saw it](docs/screenshots/03-as-the-model-saw-it.png)

## Architecture

| Part | Stack | Job |
|---|---|---|
| `gateway/` | Go 1.24, standard library only | Seals identities, pseudonymises with typed tags, refuses requests with a surviving identifier, routes each hospital only to the processors its contract names (AWS Bedrock eu-central-1 with SigV4; Anthropic API for development), budgets, retries, Prometheus metrics |
| `src/cta/` | Python 3.12, FastAPI, LangGraph, PostgreSQL | Import, encrypted case store (AES-GCM per tenant), agent graphs, verifier, guards, drafts, review, release, prompt registry with canaries, evaluation, audit hash chain, OpenTelemetry GenAI spans |
| `web/` | React 18, TypeScript, Vite, TanStack Query, Framer Motion | Clinician console and quality views, German and English, light and dark |
| `src/ctasim/` | Python | Simulated hospital documents with known facts and traps, and a simulated model behind the real gateway |
| `deploy/` | Docker, Terraform (AWS), OpenTelemetry Collector, Prometheus, Grafana | Local stack and an EU-only AWS deployment: ECS Fargate in private subnets without internet, RDS with KMS, a KMS key per hospital, Bedrock through a VPC endpoint |

Details: [docs/DESIGN.md](docs/DESIGN.md). Decisions: [docs/adr](docs/adr). Regulatory position:
[docs/INTENDED_PURPOSE.md](docs/INTENDED_PURPOSE.md). Operations: [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Results

All numbers come from committed reports (`reports/`) and can be regenerated with the commands in
[docs/EVALUATION.md](docs/EVALUATION.md).

**Golden set** (200 simulated cases, 3,800 fields; simulated model behind the real gateway; deterministic, so the same code gives the same numbers):

| Drafter | Field accuracy | Wrong but shown as ready (major) | Review load | Fabrications | Gate |
|---|---|---|---|---|---|
| prompt v2 | 96.9 % | 0 of 2,622 ready values | 3.0 % | 0 | passed against v1 (paired +0.004, 95 % CI −0.002 to +0.011) |
| prompt v1 | 96.5 % | 1 | 6.7 % | 126 | |
| prompt v2, hasty model | 90.3 % | 1 | 13.6 % | 8 | failed on 4 of 6 checks: does not ship |

**LLM judge** for the free-text summary: used only where Cohen's κ against clinician labels ≥ 0.6 (covers needs 0.83,
no advice 0.74). "No identifiers" scores κ 0.09 because the judge only ever sees pseudonymised text, so that check
stays with the gateway.

**Blind held-out sets** for the gateway, the verifier and the guards, written by someone who saw only the writing
guide, run once and pinned:

| | v1 (rescored¹) | v2, after studying v1 |
|---|---|---|
| listed identifiers replaced | 85.3 % | 96.7 % |
| documents with a listed identifier reaching the model | 21 of 55 | 7 of 55 |
| people the record does not list, replaced | 70.7 % | 66.3 % |
| unsupportable claims shown as grounded | 9 of 40 | 5 of 36 |
| injection / out-of-scope / advice recall | 0.18 / 0.18 / 0.45 | 0.60 / 0.50 / 0.40 |

¹ same code as the first run, with a scorer bug fixed; the original first run is kept next to it.

The honest reading: identifier handling generalised, the verifier improved, and the regex guards did not generalise.
The next work is a German clinical NER model inside the gateway for unlisted people and a trained guard classifier,
both measured on a new blind set.

**Tests:** 79 Python (PostgreSQL and the real Go gateway in the loop), 42 Go test functions with `-race`, 35 Vitest
component and unit tests, 4 Playwright end-to-end tests against the running stack. CI also runs the evaluation gate,
checks the held-out pins, validates Terraform and builds the images.

## Run it

Without containers (PostgreSQL with an empty database, Go 1.24, Python 3.12, Node 22):

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
(cd web && npm ci && npm run build)
export CTA_DATABASE_URL=postgresql://user:pass@localhost:5432/cta
cta serve --local-stack            # API, console, Go gateway and simulated model; prints demo tokens
ctasim seed --api http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 and sign in with `demo-clinician`, `demo-coordinator`, `demo-quality` or
`demo-other-hospital`.

With Docker: `docker compose up --build` (console on :8000, Jaeger on :16686, Grafana on :3000).

Evaluation: `cta eval offline --set dev --candidate v2@sim-careful --baseline v1@sim-careful --local-stack`,
`cta eval judge --set dev --local-stack`, `cta heldout score --set v1 --local-stack` (regression sets only).

## Limits

- **No real model and no real patient documents were used.** Everything runs against a simulated model and simulated
  documents. The simulated model's errors are, by construction, ones the verifier knows, so golden-set accuracy is a
  regression test of the pipeline, not a forecast of accuracy with Claude on real records. The Bedrock and Anthropic
  paths are implemented and unit-tested (SigV4 against AWS's test vectors) but have not been called.
- The blind sets are small (55 to 68 items per component) and written by one author each.
- Provider matching (which care home to ask) is not built: the router knows the workflow and answers that provider search is not configured.
- The regulatory notes are an engineering position, not legal advice.

## Repository

```
gateway/            Go egress gateway (pseudo, identity, sigv4, upstream, server, config, metrics)
src/cta/            platform: api, agent/, grounding, guardrails, drafts, cases, fhir, prompts, evaluation, heldout
src/ctasim/         simulated documents, simulated model, golden-set export, demo seeding
web/                console (features: cases, review, quality, runs, session)
config/             profile, grounding rules, guards, agent limits, evaluation gate, gateway policy, access roles
prompts/            versioned prompts (drafter v1, v2; router; case chat; summary judge)
eval/golden/dev/    golden set; heldout/ blind sets and the writing guide; reports/ committed results
deploy/             Dockerfiles, Terraform, collector, Prometheus, Grafana dashboard
docs/               design, evaluation, intended purpose, runbook, research, ADRs, screenshots
```
