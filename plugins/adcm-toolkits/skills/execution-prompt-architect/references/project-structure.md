# Project container structure (the standard layout)

The canonical filesystem layout every generated artifact (ai-brain, context skills,
marketplaces) must respect. Read this BEFORE deciding where to write anything. If the
user's existing layout differs, their layout wins — but when creating a NEW project,
this is the default, applied without asking.

## The container

Containers live in one of two places, by relationship: **Own ventures** →
`~/<venture>/` (one folder per venture the owner runs). **Client
work** → `~/clientes_projects/<client>/`, one container per client, same internal
layout. A brand-new client is registered the same day as a `directory` marketplace
(rule 10) before any remote exists.

```
~/<project>/                 ← CONTAINER — NOT a git repo, NO loose files at this level
├── ai/                      ← EVERYTHING AI lives here (plain folder, no git of its own)
│   ├── ai-brain/            ← own git repo — ALL documentation lives here:
│   │   ├── README.md        ←   documents THIS whole container layout (versioned here)
│   │   ├── docs/            ←   product docs (spec, plan, ADRs/decisions, backlog, …)
│   │   ├── modules/<mod>/   ←   lazy per-module doc (its own six-doc family) when the
│   │   │                        container hosts several modules/initiatives
│   │   └── …                ←   the six execution documents + visuals (plans/prompts html)
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

## Where ai-brain may live (and why it matters)

Canonical: `<container>/ai/ai-brain/`. Two accepted alternates are LIVE in
production:

- `<container>/ai-brain/` at the container root (a venture whose brain sits at `~/<venture>/ai-brain/` and whose
  with the code under `p-engineering/` instead of `projects/`).
- `docs/ai-brain/` plus a symlink `ai/ai-brain -> ../docs/ai-brain` (a venture that keeps its docs under `docs/`), where the
  symlink is MANDATORY.

Why it matters: the Stop hook `templates/artifact-guard.py` discovers the artifacts
registry by walking UP from cwd to `$HOME` looking for exactly
`ai/ai-brain/artifacts.json` or `ai-brain/artifacts.json` (`REGISTRY_CANDIDATES`). Any
other layout is invisible to it, and the freshness/links enforcement silently becomes
a no-op. A symlink satisfies the check — create it in the SAME session that creates
`artifacts.json`.

## Rules

1. **The container is never a git repo** and carries no loose files — a root README
   would be unversioned; the layout documentation lives in `ai-brain/README.md`, and
   the project's `code-project-context-*` skill (lazy-loading) is what routes sessions
   through the structure.
2. **ALL documentation lives in `ai/ai-brain/`** — execution documents, product
   spec/plan/decisions/backlog, visuals, logbook. Code repos carry only code plus
   their operational `CLAUDE.md`/`README.md`; those reference the docs via
   `ai-brain/…` relative paths.
3. **Every major repo folder is its own git repo** (`ai/` and `projects/` themselves are plain grouping folders) (local-only at first; remotes live in
   a per-project GitLab/GitHub group when they exist, marketplaces under an `ai/` or
   `ia/` subgroup).
4. **Each engineering project gets a gitignored symlink to the brain**:
   `ln -s ../../ai/ai-brain ai-brain` from the project root — or, when the project is a
   MODULE with lazy doc, `ln -s ../../ai/ai-brain/modules/<mod> ai-brain` (depth
   matches nesting). This
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
   Fuller naming: `<venture>-{ai|ia}-admin` (business context / leadership), `-common`
   (operational/engineering), plus per-venture variants already in use (`-commercial`,
   `-platform`, `-academic`) when a venture's marketplace split warrants it — one repo
   per marketplace either way.
7. **`ai-brain/README.md` is mandatory** and carries: the container table
   (`| Folder | What it is | Git |`), the doc map, the symlink setup line, a status line
   pointing at the task tracker, and disambiguation against sibling
   projects/businesses.
8. **The logbook commits in `ai-brain/`**, not in code MRs: closing a wave touches two
   repos (code + brain) and, when facts changed, a third (the marketplace, with a
   plugin version bump). A new engineering project = a new folder in `projects/` with
   its own git and its own symlink.
9. **Document names follow the venture's working language**: Spanish-speaking
   ventures deploy `propuesta-ejecutiva.md, plan-maestro.md, plan-detallado.md,
   plan-timeframe.md, task.md, execute.md, plans.html, prompts.html`; `task.md` and
   `execute.md` keep their English names in BOTH languages (addressed by tooling: the
   `artifact-guard` `close_markers` default, and every cross-reference in the
   prompts). The English set (`executive-proposal.md, master-plan.md,
   detailed-plan.md, timeframe-plan.md`) is the alternative. Whichever set is chosen
   is FIXED per container, recorded in `ai-brain/README.md`, and
   `artifacts.json.close_markers` names the real third document (e.g.
   `["task.md","execute.md","plan-detallado.md"]`). Never rename an existing
   deployment.
10. **Day-0 marketplace registration is a `directory` source**: before a client
    container has a remote, register from the local path
    (`{"source":"directory","path":"<container>/ai/<slug>-ia-admin"}` in the
    profile's `extraKnownMarketplaces`, via `claude plugin marketplace add <path>` +
    `claude plugin install <plugin>@<marketplace>`); migrate to `git`/`github` when
    the remote exists. Registration lives in the profile's settings, never in the
    container.
