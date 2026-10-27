# Runbook

## Deploy

1. CI is green: tests, evaluation gate, held-out pins, Terraform validate, images.
2. Push the images to ECR; `terraform apply -var-file=<env>.tfvars` in `deploy/terraform` (eu-central-1).
3. Run migrations once as a one-off ECS task with the agent image: `cta migrate`.
4. Watch the dashboard "Care transition agent" for 30 minutes: runs by outcome, verdicts, review actions, gateway
   refusals.

A failed deployment rolls back by itself (ECS circuit breaker).

## Roll out a prompt or a model

1. Offline first: `cta eval offline --set dev --candidate vN@model --baseline <production> --local-stack`. The gate
   must pass: no major field wrong but shown as grounded, accuracy not worse (paired bootstrap), review load and tokens
   within limits, no identifier at a provider.
2. Canary: in the console (Quality, Prompt versions) or `cta prompts deploy --tenant T --prompt profile_drafter
   --version vN --model M --share 0.2`. Cases are assigned by a stable hash, so a case stays in its arm.
3. Compare the arms in Quality, "In service": grounded values accepted unchanged, values changed, flags that were
   right, seconds per field. Look again after a week of normal volume.
4. Promote with `--share 1`, or withdraw. Withdrawal takes effect for the next run.

## Alerts and what to do

| Signal | Likely cause | First action |
|---|---|---|
| `cta_gateway_leaks_blocked_total` rises | documents with identifiers the replacer misses (a new form, a new OCR source) | find the document kinds in the case store (blocked documents are marked), add a regression case to `gateway/internal/pseudo`, fix, write a new held-out item set |
| `cta_gateway_policy_denied_total{reason="route"}` | a tenant asked for a processor its contract does not name | a configuration error; never widen the tenant's list without the contract |
| runs with `status="budget_exceeded"` | a document set larger than the context budget, or a loop | check `cta_agent_model_calls_total` per run; raise `config/agent.yaml` limits only with an evaluation run |
| grounded values edited more often | the drafter or the documents changed | compare by prompt arm in Quality; withdraw the canary |
| `conflict` verdicts rise | stays get longer, more documents per case | expected; check that the latest statement is the one shown |
| gateway 5xx and retries | provider throttling (429/529) | retries with jitter are automatic; check the daily token budget and Bedrock quotas |

## Suspected identifier at a provider

1. Stop model calls for the tenant: remove its upstreams in `config/gateway.json` and redeploy the gateway (requests
   then fail closed; drafting stops, review of existing drafts continues).
2. Find the request: the gateway logs request ids and identifier kinds, never values; the agent's `runs` and
   `run_steps` link run, case and model calls.
3. Reproduce with the document in a local stack, add the case to the gateway tests, fix, re-run the held-out sets
   (the set becomes a regression set if you study it).
4. Inform the hospital's data protection officer through the agreed process; Bedrock does not store prompts or
   train on them, which the notification should state with the request times.

## Keys and retention

- Per-tenant data keys live in `CTA_KEYRING` (Secrets Manager), each wrapped by the tenant's KMS key.
- `cta retention purge --tenant T` deletes document ciphertext past the tenant's retention days (crypto-shred); case
  rows and the audit trail stay. Schedule it daily.
- Rotating a tenant key: add the new key, re-encrypt with a maintenance job, remove the old key. The audit chain is
  unaffected.

## Audit

`GET /api/audit/verify` (AI team role) or `audit.verify` checks the hash chain per tenant. The table rejects updates
and deletes at the database level.
