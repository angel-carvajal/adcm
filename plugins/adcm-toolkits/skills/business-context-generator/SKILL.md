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
  negocio', 'business context', 'I already have the material', 'mine my
  documents', 'build the context from what exists', 'ya tengo el material',
  'sácalo de los documentos', 'arma el contexto con lo que ya existe', or any
  variation where they want Claude to understand and remember a business for
  future working sessions.
compatibility: >
  No runtime dependencies. Markdown-only skill. Uses AskUserQuestion for the
  interview and WebFetch for website research when available; degrades to a
  plain-text interview without them. Works in Claude Code, Cowork, and claude.ai.
last_updated: 2026-09-19
protocol: 0.11.0
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
| `references/existing-sources.md` | mining protocol: source families, miner brief, fact-sheet schema, consolidation, confidentiality defaults | STEP 1b |
| `references/delivery-guide.md` | how to deliver the generated skill (private marketplace or `.skill` zip) | STEP 5 |
| `templates/SKILL.md.tmpl` | index of the generated skill (identity, hard rules, task→file map, rules) | STEP 3 |
| `templates/*.md.tmpl` | one per generated reference file (`company`, `offering`, `market`, `brand`, `sales`, `operations`, `objectives`, `INTERNAL`) | STEP 3 |

When an absolute path is needed, this skill lives at
`${CLAUDE_PLUGIN_ROOT}/skills/business-context-generator/`.

---

## Agent roles (the tiered protocol)

Same tiered protocol as `execution-prompt-architect` (canonical role table in its
"Agent roles" section); here the roles mine sources instead of writing code:

| Role | Model | Does | Never does |
|---|---|---|---|
| **Orchestrator** | the main session (Fable) | Owns STEP 0. Writes the miner briefs. **Audits** every fact sheet that comes back (contradictions, staleness, confidentiality class) and consolidates them into ONE sheet. Runs the interview. Fills a tiny gap itself (one Read/grep) instead of spending an agent. | Mine a whole source family itself when agents are available. Delegate AskUserQuestion. Spawn agents of its own tier. |
| **Miner / Auditor** | `adcm-toolkits:researcher` called with `model: opus` (quota 10); the refuter pass is an `adcm-toolkits:auditor` | One source FAMILY each: extracts facts into the row schema, flags UNKNOWNs, proposes a confidentiality class. Also the single refuter pass over the consolidated sheet. | Write files. Interview the user. Invent a value. Read outside its `PATHS`. |
| **Bulk extractor** | `adcm-toolkits:researcher` (default `sonnet`) | Mechanical families: decks/HTML, CSS tokens, catalog dumps. Proposes a class; the orchestrator decides. | Judge confidentiality, resolve conflicts, or decide scope. |
| **Researcher / Generator** | `adcm-toolkits:researcher` (STEP 1) and `adcm-toolkits:executor` (STEP 3), one per file or family | STEP 1 website research (returns a short fact sheet, never raw pages) and STEP 3 generation of the 8 context files from the audited fact sheet and the interview answers, written to disk. | Decide scope, judge confidentiality, or interview the user. |

**Pure-orchestrator rule.** The main session does only STEP 0, the interview (STEP 2),
the audit of the fact sheets and the review (STEP 4); STEP 1 web research and STEP 3
generation are always delegated to the sub-agents above, each call an `adcm-toolkits:*` type
or an explicit `model` (no plugin in this session → `Agent(subagent_type: "general-purpose",
model: "<tier>")` with the same brief), each RETURN short and structured (files written, rulings, open questions),
never whole files. Escape hatch, in the user's own words: `sin tanto lío` (direct mode
for that one task) or `modo directo` (stays on until `modo orquestador`). Canonical
rule: `../execution-prompt-architect/references/orchestrator-rule.md`.

**Budget: 20 delegated agents per run.** Every call carries an explicit `model` or an `adcm-toolkits:*` type; `SendMessage`
to a live miner costs 0; a realistic run spends 4–8. Reaching 20 means STOP and ask
the user — and no agent may spawn unbounded amplifiers of its own.

---

## Workflow

### STEP 0: Language, mode, target, and existing sources

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
4. **Existing sources.** Asked in the SAME AskUserQuestion call as mode and
   language: does the venture already have artifacts to mine — sales decks or
   presentations, a database (seed/migrations with catalog and prices), a
   quoting/pricing tool, execution or planning docs of this or a sibling venture,
   brand assets (CSS tokens, logos), prior Claude skills or memory files? **YES →
   STEP 1b**, and the interview shrinks to the UNKNOWN list. **NO** → the classic
   flow, unchanged.

### STEP 1: Website research (before asking anything)

If the business has a website, read `references/web-research.md` and run the protocol
with WebFetch **before Round 1**. Pre-fill everything you can (identity, offering,
value proposition, portfolio, hours, tone of the current copy) and turn questions
into confirmations. Ask the owner whether the website is a reliable source of truth.
If WebFetch is unavailable or the site fails, degrade to the plain interview.

### STEP 1b: Pre-fill from EXISTING SOURCES (fan-out)

Only when STEP 0 item 4 answered YES. Read `references/existing-sources.md`.

1. **Inventory with the owner.** Agree the paths: one line per source family and
   what that family should prove.
2. **Fan out ONE agent per family** (≤6): `adcm-toolkits:researcher` with `model: opus` for judgement families, plain
   `adcm-toolkits:researcher` (`sonnet`) for bulk ones, each with a miner brief plus the fact-sheet row schema.
   Families are **DISJOINT trees** — no two miners read the same path.
3. **Audit and consolidate — the orchestrator, never delegated.** Dedupe; resolve
   conflicts by authority (**prod DB > product code > execution docs > collateral
   > memory > website**); assign a class per fact; emit an explicit UNKNOWN list.
   The result is ONE fact sheet.
4. **Present the sheet as a confirmation batch**, then go to STEP 2 with the
   interview reduced to the UNKNOWNs plus everything marked `inferred`.

Website research (STEP 1) is simply family **F0**, with the lowest authority of all.
**Never block on mining:** a family that yields nothing becomes UNKNOWNs.

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

Rules that always apply: never re-ask what the conversation, the website or the
fact sheet already answered — confirm instead; in every round, explicitly ask what
is confidential; record unanswered items as `[TO BE DEFINED]`.

**With a fact sheet the interview shrinks.** R1–R7 collapse into (a) ONE
confirmation batch per round carrying only that round's mined facts ("tick what is
wrong") and (b) questions for that round's UNKNOWNs and every fact marked
`inferred`; `verbatim` facts are confirmed in bulk. **R8 always runs in full** —
hard rules, "never say X" and the confidentiality split are the owner's judgements,
not artifacts. A well-mined Full interview lands near Express in wall clock without
losing a round.

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
4. **Provenance survives generation.** Every mined fact keeps an HTML comment at
   the end of the line or bullet it feeds —
   `<!-- src: <path>#<anchor> · as-of <date> · verbatim|derived|inferred -->` —
   invisible when rendered. The full fact sheet, private paths included, is
   appended to `references/INTERNAL.md` under `## Sources & freshness`: paths to a
   venture's repos and databases are themselves internal.
5. **Mined ≠ public.** A fact's class follows the AUDIENCE of the artifact it came
   from, never its location on disk: a price in a dealer deck is partner-facing →
   `INTERNAL.md` unless the owner declassifies it; a price in a migration or a
   quoting RPC is CONFIDENTIAL by default; a claim on the public website is
   public. The STEP 4 review is unchanged — the owner still has the last word.
6. List every `[TO BE DEFINED]` item in the "Pending context" section of
   `objectives.md`. An item that came from an UNKNOWN records what was already
   searched — `[TO BE DEFINED] — margins (not found in: migrations, quoting tool,
   execution docs; searched 2026-09-19)` — so update-mode never re-mines the same
   ground.
7. Render all content — including section headings — in the language chosen in
   STEP 0; file names, placeholders and structure stay in English.

### STEP 4: Review with the owner

Present: the generated tree, the context-file table, and — explicitly — the
confidentiality split: *"this is what ended up in INTERNAL.md — is anything missing,
or is anything there that shouldn't be?"*. Also confirm the **hard rules** list.
Iterate until approved.

### STEP 5: Deliver

Read `references/delivery-guide.md` and offer both routes:

- **Option A — the user's private plugin marketplace** (recommended when they have
  one): by the standard container convention the home is
  `<container>/ai/<slug>-{ai|ia}-admin/plugins/<x>-admin/skills/` (see
  `../execution-prompt-architect/references/project-structure.md`; scaffold the
  marketplace there — own git repo — if the container exists without one). Place the
  folder in that plugin's `skills/` directory and walk them through the version bump
  + commit. Never push their repo for them.
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
- **Mine before you ask:** facts that already exist in an artifact are extracted,
  not asked for. The interview spends its budget on judgements — rules,
  confidentiality, tone — never on data entry.
- **Provenance or it didn't happen:** every mined fact carries its path, its date
  and its confidence. No source = `inferred` = must be confirmed by the owner; an
  `inferred` fact nobody can confirm becomes `[TO BE DEFINED]`.
- **Accuracy over completeness:** record what you don't know as `[TO BE DEFINED]`
  rather than inventing — especially prices, dates, and policies.
- **Generous triggers:** the generated description includes the brand, legal
  entity, domain, nicknames, and disambiguation against the owner's other
  businesses.
- **Living, not fossilized:** update mode (STEP 0) refreshes an existing skill
  incrementally; the generated skill itself instructs Claude to offer updates when
  the owner contradicts or completes the stored context.
