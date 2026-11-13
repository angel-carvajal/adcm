# dependency-renovate

Renews the dependencies of one code project on demand and leaves the result reviewable: one MR with every patch and minor bump, one stacked
MR per major, one changelog entry and a refreshed `dependencies.md`. The Reviewer merges; Claude never does.

## What it does

- **Plans** with a deterministic CLI, `deps-check`: outdated packages, advisories, Node LTS status, the project policy, holds, never-auto
  packages and the decisions only the owner can take. The `dependencies.md` of the project's context skill is read first; no agent reads the
  code to learn the dependencies.
- **Ships** one verified MR with every patch and minor bump (build, typecheck, lint, tests, CI gates and a before/after visual smoke by
  `deps-smoke`), written by one Sonnet executor, and one MR per major with migration notes, written by one Opus executor each, as a linear
  stack of Draft MRs.
- **Gates**: an Opus auditor says `ship` or `fix-first` before the MRs are marked ready.
- **Hands over** the merge order and the `Para ti` list: runtime and never-auto decisions, pending majors, identity and reviewer follow-ups.

## Install

It ships in the `adcm-toolkits` plugin of the `adcm` marketplace: nothing extra to install once that plugin is enabled. To update it:

```
claude plugin marketplace update adcm
claude plugin update adcm-toolkits@adcm
```

Then restart the session or run `/reload-plugins`.

## Use

- Ask for it: `renueva las dependencias de <project>`, `actualiza las dependencias`, `update dependencies`, `bump dependencies`,
  `upgrade dependencies`, `paquetes desactualizados`, `outdated packages`; or run `/adcm-toolkits:dependency-renovate`.
- `security advisories` and `dependency audit` alone get a read-only digest (`deps-check plan`): no agents, no branch, no MR. Ask for the
  fix to start a run.
- `dry run` (or `sin push`) after the request runs everything except the push and the MR: the branches stay local and the handover lists
  their cleanup.
- One project per clean session. The skill stops while MRs labelled `dependencies` are still open.

## What one run leaves behind

- 1 Draft MR with every patch and minor bump, then up to 3 major MRs stacked on it (each targets the previous wave's branch); all are marked
  ready, in merge order, only after the auditor says `ship`.
- One entry in the dependency changelog (`docs/dependencies/CHANGELOG.md` unless the project's Delivery list says otherwise).
- A refreshed `dependencies.md` in the context skill of the project, and a patch bump of that plugin.
- A scratch folder (plan, logs, screenshots, notes) outside the repo. Nothing of it is committed.

## Requirements

- Python 3 (standard library) for `deps-check`.
- Node 20+, `playwright-core` 1.61+ and Chrome for `deps-smoke`. `playwright-core` is found through `PW_CORE_DIR`, then the npx cache, then the
  project's `node_modules`; `deps-smoke doctor` reports what is missing and how to fix it.
- `glab` authenticated for the forge host of the project.
- The git identity set in the repo (`git config user.email`); the skill never changes it and hands the command to the owner.
- The project's pinned Node installed under nvm; the skill never installs runtimes or touches the tooling of the machine.

## Launchers

`scripts/launchers/deps-check` and `scripts/launchers/deps-smoke` are on the Bash PATH through the plugin's SessionStart hook. Each command prints at most 40 lines and ends with a
verdict line; 64 is a usage error in every subcommand.

| `deps-check` | Exit 0 | Exit 1 | Exit 2 |
|---|---|---|---|
| `preflight` | ready | blocked | unparsed (not a git repo, no manifest) |
| `plan` | current | needed or partial | unparsed |
| `changelog` | ok, written or would write | mismatch (`--check`) or partial | unparsed |
| `context` | current or written | would write | unparsed, or the different-repo guard |
| `status` | none or all green | running, failed, conflict or no pipeline | glab missing or failing |

| `deps-smoke` | Exit 0 | Exit 1 | Exit 2 |
|---|---|---|---|
| `doctor` | `DOCTOR: ready` | | `DOCTOR: not ready` |
| `shoot` | every route shot | a route failed | environment: Node, playwright-core, Chrome, busy port, server never ready |
| `diff` | every route `same` | changed, resized, missing or unstable | unsupported PNG |

## What it will not do

Merge, schedule a merge, or push to the default branch; change `user.email`; bump `node`, `npm`, `pnpm`, `yarn`, `corepack`, `bun` or `deno`
as dependencies; decide a runtime major the repo does not declare; edit source code for a patch or minor bump; put screenshots or logs in an
MR; print `.npmrc` or `.env` values.

## Structure

- `SKILL.md`: what the main session does, the roles and the hard rules.
- `references/flow.md`: phases 0-7, dry-run and open-run modes, the budget, the handover.
- `references/policy.md`: the `## Policy` section of `dependencies.md`, the built-ins and the precedence.
- `templates/`: the four agent briefs, and the changelog entry and MR description rendered by `deps-check`.
- `scripts/`: `deps_check.py` and `deps_smoke.mjs` with their selftests.
- `fixtures/npm-basic/`: a generic Acme project for the selftests.
- Sibling skill `code-project-context-generator`: `scripts/dependency_manifest.py` and `templates/dependencies.md.tmpl`.

MIT licensed.
