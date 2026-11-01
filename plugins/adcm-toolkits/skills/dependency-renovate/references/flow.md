# Run flow

Read by the main session when it runs the skill. `<repo>` = the project root · `<S>` = the scratch run dir (`--scratch`; default
`$TMPDIR/deps-renovate/<repo>/<run-id>`, `run-id = <date>-<sha7 of the base>`) · `<context>` = the project's `code-project-context-*` skill ·
`<default>` = the default branch · `{{skill_dir}}` = this skill's folder.

`<S>` holds `plan.json`, `logs/`, `smoke/{before,before-2,after-<wave>,diff-<wave>}`, `mr/<wave>.md` and `notes/<family>.md`. It is created
0700 (a scratch dir owned by another user or writable by group or others is refused) and never enters the repo or an MR.

Every `deps-check` and `deps-smoke` command prints at most 40 lines and ends with its verdict line; exit 64 is a usage error. Launchers run
bare; without the plugin use `python3 {{skill_dir}}/scripts/deps_check.py` and `node {{skill_dir}}/scripts/deps_smoke.mjs`.

## Filling the briefs

The main session fills the `{{placeholders}}` of the four briefs in `templates/` from `<S>/plan.json`; the agents never re-derive them.

| Placeholder | Source |
|---|---|
| `{{repo}}` `{{default_branch}}` `{{run_id}}` `{{plan}}` `{{scratch}}` | the repo path · `git.default_branch` · `<date>-<sha7 of git.base>` · `<S>/plan.json` · `<S>` |
| `{{branch}}` `{{base_branch}}` `{{commands}}` `{{edits}}` `{{migration_refs}}` | the wave in `waves[]`: `branch`, `base`, `commands` (`cwd` + `run`; every token is already shell-quoted, run them as given), `edits` (`file`, `key`, `from`, `to`), `migration_refs` |
| `{{family}}` `{{from}}` `{{to}}` `{{wave_id}}` `{{wave_slug}}` `{{previous_wave}}` | a major wave: the family, `from_to`, `major:<family>`, its slug (`major-<family>`, as in `after-<slug>`, `diff-<slug>`, `<S>/mr/<slug>.md`), the slug of the wave before it (`patch-minor` for the first) |
| `{{mr_body}}` `{{merge_order}}` | `<S>/mr/<wave_slug>.md` · `MR !a → !b → !c` |
| `{{env_prefix}}` | `env.path_prefix` plus the `env.corepack` pairs: the pinned Node first on PATH for every install, build and test command |
| `{{verify}}` | `verification` (build, typecheck, lint, test, e2e, the `ci` steps) with the Policy overrides; `n/a` steps are skipped and a placeholder test script is never run |
| `{{routes}}` `{{base_url}}` `{{serve_cmd}}` `{{ready_url}}` `{{port}}` `{{node_pin}}` | `smoke.routes` · the Delivery `Server` row of `dependencies.md` (start command, port, ready route) · `smoke.node_pin` |
| `{{push_opts}}` | `-o ci.skip` when `ci.mr_pipelines` is true, else empty |
| `{{reviewer}}` `{{identity}}` | `context.reviewer.handle` · `context.expected_identity` |
| `{{context_skill}}` `{{context_file}}` `{{consent}}` | the context skill folder · the path of its `dependencies.md` (`none` when absent) · `yes` when the owner agreed to create the file |
| `{{changelog_path}}` | the Delivery `Changelog`, else `docs/dependencies/CHANGELOG.md` |
| `{{branches}}` `{{tip}}` `{{changed_routes}}` | the wave branches in merge order · the last of them · the `changed` and `resized` routes of every `diff.json` with their PNG paths |
| `{{dry_run}}` | `yes` for a dry run, else `no` |

## Modes

- **Live run** (default): every phase below.
- **Dry run** (`dry run`, `sin push`): phases 0-6 with no push and no MR; every brief gets `{{dry_run}}` = `yes`.
  - Phases 2 and 3 commit on the local `deps/*` branches and stop before the push; the branches are kept.
  - Phase 5 renders in scratch: `mkdir -p <S>/ctx`, copy the current `dependencies.md` into it when one exists, then run
    `deps-check context <repo> --context <S>/ctx --plan <S>/plan.json --write`. No index line, no plugin bump, no commit, no push, no
    `claude plugin update`.
  - Phase 6: the auditor skips MR, pipeline and label checks and reviews the local branches and `git log --format='%ae %ce' <default>..<tip>`
    instead; `git ls-remote --heads origin 'deps/*'` stays empty.
  - Phase 7: no `--ready`; the handover lists one `git branch -D <branch>` per local branch for the owner.
- **Open run** (MRs labelled `dependencies` are still open): stop. `deps-check preflight` lists `open-run` when
  `glab mr list --label dependencies -F json` returns opened MRs. `deps-check status <repo>` shows each MR's head pipeline. `Para ti`: ask the
  Reviewer to merge or close them first. Rebasing open dependency branches is out of scope.
  Leftover `deps/*` branches are `review:` lines of preflight: local ones (delete them after a run) and remote ones without an MR.

## 0 · Preflight (0 agents, main session)

- Resolve the repo: the current directory when it is the named project, else the container's `projects/`, `p-engineering/` or
  `engineering/` folder; ask only when ambiguous.
- `deps-check preflight <repo> [--context <context>] [--expect-email <addr>]` ends `PREFLIGHT: ready` (exit 0), `PREFLIGHT: blocked(...)`
  (exit 1) or `PREFLIGHT: unparsed (...)` (exit 2: not a git repo, no manifest).
- Blockers: `identity` (the effective `user.email` differs from the expected address, given by `--expect-email` or the Delivery
  `Commit identity`; without an expected address a repo-local `user.email` counts as ok, a global or unset one blocks) · `reviewer` (no
  `@reviewer-handle` in the brain's `Reviewer` line nor in the Delivery list of `dependencies.md`) · `dirty` · `behind` (default branch
  behind origin) · `open-run` · `node-missing` (the pinned Node is not installed under nvm; the skill never installs runtimes) ·
  `external-missing` (a verification command needs a path outside the repo, such as a sibling checkout, that does not exist) ·
  `context-ambiguous` (pass `--context`) · `pm-mismatch` (`<pm> --version` differs from `packageManager`).
- Each blocker prints one `Para ti:` line with the exact owner command, for example `git -C <repo> config user.email dev@example.com`.
  The skill never runs it and never changes `user.email` or any git config: the owner does, with `!`.
- Missing values (expected identity, `@reviewer-handle`, smoke routes) are asked in ONE AskUserQuestion round, then preflight runs again.
  Identity is checked again before every commit.
- `dependencies.md` exists → read it once (Policy: Rules, Verification, Smoke, Delivery). The repo is never re-scanned.
- `deps-smoke doctor` must end `DOCTOR: ready` (Node 20+, playwright-core, Chrome); otherwise it is a `Para ti` line.
- The CONTEXT line may end `context: stale (base sha ≠ origin/<default>)`: the file records an older base, for example after the Reviewer
  merged the last run. `deps-check context <repo> --context <context> --if-merged --write` re-renders it only when the base sha moved
  (`CONTEXT: current` otherwise); phase 5 renders it again anyway.

## 1 · Plan (0 agents)

- `deps-check plan <repo> --context <context> --scratch <S> [--prioritize a,b] [--max-majors N] --write` prints the ≤40-line digest and writes
  `<S>/plan.json`; `--json` prints one object whose `text` is the list of the plain lines. It queries the registry, the advisories (bulk
  POST of the locked versions), the Node schedule, `glab mr list` and `git ls-remote`; `--offline` skips them and ends `DEPS: partial(offline)`.
- `DEPS: current` (exit 0) ends the run: no MR, no changelog entry. Exit 1 is needed or partial; `partial(<steps>)` names the steps that failed
  (network, glab): fix the cause or go on with the owner's consent.
- The owner's standing decisions apply: patch+minor is automatic; majors are automatic up to the cap (Delivery `Max majors per run`, else 3,
  or `--max-majors`); `--prioritize` orders majors right after the ones that close advisories. The main session confirms the waves and keeps
  `para_ti` for the handover.
- A package name or workspace path outside the npm, composer or path patterns is dropped from its wave with a `review:` line: it goes to `Para ti`.
- Smoke routes come from the Smoke table of `dependencies.md`; without one `/` alone, or with `--routes auto` `/` plus up to 3 static GET routes
  found by the cpcg scanner (the `code-project-context-generator` skill); `--routes none` disables smoke. Peer dependencies never get bump commands.
- Read-only digest (`security advisories`, `dependency audit`): run this command without `--write` and stop after reporting ADVISORIES, HOLDS,
  NEVER-AUTO and `Para ti`.

## 2 · Patch + minor wave (1 Sonnet executor, `templates/patch-minor-brief.md`)

`Agent(subagent_type: "adcm-toolkits:executor")` (sonnet), only when `waves[]` has a `patch-minor` wave. The executor:

1. `git switch <default>` with a clean tree. Baseline under `env.path_prefix`: frozen install (`npm ci`, `pnpm install --frozen-lockfile`),
   every verification step, e2e with the JSON reporter, and the smoke twice (`<S>/smoke/before`, `<S>/smoke/before-2`).
2. `git switch -c <wave.branch>`; apply `wave.commands` and `wave.edits` exactly; reinstall; a clean frozen install proves the lockfile.
3. Verify: build · typecheck · lint · test · CI steps · e2e with no NEW failure against the baseline · smoke after, then
   `deps-smoke diff <S>/smoke/before <S>/smoke/after-patch-minor --noise <S>/smoke/before-2 --out <S>/smoke/diff-patch-minor`.
4. Failure: bisect the wave (≤3 halvings), drop the culprit to `needs-code` or `held`, verify again. Never edit source code, a test or a
   deny-list to make a bump pass.
5. The changelog entry and the MR body, with the results of step 3:

   ```
   deps-check changelog <repo> --plan <S>/plan.json --wave patch-minor --verify build=pass --verify e2e="pass 24/24 (base 24/24)" --smoke <S>/smoke/diff-patch-minor/diff.json --write
   deps-check changelog <repo> --plan <S>/plan.json --wave patch-minor --verify build=pass --verify e2e="pass 24/24 (base 24/24)" --smoke <S>/smoke/diff-patch-minor/diff.json --format mr --write
   ```

   The entry is keyed by `run-id` (`<date>-<sha7>`); wave sub-sections merge idempotently, so a rerun rewrites only its own rows. The MR body
   lands in `<S>/mr/patch-minor.md`. `--verify`, `--smoke` and, for a major, `--notes` feed both outputs: without them the rows read
   `not recorded`.
6. Identity check (`deps-check preflight <repo>`), commit, then push and open the Draft MR. One pipeline per MR at creation; the MR stays
   Draft until the auditor says `ship`. `-o ci.skip` only when `ci.mr_pipelines`:

   ```
   git push -u origin <branch> -o ci.skip
   glab mr create --draft -s <branch> -b <default> -a @reviewer-handle --reviewer @reviewer-handle -l dependencies --remove-source-branch -y -t "<title>" -d "$(cat <S>/mr/patch-minor.md)"
   ```

e2e and every smoke shoot run in the background with a wait (a foreground Bash call is capped at 10 minutes). Before each, the port is
free: `lsof -iTCP:<port> -sTCP:LISTEN` prints nothing, on 127.0.0.1 and `::1`; a busy port is a STOP (the Playwright `webServer` would
reuse the other process).

### Visual smoke

`deps-smoke shoot --base http://localhost:3000 --routes /,/compare --out <S>/smoke/after-patch-minor --serve "npm start" --ready http://localhost:3000/ --env PORT=3000 --env HOST=127.0.0.1`

- The same command with `--out <S>/smoke/before`, then `<S>/smoke/before-2`, runs on `<default>` before the bump; the briefs add `--node-pin <ver>`
  (the plan's `smoke.node_pin`) to every shoot.
- The built-in shooter is the only one: never a project shot script (`--with`), because a bump of the project's Playwright changes its driver
  and before and after would not compare. Cookies for logged-in or consent-gated routes: `--cookie name=value`; dynamic regions:
  `--mask "/route=sel,sel"`; `--full` for full-page shots.
- `--ready` passes on a TCP accept plus an HTTP answer below 500. `--ready-status 2xx` demands a 2xx, `any` accepts any answer;
  `--ready-timeout` (default 120 s). Point it at a route that exists and answers without a backend (the home page); never a health route
  that depends on one.
- Most apps need `PORT` and `HOST` in their environment (`--env`). `--node-pin <ver>` puts the pinned Node first on the server's PATH;
  `--cwd` sets its directory. `SMOKE_CHANNEL` picks the Chrome channel (default `chrome`).
- The server runs in its own process group: `<out>/.serve.pid` names it, `<out>/.serve.log` keeps its output, the group is killed on every
  exit and a pidfile left by a run that died is reaped by the next shoot. A busy port exits 2.
- `deps-smoke diff` ends `SMOKE: same(n)` or lists `changed(/a 0.84%)`, `resized(/c)`, `missing(/d)` or `unstable(/e)` (exit 1), or
  `unparsed(/f)` for a PNG it cannot decode (exit 2). `unstable` is a route that differs from its own second shot (`before-2`): noise to mask,
  not a regression. The auditor looks only at `changed` and `resized` routes.

## 3 · Majors (one Opus executor per family, in turn, `templates/major-brief.md`)

`Agent(subagent_type: "adcm-toolkits:executor", model: "opus")`, one family at a time.

- Linear stack in the order of `waves[]`: each wave starts from its `wave.base` (the default branch for the first wave, the previous wave's
  branch for the rest) and its Draft MR targets that base. The MR body states `Merge order` and `Stacked on`.
- Baseline = the previous wave's after-state (its logs and `<S>/smoke/after-<previous>`); the smoke diffs against that set.
- Research: the official migration guide or CHANGELOG (`wave.migration_refs`), then `git grep` of the usages of the package. Notes of at most
  10 lines per change go to `<S>/notes/<family>.md`.
- Minimal code change for the API changes of the family only; the same DoD as phase 2;
  `deps-check changelog <repo> --plan <S>/plan.json --wave major:<family> --notes <S>/notes/<family>.md --verify build=pass --smoke <S>/smoke/diff-<slug>/diff.json --write`,
  then the same command with `--format mr`; commit; push; Draft MR.
- STOP when the change touches more than 15 files or a human-first zone listed in `security.md` of the context skill, or needs another
  package's major. The family becomes a `Para ti` line.
- Runtime majors (Node, `.nvmrc`, `engines`, CI image) are a wave only when the deploy runtime is declared in the repo (Dockerfile, CI
  deploy image, `engines` with engine-strict, platform config); otherwise a `Para ti` line.

## 4 · Changelog check (0 agents)

With the repo on the tip branch, where the last executor leaves it, `deps-check changelog <repo> --plan <S>/plan.json --check` must end `CHANGELOG: ok`. `mismatch(<names>)` (exit 1) sends the
wave back to its executor through `SendMessage`.

## 5 · Context refresh (1 Sonnet executor, `templates/context-brief.md`)

`Agent(subagent_type: "adcm-toolkits:executor")` (sonnet).

- The code repo is switched to `<default>` first, so the snapshot is the default branch:
  `deps-check context <repo> --context <context> --plan <S>/plan.json --write`. The file lands at the root of a flat skill or in
  `references/` of a custom layout. Its Policy section is written only for a NEW file, and a first creation needs the owner's consent. A file
  that records another repo is refused (exit 2) unless `--file dependencies-<repo>.md`.
- Without a context skill (`context: none`) there is nothing to attach the file to: the main session runs
  `deps-check context <repo> --plan <S>/plan.json --scratch <S> --write`, which renders `<S>/dependencies.md`, offers it to the owner in `Para ti`,
  and no executor runs.
- The snapshot says `<default>@<sha7>` and lists the run's open MRs under "Open dependency branches". After the Reviewer merges them,
  `preflight` reports `context: stale` and `deps-check context <repo> --context <context> --if-merged --write` re-renders it.
- One index line is added to the context `SKILL.md` if missing; that plugin gets a patch bump (without one `claude plugin update` does
  nothing); the identity of THAT repo is checked; its main is committed and pushed (a docs repo).
- RETURN `PLUGIN: <p>@<mk> a → b`. The main session then runs `claude plugin marketplace update <mk>` and `claude plugin update <p>@<mk>`
  (no CLI → hand both to the owner) and reminds `/reload-plugins` or a new session.
- Dry run: the scratch render of Modes; RETURN `PLUGIN: none (dry run)`.

## 6 · Auditor gate (1 Opus auditor, `templates/auditor-brief.md`)

`Agent(subagent_type: "adcm-toolkits:auditor")` (opus, read-only). Gate: only planned packages changed · lockfile in sync · no NEW failure
against the baseline · `changed` and `resized` smoke routes judged from the PNGs · notes match the code diff · `deps-check changelog --check`
→ ok · commit identity · Draft MRs assigned, labelled and stacked on the right branch · `deps-check status <repo>` with no failed,
conflicting or pipeline-less (`nopipeline(!n)`) MR · no secrets in diffs, MR bodies, notes or logs. Verdict `ship` or `fix-first`.

- `fix-first`: the findings go to the owning executor through `SendMessage` (0 agents). When `SendMessage` cannot resume it, a NEW executor
  gets the same brief plus the findings (3 + k + 1 agents).
- A fix in wave N is committed on branch N. Then, for each later wave up to the tip, in stack order: `git switch <branch> && git merge --no-ff <branch N>`,
  reinstall, verify again, `deps-check changelog <repo> --plan <S>/plan.json --wave <wave> --verify build=pass --write` (idempotent), push. This is a
  merge between wave branches, never into `<default>`, with no rebase and no force.
- A merge conflict in the changelog alone: run `deps-check changelog <repo> --wave <that wave> --plan <S>/plan.json --write` with that wave's
  fresh `--verify` values (without them the row reads `not recorded`) and `git add` the file; the entry is re-derived from the lockfile.
  Finish with `git commit --no-edit`.
- At most 1 re-audit, by `SendMessage` to the same auditor; it covers the whole stack. Whatever is still `fix-first` goes to the owner as
  `Para ti`.

## 7 · Handover

- Live run with verdict `ship`: `glab mr update <iid> --ready` per MR in merge order, after `deps-check status <repo>` shows no failed,
  conflicting or pipeline-less MR (`STATUS: ok(!a,!b)`). `STATUS: unparsed` (exit 2) means glab is missing, unauthenticated or cannot
  resolve the host (an SSH-alias remote may need `GITLAB_HOST` or `-R`): a `Para ti` line.
- The PNGs of changed routes (`diff-<slug>.png` and the after shots) go out with `SendUserFile`: sub-agents cannot.
- The final message names MRs by iid (no links block: no artifacts) and carries the `Para ti` lines:
  - merge order `MR !a → !b → !c`: each merge retargets the next MR and clears its head pipeline, so the Reviewer re-runs it;
  - the never-auto decisions and the runtime decision (EOL date, candidate LTS lines);
  - pending majors and suggested `hold-major` rows;
  - identity and reviewer follow-ups with their exact commands;
  - the deploy note: what changes at deploy (runtime, lockfile, build);
  - CI cost: about 3k+3 pipelines for k majors (one at each MR creation, one re-run per retarget, one on the default branch per merge, one for
    an audit fix) times the duration of the `guard` job, against the 400 minutes per month per namespace of GitLab Free;
  - after the merges: `deps-check context <repo> --context <context> --if-merged --write`;
  - dry run: one `git branch -D <branch>` per local branch.
- `<S>` is named in the message (plan, logs, shots) and left in place.

## Budget

3 + k agents: the patch+minor executor (Sonnet), k major executors (Opus, k ≤ 3), the context executor (Sonnet) and the auditor (Opus), so
Opus = k + 1. Fix loops and the re-audit use `SendMessage` (0 agents). A NEW executor, because `SendMessage` cannot resume a finished one,
counts in the budget (3 + k + 1); an auditor that cannot be resumed is replaced by a new one with the same gate and the fix list.
