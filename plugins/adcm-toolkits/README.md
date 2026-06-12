# adcm-toolkits

Public ADCM toolkits: the Council multi-advisor deliberation framework (generic, bring-your-own-context), a code-project context generator that builds a lazy-loading, refreshable knowledge base of a codebase (architecture, API surface, data models, config, security, conventions), and an execution-prompt architect that turns goals + deep code analysis into a five-document execution plan (executive proposal, master plan, detailed plan, task tracker, execution protocol) with copy-paste prompts per wave. Use for structured multi-perspective decisions, to document a codebase, or to plan and prompt large tasks and migrations.  ·  v0.3.0

## Skills

- **`code-project-context-generator`** — Scans a code project, builds a structured map of its architecture, and generates an installable skill of the form `code-project-context:[project-name]` with lazy-loading (the resulting SKILL.md loads…  ·  invoke: `/adcm-toolkits:code-project-context-generator`
- **`council`** — Convenes a council of 5 advisors (Strategist, Adversary, Outsider, Operator, Futurist) plus a Chairman to deliberate on a decision and deliver an actionable verdict.  ·  invoke: `/adcm-toolkits:council`
- **`execution-prompt-architect`** — Turns a task description plus deep code analysis into a complete execution-plan family: executive proposal, master plan, detailed plan, task tracker, and an execution protocol with copy-paste prompts per wave (GOAL · TASKS · LOOP · WORKFLOW fan-out · GUARDRAILS & CLOSE) whose loop exits by verifiable DoD. ⚠ High token consumption — best results. Pairs with `code-project-context-generator`.  ·  invoke: `/adcm-toolkits:execution-prompt-architect`

## Requirements

- `code-project-context-generator`: Python 3 (stdlib only, no external dependencies) for the scanner.
- `council`: No runtime dependencies. Markdown-only skill read by Claude. In Claude Code, parallel advisor execution uses the built-in Task tool; in claude.ai/Cowork it falls back to sequential context-isolated reads. Works in Claude Code, Cowork, and claude.ai.
- `execution-prompt-architect`: No runtime dependencies. Markdown-only skill read by Claude. Sub-agent fan-out uses Claude Code's built-in agents/Workflow; elsewhere it degrades to sequential analysis.

## Install

```
/plugin marketplace add angel-carvajal/adcm
/plugin install adcm-toolkits@adcm
```

Skills are namespaced as `/adcm-toolkits:<skill>`; description-based auto-invocation also works.

## Access

🌍 Public — anyone can install
