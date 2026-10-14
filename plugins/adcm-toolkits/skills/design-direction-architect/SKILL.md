---
name: design-direction-architect
description: >
  Researches and locks a web design direction BEFORE any code is written.
  Interviews the owner, then mines real sources (the Framer template
  marketplace, Awwwards, 21st.dev, the owner's inspiration folder and Pexels
  for assets) plus a market scan of competitors, triages 15+ candidates,
  walks 8, and presents 5 finalists backed by two or more sources, never the
  first hit. Everything lands on one fixed board with 5 tabs (Options,
  References, Market, Method, Tokens) and a token export; the scripts do the
  mechanical work (captures, thumbnails, HTML, tokens, decision log, pack),
  agents only write data. Writes a reusable pack to `.design/` and hands it to
  the building skills; it does not build the site. Triggers on 'design a
  website', 'landing page', 'design references', 'design direction',
  'moodboard', 'inspiration', 'make it look expensive', 'my site looks
  generic', 'AI slop design', 'design board', 'diseñar un sitio', 'buscar
  referencias', 'inspiración', 'dirección de diseño', 'que no se vea
  genérico', 'tablero de diseño'.
compatibility: >
  Python 3 (board builder) · Node >= 20 + playwright-core >= 1.61 + Chrome
  (captures; `design-board doctor`) · WebSearch for market and Awwwards ·
  Pexels reads PEXELS_API_KEY · 21st.dev needs the `magic` MCP · Pinterest is
  a manual folder.
---

# Design Direction Architect

AI-generated sites look generic because the agent starts **without references**.
This skill is the missing phase zero: it interviews, researches real sources,
curates without settling for the first hit, and produces a reference pack that
the building skills consume. The owner judges everything on one board; the
`design-board` launcher (the plugin's `bin/`) builds it.

**It never writes the site.** Its output is a direction, not a page.

`design-board <doctor|init|capture|check|build|mark|adopt|log|pack>`. Run it bare;
without the plugin on PATH: `python3 "${CLAUDE_PLUGIN_ROOT}/skills/design-direction-architect/scripts/design-board.py" <cmd> .design`
(captures: `node …/scripts/capture.mjs`, Node >= 20 first on PATH). Exit: `0` ok · `1` check
failed (`FAIL <path>: <why>` lines) · `2` missing or unparseable input · `64` usage.

Combo code, the owner's pick from the Tokens tab: `<opt>/<fontId>/<r<ratio>[b<base>]|presetId>/<paletteId>`
(`b<base>` only when the base differs from the preset), for example `b/f2/r1.25/p1` or `b/f2/r1.25b18/p1`.

## If you are the main session

You orchestrate. You interview, lock the direction, decide drops and write nothing
mechanical. Every agent call is an `adcm-toolkits:*` type (it fixes the `model`) or an
explicit `model`; no plugin in this session means `Agent(subagent_type: "general-purpose",
model: "<tier>")` with the same brief. Read a reference only when its step begins.

| Step | Who | What |
|---|---|---|
| 0 Doctor, context | main, then SCRIPT | `design-board doctor` (node, playwright-core, chrome, image tool, python3, `PEXELS_API_KEY` yes/no, `.design/inspiration/`). Check whether the `magic` MCP is loaded. Probe the repo and skills for context (below), then `design-board init .design` (creates `board.json` from the template, `board.d/`, `inspiration/`; never overwrites). |
| 1 Interview | main | `references/interview-guide.md`. Express (Q1, 2, 3, 6, 9) or Full (all nine) through `AskUserQuestion`; Q9 is never skipped. Ask the owner to drop pins and images into `.design/inspiration/` (optional; a `<file>.url` sidecar or `sources.txt` carries the public URL). |
| 2 Direction | main | `references/style-taxonomy.md`, `category-map.md`. One or two named styles, Framer categories, Awwwards tags, 21st.dev keywords and the market query (line of business, region, segment). Restate in two sentences, get a nod, then `design-board log .design --step 2 --decided "<owner's words>" --date <today>`. |
| 3 Search | 3 researchers (sonnet) in parallel, then SCRIPT | Templates (Framer plus 21st.dev) · Awwwards · Market. Each leaves one fragment in `.design/board.d/` with URLs. Then `design-board capture --board .design/board.json --out .design` (>= 15 URLs; full metrics for the best 8) and the `inspiration/` index. Pinterest has no agent. |
| 3b Commercial | folded into Market | Each market entry carries a one-line `commerce` note on the entry (a string, <= 160); at least 6 sites with a commerce note across Market and References (when the business sells). `commerce.md` is still written in step 7. |
| 4 Scoring | researcher `model: opus`, SCRIPT, courier | Reads fragments, capture metrics and PNGs; writes `board.d/scores.json` (9 dimensions, total, "does what others don't", cost, anti-first-option `findings`, and `finalist: true` on its 5 picks). `build` promotes those badges (`board.json` wins when it sets `finalist` or `dropped` itself; `mark --finalist` is only for manual overrides). Then `design-board build .design` and `design-board check .design`; ONE courier publishes `board.html`. |
| 5 Drop plus why | owner on the board, then SCRIPT | The owner gives drops in chat only ("drop R03, too corporate"); the board has no drop-export button. Main runs `design-board mark .design --drop R03 --why "…"` (or `--finalist`, `--undrop`), `design-board build .design`, `design-board log .design --step 5 …`; republish through `SendMessage` to the same courier (zero new agents). Routing: >= 2 finalists survive go to 5b; fewer than 2 go back to step 3 with the correction table; a second return to step 3 from anywhere goes to step 2. |
| 5b Three options | executor-frontend, SCRIPT, auditor opus, courier | The variants executor writes `variants/{a,b,c}.html` (with 2 survivors, C = A + B) and `board.d/options.json`. Then `design-board capture --variants --out .design`, `build`, `check`, the opus gate, republish. The owner opens Options, Method and Tokens, toggles, presses Export and pastes the combo code. Main runs `design-board adopt "b/f2/r1.25/p1" .design` (`--dry` prints; `--file tokens.json` also works) and `log --step 5b --decided "<owner's words>" --date YYYY-MM-DD .design`. |
| 6 Extraction | SCRIPT, plus the pack executor | Capture metrics already give palette by painted area, type scale and section map; `design-board pack .design` writes `references.md` and the market summary. `structure-only`: toggles are locked to the design system's values (`references/structure-only-mode.md`). |
| 6b Pexels | folded into the pack executor | `references/source-pexels.md`. No key means skip and log the gap. |
| 7 Pack, handoff | pack executor (sonnet), main, courier | The executor writes `brief.md`, `commerce.md`, `assets.md` and the extraction notes; `references.md`, `tokens.css`, `tokens.json` and `decisions.md` come from the scripts. Main names the building skill (`references/handoff-guide.md`), closes through the courier: the REVIEW row for the board (its only registry row) plus PACK links to the committed `.design/` files, which the courier builds from the repo remote, never from registry rows. |
| `--update` | main, as steps 3 to 7 | No interview: read `.design/brief.md` as the locked direction. `board.json` persists (new ids, kept drops, regenerated options with a version bump); `decisions.md` is appended. |

**Step 0 context.** Search the available skills for a `business-init-*` or
`code-project-context-*` that matches, and probe the repo: `.design/`,
`**/tokens.{css,json,ts}`, `tailwind.config*`, `*design-system*`, `docs/**/*design*`,
`docs/specs/**`, `README*`, any `*-quote-*` skill. Read what you find and **confirm instead
of asking** ("detected <business>, <one-line positioning>; going with that?"). If a design
system or token file exists set **`mode: structure-only`** (`references/structure-only-mode.md`):
the WHAT is fixed, this run researches the HOW. Answer in the prompt's language.

**Who writes `board.json`.** Nobody in parallel. Agents leave fragments in
`.design/board.d/<name>.json`; `check` and `build` merge them by id and `board.json` wins per
field. Only `init`, `mark`, `adopt` and `log` edit it, run by the main session, never during
`build` or `capture`.

**Delivery close.** `board.html` is the single owner-facing artifact; `references/board.md`
has the correction table and the link-block rules. The board's registry is ALWAYS
`.design/artifacts.json` (docs_dir = `.design`), never the brain's; this skill leaves the
brain's own `artifacts.json` untouched. Its one row:
`{"file":"board.html","title":"<Project> · Design board","favicon":"🎨","in_close_block":false,"regen":"design-board build .","sources":["board.json","board.d","variants/a.html","variants/b.html","variants/c.html","inspiration","captures"]}`;
`build` writes the row's `files` key. The courier is pointed at `.design` and its brief carries
`BLOCK FLAGS: --only board.html --include-hidden`; its RETURN block is pasted verbatim, once, as the last lines (questions go
above). You never call the Artifact tool and never build your own bullets.

**Economy per run.** 8 agents: 2 opus (scorer, auditor) and 6 sonnet (3 researchers, variants
executor, pack executor, courier). A drop round costs zero agents.

Escape hatch, in the owner's words: `sin tanto lío` (direct mode for that task) or `modo directo`
(until `modo orquestador`). Canonical rule:
`${CLAUDE_PLUGIN_ROOT}/skills/execution-prompt-architect/references/orchestrator-rule.md`.

## If you are a researcher (step 3)

Your brief names ONE source and ONE output fragment. Write only that fragment under
`.design/board.d/` (through Bash); no captures (the script takes them), no pages behind a
login, no invented URLs, no copying their copy. Every URL you write must have been visited or
returned by a search in this session. Return a short table (name, URL, one line), never inline
screenshots.

- **Templates** (sonnet): `references/source-framer.md`, `source-21st.md`, `category-map.md`. Candidates
  from the Framer marketplace (detail page plus public demo) and 21st.dev through the `magic`
  MCP, into `board.d/refs-templates.json`. Without the MCP, say that layer is missing.
- **Awwwards** (sonnet): `references/source-awwwards.md`. 6 to 10 live sites (SOTD, Honorable, Nominees) for the
  locked styles from at most 5 filtered listing pages; the live URL comes from WebSearch of the
  name. **At most 10 fetches to awwwards.com**, honor robots.txt, no pagination, no captures of
  awwwards.com. Listing asks for a login or blocks: return `blocked`. Output
  `board.d/refs-awwwards.json` (`{id, kind: awwwards, award, name, url, via, why, style_fit}`).
- **Market** (opus only if asked; default sonnet): `references/market-research.md`, `commerce-patterns.md`.
  4 to 6 competitors of the same line, region and segment plus 2 to 4 adjacent references with the same
  buying pattern, from `brief.md` Q1 and Q9. Output `board.d/market.json` (`{id, kind, name, url,
  works (2 lines), doesnt (2 lines), commerce (1 line), query}`). Fewer than 4 competitors: return what
  exists and log the gap.

DoD for each: `design-board check .design` exits 0.

## If you are the variants executor (step 5b)

Read `board.json` and the fragments, `references/board.md`, `references/tokens-contract.md` and
`captures/`. Build three deliberately unfinished one-pagers with the project's **real brand
copy**, one per surviving finalist.

1. **CSS variable contract.** Every color, font and size comes from a variable declared in the
   page's own `:root` block: fonts `--font-display --font-body --font-mono` · scale `--step--1 … --step-5`
   `--leading-tight --leading-body --tracking-display` · color roles `--color-ground --color-surface
   --color-ink --color-ink-muted --color-primary --color-accent --color-accent-ink --color-border` ·
   statics `--space-1 … --space-6 --radius --dur --ease`. No literal color, font or size outside `:root`
   (`check` greps it). Real reflow in `@media (min-width: 1024px)`; no frameworks, no external images.
2. **Bridge.** Paste `templates/variant-bridge.html` (the `data-board-bridge` script) into each
   variant unchanged; it lets the board's Tokens tab apply the toggles. `check` requires it and
   `var(--font-display)`.
3. **`board.d/options.json`**, one entry per `a`, `b`, `c`: `id`, `name`, `idea`, `refs_used`,
   `how_made` (<= 4 lines), `why` (<= 3), `what_changes_if_picked`, `cost`, `fonts[3-5 pairs
   {id, display, body, mono?}]`, `ratios[2-3]`, `palettes[2-3 {id, label, colors}]` with the 8 roles as
   `#RRGGBB` and readable contrast. `usedRefs` never cite a dropped reference.

DoD: `design-board check .design` and `design-board capture --variants --out .design` exit 0. Never edit
`board.html`; never reuse a reference's copy.

## If you are the pack executor (steps 6b and 7)

Read `.design/board.json`, `decisions.md`, `references.md` (from `design-board pack`),
`references/extraction-guide.md`, `handoff-guide.md`, `licensing-and-ethics.md`,
`source-pexels.md` and the templates. Write `brief.md`, `commerce.md` (if it sells), `assets.md`
(Pexels manifest: slot to candidates, ids, dimensions, license; business products are
`REAL-PHOTO-NEEDED`, the key is never printed) and the extraction notes. Do not hand-write
`references.md`, `tokens.css`, `tokens.json` or `decisions.md`; if one is stale, report it and the
main session reruns the script. Return the file list and the handoff sentence.

## Hard rules

1. **Reference is not copy.** Never reproduce a reference's copy, images or assets.
   Extract structure, rhythm, scale and pattern, never content.
2. **5 finalists from at least 2 sources; exactly 3 options.** Never a pack drawn from a
   single source.
3. **Never the first option.** Triage at least 15 full-page candidates and **walk at least 8**
   before presenting; `scored` means walked. If #1 is the first candidate walked, defend it against
   the other four or demote it.
4. **Zero invented references.** Every URL written to `.design/` was actually fetched or visited
   in this session.
5. **Public demos only.** Never screenshot anything behind a login.
6. **Degrade out loud.** If a source is unavailable, say which layer is missing rather than
   pretending coverage.
7. **Stock is not the product.** Pexels supplies atmosphere, texture and B-roll. Anything the
   business sells is marked `REAL-PHOTO-NEEDED`.
8. **Never print `PEXELS_API_KEY`** in output, logs, `board.json`, `board.html` or any `.design/` file.
9. **Never buy a template to study it.** Walk its public demo and extract relationships between
   values. Reproducing a template's layout, copy or assets is forbidden.
10. **One registry row: `.design/board.html`, `in_close_block: false`.** The courier brief carries
    `--only board.html --include-hidden`; its block is pasted once, last (see Delivery close).
11. **Pure orchestrator.** Main interviews, locks, decides drops and runs the `design-board` calls;
    it does not browse, score, write HTML or publish. Browsing: `adcm-toolkits:researcher` per
    source. Scoring: `adcm-toolkits:researcher` with `model: opus`. Variants:
    `adcm-toolkits:executor-frontend`. Gate: `adcm-toolkits:auditor` (opus; exactly 3 options, every
    reference and market entry with an https URL and a capture or sidecar, 390 and 1440 shots per
    option, the 5 badges from `scores.json`, combo through `adopt --dry` yielding the full contract,
    no secrets, size under threshold; RETURN `ship | fix-first: <items → owning agent>`). Pack:
    `adcm-toolkits:executor`. Publishing: `adcm-toolkits:courier`.
12. **Agents write data, scripts write HTML.** Agents never write `board.html`, `board.json`,
    `tokens.css` or thumbnails; they leave fragments and variant pages.
13. **The exported `tokens.css` is the source of truth.** `design-board adopt` regenerates
    `tokens.css` and `tokens.json` from the owner's pick; downstream skills read those, not the
    variants. Packs from before 0.18.0 use old token names: regenerate with `adopt`.
14. **Every reference shows its public URL** on the board and in `references.md`.

## Files

| File | What it is | Read at |
|---|---|---|
| `scripts/design-board.py` | the board builder: init, check, build, mark, adopt, log, pack | never; run it |
| `scripts/capture.mjs` | Playwright captures at 1440 and 390 plus palette, type and section metrics; `--variants`, `--doctor` | never; run it |
| `scripts/design-board-selftest.py` | offline checks of the builder against `fixtures/demo/` | after changing the scripts |
| `templates/board.json.tmpl`, `board.html.tmpl` | the board data schema with an example, and the page the builder fills | `init`, `build` |
| `templates/variant-bridge.html` | the `data-board-bridge` snippet every variant carries | variants executor |
| `templates/tokens.css.tmpl` | token names of the CSS contract (LOCKED VARIANT in structure-only mode) | step 5b |
| `templates/decision-entry.md.tmpl` | dated log entry (`log` also writes the `decisions.md` header) | `log` |
| `templates/brief.md.tmpl`, `commerce.md.tmpl`, `assets.md.tmpl` | one per hand-written `.design/` output file (`pack` writes `references.md`) | step 7 |
| `references/interview-guide.md` | the 9 questions, Express vs Full, auto-context | step 1 |
| `references/structure-only-mode.md` | locked brand: research the HOW, lock the toggles | steps 0, 5b, 6 |
| `references/style-taxonomy.md`, `category-map.md` | the 15 styles; business type to categories, queries, keywords | step 2 |
| `references/source-framer.md`, `source-awwwards.md`, `source-21st.md`, `source-pinterest.md` | per-source protocols (Pinterest is the manual folder plus sidecar) | step 3 |
| `references/market-research.md`, `commerce-patterns.md` | competitor and adjacent scan; how products and quotes are shown | steps 3, 3b |
| `references/scoring-rubric.md` | the 9 dimensions, the funnel, `scores.json`, tie-breaks | step 4 |
| `references/board.md` | the board tabs, drop-correction table, 390/1440 review, link-block rules | steps 4, 5, 5b |
| `references/tokens-contract.md` | CSS variable contract, toggles, export formats, combo code | variants executor, step 5b |
| `references/extraction-guide.md` | turning a capture into sections, tokens, motion | step 6 |
| `references/source-pexels.md` | Pexels photo and video API, the 403 gotcha, license | step 6b |
| `references/handoff-guide.md`, `licensing-and-ethics.md` | which building skill gets the pack; reference is not copy | step 7 |
| `fixtures/demo/` | a generic demo board for the selftest | selftest |
| `bin/design-board` | the launcher (plugin level) | every `design-board` call |

Absolute path when needed: `${CLAUDE_PLUGIN_ROOT}/skills/design-direction-architect/`
