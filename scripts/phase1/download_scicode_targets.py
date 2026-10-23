"""Stream the original publisher's large public HDF5 file without inline bytes."""
from __future__ import annotations
import hashlib
from html.parser import HTMLParser
import http.cookiejar
import json
import re
from pathlib import Path
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / ".phase1-data/scicode/test_data.h5"
EXPECTED_BYTES = 1049345865
FILE_ID = "17G_k65N_6yFFZ2O-jQH00Lh6iaw3z-AW"
URL = f"https://drive.usercontent.google.com/download?id={FILE_ID}&export=download&confirm=t"

class ConfirmationForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}
        self.active = False
    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "form" and fields.get("id") == "download-form":
            self.active = True
            self.action = fields.get("action")
        if self.active and tag == "input" and fields.get("name"):
            self.fields[fields["name"]] = fields.get("value", "")
    def handle_endtag(self, tag):
        if tag == "form":
            self.active = False

def open_download():
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    response = opener.open(urllib.request.Request(URL, headers={"User-Agent": "ObjRun-phase1"}), timeout=60)
    if "text/html" not in response.headers.get("Content-Type", ""):
        return response
    form = ConfirmationForm()
    page = response.read(256 * 1024).decode("utf-8")
    form.feed(page)
    response.close()
    if form.action != "https://drive.usercontent.google.com/download" or form.fields.get("id") != FILE_ID:
        print(json.dumps({"confirmationTitle": re.findall(r"<title>(.*?)</title>", page), "formAction": form.action, "fieldNames": sorted(form.fields), "forms": re.findall(r"<form[^>]*>", page)}), flush=True)
        raise RuntimeError("The publisher's public file has no recognized Google download confirmation form.")
    query = urllib.parse.urlencode(form.fields)
    response = opener.open(urllib.request.Request(form.action + "?" + query, headers={"User-Agent": "ObjRun-phase1"}), timeout=60)
    return response

if TARGET.exists() and TARGET.stat().st_size == EXPECTED_BYTES:
    print(json.dumps({"status": "already_downloaded", "bytes": EXPECTED_BYTES}), flush=True)
else:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix(".h5.part")
    digest = hashlib.sha256()
    count = 0
    with open_download() as response:
        if "text/html" in response.headers.get("Content-Type", ""):
            raise RuntimeError("The public download requires a confirmation/access step; no dataset bytes were downloaded.")
        with temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                if count == 0 and not chunk.startswith(b"\x89HDF\r\n\x1a\n"):
                    raise RuntimeError("The public link did not return an HDF5 file.")
                output.write(chunk)
                digest.update(chunk)
                count += len(chunk)
                if count % (64 * 1024 * 1024) == 0:
                    print(json.dumps({"downloadedBytes": count, "expectedBytes": EXPECTED_BYTES}), flush=True)
    if count != EXPECTED_BYTES:
        raise RuntimeError(f"Dataset size mismatch: {count} != {EXPECTED_BYTES}")
    temporary.replace(TARGET)
    record = {"source": f"https://drive.google.com/file/d/{FILE_ID}/view", "bytes": count, "sha256": digest.hexdigest()}
    TARGET.with_suffix(".source.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "downloaded", **record}), flush=True)
