# PATCH+MINOR BRIEF (fill every {{...}} from plan.json as references/flow.md says; this file is the Agent prompt; dry_run is yes or no)
# Agent(subagent_type: "adcm-toolkits:executor") (sonnet). No such type in this session → Agent(subagent_type: "general-purpose", model: "sonnet") with the same brief.

TASK: Ship ONE verified Draft MR with every patch and minor bump of {{repo}}: wave `patch-minor` of {{plan}}, run {{run_id}}, branch {{branch}} from {{default_branch}}. dry_run: {{dry_run}}.
  Work inside {{repo}}. Prefix every install, build, test and smoke command with {{env_prefix}}. Reviewer {{reviewer}}; commit identity {{identity}}.

FILES: read {{plan}} and {{context_file}} (Policy: Verification, Smoke, Delivery). Edit only what the wave changes (manifests, lockfile, CI pins): {{commands}} · {{edits}}.
  Write logs to {{scratch}}/logs, shots to {{scratch}}/smoke, the MR body to {{scratch}}/mr/patch-minor.md, the changelog entry at {{changelog_path}}.
SKILLS: — (none to load)

DELIVERABLE (log every step under {{scratch}}/logs):
  1. `git switch {{default_branch}}` with a clean tree. Baseline: frozen install (`npm ci` or `pnpm install --frozen-lockfile`), {{verify}}, e2e (JSON reporter when the runner has one), SHOOT twice (--out {{scratch}}/smoke/before, then before-2).
  2. `git switch -c {{branch}}`; apply {{commands}} and {{edits}} exactly; reinstall; a clean frozen install proves the lockfile.
  3. Verify: {{verify}} pass or fail exactly as in the baseline, e2e shows no NEW failure; SHOOT --out {{scratch}}/smoke/after-patch-minor; then
     `deps-smoke diff {{scratch}}/smoke/before {{scratch}}/smoke/after-patch-minor --noise {{scratch}}/smoke/before-2 --out {{scratch}}/smoke/diff-patch-minor`.
  4. On a failure bisect the wave (≤3 halvings), move the culprit to needs-code or held, verify again.
  5. `deps-check changelog {{repo}} --plan {{plan}} --wave patch-minor --verify build=pass --verify e2e="pass n/n (base n/n)" --smoke {{scratch}}/smoke/diff-patch-minor/diff.json --write` (one `--verify step=result` per step run),
     then the same command plus `--format mr` (the MR body needs the same `--verify` and `--smoke`). Entries are keyed by run-id (<date>-<sha7>).
  6. `deps-check preflight {{repo}}` must still say identity ok; commit. dry_run yes → stop: branch kept, no push, no MR. Else `git push -u origin {{branch}} {{push_opts}}`, then
     `glab mr create --draft -s {{branch}} -b {{default_branch}} -a {{reviewer}} --reviewer {{reviewer}} -l dependencies --remove-source-branch -y -t "chore(deps): patch and minor bumps {{run_id}}" -d "$(cat {{scratch}}/mr/patch-minor.md)"`.
  SHOOT = `deps-smoke shoot --base {{base_url}} --routes {{routes}} --serve "{{serve_cmd}}" --ready {{ready_url}} --env PORT={{port}} --env HOST=127.0.0.1 --node-pin {{node_pin}} --out <dir>`.
  e2e and SHOOT run in the background and are awaited (a foreground Bash call is capped at 10 minutes). Before each, `lsof -iTCP:{{port}} -sTCP:LISTEN` prints nothing (127.0.0.1 and ::1).
  Fix loop (SendMessage): commit the fix here; then, for each later wave in order, `git switch <branch> && git merge --no-ff {{branch}}`, reinstall, verify again,
  `deps-check changelog {{repo}} --plan {{plan}} --wave <that wave> --verify build=pass --write`, push. A merge conflict in the changelog alone: run that changelog command, `git add` it, `git commit --no-edit`.

DOD-SLICE: {{verify}} → pass or the baseline failures; `deps-check changelog {{repo}} --plan {{plan}} --check` → `CHANGELOG: ok`; `deps-smoke diff` → `SMOKE: same(n)` or the changed routes in RETURN;
  `git log --format='%ae %ce' {{default_branch}}..{{branch}}` → only {{identity}}; live run: `glab mr view <iid> -F json` → draft true, assignee and reviewer {{reviewer}}, label dependencies.
STOP IF: identity is not ok · a bump needs a source-code edit · a new package with an install script · a deny-list hit after the bisect · the frozen install reports the lockfile out of sync · the port is busy · `deps/*` already exists on the remote.
FORBIDDEN: editing source code, tests or a deny-list to pass · never-auto or held packages · `--auto-merge`, `glab mr merge` · a push to {{default_branch}} · `--no-verify`, `--force` · changing `user.email` · printing `.npmrc` or `.env` values · shots or logs in the repo or the MR.
  Also forbidden: bumping a never-auto package (`node`, `npm`, `pnpm`, `yarn`, `corepack`, `bun`, `deno` as dependencies): it is a `Para ti` line · pushing without `-o ci.skip` where the repo runs MR pipelines ({{push_opts}}), so the only pipeline is the one MR creation starts · marking the MR ready: it stays Draft until the auditor says `ship`.
RETURN: DIFF · DOD-SLICE · ESCALATION · `WAVE: applied n · dropped [name: reason]` · `SMOKE: <last line of deps-smoke diff>` · `MR: !iid {{branch}} sha7` (dry run: `branch sha7`) · `LOGS: {{scratch}}/logs`.
