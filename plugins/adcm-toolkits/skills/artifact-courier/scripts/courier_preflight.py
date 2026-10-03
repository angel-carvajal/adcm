#!/usr/bin/env python3
"""courier_preflight -- read-only state check and registry sealer for the artifact courier.

Stdlib only. Reads an `artifacts.json` registry (see references/registry.md) and tells the
courier which rows need work:

  missing            the file does not exist on disk
  new                the row has no `url` yet (first publish, no `url` in the Artifact call)
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

Usage
  courier_preflight.py <docs_dir|artifacts.json> [--module REL]... [--only F,F]
                       [--threshold-kb 300] [--batch-kb 400] [--page-kb 60]
                       [--summary | --batches | --block-only [--include-hidden]]
  courier_preflight.py <docs_dir> --mark-published FILE URL VERSION
                       [--previous-url OLD] [--reason TEXT]
                       (--previous-url must equal the row's current url, exit 2 otherwise;
                        without it a changed url records the old one as previous_url)
  courier_preflight.py <docs_dir> --set-regen FILE COMMAND
  courier_preflight.py --pages SAVED_FILE [--page-kb 60] [--page-lines 450]

Reading never writes anything. Only --mark-published and --set-regen write the registry
(exclusive flock on `.artifacts.json.lock`, atomic tmp+fsync+replace, key order, indent and
non-ASCII characters preserved; the transient lock file is always removed, also after die()).

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

REGISTRY_CANDIDATES = ("artifacts.json", "ai/ai-brain/artifacts.json", "ai-brain/artifacts.json")
DEFAULT_MARKERS = ("task.md", "execute.md", "detailed-plan.md")
KB = 1024
CLOCK_SKEW = 60  # seconds: a published_at further in the future than this is ignored (as in the guard)
LONG_LINE = 2000
ACCOUNT_KEYS = ("active_account", "cuenta_activa")
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


def stamped_sha(a):
    """Registry sha256 normalised like the guard: strip, lower, drop a "sha256:" prefix."""
    value = a.get("sha256")
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


def regen_cmd(a):
    r = a.get("regen")
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

def analyse(reg_dir, data, threshold_kb):
    markers = normalize_markers(data.get("close_markers"))
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
        url = a.get("url") if isinstance(a.get("url"), str) and a.get("url") else None
        pb = a.get("published_bytes")
        pb = pb if isinstance(pb, (int, float)) and not isinstance(pb, bool) else 0
        if not exists:
            state = "missing"
        elif not url:
            state = "new"
        else:
            sha = stamped_sha(a)
            pub = iso_to_epoch(a.get("published_at"))
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
        needs_regen = src_newer and not regen
        regen_due = src_newer and bool(regen)
        if src_newer and state == "fresh":
            state = "regen-due"  # never "fresh": the page predates its sources
        rows.append({
            "a": a, "file": a["file"], "abs": absf, "exists": exists, "size": size,
            "mtime": mtime, "url": url, "state": state, "regen": regen,
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
    todo = [r for r in rows if r["state"] != "fresh" and
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
    rows = analyse(reg_dir, data, args.threshold_kb)

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
    missing_url = []
    for r in block_rows:
        if r["a"].get("in_close_block", True) is False:
            continue
        if r["url"]:
            block.append("- " + fmt_link({**r["a"], "url": r["url"]}))
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

    if args.block_only:
        lines = block
        if args.include_hidden:
            lines = ["- " + fmt_link({**r["a"], "url": r["url"]}) for r in work_rows if r["url"]]
        print("\n".join(lines))
        for f in missing_url:
            print(f"warn: {f} has no url, left out of the block", file=sys.stderr)
        return 0

    if args.batches:
        print(batches_text(batches))
        return 0

    if args.summary:
        parts = [f"{len(work_rows)} rows"]
        for k in ("fresh", "stale-inplace", "stale-reissue", "new", "missing"):
            if counts.get(k):
                parts.append(f"{k} {counts[k]}")
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
        print("courier-preflight: " + " · ".join(parts))
        return 0

    active = next((data[k] for k in ACCOUNT_KEYS if isinstance(data.get(k), str)), None)
    ignored = sorted({k for r in rows for k in r["a"] if k.startswith("url_")})
    print(f"registry: {reg}")
    print(f"active account: {active or 'not set'} · publishing always uses `url`"
          + (f" · {', '.join(ignored)}: not used" if ignored else ""))
    print(f"threshold: {args.threshold_kb:g} KB (re-issue above) · batch: {args.batch_kb:g} KB (live + local bytes)")
    print()
    body = []
    for r in work_rows:
        if r["regen"]:
            rg = ("regen (due): " if r["regen_due"] else "regen: ") + r["regen"]
        elif r["needs_regen"]:
            rg = "needs-regen: " + needs_regen_text(r["file"], r["abs"])
        else:
            rg = "-"
        pub = r["a"].get("published_at")
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
    for f in missing_url:
        print(f"warn: {f} has no url yet, left out of the block (publish it as `new`)")
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
    print("=== LINKS ===")
    print("\n".join(block))
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
        old = a.get("url") if isinstance(a.get("url"), str) and a.get("url") else None
        prev = args.previous_url
        if prev and old and prev != old:
            die(f"--previous-url {prev} does not match the row's current url; the real old url is {old}")
        if not prev and old and old != url:
            prev = old
        if prev and prev == url:
            prev = None
        ts, day = now_stamp()
        before = {k: a.get(k) for k in ("url", "published_at", "version", "sha256", "published_bytes", "previous_url", "reissued")}
        a["url"] = url
        a["published_at"] = ts
        a["version"] = version
        a["sha256"] = file_sha256(absf)
        a["published_bytes"] = os.path.getsize(absf)
        if "published" in a:
            cur = a["published"]
            a["published"] = ts if isinstance(cur, str) and len(cur) > 10 else day
        if prev:
            reason = args.reason or "re-issued as a new artifact"
            a["previous_url"] = prev
            a["reissued"] = f"{day}: {reason}. Antecedente: {prev}"
        after = {k: a.get(k) for k in before}
        return before, after

    before, after = update_registry(args.target, mutate)
    print(f"stamped {file_}")
    for k in after:
        if before[k] != after[k]:
            print(f"  {k}: {before[k]!r} -> {after[k]!r}")
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
    p.add_argument("--threshold-kb", type=float, default=300, help="re-issue above this size (default 300)")
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
    p.add_argument("--pages", metavar="SAVED_FILE")
    p.add_argument("--page-kb", type=float, default=60)
    p.add_argument("--page-lines", type=int, default=450)
    args = p.parse_args()

    if args.pages:
        return pages(args)
    if not args.target:
        p.error("target (docs dir or artifacts.json) is required")
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
