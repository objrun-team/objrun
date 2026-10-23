# 沉淀（distill）—— 从判决史里抽 skill，用留出题验它

这是 agentos 那边「降解 → 结晶 → 入林」那一环在 TgEngin 上的版本。**内核一个字没动**：
产物是 `skill` 表的行（`POST /declare` 灌），触发是 `trigger` 表的条件。
跟那边最大的不同是验收：**一份 skill 有没有用，只看它没见过的题上 U 臂涨没涨**。
同一道题 ✖→✓ 不算数（agentos 的用法案例册里 7490 那一案就是这么被证伪的：单点翻了，同类 4 题 0/4）。

## 四步

```
cd app                                   # bun 脚本一律从 app/ 起（这台节点 bun 读 .env 撞 statx）
set -a; . ../.env; set +a                # OPENROUTER_API_KEY
D=../runs/distill-cmt
bun ../examples/distill/run.ts harvest ../runs/cmt-f-0731/h2h.sqlite ../runs/cmt-u-0731/unaided.csv --out $D/harvest.json
bun ../examples/distill/run.ts extract $D/harvest.json --only <训练半 id> --out $D/candidates-A.json
bun ../examples/distill/run.ts land    $D/candidates-A.json $D/harvest.json --domain physics --corpus <训练半 id> --out $D/declare-A.json
bun ../examples/distill/run.ts probe   $D/declare-A.json $D/harvest.json --only <留出半 id>
bun ../examples/distill/run.ts pool    $D/candidates-A.json $D/harvest.json --domain physics --corpus <训练半 id> --out $D/declare-pooled-A.json
```

| 步 | 做什么 | 调模型 |
| --- | --- | --- |
| `harvest` | 从 F 臂的库读每道题每个 node 上验过的原文和判决，配上 U 臂成绩；默认只留「没反馈做不对、有反馈做对了」的题 | 否 |
| `extract` | 每道题一份候选：`does` / `body` / 从题面原样抄的触发词 / 类别标签 | 是 |
| `land` | 四道闸（`app/src/distill/gate.ts`）→ 过了的拼成声明；触发 = domain + 根站 + 题面里至少共现两个触发词 | 否 |
| `probe` | 不跑引擎，算一份声明会在哪些题面上触发 | 否 |
| `pool` | 第二级：把多份单题教训并成一份领域级的，只按 domain 触发 | 是 |

## 四道闸

| 闸 | 拦什么 | 抄自 |
| --- | --- | --- |
| 指纹 | 正文含这道题被判过的任何一段原文（对错都算） | `degrade/submit.py` 题号指纹 |
| 词在题面 | 触发词必须是题面里原样的子串，不然引擎的 `contains` 永远不命中、零报错 | 「静默不生效」 |
| 双边探针 | 触发词命中来源题、且命中语料里至少另一道、且不超过 30% | `locate.probe_for` |
| 别人的答案 | 正文含语料里其它题被判对的原文 | — |

**闸拦不住的**：把答案写成散文（「对这类模型，正确说法是 X」）。判过的原文是 `\boxed{c}` 这种选项字母时，
指纹闸对散文无能为力。所以留出验证不是可选项。

## 留出验证（CMT，2026-09-27）

训练半 = 偶数下标 25 题，留出半 = 奇数下标 25 题；对照 = `runs/cmt-u-0731` 里留出半那 25 行。

| 阶段 | 结果 |
| --- | --- |
| 训练半里「反馈教会的」题 | 16 |
| 按题抽的 skill，全词 AND | 14 单题、2 词不在题面、0 落地 |
| 任两词共现 | 2 落地，留出半触发 **0/25** |
| 汇成一份领域级 skill | 过闸；留出半 U 臂见 `runs/cmt-u-distill-B/` |

`runs/cmt-distill-holdout.sh` 把上面整条流程串起来；`runs/cmt-arm.sbatch` 收 `SKILLS=` 和 `TGENGIN_CMT_ONLY=`。

## 全集验证（CMT 50 题抽、同 50 题测，2026-09-27，`runs/cmt-u-distill-all`）

用户点名要的「抽题即测题」那一跑：30 道反馈教会的题各抽一份，过指纹闸的 26 份（含 22 份只命中自己的）+ 1 份汇总，全挂。

| 组 | n | 基线 U | 挂后 U |
| --- | --- | --- | --- |
| 有自己那份 skill（抽自本题的判决） | 26 | 0 | **15** |
| 只有汇总 skill | 24 | 13 | **5** |
| 合计 | 50 | 13 | 20（+7） |

涨的 15 道全部是「自己那份」挂上的题，跌的 8 道全部是只挂了汇总的题。
前者就是答案回流（留出半上同样的 skill 触发 0/25、汇总 Δ=0），后者说明一段不相干的领域级 checklist
在 U 臂上是**负作用**。两组加起来的 +7 不能当成学习环的收益。

## ChemBench 留出验证（2026-09-27，`runs/distill-chembench/`）

F 500 题子集按 topic 内对半：训练 253 / 留出 247；基线 = `runs/chembench-u-0731b` 同 247 题（167/247）。
训练半里反馈教会的 46 题各抽一份 → 任两词共现、份额上限 50%（preference 题占 37%）→ 33 落地、8 单题、5 拒。
另按 topic 汇总两份：preference（触发 `Imagine an early virtual screening campaign`，训练半 94/94 命中、其它 0）、
toxicity（触发 `safety risks|hazard|toxic|safe handling` 任一）。

| topic | n | 基线 | 全挂 35 份 | 只挂 2 份汇总 |
| --- | --- | --- | --- | --- |
| chemical_preference | 93 | 56 | −2（每题被塞 25 份） | +0 |
| toxicity_and_safety | 58 | 27 | **+4** | **+5** |
| 其它 7 个 topic | 96 | 84 | +3 | −4 |
| 合计 | 247 | 167 | +5 | +1 |

没触发任何 skill 的 79 题在全挂臂上 +2：这就是跑与跑之间的噪声量级。所以只有 toxicity 那 +4/+5 值得再看；
`runs/chembench-u-hold-control`（不挂 skill 的对照重跑）用来量噪声。
preference 那 22 份单题 skill 触发词互相重叠，一题 25 份，是负作用 —— 触发面窄不只是防泄题，也是防互相踩。

**对照重跑（`chembench-u-hold-control`，不挂 skill，同 247 题）= 175/247**，比两天前的基线高 8，与它有 24 题不一致 —— 这是跑与跑之间的噪声。按它重算：

| topic | n | 对照 | 全挂 | 只挂汇总 |
| --- | --- | --- | --- | --- |
| chemical_preference | 93 | 63 | 54（−9） | 56（−7） |
| toxicity_and_safety | 58 | 28 | 31（+3） | 32（+4，翻对 4 翻错 0） |
| 其它 | 96 | 84 | 87 | 80 |
| 合计 | 247 | 175 | 172（−3） | 168（−7） |

结论：整体是负的；preference 的 skill（无论 22 份还是 1 份汇总）都把原本会做的题带偏；唯一疑似正向的是 toxicity 汇总那份
（+4，0 翻错，toxicity 在两个无 skill 跑之间只有 3 题不一致），量级小，要再做才敢说。
