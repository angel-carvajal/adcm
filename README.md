# adcm  ·  marketplace `adcm`

ADCM public toolkits for Claude Code (open-source).

## Plugins

| Plugin | What it does | Skills |
|---|---|---|
| `adcm-toolkits` | Public ADCM toolkits: multi-advisor council, code-project and business-context generators, execution-prompt architect, agentic SEO reporter, design-direction architect, artifact courier, explainer-video recorder. | agentic-seo-report, artifact-courier, business-context-generator, code-project-context-generator, council, design-direction-architect, execution-prompt-architect, explainer-video |

## Install

> Marketplace state is per `CLAUDE_CONFIG_DIR` — run this once per profile.

```
/plugin marketplace add angel-carvajal/adcm
/plugin install adcm-toolkits@adcm
```

## Access

🌍 Public — anyone can install  ·  profile: any (claude-personal for your own use)

## Notes

- Public open-source toolkit marketplace by ADCM. The `adcm-toolkits` plugin ships the Council multi-advisor deliberation framework (generic, no confidential context), a code-project context generator, a business context generator, and an execution-prompt architect. **Do not commit private context to a public fork.** The plugin also ships an artifact courier (a Sonnet sub-agent that regenerates and republishes the plan pages and returns the links block) and a pure-orchestrator hard rule shared by all eight skills. It also ships a deterministic status digest for session start, six role agents with fixed models and tools, and a renovate flow for existing brains that also fixes stale notes. See the plugin README and CHANGELOG for the current release.
- Per-plugin requirements: see each plugin's README.

## License

MIT — see [LICENSE](./LICENSE). © 2026 Angel Carvajal.
