"""Record confirmed F900 selection without editing the prior review or runners."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/repair-2026-10-08"


def pin(path):
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha}


def save(path, value, raw=False):
    data = value if raw else (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == data
    return pin(path)


def main(output):
    output = Path(os.path.abspath(output))
    assert output.parent == DOC and output.name.startswith("chemiq-f-formal-readiness-") and not output.exists()
    prior = DOC / "chemiq-f-formal-readiness-v1/readiness.json"
    prior_pin = pin(prior)
    assert prior_pin["sha256"] == "6ab710bc86d050dbb985f0c70ddcc349eeed82874dc578cac0b577e12f336818"
    review = json.loads(prior.read_bytes())
    scope_pin = review["formalTarget"]["scopeArtifact"]
    assert pin(Path(scope_pin["path"])) == scope_pin
    assert scope_pin["sha256"] == "8a1d219398fa36877a00a14c253601df9fd38dddc986726233b48c16319e6b12"
    inputs = review["sourceAndInputPins"] + [prior_pin, scope_pin, pin(Path(__file__))]
    assert all(pin(Path(item["path"])) == item for item in inputs)
    review["protocol"] = "chemiq-f-formal-readiness-v2-900s"
    review["createdAtUtc"] = datetime.now(timezone.utc).isoformat()
    review["derivedFrom"] = prior_pin
    review["timeSelection"] = {
        "solveSeconds": 900, "selectedByUser": True,
        "trustedInstruction": "Root relayed the user's explicit selection of900s on2026-10-09; this records preparation only, not a model launch",
        "priorAlternativesRetained": [600, 900], "priorReviewModified": False,
        "oldFDeclaredTimeComparable": True, "entireOldProtocolReproduced": False,
    }
    review["prospectiveSettings"].update({
        "selectedSolveSeconds": 900,
        "timeSelection": "User explicitly selected900s; new entry/recipe/cash guard remain pending",
    })
    review["formalTarget"]["solveSeconds"] = 900
    review["minimumRepresentativeFPilot"]["solveSeconds"] = 900
    review["minimumRepresentativeFPilot"]["queryAndTimeSettings"] = "Confirmed900s; same checks5/branches4/model/decoding/profile to be frozen for pilot and later formalF"
    review["sourceAndInputPins"] = inputs
    review["requiredBeforeRepairedFormalFullF"] = [item.replace("selected600or900s", "selected900s") for item in review["requiredBeforeRepairedFormalFullF"]]
    review["formalPaidReady"] = False
    review["executionRecipeFrozen"] = False
    assert review["formalTarget"]["denominator"] == 816 and len(review["minimumRepresentativeFPilot"]["taskRecords"]) == 16
    assert all(pin(Path(item["path"])) == item for item in inputs)
    output.mkdir()
    report_pin = save(output / "readiness.json", review)
    pilot = review["minimumRepresentativeFPilot"]["taskRecords"]
    table = "\n".join(f"| {item['officialIndex']} | {item['officialId']} | {item['category']}/{item['subCategory']} |" for item in pilot)
    scenarios = [item for item in review["feeTimeByteScenarios"]["scenarios"] if item["scenarioSolveSeconds"] == 900]
    costs = "\n".join(f"| {item['FTaskRuns']} | {float(item['cachedUsdPeakRateScenario']):.2f} | {float(item['noCacheUsdPeakRateScenario']):.2f} | {float(item['cachedCnyAllPeakTokenScenario']):.2f} | {float(item['noCacheCnyAllPeakTokenScenario']):.2f} |" for item in scenarios)
    text = f"""用户已明确选择 ChemIQ F 每题 **900 秒**。完整目标为原题序 **816 题、每题1次F、共816次**，16题代表性试跑也使用900秒。此件没有生成、评分或启动模型；`formalPaidReady=false`，独立执行入口、recipe/source与cash仍未冻结。

| 对象 | 任务及状态 | 时间/预算 | 差异 |
|---|---|---|---|
| 旧F0731 | 816，存680通过，实际4claimed；scorecard计0running | 900秒/checks3/K8/search3 | 历史source/checkpoint未认证，finalvalidity0 |
| 旧Fc5kinf0929 | 816，存633通过，实际6claimed；303search全402 | 900秒/checks5/K100000/search3 | 不作为新正式成绩 |
| 真实10题F试跑 | 10，3通过；仅NMR/zinc_2d | 180秒/checks5/branch4/无search | 原shutdown超时与laterclosing均保留；不代表816 |
| 本次新F目标 | 原816ID全部保留；未执行 | **900秒**/checks5/branch4/K100000/无search | 新deepseek-flash，8192/temp0/seed42/reasoningnone；非旧0731 checkpoint复现 |

同一任务范围见原 [task-scope.json](../chemiq-f-formal-readiness-v1/task-scope.json)，209,338字节，SHA `{scope_pin['sha256']}`。原待选版本与全部输入SHA未回写；本次再次逐项核验当前字节不变。范围只包含ID/prompt摘要，无参考答案。900秒与旧F时间相同，并不认证模型、搜索、预算、评分与旧运行整体等价。

修订评分采用固定local OPSIN2.8.0 + raw-input-length，REST fallback=false，level0；原子映射的原文200字限制修复30道误拒。官方parser/RDKit判等保持原源。已有同source正控782/816，负值/结构与格式负控各816；34个IUPAC正参考仍缺，random/canonical各17。全部34准确ID在JSON，不能删分母、记成答错或宣称完全修复。应先补私有正确名称并验证；少量pilot不能替代这一步。该协议与旧未知REST或官方parsed-length成绩不同。

最小代表性试跑固定 **16F900**：14个类别/子类/判法各取原题序首题，再加两个25原子映射边界。覆盖8类别、14子类/判法、5评分方法，全部16已有正控；未按模型成绩选择。缺参考34题并不因此获得认证，补齐正参考后可用JSON预定的两题做额外诊断。是否将pilot纳入正式预定子集必须在生成前决定，不能拼接变更后的协议或挑成功样本。

| 原题索引(0起) | 固定taskID | 类别/子类 |
|---|---|---|
{table}

费用只按原10道NMR F180的真实token做900/180压力场景：

| F次数 | 缓存USD峰价估算 | 无缓存USD峰价估算 | 全峰CNY独立估算 | 无缓存全峰CNY独立估算 |
|---|---|---|---|---|
{costs}

这些数字不是发票、汇率转换、收费硬上界或当前余额；NMR不是代表性费用样本。用户表示会充值不代表已到账，Root需临近启动获取真实余额/TTL、冻结独立cash envelope，保留原4未知费用8.39218CNY。每次provider forward前先持久raw+admission+现金预留；完整usage/late回执、未知费用、共享ownerwx均不得绕过。

checks5限制显式检查，runtime自动与最终独立判卷要另计物理G调用；不得声称全G只有5次或U/F等预算因果效应。现有冻结scientific计划仍产生U/F，且其16题calibration选择不同，因此需另建F-only入口/审核，不改原81源。原全JSON热重写不可直接扩至816，现cash全历史计数与128MiB单Pin/256MiB现金元数据上限也须依据新pilot实际量做范围评估。

启动前还需新鲜私有grader/source/runtime/JAR/queue/正负控、RAM与磁盘门、封口候选摘要、原始trace/wire/token/费用、明确的时限与评分分组及精确所有权收尾。历史环境观察和16覆盖不能替代新运行证据。任何invalid保持invalid，部分分数不得标816完整分数。没有修改论文、旧数据、原包或冻结执行来源。

完整 [readiness.json](readiness.json)：{report_pin['bytes']}字节，SHA `{report_pin['sha256']}`。
"""
    markdown_pin = save(output / "readiness.md", text.encode(), raw=True)
    print(json.dumps({"report": report_pin, "markdown": markdown_pin, "scope": scope_pin,
                      "source": pin(Path(__file__)), "selectedSolveSeconds": 900,
                      "formalPaidReady": False, "modelCalls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    main(parser.parse_args().output_dir)
