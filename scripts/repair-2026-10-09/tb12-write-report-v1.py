"""Write the reviewable paired trial report from verified real receipts."""
import argparse
from decimal import Decimal
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-directory", required=True)
    args = parser.parse_args()
    home = Path(args.run_directory).resolve()
    def read(name):
        return json.loads((home / name).read_bytes())
    review, audit = read("independent/deep-review.json"), read("independent/raw-audit.json")
    summary, manifest = read("summary.json"), read("manifest.json")
    cash = read("cash/cash-close.json")
    assert review["integrityValid"] and audit["integrityValid"] and summary["operationalComplete"]
    assert summary["providerKind"] == "real-provider" and len(review["tasks"]) == 24
    assert read("entry-closed.json")["canonicalOwnerReleased"]
    scores = audit["result"]["score"]
    money = Decimal(cash["snapshot"]["newKnownEstimatedNanoCny"]) / Decimal(1000000000)
    assert money <= 9 and cash["snapshot"]["pendingCount"] == cash["snapshot"]["newUnknownCount"] == 0
    rows = {(row["taskId"], row["arm"]): row for row in review["tasks"]}
    lines = ["# Terminal-Bench 固定 12 题真实 U/F 试跑审阅", "",
             "本轮完成固定 12 道不同题、24 条真实 U/F 记录。独立原始材料审计与额外评分回放均通过；所有精确 owned 容器、引擎和评分服务已关闭，共享 canonical owner 已按独立关闭凭据释放。旧 nginx 单题不计入本轮。", "",
             f"U：{scores['U']}/12；F：{scores['F']}/12。累计 {summary['modelCalls']} 次真实模型请求。按原始 usage 与公开人民币价目重放的新增费用估算为 **{money} 元**，授权上限 **9 元**；pending 与新增 unknown 均为 0。原 **8.39218 元**未结预留继续保留，没有因本轮关闭而结清。费用估算不是发票。", "",
             "| 固定题目 | U | F | U/F 模型请求 | U/F 运行中 verify | U/F 实际评分次数 |",
             "|---|---|---|---|---|---|"]
    for task_id in manifest["taskIds"]:
        u, f = rows[task_id, "U"], rows[task_id, "F"]
        def verdict(row):
            return "通过" if row["passed"] else row["outcome"]
        lines.append(f"| {task_id} | {verdict(u)} | {verdict(f)} | {u['modelRequests']}/{f['modelRequests']} | {u['runtimeVerifyCalls']}/{f['runtimeVerifyCalls']} | {u['actualPrivateGrades']}/{f['actualPrivateGrades']} |")
    lines += ["", "`no_candidate` 等实验失败按冻结协议记 0，不能写成原测试已执行且失败。`rejected` 表示实际提交后的评分未通过。表中的评分次数包含 F 的运行中检查与已执行的最终检查；不把它们算作不同题目或重复试跑。", "",
              "独立审阅逐条核对原生评分器 stdout 最后帧、invocation ID、实际退出、48 个原测试的逐项 CTRF、私有源码和依赖版本、候选/评分器 PID 与 mount namespace、网络隔离、保护输入哈希，以及最终评分前实际引擎关闭。完整 raw request/response、SQLite 轨迹、事件链、代码快照、各次故障和关闭证明保留在本轮目录。", "",
              "准备阶段实际完成每题空/正/错共 36 个对照、原测试 collection、12 题原六工具与存储测量、OpenSSL 不可信岛双对照，以及真实项目引擎的零模型联调。模拟响应和准备对照均不计本轮模型请求或成绩。", "",
              "本轮范围为按公开元数据冻结的 12/89 题、11 类、每题一组 U/F，顺序固定为 U 后 F。它不证明全量表现或任务频率代表性。模型仅能固定请求别名 deepseek-flash；provider 原响应也返回该别名，不能据此声称不可变底层检查点。temperature 0 与 seed 42 不构成确定性保证。", "",
              "原 agent/verifier 秒数保留。额外操作边界为每请求最多 8192 输出 token、每循环最多 32 单元、F 最多 4 次检查、工具流 2 MiB 及按题文件捕获上限。原 test.sh 归档，实际通过明确的新离线 runner 执行原 tests；不能把该 runner 写成官方整套执行环境。", "",
              "Docker 后端实际不支持 10 GiB 每容器硬配额。本轮在模型前实测可用存储至少 10 GiB，工具前后与 seal 时采样 writable layer 并拒绝越界候选；**不是连续硬限制**。nginx 是受限 TLS 活态观察，不是不可变文件系统快照。OpenSSL 候选脚本只在独立不可信岛执行，stdout/stderr/exit 作为数据交给私有 checker。", "",
              "F 反馈为 ran/passed 布尔值和通用失败说明，没有把私有断言发给模型。CSV/JSON/NPY/Parquet/SQLite 等均按白名单捕获；NPY 禁用 pickle，SQLite 禁扩展且只读，原数据库/参考 SQL 与日历在评分时保持一致。", "",
              "原始独立审计：`independent/raw-audit.json`。额外评分审阅：`independent/deep-review.json`。财务关闭：`cash/cash-close.json` 与 `independent/close-certificate.json`。即时资源复查：`fresh-absence/`。授权原文、协议和依赖固定点在准入与 readiness 引用中。", "",
              "本轮等待用户确认；不自动启动全量、R 或论文修改。", ""]
    target = home / "README.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(target), "score": scores, "estimatedCny": str(money), "modelRequests": summary["modelCalls"]}))


if __name__ == "__main__":
    main()
