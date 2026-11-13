/**
 * Register the skills in this directory with the engine.
 *
 * ```
 * bun examples/benchmark/cmt/parmeras/load.ts [--dry]
 * ```
 *
 * Each `.md` contains frontmatter (`name`/`description`) plus a body, exactly the three values needed by a `skills[]` row:
 *
 * | `.md` | -> | `skills[]` |
 * | --- | --- | --- |
 * | `name` | | `identity` |
 * | `description` | | `does` |
 * | All text after frontmatter | | `body` |
 *
 * ## Define `when` here rather than copying it
 *
 * The old system used a `constants` trigger dimension. This system has `agent/task/cycle/chain/moment/place`, **with no constants dimension**. Rewrite the gates explicitly in `GATE`; each selected skill declares its applicability rather than relying on name-prefix inference.
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const DRY = process.argv.includes("--dry");
const HERE = new URL(".", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

type Term = { dim: string; key: string; op: string; value: string };

/**
 * Applicability of each migrated skill. **Do not register anything absent from this mapping.**
 *
 * ## `trigger` is a keyword-matching table
 *
 * Each `value` contains one keyword. `check` rejects spaces and asks for two rows in the same group rather than making the system guess. The three levels are:
 *
 * ```
 *   Groups                    OR     trigger.group
 *   Rows within a group       AND    multiple rows sharing a group
 *   Synonyms within one row   OR     op: "in", with a JSON list as value
 * ```
 *
 * The old `constants: [[["coding"], ["fits","card"]]]` maps exactly to this structure, with no missing information and no new dimensions or columns required.
 *
 * ## Keywords come from the extension itself
 *
 * For the same `description contains "symmetry"` rule, **keyword provenance** distinguishes legitimate matching from fitting the sample:
 *
 * | Keyword source | Assessment |
 * | --- | --- |
 * | The extension's declared name, description, or body markers | Valid: describes its purpose independently of how many dataset questions match |
 * | Keywords chosen after inspecting the 50 questions | Invalid: selecting samples from the samples gives some questions special treatment and silently inflates scores |
 *
 * This skill declares its purpose in its name `cmt-pre-symmetry-projection`, its description (symmetry projection for CMT), and the opening body marker (boundary-context marker + general method, `symmetry_projection`). Those declarations supply the keywords.
 *
 * Previous incorrect approaches are recorded to avoid repetition: `task.run` ties the rule to one run; `agent.name` alone binds it to one machine; `domain = "physics.cmt.hf"` packs a hierarchy into one string even though the dimensions are already separate.
 */
const GATE: Record<string, { why: string; when: Term[][] }> = {
  /**
   * Translate the skill's declared applicability into conditions:
   *
   * | Self-description | Condition |
   * | --- | --- |
   * | CMT in its description | `task.domain = physics` |
   * | `-pre-` in its name (a boundary-context marker injected at startup) | `cycle.cycle = ask` / `moment = unit_start` |
   * | `symmetry_projection` in its name/body | Two keywords on `task.description`, AND within one group |
   * | Method only, not the answer; intended for the model-speaking station | `task.mode = solve`, with ask/act stations |
   */
  "cmt-pre-symmetry-projection": {
    why: "Injected at the asking station of the solving mechanism, on physics problems involving symmetry. The keywords come from its own name and the marker in its body",
    when: [
      [
        // Problem category.
        { dim: "task", key: "domain", op: "eq", value: "physics" },
        { dim: "task", key: "description", op: "contains", value: "symmetry" },
        // Activity.
        { dim: "task", key: "mode", op: "eq", value: "solve" },
        { dim: "task", key: "source", op: "in", value: '["user","eacn"]' },
        // Timing.
        //
        // **Do not set `moment`.** Skills fire in `#advance`, whose facts do not contain moment. Only rules handled by `#atMoment` set it. A moment condition would silently never match.
        { dim: "cycle", key: "cycle", op: "eq", value: "ask" },
        // Execution place.
        { dim: "place", key: "", op: "eq", value: "local" },
      ],
    ],
  },
};

/** Extract frontmatter. Only two fields are needed; `description` may wrap onto indented continuation lines. */
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
    console.log(`skipping ${id} - GATE gives it no terms, so there is no telling when to inject it`);
    continue;
  }
  if (!does || !body.trim()) {
    console.log(`skipping ${id} - missing description or body`);
    continue;
  }
  console.log(`${id}：${gate.why}`);
  skills.push({ identity: id, does, params: {}, role: "user", body, when: gate.when });
}

if (skills.length === 0) {
  console.error("none at all");
  process.exit(1);
}

if (DRY) {
  console.log("\n--dry, not sending:");
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
  console.error(`nothing was written at all: ${got.error}`);
  for (const p of got.problems ?? []) console.error(`  - ${p}`);
  process.exit(1);
}
console.log(`\nwent in: ${got.skills?.join(", ")}`);
