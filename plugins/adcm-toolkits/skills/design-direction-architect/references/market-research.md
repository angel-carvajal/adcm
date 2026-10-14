# Market research — STEP 3 (absorbs the commercial pass)

The Market tab shows how the owner's competitors and adjacent businesses present and sell. It is
evidence for the brief and the commercial section; it is not a source of finalists.

## Method

Read the brief's business answers (what is sold, to whom, where) and `commerce-patterns.md` §C.

1. Find **4–6 competitors**: same line of business, region and customer segment.
2. Find **2–4 adjacent references**: a different business with the same purchase pattern
   (same buyer decision, price, quote or checkout shape).
3. Visit every URL in the session. No login pages, no invented URLs, no copying their copy.
4. If fewer than 4 competitors exist, return what you found and log the gap; do not pad.

## Output

Write only `.design/board.d/market.json`, via Bash:

```json
{ "market": [
  { "id": "provider-books", "kind": "competitor", "name": "Provider Books",
    "url": "https://www.example.com/",
    "works": "what it does well, at most 2 lines (board limit 160 chars)",
    "doesnt": "what it misses or hides, at most 2 lines (160 chars)",
    "commerce": "one line: how it prices, quotes or converts",
    "query": "the search that found it" }
] }
```

`kind` is `competitor` or `adjacent`. `commerce` is optional (a string, at most 160 chars) and is also
allowed on `references[]` entries. `works` and `doesnt` are both mandatory; `check` fails without
them. `id` is `^[a-z0-9-]{1,48}$`, unique across the board. Screenshots are taken later by
`design-board capture` (the market entry's `url` is captured like a reference).

## Commerce rule

Every entry carries a one-line `commerce` note. When an entry's product section is notably strong, say
so in that note ("strong product section") so the main session can promote it to a reference. The pack
needs at least **6 sites with a commerce note** between Market and References; `commerce.md` is still
written at STEP 7.

## Gaps

State what is missing as a line in your RETURN ("only 3 competitors in this region"); the main session
logs it with `design-board log --step 3 --decided "…" --date YYYY-MM-DD --findings "…" .design`. Run `design-board check .design` before returning.
