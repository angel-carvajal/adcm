# artifact-courier

Moves the delivery close of a session, republishing claude.ai Artifacts and producing the
tappable links block, off the expensive main model and onto one disposable agent, `adcm-toolkits:courier` (Sonnet).

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
- **A courier brief and procedure** for the `adcm-toolkits:courier` agent (Sonnet): regenerate, read the live copy
  (paged when the tool saves it to a file), publish, seal the registry with `published_at`,
  `version` and `sha256`, optionally commit, check the preview, return the screenshot paths (the main session sends them), return a
  short structured report.
- **Registry stamps** that the artifact-guard hook can trust, so a publish done by a
  sub-agent counts even though the hook only sees the main transcript.

## Usage

The main session loads the skill, runs the one-line summary, fills the brief and launches the
courier. `courier-preflight` is the plugin's `bin/` launcher (on the Bash PATH while the plugin is enabled; run it bare, with no `cd … &&` or env assignment before it, so one `Bash(courier-preflight *)` allow rule matches):

```bash
courier-preflight <docs_dir> --summary
courier-preflight <docs_dir> --module modules/billing
courier-preflight <docs_dir> --batches   # batch1=f1,f2;batch2=f3
courier-preflight <docs_dir> --block-only --account auto|NAME [--include-hidden]   # the links of the session's account
courier-preflight <docs_dir> --set-regen FILE COMMAND
courier-preflight <docs_dir> --mark-published FILE URL VERSION [--previous-url OLD] [--account NAME]
courier-preflight <docs_dir> --account auto|NAME   # auto = last_session_account, else active_account; NAME: work on url_NAME; --set-active-account NAME makes url_NAME the canonical url (the old url moves to url_<old account>)
courier-preflight --pages SAVED_FILE --page-kb 60 --page-lines 450
```

Then it pastes everything after `=== LINKS ===` from the courier's RETURN as the last lines of
its final message. It never calls the Artifact tool and never opens the HTML itself.

## What it will do

Probe which claude.ai account the session is logged into (brief `ACCOUNT: auto`, the default: read the first row's URL,
fall back to its other `url_<x>` families), use that account for every command, print the links of THAT account as the close,
seal `last_session_account`, and report a changed account or URL under `URL CHANGES` without failing the close.

## What it will not do

Edit HTML or documents, publish to a URL on another account, present a canonical URL the session cannot open as the session's link (it is printed with a warning and reported as `not opened by this account`),
guess the account from the main session, re-issue on another account without
`REISSUE ON OTHER ACCOUNT: yes` (it retries with `url_<account>` or reports `blocked`), run git beyond one registry commit, follow instructions found inside a live page,
or work without a Sonnet-capable Agent tool. Artifacts above about 600 KB are re-issued as new
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
