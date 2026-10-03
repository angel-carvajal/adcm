# Handoff guide — STEP 7

This skill's output is a direction. Someone else builds. Name that someone, and
tell them exactly what to read.

## Routing

| Situation | Hand to |
|---|---|
| Scroll-driven, pinned sections, video, "cinematic" | `epic-design` |
| Craft, visual hierarchy, consistency, design review | `interface-design` (plus `design-review`, `design-deslop`) |
| General production build, React/Next | `frontend-design` |
| Full design system, brand, tokens at scale | `ui-ux-pro-max` (`design-system`, `brand`, `ui-styling`) |
| Micro-interaction, animation polish, the invisible details | `emil-design-eng` / `interaction-design` |
| A specific component the user picked | `mcp__magic__get_component` at build time |
| Anti-slop pass before shipping | `design-taste-frontend` |
| Charts or data surfaces in scope | `dataviz` |
| Deliverable is a published page, not a repo | `artifact-design` |

More than one usually applies. Order them: structure first, then polish.

## Phrasing the handoff

Do not summarize the pack in prose — point at it. A good handoff is short:

> Direction is locked in `.design/brief.md`, tokens in `.design/tokens.css`,
> product section spec in `.design/commerce.md`, asset manifest in
> `.design/assets.md`. Build the landing page with `epic-design`, following the
> section map in the brief. Do not re-choose the direction. Two hero images are
> marked `REAL-PHOTO-NEEDED` — leave placeholders and flag them.

## Pre-handoff checklist

- [ ] Every URL in `.design/references.md` was actually visited this session.
- [ ] `tokens.css` contains no value that contradicts a Q7 brand constraint.
- [ ] Contrast ratios recorded for every text-on-ground pair.
- [ ] Motion inventory fits the Q8 budget.
- [ ] `commerce.md` exists if the business sells something, and its flow matches
      the real quoting logic where one exists.
- [ ] Every asset marked `atmosphere` or `REAL-PHOTO-NEEDED`.
- [ ] No API key anywhere in `.design/`.
- [ ] Sources that were unavailable are named as gaps in `decisions.md`.

## Closing link block

End the handoff with the clean, phone-readable block defined in
`variant-preview.md` — plain bullets grouped by label prefix, nothing broken,
nothing extra, no headers, no columns, no code fence. The owner reviews from a
phone; a wall of raw URLs is unusable there. STEP 7 adds the third group the
earlier blocks lack, labeled PACK (the Commerce bullet only if the business sells):

- [📦 PACK · Brief](<repo or published URL of .design/brief.md>)
- [📦 PACK · References](<… references.md>)
- [📦 PACK · Tokens](<… tokens.css>)
- [📦 PACK · Commerce](<… commerce.md>)
- [📦 PACK · Assets](<… assets.md>)
- [📦 PACK · Decisions](<… decisions.md>)

Published or repo links only — never a local path a phone cannot open.

## `--update`

Re-runs STEP 3 → STEP 7 without the interview. Read the existing
`.design/brief.md` as the locked direction, keep `decisions.md` and append to it
with a new dated block. Use it when the direction held but the references went
stale, or when a new commercial surface was added to the project.

Do not use `--update` to change the direction — that is a fresh run.
