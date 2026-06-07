# council

A multi-advisor deliberation framework for Claude Code. It convenes five specialized advisors — **Strategist, Adversary, Outsider, Operator, Futurist** — plus a **Chairman** who synthesizes their input into a single, actionable verdict. The framework is generic: you bring the decision (and, optionally, your own context).

## Install

This skill ships in the **`adcm-toolkits`** plugin of the public **`adcm`** marketplace:

```
/plugin marketplace add angel-carvajal/adcm
/plugin install adcm-toolkits@adcm
```

> Marketplace state is per profile (`CLAUDE_CONFIG_DIR`), so run this once per profile.

## Use

- **Auto-invocation:** ask for multi-perspective analysis of a decision, a pre-mortem, or a hard trade-off and Claude convenes the council from this skill's description.
- **Explicit:** `/adcm-toolkits:council`
- **Triggers:** `ask the council: <question>`, `council: <question>`, `convene the council`, `consult the council`, …
- **Flags:**
  - `--context <hook>` — inject your own domain context into 4 of the 5 advisors (the Outsider stays context-blind by design).
  - `--deep` — Stage 2 cross-review among advisors (currently a stub).

## Bring your own context

Drop a markdown file in `contexts/<name>.md` (see `contexts/example.md` for the format) and run with `--context <name>`. The Outsider never receives context — that is intentional.

## Structure

- `SKILL.md` — entry point / orchestration.
- `agents/*.md` — the five advisor prompts.
- `chairman.md` — synthesis prompt.
- `protocols/{standard,deep}.md` — execution protocols.
- `contexts/` — your context hooks (`README.md` + `example.md` included).

## Requirements

None — markdown-only, read by Claude. Works in Claude Code, Cowork, and claude.ai. MIT licensed.

---
Inspired by [Andrej Karpathy's LLM Council](https://github.com/karpathy/llm-council) and [Oli Limán's Claude Council](https://www.linkedin.com/in/olilo/).
