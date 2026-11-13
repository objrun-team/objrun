# Experiment records and local archive tools

The code repository retains only the indexes, summaries, and verification manifests under `experiments/records/`. Complete content and detailed mappings were moved out and removed from Git history. The complete candidate collection is now uploaded to the private HF Dataset [imontlaji/objrun-records](https://huggingface.co/datasets/imontlaji/objrun-records) for subsequent selection and editing. See `experiments/records/external-storage.json` for its address and pinned revision. `records.py runs` reads the repository index directly. Reading, extracting, and verifying content requires `--root` or `OBJRUN_RECORDS_ROOT` to point to a complete external record directory. See the [record guide](../../experiments/records/README.md) for download and reading instructions. Restoring the earlier Restic originals is not required to read this complete export.

`curate_records.py --root INPUT --output NEW_DIRECTORY --workspace WORKSPACE` creates the selection confirmed for this round from a verified export: it retains real records, decodes confirmed model responses, archives frozen source copies and synthetic batch fixtures, and retains self-test summaries, generators, and unique diagnostics. Input is read-only and output must be a new directory. Per-file decisions are written to manifests/selection-decisions-*; unselected originals are not deleted. These selection rules match the scope confirmed by a person for this round and should not be applied directly to unknown new sources.

`export_records.py` supports `--work`, `--output`, `--only`, and `--benches`. New exports use separate working directories; `--compression-level` controls compression. SQLite databases and WAL files inside archives are first paired by member path, then exported from consistent copies. Their order within a TAR/ZIP does not affect processing. Unpaired sidecar files and unverifiable databases must be registered and cannot be presented as complete records.

`append_records.py --base EXISTING_RECORDS --supplement VERIFIED_EXPORT --output NEW_DIRECTORY --label UNIQUE_LABEL --partial workspace-tmp` reuses existing fragments by hash. Original compressed shards remain unchanged; new fragments enter newly labeled shards. Output must be a new directory. Processing stops if a new source contains entries awaiting verification. `--partial` indicates that only sources for selected benchmarks are included, not that the entire batch is complete.

`records.py read --collection COLLECTION --path outer.zip --member inner.tar.gz --member run.sqlite --table events` reads tables inside nested archives. `verify` also checks row counts in these nested databases. Run regression checks with `python -B scripts/storage/test_records_export.py`. They use small temporary synthetic samples to verify real WAL dependencies, nested reads, redaction, and incremental deduplication without accessing original archives or the network.

Use the following tools for incremental curation of remaining sources. Each output uses a new directory; original archives are read-only:

- `recover_tar_records.py` recovers readable members from damaged TAR files. Truncated content retains its available bytes and declared length; partial recovery must not be described as a complete original.
- `repair_database_pairs.py` pairs renamed SQLite/WAL files using verified original sealing manifests. It checks original content hashes before exporting consistent copies and records the basis for each pairing. The exporter recognizes ordinary `.sqlite-wal.snapshot` names directly.
- `curate_embedded_payloads.py` identifies Base64-encoded resource bodies in JSON and retains their sizes, hashes, and paths. Textual tool evidence is not truncated; credentials embedded in text are also redacted. Conversion manifests explicitly distinguish original and export hashes.
- `redact_record_findings.py` corrects upload copies using object hashes identified by verification. Reports do not include matched values. Selection, packaging, and full verification must then be rerun to ensure that unredacted bytes in old shards cannot enter the commit either.
- `resume_export.py` reuses exported records by original content hash after a manifest write failure, then reads originals sequentially to fill gaps. Cached output is an intermediate directory that may contain unreferenced fragments; incremental merging and selection are required before publication.
- `prepare_incremental.py` compares source paths and hashes and places new or repaired entries in a separate source manifest. `--resource-hashes` accepts exclusion evidence verified against content. The tool registers unread entries, but registration alone does not establish a sufficient search or recovery; inspect the content first.
- `append_records.py` merges preparation manifests and their `entry_overrides`. Old paths resolve to repaired entries through `records.py`; old shards remain retained.
- `finalize_incremental.py` excludes resources using evidence-backed JSON path rules and repacks only unpublished fragments. Published shards selected by `--base` retain their bytes. The tool rebuilds run indexes and records exclusions.
- `verify_incremental.py` reuses baseline shard evidence, fully decompresses new shards, verifies hashes and reconstruction, checks database row counts, and scans new content, shard boundaries, and decoded metadata. Reads are restricted to the candidate record directory.
- `verify_samples.py` reconstructs real-run database inputs, outputs, tool records, states, and independent requests/responses/results using the selection manifest. Reading originals outside the record directory is prohibited. A successful sample proves only that sample, not completeness of all runs.
- `coverage_records.py` generates per-benchmark coverage tables from the current valid indexes, counting outer files, nested record references, database states, and source run scopes separately. These counts cannot be treated as numbers of independent experiments.
- `shard_object_index.py --root RECORDS` splits the object index into independent gzip shards of at most 25 MiB before final acceptance, records each hash, and checks mapping round trips. `records.py` supports both the old single-file index and the new `manifests/object-index.json`; content shards remain unchanged.
- `compact_record_reports.py --root RECORDS` converts large item-level resource-exclusion lists into hashed compressed shards. Summaries remain directly readable, and report compression does not discard exclusions.

`catalog.json` stores mappings from old source paths to repaired entries in `entry_overrides`. `source_sha256` always describes the original; the exported-content hash describes the transformed record. Resource exclusions, credential redaction, archive expansion, database export, and original truncation are recorded separately.

The Restic tools below maintain local originals for verification and recovery of complete historical environments only. The originals are retained in this round and are not publication assets.

Archive data lives in `_objrun-archive/` at the workspace root and is excluded from Git. Python 3.12+ and Restic 0.19.1 are required; this round's Windows cleanup scripts use PowerShell 7. The current tools preserve complete regular-file bytes, original paths, and modification times. They do not rely on Windows ACLs to restore experiment records.

The workflow for one collection:

1. `archive_collection.py` inventories a quiescent directory, streams TAR data into Restic, writes per-file SHA-256 manifests, and checks snapshot structure. Identical content blocks are deduplicated across collections using the highest compression level.
2. `verify_collection.py` reads every archived file in full, verifies SHA-256, paths, lengths, and link targets, and rechecks that the source directory has not changed.
3. `retire_collection.ps1` previews by default. Only explicit `-Apply` removes verified expanded files. It checks each path, removes directories nonrecursively, and stops when new files appear. It retains small inputs required by the project and skips registered unreadable directories.

Restore example (PowerShell; use the actual workspace and tool locations):

```powershell
$workspace = 'F:\git\TgEngin-handoff-2026-10-07'
$restic = "$workspace\_publication-preview\2026-10-23\compact-execution\tools\restic-0.19.1\restic_0.19.1_windows_amd64.exe"
python "$workspace\objrun\scripts\storage\restore_collection.py" `
  --workspace $workspace --name legacy-runs --restic $restic `
  --destination 'F:\git\objrun-restored-runs'
```

`--destination` must be empty by default. Explicit `--merge-existing` allows restoration into an old directory retaining small project inputs, but existing files must match the archived SHA-256; differing content is never overwritten. Every file's SHA-256 is rechecked after restoration.

To inspect a manifest or extract a single log without expanding the full historical directory:

```powershell
python "$workspace\objrun\scripts\storage\inspect_collection.py" `
  --workspace $workspace --name legacy-runs list --limit 20
python "$workspace\objrun\scripts\storage\inspect_collection.py" `
  --workspace $workspace --name legacy-runs extract `
  --path 'RELATIVE_FILE_PATH_FROM_MANIFEST' --output 'F:\git\selected-log.txt' --restic $restic
```

Single-file extraction also verifies SHA-256 and refuses to overwrite existing output. TAR collections must be read sequentially up to the matching content. This saves extraction space but does not guarantee immediate random access.

Directory-link/symlink targets are stored in source manifests and the collection directory's `last-restored-links.json`; TAR restoration does not recreate these links automatically. Raw reparse data is also retained for special WSL symlinks. Hard links are restored within each collection. Absolute paths in historical scripts remain verbatim; rerunning them requires consulting the path-migration map. Archive restoration does not imply that old containers can start directly.

Each collection directory contains `record.json`, compressed path manifests, per-file SHA-256 values, integrity-check results, and cleanup logs. Only collections with `restore_verified: true` may have their original expanded files removed. `excluded` identifies unread, undeleted scope. `kept_files` lists files retained during that cleanup batch; later batches may archive some of them. `expanded_kept_files` in the overall index identifies files still at their original paths.

`--external-readonly` supports registered experiment outputs outside the workspace. It only reads originals, and the cleanup tool explicitly refuses to delete such sources. This mode is used for this round's SciCode output and the actual targets of earlier run-directory links. See `experiments/provenance/external-source-map.json` for the correspondence between links and actual archives.

The local Restic repository uses an empty password. It follows the same filesystem access controls as the original local files and is not an encryption-based confidentiality measure. Originals are retained for local verification, and every collection currently remains `uploaded: false`; the new arrangement does not upload these originals.
