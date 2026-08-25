# Project container structure (the standard layout)

The canonical filesystem layout every generated artifact (ai-brain, context skills,
marketplaces) must respect. Read this BEFORE deciding where to write anything. If the
user's existing layout differs, their layout wins — but when creating a NEW project,
this is the default, applied without asking.

## The container

```
~/<project>/                 ← CONTAINER — NOT a git repo, NO loose files at this level
├── ai-brain/                ← own git repo — the execution brain (the six documents)
│   └── README.md            ← documents THIS whole container layout (it is versioned here)
├── ai/                      ← plain folder (no git of its own)
│   ├── <slug>-{ai|ia}-admin/    ← own git repo — private plugin marketplace (business context, council)
│   └── <slug>-{ai|ia}-common/   ← own git repo — operational/engineering plugins (optional)
└── app/                     ← own git repo — the code (single-repo projects)
```

Multi-repo holdings replace `app/` with either several sibling repos or a plain
grouping folder (`projects/`, `p-engineering/`, `engineering/`) holding one git repo
per app. Everything else stays identical.

## Rules

1. **The container is never a git repo** and carries no loose files — a root README
   would be unversioned; the layout documentation lives in `ai-brain/README.md`, and
   the project's `code-project-context-*` skill (lazy-loading) is what routes sessions
   through the structure.
2. **Every major subfolder is its own git repo** (local-only at first; remotes live in
   a per-project GitLab/GitHub group when they exist, marketplaces under an `ai/` or
   `ia/` subgroup).
3. **`ai-brain/` lives at CONTAINER level, never inside the code repo.** The code repo
   references it through a **gitignored symlink**: `ln -s ../ai-brain ai-brain` from
   the code repo root (adjust depth if the code repo is nested, e.g. `../../ai-brain`).
   This keeps relative paths (`ai-brain/execute.md`, `ai-brain/detailed-plan.md`)
   resolving locally in build sessions, while the brain versions independently.
4. **Execution sessions start in the code repo** (`app/` or the specific app repo),
   not in the container. Wave prompts must name that path explicitly.
5. **Marketplaces live under `<container>/ai/`**, one repo per marketplace, each with
   `.claude-plugin/marketplace.json` + `plugins/<plugin>/skills/<skill>/`. Naming:
   `<slug>-{ai|ia}-admin` for business context/directivos, `<slug>-{ai|ia}-common` for
   operational plugins. Marketplace registration lives in the profile's Claude
   settings (`extraKnownMarketplaces`/`enabledPlugins`), never in the container.
6. **`ai-brain/README.md` is mandatory** and carries: the container table
   (`| Carpeta | Qué es | Git |`), the doc map, the symlink setup line, a status line
   pointing at `task.md`, and disambiguation against sibling projects/businesses.
7. **The bitácora commits in `ai-brain/`**, not in code MRs: closing a wave touches
   two repos (code + brain) and, when facts changed, a third (the marketplace, with a
   plugin version bump).

## Reference implementations (on Angel's machine)

`~/alpely` (the most mature: `ai-brain/` + `ai/` + `projects/alpely` + documented
symlink), `~/ancefoodtrailers`, `~/adcm` (uses `brain/`), `~/adcmcorps`,
`~/forja-trailers`, `~/adcm-ledger` (single-repo variant with `app/`).
