# Changelog — adcm-toolkits

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

- Hard cap of 5 sub-agents per phase and per wave session (ultracode included).

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
