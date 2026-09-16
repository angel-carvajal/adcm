# Interview guide — STEP 1

Ask in the user's language. Batch related questions into one `AskUserQuestion`
call (up to 4 per call). Lead every multiple-choice list with a recommendation
when one is obvious from the auto-context.

## Auto-context first

Before asking anything, look for an installed skill matching this project, and
run the repo probe from SKILL.md STEP 0 (`.design/`, a tokens file, tailwind
config, or a design-system doc):

- `business-init-*` → identity, offering, audience, brand voice, palette, tone
- `code-project-context-*` → stack, existing conventions, deployment target
- repo probe → existing tokens, palette, type, register (drives `mode:
  structure-only`)

If found, read it and **confirm rather than ask**:

> "Detected <business name> — <one-line positioning from its context skill:
> what it sells, to whom, what sets it apart>. Using that as the business
> context. Correct?"

Everything auto-context or the repo probe can answer is shown as
`detected: X — correct?` inside the same `AskUserQuestion` batch — Q7 and Q9
included. Nothing is skipped silently, and nothing detected is re-asked as an
open question. Q9 is still always shown: as a confirm line when detected, as
an open question otherwise — never silently auto-filled.

## Modes

The first `AskUserQuestion` call opens with the mode choice itself: "Express —
5 questions / Full — 9 questions".

| Mode | Questions | When |
|---|---|---|
| Express | 1, 2, 3, 6, 9 (Q1/Q6 become confirm lines when auto-context has them) | user picks it |
| Full | all 9 | default |

## The nine questions

**Q1 — Business type / industry.** Free text. Maps to Framer categories via
`category-map.md`. If the industry is not in the 50-category list, pick the two
nearest and say which.

**Q2 — What is being designed.** Landing page · portfolio · multi-page
marketing site · e-commerce storefront · dashboard/app UI · mobile app ·
one-pager. This decides which sources dominate: Framer and Pinterest for
marketing surfaces, 21st.dev for app and dashboard surfaces.

**Q3 — Style.** Multi-select from `style-taxonomy.md`, **maximum two**, plus an
`other: <label>` option for when none of the 15 fits. Combining two is allowed
and often good (e.g. `editorial` + `dark-luxury`). Free text is allowed;
derive it onto the taxonomy's dimensions and say which named style it lands
nearest. In `mode: structure-only`, Q3 is not a pick — it becomes a confirm of
the register already detected from the existing tokens.

**Q4 — Audience and intended feeling.** Who lands here, and what should they feel
in the first three seconds. Capture the feeling as adjectives — they become
Pinterest query terms.

**Q5 — References already loved or hated.** Ask for URLs. A hated reference is
worth more than a loved one: it defines the anti-pattern set for STEP 4. If they
have none, say so and move on — do not stall.

**Q6 — Target stack.** Next.js/React · plain HTML/CSS · Astro · Framer itself ·
WordPress · other. Gates feasibility scoring, and decides whether 21st.dev
components are installable at all (they are shadcn/React).

**Q7 — Existing brand constraints.** Logo, palette, typefaces already fixed?
Auto source: the repo probe (tokens file, tailwind config, design-system doc)
— when it finds one, Q7 is shown as a confirm line, not an open question.
Anything locked here becomes a constraint on token extraction in STEP 6 and on
the Pexels `color` filter in STEP 6b.

**Q8 — Motion budget and performance floor.** Static · subtle (hover, fade,
reveal) · cinematic (scroll-driven, pinned sections, video). Ask for the
performance floor too — a cinematic direction on a slow connection is a promise
you cannot keep. Record both; they are scored as "motion fit" and "feasibility".

**Q9 — What is sold and how it converts.** Never skipped. Shown as a confirm
line when auto-context has it, never silently auto-filled.
Two parts:

- **What:** products · services · both · nothing (informational/portfolio).
- **How:** if it sells — roughly how many SKUs or packages, public price or
  quote-only, and the conversion action: cart/checkout · multi-step quote wizard
  · simple quote form · book a call · WhatsApp · request a catalog.

A non-empty answer here **activates STEP 3b**. Record the answer verbatim; it is
the input to `commerce-patterns.md`.

The confirmation nod happens once, in STEP 2 — not here.
