---
name: dependency-renovate
description: >
  Triggers on 'renueva las dependencias', 'actualiza las dependencias', 'update dependencies',
  'bump dependencies', 'upgrade dependencies', 'dependency audit', 'security advisories',
  'paquetes desactualizados', 'outdated packages'. Renews the dependencies of one code project
  on demand: app packages (npm, pnpm; pip and composer when present), runtimes and toolchain
  (.nvmrc, engines, packageManager, TypeScript, framework majors) and CI or infra pins (CI
  images, Dockerfile FROM, CI action versions, Supabase CLI). A deterministic deps-check plans
  the run; one Sonnet executor ships ONE verified MR with every patch and minor bump (build,
  typecheck, lint, tests, CI gates, before/after visual smoke), one Opus executor per major
  ships its own stacked MR with migration notes, an Opus auditor gates before handover, and
  Claude never merges. Each run appends one entry to the dependency changelog and refreshes
  dependencies.md of the context skill. An audit or advisory request alone gets a read-only digest.
compatibility: >
  Python 3 (stdlib) for deps-check; Node 20+ with playwright-core and Chrome for deps-smoke;
  glab (authenticated) for MRs.
---

# dependency-renovate

## Purpose

Renews the dependencies of ONE code project on demand, one project per clean session, and leaves the result reviewable: one MR with every
patch and minor bump, one stacked MR per major, one changelog entry and a refreshed `dependencies.md`. `deps-check` plans the run and renders
the changelog, the MR bodies and the context file; `deps-smoke` shoots and diffs the routes; agents only do what mutates the repo or needs
judgement. The skill never touches the tooling of the machine (brew, nvm installs, global npm): runtimes and tool packages come back as
`Para ti` lines.

## If you are the main session

`{{skill_dir}}` = this skill's folder · `<repo>` = the project root · `<S>` = the scratch run dir · `<context>` = the project's
`code-project-context-*` skill. `deps-check` and `deps-smoke` are the plugin `bin/` launchers: run them bare (nothing before them). Without
the plugin: `python3 {{skill_dir}}/scripts/deps_check.py` and `node {{skill_dir}}/scripts/deps_smoke.mjs`. Detail of every phase:
`references/flow.md`.

**Only `security advisories` or `dependency audit` asked?** That is a read-only digest: `deps-check plan <repo>` alone (no `--write`, no
scratch, 0 agents), report its ADVISORIES, HOLDS, NEVER-AUTO and `Para ti` lines, stop. The phases below start only when the owner asks for
the fix.

0. **Preflight** (0 agents): `deps-check preflight <repo> [--context <context>] [--expect-email <addr>]` must end `PREFLIGHT: ready`.
   Every blocker prints one `Para ti:` line with the owner command; ask the missing values (expected identity, `@reviewer-handle`, smoke
   routes) in ONE AskUserQuestion round and run it again. Read `dependencies.md` once if it exists.
1. **Plan** (0 agents): `deps-check plan <repo> --context <context> --scratch <S> --write` gives the digest and `<S>/plan.json`.
   `DEPS: current` ends the run (no MR, no changelog entry); otherwise confirm the waves and keep `para_ti`.
2. **Patch + minor** (1 Sonnet executor, `templates/patch-minor-brief.md`): baseline, bumps, lockfile, verify, smoke before and after,
   changelog, commit, push with `-o ci.skip`, Draft MR.
3. **Majors** (1 Opus executor per family, one after another, `templates/major-brief.md`): a linear stack; each branch starts from the
   previous wave's branch and its Draft MR targets it. Migration notes land in `<S>/notes/`.
4. **Changelog check** (0 agents): `deps-check changelog <repo> --plan <S>/plan.json --check` on the tip branch → `CHANGELOG: ok`.
5. **Context refresh** (1 Sonnet executor, `templates/context-brief.md`): `dependencies.md`, its index line, a patch bump of the context
   plugin, docs-repo push. It returns `PLUGIN: <p>@<mk> a → b`; then run `claude plugin marketplace update <mk>` and
   `claude plugin update <p>@<mk>`.
6. **Gate** (1 Opus auditor, `templates/auditor-brief.md`): `ship` or `fix-first`. Findings go back by `SendMessage`; a fix on wave N
   is merged up the stack; one re-audit at most.
7. **Handover**: `glab mr update <iid> --ready` per MR in merge order, the PNGs of changed routes with `SendUserFile`, the `Para ti`
   lines. MRs are named by iid; there is no links block.

Modes: **dry run** (`dry run`, `sin push`): phases 0-6 with no push and no MR, branches stay local · **open run** (MRs labelled
`dependencies` are still open): stop and ask the Reviewer to merge or close them first.

## Roles by tier

| Role | Agent | Model | Does | Never |
|---|---|---|---|---|
| Main session | none | top | `deps-check preflight/plan/status`, decides, briefs, reads RETURNs, marks MRs ready after `ship`, handover | bumps, reads the repo in bulk, merges, pushes |
| Patch+minor executor | `adcm-toolkits:executor` | sonnet | baseline, bumps, lockfile, verify, smoke, changelog, commit, push, Draft MR | edits source code, touches never-auto or held packages, schedules a merge, merges |
| Major executor (one per family) | `adcm-toolkits:executor` + `model: opus` | opus | migration research, minimal code change, verify, notes, stacked branch, Draft MR | other packages, refactors, human-first zones |
| Context executor | `adcm-toolkits:executor` | sonnet | `dependencies.md`, index line, plugin patch bump, docs-repo commit and push | the code repo |
| Gate | `adcm-toolkits:auditor` | opus | the gate before handover | edits |

Budget per run: 3 + k agents (k = majors this run, cap 3), Opus = k + 1. A fix loop uses `SendMessage` (0 agents); when `SendMessage`
cannot resume a finished executor, a NEW executor takes the fix (3 + k + 1). No `adcm-toolkits:*` types in the session:
`Agent(subagent_type: "general-purpose", model: "<tier>")` with the same brief.

## Hard rules

- **Claude never merges**, never passes `--auto-merge` to `glab mr create` (the merge-guard hook denies it on every `glab mr` form), never
  pushes to the default branch. The Reviewer merges; a new run starts only when no dependency MR is left open.
- **Identity**: `deps-check preflight` must say identity ok (its `IDENTITY` line ends `→ ok`) before any commit and again before each
  one. The skill NEVER changes `user.email`: on a mismatch it hands the owner the `git config user.email` command in a `Para ti` line.
- Never-auto packages (`node`, `npm`, `pnpm`, `yarn`, `corepack`, `bun`, `deno` as dependencies) and runtime majors without a deploy
  runtime declared in the repo are human decisions: a `Para ti` line, never a bump.
- `dependencies.md` is read first; the repo is never re-scanned and no Explore or researcher agent reads the code to learn the
  dependencies. The only code reading is the major executor's `git grep` of the package it migrates.
- One run in flight per repo: open `dependencies` MRs block a new run.
- Verify locally first, then push with `-o ci.skip` and open `glab mr create --draft`: one pipeline per MR at creation. An MR stays
  Draft until the auditor says `ship`.
- Screenshots and logs stay in `<S>`, never in the MR or the repo. Never print `.npmrc` or `.env` values.
- Public examples use Acme, `example.com` and `@reviewer-handle`.
- Tiers, the explicit `model` on every call and the Brief format of the briefs:
  `${CLAUDE_PLUGIN_ROOT}/skills/execution-prompt-architect/references/orchestrator-rule.md`.

## Files

`references/flow.md` (phases 0-7, modes, budget, handover) · `references/policy.md` (the `## Policy` section of `dependencies.md`,
built-ins, precedence) · `templates/{patch-minor-brief,major-brief,auditor-brief,context-brief}.md` (the four agent briefs) ·
`templates/{changelog-entry,mr-description}.md.tmpl` (rendered by `deps-check`) ·
`scripts/{deps_check.py,deps-check-selftest.py,deps_smoke.mjs,deps-smoke-selftest.py}` · `fixtures/npm-basic/` (generic Acme project of the
selftests) · launchers `bin/deps-check`, `bin/deps-smoke`. Sibling dependency: the `code-project-context-generator` skill
(`scripts/dependency_manifest.py`, `templates/dependencies.md.tmpl`).
