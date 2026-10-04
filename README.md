# adcm  ·  marketplace `adcm`

ADCM public toolkits for Claude Code (open-source).

## Plugins

| Plugin | What it does | Skills |
|---|---|---|
| `adcm-toolkits` | Public ADCM toolkits: the Council multi-advisor deliberation framework (generic, bring-your-own-context), a code-project… | agentic-seo-report, artifact-courier, business-context-generator, code-project-context-generator, council, design-direction-architect, execution-prompt-architect |

## Install

> Marketplace state is per `CLAUDE_CONFIG_DIR` — run this once per profile.

```
/plugin marketplace add angel-carvajal/adcm
/plugin install adcm-toolkits@adcm
```

## Access

🌍 Public — anyone can install  ·  profile: any (claude-personal for your own use)

## Notes

- Public open-source toolkit marketplace by ADCM. The `adcm-toolkits` plugin ships the Council multi-advisor deliberation framework (generic, no confidential context), a code-project context generator, a business context generator, and an execution-prompt architect. **Do not commit private context to a public fork.** Since 0.12.0 the plugin also ships an artifact courier (a Sonnet sub-agent that regenerates and republishes the plan pages and returns the links block) and a pure-orchestrator hard rule shared by all six skills. It also ships a deterministic status digest for session start. Since 0.14.0: six role agents with fixed models and tools.
- Per-plugin requirements: see each plugin's README.

## License

MIT — see [LICENSE](./LICENSE). © 2026 Angel Carvajal.
