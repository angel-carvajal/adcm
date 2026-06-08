# adcm-toolkits

Public ADCM toolkits: the Council multi-advisor deliberation framework (generic, bring-your-own-context) and a code-project context generator that builds a lazy-loading, refreshable knowledge base of a codebase (architecture, API surface, data models, config, security, conventions). Use for structured multi-perspective decisions or to document a codebase.  ·  v0.1.0

## Skills

- **`code-project-context-generator`** — Scans a code project, builds a structured map of its architecture, and generates an installable skill of the form `code-project-context:[project-name]` with lazy-loading (the resulting SKILL.md loads…  ·  invoke: `/adcm-toolkits:code-project-context-generator`
- **`council`** — Convenes a council of 5 advisors (Strategist, Adversary, Outsider, Operator, Futurist) plus a Chairman to deliberate on a decision and deliver an actionable verdict.  ·  invoke: `/adcm-toolkits:council`

## Requirements

- `code-project-context-generator`: Python 3 (stdlib only, no external dependencies) for the scanner.
- `council`: No runtime dependencies. Markdown-only skill read by Claude. In Claude Code, parallel advisor execution uses the built-in Task tool; in claude.ai/Cowork it falls back to sequential context-isolated reads. Works in Claude Code, Cowork, and claude.ai.

## Install

```
/plugin marketplace add angel-carvajal/adcm
/plugin install adcm-toolkits@adcm
```

Skills are namespaced as `/adcm-toolkits:<skill>`; description-based auto-invocation also works.

## Access

🌍 Public — anyone can install
