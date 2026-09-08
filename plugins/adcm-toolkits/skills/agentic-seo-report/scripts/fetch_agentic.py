#!/usr/bin/env python3
"""Read (or trigger) an is-agentic.com agent-readiness report.

is-agentic.com scores what an AI agent can discover, fetch and use on a public site.
Free, no account, no key. Public read API, rate limit 120 req/IP/60s.

Two facts that shape this script:

  * The API NEVER starts a scan. `GET /api/v1/report` returns the last completed
    report, which can be weeks old. Callers who need today's state must pass
    --fresh, which shells out to `npx is-agentic`. We always surface scanned_at
    so a stale number is never mistaken for a current one.
  * Only failing and partial checks are itemised. The count of passing checks is
    known (eligible - issues) but their names are not exposed. We report the
    count and say the names are unavailable rather than guessing them.

Sends nothing but the URL being audited.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://is-agentic.com/api/v1/report"
TIMEOUT = 30


def fetch(url: str) -> dict:
    """GET the stored report. Returns {} when there is none yet."""
    q = urllib.parse.urlencode({"url": url})
    req = urllib.request.Request(f"{API}?{q}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        return {"_error": f"HTTP {e.code} from is-agentic", "_detail": e.reason}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return {"_error": "is-agentic unreachable", "_detail": str(e)}


def scan(url: str) -> dict:
    """Trigger a fresh scan via the CLI, then read the new report."""
    if not shutil.which("npx"):
        return {"_error": "npx not found; cannot run a fresh scan", "_detail": "install Node or drop --fresh"}
    try:
        proc = subprocess.run(
            ["npx", "--yes", "is-agentic", url],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return {"_error": "fresh scan timed out after 600s"}
    if proc.returncode != 0:
        return {"_error": f"is-agentic CLI exited {proc.returncode}", "_detail": (proc.stderr or "")[-500:]}
    return fetch(url)


def staleness(scanned_at: str | None) -> tuple[int | None, str]:
    """Age of the report in days, and a caller-facing note about it."""
    if not scanned_at:
        return None, "scan date unknown — treat every number as unverified"
    try:
        t = datetime.fromisoformat(scanned_at.replace("Z", "+00:00"))
    except ValueError:
        return None, f"unparseable scan date {scanned_at!r}"
    days = (datetime.now(timezone.utc) - t).days
    if days <= 1:
        return days, "current"
    if days <= 14:
        return days, f"{days} days old — fine unless the site changed since"
    return days, f"{days} days old — RE-SCAN with --fresh before acting on this"


def normalize(raw: dict) -> dict:
    """Flatten the API payload into what the report template consumes."""
    if not raw or "_error" in raw:
        return {"available": False, **{k: v for k, v in raw.items() if k.startswith("_")}}

    # The field is `score_breakdown`, and `bonus` has a different shape from the
    # other two buckets: additive points and a signal count, with no denominator.
    breakdown = raw.get("score_breakdown") or {}
    issues = raw.get("issues") or []
    eligible = raw.get("eligible_checks")
    days, note = staleness(raw.get("scanned_at"))

    passing = None
    if isinstance(eligible, int):
        passing = eligible - len(issues)

    buckets = {}
    for name, b in breakdown.items():
        has_denominator = "available" in b
        buckets[name] = {
            "earned": b.get("earned") if has_denominator else b.get("points"),
            "available": b.get("available"),
            "passing": b.get("passing") if has_denominator else b.get("positive_signals"),
            "total": b.get("total"),
        }

    return {
        "available": True,
        "score": raw.get("score"),
        "label": raw.get("score_label"),
        "scanned_at": raw.get("scanned_at"),
        "age_days": days,
        "staleness_note": note,
        "eligible_checks": eligible,
        # Names of passing checks are not exposed by the API. Report the count only.
        "passing_count": passing,
        "buckets": buckets,
        "issues": [
            {
                "id": i.get("id"),
                "title": i.get("title"),
                "tier": i.get("tier"),
                "result": i.get("result"),
                "details": i.get("details"),
                "recommendation": i.get("recommendation"),
            }
            for i in issues
        ],
        "report_url": raw.get("report_url"),
        "target": raw.get("target") or raw.get("display_target"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch an is-agentic agent-readiness report.")
    ap.add_argument("url", help="site to audit, e.g. https://example.com")
    ap.add_argument("--fresh", action="store_true", help="trigger a new scan instead of reading the stored one")
    ap.add_argument("--json", action="store_true", help="print normalized JSON (default: human summary)")
    args = ap.parse_args()

    raw = scan(args.url) if args.fresh else fetch(args.url)
    data = normalize(raw)

    if args.json:
        print(json.dumps({"normalized": data, "raw": raw}, indent=2, ensure_ascii=False))
        return 0 if data.get("available") else 1

    if not data.get("available"):
        err = data.get("_error", "no stored report for this URL")
        print(f"is-agentic: {err}")
        if data.get("_detail"):
            print(f"  detail: {data['_detail']}")
        print("  → the local audit still runs; the report will say this section is unavailable")
        return 1

    print(f"is-agentic score: {data['score']} — {data['label']}")
    print(f"  scanned {data['scanned_at']}  ({data['staleness_note']})")
    for name, b in data["buckets"].items():
        got = f"{b['earned']}/{b['available']}" if b["available"] is not None else f"+{b['earned']}"
        checks = f"  ({b['passing']}/{b['total']} checks)" if b["total"] else (
            f"  ({b['passing']} signals)" if b["passing"] is not None else "")
        print(f"  {name:12} {got}{checks}")
    if data["passing_count"] is not None:
        print(f"  {data['passing_count']} of {data['eligible_checks']} checks pass "
              f"(their names are not exposed by the API)")
    for i in data["issues"]:
        print(f"  [{i['result']:7}] {i['id']} ({i['tier']})")
        if i.get("details"):
            print(f"            {i['details']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
