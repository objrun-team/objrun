import { expect, test } from "bun:test";
import { machine, outside, until } from "./_lib.ts";

async function declare(m: Awaited<ReturnType<typeof machine>>, out: Awaited<ReturnType<typeof outside>>) {
  await m.api("POST", "/declare", {
    handles: [{ name: out.url("/unit"), expectMs: 5000 }, { name: out.url("/infer"), expectMs: 1000 }, { name: out.url("/grade"), expectMs: 5000 }, { name: out.url("/root"), expectMs: 1000 }],
    places: [{ place: "local" }],
    modes: [{ mode: "lifecycle", cycles: [{ cycle: "answer", maxUnits: 1, from: [], next: [], infer: out.url("/infer") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
}

async function publish(m: Awaited<ReturnType<typeof machine>>, out: Awaited<ReturnType<typeof outside>>, seconds: number) {
  await m.api("POST", "/tasks", {
    id: "lifecycle", mode: "lifecycle", agent: "bot", place: "local", source: "user", description: "return one answer", solveSeconds: seconds,
    readable: false, objective: { nodes: [{ name: "grade", moment: "done", domain: "bool", handle: out.url("/grade") }, { name: "root", moment: "done", domain: "bool", handle: out.url("/root") }], edges: [{ src: "grade", out: 0, dst: "root" }], sink: "root", checks: 1 },
  });
}

async function outcome(m: Awaited<ReturnType<typeof machine>>, wanted: string) {
  return until(`the actual engine reports ${wanted}`, async () => {
    const task = await m.api<{ state: string; result: string | null }>("GET", "/tasks/lifecycle");
    const verdict = JSON.parse(task.result ?? "{}");
    return verdict.outcome === wanted ? { ...task, verdict } : null;
  }, 5000);
}

test("terminal task state remains finalization_pending while the actual wrap-up grader is running", async () => {
  let release!: () => void;
  const grading = new Promise<void>(resolve => { release = resolve; });
  const out = await outside({ "/unit": () => ({ role: "assistant", kind: "prompt", body: "answer" }), "/infer": () => null, "/grade": async () => { await grading; return true; }, "/root": arg => (arg.feed as { value: unknown }[])[0]?.value === true });
  const m = await machine();
  try {
    await declare(m, out);
    await publish(m, out, 10);
    const pending = await outcome(m, "finalization_pending");
    expect(pending.state).toBe("done");
    expect(pending.verdict.valid).toBe(false);
    release();
    const final = await outcome(m, "passed");
    expect(final.verdict).toMatchObject({ pass: 1, valid: true });
    expect(out.calls["/grade"]?.length).toBe(1);
  } finally { release(); m.stop(); out.stop(); }
}, 10000);

test("a response received after the task timeout is recorded but never inferred or graded", async () => {
  const out = await outside({ "/unit": async () => { await Bun.sleep(1300); return { role: "assistant", kind: "prompt", body: "late correct answer" }; }, "/infer": () => null, "/grade": () => true, "/root": arg => (arg.feed as { value: unknown }[])[0]?.value === true });
  const m = await machine();
  try {
    await declare(m, out);
    await publish(m, out, 1);
    expect((await outcome(m, "finalization_pending")).state).toBe("failed");
    const final = await outcome(m, "no_candidate");
    expect(final.state).toBe("failed");
    expect(final.verdict).toMatchObject({ pass: 0, valid: false });
    expect(out.calls["/infer"]?.length).toBe(0);
    expect(out.calls["/grade"]?.length).toBe(0);
  } finally { m.stop(); out.stop(); }
}, 10000);
