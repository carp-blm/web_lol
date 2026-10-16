"""Refresh only approved public source URLs; never bypass login, CAPTCHA or quotas.

On failure the existing compact seed and generated JSON remain intact.
"""
import argparse
import csv
import io
import sys
import urllib.error
import urllib.parse
import urllib.request
from build_data import ROOT, FIELDS, read_json, write_json

ALLOWED_HOSTS = {"drive.google.com", "drive.usercontent.google.com", "oracleselixir.com",
                 "oracleselixir-downloadable-match-data.s3-us-west-2.amazonaws.com"}
MAX_BYTES = 220_000_000


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("Only configured public provider HTTPS hosts are allowed")


def validate_csv(content):
    if content.lstrip().startswith((b"<", b"{")):
        raise ValueError("Provider returned HTML/JSON instead of CSV (quota/login/error). No bypass attempted.")
    text = content.decode("utf-8-sig")
    rows = csv.DictReader(io.StringIO(text))
    if not set(FIELDS[:11]).issubset(rows.fieldnames or []):
        raise ValueError("Provider CSV schema changed")
    if sum(1 for _ in rows) < 100:
        raise ValueError("Provider returned incomplete CSV")


def refresh():
    sources = read_json(ROOT / "data/sources.json")
    out = ROOT / "data/raw"
    out.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for year, source in sources["years"].items():
            if not source.get("automatic_fetch"):
                raise ValueError(f"Automatic access disabled for {year}")
            validate_url(source["url"])
            req = urllib.request.Request(source["url"], headers={"User-Agent": "NexusArchivePrototype/0.1"})
            with urllib.request.build_opener(SafeRedirect()).open(req, timeout=60) as response:
                content = response.read(MAX_BYTES+1)
            if len(content) > MAX_BYTES:
                raise ValueError("CSV exceeded configured size limit")
            validate_csv(content)
            tmp = out / f"{year}.download"
            tmp.write_bytes(content)
            staged.append((tmp, out / f"{year}.csv"))
        for tmp, dest in staged:
            tmp.replace(dest)
        # Record actual successful primary sources, never claim mirror provenance for new downloads.
        for source in sources["years"].values():
            source["snapshot_url"] = source["url"]
            source["source_kind"] = "provider-download"
        sources["notes"] = "Refreshed from configured public provider downloads; redistribution permission still requires review."
        write_json(ROOT / "data/sources.json", sources)
        print(f"Fetched {len(staged)} yearly CSV files")
    except Exception:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    try:
        refresh()
    except Exception as exc:
        print(f"Refresh failed; retain last known good snapshot: {exc}", file=sys.stderr)
        raise SystemExit(1)
