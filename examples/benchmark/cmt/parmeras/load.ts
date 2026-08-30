/**
 * 把这个目录底下的 skill 注册进引擎。
 *
 * ```
 * bun examples/benchmark/cmt/parmeras/load.ts [--dry]
 * ```
 *
 * 一个 `.md` = frontmatter（`name` / `description`）+ 正文。这边一行 `skills[]`
 * 要的正好是这三样：
 *
 * | `.md` | → | `skills[]` |
 * | --- | --- | --- |
 * | `name` | | `identity` |
 * | `description` | | `does` |
 * | frontmatter 之后那一整段 | | `body` |
 *
 * ## `when` 是这儿定的，不是搬来的
 *
 * 老系统的触发维度叫 `constants`，这边是 `agent/task/cycle/chain/moment/place`，
 * **没有 constants 这一维**。所以门得重新写，而且写死在 `GATE` 里 ——
 * 挑出来的东西就把门也说清楚，不靠名字前缀去猜。
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const DRY = process.argv.includes("--dry");
const HERE = new URL(".", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

type Term = { dim: string; key: string; op: string; value: string };

/** 每个搬过来的 skill 什么时候塞。**没写在这儿的不注册。** */
const GATE: Record<string, { why: string; when: Term[][] }> = {
  "cmt-pre-symmetry-projection": {
    why: "只投方法（群投影），不投答案",
    // 两项在同一组 = and：cmt 这一跑，**并且**题面提到对称性。
    // 只卡 run 的话 50 道全塞 —— 提示本身不含答案，但塞到无关的题上一样是噪声。
    // 题面带 symmetr 的是 13 道。
    when: [
      [
        { dim: "task", key: "run", op: "contains", value: "cmt" },
        { dim: "task", key: "description", op: "contains", value: "symmetr" },
      ],
    ],
  },
};

/** 抠 frontmatter。要读的就两样，`description` 会折行，续行以空格开头。 */
function front(text: string): { name?: string; does?: string; body: string } {
  if (!text.startsWith("---")) return { body: text };
  const end = text.indexOf("\n---", 3);
  if (end === -1) return { body: text };
  const head = text.slice(4, end);
  const body = text.slice(end + 4).replace(/^\n+/, "");
  const buf: Record<string, string> = {};
  let key = "";
  for (const line of head.split("\n")) {
    const m = /^([a-zA-Z_]+):\s?(.*)$/.exec(line);
    if (m) {
      key = m[1];
      buf[key] = m[2];
    } else if (key && /^\s+\S/.test(line)) {
      buf[key] += " " + line.trim();
    }
  }
  return { name: buf.name?.trim(), does: buf.description?.trim(), body };
}

const skills: Record<string, unknown>[] = [];
for (const file of [...new Bun.Glob("*.md").scanSync(HERE)].sort()) {
  const { name, does, body } = front(await Bun.file(`${HERE}${file}`).text());
  const id = name ?? file.replace(/\.md$/, "");
  const gate = GATE[id];
  if (!gate) {
    console.log(`跳过 ${id} —— GATE 里没给门，不知道什么时候该塞`);
    continue;
  }
  if (!does || !body.trim()) {
    console.log(`跳过 ${id} —— 缺 description 或正文`);
    continue;
  }
  console.log(`${id}：${gate.why}`);
  skills.push({ identity: id, does, params: {}, role: "user", body, when: gate.when });
}

if (skills.length === 0) {
  console.error("一个都没有");
  process.exit(1);
}

if (DRY) {
  console.log("\n--dry，不发：");
  console.log(JSON.stringify({ skills }, null, 2).slice(0, 1200));
  process.exit(0);
}

const res = await fetch(`${BASE}/declare`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ skills }),
});
const got = (await res.json()) as { skills?: string[]; error?: string; problems?: string[] };
if (!res.ok) {
  console.error(`整份都没写：${got.error}`);
  for (const p of got.problems ?? []) console.error(`  - ${p}`);
  process.exit(1);
}
console.log(`\n进去了：${got.skills?.join("、")}`);
