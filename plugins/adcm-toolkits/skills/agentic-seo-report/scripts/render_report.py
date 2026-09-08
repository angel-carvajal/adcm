#!/usr/bin/env python3
"""Render the actionable report and keep the history that makes comparison possible.

Two rules this file exists to enforce:

  * A single run is a snapshot, not evidence of improvement. Only a diff against
    the previous run shows whether anything got better, so every run is stored
    and --compare is cheap.
  * The report must not leak what the audited project marked confidential. The
    guardrail scan below runs over the FINISHED report, because a skill that
    promises to protect a secret and then prints it in its own output is worse
    than one that never promised.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import date, datetime, timezone

SEV_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}
SEV_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡", "info": "·"}


def load_rules(path: str | None) -> dict:
    """Project hard rules. Absent is allowed — but the report says so."""
    if not path:
        return {}
    p = pathlib.Path(path)
    if not p.exists():
        return {"_missing": str(p)}
    text = p.read_text()
    rules: dict = {"forbidden_terms": [], "never_recommend": [], "name": None}
    # Deliberately a tiny parser: no YAML dependency for a 10-line config.
    section = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.endswith(":") and not s.startswith("-"):
            section = s[:-1].strip()
            continue
        if s.startswith("- ") and section in ("forbidden_terms", "never_recommend"):
            rules[section].append(s[2:].strip().strip("\"'"))
        elif ":" in s and not s.startswith("-"):
            k, _, v = s.partition(":")
            rules[k.strip()] = v.strip().strip("\"'")
    return rules


def guardrail_scan(report: str, rules: dict) -> list[str]:
    """Does our own output leak a term the project declared confidential?"""
    hits = []
    for term in rules.get("forbidden_terms", []):
        if not term:
            continue
        for m in re.finditer(re.escape(term), report, re.IGNORECASE):
            line = report[:m.start()].count("\n") + 1
            hits.append(f"line {line}: {term!r}")
    return hits


def history_dir(out: pathlib.Path) -> pathlib.Path:
    d = out / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def previous(out: pathlib.Path) -> dict | None:
    runs = sorted(history_dir(out).glob("*.json"))
    if not runs:
        return None
    return json.loads(runs[-1].read_text())


def render(url: str, agentic: dict, findings: list[dict], rules: dict, prev: dict | None) -> str:
    failed = [f for f in findings if not f["passed"]]
    passed = [f for f in findings if f["passed"]]
    failed.sort(key=lambda f: SEV_RANK.get(f["severity"], 9))

    L: list[str] = []
    L.append(f"# Agentic SEO report — {url}")
    L.append("")
    L.append(f"Generated {date.today().isoformat()} · {len(failed)} finding(s) · "
             f"{len(passed)} check(s) passed")
    if rules.get("name"):
        L.append(f"Project rules: **{rules['name']}** "
                 f"({len(rules.get('forbidden_terms', []))} confidential term(s) enforced)")
    elif rules.get("_missing"):
        L.append(f"⚠ Rules file not found at `{rules['_missing']}` — ran with generic guardrails only.")
    else:
        L.append("⚠ No project rules supplied — generic guardrails only. "
                 "Recommendations below have **not** been checked against confidentiality rules.")
    L.append("")

    # ---- agent readiness
    L.append("## Agent readiness (is-agentic.com)")
    L.append("")
    if not agentic.get("available"):
        L.append(f"Unavailable: {agentic.get('_error', 'no stored report')}. "
                 "The local audit below still stands on its own.")
    else:
        L.append(f"**{agentic['score']}/100 — {agentic['label']}**  ")
        L.append(f"Scanned `{agentic['scanned_at']}` — {agentic['staleness_note']}")
        L.append("")
        L.append("| Bucket | Points | Checks passing |")
        L.append("|---|---|---|")
        for name, b in agentic["buckets"].items():
            # `bonus` is additive and has no denominator; the others do.
            pts = f"{b['earned']}/{b['available']}" if b.get("available") is not None else f"+{b['earned']}"
            chk = (f"{b['passing']}/{b['total']}" if b.get("total")
                   else (f"{b['passing']} signals" if b.get("passing") is not None else "—"))
            L.append(f"| {name} | {pts} | {chk} |")
        L.append("")
        if agentic.get("passing_count") is not None:
            L.append(f"{agentic['passing_count']} of {agentic['eligible_checks']} checks pass. "
                     "The API does not expose which ones, so they are not listed here.")
            L.append("")
        if agentic["issues"]:
            L.append("| Check | Tier | Result | Detail |")
            L.append("|---|---|---|---|")
            for i in agentic["issues"]:
                d = (i.get("details") or "").replace("|", "\\|")
                L.append(f"| `{i['id']}` | {i['tier']} | {i['result']} | {d} |")
            L.append("")
        if prev and prev.get("agentic", {}).get("score") is not None:
            delta = (agentic.get("score") or 0) - prev["agentic"]["score"]
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "=")
            L.append(f"Versus previous run: **{arrow} {delta:+d}** "
                     f"(was {prev['agentic']['score']} on {prev.get('run_at', '?')[:10]})")
            L.append("")

    # ---- findings
    L.append("## Findings, ordered by traffic impact")
    L.append("")
    if not failed:
        L.append("Nothing failed. Re-read the *not verified* section before celebrating.")
    for f in failed:
        L.append(f"### {SEV_ICON.get(f['severity'], '·')} {f['summary']}")
        L.append("")
        L.append(f"- **Check** `{f['check']}` · severity **{f['severity']}**"
                 + (f" · tags: {', '.join(f['tags'])}" if f.get("tags") else ""))
        if f.get("where"):
            L.append(f"- **Where** {f['where']}")
        if f.get("detail"):
            L.append(f"- **What happens** {f['detail']}")
        if f.get("fix"):
            L.append(f"- **Fix** {f['fix']}")
        if f.get("command"):
            L.append(f"- **Proves it** `{f['command']}`")
        L.append("")

    # ---- what passed
    L.append("## Checked and passing")
    L.append("")
    L.append("Listed so the next run can tell a genuine regression from a new check.")
    L.append("")
    for f in passed:
        L.append(f"- `{f['check']}` — {f['summary']}")
    L.append("")

    # ---- honesty
    L.append("## Not verified")
    L.append("")
    L.append("- Search Console data (queries, impressions, positions 11–20) — needs the owner's "
             "OAuth and is off by default.")
    L.append("- Anything behind authentication, and any page not in the audited path list.")
    L.append("- Whether a finding actually moves traffic: this report measures the site, "
             "not the market. Ranking effects are never guaranteed by markup.")
    if agentic.get("available") and (agentic.get("age_days") or 0) > 14:
        L.append(f"- The is-agentic score is {agentic['age_days']} days old. Re-run with `--fresh`.")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the agentic SEO report.")
    ap.add_argument("url")
    ap.add_argument("--agentic", required=True, help="JSON from fetch_agentic.py --json")
    ap.add_argument("--findings", required=True, help="JSON from audit_local.py --json")
    ap.add_argument("--rules", help="project rules file")
    ap.add_argument("--out", default="seo-reports")
    args = ap.parse_args()

    agentic = json.loads(pathlib.Path(args.agentic).read_text())
    agentic = agentic.get("normalized", agentic)
    findings = json.loads(pathlib.Path(args.findings).read_text())
    rules = load_rules(args.rules)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    prev = previous(out)

    report = render(args.url, agentic, findings, rules, prev)

    leaks = guardrail_scan(report, rules)
    if leaks:
        print("GUARDRAIL FAILURE — the report itself contains confidential terms:", file=sys.stderr)
        for h in leaks:
            print(f"  {h}", file=sys.stderr)
        print("Report NOT written. Fix the finding text before publishing.", file=sys.stderr)
        return 2

    path = out / f"{date.today().isoformat()}-agentic-report.md"
    path.write_text(report)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (history_dir(out) / f"{stamp}.json").write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "url": args.url,
        "agentic": {"score": agentic.get("score"), "scanned_at": agentic.get("scanned_at")},
        "failed": [f["check"] for f in findings if not f["passed"]],
    }, indent=2))

    print(f"report: {path}")
    print(f"history: {history_dir(out)}/{stamp}.json")
    if rules.get("forbidden_terms"):
        print(f"guardrail scan: 0 leaks over {len(rules['forbidden_terms'])} confidential term(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
