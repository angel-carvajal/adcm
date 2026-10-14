# Source: Framer marketplace — STEP 3

The highest-value source, because every template exposes a **live demo site you
can actually walk through**. No token, no login: the marketplace is
server-rendered and `WebFetch` reads it directly.

## URLs

| Purpose | URL |
|---|---|
| All templates | `https://www.framer.com/marketplace/templates/` |
| One category | `https://www.framer.com/marketplace/templates/categories/<slug>/` |
| One template | `https://www.framer.com/marketplace/templates/<template-slug>/` |

Category slugs: see `category-map.md`. Only those 50 resolve — a guessed slug
returns nothing, so never invent one.

Ordering tabs — Trending / Best / New — are UI tabs, **not verified URL
parameters**. **UNVERIFIED**: click the tab in a browser and record the
resulting URL before relying on it; if the URL does not change, the tab is
client-side only and you harvest **Best** only. When the URLs do differ, use
**Best** for proven craft, **Trending** for current visual language, **New**
for styles that have not saturated yet.

## The Style filter is JavaScript

The marketplace's "Style" and "Price" controls are client-side and do **not**
appear in fetched HTML. Do not try to encode style in the URL. Filter by style
**on our side**, over the candidates a category returns, using the
`style-taxonomy.md` anti-patterns as the reject test.

## Reading a listing page

Each card yields: template name, author, price (Free or $N). Collect 8–12 per
category. Do not judge yet — a name and a price tell you nothing.

## Reading a template page

The detail page yields the description, the industry tags, and — the reason this
source matters — the **live demo URL**. It is **not derivable** from the name:
observed forms are `<random-words-NNNNNN>.framer.app` and `<slug>.framer.website`,
with no rule for which. Read it off the Preview link on the detail page. Never
construct it; if the detail page has no demo link, drop the candidate.

## Triage

Do not full-walk every candidate — it does not scale past a handful.

1. `WebFetch` the detail page for each candidate → description, industry
   tags, demo link.
2. Write the candidates to the fragment `.design/board.d/refs-templates.json`
   (`{"references": [...]}`), each with the reference fields: `id, title, url, via,
   kind: framer|21st, notes, tags`, plus optional `commerce`. The **main session**
   (not the researcher) then takes the triage captures of **at least 15** demos
   across the chosen categories with
   `design-board capture --quick --board .design/board.json`. Viewport screenshot
   (1440) + JSON, ~10 s each. Score each on three dimensions only — style fit, business fit,
   distinctiveness; the other six wait for the full walk.
3. Full walk (no `--quick`) only the top 8 that survive triage. Framer's
   survivors compete with the 21st.dev and Awwwards candidates
   for the 5 finalist slots — Framer alone never fills them.

## Walking the live demo (mandatory for finalists)

**Templates cost money. The direction does not.** Never buy a template to study
it, and never download or reproduce one. Open its public demo with a real
browser and extract the *relationships* — how dark the ground is against the
accent, how the type scale steps, how the sections are paced. That is design
research on a public page. Reproducing the template's layout, copy or assets is
not, and is forbidden (see `licensing-and-ethics.md`).

`WebFetch` gives you the text and misses everything visual. Check the toolchain
once, then let the script capture the finalists:

```bash
design-board doctor
design-board capture --board .design/board.json
```

`doctor` reports node ≥20, playwright-core, the Chrome channel, an image tool and
python3, and ends with `DOCTOR: ready` or `not ready`. `capture` writes desktop
and mobile screenshots plus `captures/{id}.json` per site into `.design/captures/`;
a URL that fails records `captureError` and the run continues.

### The six gotchas, all verified — the script already handles them

| Symptom | Cause | Fix |
|---|---|---|
| `Playwright requires Node.js 20 or higher` | machine default is Node 18 | prefix PATH with an nvm 20/22 bin |
| `Executable doesn't exist at <cache>/chromium_headless_shell-<n>` | cached ms-playwright builds drift from the package version | `channel: 'chrome'` — drives the installed Chrome, downloads nothing |
| `page.goto: Timeout exceeded ... waiting until "networkidle"` | Framer sites keep connections open forever | `domcontentloaded`, then scroll to bottom, then settle |
| section list is all `div div div` | you queried the wrong nodes | Framer leaves `data-framer-name` on sections — read it |
| `Cannot find module 'playwright-core'` / `$PW` empty | preflight found no cached playwright-core | run the preflight (the `npx` line) |
| `Chromium distribution 'chrome' is not found` | Google Chrome is not installed | install Google Chrome — the script drives the installed Chrome on purpose |

### What the capture returns

- **ground / ink** — colors ranked by **painted area**, not by count. The ground
  is whatever covers the most pixels, which is what the eye reads as the theme.
- **fonts** — families in use, ranked by node count.
- **typeScale** — every distinct size + weight + line-height + transform +
  tracking combination, with its family.
- **radii**, **motion** — transition property/duration/easing triples.
- **palette** — the six colors with the most painted area; **docHeight** — page length.
- The 1440 and 390 screenshots side by side: where the mobile order or heights
  diverge is where the reference actually solved responsive, and where most
  designs quietly break.

Read the numbers as *ratios*, not values to copy: ground-to-accent distance,
display-to-body ratio, mono tracking relative to its size, section height
rhythm. Those ratios port onto the project's own brand; the hex codes do not.

## Pitfalls

- A paid template's demo is still public — walking it is fine, copying it is not.
- Framer-built demos animate on scroll; a single static fetch may miss motion.
  If motion matters to the direction, open it in the browser, do not just fetch.
- Template names repeat across authors. Always key candidates by demo URL.
