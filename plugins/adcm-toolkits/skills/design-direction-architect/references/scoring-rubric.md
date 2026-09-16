# Scoring rubric — STEP 4

Triage **every** candidate and score every **walked** one before presenting any. Scoring after you have a
favorite is rationalization, not evaluation.

## The dimensions

Nine, each 1–5. Dimension 9 applies only when STEP 3b ran, and is tallied
**separately** — the overall winner and the commercial-section winner are allowed
to be different references.

| # | Dimension | 1 | 5 |
|---|---|---|---|
| 1 | **Style fit** | contradicts the named style | textbook execution of it |
| 2 | **Business fit** | wrong industry conventions entirely | speaks this industry's language |
| 3 | **Section coverage** | missing most sections this project needs | every needed section is present and solved |
| 4 | **Craft** | misaligned, inconsistent, unfinished | deliberate at every scale |
| 5 | **Motion fit** | motion fights the Q8 budget | motion matches budget and earns its cost |
| 6 | **Feasibility** | cannot be built in the Q6 stack | maps cleanly onto the stack |
| 7 | **Distinctiveness** | indistinguishable from a thousand others | one memorable move you can name |
| 8 | **Accessibility headroom** | contrast or hierarchy fails outright | accessible as-is, with margin |
| 9 | **Commercial fit** *(3b only)* | hides price, buries CTA, high friction | price and CTA where the buyer needs them |

## Scored means walked

A candidate is scored only if `scripts/extract-site.mjs` ran on it in **full
mode** — a `--quick` triage capture is not a walk — or, when the script is
unavailable, a full-page browser walk of it exists in `.design/refs/`. No walk,
no full score.

Everything else gets a **TRIAGE** record instead: name, category, one line,
and 3 quick dimensions read off the hero capture — style fit, business fit,
distinctiveness. Zero full dims: no section coverage, craft, motion,
feasibility, or accessibility score without the walk.

Funnel: **triage ≥15 → walk ≥8 → 5 finalists**. Walk the candidates the
triage scores favor, not whichever loads fastest.

## Thresholds

- Anything below **3 on dimension 6 (feasibility)** is cut regardless of total.
  A beautiful reference you cannot build is a distraction.
- Anything below **3 on dimension 8** is cut unless the user explicitly accepts
  fixing contrast during the build; note the accepted debt in `decisions.md`.
- **Dimension 7 breaks ties.** Between two references with equal totals, take
  the more distinctive one. Slop is the failure mode this whole skill exists to
  prevent.

## Anti-first-option rule

Hard, and checked before presenting:

1. At least **15 triaged**, at least **8 walked** to full scoring (plus at
   least **8 commercial candidates** if STEP 3b ran) — see **Scored means
   walked** above.
2. Finalists are **layered**, not flat:
   - **Full-page finalists** — ≥5, all walked: Framer demos, live sites
     sourced from Q5 or from web search. These carry the full nine-dimension
     score.
   - **Section finalists** — 21st.dev components, scored on dims 4 and 6
     (craft, feasibility), plus 9 when STEP 3b ran.
   - **Mood evidence** — Pinterest pins carry no score and attach to a
     finalist by id; a pin is never a finalist. If a pin's source site gets
     walked, that walk counts as a full-page finalist — the pin still doesn't.
   "≥2 sources" still binds the finalist set (full-page + section finalists);
   mood evidence never counts toward it, though it is recorded in
   `.design/references.md`.
3. If the top-scored candidate is the **first one you walked**, that is a
   smell, not a win — the bias runs toward the first walked, not the first
   listed. Defend it with an explicit paragraph against the other four, or
   demote it.
4. No more than **2 finalists from the same author or studio** — Framer
   author, 21st.dev author, or pin origin domain, whichever applies. An
   unresolved origin is never promoted past mood evidence.

## The anti-pattern check

Before scoring style fit, load the chosen style's anti-pattern list from
`style-taxonomy.md` and the Q5 "references I hate" set. Any candidate hitting an
anti-pattern is capped at 2 on dimension 1 — no matter how good it looks.

## Recording

Keep a scoring table with one row per **walked** candidate: source, URL, the
nine scores, total, and a one-line verdict. Triage rows carry the three quick
dims only; section finalists carry 4, 6 and — when 3b ran — 9. It goes into `.design/references.md` for the
finalists and `.design/decisions.md` for everything cut.

Write the *reason* for each cut, not just the score. In STEP 5 the user's
rejections are re-searched against these reasons, and a bare number tells you
nothing about what to search for next.

Add one line per convergence: `Convergence: <value> — <ref A>, <ref B>, <ref C>`
for any token — color, type choice, motion pattern — that **2+ walked
references** independently landed on. Convergence is evidence for the brief;
it is not a score bonus.
