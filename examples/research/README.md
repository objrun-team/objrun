# 科学问题实验

本目录保存目标定义、运行器、独立校验器及必要的恢复/收尾代码。具体问题由各目录的 GOAL、研究说明和校验器定义；原始日志、候选结果、证明证书与运行环境保存在仓库外。

| 目录 | 主要问题 |
| --- | --- |
| `conway99-search/` | Conway 99 图 |
| `covering-array-search/` | 覆盖数组 |
| `dna-code-search/` | DNA 编码 |
| `ks-original-search/` | Kochen–Specker 射线 |
| `lj-bound-search/`、`lj-conjecture-search/` | Lennard–Jones 下界与猜想 |
| `quadrature-search/` | 求积公式 |
| `rk-search/` | 低存储 Runge–Kutta |
| `rna-bound-search/` | RNA 可设计性上界 |
| `spherical-landscape/` | 球面能量景观 |

可离线复用各目录的独立校验器；完整运行还需要原环境和外置输入。先检查参数与依赖，不把恢复源码目录等同于已经复现结果。历史运行中的源文件哈希对应归档内的原始源码，当前目录调整后的路径见 `scripts/directory-map.json`。

Conway 的小规模离线自检：

```powershell
python examples/research/conway99-search/test_checkers.py tmp/conway99-checks
```

其他已知校验入口包括 `ks-original-search/checker.py`、`lj-bound-search/check.py` 和 `lj-bound-search/replay.py`；给它们显式传入候选/证书和输出路径。
