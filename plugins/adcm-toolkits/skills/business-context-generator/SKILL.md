---
name: business-context-generator
description: >
  Interviews a business owner and researches the business website to generate an
  installable, lazy-loading business-context skill of the form
  `business-init-[business-slug]` (the resulting SKILL.md loads only the identity,
  the hard rules and an index; per-topic detail lives in references/ files read
  on-demand). Triggers when the user asks to 'create business context', 'new
  business', 'add a business', 'business init', 'business context creator',
  'register a business', 'create a business profile', 'I want you to know my
  business', 'give me context for another business', 'I have another business',
  'crear contexto de negocio', 'nuevo negocio', 'registrar negocio', 'perfil de
  negocio', 'business context', or any variation where they want Claude to
  understand and remember a business for future working sessions.
compatibility: >
  No runtime dependencies. Markdown-only skill. Uses AskUserQuestion for the
  interview and WebFetch for website research when available; degrades to a
  plain-text interview without them. Works in Claude Code, Cowork, and claude.ai.
---

# Business Context Generator

This skill guides the process of interviewing a business owner (plus researching the
business website) and generating an installable context skill of the form
`business-init-[business-slug]` (the slug is the kebab-case form of the business
name). The resulting skill is designed with **lazy-loading**:
its SKILL.md carries only what every task needs (a 30-second summary, contact
identity, the hard rules, and an index), and the per-topic detail lives in
`references/` files that are read on-demand when the task requires them.

---

## Purpose

Solve the problem of "starting a session without having to explain to Claude what the
business sells, who buys it, how it talks to customers, what it charges, and what must
never be said publicly". After running this skill once, future sessions can invoke the
resulting `business-init-*` skill and Claude will have full business context for any
task — documents, reports, quotes, marketing, lead replies, analysis, decisions.

---

## Skill files (read on-demand)

| File | What's in it | Read at |
|---|---|---|
| `references/interview-guide.md` | the 8 interview rounds, Express/Full modes, per-round confidentiality question | STEP 2 |
| `references/web-research.md` | website research protocol (what to fetch, what to extract, confirm-don't-ask) | STEP 1 |
| `references/delivery-guide.md` | how to deliver the generated skill (private marketplace or `.skill` zip) | STEP 5 |
| `templates/SKILL.md.tmpl` | index of the generated skill (identity, hard rules, task→file map, rules) | STEP 3 |
| `templates/*.md.tmpl` | one per generated reference file (`company`, `offering`, `market`, `brand`, `sales`, `operations`, `objectives`, `INTERNAL`) | STEP 3 |

When an absolute path is needed, this skill lives at
`${CLAUDE_PLUGIN_ROOT}/skills/business-context-generator/`.

---

## Workflow

### STEP 0: Language, mode, and target

1. **Language.** Run the interview in the user's language (auto-detect from their
   prompt). Ask once, in Round 1, which language the generated skill's *content*
   should be in — default is the interview language. File names and structure are
   always English; only the content (including section headings) changes language.
2. **New vs update.** If the user points at an existing `business-init-*` skill,
   switch to **update mode**: read the existing skill, interview only for what
   changed, preserve everything untouched, and bump `last_updated` in the
   frontmatter. Never regenerate an existing skill wholesale without explicit
   confirmation.
3. **Depth.** Offer two modes: **Express** (~20 min — essential rounds only;
   everything else is recorded as `[TO BE DEFINED]`) and **Full** (~45–60 min —
   all 8 rounds).

### STEP 1: Website research (before asking anything)

If the business has a website, read `references/web-research.md` and run the protocol
with WebFetch **before Round 1**. Pre-fill everything you can (identity, offering,
value proposition, portfolio, hours, tone of the current copy) and turn questions
into confirmations. Ask the owner whether the website is a reliable source of truth.
If WebFetch is unavailable or the site fails, degrade to the plain interview.

### STEP 2: The interview

Read `references/interview-guide.md` and run the rounds with AskUserQuestion
(3–6 questions per round, one round at a time):

- **R1 — Identity & portfolio** (essential)
- **R2 — Offering** (essential)
- **R3 — Customers & market** (essential; competition part optional)
- **R4 — Sales & pricing** (essential)
- **R5 — Brand & communication** (essential)
- **R6 — Operations & team** (essential-lite)
- **R7 — Numbers & direction** (optional — offer "now or another session?")
- **R8 — Closing & rules** (essential, short)

Rules that always apply: never re-ask what the conversation or the website already
answered — confirm instead; in every round, explicitly ask what is confidential;
record unanswered items as `[TO BE DEFINED]`.

### STEP 3: Generate the skill

Render the templates in `templates/` with the collected answers:

1. `SKILL.md.tmpl` → the generated index (identity, **hard rules**, context-file
   table, task→file map, rules for Claude).
2. One `references/<topic>.md` per applicable template. **Omit files that don't
   apply** to this business (don't leave empty scaffolding) and prune every
   mention of an omitted file from the generated index: its row in the
   context-file table, its rows in the task→files map (remove or reroute them),
   and its name in the frontmatter description's file list. For simple
   businesses the minimum viable set is `offering.md`, `sales.md`, `brand.md`,
   and `INTERNAL.md` (INTERNAL.md is always generated).
3. Everything the owner marked confidential goes to `references/INTERNAL.md` —
   never inline in the other files.
4. List every `[TO BE DEFINED]` item in the "Pending context" section of
   `objectives.md`, so the generated skill knows what it is missing.
5. Render all content — including section headings — in the language chosen in
   STEP 0; file names, placeholders and structure stay in English.

### STEP 4: Review with the owner

Present: the generated tree, the context-file table, and — explicitly — the
confidentiality split: *"this is what ended up in INTERNAL.md — is anything missing,
or is anything there that shouldn't be?"*. Also confirm the **hard rules** list.
Iterate until approved.

### STEP 5: Deliver

Read `references/delivery-guide.md` and offer both routes:

- **Option A — the user's private plugin marketplace** (recommended when they have
  one): place the folder in their private plugin's `skills/` directory and walk
  them through the version bump + commit. Never push their repo for them.
- **Option B — standalone `.skill` zip** for manual installation or claude.ai.

---

## Structure of the resulting skill

```
business-init-[business-slug]/
├── SKILL.md              # index (ALWAYS loaded): 30-second summary, contact
│                         #   identity, HARD RULES, context-file table,
│                         #   task→file map, rules for Claude
└── references/
    ├── company.md        # extended identity, history & stage, sibling-business
    │                     #   disambiguation, team & decision-making, glossary, legal
    ├── offering.md       # what it sells / does NOT sell, catalog, value prop, track record
    ├── market.md         # segments & personas, geography (where yes/no), competition
    ├── brand.md          # voice & tone, public narrative, visual identity, content
    ├── sales.md          # lead channels, sales process, public pricing policy,
    │                     #   financing, FAQs & objections, commercial policies
    ├── operations.md     # delivery process, capacity & lead times, suppliers, tools
    ├── objectives.md     # goals & KPIs, known roadmap, risks, pending context
    └── INTERNAL.md       # CONFIDENTIAL: real price ranges, margins, framing
                          #   secrets, named clients, real suppliers, owner data
```

---

## Principles

- **Strict lazy-loading:** the generated SKILL.md must be short (< 120 lines). All
  the weight goes into `references/`. Never inline per-topic detail into the index.
- **Hard rules first:** the inviolable rules (what must never be said or done) live
  in the generated SKILL.md, always loaded — they must hold even when no reference
  file has been read.
- **Confidentiality by construction:** ask what's internal in every round;
  everything marked internal lands only in `INTERNAL.md`; internal content may
  *inform* work but is never *copied* into anything a third party will see.
- **Confirm, don't interrogate:** research the website first; turn questions into
  confirmations. Never re-ask what's already known.
- **Accuracy over completeness:** record what you don't know as `[TO BE DEFINED]`
  rather than inventing — especially prices, dates, and policies.
- **Generous triggers:** the generated description includes the brand, legal
  entity, domain, nicknames, and disambiguation against the owner's other
  businesses.
- **Living, not fossilized:** update mode (STEP 0) refreshes an existing skill
  incrementally; the generated skill itself instructs Claude to offer updates when
  the owner contradicts or completes the stored context.
