"""Deterministic transport fault controls; no network, E writes or model calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
import ssl
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/benchmark-repair/minif2f_public_cache.py"
spec = importlib.util.spec_from_file_location("public_cache_retry_controls", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
request = urllib.request.Request(module.AZURE + "0000000000000001.ltar", method="GET")


class Sequence:
    def __init__(self, events):
        self.events = iter(events)
        self.calls = []

    def open(self, given_request, timeout):
        assert given_request is request and timeout == 60
        self.calls.append(given_request)
        event = next(self.events)
        if isinstance(event, Exception):
            raise event
        return event


def failure(events, count, response_received=False):
    opener, backoffs = Sequence(events), []
    try:
        module.open_public_response(opener, request, lambda: None, backoffs.append)
        raise AssertionError("a permanent/exhausted opening fault was accepted")
    except module.PublicOpenFailure as error:
        assert len(opener.calls) == count == len(error.transport_attempts)
        assert error.transport_attempts[-1]["response_received"] is response_received
        return backoffs


def main():
    good = object()
    backoffs = []
    opener = Sequence([urllib.error.URLError(TimeoutError()), good])
    response, attempts = module.open_public_response(opener, request, lambda: None, backoffs.append)
    assert response is good and len(opener.calls) == 2 and backoffs == [0.5]
    assert attempts[0]["retryable"] is True and attempts[0]["response_received"] is False
    assert attempts[1]["response_received"] is True
    timeout = OSError("controlled Windows connection timeout")
    timeout.winerror = 10060
    opener = Sequence([urllib.error.URLError(timeout), good])
    _, windows_attempts = module.open_public_response(opener, request, lambda: None, lambda _: None)
    assert len(opener.calls) == 2 and windows_attempts[0]["winerror"] == 10060
    assert failure([urllib.error.URLError(TimeoutError()) for _ in range(3)], 3) == [0.5, 2.0]
    for status in [403, 404]:
        assert failure([urllib.error.HTTPError(request.full_url, status, "controlled", {}, None)], 1, True) == []
    assert failure([urllib.error.URLError(ssl.SSLCertVerificationError("controlled"))], 1) == []
    assert failure([RuntimeError("official redirect rejected")], 1) == []
    assert failure([ValueError("invalid endpoint or request")], 1) == []
    stopped = False
    def guard():
        if stopped:
            raise RuntimeError("controlled stop")
    def pause(_):
        nonlocal stopped
        stopped = True
    opener = Sequence([urllib.error.URLError(TimeoutError()), good])
    try:
        module.open_public_response(opener, request, guard, pause)
        raise AssertionError("stop during backoff admitted a new opening request")
    except RuntimeError as error:
        assert str(error) == "controlled stop" and len(opener.calls) == 1
    report = {"sourceSha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "controlsPassed": [
        "transient timeout then same Request success", "actual Win10060 reason shape then same Request success",
        "three opening attempts finite with fixed backoff", "HTTP403 single attempt", "HTTP404 single attempt",
        "TLS verification failure single attempt", "redirect rejection single attempt",
        "invalid request single attempt", "stop during backoff blocks further request"],
        "eWrite": False, "network": False, "modelCalls": 0,
        "limits": "These are controlled transport faults. Actual first public acquisition Win10060 failure is separately preserved; no claim of a completed real retry yet."}
    target = ROOT / "docs/repair-2026-10-08/minif2f-public-cache-retry-controls.json"
    if target.exists():
        raise RuntimeError("preserve existing controls evidence")
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"controlsPassed": len(report["controlsPassed"]), "network": False, "eWrite": False,
                      "modelCalls": 0, "sourceSha256": report["sourceSha256"]}))


if __name__ == "__main__":
    main()
