# LLM-SRBench v2 reproduction

This directory contains the source for the historical v2 continuation protocol. It evaluates only the 483 cells that had not started in v1, preserving the 475 completed results and two interrupted cells from that earlier run. Results must be reported by protocol version.

The original continuation plan, source receipt and source diff are archived outside Git. Restore `.local-evidence/` as described in [storage](../../../../docs/storage.md) before using `local_ops.py stage`; staging copies the exact archived plan into the isolated experiment package. The original v1 package, results, dataset and runtime are also required.

The `*_controls.py` scripts exercise local protocol behavior. `continuation.py` checks the frozen plan and original evidence before further work; `audit.py` and `report.py` operate on the experiment package and its recorded outputs. These sources do not constitute a current authorization to restart a paid campaign.
