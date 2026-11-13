#!/bin/sh
# claude.ai/Cowork refuse a top-level bin/, so the launchers live in scripts/launchers and join PATH here.
[ -n "$CLAUDE_ENV_FILE" ] || exit 0
dir="$CLAUDE_PLUGIN_ROOT/scripts/launchers"
[ -d "$dir" ] || exit 0
grep -qsF -- "$dir:" "$CLAUDE_ENV_FILE" && exit 0
printf "export PATH='%s:'\"\$PATH\"\n" "$dir" >> "$CLAUDE_ENV_FILE"
exit 0
