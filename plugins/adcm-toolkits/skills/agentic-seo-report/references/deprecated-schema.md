# Retired and restricted Schema.org types

Emitting these is not an error — the markup is still valid and non-Google consumers may still
read it. But it no longer earns enhanced display in Google, and it adds payload that an agent
has to parse. Audit them, don't panic about them.

*Idea and starting list adapted from `claude-seo` (MIT) `skills/seo-schema/references/`;
re-verified before use. Verify against Google's structured data docs before acting — this list
ages.*

| Type | Status | What it means now |
|---|---|---|
| `HowTo` | Rich result **removed** (Aug 2023) | No enhanced display. Keep only if a non-Google consumer uses it. |
| `FAQPage` | **Restricted** (Aug 2023) | Rich results limited to authoritative government and health sites. On a commercial site it renders as nothing. |
| `Sitelinks Searchbox` | **Removed** (Nov 2024) | Google generates sitelinks on its own; the markup is inert. |
| `Book` / Book Actions | **Limited** | Only for approved partners. |
| `Course` | **List format only** | The standalone Course rich result was withdrawn. |
| `VehicleListing` | **Limited availability** | Not a general-purpose rich result. |

## What to recommend instead

- Retired type on a page whose content is genuinely useful ⇒ **keep the content, drop or
  demote the markup**. The answer still gets quoted by AI engines, which do not depend on
  Google's rich-result program.
- For a local service business, the types that still earn display are `LocalBusiness` (with
  complete NAP, `geo`, `openingHoursSpecification`), `Organization`, `WebSite`,
  `BreadcrumbList`, `Product`/`Offer` (**see guardrail 1 on pricing**), `Service`, and
  `AggregateRating` **only when backed by real, verifiable reviews**.
- Never add `AggregateRating` without genuine reviews behind it. That is a manual-action risk,
  not a growth tactic.
