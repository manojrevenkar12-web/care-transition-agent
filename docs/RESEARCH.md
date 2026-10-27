# Research behind the design

| Question | What I found | How it shaped the project |
|---|---|---|
| What does the agent have to produce? | Recare's platform sends a pseudonymised transfer profile (Überleitungsprofil) to post-acute providers, who accept or decline; Recare's AI agent structures PDFs, scans and voice input into interoperable formats with a human approving every result. | A profile of 20 fields with evidence, FHIR Questionnaire/QuestionnaireResponse output, dictation and OCR in the simulator, release only by a clinician. |
| How should clinical extraction be evaluated? | CREOLA (Asgari et al., 2024, medRxiv) classifies errors as fabrication, negation, causality, contextual and omission, major or minor; giving the model an "unknown" option and structured function calls reduced errors. | CREOLA classes in the offline metrics, `mark_unknown` as a tool, "an unknown is an answer" in prompt v2, severity per field. |
| How should GenAI calls be traced? | OpenTelemetry GenAI semantic conventions: `invoke_agent`, `chat {model}`, `execute_tool {tool}` spans with `gen_ai.*` attributes; content capture is opt-in. | Span names and attributes follow the conventions; content is never captured; the collector drops content attributes anyway. |
| Is the tool a medical device? | MDCG 2019-11: software for administrative purposes is not medical device software unless its intended purpose is medical. | Intended purpose written down; guards keep the assistant out of clinical decisions. |
| What does German law require for cloud processing of health data? | §393 SGB V requires a current C5 attestation for cloud services processing social and health data. | AWS Frankfurt and Bedrock in the EU region; per-tenant processor lists in the gateway. |
| How are German identifiers validated? | KVNR: letter as two-digit position plus eight digits, weights 1-2 alternating, digit sum, mod 10. IBAN: ISO 13616 mod 97. | Check digits in the gateway reduce false positives on numbers in clinical text. |
| How is Bedrock called without an SDK? | Bedrock runtime `InvokeModel` with SigV4 (service `bedrock`), model id in the path (double-encoded in the canonical request), `anthropic_version: bedrock-2023-05-31`, `eu.` cross-region inference profiles. | A standard-library SigV4 signer tested against AWS's published vectors. |

## Sources

- heise online: Recare raises €37m and introduces an AI agent for care transitions (January 2026).
- Ärzte Zeitung and Igor'sLAB coverage of Recare's platform and its use in German hospitals.
- Asgari E. et al. A framework to assess clinical safety and hallucination rates of LLMs for medical text
  summarisation (CREOLA), medRxiv 2024.
- OpenTelemetry semantic conventions for generative AI (spans, agent spans, metrics), opentelemetry.io; Dash0's guide
  to the GenAI conventions.
- MDCG 2019-11 rev.1, Guidance on qualification and classification of software (openregulatory summary).
- Rödl & Partner: §393 SGB V and the C5 requirement for cloud processing of health data.
- AWS documentation: Bedrock InvokeModel, Signature Version 4 test suite, cross-region inference profiles.
