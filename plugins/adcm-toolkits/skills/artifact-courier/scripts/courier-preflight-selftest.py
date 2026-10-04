#!/usr/bin/env python3
"""courier-preflight-selftest - behavioural tests for courier_preflight.py's per-account URLs (stdlib only).

Usage:
  python3 courier-preflight-selftest.py [--script PATH] [--only NAME] [--keep]

Builds one throwaway `tempfile` registry per case (an `artifacts.json` whose rows carry `url`,
and `url_alt` on most of them, plus `active_account`) with the HTML files it names, runs
courier_preflight.py as a subprocess (`<docs_dir> [flags]`, PYTHONDONTWRITEBYTECODE=1) and
prints `PASS|FAIL|SKIP <case> [- why]`. Exit code 1 when any case FAILs.

Contract encoded (the courier works inside ONE account at a time; the registry's `url` is the
canonical link of the registry's `active_account`, `url_<account>` the link of any other):
  - without --account, or with --account == active_account: the work URL is `url` everywhere
    (work table, --block-only, --batches, --summary);
  - --account NAME (not active): a row with `url_NAME` uses it in the table, --block-only and
    --batches; a row without it shows state `other-account` and is left out of the batches;
  - --mark-published FILE URL VERSION --account NAME (not active): stamps the row and writes
    `url_NAME`, `url` untouched; without --account, or with the active one: `url` as always;
  - --set-active-account NAME: swaps `url` <-> `url_NAME` on every row, sets `active_account`,
    and keeps the old canonical link in `url_<old active>`;
  - the stamps are per account too: --mark-published --account NAME writes `sha256_NAME`,
    `published_at_NAME`, `published_bytes_NAME`, `version_NAME` and leaves the shared ones alone;
    the state under --account NAME is judged from those (a row with `url_NAME` but no `*_NAME`
    stamps is stale even when the shared stamps are fresh); --set-active-account moves the whole
    family (url, previous_url, reissued, sha256, published_at, published_bytes, version);
  - `url_cuenta_NAME` is an accepted alias of `url_NAME`; a row whose file is missing and that
    has no `url_NAME` stays `missing` (not `other-account`);
  - the session account: every --mark-published writes the top-level `last_session_account` (the
    --account NAME it ran with, else the active account when known); `--account auto` resolves to it
    (else to the active account) and the report header prints `account: <resolved> (auto)`;
  - --block-only (and the `=== LINKS ===` section of the default report) is the block the main session
    pastes: per row the url of the resolved account's family, falling back to the canonical `url`
    (with a stderr warning) when the family has none.

Fixtures are generic (account names "acmecorp" and "alt", example.com links, no private
paths). The script under test defaults to the courier_preflight.py next to this file; pass
--script to test an installed copy. --keep leaves the temp trees on disk.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ACTIVE = "acmecorp"
OTHER = "alt"
LOCK = ".artifacts.json.lock"
CORP = {"plans.html": "https://example.com/a/plans-corp", "prompts.html": "https://example.com/a/prompts-corp",
        "deck.html": "https://example.com/a/deck-corp"}
ALT = {"plans.html": "https://example.com/a/plans-alt", "prompts.html": "https://example.com/a/prompts-alt"}
ALL_CORP = dict(CORP, **{"ghost.html": "https://example.com/a/ghost-corp"})
SHARED = ("url", "sha256", "published_at", "published_bytes", "version")
FAMILY = ("url", "previous_url", "reissued", "sha256", "published_at", "published_bytes", "version")


class Skip(Exception):
    pass


# ------------------------------------------------------------------ harness
class R:
    """One courier_preflight run."""

    def __init__(self, p):
        self.rc, self.out, self.err = p.returncode, p.stdout, p.stderr
        self.text = p.stdout + p.stderr


class Ctx:
    def __init__(self, script, root):
        self.script, self.root = script, root
        self.env = dict(os.environ)
        self.env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                         "HOME": root})

    def registry(self, name, files=("plans.html", "prompts.html", "deck.html"), alt_for=("plans.html", "prompts.html"),
                 stamp=(), missing=(), tweak=None):
        """<root>/<name>/artifacts.json with one row per file (url, + url_alt where listed) and the files.
        Rows are stale (no stamps) unless listed in `stamp` (fresh shared stamps from the file itself);
        `missing` rows have no file on disk; `tweak` {file: {key: value|None}} edits rows (None deletes a key)."""
        d = os.path.join(self.root, name)
        os.makedirs(d, exist_ok=True)
        rows = []
        for f in files:
            row = {"file": f, "title": f.split(".")[0].capitalize(), "favicon": "📄", "url": ALL_CORP[f]}
            if f in alt_for:
                row["url_alt"] = ALT[f]
            if f not in missing:
                with open(os.path.join(d, f), "w", encoding="utf-8") as fh:
                    fh.write(f"<!doctype html><html><body><h1>{f}</h1></body></html>\n")
            if f in stamp:
                row.update({"sha256": sha(os.path.join(d, f)), "version": "V1",
                            "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                            "published_bytes": os.path.getsize(os.path.join(d, f))})
            for k, v in ((tweak or {}).get(f) or {}).items():
                if v is None:
                    row.pop(k, None)
                else:
                    row[k] = v
            rows.append(row)
        return self.write_registry(d, rows)

    def write_registry(self, d, rows, active=ACTIVE, extra=None):
        top = {"active_account": active} if active else {}
        top.update(extra or {})
        top["artifacts"] = rows
        with open(os.path.join(d, "artifacts.json"), "w", encoding="utf-8") as fh:
            json.dump(top, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        return d

    def load(self, d):
        with open(os.path.join(d, "artifacts.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def row(self, d, file_):
        return next(a for a in self.load(d)["artifacts"] if a["file"] == file_)

    def run(self, target, *flags):
        cmd = [sys.executable, self.script, target] + list(flags)
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=self.env, cwd=self.root, timeout=60)
        return R(p)


class Check:
    def __init__(self):
        self.problems = []

    def ok(self, cond, what):
        if not cond:
            self.problems.append(what)

    def eq(self, got, want, what):
        if got != want:
            self.problems.append(f"{what}: got {got!r}, want {want!r}")

    def has(self, hay, needle, what):
        if needle not in (hay or ""):
            self.problems.append(f"{what}: {needle!r} not in {(hay or '')[:80]!r}")

    def lacks(self, hay, needle, what):
        if needle in (hay or ""):
            self.problems.append(f"{what}: {needle!r} must not be present")


def table_rows(out):
    """{FILE: {COLUMN: cell}} of the default report's work table."""
    lines = out.splitlines()
    i = next((n for n, x in enumerate(lines) if x.startswith("FILE")), None)
    if i is None:
        return {}
    hdr = [h.strip() for h in lines[i].split(" | ")]
    rows = {}
    for x in lines[i + 2:]:
        if not x.strip():
            break
        cells = [c.strip() for c in x.split(" | ")]
        rows[cells[0]] = dict(zip(hdr, cells))
    return rows


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def batch_files(out):
    """Files named in a 'batch1=a,b;batch2=c' line."""
    return [f for part in out.strip().split(";") if "=" in part for f in part.split("=", 1)[1].split(",") if f]


# ------------------------------------------------------------------ cases
def case_default_uses_url_and_active_account_equals_default(ctx, t):
    d = ctx.registry("c1")
    bo = ctx.run(d, "--block-only")
    t.eq(bo.rc, 0, "default --block-only exit code")
    for f, u in CORP.items():
        t.has(bo.out, u, f"default block uses the canonical url of {f}")
    for f, u in ALT.items():
        t.lacks(bo.out, u, f"default block never shows url_alt of {f}")
    tbl = ctx.run(d)
    rows = table_rows(tbl.out)
    t.eq({f: r.get("URL") for f, r in rows.items()}, CORP, "default table: URL column is `url`")
    t.eq({r.get("STATE") for r in rows.values()}, {"stale-inplace"}, "fixture rows are all stale-inplace")
    t.eq(ctx.run(d, "--batches").out.strip(), "batch1=plans.html,prompts.html,deck.html", "default --batches")
    # --account == active_account behaves like the default
    for flag in ("--block-only", "--batches", "--summary"):
        base, same = ctx.run(d, flag), ctx.run(d, flag, "--account", ACTIVE)
        t.eq(same.rc, 0, f"{flag} --account {ACTIVE} exit code")
        t.eq(same.out, base.out, f"{flag} --account {ACTIVE} output == default")
    same = ctx.run(d, "--account", ACTIVE)
    t.eq(table_rows(same.out), rows, f"work table with --account {ACTIVE} == default")
    # a stamp under the active account updates `url`, never url_alt
    d2 = ctx.registry("c1b")
    new = "https://example.com/a/plans-corp-2"
    r = ctx.run(d2, "--mark-published", "plans.html", new, "V2", "--account", ACTIVE)
    t.eq(r.rc, 0, f"--mark-published --account {ACTIVE} exit code")
    row = ctx.row(d2, "plans.html")
    t.eq(row.get("url"), new, "stamp under the active account: url updated")
    t.eq(row.get("url_alt"), ALT["plans.html"], "stamp under the active account: url_alt untouched")


def case_account_selects_url_other_account(ctx, t):
    d = ctx.registry("c2")
    bo = ctx.run(d, "--block-only", "--account", OTHER)
    t.eq(bo.rc, 0, "--block-only --account alt exit code")
    for f, u in ALT.items():
        t.has(bo.out, u, f"block uses url_alt of {f}")
        t.lacks(bo.out, CORP[f], f"block does not use the canonical url of {f}")
    bt = ctx.run(d, "--batches", "--account", OTHER)
    t.eq(bt.rc, 0, "--batches --account alt exit code")
    files = batch_files(bt.out)
    t.ok("plans.html" in files and "prompts.html" in files, f"rows with url_alt are batched, got {bt.out.strip()!r}")
    t.ok("deck.html" not in files, f"the row without url_alt is left out of the batches, got {bt.out.strip()!r}")
    tbl = ctx.run(d, "--account", OTHER)
    t.eq(tbl.rc, 0, "work table --account alt exit code")
    rows = table_rows(tbl.out)
    t.eq(rows.get("deck.html", {}).get("STATE"), "other-account", "row without url_alt shows state other-account")
    for f, u in ALT.items():
        t.eq(rows.get(f, {}).get("URL"), u, f"table URL of {f} is url_alt")
        t.eq(rows.get(f, {}).get("STATE"), "stale-inplace", f"state of {f} is unchanged")
    t.eq(ctx.run(d, "--summary", "--account", OTHER).rc, 0, "--summary --account alt exit code")
    # the default (no flag) is unaffected by the existence of url_alt
    t.eq(ctx.run(d, "--batches").out.strip(), "batch1=plans.html,prompts.html,deck.html", "default --batches unchanged")


def case_mark_published_account(ctx, t):
    # (a) other account, row already has url_alt: stamps + url_alt replaced, url untouched
    d = ctx.registry("c3a")
    before = ctx.load(d)
    new = "https://example.com/a/plans-alt-2"
    r = ctx.run(d, "--mark-published", "plans.html", new, "V2", "--account", OTHER)
    t.eq(r.rc, 0, "--mark-published --account alt exit code")
    after = ctx.load(d)
    row = ctx.row(d, "plans.html")
    t.eq(row.get("url"), CORP["plans.html"], "url unchanged")
    t.eq(row.get("url_alt"), new, "url_alt == the new link")
    t.eq(row.get("version_alt"), "V2", "version_alt stamped (the full per-account stamp family: see per_account_stamps)")
    t.eq(after.get("active_account"), ACTIVE, "active_account untouched")
    t.eq([a for a in after["artifacts"] if a["file"] != "plans.html"],
         [a for a in before["artifacts"] if a["file"] != "plans.html"], "other rows untouched")
    t.ok(not os.path.exists(os.path.join(d, LOCK)), "lock file removed")
    t.has(ctx.run(d, "--block-only", "--account", OTHER).out, new, "--account alt block shows the new link")
    default = ctx.run(d, "--block-only").out
    t.has(default, CORP["plans.html"], "default block still shows the canonical link")
    t.lacks(default, new, "default block does not show the alt link")
    # (b) other account, row without url_alt yet: url_alt created, url untouched
    d = ctx.registry("c3b")
    new = "https://example.com/a/deck-alt"
    r = ctx.run(d, "--mark-published", "deck.html", new, "V1", "--account", OTHER)
    t.eq(r.rc, 0, "--mark-published (row without url_alt) exit code")
    row = ctx.row(d, "deck.html")
    t.eq(row.get("url"), CORP["deck.html"], "row without url_alt: url unchanged")
    t.eq(row.get("url_alt"), new, "row without url_alt: url_alt created")
    t.eq(row.get("version_alt"), "V1", "row without url_alt: version_alt stamped")
    # (c) no --account: `url` as today, url_alt untouched
    d = ctx.registry("c3c")
    new = "https://example.com/a/prompts-corp-2"
    r = ctx.run(d, "--mark-published", "prompts.html", new, "V3")
    t.eq(r.rc, 0, "--mark-published without --account exit code")
    row = ctx.row(d, "prompts.html")
    t.eq(row.get("url"), new, "no --account: url updated")
    t.eq(row.get("url_alt"), ALT["prompts.html"], "no --account: url_alt untouched")
    t.eq(row.get("version"), "V3", "no --account: version stamped")


def case_set_active_account_swap(ctx, t):
    files = ("plans.html", "prompts.html")
    d = ctx.registry("c4", files=files)
    r = ctx.run(d, "--set-active-account", OTHER)
    t.eq(r.rc, 0, "--set-active-account alt exit code")
    data = ctx.load(d)
    t.eq(data.get("active_account"), OTHER, "active_account == alt")
    for a in data["artifacts"]:
        f = a["file"]
        t.eq(a.get("url"), ALT[f], f"{f}: url is the former url_alt")
        t.eq(a.get(f"url_{ACTIVE}"), CORP[f], f"{f}: url_{ACTIVE} holds the former canonical link")
    block = ctx.run(d, "--block-only").out
    for f in files:
        t.has(block, ALT[f], f"default block now shows the alt link of {f}")
        t.lacks(block, CORP[f], f"default block no longer shows the {ACTIVE} link of {f}")
    t.ok(not os.path.exists(os.path.join(d, LOCK)), "lock file removed")
    r = ctx.run(d, "--set-active-account", ACTIVE)
    t.eq(r.rc, 0, f"--set-active-account {ACTIVE} (swap back) exit code")
    data = ctx.load(d)
    t.eq(data.get("active_account"), ACTIVE, f"active_account == {ACTIVE} again")
    t.eq({a["file"]: a.get("url") for a in data["artifacts"]}, {f: CORP[f] for f in files}, "round trip restores every url")


def case_per_account_stamps(ctx, t):
    d = ctx.registry("c5", stamp=("plans.html", "prompts.html"))
    shared0 = {f: {k: ctx.row(d, f).get(k) for k in SHARED} for f in ("plans.html", "prompts.html")}
    default = table_rows(ctx.run(d).out)
    t.eq({f: default.get(f, {}).get("STATE") for f in shared0}, {"plans.html": "fresh", "prompts.html": "fresh"},
         "default run: rows with fresh shared stamps are fresh")
    other = table_rows(ctx.run(d, "--account", OTHER).out)
    t.eq({f: other.get(f, {}).get("STATE") for f in shared0}, {"plans.html": "stale-inplace", "prompts.html": "stale-inplace"},
         "--account alt: url_alt without *_alt stamps is stale-inplace even though the shared stamps are fresh")
    new = "https://example.com/a/plans-alt-2"
    r = ctx.run(d, "--mark-published", "plans.html", new, "V2", "--account", OTHER)
    t.eq(r.rc, 0, "--mark-published --account alt exit code")
    row = ctx.row(d, "plans.html")
    path = os.path.join(d, "plans.html")
    t.eq(row.get("url_alt"), new, "url_alt == the new link")
    t.eq(row.get("sha256_alt"), sha(path), "sha256_alt stamped")
    t.eq(row.get("published_bytes_alt"), os.path.getsize(path), "published_bytes_alt stamped")
    t.eq(row.get("version_alt"), "V2", "version_alt stamped")
    t.ok(isinstance(row.get("published_at_alt"), str) and bool(row.get("published_at_alt")), "published_at_alt stamped")
    t.eq({k: row.get(k) for k in SHARED}, shared0["plans.html"], "shared stamps (and url) untouched")
    t.eq({k: ctx.row(d, "prompts.html").get(k) for k in SHARED}, shared0["prompts.html"], "the other row is untouched")
    default = table_rows(ctx.run(d).out)
    t.eq({f: default.get(f, {}).get("STATE") for f in shared0}, {"plans.html": "fresh", "prompts.html": "fresh"},
         "default run: the canonical state is unchanged by a alt stamp")
    t.eq(default.get("plans.html", {}).get("URL"), CORP["plans.html"], "default run: canonical url unchanged")
    other = table_rows(ctx.run(d, "--account", OTHER).out)
    t.eq({f: other.get(f, {}).get("STATE") for f in shared0}, {"plans.html": "fresh", "prompts.html": "stale-inplace"},
         "--account alt: the stamped row is fresh, the unstamped one stays stale-inplace")
    t.eq(other.get("plans.html", {}).get("URL"), new, "--account alt: URL column shows the new alt link")
    t.ok(not os.path.exists(os.path.join(d, LOCK)), "lock file removed")


def case_account_alias_url_cuenta(ctx, t):
    alias = "https://example.com/a/plans-cuenta-alt"
    d = ctx.registry("c6", tweak={"plans.html": {"url_alt": None, "url_cuenta_alt": alias}})
    row = ctx.row(d, "plans.html")
    t.ok("url_alt" not in row and row.get("url_cuenta_alt") == alias, "fixture: plans.html has only url_cuenta_alt")
    bo = ctx.run(d, "--block-only", "--account", OTHER)
    t.eq(bo.rc, 0, "--block-only --account alt exit code")
    t.has(bo.out, alias, "block uses the url_cuenta_alt alias")
    t.lacks(bo.out, CORP["plans.html"], "block does not fall back to the canonical url")
    rows = table_rows(ctx.run(d, "--account", OTHER).out)
    t.eq(rows.get("plans.html", {}).get("URL"), alias, "table URL is the alias")
    t.eq(rows.get("plans.html", {}).get("STATE"), "stale-inplace", "the alias row is not other-account")
    t.eq(rows.get("deck.html", {}).get("STATE"), "other-account", "a row with neither spelling is other-account")
    t.ok("plans.html" in batch_files(ctx.run(d, "--batches", "--account", OTHER).out), "the alias row is batched")


def case_missing_file_without_url_other_account(ctx, t):
    d = ctx.registry("c7", files=("plans.html", "ghost.html"), alt_for=("plans.html",), missing=("ghost.html",))
    t.ok(not os.path.exists(os.path.join(d, "ghost.html")), "fixture: ghost.html is not on disk")
    t.eq(table_rows(ctx.run(d).out).get("ghost.html", {}).get("STATE"), "missing", "default run: state missing")
    r = ctx.run(d, "--account", OTHER)
    t.eq(r.rc, 0, "--account alt exit code")
    rows = table_rows(r.out)
    t.eq(rows.get("ghost.html", {}).get("STATE"), "missing", "--account alt: a missing file without url_alt stays missing")
    t.eq(rows.get("plans.html", {}).get("STATE"), "stale-inplace", "--account alt: the existing row is unaffected")


def case_set_active_account_family(ctx, t):
    files = ("plans.html", "prompts.html")
    d = ctx.registry("c8", files=files)
    data = ctx.load(d)
    canon, alt = {}, {}
    for i, a in enumerate(data["artifacts"], 1):
        f = a["file"]
        canon[f] = {"url": CORP[f], "previous_url": CORP[f] + "-old", "reissued": f"2026-01-0{i}: re-issued. Antecedente: {CORP[f]}-old",
                    "sha256": "c" * 63 + str(i), "published_at": f"2026-01-0{i}T10:00:00.000Z", "published_bytes": 100 + i,
                    "version": f"Vc{i}"}
        alt[f] = {"url": ALT[f], "previous_url": ALT[f] + "-old", "reissued": f"2026-02-0{i}: re-issued. Antecedente: {ALT[f]}-old",
                    "sha256": "b" * 63 + str(i), "published_at": f"2026-02-0{i}T10:00:00.000Z", "published_bytes": 200 + i,
                    "version": f"Vg{i}"}
        a.update(canon[f])
        a.update({f"{k}_{OTHER}": v for k, v in alt[f].items()})
    ctx.write_registry(d, data["artifacts"])

    def fam(f, suffix=""):
        row = ctx.row(d, f)
        return {k: row.get(k + suffix) for k in FAMILY}

    r = ctx.run(d, "--set-active-account", OTHER)
    t.eq(r.rc, 0, "--set-active-account alt exit code")
    t.eq(ctx.load(d).get("active_account"), OTHER, "active_account == alt")
    for f in files:
        t.eq(fam(f), alt[f], f"{f}: the whole canonical family is now the former alt one")
        t.eq(fam(f, "_" + ACTIVE), canon[f], f"{f}: the former canonical family is kept as *_{ACTIVE}")
    t.has(ctx.run(d, "--block-only", "--account", ACTIVE).out, CORP["plans.html"], f"--account {ACTIVE} (no longer active) uses url_{ACTIVE}")
    r = ctx.run(d, "--set-active-account", ACTIVE)
    t.eq(r.rc, 0, f"--set-active-account {ACTIVE} (back) exit code")
    t.eq(ctx.load(d).get("active_account"), ACTIVE, f"active_account == {ACTIVE} again")
    for f in files:
        t.eq(fam(f), canon[f], f"{f}: round trip restores the canonical family")
        t.eq(fam(f, "_" + OTHER), alt[f], f"{f}: round trip restores the alt family")


def case_last_session_account(ctx, t):
    d = ctx.registry("c9")
    t.ok("last_session_account" not in ctx.load(d), "fixture: no last_session_account yet")
    # --account auto without last_session_account resolves to the active account
    auto = ctx.run(d, "--account", "auto")
    t.eq(auto.rc, 0, "--account auto (no last_session_account) exit code")
    t.has(auto.out, f"account: {ACTIVE} (auto)", "header shows the resolved active account")
    t.eq({f: r.get("URL") for f, r in table_rows(auto.out).items()}, CORP, "auto == active: the table URL column is `url`")
    t.eq(ctx.run(d, "--account", "auto", "--block-only").out, ctx.run(d, "--block-only").out,
         "auto == active: --block-only equals the default block")
    t.lacks(ctx.run(d).out, "(auto)", "default header has no auto line")
    # sealing under `alt` records it, right after active_account
    new = "https://example.com/a/plans-alt-2"
    r = ctx.run(d, "--mark-published", "plans.html", new, "V2", "--account", OTHER)
    t.eq(r.rc, 0, "--mark-published --account alt exit code")
    t.has(r.out, f"last_session_account: None -> '{OTHER}'", "the seal output reports last_session_account")
    data = ctx.load(d)
    t.eq(data.get("last_session_account"), OTHER, "last_session_account == alt after the seal")
    t.eq(list(data), ["active_account", "last_session_account", "artifacts"], "new key sits right after active_account")
    t.eq(data.get("active_account"), ACTIVE, "active_account untouched")
    # --account auto now resolves to it
    auto = ctx.run(d, "--account", "auto")
    t.eq(auto.rc, 0, "--account auto (after the seal) exit code")
    t.has(auto.out, f"account: {OTHER} (auto)", "header shows the session account")
    rows = table_rows(auto.out)
    t.eq(rows.get("plans.html", {}).get("URL"), new, "auto: plans.html URL is the sealed url_alt")
    t.eq(rows.get("plans.html", {}).get("STATE"), "fresh", "auto: the sealed row is fresh under alt")
    t.eq(rows.get("prompts.html", {}).get("URL"), ALT["prompts.html"], "auto: prompts.html URL is url_alt")
    t.eq(rows.get("deck.html", {}).get("STATE"), "other-account", "auto: the row without url_alt is other-account")
    t.eq(ctx.run(d, "--account", "auto", "--block-only").out, ctx.run(d, "--account", OTHER, "--block-only").out,
         "--account auto == --account alt for --block-only")
    t.eq(ctx.run(d, "--account", "auto", "--summary").out, ctx.run(d, "--account", OTHER, "--summary").out,
         "--account auto == --account alt for --summary")
    t.eq(ctx.run(d, "--account", "auto", "--batches").out, ctx.run(d, "--account", OTHER, "--batches").out,
         "--account auto == --account alt for --batches")
    # a plain run is not influenced by the key
    with_key = ctx.run(d).out
    data.pop("last_session_account")
    ctx.write_registry(d, data["artifacts"])
    t.eq(ctx.run(d).out, with_key, "default report ignores last_session_account")
    # the seal under the active account, or without --account, moves it back to the active account
    ctx.write_registry(d, data["artifacts"], extra={"last_session_account": OTHER})
    r = ctx.run(d, "--mark-published", "prompts.html", "https://example.com/a/prompts-corp-2", "V2")
    t.eq(r.rc, 0, "--mark-published without --account exit code")
    t.eq(ctx.load(d).get("last_session_account"), ACTIVE, "no --account: last_session_account == the active account")
    ctx.write_registry(d, data["artifacts"], extra={"last_session_account": OTHER})
    r = ctx.run(d, "--mark-published", "prompts.html", "https://example.com/a/prompts-corp-3", "V3", "--account", ACTIVE)
    t.eq(r.rc, 0, f"--mark-published --account {ACTIVE} exit code")
    t.eq(ctx.load(d).get("last_session_account"), ACTIVE, f"--account {ACTIVE}: last_session_account == {ACTIVE}")
    auto = ctx.run(d, "--account", "auto")
    t.has(auto.out, f"account: {ACTIVE} (auto)", "auto follows the key back to the active account")
    t.eq(table_rows(auto.out).get("prompts.html", {}).get("URL"), "https://example.com/a/prompts-corp-3",
         "auto == active: the table URL is the canonical url")
    # no active account known: no --account leaves the key out, --account NAME still writes it
    d = ctx.registry("c9b")
    ctx.write_registry(d, ctx.load(d)["artifacts"], active=None)
    r = ctx.run(d, "--mark-published", "plans.html", "https://example.com/a/plans-corp-2", "V2")
    t.eq(r.rc, 0, "--mark-published without any account known: exit code")
    t.ok("last_session_account" not in ctx.load(d), "no account known: last_session_account is not written")
    t.has(ctx.run(d, "--account", "auto").out, "account: not set (auto)", "auto with nothing known: header says not set")
    r = ctx.run(d, "--mark-published", "plans.html", "https://example.com/a/plans-alt-3", "V3", "--account", OTHER)
    t.eq(r.rc, 0, "--mark-published --account alt (no active account) exit code")
    t.eq(ctx.load(d).get("last_session_account"), OTHER, "--account alt: last_session_account written even without an active account")
    t.ok(not os.path.exists(os.path.join(d, LOCK)), "lock file removed")


def case_block_only_uses_session_account(ctx, t):
    d = ctx.registry("c10")
    default = ctx.run(d, "--block-only")
    t.eq(default.rc, 0, "default --block-only exit code")
    for f, u in CORP.items():
        t.has(default.out, u, f"default block shows the canonical url of {f}")
    t.eq(default.err, "", "default --block-only prints no warning")
    bo = ctx.run(d, "--block-only", "--account", OTHER)
    t.eq(bo.rc, 0, "--block-only --account alt exit code")
    lines = bo.out.splitlines()
    t.eq(len(lines), 3, "one line per row, the row without url_alt included")
    for f, u in ALT.items():
        t.has(bo.out, u, f"block shows url_alt of {f}")
        t.lacks(bo.out, CORP[f], f"block does not show the canonical url of {f}")
    t.has(bo.out, f"- [📄 Deck]({CORP['deck.html']})", "the row without url_alt prints its canonical url")
    t.has(bo.err, "deck.html has no url_alt", "stderr names the row that fell back to the canonical url")
    t.lacks(bo.err, "plans.html", "stderr does not name rows that have url_alt")
    # the default report's `=== LINKS ===` section follows the same rule
    full = ctx.run(d, "--account", OTHER)
    links = full.out.split("=== LINKS ===", 1)[1] if "=== LINKS ===" in full.out else ""
    t.eq(links.strip(), bo.out.strip(), "`=== LINKS ===` section == --block-only under --account alt")
    t.has(full.err, "deck.html has no url_alt", "default report: stderr names the canonical fallback row")
    t.lacks(full.out, "left out of the block", "default report: no row is left out while a canonical url exists")
    # a hidden row stays out of the block unless --include-hidden, and then also prints the alt url
    d = ctx.registry("c10b", tweak={"prompts.html": {"in_close_block": False}})
    t.lacks(ctx.run(d, "--block-only", "--account", OTHER).out, ALT["prompts.html"], "hidden row not in the block")
    hid = ctx.run(d, "--block-only", "--include-hidden", "--account", OTHER)
    t.has(hid.out, ALT["prompts.html"], "--include-hidden: the hidden row prints its url_alt")
    t.lacks(hid.out, CORP["prompts.html"], "--include-hidden: not its canonical url")
    t.has(hid.out, CORP["deck.html"], "--include-hidden: the row without url_alt prints its canonical url")
    # a row with neither url_alt nor url is still left out, with a warning
    d = ctx.registry("c10c", tweak={"deck.html": {"url": None}})
    bo = ctx.run(d, "--block-only", "--account", OTHER)
    t.eq(len(bo.out.splitlines()), 2, "a row with no url at all is left out of the block")
    t.has(bo.err, "deck.html has no url_alt, left out of the block", "stderr: left out, no url at all")
    # the session account recorded by the seal drives it: --account auto prints the same block
    d = ctx.registry("c10d")
    new = "https://example.com/a/plans-alt-2"
    t.eq(ctx.run(d, "--mark-published", "plans.html", new, "V2", "--account", OTHER).rc, 0, "seal under alt exit code")
    auto = ctx.run(d, "--block-only", "--account", "auto")
    t.has(auto.out, new, "auto block: the sealed url_alt")
    t.has(auto.out, ALT["prompts.html"], "auto block: the other url_alt")
    t.has(auto.out, CORP["deck.html"], "auto block: the canonical fallback")
    for f in ("plans.html", "prompts.html"):
        t.lacks(auto.out, CORP[f], f"auto block: not the canonical url of {f}")
    # under the active account nothing changes: every row prints `url`
    t.eq(ctx.run(d, "--block-only", "--account", ACTIVE).out, ctx.run(d, "--block-only").out,
         f"--account {ACTIVE} block == default block")


CASES = [
    ("default_uses_url_and_active_account_equals_default", case_default_uses_url_and_active_account_equals_default),
    ("account_selects_url_other_account", case_account_selects_url_other_account),
    ("mark_published_account", case_mark_published_account),
    ("set_active_account_swap", case_set_active_account_swap),
    ("per_account_stamps", case_per_account_stamps),
    ("account_alias_url_cuenta", case_account_alias_url_cuenta),
    ("missing_file_without_url_other_account", case_missing_file_without_url_other_account),
    ("set_active_account_family", case_set_active_account_family),
    ("last_session_account", case_last_session_account),
    ("block_only_uses_session_account", case_block_only_uses_session_account),
]


def run_case(fn, script, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="courier-preflight-selftest-"))
    t = Check()
    try:
        fn(Ctx(script, root), t)
        verdict, why = ("FAIL", "; ".join(p[:150] for p in t.problems[:8])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except Exception as exc:  # a broken harness or a crashing script is a failure, not a crash
        verdict, why = "FAIL", f"harness error: {exc!r}"
    finally:
        if keep:
            print(f"  kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for courier_preflight.py (per-account URLs)")
    ap.add_argument("--script", default=os.path.join(HERE, "courier_preflight.py"))
    ap.add_argument("--only", help="run a single case by name")
    ap.add_argument("--keep", action="store_true", help="leave the temp trees on disk")
    args = ap.parse_args()
    script = os.path.abspath(os.path.expanduser(args.script))
    if not os.path.isfile(script):
        print(f"script not found: {script}")
        return 2
    cases = [c for c in CASES if not args.only or c[0] == args.only]
    if not cases:
        print(f"unknown case {args.only!r}; known: {', '.join(n for n, _ in CASES)}")
        return 2
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, fn in cases:
        verdict, why = run_case(fn, script, args.keep)
        tally[verdict] += 1
        print(f"{verdict} {name}" + (f" — {why}" if why else ""))
    print(f"{tally['PASS']} PASS · {tally['FAIL']} FAIL · {tally['SKIP']} SKIP (of {len(cases)})")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
