# LAB-Bench ProtocolQA and SeqQA

The owned runner is in `scripts/labbench/`. It evaluates the 108 ProtocolQA and
600 SeqQA public MCQs at upstream revision 998a8e0a40cf116c80e1b0e7a805ebb5fb9fa838.
Only baseline and native ObjRun run. OpenRouter is pinned to DigitalOcean.

`prepare.py` freezes identical public inputs and private option permutations for
both arms. `controls.py` performs server acceptance with synthetic model responses.
`controller.py` gates the full run on the fixed 20-question, two-arm canary.
`ops.py` deploys, launches with a credential received over stdin, pulls compact
state, and retrieves the complete archive. `verify_local.py` checks full delivery.

G is parsed -> correct. Format failures may receive a format instruction;
correctness feedback contains only the boolean and an empty note. The private
grader compares option identity, not text similarity, and never calls a model.
All 5--8 choices, including the randomized abstain choice, are preserved.

The full method receives oracle correctness feedback. Final success can include
option exclusion and does not establish biological reasoning repair. The known
duplicate-option item remains in primary scoring and is excluded only in the
prespecified sensitivity summary. Complete results retain all candidates, raw
requests/responses, fees, feedback, traces, databases, source and dependency pins.
