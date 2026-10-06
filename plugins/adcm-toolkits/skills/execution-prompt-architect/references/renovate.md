# Renovate an existing brain

Read on 'renovate the brain', 'upgrade the brain', 'renueva el brain' or 'actualiza el protocolo'. It brings an older
brain up to the checker's target (`renovate-check --version`) and never re-plans: wave scope, state and logbook stay.

## 0. Requirement and snapshot
Deterministic first, model second. `{{skill_dir}}` = this skill's base dir; `<docs_dir>` = the brain. A plugin shipping
`renovate_check.py` must be loaded (`/reload-plugins` or a new session); its `bin/` launchers (`status-digest`,
`renovate-check`, `plans-regen`, `prompts-regen`) run bare; without the plugin: `python3 {{skill_dir}}/templates/<script>.py`.
- Never read `task.md` or `execute.md`. State: `status-digest --brain <docs_dir>`
- Snapshot (pasted into every brief): `renovate-check --brain <docs_dir> --all-modules --invariants`
  Exit 0 `up-to-date` (stop: 0 agents) · 1 `needed(<blocks>)` · 2 no brain or unreadable · 64 usage.

## 1. Scripts (deterministic, 0 agents)
`renovate-check --brain <docs_dir> --all-modules --copy-scripts` copies the missing SCRIPTS files into
`<docs_dir>/scripts/` and nothing else. A differing copy is informational (`SCRIPTS ok · custom: <file>`) and never
blocks `up-to-date`: keep it when customised, else `--force-outdated`. Only `cache-dep: <file>` (a script reading `plugins/cache/`) needs an executor.

## 2. One executor per needed block
For EVERY block in `needed(...)` (state `missing`, `partial`, `unparsed`; RULES: `needed`), ONE `Agent(subagent_type:
"adcm-toolkits:executor")` (sonnet) with `{{skill_dir}}/templates/renovate-brief.md`, the check output and the snapshot.
- Order, sequential: SCRIPTS (cache-dep) → ARTIFACTS → EXECUTE → TASK → RULES. Modules after the root.
- EXECUTE keeps the brain's gate-report path (`qa/<wave>/gate-*.md` when `qa/` has per-wave folders) when aligning §1/§7.
  Since 0.16.0 `lacks` can name `reviewer-line`, `merge-rule`, `links-once` or the retired merge policy (`auto-` + `merge`, in §3 only).
  The executor writes the template's text: the `> **Reviewer:** <handle> (<forge>) · **Merge policy:** wait` line under the Protocol line,
  §1 principle 12, §3 (2-row table + the `**Claude never merges.**` paragraph), the §2b paragraph `exactly once per delivery close` (steps
  5/7 consistent: no guard-built block, no links every turn) and, in §7, only the ☐ 🔄 ⛔ ⏸ prompts (precondition previous MR merged,
  delivery = open the MR + assign the Reviewer, never merge, close = links once + a `Para ti` line `MR !N → review and merge (<reviewer>)`).
  Reviewer unknown → `_pending — owner sets it_`: `review: reviewer pending → owner sets @handle` (never `needed`); "Para ti" asks for it.
- HOOKS (informational, never `needed`; JSON `blocks.hooks`): `review: merge-guard hook missing …` / `review: artifact-guard hook missing |
  outdated …` name what `$CLAUDE_CONFIG_DIR/hooks` (else `~/.claude/hooks`) lacks, or an artifact-guard that differs from
  `templates/artifact-guard.py` (`unknown`, no line, when that template is not beside the checker). Renovation never installs hooks: the
  final message hands the owner a scratchpad install script to run with `!`.
- ARTIFACTS `review: no active_account declared` is not in `needed`: the final message gives the owner
  `courier-preflight <docs_dir> --set-active-account <name>` (declarative when no `url_<name>` family exists).
- RULES (`needed` on `fix` findings): the checker resolves its targets itself (project memory dir from
  `$CLAUDE_CONFIG_DIR` + the container path, container `CLAUDE.md`/`AGENTS.md`, brain `README.md`; `--memory-dir PATH`
  overrides, `--no-rules` skips). `fix` → ONE executor with the RULES block; `review` findings go to the owner in the
  final message, untouched. The memory lives outside the repo: never committed.
- CONTEXT last, only on `CONTEXT ok (<skill>)`: its executor runs STEP 4.5 `--update`, patch-bumps the context plugin (else
  `plugin update` does nothing), commits + pushes its repo and RETURNs `PLUGIN: <plugin>@<marketplace> <old> → <new>`; the main session then runs `claude plugin
  marketplace update <marketplace>` and `claude plugin update <plugin>@<marketplace>` (no CLI → hand both to the
  owner) and reminds `/reload-plugins` or a new session. `n/a` is skipped.
- A block that returns `STOP` (an invariant would change, or it needs re-planning) goes to the user.

## 3. Audit gate
ONE `Agent(subagent_type: "adcm-toolkits:auditor")` (read-only), brief ≤40 lines:
- `git -C <docs_dir> diff --stat`: only the expected files, no deletions of history; the INVARIANTS line (s7 headers,
  h2 sections, logbook entries, wave rows) before and after: identical (`lines=` may grow);
- generators: `plans-regen --check` / `prompts-regen --check` only for rows whose `regen` uses them
  (`regen none` is not checked; exit 3 = hand-maintained layout, leave it);
- `renovate-check --brain <docs_dir> --all-modules` → `RENOVATE: up-to-date`; a public brain also gets the privacy grep.
Findings go back to the SAME executor (`SendMessage`, cost 0).

## 4. Close
- Doc-sync in the brain's own repo: the logbook entry `[REFRESH] protocol <target>` (with its `Next:` line) appended as
  the ≤20-line orchestrator shortcut (logged), then commit + push.
- ONE `Agent(subagent_type: "adcm-toolkits:courier")` with the `artifact-courier` skill's `templates/courier-brief.md`,
  `REGEN: yes`; the LAST courier RETURN's links block goes last in the final message, once. Rows never sealed (decks, demos) are republished and sealed once.

## 5. Idempotency, budget, drift
Repeating the phrase on a renovated brain prints `RENOVATE: up-to-date`, 0 agents. Typical budget 3-5 of this session's 20
(executors 2-4, auditor 1 with 1 Opus quota — `model: sonnet` once the Opus quota is spent —, courier 1). Census drift: renovate adds `artifacts.json`
rows, so the next wave's SCOPE census may STOP: re-run it, fix its `expected` line (≤20-line shortcut, logged), never re-plan.

## Sessions without the agent types
No `adcm-toolkits:*` types (not reloaded): `Agent(subagent_type: "general-purpose", model: "sonnet")` with the same
briefs, one per block ("Renovate this brain to the current protocol: apply each block the check lists from
`renovate-brief.md`, one sonnet agent per block"). Two states go back to the owner: `needed(scripts)` after a failed copy
(`failed x (symlink)`, read-only dir) and `ARTIFACTS unparsed` (a registry `--set-regen` cannot repair).
