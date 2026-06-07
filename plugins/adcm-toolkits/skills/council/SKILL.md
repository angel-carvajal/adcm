---
name: council
description: >
  Convenes a council of 5 advisors (Strategist, Adversary, Outsider, Operator,
  Futurist) plus a Chairman to deliberate on a decision and deliver an
  actionable verdict. Inspired by Karpathy's LLM Council and Oli Limán's Claude
  Council. Use when the user says 'ask the council', 'council:', 'convene the
  council', 'consult the council', 'what does the council say', or any
  variation requesting multi-perspective deliberation on a technical, business,
  personal, or academic decision. Supports a
  context flag (double-dash + the word context + comma-separated hook names that
  map to files in contexts/) to inject domain context into 4 of the 5 advisors.
  Supports a deep flag (double-dash + deep) to enable Stage 2 cross-review,
  currently a stub. Output language is auto-detected from the user's prompt
  (English or Spanish).
compatibility: >
  No runtime dependencies. Markdown-only skill read by Claude. In Claude Code,
  parallel advisor execution uses the built-in Task tool; in claude.ai/Cowork it
  falls back to sequential context-isolated reads. Works in Claude Code, Cowork,
  and claude.ai.
---

# The Council — Multi-Advisor Deliberation Skill

Inspired by [Andrej Karpathy's LLM Council](https://github.com/karpathy/llm-council) and [Oli Limán's Claude Council](https://www.linkedin.com/in/olilo/), but redesigned to be an **actionable advisory council** that lives as a native Claude skill and works in Claude Code, Cowork, and claude.ai.

When triggered, Claude convenes 5 specialized advisors who respond in parallel (or sequentially with context isolation, depending on the environment), optionally do a cross-review, and a Chairman synthesizes an actionable verdict.

---

## When it activates

Explicit user triggers:

- `ask the council: <question>`
- `council: <question>`
- `convene the council <question>`
- `consult the council <question>`
- `what does the council say? <question>`
- Any similar phrase meaning "I want multi-perspective deliberation on this"

Optional flags:

- `--context <hook>` or `--context <hook1,hook2>` — injects business context into 4 of the 5 advisors (the Outsider is always context-blind by design). The hook name corresponds to a file the user places in `contexts/<hook>.md`. Available hooks: see the `contexts/` folder.
- `--deep` — activates Stage 2 (cross-review among advisors). **Currently a stub** — the flag is accepted but only leaves a note in the output. It will be implemented in a future iteration.

Examples:

```
ask the council: should I hire a second person for my team?
ask the council --context example: do I launch the new product now or wait to validate 10 customers?
council --context example: how do I split my week between two priorities?
ask the council --deep --context example: <big question>
```

(`example` corresponds to the sample file `contexts/example.md`. Replace it with your own hooks — see "Context hooks" below.)

---

## Output language

**Automatically detects** the language of the user's prompt. If the user writes in Spanish, all output (advisors + Chairman) is in Spanish. If they write in English, everything is in English. Do not mix languages within a single deliberation.

---

## Execution flow

### Step 1 — Parse the invocation

1. Extract the **question** (everything after the trigger and the flags).
2. Detect which flags are present:
   - `--context <list>` → read each hook in `contexts/<hook>.md` and keep its content as "injectable context" for the context-enabled advisors.
   - `--deep` → mark to activate Stage 2 (stub for now).
3. Detect the language of the prompt.

If a referenced context hook does not exist in `contexts/`, warn the user and proceed without context (do not fail).

### Step 2 — Convene the 5 advisors

Each advisor runs as an **isolated thinking block** — Claude must process its prompt without the other advisors' output contaminating it. In Claude Code this is done with parallel sub-agents via the `Task` tool. In claude.ai/Cowork it is done sequentially, but reading each advisor's prompt separately before drafting its response.

For each advisor:

1. Read its prompt from `agents/<name>.md`.
2. If the advisor receives context (all except the Outsider) and `--context` is active: inject the hook content as a "## Additional context" section at the start of the advisor's prompt.
3. Pass it the user's question.
4. Get its response (in the structured form its own prompt defines).

The 5 advisors are:

- **Strategist** (`agents/strategist.md`) — Reframes the problem, identifies the real "job to be done".
- **Adversary** (`agents/adversary.md`) — Hunts for killer assumptions and failure modes.
- **Outsider** (`agents/outsider.md`) — Context-blind. Sees the question as a stranger and brings lateral perspective.
- **Operator** (`agents/operator.md`) — Grounds the decision in the next actionable step.
- **Futurist** (`agents/futurist.md`) — Projects out to 6, 18, 60 months. Identifies trajectories.

### Step 3 — Stage 2: Cross-review (optional, currently a stub)

If `--deep` is active: **for now**, do not run a real cross-review. Just add a note to the Chairman's output:

> *Stage 2 (cross-review) is marked as a stub in this version of the Council. When implemented, each advisor will receive the anonymized responses of the other 4 and identify the strongest insight, the weakest one, and refine its own response.*

(When implemented, read `protocols/deep.md`.)

### Step 4 — Convene the Chairman

Read `chairman.md`. Pass it:

1. The user's original question.
2. The 5 advisor responses.
3. (If Stage 2 were active) the reviews. For now, just the 5 responses.

The Chairman produces the final structured output (see `chairman.md` for the exact format).

### Step 5 — Present to the user

Structure of the output to the user:

```
# Council Verdict

[Chairman output — verdict, reason, next step, killer assumption, dissents]

---

<details>
<summary>See the individual responses from the 5 advisors</summary>

## Strategist
[response]

## Adversary
[response]

## Outsider
[response]

## Operator
[response]

## Futurist
[response]

</details>
```

In claude.ai, where `<details>` may not collapse, present the individual responses after the Chairman's verdict with clear headings. **The important thing is that the Chairman's verdict comes first and on top** — that is the actionable information.

---

## Design: why the Outsider is context-blind

By design, the Outsider **never receives the injected context hooks**, even if the user enables `--context`. Its value is seeing the question as a stranger who knows nothing about the business. If it knew the context, it would be redundant with the other 4 advisors. This is deliberate, not a bug.

---

## Context hooks

Hooks live in `contexts/<name>.md`. Each one is a dense summary (300-500 words max) of a domain (business, project, person) that Claude can inject into 4 of the 5 advisors when the user enables `--context <name>`.

**This is the part you customize.** The framework ships no real business hooks — that would be your private information. To use context:

1. Create a file in `contexts/<your-name>.md` (e.g. `contexts/mycompany.md`).
2. Invoke with `--context your-name`.

Included in this version:

- `contexts/example.md` — a sanitized sample hook (fictional company) that illustrates the format. Copy and adapt it, or delete it.

For the rules on writing a hook, see `contexts/README.md`.

---

## Notes for Claude (operational)

1. **Do not improvise the advisors.** Follow the output format that each `agents/*.md` defines. If the Strategist's prompt says "respond in 3 sections: Reframing / Core insight / Typical trap", then the Strategist responds exactly that way.

2. **Maintain context isolation.** Before drafting advisor N's response, do not read responses N-1, N-2, etc. Each advisor responds as if it were the only one responding. (This is what kills sycophancy.)

3. **The Chairman does see everything.** Its job is precisely to synthesize the 5 responses and take a stance.

4. **Do not expand the question.** If the user asks a short question, do not "pad" it before passing it to the advisors. The advisors work with the question as-is.

5. **Language detection:** look at the user's prompt, not the file names. The advisor prompts are written in English but must respond in the user's language.

6. **If the user asks a question without an explicit trigger but asks for "advice"**, assume they want the Council and proceed.

7. **Do not add advisors or change the count.** The Council is 5 + Chairman. Period.
