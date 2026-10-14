# Source: Pinterest — STEP 3

Pinterest is **a manual folder**, not a search source. Its pages are JavaScript-rendered behind a login
wall, so no agent browses it. The owner drops pins or screenshots into `.design/inspiration/` (asked
at the end of the interview, optional) and `design-board build` indexes them.

## The folder

- Images: `.design/inspiration/*.png|jpg|jpeg|webp`, ordered by file name. Each becomes a reference
  `insp-<slug>`, titled from the file name, with `kind: pinterest` when its URL host is `pinterest.com`
  or `pin.it`, otherwise `manual`.
- URL per image, either way:
  - a sidecar `<file>.url` holding one https line, or
  - a line in `inspiration/sources.txt`: `filename<TAB>url[<TAB>title]`.
  The sidecar wins over `sources.txt`. An image with no URL is shown as mood with no link.
- If `board.json` carries a reference with the same id, its finalist, dropped and notes win.

## Rules

- A pin is never a finalist by itself. When a pin links out to a live site, that site is added as a
  reference (`kind: live`, `via` the pin URL) and walked like any other; the pin stays mood evidence.
- Many pins are Dribbble shots that were never built, or mobile app UI mislabeled as web. Score them
  down on feasibility and check the aspect ratio.
- Never put a logged-in or personal view (boards, saved pins, profile) in the folder: save the pin URL
  and the public source URL instead.
- If the folder is empty, say so: "the Pinterest layer is missing, this direction rests on the other
  sources" — and continue. Never fabricate pins.
