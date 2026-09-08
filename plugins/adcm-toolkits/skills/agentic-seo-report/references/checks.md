# Check catalog

Every check names its source and its severity, and carries the command that reproduces it.
A check that cannot be reproduced from the command line does not belong here.

## External — is-agentic.com

Scored by them, reported by us **unmodified**. Free, no auth, `GET /api/v1/report?url=`,
rate limit 120/IP/min. Buckets: `essential` (80 pts), `recommended` (20, conditional on
detected capabilities), `bonus`. Checks that do not apply do not penalise.

⚠ **The API never starts a scan.** It returns the last completed report, which may be weeks
old. `--fresh` runs `npx is-agentic`. Always print `scanned_at`; a stale number presented as
current is the easiest way for this skill to lie.

⚠ Only failing and partial checks are itemised. The passing count is derivable
(`eligible_checks - issues`), the passing **names are not**. Report the count; do not invent
the names.

## Local — what is-agentic does not measure

| Check | Severity when failing | Why it matters |
|---|---|---|
| `llms-txt` | medium | Agents have no map of what the site is for. Also what fails their `agent-instruction`. |
| `markdown-negotiation` | medium | Agents ask for markdown. Serving HTML without `Vary: Accept` lets a CDN hand a cached HTML body to an agent that asked for markdown. |
| `robots-ai-crawlers` | info | Which AI crawlers are named at all. |
| `robots-ai-posture` | low | Access inherited from `User-agent: *` rather than decided. **A named block REPLACES the wildcard block** — it does not inherit — so private paths must be repeated inside every named block. This bites people. |
| `robots-crawl-delay` | low | Search engines often get an explicit `Crawl-delay: 0` while AI crawlers inherit a slower one. |
| `sitemap` | high if unreachable | Language alternates belong **inside** each `<url>` block; separate `<loc>` per language is not required and its absence is not a bug. |
| `ssr:<path>` | medium under ~1000 chars | Text visible with JS disabled — literally what an agent gets. |
| `hreflang:<path>` | high if not reciprocal | Every alternate must link back to the full set. One-way hreflang is ignored wholesale. |
| `jsonld-parse:<path>` | high | Invalid JSON-LD is silently dropped by every consumer. Dead weight that looks like coverage. |
| `jsonld-retired:<path>` | low | Uses a retired type — see `deprecated-schema.md`. |
| `jsonld-types:<path>` | info | Coverage inventory, so gaps are visible. |

## Control mutation — without this the report proves nothing

A report that comes out identical for two different sites is inventing. Before trusting a
clean run, prove the checks can go red:

```bash
# 1 · point it at a site that HAS llms.txt ⇒ the llms-txt finding must disappear
python3 scripts/audit_local.py https://vercel.com --json | grep -c llms-txt

# 2 · point it at a site with no hreflang ⇒ the hreflang check must vanish, not pass silently
python3 scripts/audit_local.py https://example.com

# 3 · break a rule on purpose: add a forbidden term to a finding and re-render
#     ⇒ render_report.py must EXIT 2 and refuse to write the file
```

A check that never fails is not a check. If a run comes back completely clean, suspect the
harness before congratulating the site.

## Deliberately not checked

- **Backlinks, keyword volume, competitor rankings.** They need paid APIs that ingest content
  (guardrail 3), and their numbers are estimates sold as facts.
- **A composite health score.** is-agentic's score is theirs and gets reported as theirs.
  Inventing a second number that blends heuristics would make the report feel more
  authoritative than it is.
- **Anything requiring credentials**, unless the owner explicitly enables the Search Console
  module.
