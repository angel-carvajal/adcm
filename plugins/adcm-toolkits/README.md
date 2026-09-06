# adcm-toolkits

Public ADCM toolkits: the Council multi-advisor deliberation framework (generic, bring-your-own-context), a code-project context generator that builds a lazy-loading, refreshable knowledge base of a codebase (architecture, API surface, data models, config, security, conventions), a business context generator that interviews the owner and researches the business website to produce an installable, lazy-loading business-context skill (identity, offering, market, brand voice, sales, operations, objectives, plus a confidential internal file), and an execution-prompt architect that turns goals + deep code analysis into a six-document execution plan (executive proposal, master plan, detailed plan, timeframe plan with critical path and week-by-week schedule, task tracker, execution protocol) with self-contained copy-paste prompts per wave (each embeds a SCOPE manifest: files to modify with why, impact census of shared-surface consumers, freshness checks — clean sessions execute without re-analyzing the project) and an optional single-file HTML with a CSS Gantt timeline. The context generator also emits a usage-map (shared surfaces → consumer census) and supports delta refreshes (--update) at wave close. Use for structured multi-perspective decisions, to document a codebase or a business, or to plan and prompt large tasks and migrations.  ·  v0.8.0

## Skills

- **`business-context-generator`** — Interviews a business owner and researches the business website to generate an installable, lazy-loading business-context skill of the form `business-init-[business-slug]` (the resulting SKILL.md load…  ·  invoke: `/adcm-toolkits:business-context-generator`
- **`code-project-context-generator`** — Scans a code project, builds a structured map of its architecture, and generates an installable skill of the form `code-project-context-[project-name]` with lazy-loading (the resulting SKILL.md loads…  ·  invoke: `/adcm-toolkits:code-project-context-generator`
- **`council`** — Convenes a council of 5 advisors (Strategist, Adversary, Outsider, Operator, Futurist) plus a Chairman to deliberate on a decision and deliver an actionable verdict.  ·  invoke: `/adcm-toolkits:council`
- **`execution-prompt-architect`** — Turns a task description plus deep code analysis into a complete execution-plan family: an executive proposal (what is sought and what to approve, for stakeholders), a master plan (strategy and decisi…  ·  invoke: `/adcm-toolkits:execution-prompt-architect`

## Requirements

- `business-context-generator`: No runtime dependencies. Markdown-only skill. Uses AskUserQuestion for the interview and WebFetch for website research when available; degrades to a plain-text interview without them. Works in Claude Code, Cowork, and claude.ai.
- `code-project-context-generator`: Python 3 (stdlib only, no external dependencies) for the scanner.
- `council`: No runtime dependencies. Markdown-only skill read by Claude. In Claude Code, parallel advisor execution uses the built-in Task tool; in claude.ai/Cowork it falls back to sequential context-isolated reads. Works in Claude Code, Cowork, and claude.ai.
- `execution-prompt-architect`: Works with any Claude model. In Claude Code the code analysis fans out to sub-agents using the model/effort the user picks; in environments without sub-agents it degrades to sequential analysis. Sub-agent fan-out is budgeted at 20 per phase with fixed roles by model tier: the main session (Fable) orchestrates and runs the DoD, Opus sub-agents investigate and audit (and implement ⚠gate waves), Sonnet sub-agents implement from executor briefs, with an escalation ladder Sonnet → Opus → Fable — in every effort level, ultracode included. Generated prompts are tuned for Fable at high effort but run on any model.

## Install

```
/plugin marketplace add angel-carvajal/adcm
/plugin install adcm-toolkits@adcm
```

Skills are namespaced as `/adcm-toolkits:<skill>`; description-based auto-invocation also works.

## Project container convention

The three generators share one filesystem convention (canonical spec:
`skills/execution-prompt-architect/references/project-structure.md`): each project
lives in a **container that is never a git repo** —
`<container>/{ai, projects}` — EVERYTHING AI lives under `ai/`: `ai/ai-brain` is its
own git repo holding ALL documentation (execution brain, the product's
spec/plan/decisions/backlog under `docs/`, and lazy per-module doc under
`modules/<mod>/`), and `ai/<slug>-{ai|ia}-{admin|common}/` holds the plugin
marketplaces (one git repo each),
and the code lives under `projects/` — a plain grouping folder with **one git repo per
engineering project**, each carrying a gitignored `ai-brain` symlink (to `ai/ai-brain` or its
`modules/<mod>`) so relative doc paths resolve in build sessions. The container
layout is documented in `ai/ai-brain/README.md`, never in loose root files.

## Access

🌍 Public — anyone can install
