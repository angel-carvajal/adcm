# adcm-toolkits

Public ADCM toolkits: the Council multi-advisor deliberation framework (generic, bring-your-own-context) and a code-project context generator that scaffolds lazy-loading project docs. Use for structured multi-perspective decisions or to document a codebase.  ·  v0.1.0

## Skills

- **`code-project-context-generator`** — Escanea un proyecto de código, arma un mapa estructurado de su arquitectura y genera un skill instalable tipo `code-project-context:[project-name]` con lazy-loading (el SKILL.md resultante carga solo…  ·  invoke: `/adcm-toolkits:code-project-context-generator`
- **`council`** — Convenes a council of 5 advisors (Strategist, Adversary, Outsider, Operator, Futurist) plus a Chairman to deliberate on a decision and deliver an actionable verdict.  ·  invoke: `/adcm-toolkits:council`

## Requirements

- `code-project-context-generator`: Python 3 (solo stdlib, sin dependencias externas) para el scanner.
- `council`: No runtime dependencies. Markdown-only skill read by Claude. In Claude Code, parallel advisor execution uses the built-in Task tool; in claude.ai/Cowork it falls back to sequential context-isolated reads. Works in Claude Code, Cowork, and claude.ai.

## Install

```
/plugin marketplace add <tu-usuario-github>/adcm
/plugin install adcm-toolkits@adcm
```

Skills are namespaced as `/adcm-toolkits:<skill>`; description-based auto-invocation also works.

## Access

🌍 Public — anyone can install
