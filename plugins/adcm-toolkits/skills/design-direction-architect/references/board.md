# The design board — STEPS 4 to 5b

One page, `.design/board.html`, built by `design-board build` from `board.json` plus the fragments in
`board.d/`. Agents write data; the script writes the HTML. The board is published by the
`adcm-toolkits:courier` (never by the main session) and opened from a phone link.

## The five tabs

| Tab | What the owner sees | What the owner does |
|---|---|---|
| Options | The three directions as live thumbnails; "view large" opens one with a 390/1440 toggle | Compares them at both widths, then reads Method and Tokens |
| References | Every reference with its public URL, capture, badges (finalist, dropped, capture error); lightbox with arrows and Esc; filters all / finalists / dropped / kind | Drops the ones that miss, saying why in a few words |
| Market | Competitors and adjacent references, each with "what works / what doesn't" | Reads; challenges a competitor that does not belong |
| Method | Per option: how it was made, why, which reference ids it used, what changes if picked, cost | Checks the cited ids are real references |
| Tokens | Per option: font pairs, scale ratios, palettes, color-per-role pickers | Toggles, then presses Export |

Export shows the CSS, the `tokens-{id}.json` and a **combo code** `option/font/ratio/palette`
(for example `b/f2/r1.25/p1`, or `b/f2/r1.25b18/p1` when the base size was changed). Downloads and clipboard may be blocked inside the artifact, so the code is
always visible as text. The owner pastes it in the chat; the main session runs
`design-board adopt "<combo>" .design` (see `tokens-contract.md`) and then `design-board log --step 5b --decided "<owner's words>" --date YYYY-MM-DD .design`.

## Who writes what

Agents write `board.d/*.json` fragments and `variants/*.html`. Scripts write `captures/`, `shots/`,
`board.html`. Only the main session runs the explicit editors, never during `build`/`capture`:

- `design-board mark --drop <id|Rnn> --why "<owner's words>"` · `--finalist <id|Rnn>` · `--undrop <id|Rnn>`.
  `Rnn` is the short code shown on the card; it resolves to the id.
- `design-board build .design` then `design-board check .design` after every change (exit 1 prints one
  `FAIL <path>: <why>` per error).
- `design-board log --step N --decided "<owner's words>" --date YYYY-MM-DD` appends to `decisions.md`.

## The keep/drop loop (STEP 5)

The point is that the owner **removes** options. One recommendation plus "good?" produces agreement,
not a decision. The board shows exactly 5 finalists (the scorer sets `"finalist": true` on its 5 in `board.d/scores.json`; `build` promotes those badges, and `board.json` wins if it sets `finalist` or `dropped` itself; `mark --finalist` is for manual overrides only); never fewer
because "these were clearly the best".

The owner answers in chat only ("drop R03, too corporate"). The main session runs `mark --drop … --why …` per item, `build`, `log --step 5 --decided "…" --date YYYY-MM-DD .design`, and
republishes through `SendMessage` to the same courier. No new agent.

Routing, one rule:

- **2 or more survive** → STEP 5b with the top 3 by total. With exactly 2, option C combines A and B.
  Do not ask "which leads" here; 5b asks it once, with the options in front of the owner.
- **Fewer than 2 survive** → back to STEP 3, not "more of the same". Turn each reason into a search
  correction and say it out loud before re-searching so the owner can veto it:

  | They said | Correction |
  |---|---|
  | "too corporate" | drop `corporate-clean`, raise distinctiveness weight, search New instead of Best |
  | "too busy" | shift toward `swiss-minimal` / `editorial`, add whitespace terms |
  | "too plain" | shift toward `editorial` / `dark-luxury`, search Trending |
  | "doesn't feel premium" | dark grounds, serif display, slower motion, fewer elements |
  | "looks like a template" | new categories entirely, cap authors at 1 each |
  | "wrong for my customers" | re-check `category-map.md`; the business mapping was wrong, not the style |

- **Global counter.** The second return to STEP 3 from anywhere (STEP 5 or 5b) goes to STEP 2: the
  direction is wrong, not the candidates.

## Three options (STEP 5b)

Three deliberately unfinished one-pagers `a/b/c` in the project's real copy, one per surviving
direction, named after the idea ("phased spine"), not the reference. They consume the CSS contract in
`tokens-contract.md` and port a reference's structure (order, pacing, hero anatomy), never its copy,
layout or assets. `design-board capture --variants` shoots them; `check` enforces the contract.

Ask the 390/1440 questions with both widths in front of the owner:

| At 390px | At 1440px |
|---|---|
| What comes first, how far down is the price? | What sits beside what? |
| Does the CTA persist while scrolling? | Where does the eye land with room to roam? |
| How many taps to convert? | Full-width frame, or float in dead space? |
| Does the section order still make sense stacked? | Which sections become columns? |

Desktop is not the phone stretched: a single column at 1440 was left there, not designed. Real reflow
means columns and a stepped-up scale under `@media (min-width: 1024px)`.

The owner may combine ("A's spine with C's hero"); that is a valid answer. If none convince, the
direction is wrong: return to the keep/drop with what the options revealed. Write the decision in the
owner's words with `log --step 5b --decided "…" --date YYYY-MM-DD .design`; `brief.md`'s Composition is filled from it, not re-asked.

## Registry and the closing link block

The registry is always `.design/artifacts.json` (docs_dir `.design`), with one row:

```json
{ "file": "board.html", "title": "<Project> · Design board", "favicon": "🎨", "in_close_block": false,
  "regen": "design-board build .",
  "sources": ["board.json", "board.d", "variants/a.html", "variants/b.html", "variants/c.html",
              "inspiration", "captures"] }
```

`build` patches the row's `files` key itself. The courier is pointed at `.design` and publishes with
`courier_preflight.py .design --block-only --only board.html --include-hidden`, since the standard block
omits `in_close_block: false` rows.

The link block is the courier's RETURN (everything after `=== LINKS ===` of the LAST RETURN), once per
delivery close, pasted verbatim as the last lines; the session never builds it. It carries registry rows
only. Format: plain markdown bullets, one link per line, label inside the link text, no headers,
columns, code fence or indentation, nothing after the block. Groups in order: REVIEW, then PACK.

- [🎨 REVIEW · Board](<artifact url>)

Public reference URLs live inside the board, not in the block. Only links worth opening, every URL
opened this session, no local paths. STEP 7 adds PACK (see `handoff-guide.md`).

## Never

- Never re-present a reference the owner already dropped without saying so and why.
- Never let a source go unrepresented without naming it as a gap.
- Never publish a reference capture as the project's own work, and never reuse a template's copy.
- Never end a presentation without the link block; the owner reviews from a phone.
