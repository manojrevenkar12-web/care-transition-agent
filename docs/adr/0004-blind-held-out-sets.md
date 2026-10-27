# 0004: Blind held-out sets, run once, pinned

**Decision.** The pseudonymiser, the verifier and the guards are measured on sets written by someone who has read only
`heldout/WRITING_GUIDE.md`. Each set runs once; its first run is pinned by hash and checked in CI. Studying a set's
failures turns it into a regression set, and a new blind set measures the fix.

**Why.** Rule-based components overfit to the examples their author has in mind. Set v1 showed it: listed-identifier
recall 0.85 and guard recall around 0.2 on text the code had not seen, while the unit tests passed. After studying v1,
set v2 measured the fixes honestly: identifier recall 0.97 and far fewer documents reaching the model with an
identifier, but injection recall 0.60 and scope recall 0.50, which says the regex guards do not generalise.
