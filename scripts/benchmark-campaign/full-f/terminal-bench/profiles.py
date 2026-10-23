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
PROFILES.update({
    "bn-fit-modify": {"kind": "data", "artifacts": {"/app/final_bn_sample.csv": 32*MIB, "/app/learned_dag.csv": MIB, "/app/intervened_dag.csv": MIB}},
    "code-from-image": {"kind": "data", "artifacts": {"/app/output.txt": MIB}},
    "count-dataset-tokens": {"kind": "data", "artifacts": {"/app/answer.txt": MIB}},
    "crack-7z-hash": {"kind": "data", "artifacts": {"/app/solution.txt": MIB}},
    "extract-moves-from-video": {"kind": "data", "artifacts": {"/app/solution.txt": MIB}},
    "fix-git": {"kind": "data", "artifacts": {"/app/personal-site/_includes/about.md": MIB, "/app/personal-site/_layouts/default.html": MIB}},
    "fix-ocaml-gc": {"kind": "data", "artifacts": {"/app/ocaml/tests.txt": MIB}},
    "gcode-to-text": {"kind": "data", "artifacts": {"/app/out.txt": MIB}},
    "mteb-leaderboard": {"kind": "data", "artifacts": {"/app/result.txt": MIB}},
    "mteb-retrieve": {"kind": "data", "artifacts": {"/app/result.txt": MIB}},
    "password-recovery": {"kind": "data", "artifacts": {"/app/recovered_passwords.txt": MIB}},
    "protein-assembly": {"kind": "data", "artifacts": {"/app/gblock.txt": MIB}},
    "regex-log": {"kind": "data", "artifacts": {"/app/regex.txt": MIB}},
    "vulnerable-secret": {"kind": "data", "artifacts": {"/app/results.txt": MIB}},
    "sparql-university": {"kind": "data", "artifacts": {"/app/solution.sparql": MIB}},
    "feal-linear-cryptanalysis": {"kind": "data", "artifacts": {"/app/plaintexts.txt": MIB}},
    "financial-document-processor": {"kind": "data", "artifacts": {}, "trees": {"/app/documents": 128*MIB, "/app/invoices": 128*MIB, "/app/other": 128*MIB}},
    "llm-inference-batching-scheduler": {"kind": "data", "artifacts": {
        "/app/task_file/input_data/requests_bucket_1.jsonl": 32*MIB,
        "/app/task_file/input_data/requests_bucket_2.jsonl": 32*MIB,
        "/app/task_file/output_data/plan_b1.jsonl": 32*MIB,
        "/app/task_file/output_data/plan_b2.jsonl": 32*MIB}},
    "caffe-cifar-10": {"kind": "caffe-worker", "artifacts": {
        "/app/caffe/.build_release/tools/caffe.bin": 64*MIB,
        "/app/caffe/build/tools/caffe": 64*MIB,
        "/app/caffe/examples/cifar10/cifar10_quick_iter_500.caffemodel": 128*MIB,
        "/app/caffe/examples/cifar10/cifar10_quick_solver.prototxt": MIB,
        "/app/caffe/examples/cifar10/cifar10_quick_train_test.prototxt": MIB,
        "/app/caffe/Makefile.config": MIB,
        "/app/caffe/build/CMakeCache.txt": 4*MIB,
        "/app/caffe/training_output.txt": 32*MIB}},
    "dna-insert": {"kind": "data", "artifacts": {"/app/primers.fasta": MIB}},
    "dna-assembly": {"kind": "data", "artifacts": {"/app/primers.fasta": MIB}},
    "build-pmars": {"kind": "pmars-worker", "artifacts": {"/usr/local/bin/pmars": 32*MIB},
                    "metadataGlobs": {"/app": "pmars-*"}},
    "prove-plus-comm": {"kind": "fixed-cli-worker", "artifacts": {"/app/plus_comm.v": MIB,"/app/plus_comm.vo": 16*MIB}},
    "rstan-to-pystan": {"kind": "fixed-cli-worker", "artifacts": {
        "/app/alpha_est.csv": MIB,"/app/beta_est.csv": MIB,"/app/rho_est.csv": MIB,"/app/sigma_est.csv": MIB}},
    "build-pov-ray": {"kind": "povray-worker", "artifacts": {
        "/app/povray-2.2/file_id.diz": MIB,"/app/povray-2.2/knownbug.doc": MIB,
        "/app/povray-2.2/povlegal.doc": MIB,"/app/povray-2.2/whatsnew.doc": MIB,
        "/app/povray-2.2/povdoc/include/colors.inc": MIB,
        "/app/povray-2.2/povdoc/include/shapes.inc": MIB,"/app/deps/illum1.pov": MIB}},
    "winning-avg-corewars": {"kind": "fixed-cli-worker", "artifacts": {
        "/app/my_warrior.red": MIB,"/app/warriors/stone.red": MIB,
        "/app/warriors/paper.red": MIB,"/app/warriors/vampire.red": MIB,
        "/app/warriors/snake.red": MIB,"/app/warriors/g2-clear.red": MIB}},
    "polyglot-c-py": {"kind": "polyglot-worker", "artifacts": {"/app/polyglot/main.py.c": MIB}},
    "polyglot-rust-c": {"kind": "rust-polyglot-worker", "artifacts": {"/app/polyglot/main.rs": MIB}},
    "git-leak-recovery": {"kind": "git-leak-worker", "artifacts": {"/app/secret.txt": MIB}},
    "custom-memory-heap-crash": {"kind": "heap-worker", "artifacts": {
        "/app/main.cpp": MIB,"/app/user.h": MIB,"/app/user.cpp": MIB}},
    "gpt2-codegolf": {"kind": "gpt2-worker", "artifacts": {"/app/gpt2.c": MIB}},
})
FAMILY = "terminal-bench-twelve-journal-v2"
MIN_HOST_C_FREE = 1024 ** 3
MIN_HOST_F_FREE = 4 * 1024 ** 3
MAX_STREAM = 2 * MIB
MINIMUM_DISTINCT_TASKS = 10
