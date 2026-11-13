# Experiment record index and external content

The code repository retains run indexes, summaries, current coverage reports, and SHA-256 manifests. Complete content shards, per-file mappings, and historical curation reports were moved outside the repository on 2026-11-04 and removed from the published Git history. On the same day, the complete candidate collection was uploaded to the private Hugging Face Dataset [imontlaji/objrun-records](https://huggingface.co/datasets/imontlaji/objrun-records) for subsequent selection and editing. Cloning the code repository alone does not provide complete trajectories.

Complete local record directory:

```text
F:\git\TgEngin-handoff-2026-10-07\_objrun-cleanup-backup-20261104\repository-before\experiments\records
```

Both the local backup and the HF dataset include `catalog.json`, `packs/`, `manifests/`, `runs/`, `reports/`, and `summaries/`. Original content shards and reconstruction mappings retain their original bytes. The HF dataset homepage includes download and reading instructions. The current candidate collection contains 2,857 files totaling approximately 4.05 GB, plus an HF-generated `.gitattributes` file. All remote file sizes and hashes match. Download spot checks passed for 7 files, including decompressed-hash verification of 3 content shards.

The pinned revision is [`5c00daab7319c87fa89ede743f07873d3114ef45`](https://huggingface.co/datasets/imontlaji/objrun-records/tree/5c00daab7319c87fa89ede743f07873d3114ef45); its address and revision are also recorded in [external-storage.json](external-storage.json). The dataset's `main` branch may continue to change. Use this pinned revision to read the candidate collection described here. Historical reports describe only the state when they were generated.

After signing in with an authorized HF account, download the complete directory with `huggingface_hub`; downloading only the packs is insufficient:

```powershell
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='imontlaji/objrun-records', repo_type='dataset', revision='5c00daab7319c87fa89ede743f07873d3114ef45', local_dir='F:/objrun-records')"
```

To inspect only the index stored in the repository:

```powershell
python -B scripts/storage/records.py runs --bench labbench --limit 20
```

Reading content requires Python 3.12+ and zstandard from `requirements-records.txt`. Explicitly select the backup directory or a complete downloaded directory. For the download location above, change `$recordsRoot` below to `F:\objrun-records`:

```powershell
$recordsRoot = 'F:\git\TgEngin-handoff-2026-10-07\_objrun-cleanup-backup-20261104\repository-before\experiments\records'
python -B scripts/storage/records.py --root $recordsRoot files --bench terminal-bench --limit 20
python -B scripts/storage/records.py --root $recordsRoot --isolated read --collection COLLECTION --path 'PATH_FROM_INDEX'
python -B scripts/storage/records.py --root $recordsRoot extract --collection COLLECTION --path 'PATH_FROM_INDEX' --output 'F:\selected-log.txt'
python -B scripts/storage/records.py --root $recordsRoot verify
```

You can also set `OBJRUN_RECORDS_ROOT`; the command-line `--root` takes precedence. Without an external content directory, content reads give an explicit diagnostic while the index remains accessible. Use `--table TABLE_NAME` for SQLite tables and repeatable `--member MEMBER_PATH` arguments for archive members. Extraction refuses to overwrite existing output.

`manifests/packs.json` records the length and SHA-256 of each content pack. `manifests/object-index.json` records the SHA-256 of external object-index shards. `catalog.json` retains source collections and detailed manifest locations. These relative paths in the repository are rooted at the complete external record directory; they do not mean that the content exists in this repository.

For current coverage, see the [coverage table](summaries/coverage.md), [current report](reports/current-bench-coverage.json), and [original gaps](reports/original-source-gaps.json). Evidence of failures, interruptions, retries, and successes is retained externally. The relocation neither fabricated missing records nor reran experiments or grading. `source_sha256` describes the original file; `content.sha256` describes previously exported content. They are distinct.
