import { expect, test } from "bun:test";
import { machine } from "./_lib.ts";

test("consecutive test engines stop the exact Bun process recorded at startup", async () => {
  for (let i = 0; i < 3; i++) {
    const m = await machine();
    const pid = m.pid;
    try { expect(Number.isInteger(pid) && pid > 0).toBe(true); }
    finally { await m.stop(); }
    expect(() => process.kill(pid, 0)).toThrow();
  }
}, 15000);
