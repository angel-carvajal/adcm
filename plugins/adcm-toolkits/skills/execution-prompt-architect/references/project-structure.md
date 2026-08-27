# Project container structure (the standard layout)

The canonical filesystem layout every generated artifact (ai-brain, context skills,
marketplaces) must respect. Read this BEFORE deciding where to write anything. If the
user's existing layout differs, their layout wins — but when creating a NEW project,
this is the default, applied without asking.

## The container

```
~/<project>/                 ← CONTAINER — NOT a git repo, NO loose files at this level
├── ai-brain/                ← own git repo — ALL documentation lives here:
│   ├── README.md            ←   documents THIS whole container layout (versioned here)
│   ├── docs/                ←   product docs (spec, plan, ADRs/decisions, backlog, …)
│   └── …                    ←   the six execution documents + visuals (plans/prompts html)
├── ai/                      ← plain folder (no git of its own)
│   ├── <slug>-{ai|ia}-admin/    ← own git repo — private plugin marketplace (business context, council)
│   └── <slug>-{ai|ia}-common/   ← own git repo — operational/engineering plugins (optional)
└── projects/                ← plain grouping folder (no git of its own)
    ├── <project-a>/         ← own git repo — one engineering project
    └── <project-b>/         ← own git repo — another engineering project
```

Some containers use a different grouping name (`p-engineering/`, `engineering/`) or —
in single-app businesses — a directly-named repo at container level (e.g. `web/`).
`projects/` is the default for new containers. **Git lives PER project, never at the
grouping-folder or container level.**

## Rules

1. **The container is never a git repo** and carries no loose files — a root README
   would be unversioned; the layout documentation lives in `ai-brain/README.md`, and
   the project's `code-project-context-*` skill (lazy-loading) is what routes sessions
   through the structure.
2. **ALL documentation lives in `ai-brain/`** — execution documents, product
   spec/plan/decisions/backlog, visuals, logbook. Code repos carry only code plus
   their operational `CLAUDE.md`/`README.md`; those reference the docs via
   `ai-brain/…` relative paths.
3. **Every major subfolder is its own git repo** (local-only at first; remotes live in
   a per-project GitLab/GitHub group when they exist, marketplaces under an `ai/` or
   `ia/` subgroup).
4. **Each engineering project gets a gitignored symlink to the brain**:
   `ln -s ../../ai-brain ai-brain` from the project root (depth matches nesting). This
   keeps relative paths (`ai-brain/execute.md`, `ai-brain/docs/SPEC.md`) resolving
   locally in build sessions, while the brain versions independently. Doc changes made
   through the symlink are committed in the **ai-brain repo**, never in the code repo.
5. **Execution sessions start in the specific project repo**
   (`<container>/projects/<project>/`), not in the container. Wave prompts must name
   that path explicitly.
6. **Marketplaces live under `<container>/ai/`**, one repo per marketplace, each with
   `.claude-plugin/marketplace.json` + `plugins/<plugin>/skills/<skill>/`. Naming:
   `<slug>-{ai|ia}-admin` for business context/leadership, `<slug>-{ai|ia}-common` for
   operational plugins. Marketplace registration lives in the profile's Claude
   settings (`extraKnownMarketplaces`/`enabledPlugins`), never in the container.
7. **`ai-brain/README.md` is mandatory** and carries: the container table
   (`| Folder | What it is | Git |`), the doc map, the symlink setup line, a status line
   pointing at the task tracker, and disambiguation against sibling
   projects/businesses.
8. **The logbook commits in `ai-brain/`**, not in code MRs: closing a wave touches two
   repos (code + brain) and, when facts changed, a third (the marketplace, with a
   plugin version bump). A new engineering project = a new folder in `projects/` with
   its own git and its own symlink.
