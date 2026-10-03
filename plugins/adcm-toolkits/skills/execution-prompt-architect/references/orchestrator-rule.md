# The pure-orchestrator rule

Canonical text; SKILL.md, `execute.md` §1.7 and every wave prompt's WORKFLOW point here.

In any substantive task the main session is a **pure orchestrator**: it analyzes, writes
briefs, launches sub-agents with an explicit `model`, reads their RETURNs and
decides/integrates. It does NOT execute the task itself:

- no reading files in bulk (a sub-agent reads; the RETURN carries what matters), no
  editing at scale, no browsing, scraping or screenshotting;
- no rendering or regenerating HTML, no calling the Artifact tool, no assembling the
  links block (the `artifact-courier` does all of it).

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

## `model` on EVERY delegated call

Every `Agent` and every Workflow `agent()` call names its `model` — packaged agents
included, and the built-in Plan and Explore types too: a Plan agent called without
`model` inherits the main session's model. The plugin's frontmatter is irrelevant.

## Tiers

| Tier | Does | Never |
|---|---|---|
| Main session (orchestrator) | Decides design and scope, audits deliverables, writes briefs, runs the DoD, integrates | Executes, reads in bulk, renders, publishes, browses |
| `opus` (quota 10 per session; 2 reserved) | Investigates, audits, reviews regression, verifies gates, implements ⚠gate waves | Decides scope |
| `sonnet` | Executes, renders, publishes (courier), researches, runs scripts | Self-approves |
| `haiku` | Inventory-only tasks: listing, counting, grepping, file-existence checks | Anything that needs judgement |

When the main session is not the top tier, every row moves one tier down; the courier
stays `sonnet` regardless. Budget 20 agents per session, `SendMessage` to a live agent
costs 0.

## Brief format (≤40 lines)

`TASK` (ID + title) · `FILES` (what to read or touch, and why) · `DELIVERABLE` (the
output, with the orchestrator's decisions applied) · `DOD-SLICE` (`command → expected
result`, run before returning) · `STOP IF` (conditions to stop and report instead of
improvising) · `FORBIDDEN` (paths, actions, dependency changes) · `RETURN` (exact shape
of the answer). The brief carries the investigation; the sub-agent never re-derives it.

## RETURN: short and structured

A sub-agent returns a compact structured text: files touched, commands run with their
real output, rulings and open questions. It never returns HTML or whole files — the
artifact is the file on disk or the published URL, not the message. A bare "done" is not
a RETURN. The orchestrator reads the RETURN, verifies the DoD-slice itself and decides.
