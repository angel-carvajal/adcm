# Website Research Protocol

Run this at STEP 1, **before asking the owner anything**, whenever the business has
a website. The goal is to walk into the interview already informed, so questions
become confirmations. This file is read on-demand.

## What to fetch (in order of value)

Use WebFetch on whichever of these exist; skip silently what doesn't:

1. **Home page** — identity, value proposition, main offering, calls to action,
   contact info.
2. **About / Our story** — history, mission, team, years in business, stage.
3. **Products / Services** (and pricing page if public) — catalog, variants,
   tiers, specs, published prices or "request a quote" signals.
4. **FAQ / help pages** — the questions leads actually ask and the answers the
   business currently endorses.
5. **Gallery / Portfolio / Case studies** — track record, notable work, client
   names that are already public.
6. **Contact / Locations** — addresses, service area, hours, phone/email/social
   links.
7. **Public social profiles** linked from the site — activity level, content
   pillars, tone.

## What to extract from each fetch

- **Facts** for pre-filling: brand name, legal entity (often in the footer),
  locations, hours, offerings, published prices, portfolio items.
- **Tone of the copy**: formal vs casual, language(s) used, how they talk about
  themselves. Present this in R5 as an inference to confirm ("your site sounds
  professional-but-warm and is written in English — should the brand voice match
  that?").
- **Boundary signals**: what the site conspicuously does *not* offer or say —
  useful candidates for the "what it does NOT do" question in R2.
- **Gaps**: what a customer cannot learn from the site (prices? service area?) —
  these become interview questions, and possibly improvement notes for the owner.

## Rules

1. **Confirm reliability first.** Ask the owner: *"Is the website up to date — can
   I treat it as a source of truth?"* Some sites are stale or placeholder; if the
   owner says so, mark website-derived data as unconfirmed and re-verify the
   important parts in the interview.
2. **Confirm, don't assume.** Everything scraped is a *draft answer*. Present it
   for confirmation in the corresponding round; never write it into the generated
   skill unconfirmed.
3. **Public ≠ publishable.** Even data found on the public site can be outdated or
   wrong; when the owner corrects it, the correction wins and may be worth a note
   ("site says X but actual policy is Y") — which usually belongs in
   `INTERNAL.md`.
4. **Degrade gracefully.** If WebFetch is unavailable, the site is down, or
   fetches fail after a couple of attempts: tell the user, skip this step, and run
   the interview without pre-fill. Never block the flow on the website.
