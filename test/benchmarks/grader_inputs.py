"""Exercise the real stand module inside its pinned grading container."""
import importlib.util
import json
import os

slug = os.environ["BENCH_SLUG"]
path = "/app/stand.py" if slug == "gpqa" else "/app/grader.py"
spec = importlib.util.spec_from_file_location("official_stand", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for prefix in ["", "pilot/"]:
    task_id = prefix + slug + "-0"
    tid, item, text = module.answer_of({"input": {"task": {"id": task_id}, "result": {"body": "candidate"}}})
    assert tid == task_id and item is module.BOOK[0] and text == "candidate"
print(json.dumps({"benchmark": slug, "namespacedCandidateChecks": 2, "passed": True}))
