# 0005: Develop and gate against a simulated model behind the real gateway

**Decision.** Tests, the evaluation gate and the demo use a simulated model that speaks the Anthropic Messages API,
sits behind the real gateway, reads only pseudonymised text, and makes errors at configured rates that respond to the
prompt's instructions. Real models plug in by configuration (`bedrock-eu`, `anthropic`).

**Why.** Reproducible, free, and runnable in CI without patient data or keys; it exercises everything except the
model's own judgement.

**Limit.** The simulated errors are, by construction, the kinds the verifier knows. Numbers on the golden set are a
regression test of the pipeline, not a prediction of accuracy with Claude on real documents. Before production, the
golden set must be run against Bedrock and labelled real documents must be added under the hospital's agreement.
