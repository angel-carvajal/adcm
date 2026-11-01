# MAJOR BRIEF (fill every {{...}} from plan.json as references/flow.md says; one brief per family, in stack order; this file is the Agent prompt; dry_run is yes or no)
# Agent(subagent_type: "adcm-toolkits:executor", model: "opus"). No such type in this session → Agent(subagent_type: "general-purpose", model: "opus") with the same brief.

TASK: Migrate {{family}} {{from}} → {{to}} in {{repo}} as ONE stacked Draft MR: wave {{wave_id}} of {{plan}}, run {{run_id}}, branch {{branch}} from {{base_branch}} (default branch {{default_branch}}). dry_run: {{dry_run}}.
  Work inside {{repo}}. Prefix every install, build, test and smoke command with {{env_prefix}}. Merge order {{merge_order}}. Reviewer {{reviewer}}; commit identity {{identity}}.

FILES: read {{plan}} (wave {{wave_id}}: commands, edits, migration_refs {{migration_refs}}), {{context_file}} and the human-first zones in `security.md` of the context skill.
  Edit the manifests and lockfile of the wave plus the source lines whose API changed in {{family}} (found with `git grep` of its usages); nothing for other packages.
  Write {{scratch}}/notes/{{family}}.md, logs under {{scratch}}/logs, shots under {{scratch}}/smoke and the MR body {{mr_body}}.
SKILLS: — (none to load)

DELIVERABLE (log every step under {{scratch}}/logs):
  1. `git switch {{base_branch}}`; the baseline is the previous wave's after-state (its logs and {{scratch}}/smoke/after-{{previous_wave}}). Then `git switch -c {{branch}}`.
  2. Research: the migration guide or CHANGELOG ({{migration_refs}}), then `git grep` of the usages. Notes, at most 10 lines per change, in {{scratch}}/notes/{{family}}.md.
  3. Apply {{commands}} and {{edits}}, make the minimal code change, reinstall, clean frozen install. DoD of the patch+minor wave: {{verify}} no worse than the baseline, e2e no NEW failure,
     SHOOT --out {{scratch}}/smoke/after-{{wave_slug}}, then `deps-smoke diff {{scratch}}/smoke/after-{{previous_wave}} {{scratch}}/smoke/after-{{wave_slug}} --out {{scratch}}/smoke/diff-{{wave_slug}}`.
  4. `deps-check changelog {{repo}} --plan {{plan}} --wave {{wave_id}} --notes {{scratch}}/notes/{{family}}.md --verify build=pass --smoke {{scratch}}/smoke/diff-{{wave_slug}}/diff.json --write` (one `--verify step=result` per step run),
     then the same command plus `--format mr` (same `--verify`, `--smoke` and `--notes`; the body states Merge order and Stacked on).
  5. `deps-check preflight {{repo}}` must still say identity ok; commit. dry_run yes → stop: branch kept, no push, no MR. Else `git push -u origin {{branch}} {{push_opts}}`, then
     `glab mr create --draft -s {{branch}} -b {{base_branch}} -a {{reviewer}} --reviewer {{reviewer}} -l dependencies --remove-source-branch -y -t "chore(deps): {{family}} {{from}} → {{to}}" -d "$(cat {{mr_body}})"`.
  SHOOT = `deps-smoke shoot --base {{base_url}} --routes {{routes}} --serve "{{serve_cmd}}" --ready {{ready_url}} --env PORT={{port}} --env HOST=127.0.0.1 --node-pin {{node_pin}} --out <dir>`.
  e2e and SHOOT run in the background and are awaited (a foreground Bash call is capped at 10 minutes). Before each, `lsof -iTCP:{{port}} -sTCP:LISTEN` prints nothing (127.0.0.1 and ::1).
  Fix loop (SendMessage): a fix for wave N is committed on N; then, for each later wave up to the tip in order, `git switch <branch> && git merge --no-ff <branch N>`, reinstall, verify again,
  `deps-check changelog {{repo}} --plan {{plan}} --wave <that wave> --verify build=pass --write`, push. A merge conflict in the changelog alone: run that changelog command, `git add` it, `git commit --no-edit`.

DOD-SLICE: {{verify}} → pass or the baseline failures; `deps-check changelog {{repo}} --plan {{plan}} --check` → `CHANGELOG: ok`; `deps-smoke diff` → `SMOKE: same(n)` or each changed route explained in the notes;
  `git diff --stat {{base_branch}}..{{branch}}` → at most 15 files; `git log --format='%ae %ce' {{base_branch}}..{{branch}}` → only {{identity}}; live run: `glab mr view <iid> -F json` → draft true, target {{base_branch}}.
STOP IF: the change touches more than 15 files or a human-first zone of `security.md` · another package's major is needed · identity is not ok · a new package with an install script · a deny-list hit · the frozen install reports the lockfile out of sync · the port is busy.
FORBIDDEN: other packages · refactors · human-first zones · `--auto-merge`, `glab mr merge` · a push to {{default_branch}} · rebase, amend or force on any branch · `--no-verify` · changing `user.email` · printing `.npmrc` or `.env` values · shots or logs in the repo or the MR.
RETURN: DIFF · DOD-SLICE · ESCALATION · `NOTES: {{scratch}}/notes/{{family}}.md` · `FILES: n changed (at most 15)` · `SMOKE: <last line of deps-smoke diff>` · `MR: !iid {{branch}} sha7` (dry run: `branch sha7`).
