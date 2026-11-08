# bin/

Bare-name launchers for the plugin's Python and Node scripts. While the plugin is enabled, Claude Code puts
its `bin/` on the Bash tool's PATH (after the user PATH); they carry the executable bit, no manifest
key. Each resolves the plugin root from its own path (symlinks followed) and runs its script with `python3 -B <script> "$@"` (`node <script> "$@"` for the Node launchers).

`courier-preflight` runs `skills/artifact-courier/scripts/courier_preflight.py`; `status-digest`,
`renovate-check`, `plans-regen` and `prompts-regen` run the `status_digest.py`, `renovate_check.py`,
`plans-regen.py` and `prompts-regen.py` of `skills/execution-prompt-architect/templates/`; `map-refresh` runs
`skills/code-project-context-generator/scripts/map_refresh.py`.

`explainer-record` is a Node launcher: it runs `skills/explainer-video/scripts/record.mjs` with `node` instead of `python3`.
Recording needs Node 20+, so it puts the newest nvm 2x install (version order) first on PATH and falls back to the `node` already there;
its `--doctor` flag reports what is missing (Node, Playwright, browser, ffmpeg, voice).

`design-board` is the launcher of the `design-direction-architect` board: `doctor` and `capture` run `skills/design-direction-architect/scripts/capture.mjs` with `node` (same Node 20+ shim as `explainer-record`);
`init`, `check`, `build`, `mark`, `adopt`, `log` and `pack` run `design-board.py` with `python3 -B`; any other subcommand prints the usage on stderr and exits 64.

`tailnet-preview` runs `skills/artifact-courier/scripts/tailnet_preview.py` with `python3 -B`: `doctor`, `up`, `status`, `url`, `down`, `list` (`up`/`down` change nothing without `--apply`; exits 0/1/2/64; `--json`). It keeps a project's dev server alive after the session (detached, `caffeinate`) and maps it with `tailscale serve` to `https://<machine>.<tailnet>.ts.net:<port>/` for the owner's phone; without Tailscale it falls back to LAN-only. Setup and lifecycle: `skills/artifact-courier/references/tailnet-preview.md`.

`deps-check` runs `skills/dependency-renovate/scripts/deps_check.py` with `python3 -B`: `preflight`, `plan`, `changelog`, `context`, `status` (read-only; `--write` is the only write flag and without it a command prints `would write <path>`; exits 0/1/2/64). It plans one dependency run from the project's manifests and the registries. `deps-smoke` is a Node shim like `explainer-record`: it runs `skills/dependency-renovate/scripts/deps_smoke.mjs` with `node` (`doctor`, `shoot`, `diff`): `shoot` takes one PNG per route and `diff` compares a before and an after set pixel by pixel; exits 0/1/2/64.

Auto mode: the classifier may deny the registry seal (`courier-preflight … --mark-published`) as
"Create Public Surface" although it only edits the project's local `artifacts.json`. The documented
remedy is an `autoMode.allow` prose exception in the owner's user settings (keep `"$defaults"` first):
`"Artifact Registry Sealing: running the plugin's courier preflight (courier-preflight or
scripts/courier_preflight.py) with --mark-published, --set-regen or --set-active-account seals or
annotates an artifact row in the project's local artifacts.json. It is a local file edit: nothing is
published; the artifact URL is only recorded text. Create Public Surface does not apply."`
If the seal is still denied, the courier returns `REGISTRY: blocked by permissions: <command>` and the
owner runs that command with `!`.
A second prose exception the owner may add to `autoMode.allow` (keep `"$defaults"` first) covers the tailnet preview:
`"Tailnet Preview: running the plugin's tailnet preview launcher (tailnet-preview or scripts/tailnet_preview.py) with up or down --apply starts or stops the current project's local development server and maps or unmaps it with tailscale serve (never tailscale funnel), so only devices signed in to the owner's own private tailnet can open it. Nothing becomes reachable from the public internet. Create Public Surface does not apply."`
If it is still denied, the owner runs the exact command with `!`. Optional, since the `footerLinksRegexes` key is not publicly documented: a footer badge for the
tailnet link, in the same entry shape as the owner's existing `footerLinksRegexes` entries:
`{"type":"regex","pattern":"\\[(?<t>[^\\]]{1,40})\\]\\(https://(?<h>[a-z0-9-]+\\.[a-z0-9-]+\\.ts\\.net(?::\\d{1,5})?)/[^)\\s]*\\)","url":"https://{h}/","label":"{t}"}`

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
