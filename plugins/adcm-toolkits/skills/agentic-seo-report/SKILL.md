---
name: agentic-seo-report
description: >
  Audits a live website for how well SEARCH ENGINES and AI AGENTS can find, read and use it,
  then writes an actionable report ranked by traffic impact — every finding carrying the file
  to touch and the command that proves it. Combines the free is-agentic.com agent-readiness
  score (public API, no auth) with local checks it does not perform: llms.txt, hreflang
  reciprocity and content parity, JSON-LD validity and deprecated types, schema coverage,
  sitemap vs. real routes, AI-crawler posture in robots.txt, and text visible without JS.
  Honors per-project hard rules (confidential pricing, topics that must never be published)
  through an optional project-rules file. Triggers when the user says 'audita el SEO',
  'seo report', 'agentic seo', 'is-agentic', 'agent readiness', 'AEO', 'GEO', 'por qué no
  llega tráfico', 'how do AI agents see my site', or asks to score/audit a site for AI agents.
---

# Agentic SEO Report

Most SEO tooling optimizes for the ten blue links. Most "AI-readiness" tooling ignores classic
search. This skill does both, and — more importantly — **refuses to recommend anything that
would break the project's own rules**. A generic SEO tool will happily tell a manufacturer to
publish `Offer` schema with exact prices and an "our process" page. For some businesses that
advice is a leak, not an optimization.

Three ideas hold this together:

- **SEO** = search engines · **AEO** = answer engines · **GEO** = generative engines. Same
  site, three audiences, overlapping but not identical requirements.
- **Every finding must be reproducible.** A finding without a command is an opinion.
- **A report that comes out identical for two different sites is inventing.** See the control
  mutation in `references/checks.md`.

## Run it

```
/agentic-seo-report <url> [--fresh] [--rules <path>] [--out <dir>] [--compare]
```

- `--fresh` triggers a new is-agentic scan (`npx is-agentic`) instead of reading the last
  stored report. **The public API never starts a scan** — without this flag you may be reading
  a result from weeks ago. Always print the scan date.
- `--rules` points to a project-rules file (see `templates/project-rules.example.yml`). Without
  it the skill runs with generic guardrails only and **says so in the report header**.
- `--compare` diffs against the previous run in `<out>/history/` — the only thing that proves
  a change actually helped.

**Hard rule: the main session is a pure orchestrator.** `fetch_agentic.py` and `audit_local.py` are run by an `adcm-toolkits:executor` that returns the JSON paths and a short summary. The report is drafted by an `adcm-toolkits:executor` with those JSON files as input (`render_report.py` plus the ranked findings). The main session reads `project-rules`, audits every recommendation against `references/guardrails.md` and delivers the report. Every delegated call is an `adcm-toolkits:*` type (which fixes the `model`) or names its `model` (no plugin in this session → `Agent(subagent_type: "general-purpose", model: "<tier>")` with the same brief); RETURNs are short and structured, never whole files. Escape hatch, in the user's own words: `sin tanto lío` (direct mode for that one task) or `modo directo` (stays on until `modo orquestador`). Canonical rule: `../execution-prompt-architect/references/orchestrator-rule.md`.

## The four phases

**1 · Agent readiness (external).** `scripts/fetch_agentic.py` reads
`https://is-agentic.com/api/v1/report?url=<url>` — free, no auth, rate limit 120/min. Returns
score, per-bucket breakdown and the issue list. Store the raw JSON in `<out>/history/`.
Their scoring is theirs: report it as *their* score, never re-weight it and never blend it into
a composite of your own.

**2 · Local audit (what is-agentic does not measure).** `scripts/audit_local.py`, all of it from
the public site — no credentials, nothing uploaded. Details in `references/checks.md`:
`llms.txt` · hreflang reciprocity and ES/EN content parity · canonical sanity · JSON-LD parses
and uses no retired types (`references/deprecated-schema.md`) · schema coverage for the page's
job · sitemap vs. the routes that actually answer 200 · which AI crawlers `robots.txt` allows,
blocks, or slows · **text visible with JavaScript disabled**, which is what an agent gets.

**3 · Traffic opportunities.** Pages with the most surface and the least content; language
parity gaps; thin or missing local pages. **Phase 2, written but OFF by default:** the Search
Console module — *every page ranking 11–20 and what it needs* — the cheapest traffic there is.
It needs the owner's OAuth, so it stays behind `--gsc` and never blocks a run.

**4 · The report.** `scripts/render_report.py` renders `templates/report.md.tmpl`: findings
ordered by traffic impact, each with severity, the file to touch, the fix, and **the command
that proves it today and will prove it fixed tomorrow**. Then the honest part — what was
checked and passed, and what could not be verified.

## Guardrails — read `references/guardrails.md` before writing any recommendation

Non-negotiable, and the reason this skill exists instead of a generic one:

1. **Never recommend publishing a value the project marked confidential.** If rules declare
   pricing internal, propose `Offer` with `priceRange` or an aggregate band — never the exact
   figure. Same for costs, margins, suppliers, manufacturing origin.
2. **Never recommend "process disclosure" content** (how it's made, where, by whom) without
   checking the rules first. It is standard E-E-A-T advice and it is exactly what leaks.
3. **Never send site content to a third party.** is-agentic receives a public URL and nothing
   else. No crawl-as-a-service, no keyword APIs that ingest pages. Fetching is direct from the
   site being audited.
4. **Be honest about heuristics.** Do not invent a composite "SEO Health Score" and present it
   as a Google signal. Cite the source of a check or label it a heuristic. Google has confirmed
   that word count and readability scores are not direct ranking factors — do not imply
   otherwise.
5. **Report what you could not verify.** A gap you declare is worth more than a green you
   assumed.

## Output

`<out>/<YYYY-MM-DD>-agentic-report.md` plus `<out>/history/<timestamp>.json` for the diff. The
report is meant to become an execution wave: findings are written so each one maps to a task.

Read `references/checks.md` for the check catalog and `references/hreflang-parity.md` for the
bilingual audit. Both are read on demand — do not preload them.
