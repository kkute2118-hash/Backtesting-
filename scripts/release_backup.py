#!/usr/bin/env python3
"""Upload the staged database backup to the GitHub Release tagged DB_RELEASE_TAG.

The second copy of the backup (the first is the file on the db-backup branch,
written by push_backup.sh, which calls this). A release asset may be up to 2 GB
where a file on a branch may be 100 MB, so this copy keeps working if the
database outgrows the branch; core.restore_db_from_github falls back to it.

Uploads two assets: market_data.sqlite3.gz (always the newest, the one restore
reads) and market_data-YYYY-MM-DD.sqlite3.gz (one per day, the newest
KEEP_DAILY kept). Standard library only. Exits non-zero on failure; the caller
decides whether that fails the run.

Environment: BACKUP_STAGE_PATH, GITHUB_REPOSITORY, GH_PUSH_TOKEN, DB_RELEASE_TAG.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

LATEST = "market_data.sqlite3.gz"
DAILY = re.compile(r"^market_data-(\d{4}-\d{2}-\d{2})\.sqlite3\.gz$")
KEEP_DAILY = 7
API = "https://api.github.com"


def call(method, url, token, data=None, content_type="application/json"):
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": content_type,
    })
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            body = r.read()
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]


def main() -> int:
    stage = os.environ["BACKUP_STAGE_PATH"]
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_PUSH_TOKEN"]
    tag = os.environ.get("DB_RELEASE_TAG", "db-backup")

    status, rel = call("GET", f"{API}/repos/{repo}/releases/tags/{tag}", token)
    if status == 404:
        status, rel = call("POST", f"{API}/repos/{repo}/releases", token, json.dumps({
            "tag_name": tag, "target_commitish": "main", "name": "Database backup",
            "prerelease": True,
            "body": "Automatic copy of the database backup, written by the scheduled jobs "
                    "(scripts/release_backup.py). market_data.sqlite3.gz is the newest; the "
                    "dated files are the last 7 days. Not a software release.",
        }).encode())
    if status not in (200, 201):
        print(f"::warning title=Release backup skipped::could not open release {tag}: {status} {rel}")
        return 1

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    names = [LATEST, f"market_data-{today}.sqlite3.gz"]
    assets = {a["name"]: a["id"] for a in rel.get("assets", [])}
    upload = rel["upload_url"].split("{")[0]
    with open(stage, "rb") as f:
        payload = f.read()
    for name in names:
        if name in assets:
            call("DELETE", f"{API}/repos/{repo}/releases/assets/{assets[name]}", token)
        status, out = call("POST", f"{upload}?name={urllib.parse.quote(name)}", token,
                           payload, "application/gzip")
        if status != 201 or not out or out.get("size") != len(payload):
            print(f"::warning title=Release backup failed::{name}: {status} {str(out)[:200]}")
            return 1
    daily = sorted((m.group(1), name) for name in assets if (m := DAILY.match(name)))
    daily = sorted(set(daily) | {(today, names[1])})
    for _, name in daily[:-KEEP_DAILY]:
        if name in assets:
            call("DELETE", f"{API}/repos/{repo}/releases/assets/{assets[name]}", token)
    print(f"Release backup: {len(payload) / 1048576:.1f} MB to {repo} release {tag} "
          f"as {LATEST} and {names[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
