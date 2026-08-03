# business-context-generator

Interviews a business owner, researches the business website, and generates an installable, **lazy-loading** business-context skill of the form `business-init-[business-slug]` — so Claude can carry full context of a business (identity, offering, market, brand voice, sales, operations, objectives, and a confidential internal file) into any future session without loading everything at once.

## Install

This skill ships in the **`adcm-toolkits`** plugin of the public **`adcm`** marketplace:

```
/plugin marketplace add angel-carvajal/adcm
/plugin install adcm-toolkits@adcm
```

> Marketplace state is per profile (`CLAUDE_CONFIG_DIR`), so run this once per profile.

## Use

- **Auto-invocation:** ask to "create business context", "register a business", "I want you to know my business", "I have another business", etc. (English or Spanish).
- **Explicit:** `/adcm-toolkits:business-context-generator`
- It researches the business website first (WebFetch), then runs an 8-round interview (AskUserQuestion) in **Express** (~20 min) or **Full** (~45–60 min) mode, and renders the generated skill from `templates/`.

## What the generated context contains

The generated `business-init-*` skill is a lazy-loaded knowledge base: a short SKILL.md index (30-second summary, contact identity, the owner's **hard rules**, and a task→file map) plus per-topic `references/` files — `company`, `offering`, `market`, `brand`, `sales`, `operations`, `objectives`, and `INTERNAL.md` for everything confidential (real prices, margins, framing secrets, named clients). Unanswered items are recorded as `[TO BE DEFINED]` so the skill knows what it's missing, and re-running the generator on an existing skill refreshes it incrementally (update mode).

## Structure

- `SKILL.md` — the generation workflow (research → interview → generate → review → deliver).
- `references/` — the interview guide (8 rounds), the website research protocol, and the delivery guide (private plugin marketplace or standalone `.skill` zip).
- `templates/` — templates for the generated skill (`SKILL.md.tmpl` + one per reference file).

## Requirements

None — markdown-only. Uses AskUserQuestion and WebFetch when available; degrades to a plain interview without them. MIT licensed.
