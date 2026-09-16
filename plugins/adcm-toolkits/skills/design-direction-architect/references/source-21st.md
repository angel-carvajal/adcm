# Source: 21st.dev — STEP 3 and STEP 3b

Component-level, via the `magic` MCP server. Where Framer and Pinterest give
whole-page direction, 21st.dev gives the **section-level building blocks** — and,
critically, blocks that are actually installable when the stack is React/shadcn.

## Tools

| Tool | Use |
|---|---|
| `mcp__magic__search` | metadata-only search across components, themes and templates. Free. `type` scopes to one kind. |
| `mcp__magic__get_inspiration` | the same corpus reranked against project design context, with confidence and rationale. Use when a `.design/` pack or project context already exists. |
| `mcp__magic__search_logo` | brand logo lookup for logo clouds and trust rows. |
| `mcp__magic__get_component` | retrieves the actual component code. **Paid** — never call it during research. Only at build time, and only for a component the user chose. |
| `mcp__magic__get_theme` | free CSS for a theme result. Useful input to `tokens.css`. |

## Rules

- **Research is metadata-only.** `search` and `get_inspiration` are free;
  `get_component` is not. This skill never fetches component code — that belongs
  to the building skill after the user picks.
- **Stack gate.** Components are shadcn/React. If Q6 said plain HTML, Astro
  without React, or WordPress, 21st.dev results are **inspiration only** — mark
  them as such in `.design/references.md` and do not present install commands.
- Query the **section**, not the business: "pricing table", "product card",
  "multi step form", "bento grid", "testimonial carousel", "video hero".
  Prefix with the style adjective when it helps: "dark pricing table".
- `type: "template"` results have no code to fetch — they are whole-page
  direction, so they compete with Framer candidates, not with components.
- `get_inspiration` with `diversity: true` (the default) avoids returning five
  near-identical cards from the same author. Keep it on.

## What to record per candidate

Name, author, `url`, `previewUrl`, whether a `videoUrl` exists, and the install
command **verbatim** (never reconstruct it by hand). For themes, note the color
bucket — a theme whose palette already matches the brand saves a token pass.

## Pitfalls

- Ranking rewards popularity; the top result is often the most-cloned component
  on the internet. That is exactly what the anti-slop dimension penalizes.
- `author` / `mine` / `liked` filters bypass ranking entirely and return plain
  recency lists — do not use them during research and expect relevance.
