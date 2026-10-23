# ChemIQ —— G 设计表

题库：oxpig/ChemIQ `questions/chemiq.jsonl`，816 题，8 类（IUPAC 命名 200、原子映射 184、最短路径 108、NMR 解谱 96、反应 90、数碳 50、数环 48、SAR 40）。
判据：官方 `answer_verifier.py` 原样（RDKit 规范 SMILES；IUPAC 名走剑桥 OPSIN 网络服务转 SMILES；计数精确；SAR 区间）。

## 四个字段

| 字段 | 现在的值 | 理由 |
|---|---|---|
| 结构 | `parsed → correct` | 官方 parser 抽不出答案的算 parsed=0，和官方「格式错=0 分」口径一致 |
| 边界 | `noSearch` 挡 chemiq/oxpig | 题库在 GitHub；SMILES 本身搜不到答案 |
| **预算** | `checks: 3`，`maxDeadSiblings: 4` | 数碳/数环答案空间小（6–25，eacndev 估枚举可达 28%）——**这两类 F 臂要单独报**；SMILES/IUPAC/映射空间无限，3 次是干净的 |
| 信息级别 | ℓ0 | 可选 ℓ1：拒绝时告诉它 RDKit 解析失败还是不等价——对 NMR 解谱有用 |

## 注意
- OPSIN 是网络调用（每个 IUPAC 名一次，有缓存）；判卷台要能出网。
- 官方规定回答里有换行或超过 200 字符直接判错——所以 `suffix` 要求 boxed 里只放答案。
