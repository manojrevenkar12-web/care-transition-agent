# Intended purpose and regulatory position

This is an engineering position for discussion with regulatory affairs, not legal advice.

## Intended purpose

The software helps discharge-management staff of a hospital prepare the administrative transfer profile that care
providers use to decide whether they can accept a patient. It extracts facts that are already documented (care type
requested, discharge date, Pflegegrad, mobility, orientation, oxygen, ventilation, dialysis, PEG, wound care,
catheter, insulin, multi-resistant organisms, insurance, legal representation), shows where each fact is written,
and answers questions about what the documents say. A clinician checks and releases every profile.

It does not diagnose, recommend or change treatment, dose medication, predict outcomes or prioritise patients. Questions
that ask for those are refused before any model is called; answers that contain treatment advice are held back.

## Medical device regulation

MDCG 2019-11 treats software whose intended purpose is administrative (transfer of patient data, organisation of
care) as not being medical device software, as long as it does not create new clinical information or drive clinical
decisions. The design keeps to that line: values are copied from the documents with their evidence, nothing is
inferred that is not written, and the guards keep the assistant out of clinical decisions. A change of intended
purpose (for example ranking providers by clinical suitability or flagging deterioration) would need a new
qualification.

## EU AI Act

As administrative software that is not a medical device or a safety component of one, the system is not high-risk
under Article 6 on that route. People interacting with the chat are told they are using an AI system (Article 50).
Human oversight, logging, accuracy measurement and documented limits are built in regardless, because a hospital
customer will ask for them.

## Health data

- GDPR Article 9: health data is processed on the hospital's legal basis for care and discharge management; the
  vendor is a processor under a data-processing agreement.
- §393 SGB V: cloud processing of social and health data for statutory health insurance purposes requires a current
  C5 attestation of the cloud service; the deployment uses AWS Frankfurt (C5 Type 2) and Bedrock in the EU region.
- Data minimisation: models see pseudonymised text only; identity is sealed at import; logs and traces carry no
  content; documents are encrypted per tenant and crypto-shredded after retention.
- No training on customer data: the platform sends inference requests only; prompts and evaluation sets are synthetic.
