---
name: design-direction-architect
description: >
  Researches and locks a web design direction BEFORE any code is written.
  Interviews the owner, then mines four real sources — the Framer template
  marketplace (live demos, 50 industry categories), Pinterest (browser),
  21st.dev (magic MCP) and Pexels (photo + video) — triages 15+ candidates,
  walks 8, and presents 5 finalists backed by two or more sources, never the first
  hit. Runs a separate search for the product/service section and quote or
  checkout flow when the business sells something. Writes a reusable pack to
  `.design/` (brief, references, tokens, commerce, assets, decisions) and hands
  it to the building skills; it does not build the site. Triggers on 'design a
  website', 'landing page', 'design references', 'design direction',
  'moodboard', 'inspiration', 'make it look expensive', 'my site looks
  generic', 'AI slop design', 'diseñar un sitio', 'buscar referencias',
  'inspiración', 'dirección de diseño', 'que no se vea genérico'.
compatibility: >
  Markdown-only. Framer needs network; Pexels reads PEXELS_API_KEY; 21st.dev
  needs the `magic` MCP; Pinterest and screenshots need a browser MCP and
  degrade explicitly without it.
---

# Design Direction Architect

AI-generated sites look generic because the agent starts **without references**.
This skill is the missing phase zero: it interviews, researches real sources,
curates without settling for the first hit, and produces a reference pack that
the building skills consume.

**It never writes the site.** Its output is a direction, not a page.

---

## Skill files (read on-demand)

Read a file only when its step begins. Never preload them.

| File | What's in it | Read at |
|---|---|---|
| `references/interview-guide.md` | the 9 questions, Express vs Full, auto-context detection | STEP 1 |
| `references/structure-only-mode.md` | the branch for a project whose brand is already locked: research the HOW, map tokens, never re-choose the WHAT | STEP 0, 6 |
| `references/style-taxonomy.md` | the 15 styles, defined operationally (type, spacing, motion, per-source keywords, anti-patterns) | STEP 2 |
| `references/category-map.md` | business type → Framer categories + Pinterest queries + 21st keywords | STEP 2 |
| `references/source-framer.md` | Framer URL patterns, sorting, reading the listing / detail / live demo | STEP 3 |
| `references/source-pinterest.md` | browser harvest protocol, query construction | STEP 3 |
| `references/source-21st.md` | the `magic` MCP tools and when each applies | STEP 3 |
| `references/commerce-patterns.md` | how products/services are shown and quoted; what to evaluate | STEP 3b |
| `references/scoring-rubric.md` | the 9 dimensions, the funnel, anti-first-option rule, tie-breaks | STEP 3 (triage dims), STEP 4 |
| `references/curation-protocol.md` | how to present 5 finalists and run the keep/drop loop | STEP 5 |
| `references/variant-preview.md` | the three brand-real variants, the phone review page, the closing link block | STEP 5 (link block), STEP 5b |
| `references/extraction-guide.md` | turning a reference into sections, tokens and a motion inventory | STEP 6 |
| `references/source-pexels.md` | Pexels photo + video API, filters, the 403 gotcha, license | STEP 6b |
| `references/handoff-guide.md` | which building skill gets the pack, and how to phrase the handoff | STEP 7 |
| `references/licensing-and-ethics.md` | reference ≠ copy; per-source licensing | before STEP 7 |
| `templates/tokens.css.tmpl` | provisional tokens (LOCKED VARIANT in structure-only mode) | STEP 5b |
| `templates/*.tmpl` (the rest) | one per output file in `.design/` | STEP 7 |
| `scripts/extract-site.mjs` | Playwright walker: palette by painted area, type scale, section map, desktop + mobile screenshots | STEP 3, 5b, 6 |

Absolute path when needed:
`${CLAUDE_PLUGIN_ROOT}/skills/design-direction-architect/`

---

## Hard rules

1. **Reference ≠ copy.** Never reproduce a reference's copy, images or assets.
   Extract structure, rhythm, scale and pattern — never content.
2. **Never fewer than 5 full-page finalists, and never a pack drawn from a
   single source.**
3. **Never the first option.** Triage at least 15 full-page candidates and
   **walk at least 8** before presenting — `scored` means walked. If the #1 is
   the first candidate you walked, defend it against the other four or demote it.
4. **Zero invented references.** Every URL written to `.design/` must have been
   actually fetched or visited in this session.
5. **Public demos only.** Never screenshot anything behind a login.
6. **Degrade out loud.** If a source is unavailable, say which layer is missing
   rather than pretending coverage.
7. **Stock is not the product.** Pexels supplies atmosphere, texture and B-roll.
   Anything the business actually sells is marked `REAL-PHOTO-NEEDED`.
8. **Never print `PEXELS_API_KEY`** in output, logs, or any `.design/` file.
9. **Never buy a template to study it.** Walk its public demo and extract the
   relationships between values. Reproducing a template's layout, copy or
   assets is forbidden.
10. **Close with the link block.** Any step that produces something the owner
    must look at ends with the clean, phone-readable link block from
    `variant-preview.md` — plain bullets grouped by label, nothing broken,
    nothing extra. The skill's artifacts (contact sheet, variants page) live in
    `.design/preview/` and one `adcm-toolkits:courier` per batch (normally 1;
    the type fixes `sonnet`) publishes them; the main session never calls the Artifact tool. Register the
    rows in `<docs_dir>/artifacts.json` with `in_close_block: false` when the
    container has a brain, otherwise in `.design/artifacts.json` (same schema).
    Because of that flag the courier's default block OMITS these rows, so the
    courier brief carries `BLOCK FLAGS: --only <its files> --include-hidden`: the
    courier's RETURN then lists exactly those rows (REVIEW / REFERENCES / PACK labels
    come from the registry titles) and the main session pastes that block verbatim,
    once, as the last lines — it never runs the preflight itself and never builds
    its own bullets (plain bullets, groups by label prefix; questions go ABOVE the
    block, nothing after).
11. **Pure orchestrator.** The main session interviews (STEP 1), locks the
    direction (STEP 2), decides the curation (STEP 5) and writes the pack
    (STEP 7); it does not browse, score or publish. Delegation map, every call
    an `adcm-toolkits:*` type (which fixes the `model`) or an explicit `model`;
    no plugin in this session → `Agent(subagent_type: "general-purpose", model: "<tier>")`
    with the same brief:
    - **Browsing** (STEP 3 Framer / Pinterest / 21st.dev / Pexels, STEP 3b):
      one `adcm-toolkits:researcher` per source, with Chrome, returning a candidate
      table (source, URL, demo URL, one line each) — never inline screenshots;
      captures go to `.design/refs/`.
    - **Scoring** (STEP 4): an `adcm-toolkits:researcher` called with `model: opus`
      scores the merged tables against the rubric and returns the ranking.
    - **Contact sheet and variants** (STEP 5 / 5b): rendered by an
      `adcm-toolkits:executor-frontend` from the orchestrator's brief; published by the
      `adcm-toolkits:courier`.

    Escape hatch, in the user's own words: `sin tanto lío` (direct mode for
    that one task) or `modo directo` (stays on until `modo orquestador`).
    Canonical rule: `../execution-prompt-architect/references/orchestrator-rule.md`.

---

## Workflow

Seven steps. STEP 3b, STEP 5b and STEP 6b are conditional.

### STEP 0 — Language, mode, auto-context

Detect the prompt's language and answer in it throughout (the skill is written
in English; the conversation is not).

Search the available skills for a `business-init-*` or `code-project-context-*`
that matches this project, and **probe the repo**: `.design/`,
`**/tokens.{css,json,ts}`, `tailwind.config*`, `*design-system*`,
`docs/**/*design*`, `docs/specs/**`, `README*`, any `*-quote-*` skill. Read
what you find and **confirm instead of asking**: "detected <business> — <its
one-line positioning>; going with that?" Nothing detected is skipped silently
and nothing detected is re-asked open — it is shown as a confirm line.

If a design system or token file exists, set **`mode: structure-only`** and read
`references/structure-only-mode.md`: the WHAT (palette, type, register) is
fixed; this run researches the HOW. Record `Brand status` in the brief.

Open the first `AskUserQuestion` with the mode choice: **Express** (questions
1, 2, 3, 6, 9) or **Full** (all nine).

### STEP 1 — Interview

Read `references/interview-guide.md`. Ask via `AskUserQuestion`, batching
related questions. Question 9 (what is sold and how it converts) is never
skipped — it decides whether STEP 3b runs.

### STEP 2 — Lock the direction

Read `references/style-taxonomy.md` and `references/category-map.md`. Convert
the answers into: one or two named styles, the Framer categories to search, the
Pinterest queries and chips, and the 21st.dev keywords. Restate the direction in
two sentences and get a nod before burning search budget.

### STEP 3 — Multi-source search

Start with `mkdir -p .design/refs`. The extractor writes
`<slug>-{desktop|mobile}[-full].png` there; a second pass on the commercial
section is renamed `<slug>-commerce-{desktop|mobile}.png`. Copy every
browser-MCP capture there **immediately** under the same names — they land in
`/var/folders/.../claude-chrome-screenshots-*/` and are lost otherwise.

Read `references/source-framer.md`, `references/source-pinterest.md` and
`references/source-21st.md`. Two-level funnel: **triage at least 15** full-page
candidates (detail page + `--quick` capture; style fit, business fit,
distinctiveness), then **walk the
top 8** with `scripts/extract-site.mjs` for all nine — never `WebFetch`, text
misses everything visual. Record source, URL, demo URL and one line each.

### STEP 3b — Commercial surface search (only if the business sells something)

Read `references/commerce-patterns.md`. Run a **second search with its own
queries** — the best site for the vibe is rarely the best at selling. Collect at
least **8 commercial-section candidates**, independent of the 15. On Framer this
means entering the live demo and scrolling to the product/service section and
the conversion flow; the hero is not enough.

### STEP 4 — Filter and score

Read `references/scoring-rubric.md`. Score every candidate on the 9 dimensions.
The commercial dimension is scored separately, so one reference may win the
overall direction while a different one wins the product section.

### STEP 5 — Curate, keep or drop

Read `references/curation-protocol.md`. Present the 5 finalists as a
**contact-sheet Artifact** (screenshots, per-dimension scores, one line each),
built at `.design/preview/contact-sheet.html` and handed to the courier.
Above the block, ask only *drop + why* — "which leads" is asked once, in STEP 5b.
Close with the courier's RETURN block for these files (rule 10: brief
`BLOCK FLAGS: --only <its files> --include-hidden`), pasted verbatim, once; the
block is the last lines. **≥2 survive → STEP 5b** (with exactly 2, variant C is A+B).
**<2 → STEP 3** with the direction corrected by why they were dropped; the
second return to STEP 3 from anywhere goes to STEP 2 instead.

### STEP 5b — Three variants and the phone review

Read `references/variant-preview.md`. Scores do not let anyone picture the
result. Build **three fast variants of one page using the project's real brand**
— one per surviving direction, deliberately unfinished — and build them as a
single page, `.design/preview/variants.html`, handed to the courier to publish,
with a **viewport toggle**: every variant judged at 390px *and*
at 1440px, because desktop is not the phone stretched. Put the reference
screenshots beside each interpretation. Write `.design/tokens.css`
provisionally from `templates/tokens.css.tmpl` (LOCKED VARIANT in
structure-only mode); STEP 6 refines it, never restarts it.

Ask which leads ABOVE the block (combining two is a valid answer), then close with the
courier's RETURN block for these files (rule 10: brief `BLOCK FLAGS: --only <its files>
--include-hidden`), pasted verbatim, once. The block is the last lines.

### STEP 6 — Extract

Read `references/extraction-guide.md`. Pull the section map, type scale and
pairing, palette with contrast ratios, spacing scale, motion inventory and
responsive patterns. Delegate token extraction to the `extract-design-system`
skill when it is available rather than reimplementing it. In `structure-only`
mode skip palette and type entirely — see `references/structure-only-mode.md`.

### STEP 6b — Source assets (Pexels)

Read `references/source-pexels.md`. Runs **after** the direction is locked —
style dictates image treatment, not the reverse. Propose a candidate set per
slot (hero, sections, textures), never a single image. Fetch video when the
direction calls for a scroll-video or cinematic hero.

### STEP 7 — Write the pack and hand off

Read `references/licensing-and-ethics.md`, then `references/handoff-guide.md`
and the templates. Write into the project:

| File | Contents |
|---|---|
| `.design/brief.md` | direction, audience, style, do/don't, section map |
| `.design/references.md` | the finalists with URL, scores, screenshot, verdict |
| `.design/tokens.css` | color, type, spacing, radii, shadow and motion custom properties |
| `.design/commerce.md` | *(if it sells)* presentation pattern, quote flow, price placement, CTA hierarchy |
| `.design/assets.md` | Pexels manifest: slot → candidates, ids, dimensions, license, `atmosphere` / `REAL-PHOTO-NEEDED` |
| `.design/decisions.md` | dated log — why each option was dropped |
| `.design/refs/*.png` | captures via `scripts/extract-site.mjs` (browser-only fallback in `curation-protocol.md`) — hero **and** commercial section; `refs/mood/*.png` holds Pinterest grid captures |

Then name the building skill that should take over and state exactly what to
tell it.

### `--update`

Re-runs STEP 3 through STEP 7 without repeating the interview, reading the
existing `.design/brief.md` as the locked direction and appending to
`.design/decisions.md`.
