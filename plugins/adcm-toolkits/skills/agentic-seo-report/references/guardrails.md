# Guardrails — read this before writing a single recommendation

Standard SEO advice is written for businesses with nothing to hide. Applied blindly to a
manufacturer, a clinic, or anyone with confidential pricing, the same advice becomes a leak.
This file is why the skill exists as its own thing instead of a wrapper over someone else's.

## 1 · Never publish a value the project marked confidential

The classic advice is *"add `Product` + `Offer` schema with the price — it wins rich results."*
For a business whose pricing is internal, that single line publishes the thing it protects, in
a machine-readable format, on a page designed to be scraped.

**Instead:** propose `Offer` with `priceRange` (`"$$$"`) or `priceSpecification` expressing a
**band**, never the exact figure. The public band is usually already on the site — reuse it.
The same applies to costs, margins, supplier names, and part references.

**How to tell:** read the project rules file. `forbidden_terms` lists what must never appear —
in the site, and in this report. If no rules file is supplied, **say so in the report header**
and treat every price-adjacent recommendation as unverified.

## 2 · Never recommend "process disclosure" without checking

E-E-A-T guidance pushes toward *"show how it's made, where, by whom"*. That is exactly the
content some businesses cannot publish — manufacturing location, subcontractors, workflow.

**Instead:** propose experience signals that carry no confidential payload — years operating,
units delivered, warranty terms, certifications, named service area, real customer outcomes.
These satisfy the same intent without naming what the rules protect.

## 3 · Never send site content to a third party

The audited site may be confidential in ways this skill cannot see. So:

- `is-agentic.com` receives **a public URL and nothing else** — it fetches the site itself.
- **No** crawl-as-a-service (Firecrawl and similar pipe your HTML through their servers).
- **No** keyword or backlink APIs that ingest page content.
- All fetching is direct, from this machine to the site being audited.

If a check cannot be done without shipping content somewhere, **the check does not get done**,
and the report says so under *Not verified*.

## 4 · Be honest about heuristics

- Do **not** invent a composite "SEO Health Score" and present it as a Google signal. If a
  score is a heuristic, label it. Report is-agentic's score as **theirs**, unmodified.
- Google has stated that **word count** and **readability scores** are not direct ranking
  factors. Do not imply otherwise, even as a shortcut.
- Markup earns *eligibility* for rich results, never a guarantee. Say "eligible for", not
  "will get".
- **Ranking is not promised by anything in this report.** The report measures the site; it
  does not measure the market or the competition.

## 5 · Declare what you could not verify

Every report ends with *Not verified*. A gap you name is worth more than a green you assumed.
If a page timed out, if a check needs credentials, if the is-agentic score is three weeks old —
that goes in the report, at full strength, not in a footnote.

## 6 · The report must survive its own guardrail

`render_report.py` scans the **finished report** against `forbidden_terms` and **refuses to
write it** if a confidential term appears — including inside a recommendation the skill itself
generated. A tool that promises to protect a secret and then prints it in its own output is
worse than one that never promised.
