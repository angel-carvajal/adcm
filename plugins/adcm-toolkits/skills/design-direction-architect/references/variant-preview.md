# Variants and the mobile review — STEP 5b

Scores and adjectives do not let anyone picture the result. Before the owner
commits to a direction, build **three fast variants of one page, using the
project's real brand**, and publish them where they can be judged from a phone.

This step exists because "structure from A, palette from B" is impossible to
imagine and trivial to recognize.

## Inputs 5b may use

5b runs before STEP 6, so most of `.design/` does not exist yet. It writes one file so the
variants use real tokens instead of reference colors:

- **`.design/tokens.css`, written provisional here** — verbatim from the project's own
  design system in structure-only mode; otherwise seeded from the owner's Q7 answers,
  filling gaps with the values the surviving references converge on. STEP 6 refines this
  file, never restarts it.
- Q7 answers and the surviving references, already in hand from STEP 5.
- `.design/refs/*.png` — the captures from STEP 3; the review page shows them beside
  each interpretation.
- Nothing written by later steps — `assets.md`, `commerce.md`, `references.md` don't
  exist yet; build with placeholders, not their output.

## What to build

**One page only** — the highest-stakes surface, usually the home hero plus two or three
sections. Not the whole site.

**Three variants, one per surviving direction.** Each is a self-contained HTML file that:

- uses the project's **own tokens** (`.design/tokens.css`), never the reference's colors
  or fonts;
- ports one reference's **structural idea** — section order, pacing, hero anatomy — not
  its layout, copy or assets;
- carries the project's real copy where it exists, placeholders where it doesn't;
- renders at **both** 390px and 1440px — mobile-first means mobile is designed first, not
  that desktop is skipped.

**Deliberately unfinished.** No build step, no framework, no component library,
placeholders only, no imagery — assets.md does not exist yet. Thirty minutes each, not
three hours: the job is to make the choice obvious, not to be the site. Name each variant
after the idea, not the reference: "phased spine", "dense catalog", "single-product
theatre".

## Two viewports, always

A variant is not a direction until it has been seen at both widths — the questions each
width asks differ:

| At 390px | At 1440px |
|---|---|
| What comes first, how far down is the price? | What sits beside what? |
| Does the CTA persist while scrolling? | Where does the eye land with room to roam? |
| How many taps to convert? | Full-width frame, or float in dead space? |
| Does the section order still make sense stacked? | Which sections become columns? |

**Desktop is not the phone stretched.** A desktop view that is the same single column at
1440px has been left there, not designed — show the real reflow: multi-column sections, a
stepped-up type scale, a hero with room.

Two techniques are accepted; pick whichever fits the harness:

1. **One miniature + container queries** — shipped in the first run. One markup, one
   stylesheet, `@container` drives the reflow. Pitfalls: grid placement breaks inside the
   review harness more than in a standalone page, and an inline `font-size` always beats
   `@container` — put sizes in classes, never inline.
2. **One `<iframe srcdoc>` per variant**, each with its own `@media (min-width: 1024px)`
   and per-breakpoint type sizes — isolates a variant's CSS from the harness and from the
   others. Reach for it when technique 1's pitfalls keep resurfacing.

Either way, the toggle sets the frame to 390 or 1440px and scales it with `transform:
scale(min(1, available / 1440))` inside a wrapper sized to the scaled height, so a phone
sees the whole desktop frame shrunk to fit.

`scripts/extract-site.mjs`'s `sections` and `mobileSections` arrays are **design input**
(where the reference itself diverged between widths), not a build technique — read them,
then build the call with technique 1 or 2.

## The review page

Build **one** page that holds all three, published by the `artifact-courier` (never by the
main session) as an Artifact so it opens on a phone from a link:

- a **viewport toggle** that switches all three between 390px and 1440px at once — mobile
  view sits them side by side, desktop stacks full-width (three 1440px frames in a row are
  too small to judge);
- each variant in a labeled frame that scrolls independently;
- under each: the one-line idea, which reference it came from, its score, and what it costs;
- the captured reference screenshots, so the owner sees source next to interpretation;
- a short "what changes if you pick this" line per variant.

Never publish the reference screenshots as the project's own work, and never include a
template's copy. Label every reference frame with its source and author.

## The closing link block

Every step that ends in something the owner must look at closes with a clean
link block — readable in a terminal **and** on a phone. It is NOT the courier's
`=== LINKS ===` block pasted as-is: that standard block omits registry rows with
`in_close_block: false`, which is how this skill registers its pages. Build it yourself from
the URLs: run `python3 <courier skill dir>/scripts/courier_preflight.py <docs_dir> --block-only --only <its files> --include-hidden`
(or read the `url` column of the courier's status table) and write your own REVIEW /
REFERENCES / PACK bullets. The format is the same: **plain markdown bullets**, one link per line,
no tracking parameters, no truncated URLs, no headers, no columns, no code fence, no
indentation.

- [📱 REVIEW · Variants 390/1440](<artifact url>)
- [🅰️ REVIEW · Variant A · phased spine](<artifact url>#a)
- [🅱️ REVIEW · Variant B · dense catalog](<artifact url>#b)
- [🔷 REVIEW · Variant C · product theatre](<artifact url>#c)
- [🔗 REFERENCES · EMBERJACK · Framer · $39](<demo url>)
- [🔗 REFERENCES · ASHLAR · Framer · $39](<demo url>)
- [🔗 REFERENCES · GridFly · Framer · free](<demo url>)

The groups are the label prefixes — REVIEW, then REFERENCES, then PACK — in that order;
a blank line between groups is allowed, a header line is not. 5b's block has only
REVIEW and REFERENCES — `.design/` holds nothing else exportable yet. STEP 7 adds the
PACK group, the `.design/` pack files and any published artifact URLs (never local
paths a phone cannot open), once the brief and its exports exist.

Rules for the block: only links worth opening (no intermediate URLs, no API
endpoints, no local paths the owner can't open from a phone); label inside the
link text; group by label prefix, never one unlabeled flat list; nothing broken —
every URL was opened this session; goes at the very end, after the analysis, never
mixed in — and nothing follows it.

## Deciding

Ask which variant leads in the prose ABOVE the block, then end the message with the block.
The owner may combine ("A's spine with C's hero") — that is a valid answer.

If none of the three convince, the direction is wrong, not the execution. Return to
STEP 5's keep/drop with what the variants revealed.

## Persist and record

Save the review HTML itself to `.design/preview/variants.html` — it is evidence, not
scratch; later steps may need to re-open it.

Once the owner decides, write to `.design/decisions.md`: which variant leads and which
parts come from which, in the owner's own words, plus the Converged-on entries — the
token values the surviving references agreed on, the ones provisional `tokens.css` was
seeded from.

`brief.md`'s Composition section is filled from that same decision, not re-asked.
