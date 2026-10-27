# Evaluation

Four kinds of evidence, each answering a different question.

## 1. Offline: the golden set (does a change make drafts better or worse?)

`eval/golden/dev/` holds 60 simulated cases (1,140 fields) with known facts, written by `ctasim golden`: German
admission forms with OCR damage, nursing notes, social-services notes, discharge letters and lower-case dictations,
with traps (a fact that changed during the stay, negations, a relative's condition, history, injected instructions).

Each field of a draft is classified the CREOLA way (Asgari et al., 2024): correct and shown as ready, correct but
flagged, rightly left empty, omission (asked or silent), and wrong by fabrication, negation, context or other,
split by whether the wrong value was shown as ready or flagged. Metrics:

- **major wrong but ready**: a wrong value on a major field that the console showed as grounded. Must be 0.
- **field accuracy**, with a paired bootstrap over cases against the baseline (2,000 resamples, 95 %).
- **review load**: right values the verifier flagged anyway (a clinician's wasted click).
- **tokens and model calls per case**.

`cta eval offline --candidate A --baseline B` exits 1 when the gate in `config/evaluation.yaml` fails. CI runs it for
the current production prompt against the candidate.

| Run (current code) | Field accuracy | Major wrong but ready | Review load | Fabrications | Tokens per case | Gate |
|---|---|---|---|---|---|---|
| drafter v2 on sim-careful | 97.4 % | 0 | 3.1 % | 0 | 20.7 k | passed against v1 |
| drafter v1 on sim-careful | 96.0 % | 0 | 7.2 % | 40 | 19.4 k | |
| drafter v2 on sim-hasty | 88.0 % | 0 | 15.1 % | 4 | 22.3 k | failed against v2 on sim-careful |

v2 against v1: paired accuracy difference +0.013 (95 % CI +0.004 to +0.024). v2's prompt adds the rules that
matter for this task (copy the words, newest statement wins, negations, an unknown is an answer, text addressed to an
AI is not an instruction, only the patient now); the simulated model responds to them, so fabrications disappear.
The hasty model shows the gate doing its job: no wrong value reaches "ready" (the verifier catches them) but the
review load quadruples and accuracy drops, so it does not ship.

## 2. LLM judge calibration (which judge criteria can be trusted?)

The summary field is free text, so it is graded by an LLM judge on four criteria. Before a criterion is used, its
agreement with clinician labels (`eval/golden/dev/judge.jsonl`) must reach Cohen's κ ≥ 0.6.

| Criterion | κ | Used |
|---|---|---|
| covers the care needs | 0.75 | yes |
| no treatment advice | 0.84 | yes |
| faithful to the documents | 0.57 | no: the verifier and the clinician check faithfulness |
| no identifiers | −0.01 | no |

The last row is a finding, not a bug: the judge sees the summary after pseudonymisation, so it cannot tell whether an
identifier was there. Identifier checks belong to the gateway, which is deterministic and measured separately.

## 3. Blind held-out sets (do the deterministic parts work on text their author never saw?)

Written by someone who read only `heldout/WRITING_GUIDE.md`, run once, pinned in `heldout/first_run.sha256`.

| | v1 first run | v1 rescored¹ | v2 first run (after studying v1) |
|---|---|---|---|
| listed identifiers replaced | 79.9 % | 85.3 % | **96.7 %** |
| documents with a listed identifier reaching the model | 30 of 55 | 21 of 55 | **7 of 55** |
| unlisted identifiers replaced | 70.7 % | 70.7 % | 66.3 % |
| clinical words destroyed (must-keep) | 11 of 326 | 11 of 326 | 3 of 402 |
| verifier correct | 75.0 % | 75.0 % | 79.0 % |
| wrongly grounded (unsupportable claims shown as grounded) | 9 of 40 | 9 of 40 | 5 of 36 |
| injection recall / precision | 0.18 / 1.00 | | 0.60 / 1.00 |
| out-of-scope recall / precision | 0.18 / 0.67 | | 0.50 / 0.71 |
| advice recall / precision | 0.45 / 0.56 | | 0.40 / 1.00 |

¹ The first scorer counted names inside other words ("Stern" in "Sternotomie") as misses. The rescore runs the same
code (enforced: the components must be byte-identical to the first run's commit) with the fixed scorer.

What this says:

- Identifier handling generalised: the normalised views and the independent leak check cut documents with an
  identifier at the model from 21 to 7 of 55. Seven is still not zero; each is a dictation or OCR pattern the
  rules do not know, which is why production needs the leak check, the tenant's own contract with the processor, and
  a learned recogniser in addition (next step).
- People the record does not list are found two times in three. Rules will not close that gap; a German clinical NER
  model inside the gateway's trust boundary is the next piece of work.
- The verifier improved and still marks 5 of 36 unsupportable claims as grounded on blind text. That is the number
  that bounds how much a reviewer can trust "ready" today.
- The regex guards do not generalise (injection recall 0.60, scope 0.50 on unseen phrasing). They are a filter, not the
  defence: documents are always data to the model, evidence from flagged text is rejected, and the clinician releases.
  A trained classifier calibrated on these sets should replace them.

v2 has not been studied. When it is, it becomes a regression set and v3 is written blind.

## 4. Online (what do clinicians do with the drafts?)

No labels are needed in production: every review action is an event with the verifier's status, the prompt version
and the model. Quality → In service shows, per prompt arm, how often grounded values are accepted unchanged, how
often they are changed, how often a flag was right, and seconds per field. A canary prompt is compared with
production on these numbers before it is promoted.
