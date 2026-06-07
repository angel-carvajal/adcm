---
name: code-project-context-generator
description: >
  Scans a code project, builds a structured map of its architecture, and generates
  an installable skill of the form `code-project-context:[project-name]` with lazy-loading
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

This skill guides the process of analyzing a code project and generating an installable context skill of the form `code-project-context:[project-name]`. The resulting skill is designed with **lazy-loading**: its SKILL.md loads only the high-level map (tree + short descriptions per folder + stack + entry points), and the details of each folder are read on-demand with Read when the working session requires them. This keeps context lightweight while still allowing deep dives where needed.

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

### STEP 1: Collect minimal metadata

Use AskUserQuestion to capture what the scanner cannot infer:

**Round 1 — Project identity:**

- What is the project called? (short name for the skill slug, e.g. `hub-plus`, `schools-backend`, `ancefoodtrailers-web`)
- Is there an internal/commercial name different from the repo name?
- What does the project do in one sentence? (business value, not tech)
- Is it your own project, a client project, open source, or experimental?

**Round 2 — Operational context (optional, if applicable):**

- Is there an associated client? (link it to an existing `client-context-*` if applicable)
- Is it frontend, backend, fullstack, mobile, CLI, library, infra?
- Does it have a deploy/live environment? (URLs, staging, prod)
- Is there relevant external documentation? (Notion, Confluence, remote README)

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
- `dependencies` — list of critical deps with version (Node, PHP, Python, Go, Rust)
- `entry_points` — scripts in package.json, artisan commands, main modules, Dockerfile CMDs, CI scripts
- `tree` — folder tree of the project with counts and sizes
- `folders` — each folder with path, file count, predominant types, and a tentative purpose hash-tag (routing, models, services, tests, config, docs, etc.)
- `configs` — configuration files found (`.env.example`, `docker-compose.yml`, CI, linters)
- `conventions` — detected hints (MVC, feature-based, monorepo, workspaces, etc.)
- `domain_terms` — terms that appear repeatedly in file/class names (glossary candidates)

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

### STEP 4: Generate the skill with lazy-loading

Build the output structure:

```
code-project-context-[project-name]/
├── SKILL.md                    # High-level index (ALWAYS loaded)
├── architecture.md             # Full tree + short descriptions (on-demand)
├── stack.md                    # Stack, deps, versions (on-demand)
├── entry-points.md             # How to start, routes, build/run/test (on-demand)
├── conventions.md              # Detected code patterns (on-demand)
├── glossary.md                 # Domain terms (on-demand)
└── folders/
    ├── [folder-1].md           # Detail of src/, app/, etc. (on-demand)
    ├── [folder-2].md
    └── ...
```

**Golden rule:** the SKILL.md must NEVER have all the details inline. It should only have:

1. Project identity (1 paragraph)
2. Stack in one line (e.g. `Node 20 • Next.js 14 • TypeScript • Prisma • PostgreSQL`)
3. High-level map (tree up to 2 levels with 1 line per folder)
4. Index of detailed files: "For details on X, read `architecture.md`. For the full stack, read `stack.md`. For the `src/api/` folder, read `folders/src-api.md`."
5. Rules for Claude on how to use this context

Use the templates in `templates/` (relative to the skill root) as a base. The templates include placeholders that are filled in with the scanner's data.

### STEP 5: Package and install

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

## Structure of the resulting SKILL.md (template)

The SKILL.md of the generated skill must follow this strict skeleton to keep context lightweight:

```markdown
---
name: code-project-context:[project-name]
description: >
  Loads the architecture context of the [Name] project. Loads only the high-level map — the
  details of each folder are read on-demand with Read from the complementary files in the
  same directory.
  Triggers when the user mentions '[project-name]', '[aliases]', [project-specific triggers].
---

# [Project Name] — Architecture Context

**What it does:** [1 sentence of business value]
**Type:** [frontend/backend/fullstack/mobile/CLI/library]
**Client/Owner:** [name or "own"]
**Status:** [active / maintenance / archived]

---

## Stack (one-liner)

[Language N.N] • [Framework N.N] • [Runtime] • [DB] • [other critical]

For full details: read `stack.md`.

---

## High-Level Map

```
project-root/
├── src/              — main source code
├── tests/            — test suites (unit + e2e)
├── docs/             — internal documentation
├── scripts/          — administrative tasks and CI helpers
├── config/           — per-environment configuration
└── [others]/         — [1 line]
```

For the full tree with depth: read `architecture.md`.
For details of a specific folder: read `folders/[name].md`.

---

## Entry Points (summary)

- **Start dev:** `[command]`
- **Build:** `[command]`
- **Tests:** `[command]`
- **Deploy:** [brief description]

For routes, APIs, and full flows: read `entry-points.md`.

---

## Key Conventions

- [1 line per convention: e.g. "Thin controllers, logic in services/"]
- [1 line: e.g. "Tests live next to the code in `*.test.ts`"]

For the full detail: read `conventions.md`.

---

## Domain Glossary (shortlist)

- **[Term 1]:** [1 line]
- **[Term 2]:** [1 line]

For the full glossary: read `glossary.md`.

---

## Rules For Claude

1. **Lazy loading:** Do NOT read all the complementary files at the start. Read only the ones the current task requires.
2. **Paths:** Before touching code, verify the real location with `Glob` or `Read`. The map is a reference, not absolute truth.
3. **Conventions:** Respect the detected conventions. If the code uses services/, don't create fat controllers.
4. **Danger zones:** [critical modules that require extra care — if applicable]
5. **Updates:** If you discover the map is out of date, suggest running `code-project-context-generator` again.
```

---

## Principles

- **Strict lazy-loading:** the resulting SKILL.md must be short (< 200 lines). All the weight goes into the complementary files.
- **Useful short descriptions:** each folder in the map must have 1 line that answers "what lives here and why would I care?". Nothing generic like "source code folder".
- **Generous triggers:** the description of the resulting skill must include the project name, aliases, base paths, key module names — anything the user might mention to bring up context.
- **Stack-agnostic:** the scanner detects the stack, but the skill's logic assumes none. It supports Node/TS, PHP, Python, Go, Rust and any mix.
- **No raw dump:** do not paste the raw scanner output into the skill. Everything goes through human (or Claude's) interpretation to produce useful short descriptions.
- **Living, not fossilized:** the skill should be easy to regenerate as the project evolves. Include at the end of the SKILL.md the date of the last scan and a hint on when to re-run.
