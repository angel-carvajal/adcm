# Extraction guide — STEP 6

Turn the surviving references into something a builder can execute without
seeing them.

## Delegate the token work

**Open mode only.** In `mode: structure-only` skip this section and the palette
and type extraction below — the DS is the source of truth; see
`structure-only-mode.md`.

If the **`extract-design-system`** skill is available, use it against the
finalists' live demo URLs rather than reimplementing extraction here. It already
pulls primitives from a public site and emits starter token files. Feed its
output into `.design/tokens.css`, then reconcile against the brand constraints
from Q7 — **brand wins over reference, always**.

Only extract by hand when that skill is absent — and then work from the
extractor JSON captured in STEP 3: `typeScale` → §2, `ground`/`ink` → §3,
`radii`/`motion` → §5, `sections` vs `mobileSections` → §6.

## What to extract

### 1. Section map
The ordered list of sections for *this* project — not a copy of the reference's.
For each: purpose, the reference it comes from, approximate viewport height, and
what carries it (type, image, video, product, data).

### 2. Type system
Display and body families with a real fallback stack. The scale as actual
values, not adjectives. Weights in use. Line-height per role. Measure cap.
Letter-spacing where it is deliberate.

### 3. Palette
Ground, surface, ink, muted ink, border, accent, and accent-on-accent. Record
**contrast ratios** for every text-on-ground pair — a palette that fails WCAG AA
is a palette you will rebuild later. Define light and dark if both are in scope.

### 4. Spacing and rhythm
The base unit and the scale built on it. Section padding at each breakpoint.
Whether the page's pace is even or accelerating toward the CTA.

### 5. Motion inventory
One row per moving thing: element, trigger, property, duration, easing, and
whether it respects `prefers-reduced-motion`. If Q8 said static or subtle and
the inventory has more than five rows, cut it back now rather than at build time.

### 6. Responsive behavior
What reflows, what stacks, what is dropped outright on mobile. For a commercial
page, name explicitly where price and CTA sit in the **mobile** order — that is
where most designs quietly break.

### 7. Anti-patterns for this project
Merge: the chosen style's anti-patterns, the Q5 hated references, and everything
learned from the STEP 5 rejections. This list is what stops the builder from
drifting back to generic.

## Reconciliation rules

1. **Brand beats reference.** Locked logo, palette or typeface from Q7 overrides
   anything extracted.
2. **Accessibility beats aesthetics.** If the reference's contrast fails, adjust
   the token and note it in `decisions.md`; do not copy the failure.
3. **Budget beats ambition.** The motion inventory must fit the Q8 budget and
   performance floor. Trim here, not later.
4. **One source of truth.** Every value lands in `tokens.css`. The brief
   describes; it does not redefine.

## Sanity check before writing

- Can a builder produce a first draft from `brief.md` + `tokens.css` alone,
  without opening a single reference URL? If not, the extraction is incomplete.
- Does any section in the map lack a stated reference and a stated purpose?
- Does the motion inventory contradict the stated performance floor?
