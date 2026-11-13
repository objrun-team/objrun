# Understanding TgEngin: purpose, design, and reading guide

This guide is for researchers new to TgEngin. It provides a map before you read the code and explains the reasons behind the implementation. Code paths are relative to the `TgEngin/` repository root. The guide reflects the code on 2026-09-30 (the working tree after commit b45758c) and the design records in `docs/`.

Historical claims and paths below refer to that snapshot. See [Data and archives](storage.md) for the current locations of archived material.

---

## 0. In one sentence

**TgEngin is a research operating system in which the human defines the success criterion, called G; everything else—models, search, execution locations, tools, rules, and skills—is replaceable data.**

At the time of this snapshot, the paper (`latex/`) described it as a measurement protocol for a verifier channel. That is one aspect of the system. Reading this guide before the paper helps distinguish the paper's claims from its supporting evidence.

---

## 1. What G represents

Formally, G is a total function for a task, `G_τ : cand_τ → {0,1}`, evaluated by an external grader holding the reference answer y*. It is sealed, queried under a budget, and returns feedback at a declared information level (`objective/spec.ts`, paper Def. 1).

Four perspectives explain its role:

| Perspective | What G represents | Traditional counterpart | Implementation |
|---|---|---|---|
| Epistemology | A falsifiable procedure: a question is well defined only when a procedure can decide whether something counts as an answer | Popper, preregistration | The output range is restricted to bool; contract violations map to 0; there is no third state |
| Computation | A verifier: the asymmetry between cheap verification and expensive search captures task difficulty | NP verification/search | Δ = solve@N − pass@1 measures this asymmetry |
| Information | A rationed channel to reality: G is the machine's contact with the world; ĝ (self-evaluation) is its internal estimate | Experiments, Lean type checking, tests | c, K, and level set the bandwidth; note is where human knowledge enters search |
| Authority | A constitution inaccessible to the object being optimized: the human retains the authority to define completion | Kernel/user separation, immutable rewards | Sealed storage; tasks with `source=agent` cannot attach G |

Together, these make **G a data record abstracting the role of an experiment**. It may be Lean, hidden tests, SymPy equivalence, a chemistry parser, an instrument, or a wet-lab experiment: G nodes can use `http://` handles.

Two consequences follow:

- **Knowledge lives in note.** Level 0 says only that an answer is wrong; level 3 explains where it is wrong. Their difference measures the value of human domain knowledge. ChemIQ's G explicitly avoids reporting the size of the error: once bandwidth exceeds log₂m, G can become an answer-leakage channel rather than a verifier.
- **A good G certifies more and leaks less.** Lean is the limiting case: the proposition is public, with zero answer leakage. Answer-matching objectives are weaker and therefore require sealing. The long-term direction is to move each domain's G toward the Lean end, from hidden answers to public specifications (`readable=true`).

G is not a reward (a scalar used for optimization; G is a decision used for termination), a reviewer (which can be persuaded; G can only be satisfied), or a measure of improvement (G only decides whether the objective is complete; open-ended improvement requires an external threshold and a newly published objective).

---

## 2. One principle behind the design

If G defines the boundary, the system needs to meet three requirements:

1. **Everything outside G must be unable to access G directly.**
2. **Everything outside G must be replaceable.**
3. **Every response from G must be recorded.** Scores can only be computed from G's verdicts.

| Design | Requirement | Purpose | Location |
|---|---|---|---|
| No concrete mode, tool, rule, or agent names in the kernel | Replaceability | Nothing outside G has privileged treatment | Header comment in `engine/loop.ts` |
| Schemas generated from declarations; `task_{mode}` and `agent_{name}_ctx/_msg` subtables derived from data | Replaceability | Declare mechanisms and agents at runtime without shutdown or code changes | `install/index.ts`, `install/tables.json` |
| The handle table unifies `fn:` and `http://`, with two validation layers | Replaceability | Execution units and G nodes can be external services | `engine/registry.ts`, `docs/tables.md` |
| The place layer supports local, WSL, containers, SSH, and browser tabs | Replaceability | Run the same engine in different execution environments | `place/`, `examples/place` |
| Search strategy is an `infer` handle | Replaceability | Change one function to change search, leaving the kernel intact | `tree/dfs.ts` |
| The trigger table governs tools, skills, and rules | Replaceability | **An evolvable layer:** self-improvement takes the form of inserting rows | `engine/trigger.ts` |
| G definitions live in the separate `db.sealed` database; the main database remains fully exposed | Inaccessibility | Enforce lack of access structurally, rather than by convention | `objective/store.ts` |
| Tasks with `source=agent` cannot attach G; enforcement is at the single entry point | Inaccessibility | Agents cannot define their own success criteria | `tasks/publish.ts` |
| `verify` reads the task ID from the database instead of accepting it from the caller | Inaccessibility | An agent cannot query another task's G | `objective/tool.ts` |
| Closed bool / bool[n] output ranges; violations map to 0; ten static publication checks | Inaccessibility | G is total and decidable | `objective/spec.ts` |
| ĝ guides internal progress; G checks claimed completion | Inaccessibility | Internal autonomy does not grant authority to certify success | Header comment in `tree/dfs.ts` |
| c, K, and T budgets plus an enumeration null model | Inaccessibility | Ration channel bandwidth | `objective/tool.ts`, paper Prop. enum |
| Verdicts enter the context as `verify` tool results | Recording | Treat the channel as a first-class part of the protocol | `msg/deliver.ts` |
| The database is the snapshot; death, state, and scores are derived | Recording | No participant writes a score directly | `engine/loop.ts`, `docs/loop.md` |
| `kind` is derived from who inserted a record, rather than supplied by callers | Recording | Attribute human, rule, tool, and model contributions without caller forgery | `msg/deliver.ts` |
| Compression levels l1–l4 are persisted; the current node stays verbatim | Recording | Reproducible context | `msg/press.ts` |
| `/check`, `/trigger/check`, and `/trigger/explain` run automatically at startup | Recording | Silent failures contaminate measurements | `trigger/check.ts` |

The historical migration document, `docs/迁移.md`, lists engineering invariants under its “theorems” section. These are the engineering form of the three requirements above and were intended to be read before the code.

---

## 3. The lifecycle of one task (see `docs/loop.md`)

```text
Publish: human supplies d + G → static validation → seal G → persist entry unit → start timer T
Attempt: ask (all ancestor messages + structured view) → act (tools) → optional verify(x), at most c times per attempt
Hand in: submit is called / nonempty text is produced / work budget is exhausted
         H1: no submission → 0; H2: exact match to an earlier verified candidate for this task → reuse verdict; H3: evaluate G
Verdict 1 → reached; verdict 0 → dead
After death: dead nodes < K and t < T → new node; inherit full context, reset c and U, do not inherit artifacts
t = T → close the task and evaluate the last submitted candidate once more for the final verdict
```

N = (K+1)(c+1)+1 is the maximum number of grader calls for one task. The score curve S(n) is accumulated per task from the checks table.

---

## 4. Position in the literature

### 4.1 Layers

| Layer | Examples | Question answered |
|---|---|---|
| Application | AI Scientist, autoresearch, benchmark evaluation | What is it used for? |
| **Runtime / protocol** | **TgEngin**, LangGraph, Temporal | Who holds the criterion, who can query it, how often, and what is recorded? |
| Criterion G | Lean, hidden tests, SymPy, parsers, experiments | What counts as completion? |
| Solver | Models, sampling, RLVR strategies | How are candidates generated? |
| Laws | Monkeys, Snell | How far can a solver progress against G? |

Lean is a G (`examples/benchmark/minif2f/G.md` attaches Lean as a node), Monkeys describes a law about G, and TgEngin is a runtime for attaching arbitrary G. They occupy different layers.

### 4.2 Where G is used and who writes it

| | After generation | In the inference loop | During training |
|---|---|---|---|
| General formalization (Lean) | Prover sampling | Interactive proving | AlphaProof |
| Human-authored, domain-specific | **Monkeys**, SWE-bench | Reflexion, CodeARC, **TgEngin** | RLVR |
| Model self-evaluation | Majority voting | AI Scientist | Self-rewarding |
| A system modifying itself | | | DGM, STOP |

TgEngin shares a cell with Reflexion and CodeARC. Its distinguishing properties are an arbitrary DAG for G, query budgets and information levels, and a runtime that seals G. It can be understood as **RLVR without weight updates**.

### 4.3 A central distinction: where information from V is written

| | Monkeys | TgEngin | RSI (STOP/DGM/AlphaEvolve) |
|---|---|---|---|
| Where V's information goes | Nowhere; used only for selection | Context | The system itself: code, harness, or weights |
| Lifetime | 0 | One task | Permanent |
| Assumed cost of V | Cheap and parallelizable | **Expensive; minimize calls** | Cheap enough to evaluate thousands of variants |

- **Monkeys' pass@k is the current generator's capability envelope.** TgEngin's H1 asks whether sequential conditioning can exceed that envelope with the same number of V calls. This probes a necessary condition for RSI: if information cannot help within one task's context, retaining it across tasks is even harder.
- **RSI requires reliable, inexpensive verification** (the “law” in MetaRSI). TgEngin packages it as a portable, programmable, sealed artifact. The architecture has three layers: G (human-authored and invariant) → engine (fixed) → skills/rules (evolvable). Its structural answer to RSI safety is that G defines the boundary and is outside the object being optimized.
- **AI Scientist has ĝ rather than G:** a model scores itself, the self-elevation of authority that TgEngin's admission check forbids.
- **autoresearch gets the crucial read-only evaluation rule right**, but its G is one scalar in one domain, protected by a convention in program.md, with unlimited queries. TgEngin generalizes this into a protocol across domains. See the item-by-item comparison at the end of `docs/loop.md`.

### 4.4 Three null models (also applicable to RSI)

| Null model | Meaning | Who needs it | Available evidence |
|---|---|---|---|
| Enumeration | When the answer space is no larger than the budget, success may only show that the budget was sufficient | Every benchmark with a verifier in the loop | 15 of 26 CMT recoveries were enumeration |
| Selection bias | The RSI outer loop performs best-of-k selection over system variants; noise alone can produce apparent improvement | DGM, AlphaEvolve, ADAS | ChemBench reruns with identical configuration: 167 vs 175 (about 10% noise) |
| Answer feedback contamination | Improving and testing on the same problems can amount to memorizing answers | RSI without held-out evaluation | — |

---

## 5. Why it works

**Δ ≈ coverage (model) × asymmetry (task) × bandwidth (G) − leakage (enumeration)**

| Factor | Mechanism | Evidence (V4-Flash-0731, six U/F benchmarks on 2026-09-26) |
|---|---|---|
| Coverage | Current models have pass@k ≫ pass@1: answers are in the distribution but are hard to select. G lets the model prune using verdicts | CMT 26→86; miniF2F 44→77 |
| Asymmetry | G recovers the advantage of verification being cheaper than search | Δ grows with answer-space size: AIME reaches the ceiling, GPQA +3.5, CMT +60 |
| Bandwidth | note places human diagnostics where they affect every attempt on every task in a domain | DeepSWE: the next candidate is accepted 33% of the time after >90% of new behavior tests pass, versus 2% when ≤50% pass |
| No self-certification | A common agent failure is declaring completion too early. Removing that authority turns the first failure into a second attempt with actual feedback | 11 CMT recoveries came from revised derivations |
| Leakage (negative term) | When N ≥ m, G can reveal the answer through enumeration; the system flags and subtracts this case | CMT 15/26; ChemIQ 226/816 are enumerable |

Two engineering properties also matter. Integrating a domain requires roughly a hundred lines for G (757 lines across eight domains; see `examples/benchmark/*/G.md`), keeping changes small. Scores are derived from traces, null-model contributions are subtracted, and paired pass@1 results are reported, making the numbers auditable.

**Δ depends on the model generation.** It is large when models have broad coverage but low first-attempt accuracy. As pass@1 approaches pass@k, Δ shrinks, as already seen on AIME. G cannot create candidates. TgEngin's long-term value lies in the three requirements, rather than the size of Δ.

---

## 6. Why the database design merits its own review

“The system is the database”: the kernel is stateless; trees, context, rules, tools, verdicts, and costs are rows. The one separating wall is the other database file holding G. The individual components have precedents (event sourcing, Temporal, Smalltalk images); their combination for agents is new.

Implications for automated research:

- The experiment record is the machine itself; results cannot be fabricated or hallucinated.
- Self-improvement inserts rows (skill + trigger), which can be diffed, rolled back, and evaluated with held-out A/B tests without accessing G. Compared with DGM modifying its own code, this is the safest form of RSI.
- `kind` cannot be forged by a caller, so human and machine contributions are attributable.
- Copying `h2h.sqlite` copies an experiment (`runs/*/` uses one database per run).

---

## 7. Known limitations and open work at this snapshot

| Category | Details |
|---|---|
| Formalism | G is Boolean and covers verifiable science. Open-ended improvement has no native representation. Choosing the research question remains outside the system |
| Encapsulation | Isolation is not adversarial security. Rules run at four moments but **do not intercept** actions; there is no `pre_call` (see the historical `paper2/README.md`). A network-accessible public corpus can expose answers, as ChemIQ's G.md acknowledges |
| **Security (high priority; not yet audited in this snapshot)** | The default token in `config.yaml` is empty, `allowWrite: true`, and the engine listens on 127.0.0.1:7801. If solver bash/Python runs on the engine host (`place=local` benchmarks), it could theoretically use `curl /api/exec` to modify the checks table. **The runs' tools tables had not yet been checked for access to 7801 or `/api/`.** Disable writes and configure a token for benchmark runs |
| Scalability | Every kernel tick scans `done=0`; SQLite has one writer; the database is on Lustre. Dozens of concurrent tasks work, while thousands would require sharding |
| Experimental gaps | P-arm pass@n uses only n∈{4,8}, while N=64–100; sampling needs n≥N. The L arm (levels 0–3), needed to establish the value of G's content, had not run. Only one model was used, and G authoring costs were not quantified |
| Paper | The text still said pass@1 had not been measured, despite the six U-arm runs from 9-26. Fig. 1's six old result groups came from another system and were obsolete (historical `01-数据总表.md`) |

---

## 8. Suggested reading order

1. The “theorems” section in historical `docs/迁移.md`, then all of `docs/loop.md`.
2. Header comments in `engine/loop.ts` and `tree/dfs.ts`, then `objective/{spec,store,tool}.ts`.
3. `tasks/publish.ts` (the single entry point and admission check) and `declare/index.ts` (whole-declaration validation).
4. The trigger, rule, tool, and skill sections of `docs/tables.md`.
5. Any `examples/benchmark/*/G.md`; chemiq is recommended for its complete field set, m table, and known pitfalls.
6. Historical `runs/bench-arm.sh`: starting a run, isolating its database, and grading the U arm after execution.
7. Historical paper files `latex/sections/03-protocol.tex` and `06-preregistration.tex`.

When writing G for a new domain, follow the fields in chemiq/G.md: source, cand, structure, h_r, boundary, budget, level, m, and known pitfalls. **The m table is required** to compute the enumeration null model.

---

## 9. Other related historical material

The original filenames below are preserved so archived records remain identifiable:

- `01-数据总表.md`: U/F results and sources for each benchmark.
- `02-实验设置与目的.md`: preregistered experimental arms.
- `paper2/`: rules as boundaries (the second paper).
- `tgengin-*` entries in the Obsidian memory directory `Claude记忆/`: operational pitfalls, model aliases, and throughput.
