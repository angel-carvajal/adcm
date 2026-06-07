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
- It runs `scripts/scan_project.py` over a target repository and scaffolds a new context skill from `templates/`. The generated skill keeps a light index in its `SKILL.md` and reads per-folder detail on demand.

## Structure

- `SKILL.md` — the generation workflow / steps.
- `scripts/scan_project.py` — the scanner (Python 3, standard library only).
- `templates/` — templates for the generated skill (`SKILL.md.tmpl` + per-section docs: architecture, stack, entry-points, conventions, glossary, folder).

## Requirements

Python 3 (standard library only — no external dependencies). MIT licensed.
