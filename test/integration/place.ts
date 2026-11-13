/**
 * Example: **add a place to execute work**.
 *
 * ```
 * bun test/integration/place.ts
 * ```
 *
 * A workplace is a **hierarchical address**, with nested layers:
 *
 * ```
 *   local                        local machine, direct in-process calls
 *   wsl                          default distribution
 *   wsl:Ubuntu-24.04             specified distribution
 *   ssh://box-7
 *   wsl/docker:build-01          container inside WSL
 *   ssh://box-7/docker:build-01
 * ```
 *
 * Tool execution **forwards calls to the runtime at that location**. Connection
 * setup transfers and starts the runtime; each subsequent call sends one JSON
 * line and receives one JSON line.
 *
 * **How to reach the location is itself a handle** (`workplace.identity`), just
 * like tools, G nodes, and inference functions. The built-in `fn:place.hops`
 * constructs `wsl` / `ssh` / `docker` command prefixes. An `http://` handle instead
 * lets another process define access; the kernel need not understand containers.
 *
 * ## Two common pitfalls
 *
 * 1. **`usable` is registration state, not a health probe.** Remote connectivity
 *    is live state, checked afresh and never stored. Persisting it would leave
 *    stale claims in the database after a restart.
 * 2. **Forwarding enabled with an empty allowlist** is valid but forwards no tool.
 *    This is almost certainly unintended and is reported during declaration.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();
const out = await outside({
  "/unit": (u) => ({ role: "assistant", kind: "prompt", body: `I am working on ${u.place}` }),
  "/infer": () => null,
  // **A custom forwarder.** The kernel does not understand its address syntax; this process decides
  // how to construct commands and whether to transfer files. The kernel knows only a handle name.
  "/forwarder": (a) => (a.op === "ping" ? { alive: true } : { ran: a.tool, on: a.place }),
});

try {
  // =============== Part 1: registration ===============
  part("Part one: registration");

  step("1. forwarding is on, but the place string uses a form nothing recognises");
  const unknownForm = await m.bad("POST", "/declare", {
    places: [{ place: "podman:box", identity: "fn:place.hops", forward: true, runtime: "/tmp/runtime", tools: [{ tool: "bash", policy: "always" }] }],
  });
  show("it answered:", unknownForm.problems);
  ok(
    "an unrecognised form fails immediately - guessing would connect somewhere else entirely",
    JSON.stringify(unknownForm.problems).includes("unrecognised segment in the place string"),
    unknownForm.problems,
  );

  step("1b. a place that does not forward can be named freely");
  const freeName = await m.api<{ places: string[] }>("POST", "/declare", { places: [{ place: "tab:deck" }] });
  show("accepted:", freeName.places);
  ok(
    "a place string has to be a chain of hops only when it forwards; otherwise the name simply says where this station is",
    freeName.places.includes("tab:deck"),
    freeName.places,
  );

  step("2. it says it forwards, but never says who carries the calls there");
  const noHandle = await m.bad("POST", "/declare", {
    places: [{ place: "wsl", forward: true, runtime: "/tmp/runtime", tools: [{ tool: "bash", policy: "always" }] }],
  });
  show("it answered:", noHandle.problems);
  ok(
    "forwarding without a handle is refused - how to reach a place is a handle's job, and a task would otherwise " +
      "walk all the way to the first forwarded tool call before finding out",
    JSON.stringify(noHandle.problems).includes("no handle was given"),
    noHandle.problems,
  );

  step("2b. it names a handle that nobody can claim");
  const ghost = await m.bad("POST", "/declare", {
    places: [
      { place: "wsl", identity: "fn:place.nowhere", forward: true, runtime: "/tmp/runtime", tools: [{ tool: "bash", policy: "always" }] },
    ],
  });
  show("it answered:", ghost.problems);
  ok("the same check every other handle reference gets", JSON.stringify(ghost.problems).includes("there is no handle named"), ghost.problems);

  step("2c. the built-in forwarder ships a runtime over, and none was given");
  const noRuntime = await m.bad("POST", "/declare", {
    places: [{ place: "wsl", identity: "fn:place.hops", forward: true, tools: [{ tool: "bash", policy: "always" }] }],
  });
  show("it answered:", noRuntime.problems);
  ok(
    "this one is asked of fn:place.hops only - what to ship over, or whether to ship anything at all, is that handle's own business",
    JSON.stringify(noRuntime.problems).includes("nothing to ship"),
    noRuntime.problems,
  );

  step("3. forwarding is on, but the allow-list is empty");
  const emptyList = await m.bad("POST", "/declare", {
    places: [{ place: "wsl", identity: "fn:place.hops", forward: true, runtime: "/tmp/runtime", tools: [] }],
  });
  show("it answered:", emptyList.problems);
  ok(
    "legal but certainly not what was meant, so it is said out loud",
    JSON.stringify(emptyList.problems).includes("not a single tool would be forwarded"),
    emptyList.problems,
  );

  step("4. an unrecognised policy in the allow-list");
  const badPolicy = await m.bad("POST", "/declare", {
    places: [{ place: "local", identity: "fn:place.hops", forward: true, tools: [{ tool: "bash", policy: "sometimes" }] }],
  });
  show("it answered:", badPolicy.problems);
  ok("it must be always or agent", JSON.stringify(badPolicy.problems).includes("unrecognised policy"), badPolicy.problems);

  step("4b. the same unrecognised address, carried by a handle of one's own");
  const mine = await m.api<{ places: string[] }>("POST", "/declare", {
    handles: [{ name: out.url("/forwarder"), expectMs: 20_000 }],
    places: [
      {
        place: "podman:box",
        identity: out.url("/forwarder"),
        forward: true,
        tools: [{ tool: "bash", policy: "always" }],
      },
    ],
  });
  show("accepted:", mine.places);
  ok(
    "step 1 refused this very string - not because the string is wrong, but because fn:place.hops cannot read it. " +
      "Reading the address is the handle's job, so a handle that can read it takes the same string",
    mine.places.includes("podman:box"),
    mine.places,
  );

  step("4c. probe it - the kernel asks that handle, and knows nothing about podman");
  const mineAlive = await m.api<Record<string, unknown>>("POST", `/places/${encodeURIComponent("podman:box")}/ping`);
  show("ping podman:box:", mineAlive);
  ok(
    "reachable, and the answer came from that process: it was asked op=ping, the two verbs of one handle",
    mineAlive.alive === true && out.calls["/forwarder"].some((c) => c.op === "ping" && c.place === "podman:box"),
    { mineAlive, asked: out.calls["/forwarder"] },
  );

  step("5. load two: this machine, and a registered but disabled remote");
  const loaded = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
    ],
    places: [
      { place: "local" },
      {
        place: "ssh://box-does-not-exist",
        identity: "fn:place.hops",
        runtime: "/tmp/tgengin-runtime",
        forward: true,
        tools: [{ tool: "bash", policy: "always" }, { tool: "read", policy: "agent" }],
        // Registered but marked unusable: this is **registration state**, not a health-check result.
        usable: false,
      },
    ],
    modes: [{ mode: "demo", cycles: [{ cycle: "go", from: [], next: [], infer: out.url("/infer") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  ok("both went in", (loaded.places as string[]).length === 2, loaded.places);

  step("6. read back how they were registered");
  const { places } = await m.api<{ places: Record<string, unknown>[] }>("GET", "/places");
  show("the list:", places);
  const ssh = places.find((p) => String(p.place).startsWith("ssh://")) as { tools: unknown[]; identity: string };
  ok("the allow-list was kept, and so was the name of who carries the calls there", ssh.tools.length === 2 && ssh.identity === "fn:place.hops", places);

  // =============== Part 2: actual-use validation ===============
  part("Part two: checks at the level of use");
  console.log("  Registered is not the same as reachable. usable is a registration; reachability has to be probed on the spot.");

  step("7. probe this machine");
  const here = await m.api<Record<string, unknown>>("POST", "/places/local/ping");
  show("ping local:", here);
  ok("this machine is reachable", here.alive === true, here);

  step("8. probe the remote that does not exist");
  const remote = await m.api<Record<string, unknown>>("POST", `/places/${encodeURIComponent("ssh://box-does-not-exist")}/ping`);
  show("ping it:", remote);
  ok("unreachable is reported as unreachable, and it can say why", remote.alive === false, remote);

  step("9. after probing, that column in the database was NOT rewritten");
  const unchanged = (await m.api<{ places: Record<string, unknown>[] }>("GET", "/places")).places;
  show("usable in the list, read again:", unchanged.map((p) => ({ place: p.place, usable: p.usable })));
  ok(
    "a probe result is never written back - written back, it becomes a stale lie after any crash and restart",
    unchanged.find((p) => String(p.place).startsWith("ssh://"))?.usable === false &&
      unchanged.find((p) => p.place === "local")?.usable === true,
    unchanged,
  );

  step("10. really run a task on this machine");
  await m.api("POST", "/tasks", {
    id: "t-local", mode: "demo", agent: "bot", place: "local", source: "user", description: "do it right here",
  });
  await until("t-local to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-local");
    return d.state === "done" ? d : null;
  });
  const echoed = (await m.api<{ rows: Record<string, unknown>[] }>("GET", "/tasks/t-local/messages")).rows
    .filter((r) => r.kind === "prompt")
    .at(-1);
  show("it said:", echoed?.body);
  ok("where to work really reached the execution unit", String(echoed?.body).includes("local"), echoed?.body);

  step("11. publish a task to an unregistered place");
  const unregistered = await m.bad("POST", "/tasks", {
    id: "t-nowhere", mode: "demo", agent: "bot", place: "mars", source: "user", description: "do it on mars",
  });
  show("it answered:", unregistered.error);
  ok("rejected at publish time - it never sits in the database waiting to be noticed", String(unregistered.error).length > 0, unregistered);
} finally {
  out.stop();
  m.stop();
}

done();
