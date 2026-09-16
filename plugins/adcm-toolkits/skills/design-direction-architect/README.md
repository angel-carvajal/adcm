# design-direction-architect

Phase zero for web design: research and lock a visual direction **before** any
code exists, then hand a reference pack to whichever skill builds the site.

## Why

AI-generated sites look generic because the agent starts with no references.
Most design skills are excellent at building and assume you already carry the
direction in your head. This one produces that direction.

## What it does

1. Interviews you (9 questions, or 5 in Express mode) — auto-filling from a
   `business-init-*` or `code-project-context-*` skill when one matches.
2. Converts the answers into a named style plus per-source search terms.
3. Searches four real sources:
   - **Framer marketplace** — 50 industry categories, and every template exposes
     a live demo site you can actually walk through.
   - **Pinterest** — via a browser, harvesting the results grid with
     `javascript_tool` (topic chips only when they render).
   - **21st.dev** — components, themes and templates through the `magic` MCP.
   - **Pexels** — photo and video assets, filtered by your own palette.
4. Triages at least 15 candidates, walks at least 8 and scores those on 9
   dimensions, then presents 5 finalists backed by
   at least two sources — never the first hit.
5. Runs a second, separate search for the **product/service section and the
   quote-or-checkout flow** when the business sells something.
6. Writes `.design/` — brief, references, tokens, commerce, assets, decisions,
   screenshots — and hands off.

## What it does not do

It does not build the site. `epic-design`, `interface-design`,
`frontend-design`, `ui-ux-pro-max` and `emil-design-eng` do that, and they do it
better with this pack in hand.

## Requirements

| Source | Needs |
|---|---|
| Framer | network only |
| Pexels | `PEXELS_API_KEY` in the environment |
| 21st.dev | the `magic` MCP server |
| Pinterest | a browser MCP (`claude-in-chrome`) — degrades explicitly without it |

## Usage

```
design direction for a food trailer landing page
design-direction-architect --update      # re-research, keep the interview
```
