"""GET the project's actual DeepSeek balance; never call a model or print keys."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[3]


def main():
    text = (ROOT / ".env").read_text(encoding="utf-8-sig")
    match = re.search(r"(?m)^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.*?)\s*$", text)
    if not match:
        raise RuntimeError("Project DeepSeek credential unavailable")
    key = match.group(1).strip()
    if key[:1] in {"'", '"'} and key[-1:] == key[:1]:
        key = key[1:-1]
    if not key or "\n" in key:
        raise RuntimeError("Project DeepSeek credential invalid")
    nonce = uuid.uuid4().hex
    output = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/cash-observations" / nonce
    output.mkdir(parents=True, exist_ok=False)
    report = {"protocol": "deepseek-resource-readonly-v1", "provider": "https://api.deepseek.com", "endpoint": "/user/balance", "method": "GET", "officialDocumentation": "https://api-docs.deepseek.com/api/get-user-balance/", "modelCalls": 0, "credentialPrinted": False, "sourceScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "scope": "TB12 actual current resource observation; no historical missing receipt settlement"}
    request = urllib.request.Request("https://api.deepseek.com/user/balance", headers={"Authorization": "Bearer " + key}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024 or key.encode() in raw:
                raise RuntimeError("Provider balance response capture boundary")
            data = json.loads(raw)
            report.update({"httpStatus": response.status, "isAvailable": data["is_available"], "balances": data["balance_infos"]})
            for row in report["balances"]:
                for name in ("total_balance", "granted_balance", "topped_up_balance"):
                    if not re.fullmatch(r"\d+(?:\.\d{1,9})?", row[name]):
                        raise RuntimeError("Invalid provider balance decimal")
                if Decimal(row["granted_balance"]) + Decimal(row["topped_up_balance"]) != Decimal(row["total_balance"]):
                    raise RuntimeError("Provider balance components mismatch")
            body = output / "provider-balance-response.json"
            body.write_bytes(raw)
            report["rawResponse"] = {"path": str(body), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    except urllib.error.HTTPError as error:
        report.update({"httpStatus": error.code, "isAvailable": False, "failureType": "HTTPError"})
    except BaseException as error:
        report.update({"isAvailable": False, "failureType": type(error).__name__})
    report["observedAtUtc"] = datetime.now(timezone.utc).isoformat()
    path = output / "balance.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path), "httpStatus": report.get("httpStatus"), "isAvailable": report["isAvailable"], "balances": report.get("balances", []), "modelCalls": 0, "credentialPrinted": False}))


if __name__ == "__main__":
    main()
