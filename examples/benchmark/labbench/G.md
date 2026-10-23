# LAB-Bench criterion

The criterion is parsed -> correct, with correct as sink and checks=5 per
native attempt. It is instantiated with owned loopback URLs by native.ts.

parsed accepts exactly one in-range option letter inside one ANSWER block, or
one bare letter, using the same parser as final scoring. Invalid formatting
receives only a format instruction. correct compares the parsed letter against
the private randomized ideal identity and returns a boolean with an empty note.

The abstain label and all displayed choices are preserved. Repeated verification
uses the same frozen permutation. No correct label, wrong-option list, reference
protocol, sequence, or hidden diagnostic enters the model context. Final scoring
uses the real deadline-bounded submit, not a verified candidate or reasoning.
