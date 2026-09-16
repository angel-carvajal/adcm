# Curation protocol — STEP 5

The point of this step is that the user **removes** options. Presenting one
recommendation and asking "good?" produces agreement, not a decision.

## Presenting

Show exactly **5 finalists** as one **contact-sheet artifact** — a single
phone-first page, not a screenshot pasted into chat. Read `artifact-design`
before building it.

Build rules:

- Images go in as **data URIs**, read from `.design/refs/` — the artifact's
  CSP blocks external image URLs, so a `<img src="https://...">` renders
  blank. Downscale to ~1200px wide and encode as JPEG before inlining; the
  whole page must stay under 16 MB.
- Grid is phone-first: one column on narrow viewports, so the owner reviewing
  from a phone scrolls a single stack instead of panning a table.
- Each tile is labeled **"source · author"** directly under the image.
- When STEP 3b ran, show the hero and commercial capture for that candidate
  as a **pair** — two images, one tile, one label — not as two separate
  finalists.
- Under each tile: the nine scores as a compact row plus the total, **one
  line** on what it does that the others do not, and **one line** on its
  cost — what the owner accepts by choosing it.
- Order tiles by total, but never label the top one "the winner" — that
  framing pre-empts the drop decision below.

If STEP 3b ran, keep the commercial finalists as a **second contact sheet**
on the same page, clearly separated: "these five set the look; these three
set how the product section sells."

The artifact closes with the link block — **REVIEW** and **REFERENCES**
groups only. No **PACK** entry yet; nothing has been chosen.

## Getting the capture into refs/

A candidate is not presentable until its image is a file under `.design/refs/`.
A tool preview, a chat inline image, or a screenshot sitting in a temp dir does
not count — the contact-sheet artifact above embeds files, not URLs.

**Primary path.** Run `scripts/extract-site.mjs` against the candidate's public
demo URL. It drives headless Chromium itself and writes both a desktop and a
mobile PNG straight into `.design/refs/` — nothing to move afterward.

**Fallback**, only when Node or Playwright is unavailable. Take the shot with
the browser-MCP screenshot tool using `save_to_disk`, then immediately copy it
out of the temp dir — it will not survive there:

```bash
mkdir -p .design/refs && cp "$(ls -t "${TMPDIR:-/tmp}"/claude-chrome-screenshots-*/*.png "$(ls -dt /var/folders/*/*/T/claude-chrome-screenshots-* 2>/dev/null | head -1)"/*.png 2>/dev/null | head -1)" .design/refs/<source>-<slug>.png
```

Note the resulting `.design/refs/` path right next to the candidate in your
working notes. A capture that stays in `claude-chrome-screenshots-*` does not
exist for the pack. Name it to the STEP 3 convention — `<slug>-desktop.png`,
`<slug>-commerce-mobile.png` — so fallback captures sort with the extractor's.

## The keep/drop loop

Ask the user only to **drop the ones that miss, and say why** in a few words —
"too corporate", "the type is boring", "too busy".

One rule, no exceptions:

- **2 or more survive** → go to **STEP 5b** with the top 3 by total as the
  variants. With exactly 2, variant C is the combination of A and B. Do not ask
  "which leads" here — 5b asks it once, with the variants in front of the owner.
- **Fewer than 2 survive** → return to STEP 3. Do **not** simply fetch more of
  the same. Convert each rejection reason into a search correction first:

  | They said | Correction |
  |---|---|
  | "too corporate" | drop `corporate-clean`, raise distinctiveness weight, search New instead of Best |
  | "too busy" | shift toward `swiss-minimal` / `editorial`, add whitespace terms |
  | "too plain" | shift toward `editorial` / `dark-luxury`, search Trending |
  | "doesn't feel premium" | dark grounds, serif display, slower motion, fewer elements |
  | "looks like a template" | new categories entirely, cap authors at 1 each |
  | "wrong for my customers" | re-check `category-map.md`; the business mapping was wrong, not the style |

  State the correction out loud before re-searching, so the user can veto it.

- **Global counter.** The *second* return to STEP 3 from anywhere (STEP 5 or
  STEP 5b) goes to **STEP 2** instead: the direction itself is wrong, not the
  candidates. Re-open the style choice with what has been learned.

## Then show it, don't describe it

Once 2 or more survive, go to **STEP 5b** (`variant-preview.md`) before extracting.
A user cannot picture "structure from A, palette from B" — they can recognize it
instantly. Three fast variants in the project's own brand, published as one
phone-openable page, turn an argument into a glance.

## Combining references

The output is usually not one template. It is normal and good to say: "structure
and pacing from A, type system from B, product section from D." Write that
combination into `.design/brief.md` explicitly, section by section — a builder
skill cannot infer it.

## Never

- Never present fewer than 5 because "these were clearly the best."
- Never re-present a reference the user already dropped without saying that you
  are doing it and why.
- Never let a source go unrepresented without naming it as a gap.
- Never end the presentation without the closing link block — the owner reviews
  from a phone, and local file paths are useless there.
