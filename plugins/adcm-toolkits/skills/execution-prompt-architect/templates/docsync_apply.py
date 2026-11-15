#!/usr/bin/env python3
"""docsync_apply - deterministic applier of a doc-sync edit sheet (stdlib only, no git, no network).

Usage:
  docsync_apply.py --sheet FILE.json [--markers FILE.json] [--root DIR] (--check | --write) [--json]

Sheet: {"edits":[{"file","op","why", ...}]}. File paths are relative to --root (required unless
every path is absolute). Ops:
  sub           old, new, count=1, scope=<heading text>   exact-N substring replace
  tick          match, suffix=""                          '[ ]' -> '[x]' on the single matching line
  insert_before anchor, text                              lines before the single line holding anchor
  insert_after  anchor, text                              lines after it
  append_rows   anchor (table header row or heading), text   rows at the end of that table
  logbook       heading, text                             entry as the newest one, in the file's order
Every op takes an optional `scope` (heading text) except logbook. An op whose result is already in
place is `ok (already applied)`. Placeholders `{{NAME}}` resolve from --markers; unresolved ones are
`open`: --check tolerates them, --write refuses unless failed = 0 and open = 0. A line an op
introduces that is longer than 300 chars is a failure. --check never writes; --write is all or
nothing. --json prints one JSON line, then the summary line.
Last line: `DOCSYNC: <n> ok · <n> failed · <n> open placeholders`. Exit 0 · 1 · 64 (usage).
"""
import argparse
import collections
import json
import os
import re
import shutil
import sys
import tempfile

LINT_MAX = 300
PH = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
HEAD = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
TEXT_FIELDS = ("old", "new", "text", "suffix", "match", "anchor", "scope", "heading")
SEARCH_FIELDS = ("old", "match", "anchor", "scope", "heading")


class Fail(Exception):
    pass


class Usage(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


# ---------------------------------------------------------------- helpers
def headings(lines):
    """[(index, level, title)] outside code fences."""
    out, fence = [], False
    for i, l in enumerate(lines):
        if l.lstrip().startswith("```"):
            fence = not fence
            continue
        m = None if fence else HEAD.match(l)
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def find_heading(lines, name):
    want = re.sub(r"^#+\s*", "", name).strip()
    hs = headings(lines)
    hit = [h for h in hs if h[2] == want] or [h for h in hs if h[2].startswith(want)]
    if len(hit) != 1:
        raise Fail("heading %r matches %d times (expected 1)" % (name, len(hit)))
    i, lvl, _ = hit[0]
    end = len(lines)
    for j, l2, _t in hs:
        if j > i and l2 <= lvl:
            end = j
            break
    return i, end, lvl


def scope_range(lines, e):
    if e.get("scope"):
        a, b, _ = find_heading(lines, e["scope"])
        return a, b
    return 0, len(lines)


def block(text):
    t = text[:-1] if text.endswith("\n") else text
    return t.split("\n")


def need(e, *names):
    for n in names:
        if not isinstance(e.get(n), str) or (e[n] == "" and n not in ("suffix", "new")):
            raise Fail("missing or empty field %r" % n)


def anchors(lines, a, b, anchor):
    return [i for i in range(a, b) if anchor in lines[i]]


def has_at(lines, pos, blk):
    return pos >= 0 and lines[pos:pos + len(blk)] == blk


# ---------------------------------------------------------------- ops
# each op takes (lines, e) and returns (lines, detail) or (None, detail) when already applied
def op_sub(lines, e):
    need(e, "old", "new")
    expected = e.get("count", 1)
    if not isinstance(expected, int) or expected < 1:
        raise Fail("count must be an int >= 1")
    a, b = scope_range(lines, e)
    tail = b < len(lines)
    seg = "\n".join(lines[a:b]) + ("\n" if tail else "")
    n = seg.count(e["old"])
    if e["new"] and e["old"] in e["new"] and seg.count(e["new"]) >= expected:
        return None, "already applied"
    if n != expected:  # MUTATION-KEY: match-count
        if n == 0 and e["new"] and seg.count(e["new"]) >= expected:
            return None, "already applied"
        raise Fail("%d match(es) of old, expected %d" % (n, expected))
    seg2 = seg.replace(e["old"], e["new"])
    if seg2.endswith("\n") and tail:
        seg2 = seg2[:-1]
    return lines[:a] + seg2.split("\n") + lines[b:], "%d replaced" % n


def op_tick(lines, e):
    need(e, "match")
    a, b = scope_range(lines, e)
    box = re.compile(r"\[( |x|X)\]")
    hit = [i for i in range(a, b) if e["match"] in lines[i] and box.search(lines[i])]
    open_ = [i for i in hit if "[ ]" in lines[i]]
    if len(open_) == 1 and len(hit) == 1:
        i = open_[0]
        out = list(lines)
        out[i] = lines[i].replace("[ ]", "[x]", 1) + e.get("suffix", "")
        return out, "line %d ticked" % (i + 1)
    if not open_ and len(hit) == 1:
        return None, "already applied"
    raise Fail("%d match(es) for %r among checkbox lines (%d unchecked), expected exactly 1" % (len(hit), e["match"], len(open_)))


def op_insert(lines, e, after):
    need(e, "anchor", "text")
    a, b = scope_range(lines, e)
    hit = anchors(lines, a, b, e["anchor"])
    blk = block(e["text"])
    for i in hit:
        if has_at(lines, i + 1 if after else i - len(blk), blk):
            return None, "already applied"
    if len(hit) != 1:
        raise Fail("%d match(es) for anchor %r, expected exactly 1" % (len(hit), e["anchor"]))
    p = hit[0] + (1 if after else 0)
    return lines[:p] + blk + lines[p:], "%d line(s) at line %d" % (len(blk), p + 1)


def table_end(lines, start, limit):
    j = start
    while j < limit and lines[j].lstrip().startswith("|"):
        j += 1
    return j


def op_append_rows(lines, e):
    need(e, "anchor", "text")
    a, b = scope_range(lines, e)
    hit = [i for i in range(a, b) if e["anchor"] in lines[i] and (lines[i].lstrip().startswith("|") or HEAD.match(lines[i]))]
    if len(hit) != 1:
        raise Fail("%d match(es) for table header/heading %r, expected exactly 1" % (len(hit), e["anchor"]))
    i = hit[0]
    if HEAD.match(lines[i]):
        _a, end, _l = find_heading(lines, lines[i])
        t0 = next((k for k in range(i + 1, end) if lines[k].lstrip().startswith("|")), None)
        if t0 is None:
            raise Fail("no table under heading %r" % e["anchor"])
    else:
        t0 = i
    t1 = table_end(lines, t0, len(lines))
    have = {l.strip() for l in lines[t0:t1]}
    rows = [r for r in block(e["text"]) if r.strip() not in have]
    if not rows:
        return None, "already applied"
    return lines[:t1] + rows + lines[t1:], "%d row(s) after line %d" % (len(rows), t1)


def op_logbook(lines, e):
    need(e, "heading", "text")
    blk = block(e["text"])
    first = next((l.strip() for l in blk if l.strip()), "")
    a, b, lvl = find_heading(lines, e["heading"])
    if any(l.strip() == first for l in lines[a:b]):
        return None, "already applied"
    entries = [i for i, l, _t in headings(lines) if a < i < b and l == lvl + 1]
    titles = [lines[i] for i in entries]
    if len(entries) >= 2 and titles[0] > titles[1]:
        return lines[:entries[0]] + blk + [""] + lines[entries[0]:], "newest entry first"
    p = b
    while p > a + 1 and lines[p - 1].strip() == "":
        p -= 1
    return lines[:p] + [""] + blk + lines[p:], "newest entry last"


OPS = {"sub": op_sub, "tick": op_tick, "append_rows": op_append_rows, "logbook": op_logbook,
       "insert_before": lambda l, e: op_insert(l, e, False), "insert_after": lambda l, e: op_insert(l, e, True)}


# ---------------------------------------------------------------- engine
def resolve(e, markers):
    out, openn, search_open = dict(e), 0, False
    for f in TEXT_FIELDS:
        if isinstance(e.get(f), str):
            def sub(m):
                nonlocal openn, search_open
                if m.group(1) in markers:
                    return str(markers[m.group(1)])
                openn += 1
                search_open = search_open or f in SEARCH_FIELDS
                return m.group(0)
            out[f] = PH.sub(sub, e[f])
    return out, openn, search_open


def load_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as ex:
        raise Fail("not valid UTF-8 (%s)" % ex.reason)
    crlf = text.count("\r\n") > text.count("\n") - text.count("\r\n")
    return text.replace("\r\n", "\n"), crlf


def process(sheet, markers, root):
    res, files, order, bad = [], {}, [], {}
    for idx, raw in enumerate(sheet["edits"]):
        r = {"index": idx, "file": "?", "op": "?", "why": "", "status": "ok", "detail": "", "open": 0}
        res.append(r)
        try:
            if not isinstance(raw, dict):
                raise Fail("edit is not an object")
            e, r["open"], search_open = resolve(raw, markers)
            r.update(file=str(e.get("file", "?")), op=str(e.get("op", "?")), why=str(e.get("why", "")))
            if e.get("op") not in OPS:
                raise Fail("unknown op %r" % e.get("op"))
            need(e, "file")
            path = e["file"] if os.path.isabs(e["file"]) else os.path.join(root, e["file"])
            if path in bad:
                raise Fail(bad[path])
            if path not in files:
                try:
                    files[path] = load_file(path) + (None,)
                except OSError as ex:
                    raise Fail("cannot read file (%s)" % ex.strerror)
                except Fail as ex:
                    bad[path] = str(ex)
                    raise
                order.append(path)
            if search_open:
                r["status"], r["detail"] = "open", "placeholder in a search field, op not evaluated"
                continue
            text, crlf, cur = files[path]
            lines = (cur if cur is not None else text.split("\n"))
            new, detail = OPS[e["op"]](lines, e)
            if new is None:
                r["detail"] = detail
                continue
            before = collections.Counter(lines)
            for l, c in (collections.Counter(new) - before).items():
                if len(l) > LINT_MAX:  # MUTATION-KEY: lint-threshold
                    raise Fail("introduces a line of %d chars (max %d)" % (len(l), LINT_MAX))
            files[path] = (text, crlf, new)
            r["detail"] = detail
        except Fail as ex:
            r["status"], r["detail"] = "failed", str(ex)
    return res, files, order


def render(res):
    for r in res:
        if r["status"] == "failed":
            yield "FAIL %s #%d %s (%s): %s" % (r["file"], r["index"], r["op"], r["why"], r["detail"])
        elif r["status"] == "open":
            yield "OPEN %s #%d %s (%s): %s" % (r["file"], r["index"], r["op"], r["why"], r["detail"])
        else:
            tag = "ok (already applied)" if r["detail"] == "already applied" else "ok"
            extra = "" if r["detail"] == "already applied" else " - " + r["detail"]
            yield "%s %s #%d %s%s%s" % (tag, r["file"], r["index"], r["op"], extra,
                                          " [%d open placeholder(s)]" % r["open"] if r["open"] else "")


def write_all(files, order):
    temps = []
    try:
        for path in order:
            text, crlf, cur = files[path]
            if cur is None:
                continue
            body = "\n".join(cur)
            if crlf:
                body = body.replace("\n", "\r\n")
            fd, tmp = tempfile.mkstemp(prefix=".docsync-", dir=os.path.dirname(path) or ".")
            temps.append((tmp, path))
            with os.fdopen(fd, "wb") as f:
                f.write(body.encode("utf-8"))
            shutil.copymode(path, tmp)
        for tmp, path in temps:
            os.replace(tmp, path)
    except OSError:
        for tmp, _p in temps:
            if os.path.exists(tmp):
                os.remove(tmp)
        raise


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as ex:
        raise Usage("cannot read %s %s: %s" % (what, path, ex))


def main(argv):
    ap = Parser(prog="docsync-apply", add_help=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--markers")
    ap.add_argument("--root")
    ap.add_argument("--json", action="store_true")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    sheet = load_json(a.sheet, "sheet")
    if not isinstance(sheet, dict) or not isinstance(sheet.get("edits"), list):
        raise Usage('sheet must be {"edits": [...]}')
    markers = load_json(a.markers, "markers") if a.markers else {}
    if not isinstance(markers, dict):
        raise Usage("markers must be a JSON object")
    if not a.root and not all(isinstance(e, dict) and os.path.isabs(str(e.get("file", ""))) for e in sheet["edits"]):
        raise Usage("--root is required unless every path is absolute")
    res, files, order = process(sheet, markers, os.path.abspath(a.root) if a.root else "")
    ok = sum(1 for r in res if r["status"] == "ok")
    failed = sum(1 for r in res if r["status"] == "failed")
    openn = sum(r["open"] for r in res)
    write = a.write
    deltas = []
    wrote = False
    if write:
        if failed or (write and openn):  # MUTATION-KEY: write-gate
            pass
        else:
            write_all(files, order)
            wrote = True
        for p in order:
            text, _c, cur = files[p]
            if cur is not None:
                deltas.append((p, text.count("\n"), "\n".join(cur).count("\n")))
    line = "DOCSYNC: %d ok · %d failed · %d open placeholders" % (ok, failed, openn)
    if a.json:
        print(json.dumps({"ok": ok, "failed": failed, "open": openn, "mode": "write" if write else "check",
                          "wrote": wrote, "results": res,
                          "deltas": [{"file": p, "before": x, "after": y} for p, x, y in deltas]}, ensure_ascii=False))
    else:
        for s in render(res):
            print(s)
        for p, x, y in deltas:
            print("%s: %d -> %d lines (%+d)%s" % (os.path.relpath(p, a.root) if a.root else p, x, y, y - x,
                                                  "" if wrote else " [not written]"))
        if write and not wrote:
            print("REFUSED: --write needs 0 failed and 0 open placeholders; no file was touched")
    print(line)
    return 1 if (failed or (write and openn)) else 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Usage as ex:
        print("docsync-apply: usage: %s" % ex, file=sys.stderr)
        print("DOCSYNC: 0 ok · 0 failed · 0 open placeholders")
        sys.exit(64)
    except SystemExit:
        raise
    except BaseException as ex:  # bad input never crashes
        print("docsync-apply: %s: %s" % (type(ex).__name__, ex), file=sys.stderr)
        sys.exit(64)
