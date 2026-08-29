/**
 * 外置工具的实现：操作一台**已经登录好**的浏览器，进一个**已经预约好**的会。
 *
 * ```
 * bun examples/tool/meetkit.ts        # 听在 7899
 * ```
 *
 * 这个文件是例子里唯一需要脚本的部分 —— 因为工具的**实现**得真有个地方能被调到。
 * 库里存的只是名字，真函数得有人持有：进程内的 `fn:` 由代码注册，进程外的就是
 * 这么一个地址。
 *
 * 为了跑得起来，浏览器和会议是假的（真的那套是 puppeteer + Google Meet）。
 * 形状是真的：收一份 JSON，回一份 JSON。
 *
 * ## 要点：进会之后长出新句柄
 *
 * `meet_join` 干完之后会**回过头调引擎的 `/declare`**，把会里才有的那几样注册进去
 * （说话、共享、离会）。它走的是跟你一样的那个公开接口 —— 没有后门。
 *
 * 于是「有哪些工具」不是开机时定死的，是**跟着世界的状态长出来的**：没进会的时候
 * 根本没有 `meet_say` 这个东西，模型也就不可能去调它。
 */

const PORT = Number(process.env.PORT ?? 7899);
const BASE = process.env.BASE ?? "http://127.0.0.1:7801/api";
const ME = `http://127.0.0.1:${PORT}`;

/** 现在在哪个会里。**这是活状态，不进库** —— 库里存的是登记，不是探活的结果。 */
let inMeeting: string | null = null;

/** 往引擎里注册东西。跟你在终端里 curl 打的是同一个口。 */
async function declare(body: unknown): Promise<unknown> {
  const res = await fetch(`${BASE}/declare`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return await res.json();
}

/** 进会之后才有的那几样。 */
async function 会里的工具(meetId: string): Promise<string[]> {
  const r = (await declare({
    handles: [
      { name: `${ME}/meet_say`, expectMs: 30_000 },
      { name: `${ME}/meet_leave`, expectMs: 10_000 },
      { name: `${ME}/share_open`, expectMs: 20_000 },
    ],
    tools: [
      {
        name: "meet_say",
        identity: `${ME}/meet_say`,
        does: "在会上说一句话",
        params: { type: "object", properties: { text: { type: "string" } }, required: ["text"] },
        output: { type: "object", properties: { ok: { type: "boolean" } } },
        when: [[{ dim: "task", key: "description", op: "contains", value: "会议" }]],
      },
      {
        name: "share_open",
        identity: `${ME}/share_open`,
        does: "在会上共享一份材料，返回这份材料的操作契约",
        params: { type: "object", properties: { url: { type: "string" } }, required: ["url"] },
        output: { type: "object", properties: { contract: { type: "object" } } },
        when: [[{ dim: "task", key: "description", op: "contains", value: "会议" }]],
      },
      {
        name: "meet_leave",
        identity: `${ME}/meet_leave`,
        does: "离开会议",
        params: { type: "object", properties: {} },
        output: { type: "object", properties: { ok: { type: "boolean" } } },
        when: [[{ dim: "task", key: "description", op: "contains", value: "会议" }]],
      },
    ],
  })) as { tools?: string[]; problems?: string[] };
  if (r.problems) throw new Error(`注册会里的工具没成：${r.problems.join("；")}`);
  console.log(`   进了 ${meetId}，长出 ${r.tools?.join("、")}`);
  return r.tools ?? [];
}

Bun.serve({
  port: PORT,
  async fetch(req) {
    const path = new URL(req.url).pathname;
    const a = (await req.json().catch(() => ({}))) as Record<string, unknown>;

    // ── 工具的实现 ────────────────────────────────────────────────────────
    // 工具收到的是 `args`（模型给的那份），外面还包着 place / agent / instance / unit。

    if (path === "/browser_status") {
      console.log("← browser_status");
      // 真的那套会去问 puppeteer 连没连上、哪个 profile、登录没登录。
      return Response.json({ running: true, profile: "meetkit-chrome", loggedIn: true });
    }

    if (path === "/meet_join") {
      const url = String((a.args as Record<string, unknown>)?.meetUrl ?? "");
      console.log(`← meet_join ${url}`);
      if (!/^https:\/\/meet\.google\.com\//.test(url)) {
        return Response.json({ ok: false, why: "这不是一个 Meet 地址" });
      }
      inMeeting = url.split("/").pop() ?? "?";
      const grew = await 会里的工具(inMeeting);
      return Response.json({ ok: true, meetId: inMeeting, 长出来的工具: grew });
    }

    if (path === "/meet_say") {
      const text = String((a.args as Record<string, unknown>)?.text ?? "");
      console.log(`← meet_say「${text}」`);
      if (!inMeeting) return Response.json({ ok: false, why: "还没进会" });
      return Response.json({ ok: true });
    }

    if (path === "/share_open") {
      console.log("← share_open");
      if (!inMeeting) return Response.json({ ok: false, why: "还没进会" });
      // 每份材料自己声明一份操作契约：能做哪些操作、各自对应什么键鼠输入。
      // 操作工具包是格式无关的纯键鼠，认的就是这份契约。
      return Response.json({
        contract: {
          type: "deck",
          state: { page: 1, total: 12, heading: "开场" },
          operations: [
            { name: "next", input: "press('ArrowRight')" },
            { name: "prev", input: "press('ArrowLeft')" },
            { name: "goto", input: "type('12')" },
          ],
        },
      });
    }

    if (path === "/meet_leave") {
      console.log("← meet_leave");
      inMeeting = null;
      return Response.json({ ok: true });
    }

    // ── 跑起来要用的另外两条 ──────────────────────────────────────────────

    if (path === "/unit") {
      const tools = ((a.tools ?? []) as { name: string }[]).map((t) => t.name);
      console.log(`← unit｜这一轮挂上：${tools.join("、")}`);
      return Response.json({ role: "assistant", kind: "prompt", body: tools.join("、") });
    }
    if (path === "/infer") return Response.json(null);

    return new Response("没有这个路径", { status: 404 });
  },
});

console.log(`meetkit 听在 ${ME}`);
console.log(`  /browser_status  浏览器连上没有、登录没有`);
console.log(`  /meet_join       进一个已预约的会 → 会长出 meet_say / share_open / meet_leave`);
console.log(`  /unit  /infer    跑起来要用的`);
