# Distill — extract skills from verdict history and test them on held-out tasks

This is the TgEngin version of agentos's “degrade → crystallize → enter the forest” stage. **The kernel is unchanged**:
outputs are rows in the `skill` table (loaded through `POST /declare`), and triggers are conditions in the `trigger` table.
The main difference is validation: **a skill is useful only if it improves the U arm on tasks it has never seen**.
Changing ✖ to ✓ on the same task does not count (case 7490 in the agentos usage casebook was falsified this way: one task flipped, but four related tasks scored 0/4).

## Four steps

```
cd app                                   # Run all Bun scripts from app/ (Bun hits statx reading .env on this node).
set -a; . ../.env; set +a                # OPENROUTER_API_KEY
D=../runs/distill-cmt
bun ../examples/distill/run.ts harvest ../runs/cmt-f-0731/h2h.sqlite ../runs/cmt-u-0731/unaided.csv --out $D/harvest.json
bun ../examples/distill/run.ts extract $D/harvest.json --only <training-half-ids> --out $D/candidates-A.json
bun ../examples/distill/run.ts land    $D/candidates-A.json $D/harvest.json --domain physics --corpus <training-half-ids> --out $D/declare-A.json
bun ../examples/distill/run.ts probe   $D/declare-A.json $D/harvest.json --only <held-out-half-ids>
bun ../examples/distill/run.ts pool    $D/candidates-A.json $D/harvest.json --domain physics --corpus <training-half-ids> --out $D/declare-pooled-A.json
```

| Step | What it does | Model call |
| --- | --- | --- |
| `harvest` | Read graded raw text and verdicts at every node of each task from the F-arm database, paired with U-arm results; by default, retain only tasks solved with feedback but not without it | No |
| `extract` | One candidate per task: `does` / `body` / trigger terms copied verbatim from the prompt / category labels | Yes |
| `land` | Apply four gates (`app/src/distill/gate.ts`), then combine passing candidates into a declaration; trigger = domain + root station + at least two trigger terms co-occurring in the prompt | No |
| `probe` | Without running the engine, calculate which prompts would trigger a declaration | No |
| `pool` | Second stage: combine lessons from multiple individual tasks into one domain-level skill, triggered only by domain | Yes |

## Four gates

| Gate | What it rejects | Adapted from |
| --- | --- | --- |
| Fingerprint | A body containing any raw text graded for this task, whether correct or incorrect | Task-number fingerprints in `degrade/submit.py` |
| Terms in prompt | Trigger terms must be exact substrings of the prompt; otherwise the engine's `contains` never matches and reports no error | Silent nonactivation |
| Two-sided probe | Trigger terms must match the source task and at least one other corpus task, but no more than 30% | `locate.probe_for` |
| Other tasks' answers | A body containing raw text graded correct for another corpus task | — |

**What the gates cannot catch**: answers paraphrased into prose (“For this type of model, the correct statement is X”). When graded raw text is an option letter such as `\boxed{c}`,
the fingerprint gate cannot catch prose. Held-out validation is therefore mandatory.

## Held-out validation (CMT, 2026-09-27)

Training half = 25 even-indexed tasks; held-out half = 25 odd-indexed tasks; control = the 25 corresponding held-out rows in `runs/cmt-u-0731`.

| Stage | Result |
| --- | --- |
| Training tasks solved because of feedback | 16 |
| Per-task skills, AND across all terms | 14 matched only their own task, 2 had terms absent from the prompt, 0 landed |
| Any two terms co-occur | 2 landed, triggered on **0/25** held-out tasks |
| Pool into one domain-level skill | Passed gates; held-out U-arm run is in `runs/cmt-u-distill-B/` |

`runs/cmt-distill-holdout.sh` connects the full pipeline above; `runs/cmt-arm.sbatch` accepts `SKILLS=` and `TGENGIN_CMT_ONLY=`.

## Full-set validation (extract from CMT 50, test on the same 50, 2026-09-27, `runs/cmt-u-distill-all`)

The user specifically requested this run that tests on the extraction tasks: extract one skill from each of 30 tasks solved because of feedback, then attach all 26 that pass the fingerprint gate (including 22 matching only their own task), plus 1 pooled skill.

| Group | n | Baseline U | U with skills |
| --- | --- | --- | --- |
| Has its own skill (extracted from this task's verdicts) | 26 | 0 | **15** |
| Pooled skill only | 24 | 13 | **5** |
| Total | 50 | 13 | 20 (+7) |

All 15 gains came from tasks with their own skill attached; all 8 losses came from tasks with only the pooled skill.
The former is answer leakage (the same skills triggered on 0/25 held-out tasks, and pooled Δ=0). The latter shows that an irrelevant domain-level checklist
has a **negative effect** on the U arm. The combined +7 cannot be treated as a benefit of the learning loop.

## ChemBench held-out validation (2026-09-27, `runs/distill-chembench/`)

Split the F 500-task subset in half within each topic: training 253 / held-out 247; baseline = the same 247 tasks in `runs/chembench-u-0731b` (167/247).
Extract one skill for each of 46 training tasks solved because of feedback → any two terms co-occur, maximum share 50% (preference tasks account for 37%) → 33 landed, 8 matched only their own task, 5 rejected.
Also pool two topic-level skills: preference (trigger `Imagine an early virtual screening campaign`, matching 94/94 training tasks and 0 others),
and toxicity (trigger any of `safety risks|hazard|toxic|safe handling`).

| Topic | n | Baseline | All 35 skills | Only 2 pooled skills |
| --- | --- | --- | --- | --- |
| chemical_preference | 93 | 56 | −2 (25 skills injected per task) | +0 |
| toxicity_and_safety | 58 | 27 | **+4** | **+5** |
| Other 7 topics | 96 | 84 | +3 | −4 |
| Total | 247 | 167 | +5 | +1 |

The 79 tasks triggering no skill gained +2 in the all-skills arm: this indicates the scale of run-to-run noise. Only toxicity's +4/+5 warrants further investigation;
`runs/chembench-u-hold-control` (a control rerun without skills) measures that noise.
The 22 individual preference skills have overlapping trigger terms, producing 25 skills per task and a negative effect. Narrow trigger coverage prevents both answer leakage and interference between skills.

**Control rerun (`chembench-u-hold-control`, no skills, same 247 tasks) = 175/247**, 8 above the baseline from two days earlier, with disagreement on 24 tasks: this is run-to-run noise. Recomputing against it:

| Topic | n | Control | All skills | Pooled only |
| --- | --- | --- | --- | --- |
| chemical_preference | 93 | 63 | 54 (−9) | 56 (−7) |
| toxicity_and_safety | 58 | 28 | 31 (+3) | 32 (+4, 4 corrected and 0 made incorrect) |
| Other | 96 | 84 | 87 | 80 |
| Total | 247 | 175 | 172 (−3) | 168 (−7) |

Conclusion: the overall effect is negative. Preference skills, whether 22 individual skills or 1 pooled skill, derail tasks the model could already solve. The only potentially positive result is the pooled toxicity skill
(+4, no regressions; toxicity disagrees on only 3 tasks between the two no-skill runs). The effect is small and requires another run before making a claim.
