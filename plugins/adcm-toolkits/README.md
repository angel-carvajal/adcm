# adcm-toolkits

Public ADCM toolkits: the Council multi-advisor deliberation framework (generic, bring-your-own-context), a code-project context generator that builds a lazy-loading, refreshable knowledge base of a codebase (architecture, API surface, data models, config, security, conventions), a business context generator that interviews the owner and researches the business website to produce an installable, lazy-loading business-context skill (identity, offering, market, brand voice, sales, operations, objectives, plus a confidential internal file), and an execution-prompt architect that turns goals + deep code analysis into a six-document execution plan (executive proposal, master plan, detailed plan, timeframe plan with critical path and week-by-week schedule, task tracker, execution protocol) with self-contained copy-paste prompts per wave (each embeds a SCOPE manifest: files to modify with why, impact census of shared-surface consumers, freshness checks — clean sessions execute without re-analyzing the project) and an optional single-file HTML with a CSS Gantt timeline. The context generator also emits a usage-map (shared surfaces → consumer census) and supports delta refreshes (--update) at wave close. Use for structured multi-perspective decisions, to document a codebase or a business, or to plan and prompt large tasks and migrations.  ·  v0.11.0

## Skills

- **`agentic-seo-report`** — Audits a live website for how well search engines AND AI agents can find, read and use it: combines the free is-agentic.com agent-readiness score with local checks (llms.txt, hreflang reciprocity, JSON-LD validity, schema coverage, sitemap health, AI-crawler posture, text visible without JS), writing findings ranked by traffic impact, each with the command that reproduces it — and it honors per-project confidentiality rules so it never recommends publishing internal pricing or process detail.  ·  invoke: `/adcm-toolkits:agentic-seo-report`
- **`business-context-generator`** — Interviews a business owner and researches the business website to generate an installable, lazy-loading business-context skill of the form `business-init-[business-slug]`. Now also mines EXISTING sources first — sales decks, database migrations and price catalogs, quoting tools, a sibling venture's execution docs, brand tokens and memory files — one sub-agent per source family under the 20-agent tiered protocol, consolidating a fact sheet where every fact carries its source path, date, confidence and confidentiality class, then interviews only for the UNKNOWNs.  ·  invoke: `/adcm-toolkits:business-context-generator`
- **`code-project-context-generator`** — Scans a code project, builds a structured map of its architecture, and generates an installable skill of the form `code-project-context-[project-name]` with lazy-loading (the resulting SKILL.md loads…  ·  invoke: `/adcm-toolkits:code-project-context-generator`
- **`council`** — Convenes a council of 5 advisors (Strategist, Adversary, Outsider, Operator, Futurist) plus a Chairman to deliberate on a decision and deliver an actionable verdict.  ·  invoke: `/adcm-toolkits:council`
- **`design-direction-architect`** — Researches and locks a web design direction before any code is written: interviews the owner, mines the Framer template marketplace, Pinterest, 21st.dev (magic MCP) and Pexels, triages 15+ candidates and presents 5 finalists backed by two or more sources. Writes a reusable pack to `.design/` (brief, references, tokens, commerce, assets, decisions) that the building skills consume; it never builds the site itself.  ·  invoke: `/adcm-toolkits:design-direction-architect`
- **`execution-prompt-architect`** — Turns a task description plus deep code analysis into a complete execution-plan family: an executive proposal (what is sought and what to approve, for stakeholders), a master plan (strategy and decisi…  ·  invoke: `/adcm-toolkits:execution-prompt-architect`

## Requirements

- `agentic-seo-report`: No runtime dependencies. Reads the free is-agentic.com public API plus local checks against the project's own site content; honors an optional project-rules file for confidentiality.
- `business-context-generator`: No runtime dependencies. Markdown-only skill. Uses AskUserQuestion for the interview and WebFetch for website research when available; the mining mode fans out one sub-agent per source family (Claude Code); degrades to a plain-text interview without sub-agents. Works in Claude Code, Cowork, and claude.ai.
- `code-project-context-generator`: Python 3 (stdlib only, no external dependencies) for the scanner.
- `council`: No runtime dependencies. Markdown-only skill read by Claude. In Claude Code, parallel advisor execution uses the built-in Task tool; in claude.ai/Cowork it falls back to sequential context-isolated reads. Works in Claude Code, Cowork, and claude.ai.
- `design-direction-architect`: Markdown-only. Framer needs network; Pexels reads `PEXELS_API_KEY`; 21st.dev needs the `magic` MCP; Pinterest and screenshots need a browser MCP and degrade explicitly without it.
- `execution-prompt-architect`: Works with any Claude model. In Claude Code the code analysis fans out to sub-agents using the model/effort the user picks; in environments without sub-agents it degrades to sequential analysis. Sub-agent fan-out is budgeted at 20 per phase with fixed roles by model tier: the main session (Fable) orchestrates and runs the DoD, Opus sub-agents investigate and audit (and implement ⚠gate waves), Sonnet sub-agents implement from executor briefs, with an escalation ladder Sonnet → Opus → Fable — in every effort level, ultracode included. Generated prompts are tuned for Fable at high effort but run on any model.

## Install

```
/plugin marketplace add angel-carvajal/adcm
/plugin install adcm-toolkits@adcm
```

Skills are namespaced as `/adcm-toolkits:<skill>`; description-based auto-invocation also works.

## Project container convention

The generators share one filesystem convention (canonical spec:
`skills/execution-prompt-architect/references/project-structure.md`). A container
lives in one of **two homes**, by relationship: `~/<venture>/` for own ventures
(e.g. `~/<venture>/`), or `~/clientes_projects/<client>/` for client work. It
is **never a git repo** — `<container>/{ai, projects}` — EVERYTHING AI lives under
`ai/`: `ai/<slug>-{ai|ia}-{admin|common}/` (plus per-venture variants `-commercial`,
`-platform`, `-academic`) holds the plugin marketplaces, one git repo each; and the
code lives under `projects/` (or `p-engineering/`/`engineering/`) — a plain grouping
folder with **one git repo per engineering project**.

The execution brain, `ai-brain/`, has **three supported positions**: canonical
`ai/ai-brain/` (its own git repo holding ALL documentation — execution docs, the
product's spec/plan/decisions/backlog under `docs/`, and lazy per-module doc under
`modules/<mod>/`); the container root, `<container>/ai-brain/`; or `docs/ai-brain/`
with a symlink `ai/ai-brain -> ../docs/ai-brain` that is MANDATORY in that third
case — the `artifact-guard` Stop hook only discovers `ai/ai-brain/artifacts.json` or
`ai-brain/artifacts.json`, so any other layout silently disables it. Each engineering
project carries a gitignored `ai-brain` symlink (to wherever the brain actually lives,
or its `modules/<mod>`) so relative doc paths resolve in build sessions. The container
layout is documented in `ai/ai-brain/README.md`, never in loose root files — including
which document-name set (English or Spanish) the container uses (rule 9).

## Access

🌍 Public — anyone can install
