# Source: Pexels (photo + video assets) — STEP 6b

Runs **after** the direction is locked. Style dictates image treatment, not the
reverse — searching for assets before the direction exists is how you end up
with a generic stock hero.

## Auth

The key lives in the environment as `PEXELS_API_KEY` (exported from the user's
shell profile). Read it from the environment; **never print it**, never write it
into `.design/`, never echo it in a command the user will see.

If it is missing, say so and continue without the asset layer rather than asking
the user to paste a key into the chat.

## The 403 gotcha

The API returns **HTTP 403 when the request carries a default script
User-Agent** (`python-urllib`, bare `curl`). It is not an auth failure — the key
is fine. Send a browser User-Agent and it returns 200.

```python
import os, json, urllib.request
H = {
    "Authorization": os.environ["PEXELS_API_KEY"],
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept": "application/json",
}
def pexels(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=25) as r:
        return json.load(r)
```

Response headers carry `X-Ratelimit-Remaining` — log the remaining quota when it
drops low, so the user is not surprised mid-project.

## Endpoints

| Need | Endpoint |
|---|---|
| Photos | `https://api.pexels.com/v1/search?query=…` |
| Curated photos | `https://api.pexels.com/v1/curated` |
| Videos | `https://api.pexels.com/videos/search?query=…` |

Useful parameters:

- `orientation` — `landscape` for heroes, `portrait` for mobile and side panels.
- `size` — `large` for anything full-bleed.
- `color` — **the important one.** Feed it the ground or accent already written
  into `.design/tokens.css` so the hero does not fight the brand. Accepts named
  buckets (`red`, `teal`, `black`, `white`…) and hex.
- `per_page` — request 10–15 per slot; you are choosing, not taking the first.
- `locale` — biases the corpus; worth setting for non-US-facing sites.

## Video: picking the file

Each video result carries a `video_files` array with `sd` / `hd` / `uhd`
variants, each with a direct `.mp4` `link`, plus `width`, `height` and `fps`.

- **Scroll-scrubbed hero:** prefer `hd` (1920) — `uhd` is too heavy to scrub
  smoothly and the extra pixels are invisible behind an overlay.
- **Looping background:** `sd` (640–960) is usually enough once blurred or
  darkened, and it protects the performance floor from Q8.
- Always record the duration and whether the clip loops cleanly. A clip with a
  hard cut at the end cannot be a background loop.

The `cinematic-scroll` style **requires** this step — it is the flat, static
asset input that `epic-design` expects (no WebGL, no 3D pipeline).

## Slots and candidate sets

Propose a **set per slot**, never a single image — the same no-first-option
discipline as the rest of the skill.

| Slot | Typical need |
|---|---|
| Hero | one landscape photo *or* one video loop, brand-color filtered |
| Section breaks | 2–3 atmosphere shots that share a color temperature |
| Texture / ground | grain, concrete, paper, fabric — used at low opacity |
| Proof / context | environment shots that place the product in real use |

Keep the set **color-coherent**: pull all of them through the same `color`
filter, or the page reads as a collage.

## Hard rule: stock is not the product

Whatever the business actually sells gets a **real photograph**. Pexels supplies
atmosphere, texture and B-roll. In `.design/assets.md`, mark every entry:

- `atmosphere` — stock is the final answer here.
- `REAL-PHOTO-NEEDED` — a placeholder standing in for a shot the client owes.

A food-trailer site whose hero shows somebody else's trailer is a worse outcome
than a site with no hero image.

## License

Pexels content is free for commercial use and attribution is not required
(crediting is appreciated). Not allowed: reselling unaltered copies, implying
that an identifiable person or brand in the image endorses the product, or using
identifiable people in a way that is defamatory or sensitive. Record the source
URL for every asset in `.design/assets.md` so provenance survives the project.
