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
