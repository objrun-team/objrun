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

/**
 * 每个搬过来的 skill 适用于什么处境。**没写在这儿的不注册。**
 *
 * ## `trigger` 是一张关键词匹配表
 *
 * 一个 `value` 一个关键词（带空格会被 `check` 拦下来：「拆成同一组的两条，别让系统
 * 猜」）。三层结构齐了：
 *
 * ```
 *   组          之间 or            trigger.group
 *   组内一条条  之间 and           同组多行
 *   一条内的同义词  or             op: "in"，value 是一份 JSON 列表
 * ```
 *
 * 老仓库那个 `constants: [[["coding"], ["fits","card"]]]` 一比一就是这个形状，
 * 什么都不缺 —— 所以搬过来不用加维、不用加列。
 *
 * ## 关键词从扩展自己身上来
 *
 * 这是关键的一条。同样是 `description contains "symmetry"`，**词是哪儿来的**决定了
 * 它是正经匹配还是按样本拟合：
 *
 * | 词的来源 | |
 * | --- | --- |
 * | 扩展自己声明的（名字 / 描述 / 正文里的标记） | ✔ 它在说「我是干这个的」，跟数据集里命中几道无关 |
 * | 我翻了 50 道题挑出来的 | ✘ 拿样本挑样本，给一部分题开小灶，分数虚高还查不出来 |
 *
 * 下面这个 skill 自己声明得很清楚：名字 `cmt-pre-symmetry-projection`、描述
 * 「对称性投影（CMT）」、正文头一行 `=== 边际处境标记 + 通用方法(symmetry_projection)===`。
 * 关键词就取自这儿。
 *
 * 还试过几种错的，记着免得再犯：`task.run`（绑在某一次考试上，换一跑就没了）、
 * `agent.name` 单独一条（焊死在一台机器上）、`domain = "physics.cmt.hf"`
 * （把层级塞进一个串里 —— 维已经分好了，不该在值里再分一遍）。
 */
const GATE: Record<string, { why: string; when: Term[][] }> = {
  /**
   * 它自己声明的处境，逐段翻成条件：
   *
   * | 它说自己是什么 | 翻成 |
   * | --- | --- |
   * | 描述里的「（CMT）」 | `task.domain = physics` |
   * | 名字里的 `-pre-`（边际处境标记，开工时投） | `cycle.cycle = ask`｜`moment = unit_start` |
   * | 名字/正文里的 `symmetry_projection` | `task.description` 上两条关键词，同组 and |
   * | 「只投方法不投答案」 = 给模型开口那一站用 | `task.mode = solve`（有 ask/act 两站的那种机制） |
   */
  "cmt-pre-symmetry-projection": {
    why: "解题机制的提问站上，面对涉及对称性的物理题时投。关键词取自它自己的名字和正文标记",
    when: [
      [
        // 面对什么问题
        { dim: "task", key: "domain", op: "eq", value: "physics" },
        { dim: "task", key: "description", op: "contains", value: "symmetry" },
        // 在做什么事
        { dim: "task", key: "mode", op: "eq", value: "solve" },
        { dim: "task", key: "source", op: "in", value: '["user","eacn"]' },
        // 什么时候
        //
        // **不能写 `moment`。** skill 是在 `#advance` 里 fire 的，那份 facts 不带
        // moment（只有规则走的 `#atMoment` 才设），写了就永远不中 —— 而且不报错。
        { dim: "cycle", key: "cycle", op: "eq", value: "ask" },
        // 在哪儿
        { dim: "place", key: "", op: "eq", value: "local" },
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
