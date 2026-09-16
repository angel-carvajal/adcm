# Structure-only mode — STEP 0 branch

Triggered by the STEP 0 repo probe (SKILL.md) when a design system or token
file already exists. The goal reframes: research the HOW — section anatomy,
pacing, commerce/quote flow, motion inventory. The WHAT — palette, type,
brand register — is fixed. Spend the run's budget on structure, not on
re-deriving tokens the project already has.

## What to read in the repo

Before asking anything, read what STEP 0 found:

| Look for | Tells you |
|---|---|
| Tokens file (`tokens.css`, `tokens.json`, `theme.ts`) | Palette, type scale, spacing, radii, motion durations — verbatim |
| `tailwind.config.*` | Token names as Tailwind consumes them, breakpoints |
| `*design-system*` doc | Register/voice already written down — quote it, don't reinterpret |
| `docs/specs/**`, domain docs | Process-phase names, business vocabulary the section map must use |

If a design-system doc names the register explicitly ("editorial", "brutalist
warmth", whatever), that is the confirmed register — do not re-derive it from
the style taxonomy.

**Partial status:** if the DS locks some tokens but not others (palette fixed,
type open, say), map the locked ones in tokens.css's LOCKED VARIANT block and
derive the rest the normal open-mode way. Structure scoring below still
applies in full; style-fit scores against whatever is locked.

## Interview changes

- **Q3 (style):** a confirm line, not a multi-select. State the detected
  register and ask for a yes or a custom label:
  > "Detected register: {{REGISTER}} — from {{DS_PATH}}. Keep this label, or
  > name it differently?"
  A custom label is allowed; it does not change the underlying tokens.
- **Q7 (brand constraints):** also a confirm line. Palette and type are
  already locked by the DS — state that and move on, never ask the open
  question from full mode.
- Q1, Q2, Q4–Q6, Q8, Q9 run unchanged — they're about the business and the
  build, not the brand.

## STEP 3 / STEP 4 — scoring

All nine rubric dimensions still score, and the cuts on 6 (feasibility) and
8 (accessibility headroom) stay in force. What changes is the weight and the
yardstick:

| Rubric dimension | In structure-only mode |
|---|---|
| 1 Style fit | scored against the **locked register** from the DS, not the taxonomy |
| 3 Section coverage | heaviest weight — does the section anatomy fit this business's flow? |
| 5 Motion fit | concrete techniques worth stealing (reveal, parallax, pin), against the Q8 budget |
| 9 Commercial fit | does the conversion pattern match Q9's answer? |
| 2, 4, 6, 7, 8 | unchanged |

A reference is never kept or dropped for its palette or type — those are fixed
by the DS and carry no score.

## STEP 5b — curation

Consumes the project's own tokens verbatim. Do not re-extract or re-derive
values from the surviving references — the DS is the source of truth. 5b's
job narrows to confirming structure choices (section order, motion picks),
not producing a palette.

## STEP 6 — brief assembly

Emits the section map and the motion inventory. The **Style** block still
carries the register confirmed in Q3 plus the motion budget and stack. In
**Composition**, the **Palette** and **Type system** rows read
`locked — {{DS_PATH}}` instead of a reference key: no reference contributes them.
Delegates nothing to `extract-design-system`: that skill exists for open
mode, and structure-only mode never calls it, because there is nothing left
to extract.

## brief.md and tokens.css in structure-only mode

- `brief.md`'s **Business context** records `Brand status: locked|partial —
  {{DS_PATH}}`.
- `tokens.css`'s LOCKED VARIANT block (top of the template) maps DS token
  names to the names brief.md uses. It never restates a value — every row is
  `var(--ds-name)`. New tokens the brief needs but the DS lacks go in the
  "New tokens proposed" block below it, flagged for a PR to the DS, never
  invented as bypass values.
