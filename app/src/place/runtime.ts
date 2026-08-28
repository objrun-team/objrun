/**
 * 运行时 —— **被送到那个位置上去跑的那个东西**。
 *
 * 建立连接的时候把这个二进制送过去、起起来；之后每一次工具调用都是转发给它。
 * 它装的就是 `../tools/` 那一批，跟本机同一份实现 —— 所以 `local` 和转发出去的
 * 结果是一样的，不会出现「本机能跑、转过去行为不一样」那种事。
 *
 * ## 协议：stdin / stdout 上的 JSON 行
 *
 * ```
 * → {"id":1,"tool":"read","args":{"file_path":"/etc/hostname"}}
 * ← {"id":1,"ok":true,"value":{...}}
 * ← {"id":1,"ok":false,"error":"..."}
 * ```
 *
 * **stdout 上只许有协议行。** 工具自己的输出是被捕获的（子进程的 stdout 不继承），
 * 混进来一行的话对面解析就错位，而那不报错，只是从某一刻起答非所问。
 */

import { TOOLS } from "../tools/index.ts";

const by = new Map(TOOLS.map((t) => [t.name, t]));

async function handle(line: string): Promise<string | null> {
  if (line.trim() === "") return null;
  let id: unknown = null;
  try {
    const req = JSON.parse(line) as { id?: unknown; tool?: unknown; args?: unknown };
    id = req.id ?? null;
    if (req.tool === "ping") return JSON.stringify({ id, ok: true, value: { tools: [...by.keys()] } });
    const t = by.get(String(req.tool));
    if (!t) throw new Error(`这个运行时里没有 ${String(req.tool)} 这个工具`);
    const value = await t.run((req.args ?? {}) as Record<string, unknown>);
    return JSON.stringify({ id, ok: true, value });
  } catch (e) {
    return JSON.stringify({ id, ok: false, error: e instanceof Error ? e.message : String(e) });
  }
}

let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk: string) => {
  buf += chunk;
  let nl = buf.indexOf("\n");
  while (nl !== -1) {
    const line = buf.slice(0, nl);
    buf = buf.slice(nl + 1);
    void handle(line).then((out) => {
      if (out !== null) process.stdout.write(out + "\n");
    });
    nl = buf.indexOf("\n");
  }
});
process.stdin.on("end", () => process.exit(0));
