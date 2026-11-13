# The TgEngin task loop (compared with autoresearch's program.md)

Checked against the source at b45758c plus uncommitted press.ts changes: `objective/spec.ts`, `objective/tool.ts`, `tree/dfs.ts`, `engine/loop.ts`, and `msg/press.ts`.
Section 9, Methods, of the paper is its formal counterpart.

## Responsibilities

| File/process | Contents | Who can modify it |
|---|---|---|
| Grading process (`examples/benchmark/*/grader.py`, separate container/port) | Reference answer y*, hidden tests, evaluator nodes (CMT `parsed→equiv`; DeepSWE `applies→resolved`), information level `--level` | Human; the solver cannot access it |
| Sealed storage (`objective/store.ts`) | G's definition (V, E, r, c): nodes, edges, output node, and per-attempt query allowance | Written once at publication, then read-only; inaccessible even through the main database's full API |
| Task description d | Problem statement without the reference solution; if readable, also G's definition without the answer | Publisher |
| Solver (`deepseek-v4-flash`, T=0, seed 42) and tools (bash/read/write/edit/glob/grep, or retrieval + Python) | Perform the task | Identical across arms, except for whether `verify` is attached |
| Trace tables (units / checks / tools) | One row per execution unit, evaluator call, or tool call | Written by the kernel; scores are computed from these records, never stored |

## Publication (once per task)

```text
0. The publisher supplies d + G; the kernel checks (W1)–(W6): valid edges, no cycles,
   one sink, a Boolean sink, an incoming edge to the sink, and every port connected.
   Any failure rejects the entire batch.
1. Seal G; c (the per-attempt query allowance) belongs to G, rather than the task.
2. Persist the first unit (entry cycle); start wall-clock budget T (CMT 3600 s, DeepSWE 7200 s).
```

## One attempt (a node in the tree)

```text
LOOP attempt a_j:
  1. ask — the model sees the context: all ancestor messages plus a structured view
     of the problem, current cycle, remaining budget, and attempted nodes with their states.
  2. act — execute requested tools (bash, etc.); each cycle has at most U units (CMT 35, DeepSWE 70).
  3. verify(x) may be called during the attempt:
       - If this attempt has received fewer than c verdicts (CMT 10, DeepSWE 6),
         the grader evaluates the entire G and returns
         {pass 0/1, why, note(at the declared level), graded=original text, left=remaining allowance}.
         It returns neither the answer nor the trace.
       - If the allowance is exhausted, reject with a message; rejected requests do not count.
  4. Enter the submission cycle when submit is called, nonempty text is produced,
     or work budget U is exhausted, regardless of the agent's preference.
  5. Hand in (H1–H3):
       H1: submit was not called → verdict 0, "nothing handed in"; do not run the evaluator.
       H2: the submission exactly matches the original text of any earlier verify
           candidate in this task → reuse that verdict; do not run the evaluator.
       H3: otherwise, evaluate G once.
     Deliver the verdict into context in the shape of a verify tool result, including why/note.
  6. Verdict 1 → reached; finish the task.
     Verdict 0 → dead.
```

## After a node is marked dead

```text
  7. If the number of dead nodes is < K (8) and t < T:
       Create a new node below the closing unit. Its context contains all conversations
       and verdicts from a_1..a_j. Reset query allowance c and work budget U.
       Do not inherit artifacts: rewrite the answer; in DeepSWE, recreate the commit.
     Otherwise, finish the task.
  8. If the task remains open at t = T, close it, grade the last submitted candidate
     again, and use that verdict as the final result.
  9. Attempts that exceed the per-unit time limit also count as dead toward K.
```

## Context assembly

- Follow `from_unit` pointers to the root. Ancestors are visible; siblings are not. Under this mechanism there are no siblings: a new node is attached below the previous node's closing unit, so the chain contains the entire history.
- Compress only after `api.compress_at` is exceeded (DeepSWE: 900k), and only closed nodes. The current node always remains verbatim. Verdict rows are always retained: the verdict part of a hand-in record is keep/keep/keep; a verify result is single-line JSON and is not cut by tail/sample.
- The CMT run predated the compression implementation and used verbatim context throughout.

## Prohibited actions (corresponding to autoresearch's read-only prepare.py)

| Rule | Enforcement |
|---|---|
| Only a human can attach G; agent-derived tasks cannot carry G | Publication route and admission checks |
| The solver cannot read y* | The grader exposes only ν(x); DeepSWE separates work and grading containers with networking disabled; CMT uses an audit on the shared host |
| verify can only query its own task | `verify` reads the task ID from the database rather than accepting a caller-supplied ID |
| Disabled tools receive zero calls | Audit `tools.csv` for each run (DeepSWE: web_search 0, python_exec 0) |
| Scores are not stored | Compute them from trace tables according to their definitions |

## Recorded data (corresponding to results.tsv)

| Table | One row represents | Key columns |
|---|---|---|
| units / stations | One execution unit | node, cycle(ask/act/submit), status, seconds, tokens |
| checks / verify | One evaluator call | pass, why, note, graded, left, reused, asked_by(agent/submit) |
| tools | Per-tool call counts | bash 16,782 … verify 642, submit 341 |
| tasks | One task | state, pass, first_answer_pass, nodes, seconds |

The score is the fraction of tasks with pass=1. The curve S(n) is accumulated from per-task evaluator call counts in checks.

## Comparison with autoresearch

| | autoresearch | TgEngin |
|---|---|---|
| What the agent changes | train.py; commits accumulate | One answer or commit, rewritten for each attempt |
| Read-only components | prepare.py (evaluation function) | Grading process and sealed storage (G definition + y*) |
| One evaluation | Five minutes of training, returning a real number | 3–97 s or a full test suite, returning 0/1 + why + note |
| Number of queries | Unlimited | c per attempt, at most K attempts, wall-clock budget T |
| Keep/discard | Keep the commit if the metric decreases; otherwise git reset | Stop on verdict 1; on verdict 0, create a new node, inheriting context but not artifacts |
| Stop condition | NEVER STOP | First verdict 1, or exhaustion of K/T |
| Reported result | Final val_bpb | Full S(n) curve, first candidate, enumeration-vulnerability flag, and pass@1 (not run at this snapshot) |
