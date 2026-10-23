"""Small authorized protocol probe; never starts a benchmark or prints credentials."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "docs/repair-2026-10-10/openrouter-submit" / uuid.uuid4().hex
HOME.mkdir(parents=True)
key = os.environ.get("OPENROUTER_API_KEY")
for candidate in (ROOT / ".env",):
    if key or not candidate.exists():
        continue
    for line in candidate.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$", line)
        if match:
            key = match.group(1).strip().strip('"').strip("'")
if not key:
    raise SystemExit("OPENROUTER_API_KEY is missing; no model request made")

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def save(name, data):
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    path = HOME / name
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}

def request(path, body=None):
    raw = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request("https://openrouter.ai/api/v1/" + path,
        data=raw, headers={"Authorization": "Bearer " + key,
        "Content-Type": "application/json", "X-OpenRouter-Title": "TgEngin protocol verification"},
        method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())

status, credit = request("credits")
if status != 200:
    save("balance-error.json", {"httpStatus": status, "response": credit, "modelCalls": 0})
    raise SystemExit("OpenRouter balance verification failed; no model request made")
data = credit["data"]
remaining = float(data["total_credits"]) - float(data["total_usage"])
save("balance.json", {"protocol": "openrouter-usd-balance-readonly-v1", "currency": "USD",
    "observedAtUtc": now(), "remainingUsd": remaining, "httpStatus": status,
    "modelCalls": 0, "credentialPrinted": False})
CAP_USD = 0.05
if remaining < CAP_USD:
    raise SystemExit("Less than USD 0.05 available; no model request made")
rows = []
exposure = 0.0
tool = {"type": "function", "function": {"name": "submit", "description": "Submit the numeric answer",
    "parameters": {"type": "object", "properties": {"answer": {"type": "string"}},
    "required": ["answer"], "additionalProperties": False}}}
MODEL = "deepseek/deepseek-v4.1-flash"
def call(label, thinking, forced, messages):
    global exposure
    body = {"model": MODEL, "provider": {"only": ["deepseek"], "allow_fallbacks": False,
        "max_price": {"prompt": 0.3, "completion": 1.2}},
        "reasoning": {"enabled": thinking, "effort": "high" if thinking else "none", "exclude": False},
        "temperature": 0, "max_tokens": 2048, "stream": False,
        "messages": messages, "tools": [tool],
        "tool_choice": {"type": "function", "function": {"name": "submit"}} if forced else "auto"}
    raw = json.dumps(body).encode("utf-8")
    reservation = ((len(raw) + 2048 + len(messages)*256)*0.3 + 2048*1.2)/1e6
    if exposure + reservation > CAP_USD:
        raise RuntimeError("USD probe envelope exhausted")
    start = {"label": label, "currency": "USD", "reservationUsd": reservation,
        "request": save(label + "-request.json", body), "startedAt": now()}
    save(label + "-start.json", start)
    exposure += reservation
    try:
        status, response = request("chat/completions", body)
    except Exception as error:
        rows.append({**start, "fault": type(error).__name__, "costBasis": "unknown_reservation"})
        save("result.json", {"rows": rows, "exposureUpperBoundUsd": exposure, "capUsd": CAP_USD,
            "modelCalls": len(rows), "complete": False})
        raise SystemExit("Provider transport failed; reservation retained, no retry")
    usage = response.get("usage", {})
    cost = usage.get("cost")
    if isinstance(cost, (float, int)) and cost >= 0:
        exposure += float(cost) - reservation
        basis = "provider_reported_usd"
    elif status in [400, 401, 402, 403, 404, 422] and not usage:
        exposure -= reservation
        cost, basis = 0, "confirmed_pre_generation_rejection"
    else:
        basis = "unknown_reservation"
    generation = None
    if status == 200 and response.get("id"):
        gs, value = request("generation?id=" + response["id"])
        generation = save(label + "-generation.json", {"httpStatus": gs, "response": value})
    row = {**start, "finishedAt": now(), "httpStatus": status,
        "response": save(label + "-response.json", response), "generation": generation,
        "reportedProvider": response.get("provider"), "servedModel": response.get("model"),
        "billedCostUsd": cost, "costBasis": basis, "usage": usage,
        "toolNames": [c.get("function", {}).get("name") for c in response.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])],
        "reasoningReturned": bool(response.get("choices", [{}])[0].get("message", {}).get("reasoning")),
        "errorCode": response.get("error", {}).get("code")}
    rows.append(row)
    print(json.dumps({k: row.get(k) for k in ["label", "httpStatus", "reportedProvider", "toolNames", "reasoningReturned", "billedCostUsd", "errorCode"]}), flush=True)
    return response

messages = [{"role": "system", "content": "This is a protocol test. Call submit with the numeric answer. Do not answer only in text."},
    {"role": "user", "content": "What is 12 + 30? Submit the answer as a string using the submit tool."}]
call("native-forced-thinking", True, True, messages)
call("native-forced-no-thinking", False, True, messages)
auto = call("constrained-auto-thinking", True, False, messages)
message = auto.get("choices", [{}])[0].get("message", {})
if message.get("tool_calls"):
    calls = message["tool_calls"]
    history = messages + [{"role": "assistant", "content": message.get("content"),
        "tool_calls": calls, "reasoning_content": message.get("reasoning", "")},
        *[{"role": "tool", "tool_call_id": c["id"], "content": "Accepted answer 42."} for c in calls],
        {"role": "user", "content": "Submit the same checked numeric answer again using submit. This tests preservation of reasoning history."}]
    call("constrained-auto-thinking-history", True, False, history)
result = {"protocol": "openrouter-native-submit-probe-v1", "model": MODEL,
    "providerOnly": ["deepseek"], "currency": "USD", "capUsd": CAP_USD,
    "exposureUpperBoundUsd": exposure, "modelCalls": len(rows), "rows": rows,
    "complete": True, "credentialPrinted": False, "benchmarkStarted": False}
save("result.json", result)
print(json.dumps({"resultPath": str(HOME / "result.json"), "exposureUpperBoundUsd": exposure,
    "modelCalls": len(rows), "benchmarkStarted": False}), flush=True)
