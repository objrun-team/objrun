/**
 * What this machine recognizes.
 *
 * ## Why this endpoint exists
 *
 * **Clients must not hard-code these definitions.** The failure is concrete: adding `voice`
 * to message types without updating a client's switch makes live speech appear **blank** in
 * the UI, without an error. New states or invocation shapes have the same failure mode.
 *
 * Clients should fetch this endpoint at startup and treat its definitions **as data**.
 * A new server-side entry then becomes available automatically.
 *
 * The human-authored marker especially matters: human messages carry it, and clients must
 * either remove it for display or style the message accordingly. Hard-coding `"[human]"` breaks
 * clients as soon as the server changes that marker.
 */

import { all, type Store } from "../H2H/db.ts";
import { HUMAN_KINDS, HUMAN_MARK, KINDS } from "../msg/deliver.ts";
import { MODES } from "../llm/index.ts";
import { SOURCES, STATES } from "../tasks/publish.ts";
import type { Route } from "./spec.ts";

/** The four task states. **Derived alongside `STATES`**: those are allowed values; these are human-readable explanations. */
const STATE_NOTE: Record<string, string> = {
  open: "Waiting to be picked up: not a single execution unit has been opened",
  claimed: "Someone is working on it: there are unfinished execution units",
  done: "Everything finished. If it has a grading function, that function has the last word",
  failed: "Judged a failure - result says why",
};

const SOURCE_NOTE: Record<string, string> = {
  user: "Published by a person. Only this source may carry a grading function",
  agent: "Derived by the agent inside the tree. May not carry a grading function - that would be self-granted authority",
  world: "Triggered by the environment",
  eacn: "Published by the system above",
};

/** Execution-unit terminal states. **Fixed when the row is created; never changed afterward.** */
const UNIT_STATUS: [string, string][] = [
  ["reached", "Claims to have arrived"],
  ["dead_failed", "Ruled out: this step did not work"],
  ["dead_below_bar", "Ruled out: below the bar"],
];

export function aboutRoutes(prefix: string, store: Store, version: string, duplex: string[]): Route[] {
  return [
    {
      method: "GET",
      path: "/about",
      group: "This machine",
      does: "Which values this machine knows: states, sources, message kinds, api modes",
      why: "Do not hard-code these in a client. Add a message kind here, and a client switch without that branch renders the message as blank - no error, it is simply gone. Read this route as data, and a kind added here shows up there on its own.",
      returns: {
        version: "1.0.0",
        prefix: "/api",
        taskStates: [{ name: "open", note: "Waiting to be picked up: not a single execution unit has been opened" }],
        taskSources: [{ name: "user", note: "Published by a person. Only this source may carry a grading function" }],
        msgKinds: [{ name: "voice", note: "Spoken by a person (transcribed)", human: true }],
        apiModes: [{ name: "duplex", note: "Realtime, both directions. One execution unit = one turn in the session" }],
        unitStatuses: [{ name: "reached", note: "Claims to have arrived" }],
        humanMark: "[human] ",
        declared: { modes: ["dfs"], agents: ["solver"], places: ["local"], duplexHandles: [] },
      },
      handler: async () => {
        // Derive `human` from the delivery inference table. **Do not keep a second list here**:
        // otherwise adding a human source would eventually leave one list outdated.
        return {
          version,
          prefix,
          taskStates: STATES.map((s) => ({ name: s, note: STATE_NOTE[s] ?? "" })),
          taskSources: SOURCES.map((s) => ({ name: s, note: SOURCE_NOTE[s] ?? "" })),
          msgKinds: KINDS.map(([name, note]) => ({ name, note, human: HUMAN_KINDS.has(name) })),
          apiModes: MODES.map(([name, note]) => ({ name, note })),
          unitStatuses: UNIT_STATUS.map(([name, note]) => ({ name, note })),
          humanMark: HUMAN_MARK,
          declared: {
            duplexHandles: duplex,
            modes: (all(store.ro, `select distinct mode from cycle order by mode`) as { mode: string }[]).map(
              (r) => r.mode,
            ),
            agents: (all(store.ro, `select name from agent order by name`) as { name: string }[]).map((r) => r.name),
            places: (all(store.ro, `select place from workplace order by place`) as { place: string }[]).map(
              (r) => r.place,
            ),
          },
        };
      },
    },
  ];
}
