# design-direction-architect

Phase zero for web design: research and lock a visual direction **before** any
code exists, then hand a reference pack to whichever skill builds the site.

## Why

AI-generated sites look generic because the agent starts with no references.
This skill produces the direction the building skills assume you already have.

## What it does

1. Interviews you (9 questions, or 5 in Express mode) — auto-filling from a
   `business-init-*` or `code-project-context-*` skill when one matches.
2. Converts the answers into a named style plus per-source search terms.
3. Gathers references from five sources:
   - **Framer marketplace** — 50 industry categories, each template with a live demo.
   - **Awwwards** — live sites that won or were nominated for your styles.
   - **21st.dev** — components, themes and templates through the `magic` MCP.
   - **Pexels** — photo and video assets, filtered by your palette.
   - **Inspiration folder** — pins and images you drop in `.design/inspiration/`
     by hand (optional `<image>.url` sidecar keeps the source link).
   A market search adds competitors and adjacent references.
4. Scripts capture every candidate at 390 and 1440 px, then the finalists are
   scored on 9 dimensions: 5 finalists backed by at least two sources, never the first hit.
5. Builds **one fixed board**, `.design/board.html`, with 5 tabs: Market,
   References (drop what you dislike, with a reason), Options (exactly 3
   previews), Method and Tokens.
6. **Token export**: toggle font pair, scale and palette per option, press
   Export and paste the short combo code in the chat. `design-board adopt`
   turns it into `.design/tokens.css` + `tokens.json`, the source of truth for the build.
7. Writes the `.design/` pack (brief, references, tokens, commerce, assets,
   decisions) and hands off. Agents write data; scripts write the HTML.

## What it does not do

It does not build the site. `epic-design`, `interface-design`,
`frontend-design`, `ui-ux-pro-max` and `emil-design-eng` do that, and they do it
better with this pack in hand.

## Requirements

Python 3 (board builder) · Node >= 20 + playwright-core >= 1.61 + Chrome (captures; `design-board doctor`) · WebSearch for market and Awwwards · Pexels reads `PEXELS_API_KEY` · 21st.dev needs the `magic` MCP · Pinterest is a manual folder

## Usage

```
design direction for a food trailer landing page
design-direction-architect --update      # re-research, keep the interview
design-board doctor                      # check Node, playwright-core, Chrome
design-board init .design                # board.json + board.d/ + inspiration/
design-board capture --board .design/board.json  # screenshots and metrics (--variants for options)
design-board check .design              #
design-board build .design              # validate, then write board.html
design-board mark --drop R03 --why "too corporate" .design
design-board adopt "<combo code>" .design # tokens.css + tokens.json
design-board log --step 5 --decided "…" --date YYYY-MM-DD .design  # append to decisions.md
design-board pack .design              # references.md + market summary
```
