import { createHash, timingSafeEqual } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { gzipSync } from "node:zlib";
import { graderFetch } from "../../app/src/engine/registry.ts";
import { SIX_TOOLS } from "./tb-nginx-contract.ts";

export type ToolReceipt = {
  index: number; place: string; tool: string; admittedAt: number; requestSha256: string;
  forwarded: boolean; finishedAt?: number; httpStatus?: number; responseSha256?: string;
  denial?: string; fault?: string;
};

/** An owned admission boundary; completion means the actual stand response was read. */
export function tbToolGateway(options: { stand: string; token: string; store: string; ledger: (receipts: ToolReceipt[]) => void }) {
  const receipts: ToolReceipt[] = [];
  const places = new Map<string, { eligible: () => string | undefined; sealed?: string; pending: Set<Promise<void>> }>();
  const equal = (value: string) => {
    const a = Buffer.from(value), b = Buffer.from(options.token);
    return a.length === b.length && timingSafeEqual(a, b);
  };
  const hash = (raw: string) => createHash("sha256").update(raw).digest("hex");
  let captureFault: string | undefined;
  function persist() { try { options.ledger(receipts); } catch { captureFault = "tool_ledger_capture_error"; } }
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, maxRequestBodySize: 4 * 1024 * 1024,
    async fetch(request) {
      if (!equal(request.headers.get("X-ObjRun-Grader-Token") ?? "")) return Response.json({ error: "Unauthorized tool gateway" }, { status: 401 });
      if (request.method !== "POST" || new URL(request.url).pathname !== "/place") return Response.json({ error: "Unknown tool route" }, { status: 404 });
      let raw: string, body: {place?:string;tool?:string;op?:string};
      try { raw = await request.text(); body = JSON.parse(raw); } catch { return Response.json({ error: "Malformed tool request" }, { status: 400 }); }
      const place = String(body.place ?? ""), owner = places.get(place);
      if (!owner) return Response.json({ error: "Unknown owned place" }, { status: 422 });
      let denial = owner.sealed ?? captureFault;
      if (!denial) { try { denial = owner.eligible(); } catch { denial = "tool_admission_evidence_error"; captureFault = denial; } }
      if (denial) owner.sealed ??= denial;
      if (body.op === "ping" && denial) return Response.json({ alive: false, closed: true });
      if (body.op !== "ping" && !SIX_TOOLS.includes(body.tool as never)) return Response.json({ error: "Unsupported tool" }, { status: 422 });
      const record: ToolReceipt = { index: receipts.length, place, tool: body.op === "ping" ? "ping" : String(body.tool), admittedAt: Date.now(), requestSha256: hash(raw), forwarded: false };
      receipts.push(record);
      if (denial) { record.denial = denial; record.finishedAt = Date.now(); persist(); return Response.json({ error: "Task tool admission closed", reason: denial }, { status: 409 }); }
      let complete!: () => void;
      const pending = new Promise<void>(resolve => { complete = resolve; });
      owner.pending.add(pending);
      try {
        const requestFile = join(options.store, "tool-" + record.index + "-request.json.gz");
        mkdirSync(dirname(requestFile), { recursive: true }); writeFileSync(requestFile, gzipSync(raw));
        persist(); if (captureFault) throw new Error(captureFault);
        record.forwarded = true;
        // Admission is synchronous from the final policy check to this fetch; sealing
        // prevents every later request without interrupting an already issued command.
        const response = await graderFetch(options.stand + "/place", { method: "POST", headers: { "content-type": "application/json" }, body: raw, signal: AbortSignal.timeout(930000) });
        const text = await response.text();
        record.httpStatus = response.status; record.responseSha256 = hash(text);
        writeFileSync(join(options.store, "tool-" + record.index + "-response.json.gz"), gzipSync(text));
        return new Response(text, { status: response.status, headers: { "content-type": "application/json" } });
      } catch {
        record.fault = "tool_completion_or_capture_error"; captureFault ??= record.fault;
        return Response.json({ error: "Tool completion could not be certified" }, { status: 503 });
      } finally { record.finishedAt = Date.now(); persist(); owner.pending.delete(pending); complete(); }
    },
  });
  return {
    origin: "http://127.0.0.1:" + server.port,
    receipts,
    register(place: string, eligible: () => string | undefined) { if (places.has(place)) throw new Error("Owned place already registered"); places.set(place, { eligible, pending: new Set() }); },
    seal(place: string, why = "task_delivered") { const owner = places.get(place); if (!owner) throw new Error("Unknown owned place"); owner.sealed ??= why; },
    async drain(place: string, timeoutMs = 940000) {
      const owner = places.get(place); if (!owner) throw new Error("Unknown owned place");
      this.seal(place);
      const until = Date.now() + timeoutMs;
      while (owner.pending.size && Date.now() < until) await Bun.sleep(10);
      if (owner.pending.size) throw new Error("Tool completion deadline exceeded");
      if (captureFault) throw new Error(captureFault);
      const result = receipts.filter(record => record.place === place);
      if (result.some(record => record.forwarded && (!record.finishedAt || record.fault))) throw new Error("Actual tool completion is incomplete");
      return { sealed: true, finishedAt: Date.now(), outstanding: 0, receipts: result };
    },
    async stop() { for (const owner of places.values()) owner.sealed ??= "gateway_stopped"; await server.stop(true); },
  };
}
