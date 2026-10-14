# Source: Awwwards — STEP 3

Awwwards is a **lead source**, not a capture source. Its pages are walled and its assets are not ours:
the board shows the winner's **live site**, with the gallery page kept as `via`.

## Method

1. Take the styles fixed in STEP 2 and map them to Awwwards categories or tags.
2. Fetch **at most 5 listing pages** (Site of the Day, Honorable Mention, Nominees), filtered by
   category or tag. Text is enough; no images, no pagination beyond those pages.
3. For each promising entry, find the **live site URL** with WebSearch on the site's name. Fetch an
   Awwwards detail page only when the name is ambiguous (at most 5).
4. Hard budget: **≤10 fetches to awwwards.com** in total. Respect `robots.txt`.
5. Return 6–10 live sites for the pinned styles. Visit every URL you return.

## Output

Write only `.design/board.d/refs-awwwards.json`, via Bash:

```json
{ "references": [
  { "id": "acme-site", "kind": "awwwards", "award": "SOTD", "name": "Acme Studio",
    "url": "https://www.example.com/", "via": "https://www.awwwards.com/sites/acme-studio",
    "why": "one line on why it fits", "style_fit": "swiss-minimal" }
] }
```

`id` is `^[a-z0-9-]{1,48}$` and unique across the whole board. `url` is the live site, https. `via` is the
gallery page you read. Run `design-board check .design` and fix every `FAIL` before returning.

## STOP and blocked

- A listing asks for login or blocks the fetch → stop and return `blocked: awwwards listing <why>`.
  Do not retry with other tools or scrape around the wall.
- Fewer than 6 sites → return what you have and name the gap.

## Forbidden

Captures of awwwards.com, downloading its assets, URLs you did not visit, inventing an award.
Captures of the live sites are taken later by `design-board capture`.
