# Scientific research experiments

This directory contains objective definitions, runners, independent checkers, and necessary recovery/finalization code. Each directory's GOAL, research notes, and checkers define its problem. Original logs, candidate results, proof certificates, and runtime environments are stored outside the repository.

| Directory | Main problem |
| --- | --- |
| `conway99-search/` | Conway's 99-graph problem |
| `covering-array-search/` | Covering arrays |
| `dna-code-search/` | DNA codes |
| `ks-original-search/` | Kochen–Specker rays |
| `lj-bound-search/`, `lj-conjecture-search/` | Lennard–Jones lower bounds and conjectures |
| `quadrature-search/` | Quadrature formulas |
| `rk-search/` | Low-storage Runge–Kutta methods |
| `rna-bound-search/` | RNA designability upper bounds |
| `spherical-landscape/` | Spherical energy landscapes |

The independent checkers can be reused offline. Complete runs also require the original environments and external inputs. Check arguments and dependencies first; restoring a source directory does not reproduce a result by itself. Historical source hashes refer to the original source in the archive. See `scripts/directory-map.json` for the current relocated paths.

A small offline Conway self-test:

```powershell
python examples/research/conway99-search/test_checkers.py tmp/conway99-checks
```

Other known verification entry points include `ks-original-search/checker.py`, `lj-bound-search/check.py`, and `lj-bound-search/replay.py`. Pass explicit candidate/certificate inputs and output paths.
