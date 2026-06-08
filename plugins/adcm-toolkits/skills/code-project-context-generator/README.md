# code-project-context-generator

Scans a code project, builds a structured map of its architecture, and generates an installable, **lazy-loading** context skill of the form `code-project-context:[project-name]` — so Claude can understand and remember a codebase across working sessions without loading everything at once.

## Install

This skill ships in the **`adcm-toolkits`** plugin of the public **`adcm`** marketplace:

```
/plugin marketplace add angel-carvajal/adcm
/plugin install adcm-toolkits@adcm
```

> Marketplace state is per profile (`CLAUDE_CONFIG_DIR`), so run this once per profile.

## Use

- **Auto-invocation:** ask to "create project context", "scan repo", "map architecture", "give me context for another project", etc.
- **Explicit:** `/adcm-toolkits:code-project-context-generator`
- It runs `scripts/scan_project.py` over a target repository and scaffolds a new context skill from `templates/`. The generated skill keeps a light index in its `SKILL.md` and reads per-section detail on demand.

## What the generated context contains

The generated `code-project-context:[name]` skill is a lazy-loaded knowledge base. Each section file is either:

- **`auto`** — scan-derived and rewritten on every run (wrapped in `<!-- auto-generated -->`): `stack`, `architecture`, `entry-points`, `api-surface`, `data-models`, `config-env` (env var **names only**, no values), `testing`, `conventions`, `glossary`, `folders/*`.
- **`human`** — authored by Claude reading the code, and **preserved** across re-scans: `business-flows`, `security` (incl. auth & human-first zones), `tech-debt`.

Re-running on an evolved project is a **refresh**: it regenerates the `auto` files and updates `last_scanned`, while never overwriting the `human` ones.

## Structure

- `SKILL.md` — the generation workflow (scan → review → author semantic sections → generate → refresh).
- `scripts/scan_project.py` — the scanner (Python 3, standard library only); detects stack, tree, entry points, API surface, data models, env vars, and testing.
- `templates/` — templates for the generated skill (`SKILL.md.tmpl` + per-section docs, `auto` and `human`).

## Requirements

Python 3 (standard library only — no external dependencies). MIT licensed.
