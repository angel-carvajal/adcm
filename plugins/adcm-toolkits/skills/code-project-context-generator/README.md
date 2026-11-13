# code-project-context-generator

Scans a code project, builds a structured map of its architecture, and generates an installable, **lazy-loading** context skill of the form `code-project-context-[project-name]` — so Claude can understand and remember a codebase across working sessions without loading everything at once.

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
- It runs `scripts/scan_project.py` over a target repository and scaffolds a new context skill from `templates/`. The generated skill keeps a light index in its `SKILL.md` and reads per-section detail on demand. For a project with an execution brain it also writes the brain map with `scripts/launchers/map-refresh`.

## What the generated context contains

The generated `code-project-context-[name]` skill is a lazy-loaded knowledge base. Each section file is either:

- **`auto`** — scan-derived and rewritten on every run (wrapped in `<!-- auto-generated -->`): `stack`, `architecture`, `entry-points`, `api-surface`, `data-models`, `config-env` (env var **names only**, no values), `testing`, `conventions`, `glossary`, `usage-map` (shared surfaces → consumer census, so "this component is rendered by 10 more pages" is a lookup, not a re-derivation), `folders/*`.
- **`human`** — authored by Claude reading the code, and **preserved** across re-scans: `business-flows`, `security` (incl. auth & human-first zones), `tech-debt`.
- **`mixed`** — `dependencies` (runtime pins, package manager, every direct dependency `declared → locked`, CI and Docker pins, rendered by script) with a human `## Policy` section that the dependency-renovate skill obeys and every refresh preserves.

Beside the skill, the brain gets a **reuse map** (`<ai-brain>/map/utilities.md`, `patterns.md`, `where-to-look.md`): the helpers, bases and patterns that already exist, so new code consumes them instead of writing a variant. `map-refresh` renders the rows from the scan; the ✍ columns are human text that every refresh keeps. It is not an `auto` file of the skill and a full refresh never overwrites it.

The generated `SKILL.md` routes reading by task type (a "Start here when…" hint per file plus an L1–L4 reading order), so sessions spend the minimum tokens the task needs.

Re-running on an evolved project is a **refresh**: it regenerates the `auto` files and updates `last_scanned`, while never overwriting the `human` ones. After a closed execution wave, the **delta mode** — `scan_project.py <root> --update <changed-paths>` — refreshes only the affected `folders/*.md` and `usage-map.md` rows, cheap enough to run at every wave close; `map-refresh --project <root> --brain <dir> --update <changed-paths>` rewrites the project's map block and reports the rows those paths touch, and `map-refresh --brain <dir> --check` reports whether the map is fresh (exit 0), stale (1) or missing (2). A manifest, lockfile, runtime-pin, CI or Dockerfile path in `--update` also marks `dependencies.md` and the matching `stack.md` sections.

## Structure

- `SKILL.md` — the generation workflow (scan → review → author semantic sections → generate → refresh).
- `scripts/scan_project.py` — the scanner (Python 3, standard library only); detects stack, tree, entry points, API surface, data models, env vars, and testing.
- `scripts/dependency_manifest.py` — the dependency manifest block (stdlib), imported by the scanner and by the `deps-check` of the dependency-renovate skill. Selftest: `scripts/dependency-manifest-selftest.py`.
- `scripts/map_refresh.py` — the brain map renderer behind the `map-refresh` launcher (stdlib only). Selftest: `scripts/map-refresh-selftest.py`.
- `templates/map/` — the three map templates (`utilities`, `patterns`, `where-to-look`), rendered by `map_refresh.py`.
- `templates/` — templates for the generated skill (`SKILL.md.tmpl` + per-section docs, `auto` and `human`).

## Requirements

Python 3 (standard library only — no external dependencies). MIT licensed.
