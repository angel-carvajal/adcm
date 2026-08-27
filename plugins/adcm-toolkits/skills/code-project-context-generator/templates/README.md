# Templates — code-project-context-generator

These templates are the base for generating the `code-project-context-[project-name]` skill. When the generator flow reaches Step 4, Claude takes each template, fills the `{{...}}` placeholders with scan data + the user's answers, and writes them to the skill's output.

## Inventory

Each template is **`auto`** (scan-derived; wrapped in `<!-- auto-generated -->` markers and rewritten on every scan) or **`human`** (semantic; written once by Claude in Step 3.5 and **preserved** across re-scans).

| Template | Destination in the generated skill | What it contains | Kind |
|----------|------------------------------------|------------------|------|
| `SKILL.md.tmpl` | `SKILL.md` (root) | High-level index — ALWAYS loaded (auto block wrapped) | mixed |
| `architecture.md.tmpl` | `architecture.md` | Full tree + short descriptions — on-demand | auto |
| `stack.md.tmpl` | `stack.md` | Stack, deps, versions, DB, testing — on-demand | auto |
| `entry-points.md.tmpl` | `entry-points.md` | Commands, routes, flows, jobs — on-demand | auto |
| `api-surface.md.tmpl` | `api-surface.md` | Endpoints/routes, methods, specs — on-demand | auto |
| `data-models.md.tmpl` | `data-models.md` | Entities, ORM, migrations, schema — on-demand | auto |
| `config-env.md.tmpl` | `config-env.md` | Env var names (no values), config files — on-demand | auto |
| `testing.md.tmpl` | `testing.md` | Frameworks, test dirs, coverage, CI — on-demand | auto |
| `conventions.md.tmpl` | `conventions.md` | Detected code conventions — on-demand | auto |
| `glossary.md.tmpl` | `glossary.md` | Domain terms — on-demand | auto |
| `folder.md.tmpl` | `folders/[slug].md` | Detail of a specific folder — on-demand | auto |
| `business-flows.md.tmpl` | `business-flows.md` | Critical end-to-end journeys — on-demand | human |
| `security.md.tmpl` | `security.md` | Auth, sensitive data, gaps, human-first zones — on-demand | human |
| `tech-debt.md.tmpl` | `tech-debt.md` | Known quirks & tech debt (`file:line`) — on-demand | human |

## Placeholders used

Placeholders have the format `{{NAME_UPPERCASE}}` and are replaced by Claude when rendering. They are descriptive by design — there is no rigid list; Claude decides what to put based on what the scanner extracted and what the user provided.

Common placeholders:

- `{{PROJECT_NAME}}` — human-readable project name
- `{{PROJECT_SLUG}}` — kebab-case slug for the skill name
- `{{ONE_LINE_DESCRIPTION}}` — what the project does in one business sentence
- `{{STACK_ONELINER}}` — stack summarized on one line, e.g. `Node 20 • Next.js 14 • TypeScript • Prisma • PostgreSQL`
- `{{HIGH_LEVEL_TREE}}` — tree up to 2 levels with 1 line per folder
- `{{FULL_TREE}}` — full tree
- `{{ALIASES_LIST}}` — additional aliases and triggers separated by commas
- `{{SCAN_DATE}}` — scan date in `YYYY-MM-DD` format
- `{{ROOT_HINT}}` — usual path where the project lives (if recurring)

## Philosophy

The templates are guides, not straitjackets. If a project has no database, omit the DB section. If it has no CI/CD, omit that part. It's better to have a short, useful skill than a long one with empty sections "for completeness".

**The only thing that CANNOT change:** the resulting SKILL.md must respect the lazy-loading pattern. Never inline the details of each folder into the SKILL.md — that defeats the whole point of the skill.
