# Changelog — adcm-toolkits

## 0.24.0 — 2026-11-23

- **MR evidence.** New `mr-evidence` launcher (`skills/explainer-video/scripts/evidence.mjs`, spec and rules in `references/evidence.md`):
  `doctor`, `check`, `capture`, `attach`, `run` take desktop/mobile screenshots and a silent captioned mp4 of the branch's local dev server
  and upload them to the GitLab MR (`## Evidencia` between `<!-- evidence:start -->` and `<!-- evidence:end -->`, or an MR note). GitHub
  repos get an "adjuntar a mano" block. Why: frontend MRs carried no visual evidence; screenshots only reached the phone.
- **`--mode` is media only.** `--mode screenshots|video|both|none` picks the media; the new boolean `--note` posts an MR note instead of
  replacing the description region (default placement is the description). `--mode body|note` exits 64 with a hint. The note case of
  `evidence-selftest.py` covers both. The launcher still rewrites `--env-file` to `--creds-file`.
- **executor-frontend.** With `EVIDENCE: spec` in its brief it writes `qa/evidence/<Wx>.json` and returns `EVIDENCE-SPEC:`; it never
  captures or uploads (`docs/agents.md`). The orchestrator's rule lives in `execution-prompt-architect/references/orchestrator-rule.md`, section "MR evidence".
- **dependency-renovate.** The existing single AskUserQuestion round gains one question: upload the diff/after shots to the MR? (yes | no;
  no video). On yes, `mr-evidence attach --files <S>/<shots dir> --md-out <S>/mr/evidence.md` runs before `glab mr create` (no new capture)
  and `deps-check changelog --format mr --evidence <file>` renders it in `{{EVIDENCE_BLOCK}}` after `### Visual smoke`. Logs and
  `.npmrc`/`.env` values still never go in the MR. Files: `SKILL.md`, `README.md`, `references/flow.md`, `templates/major-brief.md`,
  `templates/mr-description.md.tmpl`, `scripts/deps_check.py`, `scripts/deps-check-selftest.py`.
- **execution-prompt-architect.** New phase a step 3a (after the status-digest step, before any executor) asks once for UI waves: MR evidence `screenshots | video | both | none`. The answer is recorded as the handoff/task `Evidence:` label and phase c reuses it. `## Evidencia: pendiente (<reason>)` is written between the `<!-- evidence:start -->` and `<!-- evidence:end -->` markers so a later run replaces it. The `mr-evidence run` Bash call carries `timeout: 600000`. The deterministic `mr-evidence` script is the one stated exception to "the main session never renders". Files: `SKILL.md`, `references/orchestrator-rule.md`, `references/renovate.md`, `templates/wave-prompt.tmpl`, `templates/execute.md.tmpl`, `templates/task.md.tmpl`.
- **renovate_check.** New `evidence-ask` flag in `lacks` (a template without the `mr-evidence capture` literal); the selftest gains 4 merge-guard cases.
- **executor-frontend.** Returns `EVIDENCE-SPEC: not asked` when its brief carries no `EVIDENCE:` line.
- **dependency-renovate patch-minor.** `templates/patch-minor-brief.md` now wires evidence like the major brief: `mr-evidence attach --files {{scratch}}/smoke/diff-patch-minor ... --md-out {{evidence_file}}` before `glab mr create` and `--evidence {{evidence_file}}` on the `--format mr` render. `{{evidence_file}}` (empty = the user said no) is defined in `references/flow.md`; the major brief names its diff dir explicitly (`diff-{{wave_slug}}`).
- **mr-evidence hardening.** SIGTERM/SIGHUP cleanup of the dev server and temp files, stricter spec validation, and `glab mr note create` for the `--note` placement.
- **Version constants.** `plugin.json` and the version strings of `courier_preflight.py`, `renovate_check.py`, `status_digest.py` and the
  renovate selftest read 0.24.0 (the `execute.md.tmpl` Protocol line follows with the template owner's change).

## 0.23.0 — 2026-11-19

- **Effort.** The planning skill stops recommending the multi-agent effort mode and drops its explanation: `/effort max` is for the
  planning run only. Every phase of `wave-prompt.tmpl` (and the phase shells of `execute.md.tmpl`) gets one launch line OUTSIDE its fenced
  block, because a pasted first line starting with `/` runs as a command: `LAUNCH: /model fable · /effort high` for phases a and c,
  `LAUNCH: /model opus · /effort high` for b, d and e. `status-digest --prompt` prints that line before the block. The deep-reasoning keyword is typed by
  the user for one design turn and is never baked into a prompt; `CLAUDE_CODE_EFFORT_LEVEL` is never suggested (it overrides
  sub-agent effort). `executor`, `executor-frontend` and `researcher` default to `effort: medium`; ⚠gate executor calls and
  `researcher` + `model: opus` calls pass `effort: high` per call.
- **Phase c is one round.** No Workflows, auditors or verifications: DoD green on round 1 goes to `Next phase: b`, where verification
  lives. Advisory waves keep c → d, also without Workflows or auditors; their check is the scripted DoD.
- **SendMessage is not free.** It adds 0 to the agent counter but re-reads the agent's whole context: resume only the same task with
  < 5 min idle; otherwise a new executor with a relay file of ≤ 40 lines, counted against the 20. Exempt: courier retry and doc-sync
  phase B. Doubts to a researcher or auditor follow the 5-minute rule; the simplify fix round is a new executor.
- **No mid-run STOP IF from the orchestrator.** It adopts the verifier's minimal fix unless it cites evidence and logs each override as
  `override: <reason + evidence>`.
- **Handoff labels.** `handoff.md.tmpl` gains `DoD recipe:`, `Traps:` and `Spend:` (≤ 40 lines). `status_digest.py` reads them as logbook
  labels (`traps:` / `spend:` on the LAST LOG block) and prints a `SPEND` line from the latest handoff, truncated, inside its 40-line cap.
  Side tasks that surface mid-phase are queued for the close: the memory-index warning (`check-memory-index.py --brief`) now says so.
- **Spend report.** `spend-report` (`spend_report.py`, launcher) joins the plugin; every phase close runs
  `spend-report --phase <letter>` and copies its line 1 into the handoff `Spend:` label.
- **Tiers.** One rule replaces every own-tier rule: the orchestrator never implements first and never audits or verifies a diff in its own
  context; every audit goes to a fresh agent at the tier the table names, whatever the main model; the simplify pass runs `model: opus`
  in a fresh context. The tier-down when the main model is not the top one is gone; Haiku is for inventories only. Where the text named
  the main thread as Fable it now says "the orchestrator".
- **Selftests.** `status-digest-selftest.py` covers the launch line, the spend line, the new labels and asserts that `--prompt` output,
  `wave-prompt.tmpl` and `SKILL.md` carry no effort-mode keyword.
- **Renovation and sibling skills.** `renovate_check.py` copies `spend_report.py` (thirteen SCRIPTS) and flags brains that lack the
  `spend-report` close or the `launch-line`; `prompts-regen` carries each LAUNCH line into its prompts.html card; the own-tier and
  SendMessage wording of `business-context-generator`, `dependency-renovate` and `design-direction-architect` follows the rules above.
- **Version constants.** `plugin.json`, the `execute.md.tmpl` Protocol line and the version strings of
  `courier_preflight.py`, `renovate_check.py`, `status_digest.py` and the renovate selftest read 0.23.0.

Notes: run `claude plugin marketplace update adcm` and `claude plugin update adcm-toolkits@adcm`, then reload plugins or restart sessions.
Existing brains adopt the new phase prompts only through the renovation phrase.

## 0.22.2 — 2026-11-16

- **Hardened: coarse path.** The textual tamper check also runs on a normalised copy of the input (quotes and backslashes removed, home
  shorthand expanded), so a path split by quoting no longer slips past it.
- **Hardened: time budget.** Measured in CPU time (0.6 s) with a 3 s wall-clock safety net, so a loaded machine cannot trip it. On the
  attended main thread outside direct mode a command too costly to evaluate is denied instead of falling back to the coarse rules.
  Sub-agents, direct mode and unattended runs keep the coarse path.
- **Hardened: words too long to probe.** Brace lists are expanded before the length test; a path-changing command (`rm`, `mv`, `cp`,
  `chmod` and the like) or a redirection whose target is still too long to probe is denied on every thread. Long arguments to
  interpreters, filters, SQL or commit messages are unaffected.
- **Added: rule X3.** On the attended main thread outside direct mode a command whose evaluation exceeds the CPU budget (0.6 s) is denied
  as too costly; when only the 3 s wall-clock net trips (a stalled machine) the coarse rules apply instead. Brace lists: every
  alternative is judged on its own (the first 64 against the filesystem, all of them lexically up to 4096); ranges are not expanded;
  a path-changing command or redirection with an operand too long to probe, or with more than 4096 alternatives, is denied on every
  thread. On the coarse path the normalised copy also drops command-substitution spans.
- **Not changed on purpose.** Commands over 16 KB from sub-agents are still allowed unless they name the guard's paths, because writing
  files through large heredocs is normal sub-agent work.
- **Selftests.** 22 suites, 946 checks, 0 failures (full run of the untouched suites from the 0.22.1 run, plus this
  refresh of the guard, notify-stop and version-constant suites). Guard suites: `main-thread-budget` (118),
  `compaction-breaker` (54), `heavy-read-guard` (27), `guard-fuzz` (3). `--mutation` kills all 60 mutants over 9
  suites (main-thread-budget 35, compaction-breaker 9, heavy-read-guard 5, docsync-apply 3, plan-audit 3,
  memory-index-check 2, status-digest 1, artifact-guard 1, guard-fuzz 1).
- **Version constants.** `plugin.json`, the `execute.md.tmpl` Protocol line and the version strings of `courier_preflight.py`,
  `renovate_check.py`, `status_digest.py` and the renovate selftest read 0.22.2.

Notes: run `claude plugin marketplace update adcm` and `claude plugin update adcm-toolkits@adcm`, then reload plugins or restart sessions.
Nothing to copy: the artifact-guard template is unchanged since 0.22.0.

## 0.22.1 — 2026-11-16

- **Fixed: guard let calls through.** For a command with an environment-variable prefix followed by a path-taking verb (`mv`, `cd`),
  the guard resolved an internal marker as a path, raised an internal error and let the call through unchecked and uncounted. Found in
  live use one day after 0.22.0 through the guard's own error log. A line with unbalanced quotes also skipped the tamper rule.
- **Changed: an internal error no longer means "allow".** A parse-free fallback keeps the compaction lock and handoff gate, the Bash / Read
  budget, the Bash size caps and a textual tamper check. Filesystem probes never raise. State is updated before fragile work. Commands over
  16 KB, or evaluation over 0.6 s, take that coarse path without word-by-word parsing; on the attended main thread outside direct mode a command over 16 KB is denied (edit cap). A command over 16 KB that names the guard's state or installation is denied with its own reason.
- **Added: visible errors.** Internal errors show as `⚠ guard errors: n` in the counter line; `errors.log` lines carry event, tool, thread,
  frames and the offending word, and the file is capped at 200 lines.
- **Added: stricter tamper rule.** A relative word is resolved against every directory the line names; a line that touches the guard's own
  paths must be one plain read-only line (no heredoc, command substitution, comment or unbalanced quote).
- **Added: state recovery.** When a session's state is missing or unreadable, the guard rebuilds it from the session transcript (Bash and
  Read counts, compactions, handoff written) instead of starting at zero. Deleting the state resets nothing, and a session that predates
  the install starts with its real counts. A handoff counts on recovery only when the file on disk holds at least 300 characters. A new session after `/clear` still starts at zero.
- **Changed: tamper and Read details.** `pushd` and the builtin or command forms of `cd` are tracked, relative words and globs are
  resolved against every directory the line names, and a line the tokenizer cannot read is still judged line by line. Non-finite Read
  limits count as whole-file reads.
- **Selftests.** 22 suites, 938 checks, 0 failures. Guard suites: `main-thread-budget` (110), `compaction-breaker`
  (54), `heavy-read-guard` (27), `guard-fuzz` (3; fixed seed, 5000 structured inputs per run). `--mutation` kills all
  53 mutants over 9 suites (main-thread-budget 28, compaction-breaker 9, heavy-read-guard 5, docsync-apply 3,
  plan-audit 3, memory-index-check 2, status-digest 1, artifact-guard 1, guard-fuzz 1).
- **Version constants.** `plugin.json`, the `execute.md.tmpl` Protocol line and the version strings of `courier_preflight.py`,
  `renovate_check.py`, `status_digest.py` and the renovate selftest read 0.22.1.

Notes: run `claude plugin marketplace update adcm` and `claude plugin update adcm-toolkits@adcm`, then restart sessions or reload plugins.
Nothing to copy: the artifact-guard template is unchanged since 0.22.0.

## 0.22.0 — 2026-11-14

- **main-thread-guard.** New plugin hook `scripts/main-thread-guard.py` (SessionStart, UserPromptSubmit, PreCompact,
  PreToolUse, PostToolUse; registered in `hooks/hooks.json`, fail open) that keeps the main session orchestrating.
  Rules, first match wins: T0 (every thread: nothing in a session changes the guard's state folder or its own files,
  meaning the three files that decide whether it runs and the folders that hold them; on those paths, or when one of them is the working directory, Bash is limited to
  a read-only allowlist with no write redirection and no environment prefix, editors are denied, and scheduling tools
  whose text carries an escape phrase are refused). The rest apply to the main thread only: R1 (lock on the 3rd
  compaction), R1b (at the 2nd compaction every other tool is denied until a handoff of at least 300 characters is
  written: state, pending items, live agents, next step, resume prompt), M1 (memory index line over 150 characters),
  R6 (a status question, a prompt that is essentially the status phrase alone, gets 3 calls; ordinary prompts that merely
  contain the word are not capped), R3 (no whole-file reads of files over 40 KB or of plan docs, no image or PDF reads, no
  transcript dumps), X1 (no browser tools, no Artifact publish or read), X2 (edits over 20 lines, Bash scripts over 25
  lines), R2 (25 Bash/Grep/Glob and 8 Read calls per session; environment caps can only lower the defaults).
  Sub-agents are exempt after T0.
- **Direct mode.** `sin tanto lío` (one turn) and `modo directo` (sticky until `modo orquestador`) are honoured only from the owner's own prompt, never inside quotes, code, pasted blocks or hand-backs; they switch off R2, R3, R6, X1 and X2 but never T0, R1, R1b or M1.
- **Unattended runs.** Headless and SDK sessions count compactions and receive notes but are never denied anything except by T0; `ADCM_GUARD_FORCE=1` forces attended mode for tests.
- **Phase sessions with handoffs.** The execute.md protocol runs one clean session per phase (a implement, b gate, c
  gate fixes, d doc-sync and close, e production close). Each phase ends with `HANDOFF: <path>`, a file from the new
  `handoff.md.tmpl`; the guard stamps a `Main thread` metric line into it, and phase prompts open with a short guard
  note.
- **Two-phase doc-sync.** New `docsync_apply.py` (launcher `docsync-apply`) applies a JSON edit sheet with `--check` then `--write`, resolves marker placeholders and lints long lines; doc-sync is always one executor in two phases (`docsync-brief.md`), and the main session never writes a sheet.
- **Plan-audit gate (Step 6b).** New `plan_audit.py` (launcher `plan-audit`, `plan-audit-brief.md`): an auditor's
  contradiction report is sealed per wave with hashes; `--check` fails on a missing, failed, open or stale seal,
  `prompts-regen` refuses to render and the digest withholds the next prompt until it passes.
- **Status digest.** `status_digest.py` gains a PHASE line, `--prompt [WAVE:PHASE]` (prints the exact phase prompt), `--mrs` (best-effort open MRs/PRs, 8 s timeout), a STALE note when a handoff or commit is newer than the logbook, and a `main:` metric with a warning flag.
- **check-memory-index.** New `scripts/check-memory-index.py` (launcher `check-memory-index`): line length and token-estimate limits for memory indexes (`--file`, `--all`, `--brief`, `--json`); the guard runs it at session start.
- **artifact-guard v7 and media rule.** The owner-installed `artifact-guard.py` template retries before blocking;
  sub-agents return `MEDIA: sent` or `MEDIA: unsent: <paths>` and the main session sends unsent paths by path without
  opening them. The courier, executor-frontend and researcher agents carry the rule.
- **Renovate.** `renovate_check.py` detects the phase-protocol literals and reports `partial` until a brain is renovated; renovate and status briefs updated.
- **Selftests.** New `scripts/selftest-all.py` runs every `*-selftest.py` (`--only`, `--list`, `--mutation`): 21
  suites, 902 checks, 0 failures. New suites: `main-thread-budget` (89), `compaction-breaker` (43), `heavy-read-guard`
  (26), `memory-index-check` (11), `docsync-apply` (22), `plan-audit` (21). Extended: `artifact-guard` (33),
  `status-digest` (60), `prompts-regen` (20), `renovate` (27). Eight suites carry mutation controls that neutralise
  one marked condition each and require the suite to fail; `--mutation` kills all 44 mutants (main-thread-budget 22,
  compaction-breaker 7, heavy-read-guard 5, docsync-apply 3, plan-audit 3, memory-index-check 2, status-digest 1,
  artifact-guard 1).
- **Version constants.** `plugin.json`, the `execute.md.tmpl` Protocol line and the version strings of `courier_preflight.py`, `renovate_check.py`, `status_digest.py` and the renovate selftest read 0.22.0.

Notes: run `claude plugin marketplace update adcm` and `claude plugin update adcm-toolkits@adcm`, then restart open sessions. After the update the owner re-copies the artifact-guard template over the installed copy:
`cp "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache/adcm/adcm-toolkits/0.22.0/skills/execution-prompt-architect/templates/artifact-guard.py" "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/artifact-guard.py"`.
Existing brains adopt the phase protocol only through the renovation phrase "Renueva el brain al protocolo vigente". The owner's global rule file is not touched by the plugin; its prose now defers to the hooks.

## 0.21.0 — 2026-11-13

- **Phone notification after long turns.** New Stop hook `scripts/notify-stop.py`, registered in the plugin's
  `hooks/hooks.json`. When a turn ran longer than `ADCM_NOTIFY_MIN_SECONDS` (default 300) and no notification was
  sent in it, the hook asks the main session to call the native `PushNotification` tool once, with `status:
  "proactive"` and a fixed minimal text (`Claude finished in <folder>` / `Claude needs you in <folder>`; the latter
  when the final message ends with a question).
- **Links stay last.** When the final message ends with the links block, the hook only emits a desktop notification
  (terminal sequence) instead of asking for a tool call, so the links remain the last lines.
- **Silent cases and switch-off.** `ADCM_NOTIFY=off` disables it. It also stays silent while background tasks or
  scheduled wake-ups are pending, on a re-entrant stop, in headless (`-p` / SDK) runs, and on Bedrock, Vertex and Foundry. No state file, no external service, no secrets.
- **"Notify the owner" rule.** `orchestrator-rule.md`, the artifact-courier skill, `execute.md.tmpl` (GUARDRAILS &
  CLOSE and section 2b step 5), `wave-prompt.tmpl`, dependency-renovate (gate and handover) and `renovate-brief.md`
  now tell the main session to notify once, right before the final message, on a delivery close, a stop that needs
  the owner, or a failed gate; never from a sub-agent.
- **Renovate marker.** `renovate_check.py` gains the `notify-rule` marker: brains generated before 0.21.0 report
  `partial` until renovated.
- **Selftests.** New `scripts/notify-stop-selftest.py` (27 checks); the renovate selftest covers the new marker.
- **Version constants.** `plugin.json`, the `execute.md.tmpl` Protocol line and the version strings of
  `courier_preflight.py`, `renovate_check.py`, `status_digest.py` and the renovate selftest read 0.21.0.

Notes: existing brains run "Renueva el brain al protocolo vigente" (renovate) once to pick up the new rule. The hook
ships with the plugin and needs no registration; in an old session, run `/reload-plugins` or restart once. Phone
delivery needs Remote Control connected and the `/config` toggle "Push when Claude decides"; the tool skips itself
when you are at the terminal.

## 0.20.0 — 2026-11-12

- **Launchers moved to `scripts/launchers/`.** claude.ai and Cowork refuse any plugin with a top-level `bin` folder, so
  the eleven launchers (`git mv`, history kept) and their README now live in `scripts/launchers/`. They resolve the
  plugin root one level deeper (`../..`); the scripts they run and their exit codes are unchanged.
- **SessionStart hook.** New `hooks/hooks.json` runs `scripts/launchers-path.sh`, which prepends the launchers
  folder to the Bash PATH by writing an `export PATH=…` line to `CLAUDE_ENV_FILE` once (it skips when the line is
  already there). It prints nothing to stdout and exits 0 in every case, so bare launcher names keep working in Claude Code.
- **`${CLAUDE_PLUGIN_ROOT}` fallback.** Where the hook does not run, call
  `${CLAUDE_PLUGIN_ROOT}/scripts/launchers/<name>`. Each skill that names a launcher says so once; briefs and
  templates keep the bare names.
- **One-sentence plugin description.** The plugin description is now one sentence (170 characters), identical in
  `plugin.json` and `marketplace.json`.
- **Shorter skill descriptions.** `execution-prompt-architect` and `design-direction-architect` descriptions are
  under 1,024 characters with every trigger kept.
- **Agents README moved.** `agents/README.md` is now `docs/agents.md`: every `.md` inside `agents/` loads as an
  agent, and the validator warned that the file had no frontmatter.
- **Selftests resolve the new depth.** The selftests that run a launcher (tailnet-preview, deps-smoke, design-board,
  explainer-video) point at `scripts/launchers/`.
- **Version constants.** `plugin.json`, the `execute.md.tmpl` Protocol line and the version strings of
  `courier_preflight.py`, `renovate_check.py`, `status_digest.py` and the renovate selftest read 0.20.0.

Notes: no behavior of any script changes. Owners who copied the hooks keep them; the new hook ships with the
plugin and needs no registration. In an old session, run `/reload-plugins` or restart once so the hook runs.

## 0.19.0 — 2026-11-08

- **Brain map.** The code-project-context generator now writes `map/` in the brain (`utilities.md`,
  `patterns.md`, `where-to-look.md`) from the scanner's candidates: shared helpers with their signature and an
  exemplar consumer, development patterns with their anti-pattern, and which doc answers what. Human columns
  are preserved on every refresh. The `map-refresh` launcher and its selftest keep it current by script.
- **Pattern families.** Planning now extracts a family when the same shape repeats: one generic base,
  per-entity subclasses that supply only their type and endpoint, and utility types instead of hand-written
  variants. The least code wins; the plan names the over-abstraction risk next to the saving.
- **Executors apply reuse.** `executor` and `executor-frontend` (also for frontend code) share a `## Reuse`
  block plus a TypeScript block: apply the plan's reuse verdict, look the map up before writing a helper, and
  report the `REUSED` and `RULE-OF-TWO` lines in the RETURN.
- **The generated skill keeps the map fresh.** The context skill gets a routing row (new code or shared logic
  goes to the map first), a rule «Maintain the map» and the script call in its section 2b.
- **`renovate-check`: `map` block.** New flag `map-step` and a deterministic step 1b; `SCRIPTS` stays at 7. A
  brain whose code has no `code-project-context-*` skill gets the map only through a context-generator run
  (STEP 4.6), never through renovation (`MAP n/a`).
- **dependency-renovate.** New skill that renews the dependencies of one project on demand. A deterministic
  plan comes first; one Sonnet executor ships one verified MR with every patch and minor bump; one Opus
  executor per major ships its own stacked Draft MR with migration notes; an Opus auditor gates; Claude never
  merges. Each run records a changelog entry and an MR description rendered by script.
- **deps-check.** Launcher with five subcommands (`preflight`, `plan`, `changelog`, `context`, `status`),
  exits 0/1/2/64 and one write flag, `--write`. Advisories come from the bulk endpoint, independent of the
  package-manager version.
- **deps-smoke.** Launcher that shoots one PNG per route and diffs a before and an after set, in pure Node.
- **Context generator: dependencies.md.** A mixed file rendered by script (declared and locked versions,
  runtime and CI pins) whose human Policy section is preserved on every refresh.
- **Scanner.** New `dependency_manifest` block, the real package manager instead of the npm label in pnpm
  repos, and `update.affected_context_files`.
- **merge-guard.** Also denies the auto-merge option of the GitLab merge-request create command. The owner
  reinstalls the hook to pick it up.
- **Tailnet preview link.** The delivery close can add a third preview link: an HTTPS tailnet URL served by
  `tailscale serve`, tailnet-only and never public, that opens the local preview from a phone on any network.
- **`tailnet-preview` launcher.** `doctor`, `up`, `status`, `url`, `down`, `list`; `--apply` is the only
  write flag. It keeps the dev server alive after the session (detached, `caffeinate`), checks port
  collisions and falls back to LAN-only without Tailscale.
- **Courier step 8b.** New field `Tailnet:`; the line is verified by curl. The guard is unchanged (29
  selftest cases).
- **Owner setup.** Tailscale Standalone, a neutral machine name, MagicDNS and HTTPS certificates, then
  `tailnet-preview doctor`.
- **Notes.** A brain whose code has no `code-project-context-*` skill gets the map only through a
  context-generator run (STEP 4.6), not by renovation (`MAP n/a`). The map reflects the working branch until
  it is merged. Brains on an earlier protocol line report `protocol-line` → `needed(execute)` and the
  renovation adds the map. The tailnet text lives in the plugin: no new renovate marker, no brain renewal.

## 0.18.1 — 2026-10-15

- **Mobile fix for `plans.html` / `prompts.html`.** The sticky topbar wrapped its wave chips into many rows
  (819 px of an 844 px phone viewport, 238 px on a 1440 px desktop) and hid the content. It is now one
  swipeable row (≤56 px) at every viewport size, with the theme toggle pinned at the edge; the hero padding
  shrinks at ≤768 px and reduced-motion also disables smooth scrolling. Both shells carry a `shell vN`
  marker (bump it whenever the style block changes).
- **Shell refresh in `plans-regen.py` / `prompts-regen.py`.** An existing regen-made page whose shell marker
  is missing or older than the template's gets its `<style>` block and marker replaced on the next regen
  (`shell: rebuilt vX→vN`), articles and hand-written hero untouched; `--check` reports it as stale
  (`would rebuild`) and writes nothing; a page regen never produced fails loudly.
- **Protocol 0.18.1** (`execute.md.tmpl` Protocol line, `renovate_check.py`, `status_digest.py`,
  `courier_preflight.py`). Brains run their own copies of the regen scripts under `scripts/`: refresh them
  with a renovation (`--force-outdated` when the copies count as custom) or by hand, then let the courier
  republish.

## 0.18.0 — 2026-10-14

- **design-board.** The design-direction-architect skill now builds one fixed design board by script, as a
  single HTML with five tabs: options, references (each with its public source URL), market, method and
  tokens. Three live options render in iframes; font, scale and colour toggles export the chosen tokens.
  Content lives in `board.json` plus fragments in `board.d/`; the board is registered in
  `.design/artifacts.json` with `regen: design-board build .`.
- **Scripts and launcher.** `scripts/design-board.py`, `scripts/capture.mjs` and the launcher
  `bin/design-board` (`doctor|init|capture|check|build|mark|adopt|log|pack`). Exit codes 0/1/2/64; for
  `capture`, 1 means some URL failed and 2 means the environment is not ready. Selftest of 24 cases with
  a generic Acme fixture.
- **Sources.** Awwwards joins the mined sources, a manual `.design/inspiration/` folder covers Pinterest,
  and the board gains a market research section.
- **Removed.** `contact-sheet.html`, `variants.html` and `extract-site.mjs` are gone;
  `curation-protocol.md` and `variant-preview.md` are folded into `board.md`.
- **Breaking.** `tokens.css` names move to the `--color-*` / `--step-*` / `--font-*` contract. Packs made
  before 0.18.0 regenerate with `design-board adopt`.
- **Agents.** Researcher agents may write one JSON fragment under `.design/board.d/`; `executor-frontend`
  treats the exported `tokens.css` as the source of truth.
- **Protocol.** The Protocol moves to 0.18.0 (`execute.md.tmpl` Protocol line, `renovate_check.py`,
  `status_digest.py`, `courier_preflight.py`). New reference `tokens-contract.md` and template
  `decision-entry.md.tmpl`.

## 0.17.0 — 2026-10-12

- **explainer-video.** New skill that records explainer videos of web apps with AI voice-over from JSON
  storyboards. The model only writes the storyboard; once the owner approves it, `scripts/record.mjs`
  (+ `lib/`) renders it with zero model turns: Playwright screencast, one TTS clip per step, ffmpeg mux,
  poster, contact sheet, verify report and manifest. Everything is config-driven (`baseUrl`, `allowHosts`
  guard that also checks redirects, `guionesDir` / `outDir` anchored to the config's own folder). Voice
  defaults to `edge:es-MX-DaliaNeural` with `piper` / `say` fallbacks that are never applied silently.
  `{{env:VAR}}` secrets are redacted in the logs both raw and URL-encoded. Flags `--check`, `--dry`,
  `--verify`, `--doctor` (synthesizes one word and reports an engine that cannot synthesize) and `--mute`;
  exit codes 0/1/2/3/4/64. Ships a Python selftest of 30 cases including an offline smoke E2E, a SKILL.md
  with the two-phase flow (storyboard → owner OK → script records), `references/`, `templates/` and
  generic Acme fixtures.
- **Launchers.** `bin/explainer-record` is the first Node launcher (it puts Node >= 20 first on PATH when
  an nvm 2x install exists); `bin/README.md` now covers both the Python and the Node launchers.

## 0.16.0 — 2026-10-05

- **Claude never merges.** `execute.md` declares a `Reviewer` (`> **Reviewer:** @handle (gitlab|github)
  · **Merge policy:** wait`) and §3 is fixed text: a wave ends with its MR open, pipeline green,
  simplify pass done and assigned to the Reviewer; the merge is a DoD-human row and wave N+1 starts
  only after MR N is merged. The `auto-merge` example is gone from the template, the executors and
  the orchestrator rule forbid merging and pushing code to the default branch; docs repos (ai-brain,
  marketplaces) keep committing and pushing to main directly.
- New PreToolUse hook `templates/merge-guard.py` (matcher `Bash|mcp__.*merge.*`): denies `gh pr merge`,
  `glab mr merge|accept`, merge API calls, MCP merge tools (`merge_merge_request`, `merge_pull_request`,
  `accept_merge_request`), and — while on main|master|develop|trunk — `git merge` / `git pull [--rebase]
  <remote> <other branch>` / `git rebase <other ref>` / `git reset --hard <other ref>`; also `git push`
  with a `merge_when_pipeline_succeeds`/`auto_merge` push option or a `<src>:<protected>` refspec
  (`HEAD:main`, `feature/x:main`). Tokenizer-based (wrappers, `bash -c`, `$()`, heredocs, comments),
  fail-open, 2 s git timeout; plain `git commit`, `git push`, `git push origin main` and sync forms
  (`git merge origin/main`, `git pull`, `git pull --rebase`) stay allowed, so docs repos are unaffected.
- The links block is printed **once per delivery close**, in the orchestrator's final message after
  the last courier RETURN; progress turns carry no links and no agent other than the courier returns
  URLs. `artifact-guard` v6 demands the block only when a courier returned (or the main session
  published) in the turn, evaluates the LAST message only, never hands over a self-built block, and
  blocks docs-touched-without-courier once with "delega el cierre en el courier".
- `courier-preflight` default report points to `--block-only` instead of printing the links marker.
- `renovate-check`: EXECUTE markers `reviewer-line`, `merge-rule`, `links-once` (+ `auto-merge`
  named when still present), `review:` line for a pending Reviewer, informational HOOKS block
  (`merge-guard` missing / `artifact-guard` outdated → `review:`, never `needed`).

## 0.15.2 — 2026-10-04

- Gate reports keep the brain's layout: the verifier brief's `REPORT PATH` is
  `qa/gate-<w>.md` for new brains or the existing per-wave layout (`qa/<wave>/gate-*.md`)
  when the brain already has one; renovate never changes an existing convention.
- `courier-preflight --set-active-account NAME` on a registry that declares no account and
  has no `url_<NAME>` family just declares `active_account` (exit 0) instead of failing;
  `--summary --account …` ends with the resolved account; `renovate-check` flags a registry
  with rows but no declared account as `review` with the command to declare it.
- Renovate's CONTEXT block ends with the plugin update: the executor reports
  `PLUGIN: <plugin>@<marketplace> <old> → <new>` and the main session runs
  `plugin marketplace update` + `plugin update` (or hands them to the owner) and reminds the
  reload — a refreshed context skill is not live until the installed plugin loads it.

## 0.15.1 — 2026-10-04

- The delivery close always prints the links of the CURRENT session's claude.ai account:
  the courier brief's `ACCOUNT` defaults to `auto`; the courier probes the registry's
  `url_<account>` families with the Artifact tool, works on the family that opens, seals
  it with `--mark-published … --account <x>`, records `last_session_account` in the
  registry so the next close starts there, and builds the `=== LINKS ===` block from that
  family (`courier-preflight … --block-only --account <x>`). A URL the session cannot open
  is never printed as the close. Trigger: a session on another account printed the
  registry's canonical URL after re-issuing the page, so the owner tapped a link of the
  other account.
- `artifact-guard.py` accepts any per-account stamp family (`published_at_<x>` /
  `sha256_<x>`) as publish evidence, so a close sealed under `--account` is not reported
  stale; it already accepted `url_<x>` links. Selftests: guard 16, preflight 10.
- `bin/` executables on the Bash PATH while the plugin is enabled (`courier-preflight`,
  `status-digest`, `renovate-check`, `plans-regen`, `prompts-regen`): bare, prefix-stable
  commands for the main session and the courier (POSIX sh wrappers that exec the plugin's
  own script with `PYTHONDONTWRITEBYTECODE`).
- Registry seal denied by the auto-mode classifier ("Create Public Surface" on a local
  `artifacts.json` write): the courier returns `REGISTRY: blocked by permissions: <exact
  command>` and the main session hands the command to the owner to run with `!`, never
  runs it itself. The documented remedy is an `autoMode.allow` exception in the owner's
  user settings describing the seal as a local file edit (README), not a permission
  bypass.

## 0.15.0 — 2026-10-03

Lessons from the first three real renovations.

- `plans-regen.py`: an inline-code `<!--` no longer opens an HTML comment that swallows the
  rest of the document (two real trackers lost 60–85 % of their detailed plan); wave ids
  without a digit or with a lowercase suffix (`WX`, `WSKILL-ARCH`, `W2a`, `WC-V2`) get their
  badge, Gantt row and task cards; free-text wave references resolve against the wave map's
  known ids first (digit-bearing ids stay as a fallback for maps that are incomplete); a link
  whose URL is a code span can no longer inject attributes (XSS);
  `--check` exits 3 on a hand-maintained layout (keep `regen: none`); `--init` on an existing
  file needs `--force`. New `plans-regen-selftest.py`.
- `prompts-regen.py`: lowercase-suffix ids; multiple deliveries per wave (`## Entrega|Delivery`
  headings, one `<pre>` + copy button each; single-delivery waves render byte-identically);
  status badges no longer show a literal `<strong>`; `--closed summary` (default) renders
  closed waves as a title + badge + note instead of the full prompt, so the page stays under
  the courier's re-issue size and keeps its URL (`--closed full` = the previous render);
  `--init` without its template exits 2 instead of a traceback; `--init --check` creates
  nothing. New `prompts-regen-selftest.py`.
- `status_digest.py` finds `courier_preflight.py` from a brain copy (newest installed plugin
  as a last resort); `courier_preflight.py` is now the seventh script copied into
  `<docs_dir>/scripts/`; `renovate_check.py` flags brain scripts that read templates from a
  plugin cache path (`cache-dep`), which break when the cache is purged.
- `courier_preflight.py --account NAME` / `--mark-published … --account` /
  `--set-active-account`: per-account URLs (`url_<account>`, `active_account`) are first-class;
  the courier never re-issues on another account unless the brief says
  `REISSUE ON OTHER ACCOUNT: yes` (brief field `ACCOUNT:`); the re-issue threshold moves from
  300 KB to 600 KB (`--threshold-kb 600`): compacting closed waves alone left pending-heavy
  trackers (400–520 KB) above 300 KB, so they would still get a new URL at every close.
  New `courier-preflight-selftest.py`.
- Policies made unambiguous: the agent budget is **20 per session** (planning run, each wave's
  clean session and a renovation are separate sessions); a ⚠gate verifier that must produce a
  report returns it under `REPORT:` and the main session saves it verbatim (third explicit
  exception to the pure-orchestrator rule); renovate's generator checks apply only to rows
  whose `regen` uses the generators; census drift caused by renovate is a ≤20-line SCOPE fix,
  not a re-plan.

## 0.14.2 — 2026-10-03

- `renovate_check.py` gains the **RULES** block: it resolves the project's auto-memory
  directory (`$CLAUDE_CONFIG_DIR/projects/<sanitized container>/memory/`, override
  `--memory-dir`, skip `--no-rules`) plus the container's `CLAUDE.md`/`AGENTS.md` and the
  brain `README.md`, and flags obsolete protocol notes with a versioned pattern list: old
  protocol versions, pre-0.14 role assignments, the courier spawned as `general-purpose`,
  "read task.md at start", "artifact-courier does not exist", sub-agents sending media
  (`fix`), and prompts-only regen / plans.html by hand / guard-counts-main-only / historical
  version mentions (`review`). Negated or current wordings ("never reads task.md",
  "sub-agents have no SendUserFile", the general-purpose fallback) are not findings; a
  finding already quoted in a `**Superseded (protocol …)**` note is dropped, so the block is
  idempotent. The checker never writes memory and never scans a config dir's own CLAUDE.md
  or ORCHESTRATOR.md. Selftest: 20 cases.
- Renovate's executor brief and `references/renovate.md`: the RULES block appends a dated
  `Superseded` note at the end of a memory file (never edits or deletes a line), marks the
  `MEMORY.md` hook, and edits CLAUDE.md/AGENTS.md lines in place; `review` findings go to
  the owner.

## 0.14.1 — 2026-10-03

- `execution-prompt-architect`: **renovate** — one phrase ("renovate the brain" / "renueva el
  brain al protocolo vigente") upgrades an existing brain to the current protocol without
  re-planning. `templates/renovate_check.py` (stdlib, deterministic) reports per block what is
  missing — `scripts/` copies (and copies them with `--copy-scripts`), `artifacts.json` rows
  without `regen` (with the suggested `--set-regen` command), `execute.md` markers (agent
  types, model rule, status-digest line, `LAST LOG` resume, `Next:`/`blocked`, `SKILLS:` on
  pending waves, protocol line), the `task.md` pending-human section, the code-context skill
  name — plus `--invariants` (counts renovate must not change) and `--all-modules`. Exit 0
  up-to-date · 1 needed · 2 unparsed · 64 usage. `references/renovate.md` is the flow for the
  main session; `templates/renovate-brief.md` the per-block executor brief; `templates/
  renovate-selftest.py` 15 cases (two audit rounds: header prefixes, wrapped skill lines,
  protocol mismatch, symlink-safe copies, unparsed registries, line-cap ordering).
- `execute.md.tmpl` now carries `> **Protocol:** adcm-toolkits <version>` under the title, so
  the checker and future upgrades know which protocol a brain was generated with; a selftest
  case asserts that plugin.json, the template line and the checker version agree.

## 0.14.0 — 2026-10-03

- New `agents/` catalog — the tiers of the orchestration protocol as plugin agent types, so
  the default model and the tool set of a delegation are fixed by the definition, not by the brief:
  `adcm-toolkits:courier` (Sonnet, `artifact-courier` preloaded, no Edit/Write),
  `adcm-toolkits:auditor` (Opus, read-only: Read/Grep/Glob/Bash, effort high),
  `adcm-toolkits:executor` (Sonnet, all tools), `adcm-toolkits:executor-frontend` (Sonnet,
  the `frontend-design` skill preloaded ≈2.5k tokens per spawn, builds inside the `.design/`
  pack), `adcm-toolkits:researcher` (Sonnet by default, `model: opus` per call, web + browser,
  no writes except captures) and `adcm-toolkits:digester` (Sonnet, read-only, status-digest
  fallback). `agents/README.md` has the table and the measured preload cost.
- Delegation rule across the six skills, the execution templates and `orchestrator-rule.md`:
  an `adcm-toolkits:*` type fixes the tool set and the default model; the tier rules still set
  the model per call (`executor` + `model: opus` on ⚠gate waves, `auditor` + `model: sonnet`
  after the Opus quota); `general-purpose` needs an explicit `model`. Briefs carry a `SKILLS:`
  line (the wave's "Skills to load"): area knowledge lives in skills loaded per brief, never in
  per-area agents. Fallback when the plugin is absent: `general-purpose` + explicit model.
- Plugin agents load at the next session or `/reload-plugins`.
- `artifact-guard.py`: the stale-artifacts message now names `adcm-toolkits:courier` (the
  `general-purpose` + `model: sonnet` form stays as the no-plugin fallback); selftest 13/13.

## 0.13.0 — 2026-10-03

- `execution-prompt-architect`: new `templates/status_digest.py` (stdlib, deterministic) answers
  "where did we leave off" from `task.md` in ≤40 lines — project, git state, wave counts and the
  waves in progress / blocked / ready, the newest logbook entry (date, wave, `[PARTIAL]`, next,
  blocked, agents used), pending human actions in any of the four shapes real trackers use,
  and the artifact preflight line. Exit 0 ok · 1 partial · 2 unparsed · 64 usage. `--entry K`
  prints one logbook entry in full; `--json` for tools. Tolerates ES/EN headings in the same
  file, extra glyphs with tags, non-numeric wave ids, malformed rows, unsorted logbooks and
  leftover template placeholders.
- `templates/status-brief.md`: the Sonnet fallback brief used only when the digest exits 2.
- `templates/status-digest-selftest.py`: 28 synthetic cases (RED→GREEN), including the
  silent-failure traps two audit rounds found: rows without a glyph, a mid-line `<!--`,
  undated or indented headings, an unrecognised or header-only pending section, `W2a` vs
  `W2`, "Blocked: None of …" kept as a blocker, and CLI hardening (minimum width, line
  floor with NEXT always kept, `--entry` cap, `..` in `--module`, git timeouts).
- The main session never reads `task.md`, `execute.md` or the plans to learn project state:
  session-start section in SKILL.md, hard rule, `orchestrator-rule.md`, §2/§4 of
  `execute.md.tmpl` and the wave prompt all point to the digest; the script is copied to
  `<docs_dir>/scripts/` at planning time.
- `task.md.tmpl`: logbook entries carry a `Next:` label and new trackers get a canonical
  `## DoD-human pending` table, so the digest needs no heuristics on new projects.

## 0.12.2 — 2026-10-03

- `artifact-courier`: verified that sub-agents have no `SendUserFile` tool (they do have the
  Chrome tools). The courier now always returns `MEDIA: unsent: <paths>` (recording a GIF to
  disk when asked) and the main session sends the files; procedure step 9, SKILL.md and the
  execution-prompt-architect close template say so.

## 0.12.1 — 2026-10-03

- `artifact-courier`: the courier now checks its own tool list first and returns
  `blocked: no Artifact tool in this session` when the Artifact tool is absent (headless
  `-p` runs expose none to any agent), so the main session reports instead of
  investigating. Found in the first end-to-end run.
- `artifact-courier`: `regen: none` marks a hand-maintained HTML (mockups, one-off pages);
  the preflight stops flagging it `needs-regen` and the courier publishes the file as it is.
  Set it with `courier_preflight.py <docs_dir> --set-regen <file> none`. A stamped
  hand-maintained row whose source docs are newer than the HTML is `fresh`, not `regen-due`
  (found in the first end-to-end run: two rows stayed stale after a successful publish).
- `artifact-courier`: procedure step 7 and the brief say where the commit runs — inside the
  repository that contains the registry, which is often nested in a container that is not a repo.

## 0.12.0 — 2026-10-03

- New skill `artifact-courier`: the delivery close of a session runs in one Sonnet
  sub-agent per batch (normally one), never in the main session. `scripts/courier_preflight.py` classifies every
  row of `artifacts.json` (fresh / stale-inplace / stale-reissue above ~300 KB / new /
  missing / needs-regen), runs each row's `regen`, pages the live version the Artifact
  tool requires before an in-place republish, applies the identical-content retry rule,
  re-issues oversized artifacts keeping `previous_url`/`reissued`, stamps `published_at`,
  `version` and `sha256` atomically, sends the visual-check media and returns a status
  table plus the phone-tappable links block the main session pastes verbatim
  (`templates/courier-brief.md`, ≤40 lines).
- `execution-prompt-architect`: `templates/plans-regen.py` — `plans.html` is now generated
  by script from the four plan documents (`--init`, `--check`, ES/EN name sets, wave
  statuses from `task.md`, CSS Gantt from the timeframe) and never hand-rendered; both
  generators and both `.tmpl` shells are copied next to each other into the brain's
  `scripts/` and the exact command lives in the row's `regen`. New `courier` role (Sonnet
  always, one per batch — 1 of the 20 reserved, no Opus quota) and a `capture` role
  for the visual check; closes delegate to it; repo paths, hashes
  and pending DoD-human now sit ABOVE the links block, which is always the last lines.
- `artifact-guard.py` v5: trusts registry stamps (`published_at` ≥ mtime or an equal
  `sha256`) as publish evidence, evaluates the links block once over the union of modules
  closing in the turn, and its stale message points to the courier instead of asking the
  main session to read the live version; still fail-open. Ships
  `artifact-guard-selftest.py` (stdlib, RED→GREEN cases).
- `design-direction-architect`: the contact sheet and the variants page are published by
  the courier; the closing block becomes plain Markdown bullets grouped by label prefix.
- Pure-orchestrator hard rule across the six skills
  (`execution-prompt-architect/references/orchestrator-rule.md`): the main session briefs
  sub-agents with an explicit model, reads their returns and decides; Sonnet executes and
  publishes, Opus investigates and audits; the owner's phrases `sin tanto lío` (one task)
  and `modo directo` (until `modo orquestador`) switch the rule off.

## 0.11.0 — 2026-09-19

- `business-context-generator`: mines EXISTING sources before interviewing — sales
  decks, database migrations and price catalogs, quoting tools, a sibling venture's
  execution docs, brand tokens and memory files — fanning out one sub-agent per
  source family under the same 20-agent tiered protocol; consolidates a fact sheet
  where every fact carries its source path, date, confidence and confidentiality
  class, then interviews only for the UNKNOWNs.
- `execution-prompt-architect` / `references/project-structure.md`: documents the two
  container homes (own ventures `~/<venture>/` vs. client work
  `~/clientes_projects/<client>/`), the three supported positions of `ai-brain`
  (canonical `ai/ai-brain/`, container-root `ai-brain/`, `docs/ai-brain/` + mandatory
  symlink) and why the `artifact-guard` Stop hook only discovers two of them,
  marketplace naming variants (`-admin`, `-common`, `-commercial`, `-platform`,
  `-academic`), the bilingual document-name sets (rule 9, `task.md`/`execute.md`
  never translate), and Day-0 `directory`-source marketplace registration for a
  brand-new client (rule 10).
- `execution-prompt-architect` SKILL.md: filenames now explicitly follow the
  venture's chosen document-name set, not just the interaction language; orchestrator
  direct fixes (the ≤~20-line escalation-ladder shortcut) must be LOGGED in the
  `task.md` logbook; Step 7 reworked into "the visual artifacts" — `plans.html`
  (stakeholders) plus `prompts.html` (the operator, on a phone; regenerated from
  `execute.md` §7's `### Wave <ID>` headers, never hand-edited) — both registered in
  `artifacts.json` and republished on change; the registry/guard discovery
  documented against the two positions it can actually see.
- Templates: `execute.md.tmpl`, `wave-prompt.tmpl` and `task.md.tmpl` gained the
  `orchestrator fix:` logbook field, the `prompts.html` regeneration step
  (`prompts-regen.py`) in the doc-sync close, and the doc-name-set note in every
  "keep the document name" instruction (6 templates). Ships `prompts-regen.py` +
  `prompts-html.tmpl` — the `prompts.html` generator script and its HTML shell.
- `code-project-context-generator`: container/brain detection now points at
  `project-structure.md`'s "Where ai-brain may live" and documents the
  `-common`/`-platform`/`-commercial` marketplace variants.

## 0.10.0 — 2026-09-15

- Reuse-first planning, comment policy, and a code-simplifier pass over every wave's
  integrated diff before the final DoD run.

## 0.9.1 — 2026-09-15

- `design-direction-architect`: the research phase before any UI is built.

## 0.9.0 — 2026-09-07

- `agentic-seo-report`: SEO + agent-readiness audits with confidentiality
  guardrails.

## 0.8.0 — 2026-09-06

- Orchestrator/auditor/executor tiers (Fable orchestrates, Opus audits and runs
  gates, Sonnet implements) with an escalation ladder.

## 0.7.1 — 2026-09-05

- Agent budget of 20 with tiered roles (executor implements, opus/sonnet
  sub-agents audit).

## 0.7.0 — 2026-09-02

- Hard cap of 5 sub-agents per phase and per wave session (the multi-agent effort mode included).

## 0.6.6 — 2026-09-02

- Close block always delivers `localhost` alongside the LAN IP.

## 0.6.5 — 2026-09-02

- `artifact-guard` v3 enforces the close-links FORMAT (Markdown link per line, last
  lines of the message, nothing after).

## 0.6.4 — 2026-08-28

- Closes are read on a phone: tappable links + media last.

## 0.6.3 — 2026-08-28

- Hardened `artifact-guard` against review findings.

## 0.6.2 — 2026-08-28

- Published artifacts registry + deterministic close guard (plus pre-publish review
  fixes).

## 0.6.1 — 2026-08-27

- Two hard rules learned in real wave execution; everything AI lives under `ai/`
  (`ai/ai-brain` + `modules/<mod>` lazy doc).

## 0.6.0 — 2026-08-25

- Codified the project container convention (`projects/` grouping, one git repo per
  engineering project, ALL docs in `ai-brain`; review fixes and template sync).

## 0.5.0 — 2026-08-17

- Self-contained wave prompts + usage-map (shared surfaces → consumer census).

## 0.4.0 — 2026-08-03

- Added the `business-context-generator` skill.

## 0.3.2 — 2026-07-04

- Project name + timeframe plan + Timeline Gantt.

## 0.3.1 — 2026-06-25

- Baked the code-legibility (anti indentation-hell) convention into generated
  plans; wave Status markers enforced at close (§7); mandatory VISUAL CHECK for UI
  waves.

## 0.3.0 — 2026-06-12

- Added the `execution-prompt-architect` skill.

## 0.1.0 — 2026-06-06 / 2026-06-07

- Initial public release; `code-project-context-generator` enhanced into a richer,
  refreshable knowledge base; marketplace translated to English with per-skill
  READMEs.
