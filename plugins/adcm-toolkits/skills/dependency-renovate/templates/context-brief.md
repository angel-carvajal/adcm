# CONTEXT BRIEF (fill every {{...}} from plan.json as references/flow.md says; this file is the Agent prompt; dry_run is yes or no)
# Agent(subagent_type: "adcm-toolkits:executor") (sonnet). No such type in this session → Agent(subagent_type: "general-purpose", model: "sonnet") with the same brief.

TASK: Refresh the dependency context of {{repo}} after run {{run_id}}: `dependencies.md` in the context skill {{context_skill}}, its index line and its plugin. dry_run: {{dry_run}}.
  Owner consent to create the file when absent: {{consent}}.

FILES: {{context_skill}} (`dependencies.md` at the root or in `references/`, `SKILL.md`), the `plugin.json` of its plugin and its marketplace entry, {{plan}}; the docs repo of that plugin.
  Of the code repo only a switch to {{default_branch}}; never its files.
SKILLS: — (none to load)

DELIVERABLE:
  1. `git -C {{repo}} switch {{default_branch}}` with a clean tree, so the snapshot is the default branch.
  2. dry_run no: `deps-check context {{repo}} --context {{context_skill}} --plan {{plan}} --write` → `CONTEXT: written <path>` or `CONTEXT: current`.
     The Policy section is written only for a NEW file: no file and no consent → stop. Exit 2 `records repo <x>` → run again with `--file dependencies-<repo>.md`.
     dry_run yes: `mkdir -p {{scratch}}/ctx`, copy the current `dependencies.md` into it when one exists, run `deps-check context {{repo}} --context {{scratch}}/ctx --plan {{plan}} --write`,
     skip steps 3 to 5 and RETURN `PLUGIN: none (dry run)`: no index line, no bump, no commit, no push.
  3. Add ONE index line to `SKILL.md` of the context skill if it is missing, in that file's language and list style: the path of `dependencies.md` — dependencies, runtime and CI pins (auto) + policy (human);
     start here when asked to update or audit dependencies.
  4. Patch-bump the version of the context plugin (`plugin.json`, and its marketplace entry when that carries a version). `git -C <docs repo> config user.email` must equal the author of its recent commits (`git -C <docs repo> log -5 --format=%ae`), else STOP.
  5. Commit and push the main branch of the docs repo (docs repos push to main directly).

DOD-SLICE: `deps-check context {{repo}} --context {{context_skill}} --plan {{plan}}` → `CONTEXT: current`; `git -C <docs repo> status --porcelain` empty and the pushed sha is on origin's main;
  dry run: `{{scratch}}/ctx/dependencies.md` exists and `git -C <docs repo> status --porcelain` is empty.
STOP IF: the identity of the docs repo is not ok · more than one context skill matches (pass --context) · `dependencies.md` records another repo and `--file` does not fit · the plugin version cannot be read.
FORBIDDEN: touching the code repo's files, the Policy section of an existing file, anything outside the context skill and its plugin · `--force`, `--no-verify` · publishing · `claude plugin update` (the main session runs it).
RETURN: DIFF · DOD-SLICE · ESCALATION · `CONTEXT: <verdict line>` · `PLUGIN: <plugin>@<marketplace> <old> → <new>` (dry run: `PLUGIN: none (dry run)`).
