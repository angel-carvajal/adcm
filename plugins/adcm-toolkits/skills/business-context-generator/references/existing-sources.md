# Mining Existing Sources

Protocol for STEP 1b: when the venture already has artifacts, the facts are
extracted from them and the interview is spent on judgements. Read on-demand.

## 1. Source families

A **family** is one disjoint tree of artifacts with one audience and one authority
level. One miner per family; never two miners over the same path.

| # | Family | Typically contains | Default class | Model |
|---|---|---|---|---|
| **F0** | Website (STEP 1) | public copy, offering, claims, tone | public | — (WebFetch) |
| **F1** | Sales & marketing collateral | decks, presentations, one-pagers, catalogs sent to partners | **partner** | `sonnet` |
| **F2** | Data layer | migrations, seeds, catalog + price tables, cost spreadsheets | **CONFIDENTIAL** | `opus` |
| **F3** | Commercial tooling | quoting tools, calculators, pricing RPCs, price scripts — the commercial **RULES** | **CONFIDENTIAL** | `opus` |
| **F4** | Prior execution docs (this or a sibling venture) | `plan-detallado.md` §waves, `execute.md` §7, `task.md` logbook — decisions **and why**, constraints, hard rules | internal | `opus` |
| **F5** | Brand assets | CSS tokens, logos, fonts, color/typography files | public | `sonnet` |
| **F6** | Memory & prior skills | `CLAUDE.md`, memory files, installed `business-init-*` / `code-project-context-*` | internal | `opus` |

**Authority order** (used to resolve conflicts, highest first):
prod DB (F2) > product code (F3) > execution docs (F4) > collateral (F1) >
memory (F6) > website (F0). F5 is authoritative only for brand tokens.

Families must be **DISJOINT**. If a repo holds both migrations and the quoting
module, split by path (F2 = `supabase/migrations/**`, F3 = `src/lib/quote/**`) and
say so in each brief.

## 2. Miner brief

≤25 lines, written by the orchestrator, one per family:

- **FAMILY** — F# + its one-line mission ("prove what the catalog and its prices
  actually are").
- **PATHS** — exact roots/globs, **read-only**. For huge files use `grep`/`sed` to
  pull the relevant sections; never read a whole multi-MB file.
- **EXTRACT** — the topics to look for, each mapped to its target reference file
  (`offering.md`, `sales.md`, `brand.md`, `INTERNAL.md`, …).
- **SCHEMA** — the row schema of §3, verbatim.
- **CLASS DEFAULT** — the family's default class, and that it may only be
  *proposed*, never decided.
- **STOP IF** — a path is missing · the class is ambiguous · two sources inside
  the family contradict each other · a source carries no date.
- **FORBIDDEN** — network access · any write · interviewing the user · inventing a
  value · reading outside `PATHS` · summarizing prose instead of extracting facts.
- **RETURN** — the rows · the UNKNOWN list · `exhausted: yes|no` · the 3 files it
  would read next if allowed.

`exhausted: no` plus those 3 files is how a family asks for a second pass: the
orchestrator decides whether to widen the PATHS via `SendMessage` (cost 0) or to
send the gap to the interview as an UNKNOWN. Shape:

```
FAMILY   F3 — the commercial rules: what is charged, on what, and under what conditions
PATHS    src/lib/quote/**  ·  scripts/prices/*.ts   (read-only; grep sections, never whole dumps)
EXTRACT  price formula + units → INTERNAL.md · discount/minimum rules → sales.md · what is
         NOT quotable → offering.md
SCHEMA   <the row schema of §3>
CLASS    CONFIDENTIAL by default — propose, never decide
STOP IF  a path is missing · the class is ambiguous · two files disagree · a source is undated
FORBIDDEN  network · any write · interviewing the user · inventing a value · reading outside
         PATHS · summarizing prose instead of extracting facts
RETURN   rows · UNKNOWN list · exhausted: yes|no · the 3 files you would read next
```

## 3. Fact-sheet row schema

```
| # | fact | value | topic → file | source (path#anchor) | as-of | confidence | class |
```

- **confidence** — `verbatim` (the source says exactly this) · `derived` (computed
  from the source; the formula goes in the value cell) · `inferred` (a judgement,
  must be confirmed by the owner).
- **class** — `public` · `partner` · `internal` · `CONFIDENTIAL`.
- **as-of** — the **source's own** date (commit, file header, deck date), never
  today's date.

## 4. Consolidation — the orchestrator, never delegated

1. **Dedupe** identical facts across families; keep the highest-authority source.
2. **Conflicts** resolve by the authority order of §1; at the same level, newer
   beats older. The loser is kept in the sheet as `superseded by #N` — a
   contradiction is itself a finding worth showing the owner.
3. **Class**: on disagreement the **strictest class wins**.
4. **Emit the UNKNOWN list** — it *is* the interview agenda for STEP 2.
5. **ONE refuter pass** (`adcm-toolkits:auditor` + `model: opus`) over the consolidated sheet, if budget allows:
   *"what here is stale, invented or misclassified?"* — it sees the sheet, not the
   sources, and returns findings only.

## 5. Budget

Maximum 20 delegated agents; a typical run spends **4–8**: ≤6 miners + 1 refuter.
Miners are `adcm-toolkits:researcher` calls with the tier of §1 as their explicit `model`; the refuter is an `adcm-toolkits:auditor`. When presenting the sheet, report
`agents used: n/20 (opus a · sonnet b)`.

## 6. Ultracode shape

The fan-out is ONE workflow; the interview NEVER runs inside an agent.

```js
const BUDGET = 20
let used = 0, opus = 0, sonnet = 0
const spend = (model, prompt, opts) => {
  if (used >= BUDGET) throw new Error('agent budget exhausted — ask the user')
  used++; model === 'opus' ? opus++ : sonnet++
  return agent(prompt, {...opts, model, agentType: opts.agentType ?? 'adcm-toolkits:researcher'})
}
// ≤6 miners, one per DISJOINT family; FAMILIES[i].model is fixed by the table in §1
const mined = await parallel(FAMILIES.map(f => () =>
  spend(f.model, minerBrief(f), {label: f.key, phase: 'Mine', schema: ROW})))
const sheet = consolidate(mined)                    // plain code, no agent — §4
const refuted = await spend('opus', refutePrompt(sheet), {phase: 'Refute', agentType: 'adcm-toolkits:auditor'})
log(`agents used: ${used}/${BUDGET} (opus ${opus} · sonnet ${sonnet})`)
return { sheet, refuted, unknowns: sheet.filter(r => r.value === 'UNKNOWN') }
// The interview (AskUserQuestion, STEP 2) runs in the main session, after this.
```

## 7. Worked example

A venture whose artifacts live inside a sibling venture's brain:

| Family | Paths | Model |
|---|---|---|
| F1 | `…/ai-brain/design/<slug>/*.html` (the decks) | `sonnet` |
| F2 | the tenant's migrations | `opus` |
| F3 | the quoting module + the price scripts | `opus` |
| F4 | `plan-detallado.md` §Wave `<X>`-1..4 · `execute.md §7` | `opus` |
| F5 | `<slug>.css` (brand tokens) | `sonnet` |
| F6 | memory files + installed sibling skills | `opus` |

Six miners + one refuter = **7/20**. The sheet comes back with the catalog, the
prices (CONFIDENTIAL), the commercial rules, the decisions and their why, and the
brand tokens. The interview then asks only for the hard rules, what may be said
publicly, the tone, and the owner's goals.
