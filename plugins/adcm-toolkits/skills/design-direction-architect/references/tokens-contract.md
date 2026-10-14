# Tokens contract

The frozen set of CSS custom properties every option page consumes and `design-board adopt` emits.
The tokens exported from the board are the source of truth; options and builds read them, never
redefine them. Packs written before 0.18.0 used `--ground/--ink/--accent`: regenerate with
`design-board adopt`.

## The variables

| Group | Names |
|---|---|
| Fonts | `--font-display --font-body --font-mono` |
| Scale | `--step--1 --step-0 --step-1 --step-2 --step-3 --step-4 --step-5` (rem, from base and ratio) |
| Type detail | `--leading-tight --leading-body --tracking-display` |
| Color (8 roles) | `--color-ground --color-surface --color-ink --color-ink-muted --color-primary --color-accent --color-accent-ink --color-border` |
| Static | `--space-1 … --space-6 --radius --dur --ease` |

`adopt` also appends a `prefers-reduced-motion` block that sets `--dur: 0ms`. Output shape of
`design-board adopt --dry "a/f1/r1.2/p1" .` (values illustrative):

```css
:root {
  --font-display: "Fraunces", Georgia, serif;
  --step-0: 1.063rem;   /* base 17px ÷ 16 */
  --step-1: 1.275rem;   /* ×ratio each step up, ÷ratio each step down */
  --color-ground: #F7F3EC;
  --color-accent-ink: #FFFFFF;
  /* …every name in the table, in this order… */
}
@media (prefers-reduced-motion: reduce) { :root { --dur: 0ms; } }
```

`adopt` also writes `tokens.json` (`combo`, `option`, `fonts`, `scale{base,ratio}`, `palette`, `colors`,
`vars`) and sets `decisions.chosen`. `--dry` prints without writing.

## Rules for option pages

1. No color, font or size literal outside the `:root` block. Everything else is `var(--…)`.
   `design-board check` greps for it and fails the page.
2. The bridge snippet from `templates/variant-bridge.html` (marked `data-board-bridge`) is mandatory in
   every option. It applies the variables the board posts by `message` and loads the chosen Google Font.
   `check` requires the marker and `var(--font-display)`.
3. The `:root` block carries the defaults of the option's first combo, so the page renders on its own.
4. Real reflow: a stepped-up scale and columns under `@media (min-width: 1024px)`.
5. No framework, no external images, no copy taken from references.

## What the toggles change

Only three things: the fonts (display, body, optional mono), the scale (base and ratio, which move the
seven `--step-*`), and the eight color roles. Leading, tracking, spacing, radius and motion stay as
`adopt` writes them. In structure-only mode the toggles are locked to the design-system values (see
`structure-only-mode.md`).

## The combo code

`option/fontPairId/ratioPart/paletteId`, where `ratioPart` is `r<ratio>[b<base>]` or a `scalePresetId`.
Examples: `b/f2/r1.25/p1`, and `b/f2/r1.25b18/p1` (base 18px). The board emits `b<base>` only when the
base differs from the option's preset. `adopt` resolves it
against `board.d/options.json` and `board.json`. `adopt --file tokens.json` re-applies an exported file.

## `board.d/options.json` (written by the variants executor)

```json
{ "options": [ { "id": "a", "name": "…", "idea": "…", "refs_used": ["ref-id"],
  "how_made": ["≤4 lines"], "why": ["≤3 lines"], "what_changes_if_picked": "…", "cost": "…",
  "fonts": [ { "id": "f1", "display": "fontId", "body": "fontId", "mono": "fontId (optional)" } ],
  "ratios": [1.2, 1.25],
  "palettes": [ { "id": "p1", "label": "…", "colors": { "ground": "#RRGGBB", "surface": "…", "ink": "…",
    "ink-muted": "…", "primary": "…", "accent": "…", "accent-ink": "…", "border": "…" } } ] } ] }
```

Exactly ids `a`, `b`, `c`. 3–5 font pairs, 2–3 ratios, 2–3 palettes per option; every `fontId` exists in
`tokens.fontShortlist`, every color is `#RRGGBB`, and each palette keeps text-on-ground contrast at AA.
`refs_used` ids must resolve to references that are not dropped. Run `design-board check .design` and
`design-board capture --variants` before returning.
