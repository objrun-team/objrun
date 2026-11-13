# Current benchmark coverage

| Bench | Coverage status | Retained outer files | Source run scopes | Allocated compressed MB | Real-sample recovery |
| --- | --- | ---: | ---: | ---: | --- |
| aime | All discovered readable records covered | 1,607 | 38 | 3.461 | Passed |
| astrovisbench | No usable detailed records found | 1 | 1 | 0.000 | Not applicable: metadata only |
| atmossci | All discovered readable records covered | 35 | 6 | 0.083 | Passed |
| atomworld | All discovered readable records covered | 7 | 3 | 0.492 | Passed |
| biocoder | All discovered readable records covered | 29 | 5 | 0.053 | Passed |
| bird | All discovered readable records covered | 157,184 | 18 | 146.799 | Passed (prior evidence reused) |
| chembench | All discovered readable records covered | 14,056 | 324 | 57.059 | Passed |
| chemiq | All discovered readable records covered | 47,755 | 408 | 199.585 | Passed |
| classeval | All discovered readable records covered | 6,764 | 8 | 10.433 | Passed (prior evidence reused) |
| cmt | All discovered readable records covered | 165 | 40 | 22.745 | Passed |
| deepswe | All discovered readable records covered | 53 | 16 | 13.663 | Passed |
| frontierscience | All discovered readable records covered | 11,470 | 329 | 12.114 | Passed |
| gpqa | All discovered readable records covered | 7,127 | 39 | 27.096 | Passed |
| humaneval-plus | All discovered readable records covered | 16,807 | 16 | 8.820 | Passed |
| labbench | All discovered readable records covered | 46,263 | 3,644 | 91.079 | Passed |
| llm-srbench | All discovered readable records covered | 31,886 | 18 | 82.187 | Passed |
| mbpp-plus | All discovered readable records covered | 11,906 | 7 | 4.209 | Passed |
| minif2f | All discovered readable records covered | 39,749 | 107 | 74.529 | Passed |
| olympiadbench | All discovered readable records covered | 26,125 | 2,228 | 44.483 | Passed (prior evidence reused) |
| scibench | All discovered readable records covered | 66,415 | 48 | 48.140 | Passed (prior evidence reused) |
| scicode | All discovered readable records covered | 56,917 | 19 | 114.531 | Passed |
| scienceworld | Unreadable sources remain | 33 | 6 | 0.278 | Passed |
| shared-or-unassigned | Shared or unassigned evidence | 360,730 | 1,952 | 435.249 | See related benchmarks |
| skillsbench | Partially retained; originals missing or damaged | 293,727 | 5,791 | 1231.027 | Passed |
| terminal-bench | Partially retained; originals missing or damaged | 1,168,597 | 2,403 | 1013.352 | Passed |
| theophyseval | All discovered readable records covered | 47,842 | 614 | 54.621 | Passed (prior evidence reused) |

Source run scopes, file references, message-row references, and database states are not counts of independent experiments or unique trajectories. Sizes are allocated according to content ownership within shared shards and may differ due to rounding; the total physical shard size is listed separately. Successful sample recovery does not imply complete evidence for every historical attempt.

For item-level sources, exclusions, gaps, and unread directories, see `../reports/current-bench-coverage.json` and `../reports/bench-coverage.csv`.
