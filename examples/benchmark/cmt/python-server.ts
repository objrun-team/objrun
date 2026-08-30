/**
 * `python_exec` —— 一台例子侧的小服务器，把一段 Python 丢进一次性沙箱里跑。
 *
 * ```
 * bun examples/benchmark/cmt/python-server.ts [port]
 * ```
 *
 * 引擎那边它就是一条 `http://` 句柄，跟判卷台那两条一样：内核 POST 一份 JSON
 * 过来，这儿回一份 JSON。**一行内核代码没改。**
 *
 * ## 为什么要这个
 *
 * 老仓库跑这套 bench 时，智能体手上只有两个工具：交卷，和 `python_exec`。
 * 我们这边给的是 `bash` —— 而这台 Windows 上根本没有可用的 python。实测的后果：
 * 一道题拿 12 个执行单元去查 `python --version`，一个字答案都没写。
 * 伸手要算力却摸到空气，额度就这么没的。
 *
 * ## 沙箱是一次性的，而且跟答案不在一起
 *
 * 每次调用起一个新容器，跑完就没：
 *
 * - `--network none` —— 没有网卡。判卷台那个口它打不到，外面也打不到
 * - `--rm` —— 不留状态。上一道题写的东西不会漏给下一道
 * - **不是判卷台那个镜像** —— 那个里面装着 `cmt_data.jsonl`。这个镜像只有
 *   sympy / numpy / scipy，一道题都没有
 *
 * 起容器每次大约一秒。这道题是推导题，不是要跑一整套流水线，这个代价换来
 * 「算一下再答」是划算的。
 */

const PORT = Number(process.argv[2] ?? 7902);
const IMAGE = process.env.TGENGIN_SANDBOX_IMAGE ?? "tgengin-sandbox";
/** 怎么进到 docker。这台机器上 docker 装在 WSL 里。 */
const DOCKER = (process.env.TGENGIN_DOCKER ?? "wsl.exe -d Ubuntu-24.04 -- /snap/bin/docker").split(" ");
/** 一段代码最多跑多久。到点连容器一起杀掉。 */
const WALL_MS = Number(process.env.TGENGIN_SANDBOX_MS ?? 20_000);
/** 回给模型的输出上限。再多也没用，只会把上下文撑掉。 */
const CAP = 4000;

interface Ask {
  args?: { code?: unknown };
}

async function run(code: string): Promise<Record<string, unknown>> {
  const proc = Bun.spawn(
    [
      ...DOCKER,
      "run",
      "--rm",
      "-i",
      "--network",
      "none",
      // 一段算错的代码不该把这台机器拖垮。
      "--memory",
      "512m",
      "--cpus",
      "1",
      IMAGE,
      "python",
      "-",
    ],
    { stdin: new TextEncoder().encode(code), stdout: "pipe", stderr: "pipe" },
  );

  const killer = setTimeout(() => proc.kill(), WALL_MS);
  const [out, err, code_] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  clearTimeout(killer);

  // 进到 docker 那条命令自己会往 stderr 上写东西（这台机器上 `wsl.exe` 每次都印
  // 一条 UTF-16 的警告横幅）。不滤掉的话它原样进模型上下文 —— 模型会当成
  // 自己那段代码报的错去改代码，而那跟它一点关系都没有。
  const NUL = String.fromCharCode(0);
  const clean = (t: string) =>
    t
      .split(NUL)
      .join("")
      .split(/\r?\n/)
      .filter((l) => !/^wsl:/i.test(l.trim()))
      .join("\n")
      .trim();
  const cut = (t0: string) => {
    const t = clean(t0);
    return t.length > CAP ? `${t.slice(0, CAP)}\n... (${t.length - CAP} more characters)` : t;
  };
  return {
    exitCode: code_,
    stdout: cut(out),
    stderr: cut(err),
    ...(code_ === 143 || code_ === 137 ? { timedOut: true } : {}),
  };
}

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, image: IMAGE });
    }
    if (url.pathname !== "/python_exec") {
      return Response.json({ error: "404" }, { status: 404 });
    }
    let body: Ask = {};
    try {
      body = (await req.json()) as Ask;
    } catch {
      /* 读不出来就当没给参数 */
    }
    const code = typeof body.args?.code === "string" ? body.args.code : "";
    if (!code.trim()) return Response.json({ error: "code is required - an empty program computes nothing" });
    try {
      return Response.json(await run(code));
    } catch (e) {
      return Response.json({ error: e instanceof Error ? e.message : String(e) });
    }
  },
});

process.stderr.write(`[python] up on http://127.0.0.1:${PORT}/python_exec, sandbox image ${IMAGE}\n`);
