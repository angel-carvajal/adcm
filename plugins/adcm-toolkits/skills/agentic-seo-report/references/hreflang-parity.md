# Bilingual audit — reciprocity, parity, translation quality

*Approach adapted from `claude-seo` (MIT) `skills/seo-hreflang/`; re-verified and narrowed.*

Three failures, in increasing order of subtlety.

## 1 · Reciprocity (automated — `hreflang:<path>`)

Every language version must declare the **complete** alternate set, **including itself**, and
each alternate must link back. Google discards one-way hreflang entirely — silently. A site can
have perfect-looking tags on the English pages and get zero benefit because the Spanish ones
do not point back.

```bash
curl -s <url>     | grep -o 'hreflang="[^"]*"'
curl -s <alt-url> | grep -o 'href="[^"]*"'   # must contain the original
```

Also verify: `x-default` present and pointing at the language-agnostic entry point; `canonical`
on each version pointing at **itself**, never at the other language. A canonical that crosses
languages tells Google the other version does not deserve indexing.

## 2 · Content parity (semi-automated)

Reciprocal tags on pages that say different things is worse than no tags: the user lands on a
page that does not deliver what the snippet promised.

Compare per URL pair: visible text length (a >30% gap is a flag, not a verdict), headings
count and order, presence of the primary CTA, structured data types, and whether both carry
the same offering. **The Spanish page missing the contact form is the classic one.**

## 3 · Machine-translation quality (manual, sampled)

Fluent output hides the failures that cost conversions:

- **Untranslated UI strings** stranded in the source language mid-page.
- **Brand and product names wrongly translated** — the model helpfully localises a name that
  should never change.
- **Local conventions**: phone format, address order, currency, date, units. A US phone number
  formatted for another market reads as a wrong number.
- **Search intent drift**: the literal translation of a keyword is often not what that market
  actually types. Verify against real query data before optimising for a translated phrase.
- **Legal and compliance copy** translated loosely. Have a human read it.

Sample 3-5 pairs per run. Full manual review of a whole site is not a check, it is a project —
and pretending it fits in an automated report is how audits become theatre.
