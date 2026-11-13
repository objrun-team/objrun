# Tables: design notes

> Notes transcribed from discussion; the design is not yet final. Once settled, it becomes declarations in `install/`.

## handle: one row per callable

**Manage callable identities centrally.** Every callable in the database is registered here;
other tables only reference it.

| Column | Description |
| --- | --- |
| `name` | Identity and primary key. An in-process handle name (`fn:chat.deepseek`) or an external endpoint (`http://…`) |
| `expect_ms` | **Expected duration.** Mark the unit dead when this is exceeded |

Six references point to this table:

| Table | Referencing column |
| --- | --- |
| `api` | `handle` |
| `agent` | `unit` |
| Task cycle table | `infer` |
| Rule table | `identity` |
| `tool` | `identity` |
| `skill` | `identity` |

There is no handle-category column: the referencing component already knows its purpose. Storing it again
would duplicate the same fact and allow the two copies to drift.

**Two validation layers** (installation and startup): every referenced handle must be registered here, and a `fn:` handle
must also resolve to an actual function in the process registry. Without either layer, a typo fails only when called.

## api

**Purpose:** how a model can be used and where to call it.

**A row is identified by the environment-variable name holding the key plus the model name. Together they form the primary key.**
The key itself is never stored in the database, which is readable throughout the system.

| Column | Type | Description |
| --- | --- | --- |
| `key_env` | text not null | Environment variable containing the key, such as `DEEPSEEK_API_KEY` |
| `model` | text not null | Model name, such as `deepseek-chat` |
| `handle` | text not null | In-process function handle → `handle.name`. **Only in-process handles; no external addresses** |
| `modes` | text not null | Comma-separated supported calling shapes. See the `mode` table for values |
| `base_url` | text not null | Request destination. **Stored in the table, not in code**: an address existing only in code is invisible in a snapshot |
| `retry_on` | text not null | Retryable failures: a JSON list of HTTP status codes, plus `network` for no response. Other failures are returned unchanged |
| `compress_at` | integer | Context token threshold above which compression precedes a call. Empty disables compression |

Primary key: `(key_env, model)`

### Why `compress_at` belongs to this row

The ceiling belongs to **this key and this model**, not to the kernel. In one measured run, a request used
1033906 tokens against a 1048576-token limit; three units exceeded the limit by 738 / 1714 / 4150 tokens.
This was a small overrun near the limit, not uncontrolled growth.

**The kernel has no tokenizer.** It estimates tokens from the bytes about to be sent: in one task,
4234989 bytes corresponded to the model's reported 1033906 tokens, approximately four bytes per token.

### One `handle` per row means it must support every value in `modes`

The primary key is `(key_env, model)`: one row per model, one handle per row. Therefore:

**The handle must support every value in `modes`.** If a row declares
`modes = "chat,duplex"` but its handle only supports chat, the kernel can select it for `duplex`
and invoke the chat adapter. **No error occurs; the unit simply behaves differently from what was intended.**
This particularly subtle configuration error is checked by `GET {prefix}/check`,
using the supported shapes recorded for each handle at registration.

A model supporting both request/response and real-time interaction needs **two rows**, with different model names
and handles. One row cannot represent both.

> A function handle cannot be stored in SQLite. The database stores its **name**, which the process resolves
> through an in-memory registry. External clients (TUI / desktop / Android) cannot use this column directly:
> they call the H2H API, while model invocations happen inside the process.

## mode

**Purpose:** register the supported **calling shapes**.

| Column | Type | Description |
| --- | --- | --- |
| `name` | text not null | `chat` / `tools` / `vision` / `duplex` |
| `note` | text | Meaning of this shape |

Primary key: `name`

### This table is populated from the implementation, not edited manually

As with `msg_kind`, **the values are exactly those supported by the implementation**. They are loaded at startup
and logged as the supported calling shapes, so users and `check` can inspect them.

**This is not a user-editable registry.** Otherwise, manually inserting `duplx` would make it appear valid
even though the implementation cannot recognize it. That lane would never be selected, with no error.
Therefore `check` compares against what the implementation supports, not merely against stored rows.

| Shape | Meaning |
| --- | --- |
| `chat` | Request/response. **One invocation = one execution unit** |
| `tools` | This lane supports tools |
| `vision` | This lane accepts images |
| `duplex` | Real-time, bidirectional interaction. **A session, not a single call**; one execution unit is one exchange in the session |

## Agreed rules

- **The primary key is `(key_env, model)`.** No surrogate key.
- **`handle` refers only to in-process functions.**
- **Keys never enter the database.**

## Task cycle table

**Purpose:** define execution modes. One row represents one cycle in a mode. The kernel loop drives
transitions according to this table.

| # | Column | Description |
| --- | --- | --- |
| 1 | `mode` | Execution mode |
| 2 | `cycle` | Cycle within this mode |
| — | `api_mode` | **The API mode needed by this cycle** (`chat` / `duplex` / …). Empty means the unit does not use a model |
| 3 | `max_units` | Maximum execution units allowed in this cycle |
| 4 | `from` | Rows in this table from which this cycle normally transitions; one list per cell |
| 5 | `next` | Rows in this table to which this cycle normally transitions; one list per cell |
| 6 | `infer` | Inference-function handle → `handle.name`, selecting the actual next cycle row |

### One agent with two lanes

`api_mode` was added after a real use case: a reporting agent attaches **two models at once**,
one for `chat` (reasoning and writing), another for `duplex` (live listening and speaking in meetings).
Without this column, there was nowhere to specify the lane for a unit.

The kernel selects a handle as follows:

- Nonempty `api_mode`: select an entry in `agent.apis` whose `modes` includes it, then call that row's `api.handle`.
- Empty `api_mode`: call `agent.unit`, for a unit not using a model, such as running tools requested in the preceding step.

**The kernel selects; the adapter invokes.** Repeating selection in the adapter would give two places
authority over the same decision and eventually cause drift.

### Real-time lane (`duplex`): one session, multiple exchanges

In chat, one call is one execution unit and the connection ends with the call. In duplex, **the connection is a session**,
and one execution unit is **one exchange** within a session that spans multiple units.

The **handle signature is identical to chat**: the kernel supplies one unit and receives the row to persist.
The duplex implementation therefore required **no kernel changes**. The kernel has no concept of a session;
if it did, the abstraction provided by `api_mode` would be ineffective.

Sessions live in an in-process pool keyed by `(vendor, instance)`:

- **A session is a connection, not state, and is not stored in the database.** As with `workplace.usable`, a registry
  is not a liveness check. Persisting connection state would produce stale claims after a restart.
- **Every exchange is persisted**: what was said, who said it, and requested tools all enter
  `agent_<name>_msg`. After a crash the session is gone, but its record remains, preserving database snapshots.
- Idle sessions close automatically. Reclamation is derived from elapsed time since last use, without a separate timer.

`instructions` is sent **once when the session opens**. The session remembers it, unlike chat,
which must resend instructions for every unit because the provider retains no prior turn.
Likewise, the previous tool request is not resent; doing so would make the model hear its own words again.

After the tree creates siblings, several units of one instance may be ready simultaneously and the kernel advances them concurrently.
**A session is a single stream**, so exchanges queue within it. Sending them concurrently would mix their events,
and **this would not raise an error**: each exchange could receive part of the other's response.

#### Scope of audio support

This implementation covers **the protocol only: text input, text and transcripts as output**.

Recording and playback belong to the device. Audio I/O libraries have native dependencies, which violate
the zero-native-dependency, cross-compilation constraint. Device audio can be attached above this layer later.

Outbound audio is **discarded after receipt; only its size is counted**. Persisting byte streams in `agent_<name>_msg`
would inflate snapshots to hundreds of MB and leave unreadable columns. **The transcript is the trace.**

#### Event names differ between beta and GA

DashScope's real-time endpoint uses OpenAI's *beta* event schema, while *GA* is now the common schema.
**Mismatched event names do not produce errors; they produce no usable events.** The connection remains open and events arrive,
but none are handled, so an exchange never completes. Incoming event names are mapped to GA before dispatch.
Only inbound events are mapped; outbound events keep beta names because the endpoint requires them.

Three failures in the old code were all **silent**:

1. Beta `response.done` had no usage field. Reading it crashed the **entire receive coroutine**,
   leaving all subsequent activity silent.
2. An undecodable event was skipped without clearing response state. The session remained permanently marked as speaking and stopped after one utterance.
3. Participant transcripts used the beta schema; decoding failed and the whole event was skipped, so other participants' words were never received.

The resulting rule is: **failure to decode one event discards only that event, never the connection**. Discarded events
must also be **counted**. Otherwise schema drift appears only as a model that has stopped speaking.
Known events requiring no action, such as `session.updated`, must still be listed explicitly in the dispatcher.
Treating them as unknown inflates the unknown-event counter, which is the **only** signal of schema drift;
normal events would make that signal unusable.

**Columns 4 and 5 determine column 6**, not the reverse. Once the possible incoming and outgoing rows are known,
the inference function follows those transitions.

Columns 4 and 5 store lists as JSON arrays. SQLite's built-in JSON functions allow
`json_each` to expand them at query time without an extra table.

## Task tables (a table family)

One main table plus one subtable per execution mode.

### Main table `task`: one row per task root

Two groups of fields: **identity is fixed at creation and never rewritten**; **state is a snapshot**.

| Column | Group | Description |
| --- | --- | --- |
| `id` | Identity | Root node identifier |
| `mode` | Identity | Execution mode → column 1 of the task cycle table. **Also determines the detail subtable** |
| `place` | Identity | Execution location → `workplace.place`. **Required for every task** |
| `run` | Identity | Benchmark run membership; empty means no run |
| `source` | Identity | Publisher: `user` / `agent` / `world` / `eacn`. **An admission criterion, not merely metadata** |
| `description` | Identity | Natural-language task description. Opaque to the kernel; interpreted by the agent |
| `created_at` | Identity | Wall-clock creation time |
| `workdir` | Identity | Working path at the selected location; empty means that machine's cwd |
| `max_branches` | Identity | Maximum simultaneous branches (concurrency limit) |
| `max_dead_siblings` | Identity | Dead siblings under one parent before backtracking to a higher level and changing direction |
| `solve_seconds` | Identity | Maximum solution time, in seconds |
| `objective` | Identity | Whether the task has objective `G`. **Its definition is stored elsewhere**, as described below |
| `readable` | Identity | Whether G's definition can be read directly. **Must be explicit when G is attached; there is no default** |
| `claimed_by` | State | Current owner; empty means unclaimed |
| `result` | State | Final answer, present only when `done` or `failed` |
| `state` | State | `open` / `claimed` / `done` / `failed`. **Derived from subtables, then updated** |

Primary key: `id`

These four states are the minimal set. Add `blocked`, `cancelled`, or `paused` only when required.

`failed` **cannot be inferred by counting rows**: it is a verdict. The objective component writes it explicitly
when implemented; inventing an interim derivation would make the field unreliable.

### Task publication: the single entry point

`POST {prefix}/tasks` is **the only external entry point for work**. Clients need not import an internal library.

One call creates the task row, first execution unit, matching agent-side row, and task description as the first context message.
**Either all are created or none remain.** A partial operation could leave a task row without an execution unit,
appearing in the database but never progressing and never reporting an error.

**Admission is enforced here because this is the single entry point.** Relying on one caller to omit a forbidden
parameter is not reliable: a signature change or new derivation path can remove that protection.
Admission therefore checks `source` at the entry point.

New modes or agents require no restart. Publication installs missing subtables on demand, idempotently.
Clients may also call `POST {prefix}/install` explicitly.

## press / press_l1..l4 / press_how / msg_part

**Purpose:** store compressed context and define **how each message part is handled at each compression level**.
This is a tiered cache: `l1` is closest to the original, while lower levels apply stronger compression.

```
task_{mode}.press ──→ press.id
                       ├─ l1 ──→ press_l1.id ──→ body
                       ├─ l2 ──→ press_l2.id ──→ body
                       ├─ l3 ──→ press_l3.id ──→ body
                       └─ l4 ──→ press_l4.id ──→ body   ← column exists, not configured yet

msg_part.name ──→ one press_how.name per level ──→ press_how.identity ──→ handle
```

**Four columns exist; the first three levels are configured.** A level is ready only when **every row fills that column**
in `msg_part` (`readyLevels`). `l4` is currently empty throughout: it is neither written nor sent, and degradation stops at `l3`.
The column is reserved because a future model-based summarizer will be declared externally against a running
database; adding a column at that point would require a migration.

**Empty differs from `keep`**: empty disables the level; `keep` enables it without compressing the part.

### press

| Column | Type | Description |
| --- | --- | --- |
| `id` | text not null | Referenced by `task_{mode}.press` |
| `l1` | text | → `press_l1.id`. Empty means this level has not been computed |
| `l2` | text | → `press_l2.id` |
| `l3` | text | → `press_l3.id` |
| `l4` | text | → `press_l4.id`. Remains empty while `msg_part.l4` is unconfigured |

Primary key: `id`

**Levels are columns, not rows.** A slot holds three levels simultaneously. Representing levels as rows would require
another scan to retrieve that slot's l2 on the hottest lookup path.

**The kernel does not assign IDs.** The writer of a level chooses its ID. A content hash naturally makes identical compressed results
share one row, without an extra comparison step.

### press_l1 / press_l2 / press_l3 / press_l4

All four tables have the same shape:

| Column | Type | Description |
| --- | --- | --- |
| `id` | text not null | Referenced by `press.l1` / `.l2` / `.l3` / `.l4` |
| `body` | text not null | Text replacing the original messages |
| `bytes` | integer not null | Size of `body`. **Persist it** so the next compression level can be selected by summing sizes without rereading every body |

Primary key: `id`

**Several `press` rows may reference the same row here.** That is intentional: one passage can replace multiple slots.
Readers deduplicate by ID and emit the passage once, rather than once per slot.

**One table per level**, rather than one table with a level column. A passage compressed at a particular level is one row;
different levels need not have matching row counts.

### press_how: one row per compression method

Like `tool`, each row has a name, a handle, and two schemas. **Built-in methods and methods declared externally
through `/declare` use the same row format.** Changing compression methods requires no kernel change.

| Name | Retained content | Unit |
| --- | --- | --- |
| `keep` | Everything | — |
| `drop` | Nothing, **not even an omission notice**: a notice costs tokens and repeats what the chosen level already implies | — |
| `cut` | First 2000 | Bytes |
| `top` | First 20 lines | **Lines** |
| `tail` | Last 20 lines, with the notice **at the beginning**; a trailing notice could be mistaken for the output's final statement | **Lines** |
| `sample` | First 3 lines + last 3 lines | Lines |
| `ask` | Ask a model for a one-sentence summary. **Empty `identity`: not implemented here**; model selection belongs outside the kernel | — |

Empty `identity` means the method is registered but not implemented here. Assigning it to `msg_part` raises an error
when that level is reached, rather than silently passing the original text through.

### msg_part: one row per message part and its treatment at each level

Parts are identified **only through existing message structure**: the `thought` column, `body.text`, `body.calls[]`,
`kind`, and `role`. A tool result is classified through the tool's own `tool.gives` value (`look` /
`event` / `receipt` / `recall`, defaulting to `event`). **This table contains no tool names.**

| Column | Type | Description |
| --- | --- | --- |
| `name` | text not null | Message part |
| `note` | text | |
| `l1` / `l2` / `l3` | text not null | → `press_how.name` |
| `l4` | text | → `press_how.name`. **The only nullable level column** |

Primary key: `name`

The three configured columns hold **defaults, not enforced policies**. On conflict, only `note` is updated, so startup does not overwrite customized strategies.

## How the tree grows

Parent pointers in `task_<mode>` already form a tree. Traversal—derivation, creating siblings after failure,
and backtracking—belongs to **one inference function**, `cycle.infer`, **not the kernel**. Replacing a search strategy
means replacing a handle.

### Two criteria serve different purposes

- **ĝ (self-evaluation / heuristic):** is this step complete? If not, derive another step. Greenness, scores,
  and confidence categories are model **estimates** of progress toward the objective.
- **G (objective):** returns only 0/1 and is **called when a node claims to have reached the goal**. A 1 means truly
  `reached`; a 0 rejects that claim and marks the node dead before trying a sibling.

Conflating them prevents the tree from reaching a second level: checking G at every intermediate step marks every step dead.
**Verifier-guided means that the agent cannot certify its own success, not that every step is verified.**

### After a node is marked dead

1. Count dead siblings under the same parent.
2. Below `max_dead_siblings`: create a sibling under **the same parent** and try a different direction.
3. At the limit: backtrack **one level higher** and create another child of the grandparent.
4. If no path remains after reaching the root, stop.

Concurrency is a separate limit: no new child is created when **unfinished** children under the same parent reach `max_branches`.
The number running concurrently and the number marked dead measure different things.

### A transition must remain within its declared candidates

The kernel only allows the inference function to choose from `cycle.next`; any other choice fails immediately. **To create a sibling
at this level, the cycle must list itself in `next`.** To backtrack, it must list the destination cycle.

This records permitted traversal in data. If the cycle table does not permit siblings, the tree must not create them;
the inference function cannot grant itself that permission.

### Two time limits

- **Unit level:** `now - at > expect_ms` means this step is stuck.
- **Task level:** `now - created_at > solve_seconds` means the whole task has timed out and must stop.
  Without it, a tree that continually creates siblings could grow forever.

## Running benchmarks

The old protocol had three steps: create a `G` for each sample, solve samples in training mode (**first result:
the number with `G=1`**), then rerun without G after degradation to obtain the second result.

Here, a benchmark run is **a batch of tasks, each with its own G**, grouped by `task.run`.

- `POST {prefix}/bench`: submit a batch. **Reject the entire batch if any task is invalid.** A partially submitted batch
  would give the wrong denominator without clearly identifying the omitted tasks.
- `GET {prefix}/bench/:run`: results. **Computed, not stored**; a stored copy could silently diverge from the records.
  Such drift would not necessarily raise an error.
- `GET {prefix}/bench`: list runs.

Resubmitting a run name is rejected: mixing two executions would invalidate their results.

**No separate bench table is needed.** Results are obtained by grouping on `run`; G already determines `state`,
so a second set of statistics is unnecessary.

### Publishing a task with G over HTTP alone

G node handles may be `http://…` addresses. Register an external handle by inserting a row in `handle`; the kernel
constructs its caller. Thus **external clients can create samples, run benchmarks, and retrieve results without changing code**:
execution units and every node of G can be externally hosted services.

## Objective G

**The criterion for whether a task is complete.** G is a directed acyclic graph: nodes compute Boolean values,
edges connect them, and the graph returns one value in `{0,1}`.

### The definition is not stored in the main database

The two boundaries are **no direct access to G's definition** and **no modification of it**. Queries are unrestricted in this design note:
callers may query as often as desired. Inferring the black box through queries is the intended test-time scaling mechanism, not itself a vulnerability.

Enforcement relies on **inaccessibility, not convention**. The main database exposes its full API, and `/query` can read any table.
**Putting G there would remove the boundary.** Definitions therefore live in a **separate database file**,
`db.sealed`, which H2H does not open. The main database stores only `objective` (presence) and `readable` (policy).

With `readable=true`, the acceptance criterion is part of the requirements and is **included directly in the task description**.
There is no separate read-G action. Benchmark samples are the cases requiring sealing.
There remains one storage boundary: every definition is sealed; `readable` only controls whether a copy enters the description.

### The value domains are closed

Only `bool` and `bool[n]` are allowed. Authors choose one rather than defining arbitrary domains, making **definition-time type checking
fully decidable**. Because `n` is fixed at definition time, edge-index bounds can be checked entirely statically.

### Every contract violation maps to 0; there is no third value

Out-of-domain returns, evaluation failures, crashes, and unregistered handles **all map to 0**. An unknown state
would force every upstream component to handle a third value, propagating it to the root. A failure includes its reason,
but that is **diagnostic information for us**; the verdict itself remains 0/1.

### Admission at publication

- **Tasks derived by agents inside the tree cannot attach G**: reject `source=agent` with G. Allowing this would let
  agents define their own success criterion, an **escalation of authority** that invalidates the criterion.
- **G requires an explicit `readable` value.** Tasks without G should not provide it.
- **Definition-time validation failure rejects the entire task**, before any database modification.

Validation covers duplicate node names, missing moments or script handles, references to nonexistent nodes, out-of-bounds edge indexes,
cycles, a unique sink, full consumption of every non-root output, a Boolean root domain,
and a root without incoming edges (a constant G is an invalid objective).

**One check is deliberately absent:** compatibility between moments and topological order. Lifecycle moments are not totally ordered,
since the same moment may recur within a task. “A is no later than B” has no precise meaning for repeated moments;
a check with unclear semantics could reject a valid G.

### Two calling interfaces

- **Kernel side:** when all execution units finish, the kernel invokes `onDone`; G runs and its verdict updates
  `state` / `result`. **The kernel does not know G**; it only reports completion of execution.
- **Agent side:** an ordinary tool returning **only the verdict**, with no G definition. Not yet connected in this note;
  it awaits the execution unit that runs model-requested tools.

The main table's `place` is the task's **usual** execution location. Each subtable row also has a `place`, normally matching it.
A different value is a per-unit exception, so both fields are necessary.

### Subtable `task_<mode>`: one row per execution unit of a task

One subtable per execution mode: `task_dfs`, `task_react`, `task_dfs_obj`, and so on.

| Column | Description |
| --- | --- |
| `task` | → `task.id` |
| `cycle` | This unit's cycle → column 2 of the task cycle table |
| `unit` | Execution-unit sequence number |
| `node` | Tree node containing this slot. **Only branching mechanisms use distinct nodes**: a node is a complete attempt. A single-chain mechanism uses 1 in every row |
| `from_cycle` | Predecessor row's cycle |
| `from_unit` | Predecessor row's execution unit |
| `agent` | Agent performing the work → `agent.name`; also determines the corresponding ctx table |
| `instance` | Agent instance performing the work |
| `place` | Execution location → `workplace.place` |
| `at` | Time this row was created / started |
| `status` | Terminal status: `reached` / `dead_failed` / `dead_below_bar`. **Immutable once written**; empty means still running |
| `press` | → `press.id`: this slot's **compressed representation**, with one version per configured level. Empty means uncompressed original messages |
| `done` | Whether the unit has finished |

Primary key: `(task, cycle, unit)`

**Compression is recorded per slot, not per node.** Context grows along a **chain**: each slot's messages appear in every later slot's context.
One measured chain contained 4136k bytes, with replayed reasoning accounting for 65–86%.

**Store references, not text**, so several slots can share one compressed passage (see `press`).

**Persist compression results instead of recomputing them when sending.** Otherwise the same slot could compress differently
on every request, producing context that changes under the model and cannot be reproduced during debugging.

**`unit` increases monotonically within a task; it does not restart per cycle.** The agent ctx table's key is
`(instance, unit)`, without cycle. Restarting the counter would make `think#1` and `act#1` collide.
`max_units` limits the number of rows belonging to a cycle, independently of their sequence numbers.

**`at` and `expect_ms` together identify timed-out units.** `done=0` includes not started, running, and stuck units;
that column alone cannot distinguish them. Combine `at` with the handle's registered `expect_ms`:
`now - at > expect_ms` means dead. Without this distinction, restart cannot determine whether to resend a request:
resending risks duplicate charges and side effects; not resending risks waiting forever.

**Every new row records its predecessor** through `from_cycle` / `from_unit`. The predecessor belongs to the same
`task`, so its task ID need not be repeated. Both fields are empty for the first row, which attaches to the main table's root.
A parent may have multiple children, while a child has one parent; parent pointers are scalar columns, not lists.
These pointers derive execution order, branching, and backtracking directly from the table without separate records.

This is the shared subtable structure. **Each mode may append its own columns** because different modes need
different execution-unit records, which is why they have separate tables.

### Subtables are generated

**Installation creates one `task_<mode>` subtable for each mode in the cycle table.**
Add rows for a mode and reinstall; its subtable is generated without handwritten DDL.
The main table does not store the subtable name, which could drift. Derive it from `mode` and the naming convention.

### Checks

1. `task.mode` must exist in the task cycle table.
2. A subtable's `cycle` must exist under its mode.
3. The number of units must not exceed `(mode, cycle).max_units`; this is where column 3 is enforced.
4. `from_cycle` / `from_unit` must identify an existing row in the same task, unless both are empty.
5. **Cross-check both sides:** look up a task row's `(agent, instance, unit)` in `agent_<agent>_ctx`
   using `(instance, unit)`. The resulting row must have the same `task`, `place`, and `done`
   values.
   The agent records its current task, and the task records its executing agent.
   **Without cross-validation, the duplicate records provide no assurance.**

---

## Agent tables (a table family)

Three layers: the agent, its context table, and the messages underlying each context row.

### `agent`: one row per agent (an expanded agent card)

| Column | Description |
| --- | --- |
| `name` | Primary key |
| `config` | Configuration file location |
| `apis` | Main model APIs: a list of references to `(key_env, model)` in the `api` table |
| `unit` | Execution-unit handle → `handle.name`, using the same execution-unit definition as above |
| `state` | Availability state |

### `agent_<name>_ctx`: one table per agent, one row per execution unit

Records which task an agent instance is executing. Each instance has its own context.

| Column | Description |
| --- | --- |
| `instance` | Instance identifier |
| `task` | Task being executed → `task.id` |
| `unit` | Execution unit |
| `place` | Execution location → `workplace.place` |
| `done` | Whether execution has finished |

Primary key: `(instance, unit)`

**An execution unit's `place` is fixed.** Once selected it does not change, so it belongs on this row,
without a separate change history.

### `agent_<name>_msg`: messages expanded from context rows, one row per message

| Column | Description |
| --- | --- |
| `instance` | ┐ Reference back to the context row |
| `unit` | ┘ |
| `seq` | Insertion order within the execution unit |
| `role` | **For the model:** `user` / `assistant` / `system`; only these roles |
| `kind` | **For us:** the message's actual origin or function → `msg_kind` |
| `body` | Content |
| `at` | Time the row was persisted |

Primary key: `(instance, unit, seq)`

**The order is fixed: persist first, then send.** The kernel obtains a transaction and assembles an execution unit,
including the context the agent will forward. **Write it to this table before sending**, then persist the response as another row.

Sending first could leave a request that was sent but never recorded if the process crashes between the two operations.
That state is unrecoverable. Persisting in order, together with `at`, makes **requests that never return detectable**:
the outgoing row exists, the response row does not, and the elapsed time exceeds the limit.

**This table holds the instance's complete context**, not only messages queued for insertion. Model responses
and tool requests are also rows, with `role` identifying the speaker. Without model-output records,
the next round would have no history to include.

`role` and `kind` must be separate columns. System-injected messages are also sent to the model as `user` messages.
**The transmitted list alone cannot distinguish them from real user input.** Models support only those roles, with no extra origin field,
so the database must retain the distinction; otherwise it is permanently lost.

### `msg_kind`: message-kind registry

| name | note |
| --- | --- |
| `user` | **Written** by a human |
| `voice` | **Spoken** by a human; transcribed by the real-time lane |
| `prompt` | Prompt |
| `inject` | System-injected; sent as `role=user`, distinguishable only through `kind` |
| `skill` | Temporary prompt supplied by a skill |
| `tool` | Tool result |
| `intervene` | Marker for a user intervention while observing execution |

**Adding a kind adds a row here without changing other tables.** More kinds may be added.

### `kind` is **derived**, not supplied

This is the central rule for this part of the design. The old implementation stated:

> A marker must be **based on facts the system already knows, not on user discipline**. Depending on a person
> to remember a prefix fails silently when they omit it, without leaving a detectable error.

Message delivery therefore specifies **who inserted it**, and derives `kind` and `role`:

| Inserted by | `kind` | `role` | Meaning |
| --- | --- | --- | --- |
| `user` | `user` | `user` | Human-written, with **intent and responsibility**; protocol prefix `[human] ` |
| `voice` | `voice` | `user` | Human speech transcribed by the real-time lane; the same intent, responsibility, and prefix `[human] ` |
| `world` | `inject` | `user` | Deterministic mechanical output, such as rule-injected knowledge; no intent or responsibility |
| `skill` | `skill` | `user` | Temporary prompt supplied by a skill |
| `tool` | `tool` | `tool` | Tool result |
| `agent` | `prompt` | `assistant` | The agent's own trace; **does not use this delivery pipeline** |
| `kernel` | `inject` | `system` | Kernel bookkeeping, not sent to the model as content |

**Human-written and system-injected content both become `user` messages after assembly**; only their database markers distinguish them.
The marker, `HUMAN_MARK`, is defined once and read by downstream components instead of duplicating its literal value.
The prefix rule is also centralized: a set identifies human-origin sources rather than checking only `by === "user"`.
That single-value check would **silently omit the marker for `voice`**, after which transmitted messages could not be distinguished.

`voice` and `user` are **recorded separately** despite both being human and receiving the prefix: speech transcripts
are not typed messages. Conflating them would resend live speech as if it had been typed when replaying context.

### One delivery implementation

The old implementation duplicated delivery code on the agent and kernel sides, even documenting the duplication.
**Two copies duplicate each bug, while a fix often reaches only one.** The kernel, publication route,
rules, and skills therefore all use the same `deliver` function.

The sole exception is **the model's own output**: that is its trace, and the adapter must specify its `kind`
(`prompt` or `call`), which cannot be inferred by the common delivery path.

## Hooks

**A hook is a rule plus a trigger condition with `dim=moment`.** No extra table is needed.

The kernel announces these moments: `unit_start` / `pre_send` / `post_send` / `task_done`.
It does not know specific rule names; it reports the current moment, and `trigger` determines which rules apply.
The old implementation used one directory per moment (`hooks/<event_type>/*.py`); here,
a moment is simply a data value.

**A failing rule fails only itself.** Hooks are on the main execution path; allowing one bad rule to abort
the entire step could stop every task.

### Subtables are generated

As with cycles, installation creates one pair of subtables for each agent in `agent`, named
`agent_<name>_ctx` and `agent_<name>_msg`, without handwritten DDL.

---

## workplace registry

**One table, not a table family**, registering execution locations.

| # | Column | Description |
| --- | --- | --- |
| 1 | `place` | Location: local / WSL / a Docker container in WSL / remote host / a container on a remote host / … |
| — | `identity` | **Handle that forwards tool calls to this location** → `handle.name`; required for forwarding |
| — | `runtime` | **Runtime sent when establishing the connection**, as a local file path; empty for `local` |
| 2 | `forward` | Whether tools are forwarded to this location |
| 3 | `tools` | Allowlist specifying tools that **always** forward, tools whose forwarding is **agent-controlled**, and other policies |
| 4 | `usable` | Registered availability |

Primary key: `place`

Column 1 is a **hierarchical address string**. Locations may be nested, such as a container inside WSL
or on a remote host, so each hop is represented explicitly:

```
local
wsl
wsl/docker:build-01
ssh://box-7
ssh://box-7/docker:build-01
```

Column 3 stores **one list per cell**, like columns 4 and 5 of the cycle table. It is not a binary membership list:
each entry has its own policy, and more policies can be added.

```json
[{"tool":"bash","policy":"always"},
 {"tool":"read","policy":"agent"}]
```

### Reaching a location is handled by a registered handle

**Locations used to be the only component outside the handle registry.** Tools used `fn:tool.bash`,
G nodes used `http://` endpoints, and inference used `fn:infer.dfs`, while location handling
was compiled into `place/index.ts`. `hops` recognized only a closed set
(`wsl` / `ssh` / `docker`), with hard-coded command construction and runtime destination paths.

This left **nowhere to express machine-specific properties**. Three observed failures occurred on one machine:

| Failure | Property of |
| --- | --- |
| `wsl.exe -- docker` could not find Docker because its snap installation was only on the login shell's PATH | That machine |
| Nested-location transfer stopped at the outermost hop, placing the runtime in WSL's `/tmp` rather than the container | That implementation |
| Snap-packaged Docker could not access `/tmp`, only `$HOME` and `/media` | That machine |

None is an inherent property of an execution location, but the only available fix was to change three kernel functions.

Rows with `forward = 1` therefore **must supply an `identity` handle** that **parses the address and forwards calls**.
Its contract is one function with JSON input and output:

```
fn:place.*  ({ place, op, tool, args })  →  tool result
```

`op: "call"` forwards one tool call; `op: "ping"` checks reachability. Both use the same handle.
Splitting them would require custom forwarders to implement two contracts for the same underlying connection:
**a reachable location is a prerequisite for forwarding to it**.

The built-in handle, `fn:place.hops`, retains the existing command-prefix behavior.
**Only this handle receives hop-syntax and runtime-transfer validation.** A different handle uses its own address syntax
(for example, `modal:sandbox-7`) and decides for itself whether anything must be transferred.

---

### How forwarding works

**Transfer and start the runtime when connecting; forward subsequent tool calls to it.**
Do not construct a fresh shell command for every call: that would recreate the environment each time and could change tool behavior.

The remote runtime contains the same tool implementations as the local process: **one implementation shared by both sides**.
`local` is the special case that needs no transfer and calls the implementation directly in-process.

**Connection liveness is not persisted.** `usable` is registration, not a probe. Check live conditions, such as a dropped connection
or a missing container, on demand; persisted liveness would be stale after a restart.

These are the minimum fields; more may be added.

---

## Rule table

**Unlike the earlier tables, rules may be registered externally**, so rows may be added at any time.

| Column | Description |
| --- | --- |
| `identity` | Identity → `handle.name`: **an internal handle or an external endpoint** |
| `does` | Purpose |
| `params` | Accepted parameters |
| `writes` | Declared database modifications |
| `access` | Database access details, allowing external rules to reach it |
| `scope` | Allowlist describing **which rows** the rule may operate on |

Primary key: `identity`

**Trigger timing is not stored here.** It lives in `trigger`, associated through
`(owner_kind='rule', owner=identity)`.

The protocol prefix in `identity` distinguishes internal and external handles in one column. **External registrations must supply it**:

```
fn:rule.route                          Internal: resolve the name through the function registry
http://127.0.0.1:9000/rules/route      External: registered by an external service
```

`params` stores one list per cell:

```json
[{"name":"task","type":"text","required":true},
 {"name":"limit","type":"integer","required":false}]
```

`writes` declares which tables may change and how. **It is not a comment**: declaring two tables and modifying a third
is an immediately detectable contract violation. External rules especially need declaration-time limits enforced during execution.

```json
[{"table":"task_dfs","op":"insert"},
 {"table":"task","op":"update"}]
```

`access` combines an address with the credential source. **Store environment-variable names, never secrets.**
In-process rules leave it empty because they already have database access:

```json
{"endpoint":"http://127.0.0.1:7801/api","token_env":"H2H_TOKEN"}
```

`scope` and `writes` are separate constraints: the latter specifies tables and operations, the former eligible rows.
Use **structured matching expressions, not SQL fragments**. The allowlist must be mechanically enforceable;
an arbitrary SQL fragment would reduce it to an unenforced annotation.

```json
[{"table":"task_dfs","match":{"mode":"dfs","done":0}}]
```

The field set is incomplete and will be extended.

---

## `trigger`: when a component applies

**Triggers are not limited to rules.** Skills and tools also use this table by adding an `owner_kind` value
without changing the schema.

One row is **one condition**. Lists are expanded into rows rather than embedded in cells.

| Column | Description |
| --- | --- |
| `owner_kind` | Condition owner type: `rule` / `skill` / `tool` / … |
| `owner` | Owner identity (`identity` for a rule) |
| `group` | Group number. **AND within a group; OR between groups** |
| `dim` | Dimension: `agent` / `task` / `cycle` / `chain` |
| `key` | Attribute in that dimension; empty for `chain` |
| `op` | Comparison: `eq` / `in` / `contains` / `prefix` / … |
| `value` | Comparison value |

Primary key: `(owner_kind, owner, group, dim, key, value)`

Example:

```
owner_kind  owner           group  dim    key    op        value
rule        fn:rule.retry   1      agent  role   eq        solver
rule        fn:rule.retry   1      task   kind   eq        swe
rule        fn:rule.retry   1      cycle  mode   eq        dfs
rule        fn:rule.retry   1      cycle  cycle  eq        act
rule        fn:rule.retry   1      chain         contains  compilation-failed
rule        fn:rule.retry   2      chain         contains  network-required
```

Group 1 requires all four conditions: solver, a swe task, the `dfs/act` cycle, and `compilation-failed` in the chain string.
Group 2 matches `network-required` in the chain. The groups are combined with OR.

**Multiple substrings need no separate all-versus-any policy**: put them in one group for AND,
or different groups for OR. The data determines the rule.

### Live database checks: `GET {prefix}/check`

One request checks condition validity (`trigger`) and data consistency (`data`). **The same check also runs at startup**;
problems generate warnings without blocking startup.

Data checks cover task modes, registered workplaces, tasks with **no execution units**
(often inserted directly instead of through publication), cycles outside their modes, missing parents,
**mismatched task and agent records**, inconsistent `done` values,
exceeded `max_units`, agent APIs referencing unregistered models, **two-layer handle validation**
(registered handles without an in-process implementation, and referenced handles absent from the database), and `result` on a nonterminal task.

This includes three silent **lane compatibility** errors:

| Configuration error | Consequence |
| --- | --- |
| A typo in `api.modes`, such as `duplx` | The lane is never selected |
| `api.modes` declares a shape its `handle` cannot support | **Selection succeeds but invokes the wrong adapter**, producing unintended behavior |
| `cycle.api_mode` requests an unsupported shape | No unit in that cycle can run |

The middle case is especially subtle: selection succeeds but routes to the wrong implementation. Validation uses
the supported shapes recorded at handle registration. The capabilities of externally registered `http://` handles
are unknown, so this particular compatibility check skips them.

These checks came from lessons recorded by the old degradation module, but **are not specific to degradation**:

> If `task_prefix` falls into `**kw`, the base class can swallow it; **no agent accepts the batch and no error is raised**.

No handler and no error describes this entire class of problems: tasks remain `open` in the database indefinitely
without an explanation. A dedicated check must ask whether any agent can actually accept a task.

> `result` belongs only on terminal nodes.

If a task records a result halfway through execution, later readers cannot determine which step produced it.

### Two tools against silent non-application

A malformed condition **need not raise an error**: its rule may simply never fire while the system runs normally.
The old implementation described this as a typical silent failure that an ordinary run does not reveal.
These tools are therefore prerequisites for using the table, not merely debugging conveniences.

**`GET {prefix}/trigger/check`** validates every condition without running the system: unknown dimensions or
operators, nonexistent attributes, a key on `chain`, a non-list value for `in`, whitespace in a value,
missing owners, and owners without any conditions. **It also runs at startup**, warning about problems without blocking
startup. A malformed condition should neither stop the entire application from starting nor fail silently.

**`POST {prefix}/trigger/explain`** explains each unmatched condition,
**including the actual observed value**:

```
fired = false
Group 1: not matched
  [y] agent.name eq a1                   actual: a1
  [n] chain.(whole string) contains compile-fail   actual: m/act#1
```

Reporting only “not matched” leaves users guessing whether the keyword is misspelled or absent from the text.

### No separate registry for `dim` / `op`

A separate registry was considered and rejected. **Supported values are those recognized by the implementation's `switch`.**
Another table could drift: it might still list `contains` after the code renames it, or the reverse,
with each side appearing correct. `check` validates directly against the implemented set.

### Keyword rules inherited from the earlier implementation

- **Values cannot contain spaces.** A space suggests multiple terms; the system does not guess adjacency or ordering.
  Express them as two conditions in the same group.
- **Matching is case-sensitive.** The capitalization of `NotImplemented` carries information.
- **Do not embed OR in a condition.** Use separate groups. The old implementation treated `"A|B"` as a literal
  that never matched and rejected it during loading; here, groups already express OR.
- The requirement to include a field name is inherent: the `key` column supplies it without embedding it in `value`.

### Chain-string format (fixed protocol)

The `chain` dimension matches the string representing the full task-execution chain leading to the current unit.
One function in `app/src/engine/chain.ts` defines the format:

```
dfs/open#1 > dfs/scope#1 > dfs/act#2
```

Follow `from_cycle` / `from_unit` from the root to the current unit. Each segment is `mode/cycle#unit`,
joined by ` > ` in **root-to-current order**; reversing the order would make `prefix` meaningless.

**Changing the format changes the protocol.** Existing `dim=chain` conditions would silently stop matching,
so a format change requires migrating those conditions at the same time.

---

## `tool`: one row per tool

| Column | Description |
| --- | --- |
| `name` | **Model-visible name**, used by the model to invoke the tool |
| `identity` | Identity → `handle.name`: internal handle or external endpoint |
| `does` | **Model-visible description**, used to decide whether to call the tool |
| `params` | **Model-visible parameter schema** |
| `output` | **Model-visible result schema** |
| `prompt` | Optional usage convention appended to the system prompt |
| `concurrent` | Whether it may run alongside other tools |
| `system` | **System tool:** available to every agent initially, independently of `trigger` |
| `access` | Database access details if needed; otherwise empty |
| `usable` | Availability |

Primary key: `name`; `identity` is unique.

**`name` and `identity` must remain separate.** The former belongs to the model's namespace; the latter specifies
how the runtime calls it, like the role/kind distinction in `agent_<name>_msg`.
**The workplace `tools` allowlist uses this `name`**, so both must share the same namespace;
otherwise the allowlist silently fails to match.

**Forwarding policy belongs to workplace**, through `forward` and `tools`, not to the tool table. Two copies of the same
policy could drift without an authority to resolve them, unlike task/agent records with distinct, cross-checkable perspectives.

**Tool implementations use the execution-location interface instead of directly accessing the host.**
A `local` place executes locally; WSL, container, and remote places forward the call. Tools do not distinguish them.
Calling `node:fs` directly would permanently restrict a tool to the local machine,
making its workplace registration ineffective.

`prompt` specifies **usage conventions**, such as reading a file before editing it.
It differs from `does`: the description explains what the tool does; the prompt explains how to use it correctly.

---

## `skill`: one row per skill

| Column | Description |
| --- | --- |
| `identity` | Identity → `handle.name`: internal handle or external endpoint |
| `does` | Purpose |
| `params` | Accepted parameters |
| `body` | Temporary context prompt. **Leave empty for dynamic content generated by the `identity` handle** |
| `role` | Role assigned when inserting the content |
| `usable` | Availability |

Primary key: `identity`

A skill has no model-visible name and description for selection: **the runtime inserts it when conditions match; the model does not choose it**.
Its inserted message has `kind=skill` in `agent_<name>_msg`, while tool results have `kind=tool`.

### Read before editing: return an operation rather than a rejection

The read-before-editing rule **does not rely on interception**. When `edit` or `write` is called without a prior read,
return **an execution operation**, not just an error:

```json
{"unit": {"tool": "read", "args": {"file_path": "…"}},
 "why": "Read … before changing it, then call edit again."}
```

A rejection only says no; returning an operation explains what to do next, in a form the model can follow.
Execution units already exist, so no additional policy layer is needed.

The criterion is **the database**: does this execution unit contain a recorded read result for this path?
Do not ask the tool or consult memory. Tools may run elsewhere and memory is lost on crashes; the database is authoritative for both sides.

### When tools and skills apply

Use `trigger` with `owner_kind` set to `skill` or `tool` and `owner` set to the corresponding primary key.

**Tools with `tool.system = 1` bypass `trigger`.** The read/write group (read / write / edit /
glob / grep / bash) consists of system tools available to every agent initially. Without this distinction,
the rule that no conditions means never triggered would make them unavailable to everyone.

The tool set for a unit is **system tools ∪ matched trigger tools**. Forwarding remains a separate decision
owned by `workplace`.

```
owner_kind  owner             group  dim    key   op        value
tool        web.search        1      chain        contains  network-required
skill       fn:skill.swe-pre  1      task   kind  eq        swe
```

---

## Field coverage

**Most of these tables still need additional fields.** Do not speculate about them now. Add fields when the next
workflow establishes a concrete requirement.

### Two references not yet implemented in this design note

1. `trigger.dim` and `trigger.op` **have no registry tables**. A typo such as `contain` instead of `contains` raises no error
   but prevents the rule from ever firing.
2. The configuration referenced by `agent.config` does not yet have a defined table.
