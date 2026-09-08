# agentic-seo-report

Audits a live site for how well **search engines and AI agents** can find, read and use it,
then writes a report where every finding carries the command that proves it.

## Why this exists

Generic SEO tooling optimizes for the ten blue links and assumes you have nothing to hide.
Point it at a business with confidential pricing and it will cheerfully recommend publishing
`Offer` schema with the exact figure and a page explaining how the product is manufactured.
That is not an optimization, it is a leak in a machine-readable format.

This skill combines:

- **is-agentic.com** — free, no auth, public API. Scores what an AI agent can discover, fetch
  and use. Reported unmodified, with its scan date, because a three-week-old number presented
  as current is the easiest way for a report to lie.
- **A local audit** of what is-agentic does not measure: `llms.txt`, hreflang reciprocity and
  content parity, JSON-LD validity and retired types, schema coverage, sitemap health,
  AI-crawler posture in `robots.txt`, and text visible with JavaScript off.
- **Project hard rules** — an optional file declaring what must never be published. It filters
  the recommendations *and* the report's own output.

## Usage

```
/agentic-seo-report <url> [--fresh] [--rules <path>] [--out <dir>] [--compare]
```

Or the scripts directly:

```bash
python3 scripts/fetch_agentic.py https://example.com --json > /tmp/agentic.json
python3 scripts/audit_local.py   https://example.com --paths "/,/pricing" --json > /tmp/local.json
python3 scripts/render_report.py https://example.com \
        --agentic /tmp/agentic.json --findings /tmp/local.json \
        --rules templates/project-rules.example.yml --out ./seo-reports
```

Nothing is uploaded. is-agentic receives a public URL; every other fetch goes straight from
this machine to the site being audited.

## What it will not do

Backlink and keyword metrics (paid APIs that ingest content, selling estimates as facts),
a composite health score of its own invention, and anything needing credentials unless the
owner explicitly turns on the Search Console module. See `references/guardrails.md`.

## Prior art

The bilingual audit approach and the retired-schema list are adapted from
[`claude-seo`](https://github.com/AgriciDaniel/claude-seo) (MIT) — read, re-verified and
narrowed, not vendored. That project is a genuinely well-maintained toolkit aimed at SEO
agencies; this skill is aimed at a single site whose owner has rules to respect.

The Search Console idea — *list every page ranking 11–20 and what it needs* — comes from the
same place and is the cheapest traffic in any audit. It ships written and switched off.
