# The pure-orchestrator rule

Canonical text; SKILL.md, `execute.md` §1.7 and every wave prompt's WORKFLOW point here.

In any substantive task the main session is a **pure orchestrator**: it analyzes, writes
briefs, launches sub-agents with an explicit `model`, reads their RETURNs and
decides/integrates. It does NOT execute the task itself:

- reading files, editing at scale, browsing and screenshots belong to sub-agents (the RETURN carries what matters);
- rendering HTML, publishing Artifacts and assembling the links block belong to the `artifact-courier`;
- the state of a project comes from one `status-digest` call, never from `task.md`, `execute.md` or the plans
  (see "Status questions").

## Enforced by hooks

The plugin's hooks impose these; the reason a denial prints names the way out. Do not restate them in prompts; the one exception is the mandatory 3-line guard note at the top of every phase prompt.
- `main-thread-guard` (every tool call of the main thread):
  - T0 tamper: the guard's own state dir is untouchable.
  - R1 lock at the 3rd compaction and R1b handoff gate at the 2nd: only handoff and memory writes pass until a handoff exists.
  - M1: a memory index line longer than 150 chars is denied.
  - R6 status turn: the 4th tool call of a status question is denied.
  - R3 heavy reads: images and PDFs, whole-file reads over 40 KB or of `task.md`, `execute.md`, plans, `plans.html`, `prompts.html`, bulk dumpers.
  - X1: browser MCP tools and any Artifact action other than open, list, pin, unpin.
  - X2 edit cap: more than 20 lines per Write or Edit, except handoffs, memory files and `qa/*.md`.
  - R2 budget: 25 Bash/Grep/Glob and 8 Read calls per main session.
- `merge-guard` (PreToolUse): merge commands and merge APIs are denied; Claude never merges.
- `artifact-guard` (Stop): the links block appears once per delivery close, as the last lines, from the last courier RETURN.
- Not enforced by any hook, so they stay rules: the agent budget and roles, the model on every call, briefs of at most 40 lines,
  the logged shortcut, MR assigned to the Reviewer with wave N+1 waiting for the merge, no URLs from any agent but the courier.

## Exceptions (three, nothing else)

1. **The ≤20-line shortcut.** A fix of about 20 lines or fewer when writing the brief
   would cost more than the change. Every one is logged in the `task.md` logbook
   (`orchestrator fix: <file> — <why a brief cost more>`); an unlogged edit is a
   protocol violation.
2. **The user's escape hatch**, in the user's own words:
   - `sin tanto lío` — direct mode for THAT task or turn only.
   - `modo directo` — direct mode stays on until the user says `modo orquestador`.

   In direct mode the main session does everything itself and the guard lifts R2, R3, R6, X1 and X2
   (never T0, R1, R1b, M1). Never infer it from tone or from the task looking small.
3. **Verbatim saves.** Saving a sub-agent's RETURN unchanged to the path the brief names
   (gate reports `qa/gate-<w>.md` or the brain's existing `qa/<wave>/gate-*.md` layout, digests) is a mechanical save, not an edit.

## Merge, links, media

- A wave ends with its MR open, pipeline green, simplify pass done and assigned to the Reviewer (`> **Reviewer:**` in execute.md); the merge is a DoD-human item and wave N+1 starts only after MR N is merged (merge policy: wait).
  The docs repo (ai-brain) and the marketplaces commit and push to main directly.
- The links block is the last RETURN's block of the last courier, pasted once per delivery close. Progress turns, 'Para ti' notes, answers and audits carry no links and no `=== LINKS ===` marker. No agent other than the courier returns URLs.
- Media: a sub-agent cannot load SendUserFile, so it returns `MEDIA: unsent: <paths>`. The main session sends them with SendUserFile by path WITHOUT opening them
  (load it with ToolSearch `select:SendUserFile`). Judging screenshots is always a sub-agent's job; the guard denies image reads on the main thread.

## Phase sessions and doc-sync

- A wave runs as phase sessions, one clean session per phase: a implement + DoD · b gate · c gate fixes · d doc-sync + courier close · e merge close (production close when the wave deploys; a no-deploy wave gets the mini e, then `Next phase: none`). Each phase prompt has one launch line outside its fenced block (`/model` and `/effort`); every phase close runs `spend-report --phase <letter>` and copies its line 1 into the handoff `Spend:` label, next to `DoD recipe:` and `Traps:`. Side tasks that surface mid-phase (a memory-index warning) are queued and done at the close, never mid-run.
  A phase never continues into the next one: it ends with `HANDOFF: <path>` and one sentence telling the owner to /clear and paste the next phase prompt.
- Doc-sync is always a sonnet executor, from `templates/docsync-brief.md`, in two phases. A builds the edit sheet and the markers file and leaves
  `docsync-apply --check` clean, writing no doc. B (by `SendMessage` with the marker values and the answers; exempt from the 5-minute rule) pulls, runs `--check`, `--write`,
  `status-digest`, commits by explicit path and pushes. When a doc-sync changes a LATER wave's plan, the closing phase re-audits those waves in
  scoped mode (`plan-audit --check` exit 2, scoped `plan-audit-brief.md`, `--seal`) before it closes; done or started waves are exempt. The main session never writes or edits a sheet; in phase d the handoff comes before B.

## Notify the owner
Only the main session notifies (no brief asks a sub-agent to). When a turn ends on (1) a delivery close, (2) a stop that needs the
owner — a decision, a permission, a DoD-human step — or (3) a failed gate — auditor `fix-first`, DoD-auto red — call the
native `PushNotification` tool ONCE, right BEFORE the final message (after any media): nothing follows the links block.
- Fixed text, one line: `Claude finished in <folder>` for (1), `Claude needs you in <folder>` for (2) and (3); `<folder>` is the
  project directory's name. No wave detail, no markdown. Pass `status: "proactive"`.
- It is deferred: load it with `ToolSearch` query `select:PushNotification`. No such tool → skip silently.
- A "not sent" result means the owner is at the terminal: fine, never retry, never mention it.
- One per stop. If the plugin's Stop hook asks for it in a turn you already notified, end the turn with no text.

## Status questions

On a session start or a status question ('where did we leave off', 'dónde nos quedamos', 'project status', 'qué sigue') the main
session makes ONE call: `status-digest --brain <docs_dir> [--module modules/<mod>] --mrs` (the plugin's `scripts/launchers/` launcher, bare:
nothing before it; without the plugin `python3 <path> --brain <docs_dir>`, `<path>` = `templates/status_digest.py` or the brain's
`scripts/status_digest.py`). It answers from that output, with the links it printed; when the digest prints STALE it says so;
it offers to dig deeper and never investigates silently (the guard caps a status turn at 3 calls; the 4th is denied, rule R6).
`--prompt [WAVE:PHASE]` prints the exact next phase prompt. Exit 0 ok · 1 partial (the digest is enough) · 2 unparsed: ONE
`Agent(subagent_type: "adcm-toolkits:digester")` with `templates/status-brief.md` (1 of the 20, 0 Opus quota) · 64 usage. `--entry [K]` prints a logbook entry (≤40 lines).

## `model` on EVERY delegated call

Every `Agent` and every Workflow `agent()` call either names its `model` or uses an
`adcm-toolkits:*` type. A per-call `model` overrides the type's default: `researcher` +
`model: opus` for Opus investigations, `executor` + `model: opus` for ⚠gate waves and
Opus-written sections, `auditor` + `model: sonnet` once the Opus quota is spent; types fix the TOOL SET, the tier rules still set the model.
The built-in Plan and Explore types and any other packaged agent still need an explicit
`model`: a Plan agent called without `model` inherits the main session's model. The `executor`, `executor-frontend` and `researcher` types default to `effort: medium`; ⚠gate `executor` calls and `researcher` + `model: opus` calls pass `effort: high` per call. The role
agents load at the next session or on `/reload-plugins`.

## Tiers

| Tier | Agent type | Does | Never |
|---|---|---|---|
| Main session (orchestrator) | — | Decides design and scope, audits deliverables, writes briefs, runs the DoD, integrates | Executes, writes doc-sync, opens screenshots, renders, publishes, browses, merges an MR / pushes code to the default branch, prints links in progress turns |
| `opus` (quota 10 per session; 2 reserved) | `adcm-toolkits:auditor` (reviews, gate verifier) · `adcm-toolkits:researcher` + `model: opus` (investigations) · `adcm-toolkits:executor` + `model: opus` (⚠gate waves) | Investigates, audits, reviews regression, verifies gates, implements ⚠gate waves | Decides scope; merges an MR / pushes code to the default branch |
| `sonnet` | `adcm-toolkits:executor` · `adcm-toolkits:executor-frontend` (UI and frontend-code waves — when the wave loads design skills OR the task's FILES are frontend app code (components, pages, hooks/composables, client services/stores); cost: the `frontend-design` preload, ~3.1k tokens) · `adcm-toolkits:researcher` (default; also the capture role: browser, no edits) · `adcm-toolkits:courier` · `adcm-toolkits:digester` | Executes, renders, publishes (courier), researches, captures, runs scripts, digests status | Self-approves; merges an MR / pushes code to the default branch; returns URLs (only the courier does) |
| `haiku` | `general-purpose` + `model: haiku` | Inventory-only tasks: listing, counting, grepping, file-existence checks | Anything that needs judgement |

The types fix the tool set; the tier rules above still set the model of each call. When
the brief's DoD includes the VISUAL CHECK, `executor-frontend` captures it itself — never
both it and a capture agent. The orchestrator never implements first and never audits or verifies a diff in its own context; every audit goes to a fresh agent at the tier the table names, whatever the main model (an Opus auditor under an Opus main is fine); the simplify pass runs `model: opus` in a fresh context. The courier is `sonnet`. The orchestrator never raises a STOP IF mid-run: it adopts the verifier's minimal fix unless it cites evidence, and logs each override as `override: <reason + evidence>`. No plugin in this session →
`Agent(subagent_type: "general-purpose", model: "<tier>")` with the same brief. Budget 20 agents per session. `SendMessage` adds 0 to the agent counter but re-reads the agent's whole context: resume only the same task with < 5 min idle; otherwise a NEW executor with a relay file of ≤ 40 lines, counted against the 20 (exempt: courier retry and doc-sync phase B).

## Brief format (≤40 lines)

`TASK` (ID + title) · `FILES` (what to read or touch, and why; the brain map `<docs_dir>/map/` when the brain has one — absolute, because worktrees lack the `ai-brain` symlink) · `SKILLS` (the wave's
"Skills to load": what the executor loads with `Skill` before starting) · `DELIVERABLE` (the
output, with the orchestrator's decisions applied) · `DOD-SLICE` (`command → expected
result`, run before returning) · `STOP IF` (conditions to stop and report instead of
improvising) · `FORBIDDEN` (paths, actions, dependency changes) · `RETURN` (exact shape
of the answer). The brief carries the investigation; the sub-agent never re-derives it.

## RETURN: short and structured

A sub-agent returns a compact structured text: files touched, commands run with their
real output, rulings and open questions. It never returns HTML or whole files — the
artifact is the file on disk, not the message. RETURN carries file paths and summaries, never URLs or a links block; only the courier returns links. A bare "done" is not
a RETURN. The executor's RETURN also carries the `REUSED` line and the `RULE-OF-TWO` line: rule-of-two entries follow the wave LOOP rule, resolved by the orchestrator (every implicated file in SCOPE → extract in-wave, helper first; any file outside → follow-up in the logbook Reuse field), and `born` helpers feed the map refresh at doc-sync (§2b step 6, via `--human`). The orchestrator reads the RETURN, verifies the DoD-slice itself and decides.
