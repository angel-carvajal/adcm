# Templates — code-project-context-generator

These templates are the base for generating the `code-project-context:[project-name]` skill. When the generator flow reaches Step 4, Claude takes each template, fills the `{{...}}` placeholders with scan data + the user's answers, and writes them to the skill's output.

## Inventory

| Template | Destination in the generated skill | What it contains |
|----------|------------------------------------|------------------|
| `SKILL.md.tmpl` | `SKILL.md` (root) | High-level index — ALWAYS loaded |
| `architecture.md.tmpl` | `architecture.md` | Full tree + short descriptions — on-demand |
| `stack.md.tmpl` | `stack.md` | Stack, deps, versions, DB, testing — on-demand |
| `entry-points.md.tmpl` | `entry-points.md` | Commands, routes, flows, jobs — on-demand |
| `conventions.md.tmpl` | `conventions.md` | Detected code conventions — on-demand |
| `glossary.md.tmpl` | `glossary.md` | Domain terms — on-demand |
| `folder.md.tmpl` | `folders/[slug].md` | Detail of a specific folder — on-demand |

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
