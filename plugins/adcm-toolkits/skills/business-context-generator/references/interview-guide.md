# Interview Guide

The full question bank for the business-context interview. Run one round at a time
with AskUserQuestion (3–6 questions per round). This file is read on-demand at
STEP 2 of the generator workflow — do not load it before the interview starts.

## Modes

- **Express (~20 min):** run only the rounds marked *essential* and, within them,
  only the questions marked ●. Everything skipped is recorded as `[TO BE DEFINED]`.
- **Full (~45–60 min):** run all 8 rounds, all questions.

In both modes, offer to stop after any round and continue in another session —
partial context with honest `[TO BE DEFINED]` markers beats invented answers.

## Rules that apply to every round

1. **Confirm, don't interrogate.** If the website scan (STEP 1) or the conversation
   already answered something, present it as a confirmation ("your site says X —
   correct?") instead of asking from scratch.
2. **The confidentiality question.** End every round by asking: *"Of what you just
   told me, is anything internal — something Claude should know but never share
   with customers, prospects, or in public material?"* Everything marked internal
   goes to `INTERNAL.md`.
3. **Don't invent.** Anything unanswered becomes `[TO BE DEFINED]`, listed later in
   the "Pending context" section of `objectives.md`.
4. **Capture hard rules as they appear.** Whenever the owner says "never say X",
   "don't mention Y", "always confirm Z with me" — in any round — add it verbatim
   to the hard-rules list for the generated SKILL.md.

---

## R1 — Identity & portfolio (essential)

Populates: generated `SKILL.md` header and triggers, `company.md`.

- ● What is the business called (commercial brand) — including any nicknames or
  informal names you and your customers use — and what is the legal entity (LLC,
  INC, etc.)? *(Nicknames feed the generated skill's triggers.)*
- ● What industry is it in, and does it have a website / social profiles? (If a
  website exists and STEP 1 hasn't run yet, run it now before continuing.)
- ● Contact & location: physical address or base of operations, phone, email,
  business hours. *(Confirm rather than ask when web research already found
  them.)*
- ● How old is the business and what stage is it in — idea, building, operating,
  scaling? Any milestones worth knowing (e.g. "6 years, 300 wholesale
  accounts")?
- ● Do you own other businesses that relate to — or could be confused with — this
  one? If so: what are the separation rules (different market, different brand
  story, different pricing)? *(This feeds the disambiguation section and the
  generated skill's triggers.)*
- ● Which languages does the business operate in (with customers vs internally)?
  And which language should the generated skill's content be in? *(default: the
  interview language)*

## R2 — Offering (essential)

Populates: `offering.md`, part of `INTERNAL.md`.

- ● What does it sell or what service does it offer? Be specific about what it
  does **and what it does NOT do** (the negative boundary prevents expensive
  mistakes).
- ● Catalog detail: variants, sizes, tiers, packages, add-ons, typical specs.
- ● Why do customers choose you — the 2–3 real differentiators?
- Notable past work, clients, or portfolio pieces? Are those names public or
  internal?

## R3 — Customers & market (essential; competition optional)

Populates: `market.md`.

- ● Who is the typical customer? Describe 2–3 profiles: who they are, what
  language they speak, what they're looking for, what they worry about.
- ● Where does the business operate — and where does it NOT (and why)? Cities,
  states, countries, online presence, delivery/service area.
- Who are the 2–3 main competitors, and how do you position against them?
- What tone do you use when a customer brings up a competitor?

## R4 — Sales & pricing (essential)

Populates: `sales.md`, `INTERNAL.md`.

- ● How do leads arrive (social, web forms, calls, referrals, walk-ins), and is
  there any tracking/attribution?
- ● What is the sales process from first contact to closed deal, step by step?
  Any CRM or tool that manages it?
- ● What is the real price range? *(goes to `INTERNAL.md`)* — and, separately:
  **how are prices communicated to customers?** (listed openly, "starting at",
  quote-only, negotiable?)
- ● Financing or payment options (installments, deposits, payment methods)?
- Commercial policies: warranty, deposit/refund rules, delivery or turnaround
  times, terms of service.
- The questions leads ask most often, and the top 3 objections — with the answer
  you endorse for each.

## R5 — Brand & communication (essential)

Populates: `brand.md`, hard rules in the generated `SKILL.md`, `INTERNAL.md`.

- ● What tone does the business use with customers — formal or casual/warm, which
  language(s)? *(If STEP 1 inferred a tone from the website copy, present it for
  confirmation.)*
- ● Public narrative: how do you want the business to be perceived? Is there
  anything about how it really operates that is **never said publicly**? *(The
  public framing goes to `brand.md`; the "never say" part goes to `INTERNAL.md`
  and usually becomes a hard rule.)*
- Visual identity: colors, logo, fonts, document templates — or "we don't have
  one".
- Does the business do content marketing (posts, videos)? If so: pillars,
  platforms, cadence, what has worked.
- And with *you* (the owner): what tone should Claude use? Direct? Detailed?

## R6 — Operations & team (essential-lite: ● questions only in Express)

Populates: `operations.md`, `company.md`.

- ● How is what you sell actually produced/delivered? Main phases, capacity,
  realistic lead times.
- ● Who does what on the team, and who decides what (pricing, discounts, hiring)?
- What tools run the business (CRM, accounting, communication, project tracking)?
- Suppliers or manufacturing partners? Is their identity confidential?
- Any licenses, certifications, insurance, or regulations the business must
  comply with?

## R7 — Numbers & direction (optional — offer "now or another session?")

Populates: `objectives.md`, `INTERNAL.md`.

- Approximate margins or cost structure? *(goes to `INTERNAL.md`)*
- Seasonality — strong and weak months?
- Goals for the next 3–12 months, and how you measure them (KPIs)?
- What do you want to improve next? *(feeds "Known roadmap" — it lets Claude
  anticipate future sessions.)*
- Any risks that worry you (dependence on one channel, one client, cash flow)?

## R8 — Closing & rules (essential, short)

Populates: generated `SKILL.md` (hard rules, triggers), `INTERNAL.md`,
`company.md` (glossary).

- ● Any other confidential information Claude should know but never reveal?
- ● What should Claude **never do or say** when working on this business? *(These
  become the hard rules — the most valuable answers of the whole interview.)*
- Internal jargon or terms Claude should understand without explanation?
- Are there other Claude skills related to this business (quote generators,
  contract generators, content engines, a code-project context)?
- Anything else Claude needs to be useful from day one?
