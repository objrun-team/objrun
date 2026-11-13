# Data and archives

The full source checkout retains the program, manuscript source, final figures and plotting data, reproducible experiment source, required test inputs, and indexes, summaries, and hashes of experiment records. See the [record guide](../experiments/records/README.md) for the location and download procedure for complete run payloads. The [storage index](../experiments/records/external-storage.json) defines the remote address and revision.

## Experiment records

The catalogs, run indexes, coverage reports, and hashes in `experiments/records/` are the entry points for records. Complete payloads and detailed mappings live in external storage, selected with `records.py --root PATH` or `OBJRUN_RECORDS_ROOT`. Public plotting data remains in the full checkout's `paper/current/data/`; compiling the paper does not require restoring raw run directories.

## Test fixtures and historical inputs

[test/fixtures](../test/fixtures/README.md) contains only a small set of synthetic regression inputs. Historical self-check reports, raw API responses, balance snapshots, failure records, recovery reviews, old experiment exports, and compiled bundles are archived outside the repository with their original contents and hashes intact.

Scripts that need original records read `.local-evidence/repository/<original-repository-relative-path>`. `.local-evidence` is an ignored local directory link to the external archive and is not distributed with a clone. The `external_inputs` section of [directory-map.json](../scripts/directory-map.json) maps former docs paths to external inputs. Historical checks lack those inputs when the archive is unavailable; core tests and synthetic pricing/provider tests do not depend on it.

The archive created in this cleanup is in the project parent's `_objrun-cleanup-backup-20261104/followup-fixtures/archived/` directory, which contains `repository/`. Restore the link from the repository root:

```powershell
$archive = (Resolve-Path '../_objrun-cleanup-backup-20261104/followup-fixtures/archived').Path
New-Item -ItemType Junction -Path .local-evidence -Target $archive
```

On another machine, retrieve the original archive first, then point the link at the directory containing `repository/`. On Linux/macOS, use `ln -s /absolute/archive/path .local-evidence`. Any later upload location for historical material is recorded in the experiment storage index; local backup paths are not published download URLs.

Write new self-check reports to `.scratch/phase1/`, software-environment reports to `.scratch/software-preflight/`, and code-benchmark smoke reports to `.scratch/code-benchmarks/`. Do not write new output into historical archives or fixture directories. Rebuild compiled bundles with the retained build scripts; use `.scratch/` or another working directory for explicit output paths.

## Historical material

Old handoffs, phase plans, audit trails, paper revision records, and obsolete directory guides are stored in the project parent's `_objrun-cleanup-backup-20261104/` directory. Additional archived documents from this cleanup are under `followup-docs-examples/repository-before/`, organized by original repository-relative path. Its audit directory contains file hashes, move manifests, old-to-new commit mappings, and validation results.

The existing `_objrun-archive/` continues to hold earlier originals without content changes. Original Git backups are for recovering historical files and must not be pushed back to the cleaned remote. Directory links were recorded and their entries moved; external archives were not recursively modified.

See the [script index](../scripts/README.md) and [example index](../examples/README.md) for current executable locations. Old absolute paths, source SHA-256 hashes, and run IDs in historical evidence retain their original values. Replaying an old execution requires its original source and environment; a current script with changed paths must not be presented as the original executed version.
