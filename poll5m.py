"""5-MINUTE POLLING EXPERIMENT — one page (`hsvufm`), a fresh Azure IP per run.

Questions (2026-09-23):
  1. Does the fetch success rate drop when polling every 5 min instead of 15?
     Baseline, 7 days at 15 min: worker `public` 97.6%, `public2` 96.0%.
  2. How many posts does 5-min polling catch that the 15-min pipeline never sees?
     A page returns only its single newest Story per fetch, so two posts inside
     one interval means the older one is lost.

RULE: fail = give up. httpx only, no retry, no Chromium, no shno1 fallback. A failure
is a data point: record one row and exit. The run stays green on purpose — a red run
every 5 min would flood the inbox with GitHub failure mails.

ISOLATED FROM PROD: never posts to the crawl webhook, never touches `fb_bai`, so no
user ever gets a message from this. Results go to a separate n8n webhook that writes
the n8n data table `poll5m_hsvufm`.

EXPIRES at EXPIRES_AT (lesson from the `cao_ab` A/B test: an experiment without an
end date quietly becomes infrastructure).
"""
from __future__ import annotations

import base64
import os
import re
import sys
import time
from datetime import datetime, timezone

import httpx

from cao import FetchError, fetch_httpx, mo_client

PAGE = "hsvufm"
EXPIRES_AT = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)   # 22:00 Vietnam time, 26 Sep


def newest_post(html: str) -> dict:
    """First Story on the page = newest post. Only the key (post_id) and the post time
    are needed — enough to join against the 15-min pipeline's `fb_bai` rows."""
    i = html.find('"__typename":"Story"')
    if i < 0:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
        title = (m.group(1).strip() if m else "").lower()
        # Page title present => FB changed the payload; bare "Facebook" => page gone.
        return {"status": "payload_changed" if title and title != "facebook" else "page_gone"}
    block = html[i:i + 400_000]
    out = {"status": "ok", "post_id": "", "creation_time": None}
    m = re.search(r'"id":"([A-Za-z0-9+/=]{20,})"', block[:2000])
    if m:
        try:
            # Story id = base64("S:_I<page_id>:<post_id>") — same key `fb_bai.sid` uses.
            decoded = base64.b64decode(m.group(1) + "==").decode("utf8", "ignore")
            k = re.match(r"S:_I(\d+):(\d+)", decoded)
            if k:
                out["post_id"] = k.group(2)
        except Exception:  # noqa: BLE001
            pass
    t = re.search(r'"creation_time":(\d{10})', block)
    if t:
        out["creation_time"] = int(t.group(1))
    return out


def main() -> int:
    started = datetime.now(timezone.utc)
    if started >= EXPIRES_AT:
        print(f"experiment expired ({EXPIRES_AT.isoformat()}) — not fetching.")
        return 0

    row = {"at": started.isoformat(), "dispatched_at": os.environ.get("DISPATCHED_AT", ""),
           "run_id": os.environ.get("GITHUB_RUN_ID", "local"), "ip": "",
           "status": "error", "error": "", "bytes": 0, "post_id": "", "creation_time": 0,
           "ms": 0}
    try:
        row["ip"] = httpx.get("https://api.ipify.org", timeout=10).text.strip()
    except Exception:  # noqa: BLE001
        pass

    t0 = time.monotonic()
    try:
        client = mo_client()
        html = fetch_httpx(client, PAGE)
        row["bytes"] = len(html)
        post = newest_post(html)
        row["status"] = post["status"]
        row["post_id"] = post.get("post_id") or ""
        row["creation_time"] = post.get("creation_time") or 0
    except FetchError as e:                       # fail = give up: record it, no retry
        row["status"] = "login_wall" if "login" in str(e) else "error"
        row["error"] = str(e)[:200]
    except Exception as e:  # noqa: BLE001
        row["error"] = f"{type(e).__name__}: {e}"[:200]
    row["ms"] = int((time.monotonic() - t0) * 1000)

    print(row)
    url, token = os.environ.get("POLL5M_URL"), os.environ.get("N8N_TOKEN")
    if not url or not token:
        print("POLL5M_URL/N8N_TOKEN missing — printed only, nothing recorded.", file=sys.stderr)
        return 0
    try:
        httpx.post(url, json=row, timeout=30,
                   headers={"X-Selenova-Token": token}).raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"recording to n8n failed: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
