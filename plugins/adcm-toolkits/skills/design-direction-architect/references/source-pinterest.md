# Source: Pinterest — STEP 3

Pinterest needs a **browser**. `WebFetch` returns an empty shell: the results are
JavaScript-rendered behind a login wall. Use `mcp__claude-in-chrome__*` against
the user's logged-in session. The **search results grid is public content** even
when reached from a logged-in tab — hard rule 5 covers account-scoped surfaces
(boards, saved pins, profile), not the grid.

## Protocol

1. `tabs_context_mcp` first, to see the existing tabs. Never reuse a tab id from
   an earlier session.
2. `tabs_create_mcp` for a new tab — do not hijack the user's current tab unless
   they asked.
3. `navigate` to
   `https://www.pinterest.com/search/pins/?q=<url-encoded query>`
   Accept redirects to `<cc>.pinterest.com` (`mx.`, etc.) — same results, do
   not fight the locale.
4. Harvest with `javascript_tool`, not `read_page` or `get_page_text` — both
   return only CSS on Pinterest, no pin data:
   ```js
   [...document.querySelectorAll('a[href*="/pin/"]')].map(a => ({
     href: a.href,
     img: a.querySelector('img')?.src,
     alt: a.querySelector('img')?.alt
   }))
   ```
   Then take a `computer` screenshot of the grid (see Pitfalls for where a
   screenshot may be saved). Scroll 3× per query — roughly 7 pins load per
   viewport, so 3 scrolls gives a usable sample.
5. `tabs_close_mcp` when finished.

If the browser MCP is unavailable or the user is not logged in, **say so
explicitly** — "the Pinterest layer is missing, this direction rests on Framer
and 21st.dev only" — and continue. Never fabricate pins.

## Filter chips — IF they render

Pinterest sometimes renders topic chips above the results (`Layout` ·
`Website` · `Web` · `Aesthetic` …). They did not render at all in the first
real run — do not depend on them. When they do appear, apply **one chip at a
time** and re-harvest; combining chips narrows to nothing. Never block the
protocol waiting for chips that are not there.

## Query construction

Run **2–3 distinct queries**, not one query scrolled deeper. Different phrasings
surface different corpora.

- `<business seed>` from `category-map.md`
- `<style name> website` from `style-taxonomy.md`
- `<feeling adjectives from Q4> web design`

Example set for a dark-luxury food trailer landing:
1. "food truck branding website"
2. "dark luxury website design"
3. "premium industrial web design"

If chips happen to render, `Website` / `Layout` / `Aesthetic` are the useful
ones — one at a time.

## What to harvest

For each promising pin: the image, the pin URL, and — when it exists — the
**source URL** the pin links out to.

A pin is never a finalist. When a pin links out to a live site, that site gets
walked like a Framer demo and counts as a full-page candidate — the pin itself
is only ever a lead toward one.

## Pitfalls

- Pinterest is dense with **Dribbble shots that were never built**. They look
  great and cannot ship. Score them down on feasibility.
- Many pins are mobile app UI mislabeled as web. Check the aspect ratio.
- Pins repeat across boards. De-duplicate by image, not by pin URL.
- Never screenshot a **logged-in or personal** view (boards, saved pins,
  profile) into `.design/refs/` — save the pin URL and the public source URL
  instead. Exception: the **public results grid** is not an account-scoped
  surface — its screenshot is allowed as mood evidence. Crop out the header
  and any account chrome, name it `pinterest-<query>.png`, save under
  `.design/refs/mood/`.
