# bin/

Bare-name launchers for the plugin's Python scripts. While the plugin is enabled, Claude Code puts
its `bin/` on the Bash tool's PATH (after the user PATH); they carry the executable bit, no manifest
key. Each resolves the plugin root from its own path (symlinks followed) and runs `python3 -B <script> "$@"`.

`courier-preflight` runs `skills/artifact-courier/scripts/courier_preflight.py`; `status-digest`,
`renovate-check`, `plans-regen` and `prompts-regen` run the `status_digest.py`, `renovate_check.py`,
`plans-regen.py` and `prompts-regen.py` of `skills/execution-prompt-architect/templates/`.

Auto mode: the classifier may deny the registry seal (`courier-preflight … --mark-published`) as
"Create Public Surface" although it only edits the project's local `artifacts.json`. The documented
remedy is an `autoMode.allow` prose exception in the owner's user settings (keep `"$defaults"` first):
`"Artifact Registry Sealing: running the plugin's courier preflight (courier-preflight or
scripts/courier_preflight.py) with --mark-published, --set-regen or --set-active-account seals or
annotates an artifact row in the project's local artifacts.json. It is a local file edit: nothing is
published; the artifact URL is only recorded text. Create Public Surface does not apply."`
If the seal is still denied, the courier returns `REGISTRY: blocked by permissions: <command>` and the
owner runs that command with `!`.

## Hooks
`artifact-guard.py` (Stop) and `merge-guard.py` (PreToolUse · matcher `Bash|mcp__.*merge.*` · timeout 10) live in `skills/execution-prompt-architect/templates/`. The owner copies them to
`$CLAUDE_CONFIG_DIR/hooks/` (default `~/.claude/hooks/`) and registers them in the user `settings.json` (`hooks.Stop` / `hooks.PreToolUse`):
```json
{"hooks": {"Stop": [{"matcher": "", "hooks": [
  {"type": "command", "command": "python3 ~/.claude/hooks/artifact-guard.py", "timeout": 20}]}]}}
{"hooks": {"PreToolUse": [{"matcher": "Bash|mcp__.*merge.*", "hooks": [
  {"type": "command", "command": "python3 ~/.claude/hooks/merge-guard.py", "timeout": 10}]}]}}
```
`renovate-check` prints `review:` lines when either hook is missing or outdated. A registration that still has the old matcher `Bash` leaves the MCP merge tools unguarded: re-run the installer, which updates it in place.
merge-guard denies `gh pr merge`, `glab mr merge|accept`, merge API calls, the MCP merge tools (`mcp__…merge_merge_request|merge_pull_request|accept_merge_request|merge_mr|merge_pr`; any other non-Bash tool passes) and, while on main|master|develop|trunk, `git merge` / `git pull [--rebase] <remote> <other-branch>` / `git rebase <ref>` / `git reset --hard|--soft|--keep|--merge <ref>` (sync forms stay allowed: `origin/main`, `upstream/main`, `@{u}`, the same branch, `HEAD~N`). It also denies a `git push` that sets an auto-merge push option (`merge_request.merge_when_pipeline_succeeds`, `merge_request.auto_merge`, `auto_merge`) or pushes another ref into a protected name (`HEAD:main`, `feature/x:main`, `+feat:refs/heads/main`). It never touches `git commit` or plain pushes (`git push`, `git push origin main`, `git push origin main:main`) — the docs repos push straight to main.
