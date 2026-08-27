---
name: code-project-context-generator
description: >
  Scans a code project, builds a structured map of its architecture, and generates
  an installable skill of the form `code-project-context-[project-name]` with lazy-loading
  (the resulting SKILL.md loads only the index, and per-folder details are read on-demand).
  Triggers when the user asks to 'create project context', 'new code project',
  'scan repo', 'map architecture', 'code project context', 'analyze project',
  'load code context', 'new repo', 'register project', 'create project skill',
  'project init', 'architecture map', 'give me context for another project', 'I have another repo',
  'map code', 'code map', or any variation where they want Claude to understand and
  remember the architecture of a code project for future working sessions.
compatibility: >
  Python 3 (stdlib only, no external dependencies) for the scanner.
---

# Code Project Context Generator

This skill guides the process of analyzing a code project and generating an installable context skill of the form `code-project-context-[project-name]`. The resulting skill is designed with **lazy-loading**: its SKILL.md loads only the high-level map (tree + short descriptions per folder + stack + entry points), and the details of each folder are read on-demand with Read when the working session requires them. This keeps context lightweight while still allowing deep dives where needed.

---

## Purpose

Solve the problem of "starting work on a project without having to explain to Claude what each folder does, what stack it uses, where the entry point is, and what the conventions are". After running this skill once on a project, future sessions can invoke the resulting skill and Claude will already know where everything is.

---

## Dependencies

- Python 3 (stdlib only, no external packages) for the scanner.
- Script bundled in this skill: `scripts/scan_project.py` (relative to the skill root).
- When an absolute path is needed, the skill lives at
  `${CLAUDE_PLUGIN_ROOT}/skills/code-project-context-generator/`, so the scanner is at
  `${CLAUDE_PLUGIN_ROOT}/skills/code-project-context-generator/scripts/scan_project.py`.

---

## Workflow

### STEP 0: Get the project path

The skill needs the absolute path of the project. Strategy:

1. **If there is a working directory already open/selected in the session**, ask the user whether that is the project to analyze.
2. **If no folder is selected**, ask the user to indicate the project root (or use the directory-selection mechanism available in the environment).
3. **If the user prefers to paste a manual path**, accept it as-is (useful for projects outside the working directory).

Verify that the path exists and that it has typical project indicators (`.git/`, `package.json`, `composer.json`, `pyproject.toml`, `requirements.txt`, `Cargo.toml`, `go.mod`, etc.). If there are none, confirm with the user that it really is a code project before continuing.

**Code repo vs container.** The standard layout (see
`../execution-prompt-architect/references/project-structure.md`) is a CONTAINER that is
not a git repo — `<container>/{ai-brain, ai, projects}` — with the code under
`projects/` (plain grouping folder, one git repo per engineering project) and ALL
documentation in `ai-brain/`. The scan target is always one **project repo**, but
detect the container: if an ancestor holds sibling `ai-brain/` and/or `ai/` folders,
record the container path — the generated skill must describe the whole container in
its architecture map and route planned work and docs to the sibling `ai-brain/`.

### STEP 1: Collect minimal metadata

Use AskUserQuestion to capture what the scanner cannot infer:

**Round 1 — Project identity:**

- What is the project called? (short name for the skill slug, e.g. `acme-web`, `billing-api`, `shop-backend`)
- Is there an internal/commercial name different from the repo name?
- What does the project do in one sentence? (business value, not tech)
- Is it your own project, a client project, open source, or experimental?

**Round 2 — Operational context (optional, if applicable):**

- Is there an associated client? (link it to an existing `client-context-*` if applicable)
- Is it frontend, backend, fullstack, mobile, CLI, library, infra?
- Does it have a deploy/live environment? (URLs, staging, prod)
- Is there relevant external documentation? (Notion, Confluence, remote README)
- Does the project keep an **execution brain**? By convention it lives at
  `<container>/ai-brain/` (own git repo, sibling of the code repo, reachable from the
  code repo through a gitignored `ai-brain` symlink) — confirm rather than ask openly;
  accept a different path if the project predates the convention. The generated skill
  routes planned work to `<ai-brain>/tasks/<ID>.md` (or its task cards) first, and
  this map covers unplanned work.

If the user already provided some of this info when invoking the skill, don't ask again — extract it from context.

### STEP 2: Scan the project

The scanner is bundled in this skill at `scripts/scan_project.py` (relative to the skill root).
Run it pointing at the project path. Before running it, check the preconditions:

```bash
# 1. Verify that Python 3 is available
command -v python3 >/dev/null 2>&1 || { echo "Error: Python 3 is required (not found in PATH)."; exit 1; }

# 2. Resolve the scanner. In an installed plugin use ${CLAUDE_PLUGIN_ROOT};
#    as a fallback, a path relative to the skill root.
SCANNER="${CLAUDE_PLUGIN_ROOT:-.}/skills/code-project-context-generator/scripts/scan_project.py"
[ -f "$SCANNER" ] || SCANNER="scripts/scan_project.py"
[ -f "$SCANNER" ] || { echo "Error: scan_project.py not found."; exit 1; }

# 3. Verify that the project path exists and is readable
PROJECT_PATH="<PROJECT_PATH>"
[ -d "$PROJECT_PATH" ] && [ -r "$PROJECT_PATH" ] || { echo "Error: path '$PROJECT_PATH' does not exist or is not readable."; exit 1; }

# 4. Scan (the JSON goes to a temp directory; adjust the destination to your <output-dir>)
python3 "$SCANNER" "$PROJECT_PATH" --output "${TMPDIR:-/tmp}/project_scan.json"
```

> Note: the scanner already validates internally that the root exists (it raises `FileNotFoundError`).
> The checks above give clear messages before invoking it.

The scanner produces a JSON with:

- `meta` — root name, size, files scanned
- `stack` — detected languages, frameworks, runtimes, package manager
- `dependencies` — list of critical deps with version (Node, PHP/Composer, Python, Go, Rust, Ruby)
- `entry_points` — scripts in package.json, artisan commands, main modules, Dockerfile CMDs, CI scripts
- `tree` — folder tree of the project with counts and sizes
- `folders` — each folder with path, file count, predominant types, and a tentative purpose hash-tag (routing, models, services, tests, config, docs, etc.)
- `configs` — configuration files found (`.env.example`, `docker-compose.yml`, CI, linters)
- `conventions` — detected hints (MVC, feature-based, monorepo, workspaces, etc.)
- `domain_terms` — terms that appear repeatedly in file/class names (glossary candidates)
- `docs` — READMEs and other documentation files found
- `api_surface` — detected endpoints/routes (`{style, endpoints:[{method,path,source}], openapi, count}`) — Laravel/Express/Nest/FastAPI/Flask/Next.js
- `data_models` — entities/ORM (`{orm, entities, migrations_count, schema_files}`) — Eloquent/Prisma/TypeORM/Sequelize/Django/SQLAlchemy/Mongoose
- `config_env` — env var **names only** from `.env.example`/`.env.sample` (`{files, vars:[{name,comment,sensitive}]}`) — never values
- `testing` — test strategy (`{frameworks, test_dirs, test_file_count, coverage_config, ci_runs_tests}`)
- `usage_map` — shared surfaces → consumer census (`{shared_roots, surfaces:[{symbol, defined_in, consumers_count, consumers, census_cmd}]}`) — exports defined under shared/lib/packages/components-style folders, with who consumes them across the rest of the project. This is what makes impact analysis ("this component is rendered by 10 more pages") a lookup instead of a re-derivation.
- `update` — only with `--update <paths>`: `{paths, affected_folders, affected_surfaces}` for delta refreshes (STEP 4.5).

These feed the **auto** sections (`api-surface.md`, `data-models.md`, `config-env.md`, `testing.md`, `usage-map.md`). The scanner does not produce the **semantic** sections — those are authored in STEP 3.5.

### STEP 3: Review with the user and fill the gaps

Present the user with a summary of the scan:

- Detected stack
- Top 10 folders by size/relevance
- Entry points found
- Candidate domain terms

Ask what the scanner cannot know:

- For ambiguous folders (the ones with a non-obvious purpose), ask the user to describe what they do in one line.
- Confirm or adjust the domain glossary terms.
- Identify "danger zones" or critical modules that Claude must touch carefully.

### STEP 3.5: Author the semantic sections (hybrid)

The scanner gives you the auto/structural sections for free. The high-value **semantic** sections (`business-flows.md`, `security.md`, `tech-debt.md`) cannot be scanned — **you author them** by reading the code the scan pointed at. This is the hybrid model: scanner for structure, Claude for judgment.

For each, read the relevant evidence and write substance (not placeholders):

- **`business-flows.md`** — read the entry points, the route files (`api_surface.source`), and the top services/controllers. Describe the 3–7 critical end-to-end journeys (trigger → participants → steps → side effects). Document the *why* (business rule), optionally with a Mermaid `sequenceDiagram`/`stateDiagram`.
- **`security.md`** — read the auth middleware/guards, the user/role model, the validation layer, and the `config_env` var names. Fill: authentication & authorization model, sensitive-data/PII classification, input validation, **known gaps** (be honest), and **human-first zones** (auth, payments, crypto, PII).
- **`tech-debt.md`** — capture quirks, gotchas, hardcoded values, disabled features, fragile coupling, "do not touch" areas — each with `file:line`. This is the highest-ROI file; be blunt.

Rules for this pass:
- **Accuracy over completeness.** If you can't determine a section from the code, write `<!-- TODO: needs manual authoring -->` instead of inventing.
- **Never include secret values** — only variable names and purposes.
- These files are **human-owned**: they carry NO `<!-- auto-generated -->` wrapper, so a future re-scan will preserve them.

### STEP 4: Generate the skill with lazy-loading

Build the output structure (`auto` = scan-derived, wrapped in `<!-- auto-generated -->`; `human` = authored in STEP 3.5, no wrapper):

```
code-project-context-[project-name]/
├── SKILL.md                    # High-level index (ALWAYS loaded) — auto block wrapped + human rules
├── stack.md                    # Stack, deps, versions, DB (auto)
├── architecture.md             # Full tree + short descriptions (auto)
├── entry-points.md             # How to start, routes, build/run/test (auto)
├── api-surface.md              # Endpoints/routes, methods, specs (auto)
├── data-models.md              # Entities, ORM, migrations, schema (auto)
├── config-env.md               # Env var names (no values), configs (auto)
├── testing.md                  # Frameworks, test dirs, coverage, CI (auto)
├── conventions.md              # Detected code patterns (auto)
├── glossary.md                 # Domain terms (auto)
├── usage-map.md                # Shared surfaces → consumer census + re-census commands (auto)
├── business-flows.md           # Critical end-to-end journeys (human)
├── security.md                 # Auth, sensitive data, gaps, human-first zones (human)
├── tech-debt.md                # Known quirks & tech debt, file:line (human)
└── folders/
    ├── [folder-1].md           # Detail of src/, app/, etc. (auto)
    └── ...
```

**Wrapping rule:** every `auto` file (and the scan-derived block of `SKILL.md`) starts with
`<!-- auto-generated: scan [date] — do not edit; refresh by re-running code-project-context-generator -->`
and ends with `<!-- end auto-generated -->`. The `human` files carry no such marker. This is what makes the refresh in STEP 4.5 safe.

**Golden rule:** the SKILL.md must NEVER have all the details inline. It should only have:

1. Project identity (1 paragraph)
2. Stack in one line (e.g. `Node 20 • Next.js 14 • TypeScript • Prisma • PostgreSQL`)
3. High-level map (tree up to 2 levels with 1 line per folder)
4. Index of detailed files: "For details on X, read `architecture.md`. For the full stack, read `stack.md`. For the `src/api/` folder, read `folders/src-api.md`."
5. Rules for Claude on how to use this context

Use the templates in `templates/` (relative to the skill root) as a base. The templates include placeholders that are filled in with the scanner's data.

### STEP 4.5: Refresh mode (when the context already exists)

If a `code-project-context-[project-name]/` already exists (the user is re-running on an evolved project), do **not** regenerate from scratch. Refresh incrementally:

**Delta refresh (preferred after a closed wave):** when the caller knows WHICH paths
changed (e.g. the wave-close doc-sync has the logbook's files-touched list), run
`scan_project.py <root> --update <comma-separated-paths>` and regenerate ONLY what its
`update` block names: the affected `folders/*.md`, the `usage-map.md` rows in
`affected_surfaces`, and the `last_scanned` stamps of those files. Everything else —
including all `human` files — stays untouched. This is what keeps the map fresh at
every wave close without paying a full refresh.

**Full refresh** (no known path list):

1. **Regenerate the `auto` files** wholesale from the fresh scan: `stack.md`, `architecture.md`, `entry-points.md`, `api-surface.md`, `data-models.md`, `config-env.md`, `testing.md`, `conventions.md`, `glossary.md`, `usage-map.md`, `folders/*.md`, and the wrapped block of `SKILL.md`. (These start with the `<!-- auto-generated -->` marker — safe to overwrite.)
2. **Preserve the `human` files** untouched: `business-flows.md`, `security.md`, `tech-debt.md`, and the identity/danger-zone prose of `SKILL.md` (anything outside the markers).
3. **Update `last_scanned`** in the `SKILL.md` frontmatter and the wrapper comments.
4. **Flag drift:** if the scan changed materially (new modules, stack change, endpoints added/removed), prepend a one-line note to the affected human files: `> ⚠ possible drift since last scan — review.` Do not edit their content.
5. Tell the user what was refreshed vs preserved.

### STEP 5: Package and install

Offer both routes (mirror of business-context-generator's delivery):

**Option A — the project's private plugin marketplace (recommended, the convention).**
By the standard container layout (see
`../execution-prompt-architect/references/project-structure.md`), the skill lands in
`<container>/ai/<slug>-{ai|ia}-common/plugins/<plugin>/skills/code-project-context-[project-name]/`
— the operational/engineering marketplace of the project (create it there if missing:
`.claude-plugin/marketplace.json` + `plugins/<plugin>/.claude-plugin/plugin.json`, own
git repo). Then bump the plugin's `version` (minor for a new skill, patch for a
refresh), update the marketplace README table, commit in THAT repo — and never push
for the user. Registration lives in the profile's Claude settings, not the container.

**Option B — standalone `.skill` zip** (no marketplace, or claude.ai):

1. Save everything under `<output-dir>/code-project-context-[project-name]/`, where `<output-dir>` is
   the output directory used by the environment (e.g. the session's outputs directory or a
   path chosen by the user).
2. (Optional) If the environment provides a skill packaging script, use it.
3. Zip it with the `.skill` extension so the environment shows it as installable:
   ```bash
   OUT_DIR="<output-dir>"
   SLUG="code-project-context-[project-name]"
   ( cd "$OUT_DIR" && zip -r "$SLUG.skill" "$SLUG/" )
   ```
4. Deliver the resulting `.skill` file to the user through the mechanism available in the environment.

---

## Structure of the resulting SKILL.md

The canonical skeleton is `templates/SKILL.md.tmpl` (render its `{{placeholders}}` from the scan + the user's answers). It must keep context lightweight, so it only contains:

1. Frontmatter: `name`, a generous `description` (triggers), plus `status`, `stack`, `default_branch`, `last_scanned`.
2. Identity (1–2 lines): what it does, type, owner, status — **human, outside the wrapper**.
3. **Context files table** — the index of every complementary doc, each tagged `auto` or `human`, with a **"Start here when…" entry hint per row**, the suggested L1–L4 reading order, and a **routing-by-task-type table** (endpoint work → api-surface+conventions+testing; shared-surface work → usage-map FIRST; auth → security+tech-debt; …). If the project has an execution brain, a "Planned work" pointer routes task IDs to `<ai-brain>/tasks/<ID>.md` before this map.
4. The wrapped **auto block**: stack one-liner, high-level tree, entry-points summary, an "at a glance" line (API/data/config/tests), conventions + glossary shortlists.
5. **Related Skills** (optional) — links to sibling/`client-context-*` skills; human, outside the wrapper. Omit if none.
6. **Rules For Claude** — lazy loading, verify-before-touch, respect conventions/human-first zones, auto-vs-human files, refresh-when-stale.

Never inline per-folder or per-section detail into the SKILL.md — that defeats the lazy-loading.

---

## Principles

- **Strict lazy-loading:** the resulting SKILL.md must be short (< 200 lines). All the weight goes into the complementary files.
- **Auto vs human:** `auto` files are scan-derived, wrapped in `<!-- auto-generated -->`, and rewritten on every scan. `human` files (`business-flows.md`, `security.md`, `tech-debt.md`) are authored once and **preserved** on refresh. Never hand-edit an `auto` file; never let a re-scan clobber a `human` one.
- **Accuracy over completeness:** for semantic sections, write `<!-- TODO: needs manual authoring -->` rather than inventing. Omit sections that don't apply (no DB → no data section) instead of leaving empty scaffolding.
- **Never leak secrets:** `config-env.md` lists variable **names only** — no values, ever.
- **Useful short descriptions:** each folder/entity gets 1 line answering "what lives here and why would I care?". Nothing generic like "source code folder".
- **Generous triggers:** the resulting skill's `description` must include the project name, aliases, base paths, key module names — anything the user might mention.
- **Stack-agnostic:** supports Node/TS, PHP, Python, Go, Rust, Ruby and any mix; degrade gracefully when a detector finds nothing.
- **Living, not fossilized:** re-runnable as the project evolves — refresh mode (STEP 4.5) updates `auto` files and `last_scanned` while preserving `human` ones; the `--update` delta mode makes per-wave freshness cheap enough to be routine.
- **Impact is a lookup, not a re-derivation:** `usage-map.md` exists so that touching a shared surface starts with "who consumes this?" answered from the map (then re-censused cheaply), never re-derived with exploratory greps.
