"""Fixed data/service interfaces for the twelve prospectively selected tasks."""
MIB = 1024 ** 2
PROFILES = {
    "nginx-request-logging": {"kind": "live-nginx", "artifacts": {}},
    "openssl-selfsigned-cert": {"kind": "openssl-worker", "artifacts": {"/app/ssl/server.key": MIB, "/app/ssl/server.crt": MIB, "/app/ssl/server.pem": 2 * MIB, "/app/ssl/verification.txt": MIB, "/app/check_cert.py": MIB}, "directories": ["/app/ssl"]},
    "log-summary-date-ranges": {"kind": "data", "artifacts": {"/app/summary.csv": MIB}},
    "db-wal-recovery": {"kind": "data", "artifacts": {"/app/recovered.json": 4 * MIB}},
    "sqlite-db-truncate": {"kind": "data", "artifacts": {"/app/recover.json": 4 * MIB}},
    "chess-best-move": {"kind": "data", "artifacts": {"/app/move.txt": MIB}},
    "multi-source-data-merger": {"kind": "data", "artifacts": {"/app/merged_users.parquet": 32 * MIB, "/app/conflicts.json": 4 * MIB}},
    "regex-chess": {"kind": "data", "artifacts": {"/app/re.json": 16 * MIB}},
    "distribution-search": {"kind": "data", "artifacts": {"/app/dist.npy": 16 * MIB}},
    "raman-fitting": {"kind": "data", "artifacts": {"/app/results.json": MIB}},
    "query-optimize": {"kind": "readonly-sql", "artifacts": {"/app/sol.sql": MIB, "/app/oewn.sqlite": 1024 * MIB, "/app/my-sql-query.sql": MIB}},
    "constraints-scheduling": {"kind": "data", "artifacts": {"/app/meeting_scheduled.ics": MIB, "/app/alice_calendar.ics": MIB, "/app/bob_calendar.ics": MIB, "/app/carol_calendar.ics": MIB}},
}

SIX_TOOLS = ("bash", "read", "write", "edit", "glob", "grep")
FAMILY = "terminal-bench-twelve-journal-v1"
MIN_HOST_C_FREE = 1024 ** 3
MIN_HOST_F_FREE = 4 * 1024 ** 3
MAX_STREAM = 2 * MIB
MINIMUM_DISTINCT_TASKS = 10
