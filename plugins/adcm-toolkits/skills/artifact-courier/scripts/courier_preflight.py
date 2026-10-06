#!/usr/bin/env python3
"""courier_preflight -- read-only state check and registry sealer for the artifact courier.

Stdlib only. Reads an `artifacts.json` registry (see references/registry.md) and tells the
courier which rows need work:

  missing            the file does not exist on disk
  new                the row has no `url` yet (first publish, no `url` in the Artifact call)
  other-account      only with --account NAME (NAME is not the registry's active account): the row
                     has no `url_NAME`; it is never published on its own and stays out of batches
  fresh              `sha256` equals the file's hash, or `published_at` >= file mtime, and no
                     source document is newer than the file
  regen-due          would be fresh, but a source document is newer than the HTML: with `regen`
                     run it, then publish by size (in place or re-issue); without `regen` the
                     REGEN column says needs-regen. A stale row with newer sources keeps its
                     stale state (REGEN column "regen (due)" or "needs-regen")
  stale-reissue>NKB  not fresh and max(file size, published_bytes) is above the threshold
  stale-inplace      anything else that is not fresh (republish to the same url)

Batches (--batches, also in --summary): every non-fresh row lands in exactly one batch,
printed as "batch1=f1,f2;batch2=f3". A row costs live + local bytes when published in place,
local bytes when re-issued or new. Re-issue, new, regen-due and needs-regen rows go in batch 1.
(A missing row with neither `regen` nor any source document has nothing a courier can do: it
is only warned about.) --batch-kb (default 400) is the live + local byte budget per batch.

`--summary` is a one-line contract also read by status_digest.py.

Accounts: `url` and its stamps (`sha256`, `published_at`, `published_bytes`, `version`, `previous_url`,
`reissued`) belong to the registry's `active_account` (`cuenta_activa` is read too); a row may carry
the same family for another claude.ai account with the account name as suffix: `url_<account>`,
`sha256_<account>`, ... (the alias `url_cuenta_<account>`, likewise `cuenta_` on every key of the
family, is read when the plain key is absent; writes always use the plain suffix). `--account NAME`
with NAME different from the active account makes `url_NAME` the working url and the `_NAME` stamps
the freshness evidence of the table, --block-only, --batches, --summary and the state machine (a
missing `_NAME` stamp means stale, the canonical stamps are never used for it); rows without
`url_NAME` are `other-account` (listed in an `OTHER-ACCOUNT:` line, left out of the batches; a row
whose file is absent stays `missing`). With NAME equal to the active account, or without the flag,
nothing changes: `url` and its stamps are used.

`--account auto` resolves to the registry's top-level `last_session_account` (written by every
--mark-published: the --account NAME it ran with, else the active account) and, when that is absent, to
the active account; the default report header then prints `account: <resolved> (auto)`. `--block-only`
prints, per row, the url of the resolved account's family and falls back to the canonical `url` when the
family has none (a warning on stderr names those rows): the block the main session pastes is the
current account's. The default report no longer carries the link block (0.16.0): it ends with the
pointer line `links: N rows · use --block-only` (N = the rows the block would list, same account rule),
so a preflight run in the main session never prints the `=== LINKS ===` marker the Stop guard reads as
a delivery. The block is printed only by `--block-only`, whose output is unchanged.
`--summary` ends with ` · account: <resolved> (auto|named)` only when --account is passed (without the
flag the line is exactly the one status_digest.py has always read).

Usage
  courier_preflight.py <docs_dir|artifacts.json> [--module REL]... [--only F,F]
                       [--threshold-kb 600] [--batch-kb 400] [--page-kb 60] [--account NAME|auto]
                       [--summary | --batches | --block-only [--include-hidden]]
  courier_preflight.py <docs_dir> --mark-published FILE URL VERSION
                       [--previous-url OLD] [--reason TEXT] [--account NAME]
                       (--previous-url must equal the row's current url, exit 2 otherwise;
                        without it a changed url records the old one as previous_url;
                        with --account NAME other than the active account ONLY the `_NAME` family
                        is written: `url_NAME`, `sha256_NAME`, `published_at_NAME`,
                        `published_bytes_NAME`, `version_NAME` and, on a changed url,
                        `previous_url_NAME` and `reissued_NAME`; `url` and its stamps stay untouched;
                        the top-level `last_session_account` is set to NAME, or to the active account
                        when no --account is given and one is known)
  courier_preflight.py <docs_dir> --set-regen FILE COMMAND
  courier_preflight.py <docs_dir> --set-active-account NAME
                       (moves the registry to account NAME: on every row that has `url_NAME` the whole
                        family (url, previous_url, reissued, sha256, published_at, published_bytes,
                        version) goes `<key>_<old active>` <- `<key>`, `<key>` <- `<key>_NAME`, and
                        the `_NAME` keys (alias keys too) are removed (<old active> = the current
                        active account, `previous` when none is set); rows without `url_NAME` stay
                        untouched and are listed;
                        `active_account` (and `cuenta_activa` if present) = NAME; running it
                        again with the old account restores every `url`. A registry that declares
                        no active account and has no `url_NAME` family on any row is only
                        declared: `active_account: NAME` is written, nothing else changes. Exit 2
                        when NAME is already the active account)
  courier_preflight.py --pages SAVED_FILE [--page-kb 60] [--page-lines 450]

Reading never writes anything. Only --mark-published, --set-regen and --set-active-account write
the registry (exclusive flock on `.artifacts.json.lock`, atomic tmp+fsync+replace, key order, indent
and non-ASCII characters preserved; the transient lock file is always removed, also after die()).

`module_root()` and `fmt_link()` mirror the artifact-guard Stop hook on purpose (the hook must
stay self-contained, so the logic is duplicated, not imported).
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone

__version__ = "0.16.0"

REGISTRY_CANDIDATES = ("artifacts.json", "ai/ai-brain/artifacts.json", "ai-brain/artifacts.json")
DEFAULT_MARKERS = ("task.md", "execute.md", "detailed-plan.md")
KB = 1024
CLOCK_SKEW = 60  # seconds: a published_at further in the future than this is ignored (as in the guard)
LONG_LINE = 2000
ACCOUNT_KEYS = ("active_account", "cuenta_activa")
FAMILY = ("url", "previous_url", "reissued", "sha256", "published_at", "published_bytes", "version")  # per-account keys
# Default `sources` for plans.html rows: the four documents, Spanish or English file names.
DOC_SETS = (
    ("propuesta-ejecutiva", "executive-proposal"),
    ("plan-maestro", "master-plan"),
    ("plan-detallado", "detailed-plan"),
    ("plan-timeframe", "timeframe-plan"),
)


# --------------------------------------------------------------------------- guard mirrors

def real(path):
    return os.path.realpath(os.path.expanduser(path))


def iso_to_epoch(ts):
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def acct_get(a, base, acct=None):
    """A row's `base` field for account `acct`: the plain key for the active account (acct None), else
    `<base>_<acct>`, falling back to the Spanish alias `<base>_cuenta_<acct>` when the plain one is absent."""
    if not acct:
        return a.get(base)
    for k in (f"{base}_{acct}", f"{base}_cuenta_{acct}"):
        if k in a:
            return a[k]
    return None


def stamped_sha(a, acct=None):
    """Registry sha256 normalised like the guard: strip, lower, drop a "sha256:" prefix."""
    value = acct_get(a, "sha256", acct)
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if value.startswith("sha256:"):
        value = value[len("sha256:"):]
    return value or None


def normalize_markers(value):
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)) and value:
        return tuple(str(m) for m in value)
    return DEFAULT_MARKERS


def module_root(reg_dir, rel_file, markers):
    d = os.path.dirname(os.path.join(reg_dir, rel_file))
    while True:
        if any(os.path.exists(os.path.join(d, m)) for m in markers):
            return d
        if real(d) == real(reg_dir) or len(d) <= len(reg_dir):
            return reg_dir
        d = os.path.dirname(d)


def fmt_link(a):
    return f"[{a.get('favicon', '🔗')} {a.get('title') or a['file']}]({a['url']})"


# --------------------------------------------------------------------------- helpers

def die(msg, code=2):
    print(f"courier_preflight: {msg}", file=sys.stderr)
    sys.exit(code)


def find_registry(target):
    t = os.path.expanduser(target)
    if os.path.isfile(t):
        return os.path.abspath(t)
    if os.path.isdir(t):
        for rel in REGISTRY_CANDIDATES:
            p = os.path.join(t, rel)
            if os.path.isfile(p):
                return os.path.abspath(p)
    die(f"no artifacts.json found at or under {target}")


def load_registry(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        die(f"cannot read {path}: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("artifacts"), list):
        die(f"{path} has no `artifacts` list")
    return data


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_ts(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_stamp():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n.microsecond // 1000), n.strftime("%Y-%m-%d")


def active_account(data):
    return next((data[k] for k in ACCOUNT_KEYS if isinstance(data.get(k), str)), None)


def other_account(data, name):
    """NAME when it is an account other than the registry's active one, else None (the `url` field applies)."""
    if not name:
        return None
    active = active_account(data)
    return name if name.strip() != (active or "").strip() else None


def resolve_account(data, name):
    """(account, auto): `--account auto` becomes the registry's `last_session_account`, else the active
    account (None when neither is known); any other NAME is returned unchanged."""
    if name != "auto":
        return name, False
    last = data.get("last_session_account")
    if isinstance(last, str) and last.strip():
        return last.strip(), True
    return active_account(data), True


def link_url(r, acct):
    """URL a link-block line shows for a row: the working account's url; under another account
    (`acct`) a row without one falls back to its canonical `url`."""
    if r["url"] or not acct:
        return r["url"]
    canon = r["a"].get("url")
    return canon if isinstance(canon, str) and canon else None


def regen_cmd(a):
    r = a.get("regen")
    if isinstance(r, str) and r.strip().lower() == "none":  # hand-maintained HTML: never regenerate
        return ""
    if not isinstance(r, str) or not r.strip():
        return None
    r = r.strip()
    if r.split()[0].endswith(".py"):
        r = "python3 " + r
    return r


def row_sources(reg_dir, a):
    """Absolute paths of the documents this row is rendered from."""
    src = a.get("sources")
    if isinstance(src, list) and src:
        return [os.path.join(reg_dir, s) for s in src if isinstance(s, str) and s]
    if os.path.basename(a["file"]) == "plans.html":
        base = os.path.dirname(os.path.join(reg_dir, a["file"]))
        found = [p for p in [os.path.join(base, "task.md")] if os.path.isfile(p)]  # wave statuses come from task.md
        for names in DOC_SETS:
            for n in names:
                p = os.path.join(base, n + ".md")
                if os.path.isfile(p):
                    found.append(p)
                    break
        return found
    if os.path.basename(a["file"]) == "prompts.html":
        base = os.path.dirname(os.path.join(reg_dir, a["file"]))
        cands = [os.path.join(base, n) for n in ("execute.md", "task.md", "prompts-titles.json")]
        return [p for p in cands if os.path.isfile(p)]
    return []


def has_article(path):
    """True when an existing HTML file already has its own <article> layout."""
    try:
        with open(path, "rb") as fh:
            return b"<article" in fh.read().lower()
    except OSError:
        return False


def needs_regen_text(file_, abs_file=None):
    """What the courier does for a row that has no `regen` yet but whose sources are newer."""
    base = os.path.basename(file_)
    if base == "plans.html":
        if abs_file and os.path.isfile(abs_file):
            d = os.path.dirname(file_) or "."
            try:
                shell = b'id="doc-master"' in open(abs_file, "rb").read()
            except OSError:
                shell = False
            if shell:  # a plans-regen shell whose regen was never stored
                return (f"regen not stored -- set it with --set-regen {file_} "
                        f"'python3 scripts/plans-regen.py --brain {d} {file_}'")
            # Never --init over a page that has its own layout: the template would replace it.
            return ("existing HTML has its own layout -- set regen to the project's builder with "
                    f"--set-regen {file_} '<python3 path/to/your-builder.py>'")
        d = os.path.dirname(file_) or "."
        return f"python3 <gen> --brain {d} {file_} --init"
    if base == "prompts.html":
        return "blocked: needs wave ids"
    return "blocked: no generator known"


# --------------------------------------------------------------------------- analysis

def analyse(reg_dir, data, threshold_kb, account=None):
    markers = normalize_markers(data.get("close_markers"))
    acct = other_account(data, account)
    limit = threshold_kb * KB
    now = time.time()
    rows = []
    for a in data["artifacts"]:
        if not isinstance(a, dict) or not isinstance(a.get("file"), str) or not a["file"]:
            continue
        absf = os.path.join(reg_dir, a["file"])
        exists = os.path.isfile(absf)
        size = os.path.getsize(absf) if exists else 0
        mtime = os.path.getmtime(absf) if exists else None
        raw = acct_get(a, "url", acct)
        url = raw if isinstance(raw, str) and raw else None
        pb = acct_get(a, "published_bytes", acct)
        pb = pb if isinstance(pb, (int, float)) and not isinstance(pb, bool) else 0
        if not exists:
            state = "missing"
        elif acct and not url:
            state = "other-account"  # this row lives on the other account: not ours to publish
        elif not url:
            state = "new"
        else:
            sha = stamped_sha(a, acct)
            pub = iso_to_epoch(acct_get(a, "published_at", acct))
            if pub is not None and pub > now + CLOCK_SKEW:
                pub = None  # future stamp: not evidence of anything (mirrors the guard)
            if sha is not None and sha == file_sha256(absf):
                state = "fresh"
            elif pub is not None and pub >= mtime:
                state = "fresh"
            elif max(size, pb) > limit:
                state = "stale-reissue>%gKB" % threshold_kb
            else:
                state = "stale-inplace"
        regen = regen_cmd(a)
        src_newer = False
        for s in row_sources(reg_dir, a):
            try:
                if mtime is None or os.path.getmtime(s) > mtime:
                    src_newer = True
                    break
            except OSError:
                continue
        hand = str(a.get("regen", "")).strip().lower() == "none"  # hand-maintained: sources ignored
        foreign = state == "other-account"
        needs_regen = src_newer and not regen and not hand and not foreign
        regen_due = src_newer and bool(regen) and not foreign
        if src_newer and state == "fresh" and not hand:
            state = "regen-due"  # never "fresh": the page predates its sources (hand-maintained rows exempt)
        rows.append({
            "a": a, "file": a["file"], "abs": absf, "exists": exists, "size": size,
            "mtime": mtime, "url": url, "state": state, "regen": regen, "hand": hand,
            "needs_regen": needs_regen, "regen_due": regen_due,
            "live": pb if pb else size,
            "module": real(module_root(reg_dir, a["file"], markers)),
        })
    return rows


def long_lines(path):
    n = 0
    try:
        with open(path, "rb") as fh:
            for ln in fh:
                if len(ln) > LONG_LINE:
                    n += 1
    except OSError:
        pass
    return n


def row_cost(r):
    """Bytes a courier handles for this row: live + local in place, local otherwise."""
    if r["state"] == "stale-inplace":
        return r["live"] + r["size"]
    return r["size"]


def make_batches(rows, batch_kb):
    """Every non-fresh row lands in one batch (a missing row with neither `regen` nor a source
    is the only exception: nothing can create it). Re-issue, new, regen-due, needs-regen and
    missing rows go first, into batch 1; in-place rows then fill batch 1 up to the budget and
    spill into the following batches. A row above the budget gets a batch alone."""
    limit = batch_kb * KB
    todo = [r for r in rows if r["state"] not in ("fresh", "other-account") and
            not (r["state"] == "missing" and not r["regen"] and not r["needs_regen"])]
    forced = [r for r in todo if r["state"].startswith(("stale-reissue", "new")) or r["needs_regen"]
              or r["regen_due"] or r["state"] == "missing"]
    rest = [r for r in todo if r not in forced]
    batches, cur, tot = [], list(forced), sum(row_cost(r) for r in forced)
    for r in rest:
        c = row_cost(r)
        if cur and tot + c > limit:
            batches.append((cur, tot))
            cur, tot = [], 0
        cur.append(r)
        tot += c
    if cur:
        batches.append((cur, tot))
    return batches


def batches_text(batches):
    return ";".join(f"batch{i}=" + ",".join(r["file"] for r in grp) for i, (grp, _) in enumerate(batches, 1)) or "none"


def table(headers, body):
    widths = [len(h) for h in headers]
    for row in body:
        for i, c in enumerate(row):
            widths[i] = max(widths[i], len(c))
    out = [" | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    out.append("-+-".join("-" * w for w in widths))
    for row in body:
        out.append(" | ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    return out


def report(args):
    reg = find_registry(args.target)
    reg_dir = os.path.dirname(reg)
    data = load_registry(reg)
    account, auto = resolve_account(data, args.account)
    acct = other_account(data, account)
    rows = analyse(reg_dir, data, args.threshold_kb, account)

    # Link block: module filter only (mirrors the guard's per-module block).
    block_rows = rows
    if args.module:
        sel = set()
        for m in args.module:
            sel.add(real(os.path.join(reg_dir, "" if m in (".", "") else m)))
        block_rows = [r for r in rows if r["module"] in sel]
        if not block_rows:
            print(f"warn: --module {', '.join(args.module)} matches no row", file=sys.stderr)
    if args.only:
        names = {n.strip() for chunk in args.only for n in chunk.split(",") if n.strip()}
        known = {r["file"] for r in rows}
        for n in sorted(names - known):
            print(f"warn: --only {n} is not a row of the registry", file=sys.stderr)
        block_rows = [r for r in block_rows if r["file"] in names]
    work_rows = block_rows

    block = []
    missing_url = []  # rows with no usable url at all: left out of the block
    fallback = []  # --account NAME rows without url_NAME: listed with their canonical `url`
    for r in block_rows:
        if r["a"].get("in_close_block", True) is False:
            continue
        u = link_url(r, acct)
        if u:
            block.append("- " + fmt_link({**r["a"], "url": u}))
            if not r["url"]:
                fallback.append(r["file"])
        else:
            missing_url.append(r["file"])

    inplace = [r for r in work_rows if r["state"] == "stale-inplace"]
    batches = make_batches(work_rows, args.batch_kb)
    batch_total = sum(t for _, t in batches)
    counts = {}
    for r in work_rows:
        key = "stale-reissue" if r["state"].startswith("stale-reissue") else r["state"]
        counts[key] = counts.get(key, 0) + 1
    regen_n = sum(1 for r in work_rows if r["regen"])
    due = [r["file"] for r in work_rows if r["regen_due"]]
    need = [r["file"] for r in work_rows if r["needs_regen"]]
    foreign = [r["file"] for r in work_rows if r["state"] == "other-account"]

    def warn_fallback():
        for f in fallback:
            print(f"warn: {f} has no url_{acct}, listed with its canonical url (it may not open under {acct})", file=sys.stderr)

    if args.block_only:
        lines = block
        if args.include_hidden:
            lines = ["- " + fmt_link({**r["a"], "url": link_url(r, acct)}) for r in work_rows if link_url(r, acct)]
        print("\n".join(lines))
        warn_fallback()
        for f in missing_url:
            print(f"warn: {f} has no url_{acct}, left out of the block (other account)" if acct
                  else f"warn: {f} has no url, left out of the block", file=sys.stderr)
        return 0

    if args.batches:
        print(batches_text(batches))
        return 0

    if args.summary:
        parts = [f"{len(work_rows)} rows"]
        for k in ("fresh", "stale-inplace", "stale-reissue", "new", "missing"):
            if counts.get(k):
                parts.append(f"{k} {counts[k]}")
        if foreign:
            parts.append(f"other-account {len(foreign)}: {', '.join(foreign)}")
        if regen_n:
            parts.append(f"regen {regen_n}")
        if due:
            parts.append(f"regen-due {len(due)}: {', '.join(due)}")
        if need:
            parts.append(f"needs-regen {len(need)}: {', '.join(need)}")
        if batches:
            parts.append(f"batches {len(batches)}: {batches_text(batches)}")
        if work_rows and counts.get("fresh", 0) == len(work_rows) and not due and not need:
            parts.append("nothing to publish")
        if args.account:
            parts.append(f"account: {account or 'not set'} ({'auto' if auto else 'named'})")
        print("courier-preflight: " + " · ".join(parts))
        return 0

    active = active_account(data)
    ignored = sorted({k for r in rows for k in r["a"] if k.startswith("url_") and k not in (f"url_{acct}", f"url_cuenta_{acct}")})
    print(f"registry: {reg}")
    if auto:
        print(f"account: {account or 'not set'} (auto)")
    if acct:
        read = sorted({f"url_{acct}" if f"url_{acct}" in r["a"] else f"url_cuenta_{acct}" for r in rows if r["url"]},
                      key=lambda k: "cuenta_" in k) or [f"url_{acct}"]
        print(f"active account: {active or 'not set'} · --account {acct}: working on "
              f"{' / '.join(f'`{k}`' for k in read)} (`url` is not used)"
              + (f" · {', '.join(ignored)}: not used" if ignored else ""))
    else:
        print(f"active account: {active or 'not set'} · publishing always uses `url`"
              + (f" · {', '.join(ignored)}: not used" if ignored else ""))
    print(f"threshold: {args.threshold_kb:g} KB (re-issue above) · batch: {args.batch_kb:g} KB (live + local bytes)")
    print()
    body = []
    for r in work_rows:
        if r.get("hand"):
            rg = "none (hand-maintained)"
        elif r["regen"]:
            rg = ("regen (due): " if r["regen_due"] else "regen: ") + r["regen"]
        elif r["needs_regen"]:
            rg = "needs-regen: " + needs_regen_text(r["file"], r["abs"])
        else:
            rg = "-"
        pub = acct_get(r["a"], "published_at", acct)
        pe = iso_to_epoch(pub)
        if pe is not None and pe > time.time() + CLOCK_SKEW:
            pub = f"{pub} (future: ignored)"
        body.append([
            r["file"],
            f"{r['size'] / KB:.1f}" if r["exists"] else "-",
            utc_ts(r["mtime"]) if r["mtime"] else "-",
            pub if isinstance(pub, str) and pub else "-",
            r["state"], rg, r["url"] or "-",
        ])
    for line in table(["FILE", "KB", "MTIME", "PUBLISHED_AT", "STATE", "REGEN", "URL"], body):
        print(line)
    if foreign:
        print(f"OTHER-ACCOUNT: {', '.join(foreign)} (no url_{acct}; left out of the batches, "
              "published only with REISSUE ON OTHER ACCOUNT: yes)")
    if due:
        print("regen-due: run each row's regen first, then publish it in place or re-issued by size "
              "(re-run --summary after the regen to see the state)")
    print()
    page_b = args.page_kb * KB
    for r in inplace:
        if r["live"] > page_b:
            print(f"pages: {r['file']} ~{math.ceil(r['live'] / page_b)} "
                  f"(<= {args.page_kb:g} KB each) -- run --pages on the saved live copy")
    for r in inplace:
        n = long_lines(r["abs"])
        if n:
            print(f"warn: {r['file']} has {n} line(s) over {LONG_LINE} chars "
                  f"(the Read tool truncates them; see the retry rule in procedure.md)")
    warn_fallback()
    for f in missing_url:
        print(f"warn: {f} has no url_{acct}, left out of the block (other account)" if acct
              else f"warn: {f} has no url yet, left out of the block (publish it as `new`)")
    for r in work_rows:
        if r["state"] == "missing":
            print(f"warn: {r['file']} does not exist on disk" + (" (regen may create it)" if r["regen"] else ""))
    if batches and (len(batches) > 1 or batch_total > args.batch_kb * KB):
        print(f"BATCHES: {len(batches)} (live + local bytes, <= {args.batch_kb:g} KB each; "
              f"re-issue/new/regen-due/needs-regen rows in batch 1)")
        for i, (grp, tot) in enumerate(batches, 1):
            print(f"  batch {i}: {', '.join(r['file'] for r in grp)} ({tot / KB:.0f} KB)")
        print(f"  {batches_text(batches)}")
    print()
    print(f"links: {len(block)} rows · use --block-only")
    return 0


# --------------------------------------------------------------------------- registry writes

def open_lock(lock_path):
    """Open and exclusively lock the lock file; retry if it was unlinked while we waited."""
    while True:
        fh = open(lock_path, "a+")
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            if os.fstat(fh.fileno()).st_ino == os.stat(lock_path).st_ino:
                return fh
        except OSError:
            pass
        fh.close()


def update_registry(target, mutate):
    """Locked, atomic read-modify-write that keeps key order, indent and non-ASCII text.
    The transient lock file is removed (still under the lock) in a finally block, so a
    die() (exit 2) inside `mutate` does not leave it behind."""
    reg = find_registry(target)
    reg_dir = os.path.dirname(reg)
    lock_path = os.path.join(reg_dir, ".artifacts.json.lock")
    lock = open_lock(lock_path)
    try:
        with open(reg, encoding="utf-8") as fh:
            text = fh.read()
        data = json.loads(text)
        m = re.search(r"\n(\t+| +)\S", text)
        indent = ("\t" if m.group(1).startswith("\t") else len(m.group(1))) if m else 2
        result = mutate(reg_dir, data)
        out = json.dumps(data, indent=indent, ensure_ascii=False)
        if text.endswith("\n"):
            out += "\n"
        fd, tmp = tempfile.mkstemp(prefix=".artifacts.", suffix=".tmp", dir=reg_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(out)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.chmod(tmp, os.stat(reg).st_mode & 0o7777)
            except OSError:
                pass
            os.replace(tmp, reg)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    finally:
        try:
            os.unlink(lock_path)  # still under the lock; also runs when die() exits
        except OSError:
            pass
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return result


def pick_row(data, file_):
    hits = [a for a in data.get("artifacts", []) if isinstance(a, dict) and a.get("file") == file_]
    if len(hits) != 1:
        die(f"{len(hits)} rows match file {file_!r} (exact match on `file` required)")
    return hits[0]


def set_top_key(data, key, value):
    """Set a top-level registry key; a new one lands right after the active-account key (else at the end)."""
    if key in data or not any(k in data for k in ACCOUNT_KEYS):
        data[key] = value
        return
    items = list(data.items())
    data.clear()
    placed = False
    for i, (k, v) in enumerate(items):
        data[k] = v
        if not placed and k in ACCOUNT_KEYS and not any(n in ACCOUNT_KEYS for n, _ in items[i + 1:]):
            data[key] = value
            placed = True


def mark_published(args):
    file_, url, version = args.mark_published
    if not re.match(r"^https://\S+$", url):
        die("URL must be an https:// link")
    if not version.strip():
        die("VERSION must not be empty")

    def mutate(reg_dir, data):
        a = pick_row(data, file_)
        absf = os.path.join(reg_dir, file_)
        if not os.path.isfile(absf):
            die(f"{file_} does not exist on disk, nothing to stamp")
        session, _ = resolve_account(data, args.account)
        acct = other_account(data, session)
        ukey, pkey, rkey, ckey, tkey, vkey, bkey = (f"{b}_{acct}" if acct else b for b in (
            "url", "previous_url", "reissued", "sha256", "published_at", "version", "published_bytes"))
        cur_url = acct_get(a, "url", acct)
        old = cur_url if isinstance(cur_url, str) and cur_url else None
        prev = args.previous_url
        if prev and old and prev != old:
            die(f"--previous-url {prev} does not match the row's current {ukey}; the real old url is {old}")
        if not prev and old and old != url:
            prev = old
        if prev and prev == url:
            prev = None
        ts, day = now_stamp()
        before = {k: a.get(k) for k in (ukey, tkey, vkey, ckey, bkey, pkey, rkey)}
        before[ukey] = cur_url
        a[ukey] = url
        a[tkey] = ts
        a[vkey] = version
        a[ckey] = file_sha256(absf)
        a[bkey] = os.path.getsize(absf)
        if acct:  # first write migrates an alias family to the plain suffix: never two urls on one row
            for b in FAMILY:
                a.pop(f"{b}_cuenta_{acct}", None)
        if "published" in a and not acct:
            cur = a["published"]
            a["published"] = ts if isinstance(cur, str) and len(cur) > 10 else day
        if prev:
            reason = args.reason or "re-issued as a new artifact"
            a[pkey] = prev
            a[rkey] = f"{day}: {reason}. Antecedente: {prev}"
        after = {k: a.get(k) for k in before}
        last_old = data.get("last_session_account")
        last = session or active_account(data)  # the account this session publishes under
        if last:
            set_top_key(data, "last_session_account", last)
        return before, after, acct, last_old, last

    before, after, acct, last_old, last = update_registry(args.target, mutate)
    print(f"stamped {file_}" + (f" (account {acct}: url_{acct})" if acct else ""))
    for k in after:
        if before[k] != after[k]:
            print(f"  {k}: {before[k]!r} -> {after[k]!r}")
    if last and last_old != last:
        print(f"  last_session_account: {last_old!r} -> {last!r}")
    return 0


def suffix_for(old):
    return (old or "").strip() or "previous"


def set_active_account(args):
    name = args.set_active_account

    def mutate(reg_dir, data):
        old = active_account(data)
        if (old or "").strip() == name.strip():
            die(f"{name!r} is already the active account, nothing to swap")
        osuf = suffix_for(old)
        if not (old or "").strip() and not any(isinstance(acct_get(a, "url", name), str) and acct_get(a, "url", name)
                                   for a in data["artifacts"] if isinstance(a, dict)):
            data["active_account"] = name  # nothing declared, nothing to move: just declare it
            return old, None, None
        swapped, kept = [], []
        for a in data["artifacts"]:
            if not isinstance(a, dict) or not isinstance(a.get("file"), str):
                continue
            other = acct_get(a, "url", name)
            if not (isinstance(other, str) and other):
                kept.append(a["file"])
                continue
            for b in FAMILY:  # rename: canonical <- _NAME, old canonical -> _<old active>, _NAME removed
                new_v = acct_get(a, b, name)
                had_new = any(k in a for k in (f"{b}_{name}", f"{b}_cuenta_{name}"))
                had_old, old_v = b in a, a.get(b)
                if had_new:
                    a[b] = new_v
                else:
                    a.pop(b, None)
                for k in (f"{b}_{name}", f"{b}_cuenta_{name}"):
                    a.pop(k, None)
                if had_old:
                    a[f"{b}_{osuf}"] = old_v
                else:
                    a.pop(f"{b}_{osuf}", None)
            swapped.append(a["file"])
        if not swapped:
            die(f"no row has `url_{name}`, nothing to swap (check the account name)")
        data["active_account"] = name
        if "cuenta_activa" in data:
            data["cuenta_activa"] = name
        return old, swapped, kept

    old, swapped, kept = update_registry(args.target, mutate)
    if swapped is None:
        print(f"declared active_account: {name} (no url_{name} families to move)")
        return 0
    print(f"active account: {old or 'not set'} -> {name}")
    print(f"moved the url_{name} family -> canonical keys and the canonical family -> _{suffix_for(old)} "
          f"on {len(swapped)} row(s): {', '.join(swapped)}")
    if kept:
        print(f"warn: {len(kept)} row(s) without url_{name} left untouched (their `url` still belongs to "
              f"{old or 'the previous account'}): {', '.join(kept)}")
    return 0


def set_regen(args):
    file_, cmd = args.set_regen

    def mutate(reg_dir, data):
        a = pick_row(data, file_)
        old = a.get("regen")
        a["regen"] = cmd
        return old

    old = update_registry(args.target, mutate)
    print(f"regen set for {file_}: {old!r} -> {cmd!r}")
    return 0


# --------------------------------------------------------------------------- pagination

def pages(args):
    path = os.path.expanduser(args.pages)
    if not os.path.isfile(path):
        die(f"{args.pages} is not a file")
    with open(path, "rb") as fh:
        lines = fh.read().split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    limit_b = args.page_kb * KB
    out, start, size, count = [], 0, 0, 0
    longs = []
    for i, ln in enumerate(lines):
        n = len(ln) + 1
        if count and (size + n > limit_b or count >= args.page_lines):
            out.append((start + 1, count, size))
            start, size, count = i, 0, 0
        size += n
        count += 1
        chars = len(ln.decode("utf-8", "replace"))
        if chars > LONG_LINE:
            longs.append((i + 1, chars))
    if count:
        out.append((start + 1, count, size))
    total = sum(p[2] for p in out)
    print(f"{os.path.basename(path)}: {len(lines)} lines · {total / KB:.0f} KB · {len(out)} page(s) "
          f"(<= {args.page_kb:g} KB, <= {args.page_lines} lines each)")
    for k, (off, lim, sz) in enumerate(out, 1):
        print(f"page {k}: offset={off} limit={lim} (~{sz / KB:.0f} KB)")
    for ln_no, chars in longs[:10]:
        print(f"warn: line {ln_no} has {chars} chars (over {LONG_LINE}: the Read tool truncates it)")
    if len(longs) > 10:
        print(f"warn: {len(longs) - 10} more long line(s)")
    return 0


# --------------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description="Artifact courier preflight and registry sealer (stdlib).")
    p.add_argument("target", nargs="?", help="docs dir containing artifacts.json, or the artifacts.json itself")
    p.add_argument("--module", action="append", default=[], metavar="REL",
                   help="only rows of this module (relative to the docs dir; '.' = root); repeatable")
    p.add_argument("--only", action="append", default=[], metavar="F,F", help="only these registry files (narrows the work table, the batches and the link block)")
    p.add_argument("--threshold-kb", type=float, default=600, help="re-issue above this size (default 600)")
    p.add_argument("--version", action="version", version="courier_preflight.py " + __version__)
    p.add_argument("--batch-kb", type=float, default=400,
                   help="byte budget per courier batch: live + local bytes of its rows (default 400, i.e. "
                        "400 KB; a larger value gives fewer, bigger batches, a row above it gets a batch alone)")
    p.add_argument("--summary", action="store_true", help="one line")
    p.add_argument("--batches", action="store_true", help='print only "batch1=f1,f2;batch2=f3"')
    p.add_argument("--block-only", action="store_true", help="print only the artifact link lines")
    p.add_argument("--include-hidden", action="store_true",
                   help="with --block-only: also rows with in_close_block false")
    p.add_argument("--mark-published", nargs=3, metavar=("FILE", "URL", "VERSION"))
    p.add_argument("--previous-url", metavar="OLD")
    p.add_argument("--reason", metavar="TEXT")
    p.add_argument("--set-regen", nargs=2, metavar=("FILE", "COMMAND"))
    p.add_argument("--account", metavar="NAME|auto",
                   help="claude.ai account the session publishes under (`auto`: the registry's "
                        "last_session_account, else its active_account); when it is not the registry's "
                        "active_account the working url is url_NAME (table, --block-only, --batches, "
                        "--summary, state machine; rows without it are `other-account`), and "
                        "--mark-published seals url_NAME and leaves url alone")
    p.add_argument("--set-active-account", metavar="NAME",
                   help="move the registry to account NAME: on every row that has url_NAME the url family "
                        "is renamed (url_NAME -> url, old url -> url_<old active>) and active_account "
                        "(and cuenta_activa if present) is set; a registry that declares no active account "
                        "(missing or empty) and has no url_NAME family is only declared: active_account: NAME "
                        "is written, nothing else changes; exit 2 when NAME is already active")
    p.add_argument("--pages", metavar="SAVED_FILE")
    p.add_argument("--page-kb", type=float, default=60)
    p.add_argument("--page-lines", type=int, default=450)
    args = p.parse_args()

    if args.pages:
        return pages(args)
    if not args.target:
        p.error("target (docs dir or artifacts.json) is required")
    for flag in ("account", "set_active_account"):
        v = getattr(args, flag)
        if v is not None and not re.fullmatch(r"[\w.-]+", v):
            p.error(f"--{flag.replace('_', '-')} needs a name made of letters, digits, `_`, `.` or `-`")
    if args.set_active_account:
        if args.account or args.mark_published or args.set_regen:
            p.error("--set-active-account is exclusive (no --account, --mark-published or --set-regen)")
        return set_active_account(args)
    if args.mark_published:
        return mark_published(args)
    if args.set_regen:
        return set_regen(args)
    if sum(map(bool, (args.summary, args.block_only, args.batches))) > 1:
        p.error("--summary, --batches and --block-only are exclusive")
    if args.include_hidden and not args.block_only:
        p.error("--include-hidden only works with --block-only")
    return report(args)


if __name__ == "__main__":
    sys.exit(main())
