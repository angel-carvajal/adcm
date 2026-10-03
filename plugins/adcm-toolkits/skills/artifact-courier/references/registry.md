# artifacts.json: what the courier reads and stamps

The registry lives at `<docs_dir>/artifacts.json` (usually `ai/ai-brain/artifacts.json`).
All paths are relative to `<docs_dir>`. The preflight accepts the folder or the file.

## Top level

| Field | Meaning |
|---|---|
| `close_markers` | Docs whose change means "closing" a module (default `task.md`, `execute.md`, `detailed-plan.md`). The guard and `--module` use them to find each row's module root. |
| `active_account` | Which claude.ai account the `url` field belongs to (a localized alias, `cuenta_activa`, is read too). Informational. |
| `artifacts` | The rows below. Unknown top-level and row fields are preserved untouched. |

## Row fields that already existed

| Field | Meaning |
|---|---|
| `file` | Path of the HTML. Exact match key for every write. |
| `url` | Canonical URL on the ACTIVE account. The courier only ever uses this one. |
| `title`, `favicon` | Text and emoji of the link in the close block. |
| `in_close_block` | `false` keeps the row out of the block (default `true`). |
| `regen` | Command that regenerates the HTML from its sources, run from `<docs_dir>`. A first token ending in `.py` gets a `python3` prefix. |
| `files` | Supporting files published beside the page (the Artifact tool's `files` map). |
| `previous_url`, `reissued` | Set by a re-issue: the old URL and a dated note. |
| `url_<account>` | URL on another account. Never used for publishing; the preflight lists them as "not used". |

## Row fields owned by the courier

| Field | Written by `--mark-published` |
|---|---|
| `published_at` | UTC time with milliseconds, ending in `Z`. |
| `version` | Version string the Artifact tool reported (`unknown` if none). |
| `sha256` | Hash of the file as published. |
| `published_bytes` | Size in bytes of the file as published (drives the live-read estimate). |

If the row already has a `published` field it is refreshed too; otherwise it is not created.
When the new URL differs from the row's current `url`, the old one is recorded as
`previous_url` (plus a dated `reissued` note) automatically. An explicit `--previous-url` must
equal the row's current `url`, otherwise the call exits 2 and the message names the real old
URL. `--set-regen FILE COMMAND` (its own mode) writes the row's `regen`. New keys are appended after the existing
ones; key order, indent and non-ASCII text are preserved. Writes take an exclusive
`flock` on `<docs_dir>/.artifacts.json.lock` and replace the registry atomically. The lock file
is transient: it is removed after every write (also a failed one), never committed, never
`git add`-ed by the courier, and belongs in `.gitignore`. A leftover one is harmless.

Unknown row and top-level keys (`$doc`, `what`, `note`, ...) are preserved and never an error.

Optional `sources`: list of paths (relative to `<docs_dir>`) the HTML is rendered from. Without
it, a row named `prompts.html` uses `execute.md` and `task.md` beside it (plus `prompts-titles.json` when present), and a row named `plans.html`
uses `task.md` and the four plan documents found beside it, in either language set: `propuesta-ejecutiva` / `executive-proposal`, `plan-maestro` /
`master-plan`, `plan-detallado` / `detailed-plan`, `plan-timeframe` / `timeframe-plan`.

## States

| State | Rule |
|---|---|
| `missing` | The file does not exist. |
| `new` | The row has no `url`. |
| `fresh` | `sha256` equals the file's hash, or `published_at` is not older than the file's mtime — and no source is newer than the HTML. |
| `regen-due` | Would be fresh, but a source is newer than the HTML. With `regen`: the courier runs it, then publishes by size; without: REGEN reads `needs-regen`. |
| `stale-reissue>300KB` | Not fresh and `max(size, published_bytes)` is above `--threshold-kb`. |
| `stale-inplace` | Any other not-fresh row. A row with no seal is stale; the first run seals it. |

REGEN column: `regen: <cmd>` when the row has `regen`; `regen (due): <cmd>` when it has `regen` and
a source is newer than the HTML (state `regen-due`: the courier runs step 2, then publishes by
size); `needs-regen: <cmd>` when it has none and a source is newer than the
HTML (for `plans.html` the template `python3 <gen> --brain <dir of file> <file> [--init]`, with
`--init` only when the file is missing and never over an existing HTML that has its own layout:
that row gets the project's own builder as `regen`; for `prompts.html` `blocked: needs wave ids`,
which the main session resolves with `--set-regen`); `-` otherwise. A stored `plans.html` regen
carries no `--init`; a first `prompts.html` regen does (a no-op once the file exists).

Batches: `--batches` prints `batch1=f1,f2;batch2=...`. A row costs live + local bytes in place,
local bytes when re-issued or new; the budget is `--batch-kb` (default 400). Every non-fresh
row is in exactly one batch; re-issue, new, regen-due, needs-regen and creatable missing rows are in batch 1.

## Contract with the artifact-guard

The Stop hook treats a row as fresh when the main transcript shows a publish after the last
change, or `published_at` is not older than the mtime, or `sha256` matches. That is why the
courier seals every row right after its publish and why a regeneration that produces
identical bytes costs nothing. The courier's link block is the format the guard checks.

## Example (neutral)

```json
{
  "active_account": "primary",
  "close_markers": ["task.md", "execute.md", "detailed-plan.md"],
  "artifacts": [
    {
      "file": "modules/billing/plans.html",
      "url": "https://claude.ai/artifact/EXAMPLEID1",
      "title": "Billing · Plans",
      "favicon": "📘",
      "regen": "scripts/plans-regen.py --brain modules/billing modules/billing/plans.html",
      "url_secondary": "https://claude.ai/artifact/EXAMPLEID2",
      "published_at": "2026-01-15T10:20:30.123Z",
      "version": "v4",
      "sha256": "<64 hex chars>",
      "published_bytes": 184320
    }
  ]
}
```

Documentation links in a registry row or block use `example.com`-style placeholders in
examples only; real rows hold the real claude.ai URLs.
