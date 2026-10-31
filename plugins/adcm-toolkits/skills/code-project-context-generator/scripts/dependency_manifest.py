#!/usr/bin/env python3
"""Dependency manifest of a code project (stdlib only, Python 3.8+).

dependency_manifest(root) reads the dependency files of a project and returns one JSON-able dict with
17 fixed keys: package manager, lockfiles, workspaces, pnpm catalogs, declared and locked packages,
overrides, patches, install-script policy, whitelisted .npmrc keys, runtime pins from every source,
update bots, CI images/actions/pins, Docker bases, verification commands, other ecosystems and notes.

The module reports facts and the file each one came from. It never runs a package manager, never picks
a runtime and never copies a credential into its output. The result is deterministic (sorted lists, no
clock, no network, no subprocess) and bounded (files at most four directory levels deep, skipping the
directories it is given, or DEFAULT_SKIP, the standalone fallback mirror of the cpcg scanner's skip set).

API
  MANIFEST_FORMAT = 1
  dependency_manifest(root, skip_dirs=None) -> dict
  attach_dependency_manifest(root, result, skip_dirs=None) -> None   hook of the cpcg scanner
  dependency_update_targets(paths) -> [{file, [sections,] paths}]   context files a changed path touches
"""
import copy
import fnmatch
import json
import os
import re
import shlex
from urllib.parse import urlsplit

try:
    import tomllib
except ImportError:  # Python < 3.11: TOML manifests are reported as not parsed
    tomllib = None

MANIFEST_FORMAT = 1

MAX_DEPTH = 4
DOCKER_DEPTH = 3
MAX_BYTES = 64 * 1024 * 1024
ALIAS_BUDGET = 200000
# The directories a run without skip_dirs leaves out: the ones the cpcg scanner skips, so both walk the same tree.
DEFAULT_SKIP = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "vendor", "bower_components",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env", ".env.d",
    "dist", "build", "out", "target", ".next", ".nuxt", ".svelte-kit",
    "coverage", ".nyc_output",
    ".idea", ".vscode", ".vs",
    "storage", "tmp", "temp",
    ".terraform",
    ".gradle", ".m2",
    "DerivedData",
})
DOT_DIRS = (".github", ".gitlab")
PARENT = os.pardir + "/"


# ---------------------------------------------------------------------------
# YAML subset: block mappings and sequences, flow collections on any number of lines, quoted and
# plain scalars, block scalars (| and >), anchors, aliases and merge keys. Comments are kept: the
# optional `comments` dict maps a key/index path to the text above and after that entry.
# ---------------------------------------------------------------------------

_BLOCK_HEAD = re.compile(r"^[|>][+-]?[0-9]?[+-]?$")
_PROP = re.compile(r"^(&[A-Za-z0-9_.-]+|![^\s]*)(?:\s+|$)")
_ALIAS = re.compile(r"^\*([A-Za-z0-9_.-]+)$")
_KEY = re.compile(r"^(.+?):(?:\s+(.*))?$")
_QUOTED_AFTER = re.compile(r"^\s*:(?:\s+(.*))?$")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/"}


class _Ln(object):
    __slots__ = ("indent", "text", "above", "inline", "block")

    def __init__(self, indent, text, above, inline):
        self.indent, self.text, self.above, self.inline, self.block = indent, text, above, inline, None


def _split_comment(s):
    """(content, comment): a '#' after whitespace and outside quotes starts the comment."""
    quote = None
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                if quote == "'" and s[i + 1:i + 2] == "'":
                    i += 2
                    continue
                quote = None
        elif ch in "\"'" and (i == 0 or s[i - 1] in " \t[{,"):
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip(), s[i + 1:].strip()
        i += 1
    return s.rstrip(), ""


def _read_quoted(s, i):
    quote = s[i]
    i += 1
    out = []
    n = len(s)
    while i < n:
        ch = s[i]
        if quote == '"' and ch == "\\" and i + 1 < n:
            out.append(_ESCAPES.get(s[i + 1], "\\" + s[i + 1]))
            i += 2
            continue
        if ch == quote:
            if quote == "'" and s[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    return "".join(out), i


def _plain(text):
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if text in ("", "null", "Null", "NULL", "~"):
        return None
    return text


def _scalar_text(text):
    text = text.strip()
    if text[:1] in ("'", '"'):
        return _read_quoted(text, 0)[0]
    return _plain(text)


def _is_seq(text):
    return text == "-" or text.startswith("- ")


def _split_key(text):
    """(key, rest-of-line) when the line is a mapping entry, else None."""
    if not text or text[0] in "[{|>":
        return None
    if text[0] in "\"'":
        key, end = _read_quoted(text, 0)
        m = _QUOTED_AFTER.match(text[end:])
        return (key, (m.group(1) or "").strip()) if m else None
    m = _KEY.match(text)
    if not m or '"' in m.group(1) or "'" in m.group(1):
        return None
    return m.group(1).strip(), (m.group(2) or "").strip()


def _brackets(text, depth=0, quote=None):
    """(depth, open quote) after `text`; a later line of the same scalar resumes from the state it returns."""
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'" and (i == 0 or text[i - 1] in " \t[{,:"):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
    return depth, quote


def _skip_ws(s, i):
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _flow_scalar(s, i):
    if s[i] in "\"'":
        return _read_quoted(s, i)
    n = len(s)
    j = i
    while j < n and s[j] not in ",]}" and not (s[j] == ":" and (j + 1 >= n or s[j + 1] in " \t,]}")):
        j += 1
    return _plain(s[i:j].strip()), j


def _flow_value(s, i):
    n = len(s)
    i = _skip_ws(s, i)
    if i >= n:
        return None, i
    if s[i] == "[":
        items = []
        i += 1
        while True:
            i = _skip_ws(s, i)
            if i >= n:
                return items, i
            if s[i] == "]":
                return items, i + 1
            if s[i] == ",":
                i += 1
                continue
            start = i
            val, i = _flow_value(s, i)
            i = _skip_ws(s, i)
            if i < n and s[i] == ":":
                nxt, i = _flow_value(s, i + 1)
                val = {str(val): nxt}
            elif i == start:
                i += 1
                continue
            items.append(val)
    if s[i] == "{":
        out = {}
        i += 1
        while True:
            i = _skip_ws(s, i)
            if i >= n:
                return out, i
            if s[i] == "}":
                return out, i + 1
            if s[i] == ",":
                i += 1
                continue
            start = i
            key, i = _flow_scalar(s, i)
            i = _skip_ws(s, i)
            val = None
            if i < n and s[i] == ":":
                val, i = _flow_value(s, i + 1)
            elif i == start:
                i += 1
                continue
            out[str(key)] = val
    return _flow_scalar(s, i)


def _block_head(content):
    """(owner offset, folded) when the line ends with a block-scalar indicator, else None."""
    toks = content.split()
    if len(toks) < 2 or not _BLOCK_HEAD.match(toks[-1]):
        return None
    if toks[-2] != "-" and not toks[-2].endswith(":"):
        return None
    dashes = re.match(r"^((?:-\s+)*)", content).group(1)
    if content[len(dashes):] == toks[-1]:
        last = re.search(r"-\s+$", dashes).group(0)
        return len(dashes) - len(last), toks[-1][0] == ">"
    return len(dashes), toks[-1][0] == ">"


def _block_text(rows, folded):
    while rows and not rows[-1].strip():
        rows.pop()
    pad = None
    for row in rows:
        if row.strip():
            pad = len(row) - len(row.lstrip(" "))
            break
    if pad is None:
        return ""
    rows = [row[pad:] if row.strip() else "" for row in rows]
    if not folded:
        return "\n".join(rows)
    out, cur = [], []
    for row in rows:
        if row:
            cur.append(row.strip())
        else:
            if cur:
                out.append(" ".join(cur))
                cur = []
            out.append("")
    if cur:
        out.append(" ".join(cur))
    return "\n".join(out)


def _logical_lines(text):
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, above = [], []
    i, n = 0, len(raw)
    while i < n:
        line = raw[i]
        i += 1
        body = line.lstrip(" \t")
        if not body.strip():
            above = []
            continue
        if body.startswith("#"):
            above.append(body.lstrip("#").strip())
            continue
        if body.strip() in ("---", "..."):
            above = []
            continue
        if "\t" in line[:len(line) - len(body)]:
            # A tab cannot indent YAML; failing the file leaves a note, reading on would drop its entries unseen.
            raise ValueError("tab in indentation")
        indent = len(line) - len(body)
        content, inline = _split_comment(body.rstrip())
        ln = _Ln(indent, content, above, inline)
        above = []
        head = _block_head(content)
        if head:
            owner, folded = indent + head[0], head[1]
            rows = []
            while i < n:
                nxt = raw[i]
                if not nxt.strip():
                    rows.append("")
                    i += 1
                    continue
                if len(nxt) - len(nxt.lstrip(" ")) <= owner:
                    break
                rows.append(nxt)
                i += 1
            ln.block = _block_text(rows, folded)
        out.append(ln)
    return out


def _size(value):
    if isinstance(value, dict):
        return 1 + sum(_size(v) for v in value.values())
    if isinstance(value, list):
        return 1 + sum(_size(v) for v in value)
    return 1


class _Yaml(object):
    def __init__(self, lines, comments):
        self.lines, self.comments, self.anchors, self.i = lines, comments, {}, 0
        self.budget = ALIAS_BUDGET

    def alias(self, name):
        value = self.anchors[name]
        self.budget -= _size(value)
        if self.budget < 0:
            raise ValueError("alias expansion too large")
        return copy.deepcopy(value)

    def peek(self):
        return self.lines[self.i] if self.i < len(self.lines) else None

    def note(self, path, ln):
        if self.comments is None:
            return
        parts = [c for c in ln.above if c]
        if ln.inline:
            parts.append(ln.inline)
        if parts:
            self.comments[path] = " ".join(parts)

    def props(self, text):
        anchor = None
        while text:
            m = _PROP.match(text)
            if not m:
                break
            if m.group(1).startswith("&"):
                anchor = m.group(1)[1:]
            text = text[m.end():]
        return anchor, text

    def scalar(self, text, ln):
        alias = _ALIAS.match(text)
        if alias and alias.group(1) in self.anchors:
            return self.alias(alias.group(1))
        if ln.block is not None and _BLOCK_HEAD.match(text):
            return ln.block
        if text[0] in "[{":
            parts, (depth, quote) = [text], _brackets(text)
            while depth > 0 and self.i < len(self.lines):
                parts.append(self.lines[self.i].text)
                depth, quote = _brackets(" " + parts[-1], depth, quote)
                self.i += 1
            if depth > 0:
                raise ValueError("unterminated flow collection")
            return _flow_value(" ".join(parts), 0)[0]
        return _scalar_text(text)

    def continued(self, val, indent):
        while self.i < len(self.lines) and self.lines[self.i].indent > indent:
            if isinstance(val, str):
                val = val + " " + self.lines[self.i].text
            self.i += 1
        return val

    def parse(self):
        return self.node(()) if self.lines else None

    def node(self, path):
        ln = self.lines[self.i]
        if _is_seq(ln.text):
            return self.seq(ln.indent, path)
        if _split_key(ln.text) is not None:
            return self.mapping(ln.indent, path)
        self.i += 1
        anchor, rest = self.props(ln.text)
        val = self.scalar(rest, ln) if rest else None
        if anchor:
            self.anchors[anchor] = val
        return val

    def seq(self, indent, path):
        out = []
        while self.i < len(self.lines):
            ln = self.lines[self.i]
            if ln.indent != indent or not _is_seq(ln.text):
                break
            rest = ln.text[1:].lstrip(" ")
            p = path + (len(out),)
            self.note(p, ln)
            if not rest:
                self.i += 1
                nxt = self.peek()
                out.append(self.node(p) if nxt is not None and nxt.indent > indent else None)
            elif _is_seq(rest) or _split_key(rest) is not None:
                ln.indent, ln.text = indent + len(ln.text) - len(rest), rest
                out.append(self.node(p))
            else:
                self.i += 1
                anchor, rest = self.props(rest)
                if rest:
                    val = self.continued(self.scalar(rest, ln), indent)
                else:
                    nxt = self.peek()
                    val = self.node(p) if nxt is not None and nxt.indent > indent else None
                if anchor:
                    self.anchors[anchor] = val
                out.append(val)
        return out

    def mapping(self, indent, path):
        out, merges = {}, []
        while self.i < len(self.lines):
            ln = self.lines[self.i]
            kv = _split_key(ln.text) if ln.indent == indent else None
            if kv is None:
                break
            key, rest = kv
            p = path + (key,)
            self.note(p, ln)
            self.i += 1
            anchor, rest = self.props(rest)
            if rest:
                val = self.continued(self.scalar(rest, ln), indent)
            else:
                nxt = self.peek()
                nested = nxt is not None and (nxt.indent > indent or (nxt.indent == indent and _is_seq(nxt.text)))
                val = self.node(p) if nested else None
            if anchor:
                self.anchors[anchor] = val
            if key == "<<":
                merges.append(val)
            else:
                out[key] = val
        for merged in merges:
            for src in (merged if isinstance(merged, list) else [merged]):
                if isinstance(src, dict):
                    for k, v in src.items():
                        out.setdefault(k, v)
        return out


def yaml_load(text, comments=None):
    """Parse the YAML subset; None for an empty document. Raises on input it cannot make sense of."""
    return _Yaml(_logical_lines(text), comments).parse()


# ---------------------------------------------------------------------------
# Project files
# ---------------------------------------------------------------------------

def _base(rel):
    return rel.rsplit("/", 1)[-1]


def _dir(rel):
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _join(ws, name):
    return name if ws == "." else ws + "/" + name


class _Ctx(object):
    def __init__(self, root, skip_dirs):
        self.root = os.path.realpath(str(root))
        self.skip = frozenset(skip_dirs) if skip_dirs is not None else DEFAULT_SKIP
        self.notes = set()
        self._cache = {}
        self.files = self._walk()
        self.names = set(self.files)

    def _walk(self):
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel = os.path.relpath(dirpath, self.root)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in self.skip and (not d.startswith(".") or d in DOT_DIRS))
            if depth >= MAX_DEPTH:
                dirnames[:] = []
            prefix = "" if rel == "." else rel.replace(os.sep, "/") + "/"
            out.extend(prefix + f for f in filenames)
        return sorted(out)

    def note(self, message):
        self.notes.add(message)

    def text(self, rel):
        key = ("text", rel)
        if key not in self._cache:
            self._cache[key] = self._read(rel)
        return self._cache[key]

    def _read(self, rel):
        if rel not in self.names:
            return None
        real = os.path.realpath(os.path.join(self.root, *rel.split("/")))
        if real != self.root and not real.startswith(self.root + os.sep):
            return None
        try:
            if os.path.getsize(real) > MAX_BYTES:
                return None
            with open(real, "r", encoding="utf-8-sig", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None

    def json(self, rel):
        key = ("json", rel)
        if key not in self._cache:
            data, text = None, self.text(rel)
            if text is not None:
                try:
                    data = json.loads(text)
                except ValueError:
                    self.note("unparsed %s (invalid JSON)" % rel)
            self._cache[key] = data if isinstance(data, dict) else None
        return self._cache[key]

    def yaml(self, rel):
        """(data, comments) of a YAML file; (None, {}) when it is missing or unreadable."""
        key = ("yaml", rel)
        if key not in self._cache:
            data, comments, text = None, {}, self.text(rel)
            if text is not None:
                try:
                    data = yaml_load(text, comments)
                except Exception:
                    data = None
                    self.note("unparsed %s (invalid YAML)" % rel)
            self._cache[key] = (data, comments)
        return self._cache[key]

    def toml(self, rel):
        key = ("toml", rel)
        if key not in self._cache:
            data, text = None, self.text(rel)
            if text is not None:
                if tomllib is None:
                    self.note("%s not parsed (tomllib needs Python 3.11)" % rel)
                else:
                    try:
                        data = tomllib.loads(text)
                    except ValueError:
                        self.note("unparsed %s (invalid TOML)" % rel)
            self._cache[key] = data if isinstance(data, dict) else None
        return self._cache[key]

    def requirements(self):
        return [f for f in self.files if "/" not in f and fnmatch.fnmatchcase(f, "requirements*.txt")]


def _dict(value):
    return value if isinstance(value, dict) else {}


def _strs(value):
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


# The userinfo of a URL may hold @, /, ? or #. A dotted host or localhost followed by a path keeps every later @ for
# the path (scoped package, git ref); any other prefix is credentials, up to the last @ of the token.
_HOST = r"(?:(?:[a-z0-9-]+\.)+[a-z0-9-]+|localhost)(?::\d*)?(?=[/?#\s]|$)"
_URL_USERINFO = re.compile(r"(://)(?:[^/?#\s]*@|(?!%s|/)(?:(?!://)\S)*[^\s/]@)" % _HOST, re.I)


def _mask_userinfo(text):
    """`text` with the userinfo of every scheme://userinfo@host replaced by ***; other values pass through."""
    return _URL_USERINFO.sub(r"\1***@", text) if isinstance(text, str) else text


def _guard(c, label, fn, default):
    try:
        return fn()
    except Exception as exc:
        c.note("section %s failed (%s)" % (label, type(exc).__name__))
        return default


# ---------------------------------------------------------------------------
# Lockfiles and package manager
# ---------------------------------------------------------------------------

LOCK_TYPES = {"package-lock.json": "package-lock", "npm-shrinkwrap.json": "npm-shrinkwrap",
              "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "bun.lock": "bun", "bun.lockb": "bun",
              "composer.lock": "composer", "poetry.lock": "poetry", "Pipfile.lock": "pipfile"}
LOCK_MANAGER = {"package-lock": "npm", "npm-shrinkwrap": "npm", "pnpm": "pnpm", "yarn": "yarn", "bun": "bun",
                "composer": "composer", "poetry": "poetry", "pipfile": "pip"}
ECOSYSTEM = {"npm": "node", "pnpm": "node", "yarn": "node", "bun": "node", "composer": "php",
             "poetry": "python", "pip": "python"}


def _lock_version(c, rel, kind):
    if rel.endswith(".lockb"):
        return None
    text = c.text(rel) or ""
    if kind in ("package-lock", "npm-shrinkwrap"):
        value = _dict(c.json(rel)).get("lockfileVersion")
    elif kind == "pipfile":
        value = _dict(_dict(c.json(rel)).get("_meta")).get("pipfile-spec")
    else:
        pattern = {"pnpm": r"^lockfileVersion:\s*['\"]?([^'\"\s#]+)", "bun": r'"lockfileVersion"\s*:\s*(\d+)',
                   "poetry": r'^lock-version\s*=\s*"([^"]+)"'}.get(kind)
        if kind == "yarn":
            return "berry" if re.search(r"^__metadata:", text, re.M) else ("1" if "yarn lockfile v1" in text else None)
        found = re.search(pattern, text, re.M) if pattern else None
        value = found.group(1) if found else None
    return None if value is None else str(value)


def _lockfiles(c):
    return [{"path": rel, "type": LOCK_TYPES[_base(rel)], "version": _lock_version(c, rel, LOCK_TYPES[_base(rel)])}
            for rel in c.files if _base(rel) in LOCK_TYPES]


def _package_manager(c, locks):
    by_manager = {}
    for lock in locks:
        if "/" not in lock["path"]:
            by_manager.setdefault(LOCK_MANAGER[lock["type"]], []).append(lock["path"])
    for eco in ("node", "php", "python"):
        found = sorted(m for m in by_manager if ECOSYSTEM[m] == eco)
        if len(found) > 1:
            c.note("conflicting lockfiles: " + ", ".join(sorted(p for m in found for p in by_manager[m])))
    declared = _dict(c.json("package.json")).get("packageManager")
    if isinstance(declared, str):
        m = re.match(r"^(npm|pnpm|yarn|bun)@([^+\s]+)", declared)
        if m:
            node_locks = sorted(p for mgr, paths in by_manager.items() if ECOSYSTEM[mgr] == "node" for p in paths)
            if node_locks and m.group(1) not in by_manager:
                c.note("packageManager says %s but the root lockfile is %s" % (m.group(1), ", ".join(node_locks)))
            return {"name": m.group(1), "version": m.group(2), "source": "packageManager"}
        c.note("unrecognised packageManager value in package.json")
    for mgr in ("pnpm", "yarn", "bun", "npm", "composer", "poetry", "pip"):
        if mgr in by_manager:
            return {"name": mgr, "version": None, "source": "lockfile"}
    name = None
    if "package.json" in c.names:
        name = "npm"
    elif "composer.json" in c.names:
        name = "composer"
    elif "pyproject.toml" in c.names:
        name = "poetry" if "[tool.poetry]" in (c.text("pyproject.toml") or "") else "pip"
    elif "Pipfile" in c.names or c.requirements():
        name = "pip"
    return {"name": name, "version": None, "source": "manifest" if name else "none"}


# ---------------------------------------------------------------------------
# Workspaces and catalogs
# ---------------------------------------------------------------------------

def _glob_re(pattern):
    pattern = pattern.strip()
    while pattern.startswith("./"):
        pattern = pattern[2:]
    pattern = pattern.strip("/")
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _workspaces(c):
    declared = _dict(c.json("package.json")).get("workspaces")
    patterns = _strs(declared.get("packages") if isinstance(declared, dict) else declared)
    patterns += _strs(_dict(c.yaml("pnpm-workspace.yaml")[0]).get("packages"))
    has_root = any(f in c.names for f in ("package.json", "composer.json", "pyproject.toml", "Pipfile")) \
        or bool(c.requirements())
    if not has_root:
        return []
    include = [_glob_re(p) for p in patterns if not p.startswith("!")]
    exclude = [_glob_re(p[1:]) for p in patterns if p.startswith("!")]
    found = set()
    for rel in c.files:
        if _base(rel) == "package.json" and "/" in rel:
            folder = _dir(rel)
            if any(r.match(folder) for r in include) and not any(r.match(folder) for r in exclude):
                found.add(folder)
    return ["."] + sorted(found)


def _catalogs(c):
    data, comments = c.yaml("pnpm-workspace.yaml")
    found = {}

    def take(name, entries, base):
        if isinstance(entries, dict):
            bucket = found.setdefault(name, {})
            for dep in sorted(entries):
                if isinstance(entries[dep], str):
                    bucket[dep] = {"spec": _mask_userinfo(entries[dep]), "comment": comments.get(base + (dep,))}

    data = _dict(data)
    take("default", data.get("catalog"), ("catalog",))
    named = _dict(data.get("catalogs"))
    for name in sorted(named):
        take(name, named[name], ("catalogs", name))
    return {k: found[k] for k in (["default"] if "default" in found else []) + sorted(k for k in found if k != "default")}


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------

DEP_GROUPS = (("prod", "dependencies"), ("dev", "devDependencies"), ("peer", "peerDependencies"),
              ("optional", "optionalDependencies"))
_EXACT = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]*)?$")
_SCHEME = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|git@)")
_SHORTHAND = re.compile(r"^[\w.-]+/[\w.-]+(?:#\S*)?$")


def _style(spec):
    s = (spec or "").strip()
    if s.startswith("catalog:"):
        return "catalog"
    if s.startswith("workspace:"):
        return "workspace"
    if s.startswith("npm:"):
        return "alias"
    if _SCHEME.match(s) or _SHORTHAND.match(s):
        return "url"
    if not s or s in ("*", "x", "X"):
        return "range"
    if _EXACT.match(s):
        return "exact"
    if re.match(r"^[A-Za-z][\w.-]*$", s):
        return "tag"
    return "range" if re.match(r"^[\^~<>=v\d|*xX. -]", s) else "other"


def _py_style(spec):
    if not spec:
        return "other"
    if _SCHEME.match(spec):
        return "url"
    return "exact" if re.match(r"^===?\s*[^\s,*]+$", spec) else "range"


def _catalog_name(spec):
    if not spec.startswith("catalog:"):
        return None
    return spec[len("catalog:"):].strip() or "default"


def _cut_peer(version):
    version = version.split("(", 1)[0]
    m = re.match(r"^(\d[^_]*)_", version)
    return m.group(1) if m else version


_PNPM_KEEP = frozenset({"lockfileVersion", "settings", "importers", "dependencies", "devDependencies",
                        "optionalDependencies", "specifiers"})


def _pnpm_head(text):
    keep, out = False, []
    for line in text.splitlines():
        if line and not line[0].isspace() and line[0] != "#":
            m = re.match(r"([^\s:#][^:]*):", line)
            keep = bool(m) and m.group(1).strip("'\"") in _PNPM_KEEP
        if keep:
            out.append(line)
    return "\n".join(out)


class _NpmLock(object):
    def __init__(self, data):
        self.packages = data.get("packages") if isinstance(data.get("packages"), dict) else None
        self.legacy = _dict(data.get("dependencies"))

    def locked(self, ws, name):
        if self.packages is None:
            version = _dict(self.legacy.get(name)).get("version")
            return None if version is None else str(version)
        for key in ([_join(ws, "node_modules/" + name)] if ws != "." else []) + ["node_modules/" + name]:
            entry = self.packages.get(key)
            if isinstance(entry, dict):
                version = entry.get("version")
                if version is None and entry.get("link") and isinstance(entry.get("resolved"), str):
                    version = _dict(self.packages.get(entry["resolved"])).get("version")
                if version is not None:
                    return str(version)
        return None

    def binary_names(self):
        """Packages installed at the root whose lock entry exposes a `node` executable."""
        out = []
        for key, entry in (self.packages or {}).items():
            if key.startswith("node_modules/") and key.count("node_modules/") == 1 and isinstance(entry, dict):
                bins = entry.get("bin")
                if (isinstance(bins, dict) and "node" in bins) or (isinstance(bins, str) and key == "node_modules/node"):
                    out.append((key[len("node_modules/"):], entry.get("version")))
        return sorted(out)


class _PnpmLock(object):
    def __init__(self, text):
        data = _dict(yaml_load(_pnpm_head(text)))
        importers = data.get("importers")
        self.importers = {k: v for k, v in importers.items() if isinstance(v, dict)} \
            if isinstance(importers, dict) else {".": data}

    def locked(self, ws, name):
        for group in ("dependencies", "devDependencies", "optionalDependencies"):
            entries = _dict(self.importers.get(ws).get(group)) if ws in self.importers else {}
            if name in entries:
                entry = entries[name]
                version = entry.get("version") if isinstance(entry, dict) else entry
                return None if version is None else _cut_peer(str(version))
        return None


def _node_lock(c, pm):
    name = pm.get("name")
    if name in ("yarn", "bun"):
        c.note("locked versions are not read for %s" % name)
    if name == "npm":
        for rel in ("package-lock.json", "npm-shrinkwrap.json"):
            if c.json(rel):
                return _NpmLock(c.json(rel))
    if name == "pnpm" and c.text("pnpm-lock.yaml") is not None:
        try:
            return _PnpmLock(c.text("pnpm-lock.yaml"))
        except Exception:
            c.note("unparsed pnpm-lock.yaml (invalid YAML)")
    return None


def _node_packages(c, lock, workspaces):
    out = []
    for ws in workspaces:
        pkg = c.json(_join(ws, "package.json"))
        for kind, field in DEP_GROUPS:
            for name, spec in sorted(_dict(_dict(pkg).get(field)).items()):
                if isinstance(spec, str):
                    out.append({"name": name, "workspace": ws, "kind": kind, "declared": spec,
                                "locked": lock.locked(ws, name) if lock else None,
                                "style": _style(spec), "catalog": _catalog_name(spec)})
    return out


_PLATFORM = re.compile(r"^(?:php(?:-64bit|-ipv6|-zts|-debug)?|ext-.+|lib-.+|composer(?:-plugin-api|-runtime-api)?)$")


def _composer_packages(c):
    data = c.json("composer.json")
    if not data:
        return []
    locked = {}
    for group in ("packages", "packages-dev"):
        for entry in _dict(c.json("composer.lock")).get(group) or []:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry.get("version") is not None:
                locked[entry["name"]] = str(entry["version"])
    out = []
    for kind, field in (("prod", "require"), ("dev", "require-dev")):
        for name, spec in sorted(_dict(data.get(field)).items()):
            if isinstance(spec, str) and not _PLATFORM.match(name):
                out.append({"name": name, "workspace": ".", "kind": kind, "declared": spec,
                            "locked": locked.get(name), "style": _style(spec), "catalog": None})
    return out


_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*([^;#]*)")


def _requirement(line):
    """(name, spec) of a pip requirement line; None for options, includes and unnamed URLs."""
    line = line.strip()
    if not line or line[0] in "#-":
        return None
    if "://" in line.split(" @ ")[0]:
        egg = re.search(r"#egg=([A-Za-z0-9._-]+)", line)
        return (egg.group(1), line.split("#", 1)[0].strip()) if egg else None
    m = _REQ.match(line)
    if not m:
        return None
    spec = m.group(2).split(" --", 1)[0].strip().rstrip("\\").strip().rstrip(",").strip()
    return m.group(1), spec[1:].strip() if spec.startswith("@") else spec


def _py_entry(name, spec, kind, locked):
    pin = re.match(r"^===?\s*([^\s,*;]+)$", spec or "")
    return {"name": name, "workspace": ".", "kind": kind, "declared": spec or None,
            "locked": locked or (pin.group(1) if pin else None), "style": _py_style(spec), "catalog": None}


def _norm_py(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _python_packages(c):
    out = []
    pin_lock = {}
    for entry in _dict(c.toml("poetry.lock")).get("package") or []:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            pin_lock[_norm_py(entry["name"])] = str(entry.get("version")) if entry.get("version") is not None else None
    for entry_name, entry in sorted(_dict(_dict(c.json("Pipfile.lock")).get("default")).items()):
        pin_lock[_norm_py(entry_name)] = str(_dict(entry).get("version", "")).lstrip("=") or None
    for entry_name, entry in sorted(_dict(_dict(c.json("Pipfile.lock")).get("develop")).items()):
        pin_lock.setdefault(_norm_py(entry_name), str(_dict(entry).get("version", "")).lstrip("=") or None)

    for rel in c.requirements():
        kind = "dev" if re.search(r"dev|test|lint|doc|ci", rel.lower()) else "prod"
        for line in (c.text(rel) or "").splitlines():
            parsed = _requirement(line)
            if parsed:
                out.append(_py_entry(parsed[0], parsed[1], kind, None))

    project = _dict(c.toml("pyproject.toml"))
    meta = _dict(project.get("project"))
    for spec in _strs(meta.get("dependencies")):
        parsed = _requirement(spec)
        if parsed:
            out.append(_py_entry(parsed[0], parsed[1], "prod", pin_lock.get(_norm_py(parsed[0]))))
    for group in sorted(_dict(meta.get("optional-dependencies"))):
        for spec in _strs(meta["optional-dependencies"][group]):
            parsed = _requirement(spec)
            if parsed:
                out.append(_py_entry(parsed[0], parsed[1], "optional", pin_lock.get(_norm_py(parsed[0]))))
    for group in sorted(_dict(project.get("dependency-groups"))):
        for spec in _strs(project["dependency-groups"][group]):
            parsed = _requirement(spec)
            if parsed:
                out.append(_py_entry(parsed[0], parsed[1], "dev", pin_lock.get(_norm_py(parsed[0]))))

    poetry = _dict(_dict(project.get("tool")).get("poetry"))
    tables = [("prod", poetry.get("dependencies")), ("dev", poetry.get("dev-dependencies"))]
    tables += [("dev", _dict(g).get("dependencies")) for _, g in sorted(_dict(poetry.get("group")).items())]
    for kind, table in tables:
        for name, spec in sorted(_dict(table).items()):
            if name.lower() == "python":
                continue
            if isinstance(spec, dict):
                spec = spec.get("version") or spec.get("git") or spec.get("url") or spec.get("path")
            if isinstance(spec, str):
                out.append({"name": name, "workspace": ".", "kind": kind, "declared": spec,
                            "locked": pin_lock.get(_norm_py(name)), "style": _style(spec), "catalog": None})

    pipfile = _dict(c.toml("Pipfile"))
    for kind, table in (("prod", pipfile.get("packages")), ("dev", pipfile.get("dev-packages"))):
        for name, spec in sorted(_dict(table).items()):
            if isinstance(spec, dict):
                spec = spec.get("version") or spec.get("git")
            spec = "" if spec == "*" else spec
            if isinstance(spec, str):
                out.append(_py_entry(name, spec, kind, pin_lock.get(_norm_py(name))))
    return out


def _packages(c, lock, workspaces):
    out = _node_packages(c, lock, workspaces) + _composer_packages(c) + _python_packages(c)
    for entry in out:
        entry["declared"], entry["locked"] = _mask_userinfo(entry["declared"]), _mask_userinfo(entry["locked"])
    rank = {ws: i for i, ws in enumerate(workspaces)}
    return sorted(out, key=lambda e: (rank.get(e["workspace"], len(rank)), e["name"], e["kind"]))


# ---------------------------------------------------------------------------
# Overrides, patches, install scripts and .npmrc
# ---------------------------------------------------------------------------

def _flatten_overrides(prefix, value):
    if isinstance(value, str):
        return [(prefix, value)]
    out = []
    for key in sorted(_dict(value)):
        if key == ".":
            out.extend(_flatten_overrides(prefix, value[key]))
        else:
            out.extend(_flatten_overrides(prefix + ">" + key if prefix else key, value[key]))
    return out


def _overrides(c):
    pkg = _dict(c.json("package.json"))
    out = []
    for source, value in (("package.json#overrides", pkg.get("overrides")),
                          ("package.json#resolutions", pkg.get("resolutions")),
                          ("package.json#pnpm.overrides", _dict(pkg.get("pnpm")).get("overrides")),
                          ("pnpm-workspace.yaml#overrides", _dict(c.yaml("pnpm-workspace.yaml")[0]).get("overrides"))):
        out.extend({"name": name, "spec": _mask_userinfo(spec), "source": source}
                   for name, spec in _flatten_overrides("", value) if name)
    return sorted(out, key=lambda e: (e["source"], e["name"]))


_PATCH_FILE = re.compile(r"^(.+?)\+(\d[^+]*)(?:\+\d+)?\.patch$")


def _patched(c):
    out = []
    pkg = _dict(c.json("package.json"))
    for source, table in (("package.json#pnpm.patchedDependencies", _dict(pkg.get("pnpm")).get("patchedDependencies")),
                          ("pnpm-workspace.yaml#patchedDependencies",
                           _dict(c.yaml("pnpm-workspace.yaml")[0]).get("patchedDependencies"))):
        out.extend({"name": name, "path": path, "source": source}
                   for name, path in _dict(table).items() if isinstance(path, str))
    for rel in c.files:
        m = _PATCH_FILE.match(_base(rel)) if _dir(rel) == "patches" else None
        if m:
            name = m.group(1)
            if name.startswith("@"):
                name = name.replace("+", "/", 1)
            out.append({"name": "%s@%s" % (name, m.group(2)), "path": rel, "source": "patches/"})
    return sorted(out, key=lambda e: (e["source"], e["name"]))


def _install_scripts(c):
    data, comments = c.yaml("pnpm-workspace.yaml")
    for source, conf, notes in (("pnpm-workspace.yaml", _dict(data), comments),
                                ("package.json#pnpm", _dict(_dict(c.json("package.json")).get("pnpm")), {})):
        allow, deny, why, found = set(), set(), {}, False
        for key, bucket in (("onlyBuiltDependencies", allow), ("ignoredBuiltDependencies", deny),
                            ("neverBuiltDependencies", deny)):
            if isinstance(conf.get(key), list):
                found = True
                for i, name in enumerate(conf[key]):
                    if isinstance(name, str):
                        bucket.add(name)
                        if (key, i) in notes:
                            why[name] = notes[(key, i)]
        if isinstance(conf.get("allowBuilds"), dict):
            found = True
            for name, flag in conf["allowBuilds"].items():
                (allow if str(flag).lower() == "true" else deny).add(name)
                if ("allowBuilds", name) in notes:
                    why[name] = notes[("allowBuilds", name)]
        if found:
            return {"allow": sorted(allow), "deny": sorted(deny), "source": source,
                    "comments": dict(sorted(why.items()))}
    return None


NPMRC_KEYS = ("save-exact", "save-prefix", "engine-strict", "legacy-peer-deps", "strict-peer-dependencies",
              "auto-install-peers", "node-linker", "shamefully-hoist")
_REGISTRY_KEY = re.compile(r"^(?:@[\w.-]+:)?registry$")


def _registry_host(value):
    """host[:port] of a registry URL without its credentials; None when there is no host to report."""
    try:
        parts = urlsplit(_mask_userinfo(value))
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host or "${" in host:
        return None
    if ":" in host:
        host = "[%s]" % host
    return host if port is None else "%s:%d" % (host, port)


def _npmrc(c):
    out = []
    for rel in c.files:
        if _base(rel) != ".npmrc":
            continue
        keys = {}
        for raw in (c.text(rel) or "").splitlines():
            line = raw.strip()
            if not line or line[0] in "#;" or "=" not in line:
                continue
            key, value = (part.strip() for part in line.split("=", 1))
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key in NPMRC_KEYS:
                keys[key] = {"true": True, "false": False}.get(value, value)
            elif _REGISTRY_KEY.match(key):
                host = _registry_host(value)
                if host:
                    keys[key] = host
        out.append({"path": rel, "keys": dict(sorted(keys.items()))})
    return out


# ---------------------------------------------------------------------------
# Images: Docker and CI
# ---------------------------------------------------------------------------

_VAR = re.compile(r"\$\{(\w+)(?::?-([^}]*))?\}|\$(\w+)")


def _subst(text, env):
    def pick(m):
        name = m.group(1) or m.group(3)
        if env.get(name):
            return env[name]
        return m.group(2) if m.group(2) is not None else m.group(0)
    return _VAR.sub(pick, text)


def _split_image(ref):
    ref = ref.split("@", 1)[0]
    colon = ref.rfind(":")
    return (ref[:colon], ref[colon + 1:]) if colon > ref.rfind("/") else (ref, None)


def _unquote(text):
    text = text.strip()
    return _read_quoted(text, 0)[0] if text[:1] in ("'", '"') else text


def _is_yaml_name(name):
    return name.endswith((".yml", ".yaml"))


def _is_compose(name):
    return _is_yaml_name(name) and name.startswith(("docker-compose", "compose"))


def _dockerfile(c, rel):
    args, stages, out, started = {}, set(), [], False
    for no, raw in enumerate((c.text(rel) or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not started and re.match(r"^ARG\s", line, re.I):
            try:
                tokens = shlex.split(line[3:], comments=False)
            except ValueError:
                tokens = []
            args.update(tok.split("=", 1) for tok in tokens if "=" in tok)
            continue
        frm = re.match(r"^FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?", line, re.I)
        if frm:
            started = True
            ref = _subst(frm.group(1), args)
            if ref.lower() != "scratch" and ref.lower() not in stages:
                image, tag = _split_image(ref)
                out.append({"file": rel, "line": no, "image": image, "tag": tag, "stage": frm.group(2)})
            if frm.group(2):
                stages.add(frm.group(2).lower())
    return out


def _compose(c, rel):
    out, in_services, service, svc_indent, child_indent = [], False, None, None, None
    for no, raw in enumerate((c.text(rel) or "").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        body = _split_comment(raw.strip())[0]
        if indent == 0:
            in_services, service, svc_indent, child_indent = body == "services:", None, None, None
            continue
        if not in_services:
            continue
        if svc_indent is None:
            svc_indent = indent
        if indent == svc_indent:
            m = re.match(r"^([\w.-]+|'[^']*'|\"[^\"]*\")\s*:\s*$", body)
            service, child_indent = (m.group(1).strip("'\"") if m else None), None
        elif service is not None:
            child_indent = indent if child_indent is None else child_indent
            m = re.match(r"^image\s*:\s*(.+)$", body)
            if m and indent == child_indent:
                image, tag = _split_image(_subst(_unquote(m.group(1)), {}))
                out.append({"file": rel, "line": no, "image": image, "tag": tag, "stage": service})
    return out


def _docker(c):
    out = []
    for rel in c.files:
        name = _base(rel)
        if name.startswith("Dockerfile") and rel.count("/") <= DOCKER_DEPTH:
            out.extend(_dockerfile(c, rel))
        elif _is_compose(name) and rel.count("/") <= DOCKER_DEPTH:
            out.extend(_compose(c, rel))
    return sorted(out, key=lambda e: (e["file"], e["line"]))


# ---------------------------------------------------------------------------
# CI: GitLab and GitHub
# ---------------------------------------------------------------------------

GITLAB_RESERVED = frozenset({"image", "services", "stages", "variables", "include", "default", "workflow",
                             "cache", "before_script", "after_script", "spec"})
_VERIFY = re.compile(
    r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?[\w:.-]*(?:build|test|lint|typecheck|type-check|check-types|check|verify|e2e|tsc|playwright)\b"
    r"|\bnpx\s+(?:-y\s+|--yes\s+)?(?:tsc|eslint|vitest|jest|playwright|prettier|biome|stylelint)\b"
    r"|\b(?:tsc|eslint|vitest|jest|pytest|phpunit|phpstan|ruff|mypy|rspec)\b"
    r"|\b(?:playwright test|go test|go vet|cargo test|cargo clippy|cargo build|mvn (?:test|verify)"
    r"|gradlew? (?:test|build|check)|make (?:test|lint|build|check))\b"
    r"|\bcomposer\s+(?:run(?:-script)?\s+)?(?:test|lint|analy[sz]e|check|cs)\b")
_AUDIT = (("npm audit", re.compile(r"(?<!yarn )\bnpm\s+audit\b")), ("pnpm audit", re.compile(r"\bpnpm\s+audit\b")),
          ("yarn audit", re.compile(r"\byarn\s+(?:npm\s+)?audit\b")), ("gitleaks", re.compile(r"\bgitleaks\b")),
          ("trivy", re.compile(r"\btrivy\b")), ("snyk", re.compile(r"\bsnyk\b")),
          ("osv-scanner", re.compile(r"\bosv-scanner\b")), ("semgrep", re.compile(r"\bsemgrep\b")),
          ("renovate", re.compile(r"(?<![\w/.-])renovate(?:-config-validator)?(?![\w/])")),
          ("socket", re.compile(r"\bsocket\s+(?:ci|scan|npm|npx|optimize|wrapper|fix|report)\b|@socketsecurity/cli|\bsocketdev\b")))
SETUP_ACTIONS = {"actions/setup-node": ("node", "node-version"), "actions/setup-python": ("python", "python-version"),
                 "shivammathur/setup-php": ("php", "php-version"), "denoland/setup-deno": ("deno", "deno-version")}
IMAGE_RUNTIME = {"node": "node", "python": "python", "php": "php", "deno": "deno"}


class _Ci(object):
    def __init__(self):
        self.files, self.images, self.actions, self.pins = [], [], [], []
        self.verify, self.audit, self.node_versions, self.versions = [], [], [], []
        self.gitlab = self.github = self.merge_requests = False


_SECRET = r"(?:token|secret|passw(?:or)?d|api[_-]?key|credentials?|auth(?![a-z]))"
_NAME = r"(?=[\w.-]*%s)[\w.-]+" % _SECRET
# A value is one shell word: a quoted string, which may hold spaces, with whatever touches it, else a run of non-space.
_WORD = r"""(?:(?:"(?:[^"\\]|\\.)*(?:"|$)|'[^']*(?:'|$))\S*|\S+)"""
_SECRET_ASSIGN = re.compile(r"((?<![\w.-])%s=)%s" % (_NAME, _WORD), re.I)
# The same names given as a flag, an npm config key or the key after `set` carry their value as the next word.
_SECRET_ARG = re.compile(r"((?:(?<!\S)--?|(?<!\w)_|\bset\s+)%s['\"]?\s+)(?![-&|;<>])%s" % (_NAME, _WORD), re.I)


def _redact(command):
    return _mask_userinfo(_SECRET_ARG.sub(r"\1***", _SECRET_ASSIGN.sub(r"\1***", command)))


def _commands(value):
    out = []
    if isinstance(value, str):
        out.extend(_redact(line.strip()) for line in value.split("\n")
                   if line.strip() and not line.strip().startswith("#"))
    elif isinstance(value, list):
        for item in value:
            out.extend(_commands(item))
    return out


def _image_name(value):
    return value.get("name") if isinstance(value, dict) else value


def _add_image(ci, rel, job, ref, role, env):
    if isinstance(ref, str) and ref.strip():
        image, tag = _split_image(_subst(ref.strip(), env))
        ci.images.append({"file": rel, "job": job, "image": image, "tag": tag, "role": role})
        runtime = IMAGE_RUNTIME.get(image.rsplit("/", 1)[-1])
        if runtime and tag:
            ci.versions.append((runtime, "ci-image:" + rel, tag))
            if runtime == "node":
                ci.node_versions.append({"file": rel, "value": tag})


def _jobs_report(ci, rel, job, steps):
    """Record the verification and audit commands of one job; `steps` is [(commands, may_fail)]."""
    verify = [cmd for commands, _ in steps for cmd in commands if _VERIFY.search(cmd)]
    if verify:
        ci.verify.append({"file": rel, "job": job, "commands": verify})
    for commands, may_fail in steps:
        for cmd in commands:
            for tool, pattern in _AUDIT:
                if pattern.search(cmd):
                    _add_audit(ci, rel, job, tool, bool(may_fail) or bool(re.search(r"\|\|\s*(?:true|exit 0)\s*$", cmd)))


def _add_audit(ci, rel, job, tool, allow_failure):
    entry = {"file": rel, "job": job, "tool": tool, "allow_failure": allow_failure}
    if entry not in ci.audit:
        ci.audit.append(entry)


def _gitlab_job(jobs, name, seen=()):
    merged = {}
    job = _dict(jobs.get(name))
    parents = job.get("extends")
    for parent in ([parents] if isinstance(parents, str) else parents if isinstance(parents, list) else []):
        if isinstance(parent, str) and parent not in seen and len(seen) < 8:
            merged.update(_gitlab_job(jobs, parent, seen + (name,)))
    merged.update(job)
    return merged


def _gitlab(c, rel, ci):
    data = _dict(c.yaml(rel)[0])
    env = {}
    for key, value in _dict(data.get("variables")).items():
        value = value.get("value") if isinstance(value, dict) else value
        if isinstance(value, str):
            env[key] = value
    defaults = _dict(data.get("default"))
    _add_image(ci, rel, None, _image_name(data.get("image")), "default", env)
    _add_image(ci, rel, None, _image_name(defaults.get("image")), "default", env)
    for scope in (data, defaults):
        for service in scope.get("services") if isinstance(scope.get("services"), list) else []:
            _add_image(ci, rel, None, _image_name(service), "service", env)
    workflow = _dict(data.get("workflow"))
    for rule in workflow.get("rules") if isinstance(workflow.get("rules"), list) else []:
        if "merge_request_event" in str(_dict(rule).get("if")):
            ci.merge_requests = True
    jobs = {k: v for k, v in data.items() if k not in GITLAB_RESERVED and isinstance(v, dict)}
    for name in sorted(jobs):
        job = jobs[name]
        _add_image(ci, rel, name, _image_name(job.get("image")), "job", env)
        for service in job.get("services") if isinstance(job.get("services"), list) else []:
            _add_image(ci, rel, name, _image_name(service), "service", env)
        if not name.startswith("."):
            full = _gitlab_job(jobs, name)
            _jobs_report(ci, rel, name, [(_commands(full.get("script")), full.get("allow_failure"))])
    if "include" in data:
        c.note("%s uses include: the included files are not followed" % rel)


def _matrix_values(expr, matrix):
    m = re.match(r"^\$\{\{\s*matrix\.([\w-]+)\s*\}\}$", expr)
    if not m:
        return [expr]
    key = m.group(1)
    listed = matrix[key] if isinstance(matrix.get(key), list) else []
    included = [_dict(inc).get(key) for inc in matrix["include"]] if isinstance(matrix.get("include"), list) else []
    found = [str(v) for v in listed + included if v is not None and not isinstance(v, (dict, list))]
    return list(dict.fromkeys(found)) or [expr]


def _github(c, rel, ci):
    jobs = _dict(_dict(c.yaml(rel)[0]).get("jobs"))
    for jid in sorted(jobs):
        job = _dict(jobs[jid])
        if isinstance(job.get("uses"), str):
            _action(ci, rel, job["uses"])
        container = job.get("container")
        _add_image(ci, rel, jid, container.get("image") if isinstance(container, dict) else container, "job", {})
        for name in sorted(_dict(job.get("services"))):
            _add_image(ci, rel, jid, _dict(job["services"][name]).get("image"), "service", {})
        matrix = _dict(_dict(job.get("strategy")).get("matrix"))
        steps = []
        for step in job.get("steps") if isinstance(job.get("steps"), list) else []:
            step = _dict(step)
            may_fail = step.get("continue-on-error") is True or job.get("continue-on-error") is True
            if isinstance(step.get("uses"), str):
                action = _action(ci, rel, step["uses"])
                setup = SETUP_ACTIONS.get(action)
                version = _dict(step.get("with")).get(setup[1]) if setup else None
                if version is not None:
                    for value in _matrix_values(str(version), matrix):
                        ci.versions.append((setup[0], "setup-%s:%s" % (setup[0], rel), value))
                        if setup[0] == "node":
                            ci.node_versions.append({"file": rel, "value": value})
                for tool, pattern in _AUDIT:
                    if pattern.search(step["uses"].split("@")[0]):
                        _add_audit(ci, rel, jid, tool, may_fail)
            steps.append((_commands(step.get("run")), may_fail))
        _jobs_report(ci, rel, jid, steps)


def _action(ci, rel, uses):
    if "@" not in uses or uses.startswith(("./", "docker://")):
        return None
    name, ref = uses.rsplit("@", 1)
    entry = {"file": rel, "uses": name, "ref": ref}
    if entry not in ci.actions:
        ci.actions.append(entry)
    return name


_OPTS_WITH_ARG = frozenset({"-r", "-c", "-i", "-f", "-t", "--requirement", "--constraint", "--index-url",
                            "--extra-index-url", "--find-links", "--target"})
_SEGMENT_END = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")


def _tokens(segment):
    return [t.strip("'\"") for t in segment.split()]


def _pins_in_line(rel, no, line):
    out = []
    for segment in _SEGMENT_END.split(line):
        pip = re.search(r"\bpip3?\s+install\b(.*)$", segment)
        if pip:
            skip = False
            for tok in _tokens(pip.group(1)):
                if skip:
                    skip = False
                elif tok in _OPTS_WITH_ARG:
                    skip = True
                elif not tok.startswith("-"):
                    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;,]+)$", tok)
                    if m:
                        out.append({"file": rel, "line": no, "kind": "pip", "name": m.group(1), "version": m.group(2)})
        runner = re.search(r"\b(?:npx|bunx|pnpm\s+dlx|yarn\s+dlx|npm\s+exec)\b(.*)$", segment)
        glob = re.search(r"\bnpm\s+(?:i|install|add)\s+(?:\S+\s+)*?(?:-g|--global)\b(.*)$", segment)
        for match, first_only in ((runner, True), (glob, False)):
            for tok in _tokens(match.group(1)) if match else []:
                if tok.startswith("-"):
                    continue
                m = re.match(r"^(@?[A-Za-z0-9][A-Za-z0-9._/-]*)@(\d[^\s]*)$", tok)
                if m:
                    out.append({"file": rel, "line": no, "kind": "supabase-cli" if m.group(1) == "supabase" else "npx",
                                "name": m.group(1), "version": m.group(2)})
                if first_only:
                    break
        goi = re.search(r"\bgo\s+install\s+(\S+)@(v\d\S*)", segment)
        if goi:
            out.append({"file": rel, "line": no, "kind": "other", "name": goi.group(1), "version": goi.group(2)})
    return out


def _ci_pins(rel, text):
    out, lines = [], text.splitlines()
    for no, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.extend(_pins_in_line(rel, no, stripped[2:] if stripped.startswith("- ") else stripped))
        if re.search(r"\buses:\s*supabase/setup-cli@", raw):
            base = len(raw) - len(raw.lstrip(" "))
            for ahead in range(no, min(no + 8, len(lines))):
                nxt = lines[ahead]
                if nxt.strip().startswith("- ") and len(nxt) - len(nxt.lstrip(" ")) <= base:
                    break
                m = re.match(r"^\s*version:\s*['\"]?([^'\"\s#]+)", nxt)
                if m:
                    out.append({"file": rel, "line": ahead + 1, "kind": "supabase-cli", "name": "supabase",
                                "version": m.group(1)})
                    break
    return out


def _ci(c):
    ci = _Ci()
    for rel in c.files:
        name = _base(rel)
        gitlab = name == ".gitlab-ci.yml" or name.endswith(".gitlab-ci.yml")
        github = _dir(rel) == ".github/workflows" and _is_yaml_name(name)
        if not (gitlab or github):
            continue
        ci.files.append(rel)
        ci.pins.extend(_ci_pins(rel, c.text(rel) or ""))
        if gitlab:
            ci.gitlab = True
            _gitlab(c, rel, ci)
        else:
            ci.github = True
            _github(c, rel, ci)
    return ci


def _ci_report(ci):
    provider = "both" if ci.gitlab and ci.github else "gitlab" if ci.gitlab else "github" if ci.github else "none"
    return {
        "provider": provider,
        "files": ci.files,
        "mr_pipelines": ci.merge_requests,
        "images": sorted(ci.images, key=lambda e: (e["file"], e["job"] or "", e["role"], e["image"], e["tag"] or "")),
        "actions": sorted(ci.actions, key=lambda e: (e["file"], e["uses"], e["ref"])),
        "pins": sorted(ci.pins, key=lambda e: (e["file"], e["line"], e["kind"], e["name"])),
        "verify_jobs": sorted(ci.verify, key=lambda e: (e["file"], e["job"])),
        "audit_jobs": sorted(ci.audit, key=lambda e: (e["file"], e["job"], e["tool"])),
        "node_versions": sorted(ci.node_versions, key=lambda e: (e["file"], e["value"])),
    }


# ---------------------------------------------------------------------------
# Runtime pins
# ---------------------------------------------------------------------------

PIN_ORDER = (".nvmrc", ".node-version", ".python-version", ".php-version", ".dvmrc", ".tool-versions",
             "engines.node", "volta.node", "devEngines.runtime", "@types/node", "runtime.txt", "requires-python",
             "tool.poetry.python", "Pipfile.python_version", "require.php", "config.platform.php", "ci-image",
             "docker", "setup-node", "setup-python", "setup-php", "setup-deno")


def _pin_key(pin):
    head = pin["source"].split(":", 1)[0]
    return (PIN_ORDER.index(head) if head in PIN_ORDER else len(PIN_ORDER), pin["source"], pin["value"])


def _first_line(text):
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def _tool_versions(text):
    out = {}
    for line in (text or "").splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 2 and parts[0] not in out:
            out[parts[0]] = parts[1]
    return out


def _shadowed_by(lock, packages):
    for pkg in packages:
        if pkg["name"] == "node":
            return {"package": "node", "declared": pkg["declared"], "locked": pkg["locked"]}
    for name, version in lock.binary_names() if isinstance(lock, _NpmLock) else []:
        return {"package": name, "declared": None, "locked": None if version is None else str(version)}
    return None


def _runtimes(c, ci, docker, packages, lock):
    pins = {"node": [], "python": [], "php": [], "deno": []}

    def add(runtime, source, value):
        if isinstance(value, str) and value.strip():
            pins[runtime].append({"source": source, "value": value.strip()})

    add("node", ".nvmrc", _first_line(c.text(".nvmrc")))
    add("node", ".node-version", _first_line(c.text(".node-version")))
    tools = _tool_versions(c.text(".tool-versions"))
    for runtime, names in (("node", ("nodejs", "node")), ("python", ("python",)), ("php", ("php",)),
                           ("deno", ("deno",))):
        add(runtime, ".tool-versions", next((tools[n] for n in names if n in tools), None))
    pkg = _dict(c.json("package.json"))
    add("node", "engines.node", _dict(pkg.get("engines")).get("node"))
    add("node", "volta.node", _dict(pkg.get("volta")).get("node"))
    declared = _dict(pkg.get("devEngines")).get("runtime")
    for entry in declared if isinstance(declared, list) else [declared]:
        entry = _dict(entry)
        if entry.get("name") in ("node", "deno"):
            add(entry["name"], "devEngines.runtime", entry.get("version"))
    add("node", "@types/node", next((_dict(pkg.get(g))["@types/node"] for g in ("dependencies", "devDependencies")
                                      if "@types/node" in _dict(pkg.get(g))), None))

    add("python", ".python-version", _first_line(c.text(".python-version")))
    runtime_txt = re.match(r"^python-(\S+)$", _first_line(c.text("runtime.txt")) or "")
    add("python", "runtime.txt", runtime_txt.group(1) if runtime_txt else None)
    pyproject = c.text("pyproject.toml") or ""
    found = re.search(r"^requires-python\s*=\s*[\"']([^\"']+)[\"']", pyproject, re.M)
    add("python", "requires-python", found.group(1) if found else None)
    found = re.search(r"^\[tool\.poetry\.dependencies\][^\[]*?^python\s*=\s*[\"']([^\"']+)[\"']", pyproject, re.M | re.S)
    add("python", "tool.poetry.python", found.group(1) if found else None)
    found = re.search(r"^python_version\s*=\s*[\"']([^\"']+)[\"']", c.text("Pipfile") or "", re.M)
    add("python", "Pipfile.python_version", found.group(1) if found else None)

    composer = _dict(c.json("composer.json"))
    add("php", ".php-version", _first_line(c.text(".php-version")))
    add("php", "require.php", _dict(composer.get("require")).get("php"))
    add("php", "config.platform.php", _dict(_dict(composer.get("config")).get("platform")).get("php"))
    add("deno", ".dvmrc", _first_line(c.text(".dvmrc")))

    for entry in docker:
        runtime = IMAGE_RUNTIME.get(entry["image"].rsplit("/", 1)[-1])
        if runtime and entry["tag"]:
            add(runtime, "docker:" + entry["file"], entry["tag"])
    for runtime, source, value in ci.versions:
        add(runtime, source, value)

    out = {name: {"pins": sorted(found_pins, key=_pin_key)} for name, found_pins in pins.items()}
    out["node"]["shadowed_by"] = _shadowed_by(lock, packages)
    return out


# ---------------------------------------------------------------------------
# Update bots
# ---------------------------------------------------------------------------

def _bot(kind, path, parsed):
    return {"kind": kind, "path": path, "parsed": parsed, "caps": [], "disabled": [],
            "min_release_age_days": None, "groups": [], "vulnerability_alerts": None, "extends": []}


def _days(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    m = re.match(r"^\s*(\d+)\s*([a-zA-Z]+)\s*$", str(value or ""))
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith("mo"):
        return n * 30
    if unit.startswith("mi") or unit == "m":
        return -(-n // 1440)
    if unit.startswith("h"):
        return -(-n // 24)
    if unit.startswith("d"):
        return n
    if unit.startswith("w"):
        return n * 7
    return n * 365 if unit.startswith("y") else None


def _rule_targets(rule):
    names, patterns = [], []
    for key in ("matchPackageNames", "matchDepNames", "packageNames", "depNames"):
        for name in _strs(rule.get(key)):
            if len(name) > 2 and name.startswith("/") and name.endswith("/"):
                patterns.append(name[1:-1])
            else:
                names.append(name)
    for key in ("matchPackagePatterns", "matchDepPatterns", "packagePatterns"):
        patterns.extend(_strs(rule.get(key)))
    patterns.extend("^" + prefix for prefix in _strs(rule.get("matchPackagePrefixes")))
    return names, patterns


def _renovate(c, rel):
    data = c.json(rel)
    bot = _bot("renovate", rel, data is not None)
    if data is None:
        return bot
    for rule in data.get("packageRules") if isinstance(data.get("packageRules"), list) else []:
        rule = _dict(rule)
        names, patterns = _rule_targets(rule)
        if isinstance(rule.get("allowedVersions"), str):
            bot["caps"].append({"names": names, "patterns": patterns, "allowed": rule["allowedVersions"]})
        if rule.get("enabled") is False:
            bot["disabled"].append({"names": names, "patterns": patterns,
                                    "update_types": _strs(rule.get("matchUpdateTypes") or rule.get("updateTypes"))})
        if isinstance(rule.get("groupName"), str):
            bot["groups"].append({"name": rule["groupName"], "names": names, "patterns": patterns})
    if _strs(data.get("ignoreDeps")):
        bot["disabled"].append({"names": _strs(data["ignoreDeps"]), "patterns": [], "update_types": []})
    bot["min_release_age_days"] = _days(data.get("minimumReleaseAge", data.get("stabilityDays")))
    bot["vulnerability_alerts"] = data.get("vulnerabilityAlerts")
    bot["extends"] = _strs(data.get("extends"))
    return bot


RENOVATE_PARSED = ("renovate.json", ".renovaterc", ".renovaterc.json", ".github/renovate.json", ".gitlab/renovate.json")
RENOVATE_PRESENT = ("renovate.json5", ".renovaterc.json5", ".github/renovate.json5", ".gitlab/renovate.json5")
DEPENDABOT = (".github/dependabot.yml", ".github/dependabot.yaml")


def _bots(c):
    out = []
    for rel in c.files:
        if rel in RENOVATE_PARSED:
            out.append(_renovate(c, rel))
        elif rel in RENOVATE_PRESENT or rel in DEPENDABOT:
            out.append(_bot("dependabot" if rel in DEPENDABOT else "renovate", rel, False))
            c.note("unparsed %s (presence only)" % rel)
    return sorted(out, key=lambda b: b["path"])


# ---------------------------------------------------------------------------
# Verification commands, other ecosystems
# ---------------------------------------------------------------------------

SCRIPT_CHOICES = (("build", ("build",)), ("typecheck", ("typecheck", "type-check", "check-types", "tsc")),
                  ("lint", ("lint",)), ("test", ("test",)), ("e2e", ("test:e2e", "e2e", "playwright")))
_SPLIT_TOKENS = re.compile(r"[\s=:;|&()<>\"']+")


def _external(c, command):
    out, seen = [], set()
    for tok in _SPLIT_TOKENS.split(command):
        if (tok == os.pardir or tok.startswith(PARENT)) and tok not in seen:
            seen.add(tok)
            out.append({"path": tok, "exists": os.path.exists(os.path.normpath(os.path.join(c.root, tok)))})
    return out


def _verification(c, pm, ci):
    scripts = _dict(_dict(c.json("package.json")).get("scripts"))
    composer = _dict(_dict(c.json("composer.json")).get("scripts"))
    runner = pm["name"] if pm["name"] in ("npm", "pnpm", "yarn", "bun") else "npm"
    out = {}
    for key, names in SCRIPT_CHOICES:
        entry = {"command": None, "source": None, "note": None}
        name = next((n for n in names if isinstance(scripts.get(n), str)), None)
        if name:
            entry = {"command": "%s run %s" % (runner, name), "source": "package.json#scripts." + name, "note": None}
            if "no test specified" in scripts[name]:
                entry["command"], entry["note"] = None, "placeholder"
        else:
            name = next((n for n in names if n in composer), None)
            if name:
                entry = {"command": "composer run " + name, "source": "composer.json#scripts." + name, "note": None}
        out[key] = entry
    out["ci"] = [{"command": cmd, "job": job["job"], "external": _external(c, cmd)}
                 for job in sorted(ci.verify, key=lambda j: (j["file"], j["job"])) for cmd in job["commands"]]
    return out


OTHER_KINDS = {"deno.json": "deno", "deno.jsonc": "deno", "import_map.json": "deno", "deno.lock": "deno",
               "go.mod": "go", "Cargo.toml": "cargo", "Gemfile": "bundler", "build.gradle": "gradle",
               "build.gradle.kts": "gradle", "pom.xml": "maven", ".yarnrc.yml": "yarn-berry",
               "bun.lock": "bun", "bun.lockb": "bun", "bunfig.toml": "bun"}


def _other(c, locks):
    out = [{"kind": OTHER_KINDS[_base(rel)], "path": rel, "action": "manual"}
           for rel in c.files if _base(rel) in OTHER_KINDS]
    out.extend({"kind": "yarn-berry", "path": lock["path"], "action": "manual"}
               for lock in locks if lock["type"] == "yarn" and lock["version"] == "berry")
    return sorted(out, key=lambda e: (e["kind"], e["path"]))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _empty_runtimes():
    out = {name: {"pins": []} for name in ("node", "python", "php", "deno")}
    out["node"]["shadowed_by"] = None
    return out


def _empty_verification():
    out = {key: {"command": None, "source": None, "note": None} for key, _ in SCRIPT_CHOICES}
    out["ci"] = []
    return out


def dependency_manifest(root, skip_dirs=None):
    """The dependency manifest of the project at `root` (see the module docstring)."""
    c = _Ctx(root, skip_dirs)
    locks = _guard(c, "lockfiles", lambda: _lockfiles(c), [])
    pm = _guard(c, "package_manager", lambda: _package_manager(c, locks),
                {"name": None, "version": None, "source": "none"})
    workspaces = _guard(c, "workspaces", lambda: _workspaces(c), [])
    lock = _guard(c, "locked versions", lambda: _node_lock(c, pm), None)
    packages = _guard(c, "packages", lambda: _packages(c, lock, workspaces), [])
    docker = _guard(c, "docker", lambda: _docker(c), [])
    ci = _guard(c, "ci", lambda: _ci(c), _Ci())
    if ci.gitlab and ci.github:
        github = [f for f in ci.files if _dir(f) == ".github/workflows"]
        c.note("GitHub workflows next to GitLab CI are probably dead: " + ", ".join(github))
    result = {
        "format": MANIFEST_FORMAT,
        "package_manager": pm,
        "lockfiles": locks,
        "workspaces": workspaces,
        "catalogs": _guard(c, "catalogs", lambda: _catalogs(c), {}),
        "packages": packages,
        "overrides": _guard(c, "overrides", lambda: _overrides(c), []),
        "patched": _guard(c, "patched", lambda: _patched(c), []),
        "install_scripts": _guard(c, "install_scripts", lambda: _install_scripts(c), None),
        "npmrc": _guard(c, "npmrc", lambda: _npmrc(c), []),
        "runtimes": _guard(c, "runtimes", lambda: _runtimes(c, ci, docker, packages, lock), _empty_runtimes()),
        "bots": _guard(c, "bots", lambda: _bots(c), []),
        "ci": _ci_report(ci),
        "docker": docker,
        "verification": _guard(c, "verification", lambda: _verification(c, pm, ci), _empty_verification()),
        "other": _guard(c, "other", lambda: _other(c, locks), []),
    }
    result["notes"] = sorted(c.notes)
    return result


def attach_dependency_manifest(root, result, skip_dirs=None):
    """Set result["dependency_manifest"] and correct the scanner's package-manager list."""
    manifest = dependency_manifest(root, skip_dirs)
    result["dependency_manifest"] = manifest
    name = manifest["package_manager"]["name"]
    managers = _dict(result.get("stack")).get("package_managers")
    if name in ("pnpm", "yarn", "bun") and isinstance(managers, list):
        if "npm" in managers:
            if name in managers:
                managers.remove("npm")
            else:
                managers[managers.index("npm")] = name
        elif name not in managers:
            managers.append(name)


MANIFEST_NAMES = frozenset(LOCK_TYPES) | frozenset(OTHER_KINDS) | frozenset({
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "pnpm-workspace.yaml",
    "yarn.lock", "bun.lock", "bun.lockb", ".npmrc", ".nvmrc", ".node-version", ".tool-versions",
    ".python-version", "composer.json", "composer.lock", "pyproject.toml", "poetry.lock", "Pipfile",
    "Pipfile.lock", "renovate.json", "renovate.json5", ".renovaterc", ".renovaterc.json", "deno.json",
    "import_map.json", ".php-version", ".dvmrc", "runtime.txt", ".renovaterc.json5"})
MANIFEST_SECTIONS = ["Runtimes", "Frameworks and Critical Libraries", "Package Managers"]


def _is_manifest_path(path):
    name = _base(path)
    return (name in MANIFEST_NAMES or fnmatch.fnmatchcase(name, "requirements*.txt")
            or (_dir(path) == "patches" and bool(_PATCH_FILE.match(name))))


def _is_ci_path(path):
    name = _base(path)
    return (name.endswith(".gitlab-ci.yml")
            or (_dir(path) == ".github/workflows" and _is_yaml_name(name))
            or path in DEPENDABOT
            or name.startswith("Dockerfile")
            or _is_compose(name))


def dependency_update_targets(paths):
    """Context files a refresh must revisit for the changed project-relative `paths`, or []."""
    manifests, pipelines = set(), set()
    for raw in paths or []:
        path = str(raw).replace("\\", "/").strip()
        while path.startswith("./"):
            path = path[2:]
        path = path.strip("/")
        if _is_manifest_path(path):
            manifests.add(path)
        elif _is_ci_path(path):
            pipelines.add(path)
    if not manifests and not pipelines:
        return []
    hit = sorted(manifests | pipelines)
    sections = (MANIFEST_SECTIONS if manifests else []) + (["CI/CD"] if pipelines else [])
    return [{"file": "dependencies.md", "paths": hit},
            {"file": "stack.md", "sections": sections, "paths": hit}]
