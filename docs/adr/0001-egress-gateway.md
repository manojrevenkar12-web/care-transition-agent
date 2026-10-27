# 0001: Every model call leaves through a pseudonymising gateway

**Decision.** The platform has no model credentials. A separate Go service, built with the standard library only,
receives every model request, replaces identifiers with typed tags from a sealed identity token, refuses the request
if a known identifier survives, and forwards it only to the processors the tenant's contract names.

**Why.** Instructions in a prompt cannot guarantee what leaves the hospital; a component that refuses can. A separate
service with no dependencies is small enough to review line by line and to certify on its own, and it can run in a
hospital's own network if a customer requires it. Typed tags keep the meaning the model needs (patient, relative,
physician, age) without the identity.

**Cost.** Text the model sees is not the text the clinician reads, so evidence offsets are mapped back for
highlighting; unlisted people get hashed tags that the gateway cannot reverse, so answers that mention them show tags.
