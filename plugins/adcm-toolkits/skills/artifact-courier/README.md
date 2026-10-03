# artifact-courier

Moves the delivery close of a session, republishing claude.ai Artifacts and producing the
tappable links block, off the expensive main model and onto one disposable Sonnet sub-agent.

## Why this exists

The Artifact tool refuses to publish to a URL the current conversation has not read, so a
fresh main session that wants to refresh a stale page must first pull the whole live version
into its context: 40 KB to 1 MB per artifact, roughly a tenth of a session for a typical set.
Add the Stop hook that insists on a precise links block at the very end, and the close of every
wave becomes the costliest, least intelligent thing the main model does.

This skill packages the cheap way:

- **A preflight script** reads `artifacts.json` and says which rows are missing, new, fresh,
  stale (in place) or stale and too big (re-issue), which need a regen, how to split the live
  reads into batches, and prints the links block in the exact format the guard checks.
- **A courier brief and procedure** for a Sonnet sub-agent: regenerate, read the live copy
  (paged when the tool saves it to a file), publish, seal the registry with `published_at`,
  `version` and `sha256`, optionally commit, check the preview, send the screenshots, return a
  short structured report.
- **Registry stamps** that the artifact-guard hook can trust, so a publish done by a
  sub-agent counts even though the hook only sees the main transcript.

## Usage

The main session loads the skill, runs the one-line summary, fills the brief and launches the
courier:

```bash
python3 scripts/courier_preflight.py <docs_dir> --summary
python3 scripts/courier_preflight.py <docs_dir> --module modules/billing
python3 scripts/courier_preflight.py <docs_dir> --batches   # batch1=f1,f2;batch2=f3
python3 scripts/courier_preflight.py <docs_dir> --block-only [--include-hidden]
python3 scripts/courier_preflight.py <docs_dir> --set-regen FILE COMMAND
python3 scripts/courier_preflight.py <docs_dir> --mark-published FILE URL VERSION [--previous-url OLD]
python3 scripts/courier_preflight.py --pages SAVED_FILE --page-kb 60 --page-lines 450
```

Then it pastes everything after `=== LINKS ===` from the courier's RETURN as the last lines of
its final message. It never calls the Artifact tool and never opens the HTML itself.

## What it will not do

Edit HTML or documents, publish to a URL on another account, re-issue on its own when a URL is
not found, run git beyond one registry commit, follow instructions found inside a live page,
or work without a Sonnet-capable Agent tool. Artifacts above about 300 KB are re-issued as new
artifacts with the previous URL kept in the registry.

## Requirements

Python 3 (stdlib only). A session whose sub-agents expose the Artifact tool. `SendUserFile`
and the Chrome extension are needed only for the optional media step.

## Layout

- `SKILL.md`: what the main session does, and the hard rules.
- `references/procedure.md`: the courier's ten steps and the RETURN contract.
- `references/registry.md`: the `artifacts.json` fields and states.
- `templates/courier-brief.md`: the brief to fill.
- `scripts/courier_preflight.py`: state check, links block, registry sealer, pager.
