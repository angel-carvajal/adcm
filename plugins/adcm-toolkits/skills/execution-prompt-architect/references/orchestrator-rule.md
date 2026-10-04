# The pure-orchestrator rule

Canonical text; SKILL.md, `execute.md` §1.7 and every wave prompt's WORKFLOW point here.

In any substantive task the main session is a **pure orchestrator**: it analyzes, writes
briefs, launches sub-agents with an explicit `model`, reads their RETURNs and
decides/integrates. It does NOT execute the task itself:

- no reading files in bulk (a sub-agent reads; the RETURN carries what matters), no
  editing at scale, no browsing, scraping or screenshotting;
- no rendering or regenerating HTML, no calling the Artifact tool, no assembling the
  links block (the `artifact-courier` does all of it);
- no reading `task.md`, `execute.md` or plan docs to learn the state of a project — the
  status digest answers it (see "Session start").

## Exceptions (two, nothing else)

1. **The ≤20-line shortcut.** A fix of about 20 lines or fewer when writing the brief
   would cost more than the change. Every one is logged in the `task.md` logbook
   (`orchestrator fix: <file> — <why a brief cost more>`); an unlogged edit is a
   protocol violation.
2. **The user's escape hatch**, in the user's own words:
   - `sin tanto lío` — direct mode for THAT task or turn only.
   - `modo directo` — direct mode stays on until the user says `modo orquestador`.

   In direct mode the main session does everything itself. Never infer it from tone or
   from the task looking small.

## Session start: the status digest

When the user opens or resumes a project ('where did we leave off', 'dónde nos quedamos',
'project status'), the main session runs `python3 <path> --brain <docs_dir> [--module
modules/<mod>]` — `<path>` is `execution-prompt-architect/templates/status_digest.py` or the
brain copy `<docs_dir>/scripts/status_digest.py` — and reads only its ≤40 lines. Exit 0 ok · 1
partial (digest printed, `DIGEST: partial(<parts>)`): the digest is enough, spawn the fallback
only if the missing part matters · 2 unparsed: always ONE `Agent(subagent_type:
"adcm-toolkits:digester")` with `execution-prompt-architect/templates/status-brief.md`
(1 of the 20, 0 Opus quota; the type fixes `sonnet` and read-only tools) · 64 usage error. `--entry [K]` prints the K-th newest logbook entry
in full (≤40 lines).

## `model` on EVERY delegated call

Every `Agent` and every Workflow `agent()` call either names its `model` or uses an
`adcm-toolkits:*` type. A per-call `model` overrides the type's default: `researcher` +
`model: opus` for Opus investigations, `executor` + `model: opus` for ⚠gate waves and
Opus-written sections, `auditor` + `model: sonnet` once the Opus quota is spent or when the
main session is one tier down; types fix the TOOL SET, the tier rules still set the model.
The built-in Plan and Explore types and any other packaged agent still need an explicit
`model`: a Plan agent called without `model` inherits the main session's model. The role
agents load at the next session or on `/reload-plugins`.

## Tiers

| Tier | Agent type | Does | Never |
|---|---|---|---|
| Main session (orchestrator) | — | Decides design and scope, audits deliverables, writes briefs, runs the DoD, integrates | Executes, reads in bulk, renders, publishes, browses |
| `opus` (quota 10 per session; 2 reserved) | `adcm-toolkits:auditor` (reviews, gate verifier) · `adcm-toolkits:researcher` + `model: opus` (investigations) · `adcm-toolkits:executor` + `model: opus` (⚠gate waves) | Investigates, audits, reviews regression, verifies gates, implements ⚠gate waves | Decides scope |
| `sonnet` | `adcm-toolkits:executor` · `adcm-toolkits:executor-frontend` (UI waves) · `adcm-toolkits:researcher` (default; also the capture role: browser, no edits) · `adcm-toolkits:courier` · `adcm-toolkits:digester` | Executes, renders, publishes (courier), researches, captures, runs scripts, digests status | Self-approves |
| `haiku` | `general-purpose` + `model: haiku` | Inventory-only tasks: listing, counting, grepping, file-existence checks | Anything that needs judgement |

The types fix the tool set; the tier rules above still set the model of each call. When
the brief's DoD includes the VISUAL CHECK, `executor-frontend` captures it itself — never
both it and a capture agent. When the main session is not the top tier, every row moves
one tier down; the courier stays `sonnet` regardless. No plugin in this session →
`Agent(subagent_type: "general-purpose", model: "<tier>")` with the same brief. Budget 20 agents per session, `SendMessage` to a live agent
costs 0.

## Brief format (≤40 lines)

`TASK` (ID + title) · `FILES` (what to read or touch, and why) · `SKILLS` (the wave's
"Skills to load": what the executor loads with `Skill` before starting) · `DELIVERABLE` (the
output, with the orchestrator's decisions applied) · `DOD-SLICE` (`command → expected
result`, run before returning) · `STOP IF` (conditions to stop and report instead of
improvising) · `FORBIDDEN` (paths, actions, dependency changes) · `RETURN` (exact shape
of the answer). The brief carries the investigation; the sub-agent never re-derives it.

## RETURN: short and structured

A sub-agent returns a compact structured text: files touched, commands run with their
real output, rulings and open questions. It never returns HTML or whole files — the
artifact is the file on disk or the published URL, not the message. A bare "done" is not
a RETURN. The orchestrator reads the RETURN, verifies the DoD-slice itself and decides.
