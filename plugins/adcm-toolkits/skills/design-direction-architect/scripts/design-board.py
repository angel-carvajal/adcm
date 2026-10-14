#!/usr/bin/env python3
"""design-board - the review board of a .design pack, built from data (Python 3 stdlib only).

The model is board.json merged with every board.d/*.json fragment (by id) and the indexed inspiration/
drop folder. `build` renders it into one board.html whose assets (thumbnails, variant pages) are files
next to it, never inlined, each referenced as `<path>?v=<sha256[:8]>`. Output is byte-deterministic:
no clock, no randomness. Run with --help for the command line.
"""
import hashlib
import html
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(os.path.dirname(HERE), "templates")

HELP = """usage: design-board.py <init|check|build|mark|adopt|log|pack> [<.design dir>=.] [options]

commands:
  init      create board.json (from templates/board.json.tmpl), board.d/ and inspiration/; never overwrites
  check     validate board.json + board.d/*.json + inspiration/; one `FAIL <path>: <why>` line per error
  build     check, index inspiration/, make shots/ thumbnails, write board.html only when its bytes change,
            then patch the `files` key of the registry row whose file is board.html
  mark      --drop <id|Rnn> --why "<text>" | --finalist <id|Rnn> | --undrop <id|Rnn>   (edits board.json)
  adopt     "<combo>" [<.design dir>] | --file <tokens.json> [<.design dir>]
            combo = <opt>/<fontId>/<r<ratio>[b<base>]|presetId>/<paletteId>; the two positionals may come in
            either order. Writes tokens.css + tokens.json and sets decisions.chosen
  log       --step N --decided "<text>" --date YYYY-MM-DD [--built "…"] [--replaces "…"] [--findings "…"]
            [--debt "…"] [--evidence "…"]   append an entry to decisions.md
  pack      write references.md (references with URL, score, verdict, drop reason + market summary)

options:
  --registry <artifacts.json>  registry to patch on build (default: <dir>/artifacts.json when present)
  --no-thumbs                  reference the original images instead of shots/ thumbnails
  --dry                        print instead of writing (mark, adopt, log, pack)
  --help                       show this text

exit: 0 ok · 1 check failed · 2 board/template missing or unparseable · 64 usage"""

OPTION_IDS = ("a", "b", "c")
ROLES = ("ground", "surface", "ink", "ink-muted", "primary", "accent", "accent-ink", "border")
ROLE_ALIASES = {"bg": "ground", "text": "ink", "muted": "ink-muted", "inkMuted": "ink-muted", "line": "border",
                "accentInk": "accent-ink"}
STATIC_DEFAULTS = (("--leading-tight", "1.1"), ("--leading-body", "1.6"), ("--tracking-display", "-0.02em"),
                   ("--space-1", "0.25rem"), ("--space-2", "0.5rem"), ("--space-3", "1rem"), ("--space-4", "1.5rem"),
                   ("--space-5", "2.5rem"), ("--space-6", "4rem"), ("--radius", "10px"), ("--dur", "200ms"),
                   ("--ease", "cubic-bezier(.2, .7, .2, 1)"))
MONO_STACK = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
REF_KINDS = ("awwwards", "21st", "framer", "pinterest", "manual", "live")
MARKET_KINDS = ("competitor", "adjacent")
STEPS = ("references", "variants", "locked")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
ID_RE = re.compile(r"^[a-z0-9-]{1,48}$")
URL_RE = re.compile(r"^https?://[^\s<>\"']+$")
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COMBO_RE = re.compile(r"^[^/]+/[^/]+/[^/]+/[^/]+$")
RCODE_RE = re.compile(r"^[Rr](\d{1,3})$")
THUMB, LARGE = 480, 1440
HTML_LIMIT = 400 * 1024
FILES_WARN = 8 * 1024 * 1024
GOOGLE_CSS = "https://fonts.googleapis.com/css2?"

KEYS = {
    "top": {"schema", "project", "step", "stamp", "decisions", "options", "references", "market", "tokens", "scores"},
    "project": {"name", "tagline", "lang"},
    "decisions": {"file", "chosen", "note"},
    "option": {"id", "title", "idea", "variantFile", "shots", "method", "usedRefs", "usedMarket", "tokens", "name",
               "refs_used", "how_made", "why", "what_changes_if_picked", "cost", "fonts", "ratios", "palettes"},
    "method": {"how", "rationale", "steps"},
    "optTokens": {"display", "body", "scale", "colors", "palettes"},
    "reference": {"id", "title", "url", "via", "kind", "files", "finalist", "dropped", "notes", "tags", "name", "why",
                  "award", "style_fit", "commerce"},
    "market": {"id", "name", "kind", "url", "files", "works", "doesnt", "commerce", "query"},
    "tokens": {"fontShortlist", "scalePresets"},
    "font": {"id", "family", "google", "stack"},
    "preset": {"id", "label", "base", "ratio"},
    "fragment": {"references", "market", "scores", "options"},
}

UI = {
    "es": {"options": "Opciones", "refs": "Referencias", "market": "Mercado", "method": "Método", "tokens": "Tokens",
           "kept": "Conservadas", "dropped": "Descartadas", "variants": "Variantes", "title": "Design board",
           "refs_md": "Referencias", "market_md": "Mercado", "none": "—"},
    "en": {"options": "Options", "refs": "References", "market": "Market", "method": "Method", "tokens": "Tokens",
           "kept": "Kept", "dropped": "Dropped", "variants": "Variants", "title": "Design board",
           "refs_md": "References", "market_md": "Market", "none": "—"},
}
TABS = ("options", "refs", "market", "method", "tokens")


class Usage(Exception):
    pass


class Fatal(Exception):
    pass


class Failed(Exception):
    pass


# ------------------------------------------------------------------ small helpers
def out(line):
    print(line, flush=True)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise Fatal(f"{what} missing: {path}")
    except (ValueError, OSError) as exc:
        raise Fatal(f"{what} unparseable: {path}: {exc}")


def read_template(name):
    """A template's text without its leading <!-- --> header."""
    tpath = os.path.join(TEMPLATES, name)
    try:
        tmpl = read_text(tpath)
    except OSError:
        raise Fatal(f"template missing: {tpath}")
    if tmpl.startswith("<!--"):
        tmpl = tmpl[tmpl.index("-->") + 3:].lstrip("\n")
    return tmpl


def dump_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def as_dict(v):
    return v if isinstance(v, dict) else {}


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def fmt(x, places=3):
    """Same rounding as the board's JS (Math.round, half up), so exported and adopted values match."""
    k = 10 ** places
    s = f"{math.floor(x * k + 0.5) / k:.{places}f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def sha8(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


FONT_TEXT = re.compile(r"""^[A-Za-z0-9 ,'"+\-]+$""")


def escapes(d, rel):
    """True when the file (symlinks resolved) lies outside the .design folder."""
    root = os.path.realpath(d)
    return not os.path.realpath(os.path.join(d, rel)).startswith(root + os.sep)


def inside(rel):
    """A relative path that stays inside the .design folder."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or "\\" in rel:
        return False
    return os.pardir not in rel.split("/")


def capture_paths(ident):
    return [f"captures/{ident}-d.jpg", f"captures/{ident}-m.jpg"]


def entry_key(e, i):
    """Entries without a string id never merge: each keeps a key of its own."""
    return e.get("id") if isinstance(e.get("id"), str) else ("#", id(e), i)


def is_dropped(r):
    return isinstance(r.get("dropped"), dict) and bool(r["dropped"].get("is"))


def norm_role(k):
    return ROLE_ALIASES.get(k, k)


def norm_colors(colors):
    if not isinstance(colors, dict):
        return {}
    res = {norm_role(k): v for k, v in colors.items()}
    if "primary" not in res and "accent" in res:
        res["primary"] = res["accent"]
    return {r: res[r] for r in ROLES if r in res}


def host_of(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def image_width(path):
    """Pixel width of a PNG or JPEG (None when unknown)."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">I", head[16:20])[0]
            if head[:2] != b"\xff\xd8":
                return None
            f.seek(2)
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                while b == b"\xff":
                    b = f.read(1)
                if not b:
                    return None
                marker = b[0]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    continue
                size = struct.unpack(">H", f.read(2))[0]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    seg = f.read(5)
                    return struct.unpack(">H", seg[3:5])[0]
                f.seek(size - 2, 1)
    except (OSError, struct.error, IndexError):
        return None


# ------------------------------------------------------------------ model
class Board:
    """board.json + board.d/*.json + inspiration/ merged into one render model."""

    def __init__(self, d):
        self.dir = os.path.abspath(d)
        self.path = os.path.join(self.dir, "board.json")
        self.raw = load_json(self.path, "board.json")
        if not isinstance(self.raw, dict):
            raise Fatal(f"board.json unparseable: {self.path}: top level is not an object")
        self.warns = []
        self.fragments = []
        frag_dir = os.path.join(self.dir, "board.d")
        if os.path.isdir(frag_dir):
            for name in sorted(os.listdir(frag_dir)):
                if name.endswith(".json"):
                    rel = f"board.d/{name}"
                    self.fragments.append((rel, self._fragment(rel, load_json(os.path.join(frag_dir, name), rel))))
        self.inspiration = self._index_inspiration()
        insp_ids = {e["id"] for e in self.inspiration}
        self.project = as_dict(self.raw.get("project"))
        self.lang = "en" if self.project.get("lang") == "en" else "es"
        self.decisions = as_dict(self.raw.get("decisions"))
        self.tokens = as_dict(self.raw.get("tokens"))
        self.fonts = [f for f in self.tokens.get("fontShortlist") or [] if isinstance(f, dict)]
        self.presets = [p for p in self.tokens.get("scalePresets") or [] if isinstance(p, dict)]
        self.font_by_id = {f.get("id"): f for f in self.fonts}
        self.preset_by_id = {p.get("id"): p for p in self.presets}
        self.scores = self._merge_scores()
        self.references = [self._norm_ref(e) for e in self._merge("references", [self.inspiration], insp_ids)]
        self.market = [dict(e) for e in self._merge("market", [], set())]
        self.options = [self._norm_option(e) for e in self._merge("options", [], set())]
        self.options.sort(key=lambda o: (o.get("id") not in OPTION_IDS, str(o.get("id"))))
        self.ref_by_id = {r.get("id"): r for r in self.references}

    # -- loading
    def _fragment(self, rel, data):
        if isinstance(data, list):
            stem = os.path.basename(rel)
            key = next((k for k in ("options", "market", "scores") if stem.startswith(k)), "references")
            return {key: data}
        if not isinstance(data, dict):
            raise Fatal(f"{rel} unparseable: expected an object or a list")
        known = KEYS["fragment"] & set(data)
        if not known and os.path.basename(rel).startswith("scores"):
            return {"scores": data}
        for k in data:
            if k not in KEYS["fragment"]:
                self.warns.append(f"WARN {rel}: unknown key {k}")
        return data

    def _index_inspiration(self):
        folder = os.path.join(self.dir, "inspiration")
        if not os.path.isdir(folder):
            return []
        sources = {}
        src_txt = os.path.join(folder, "sources.txt")
        if os.path.isfile(src_txt):
            for line in read_text(src_txt).splitlines():
                parts = line.rstrip("\r").split("\t")
                if len(parts) >= 2 and parts[0].strip() and not parts[0].startswith("#"):
                    sources[parts[0].strip()] = (parts[1].strip(), parts[2].strip() if len(parts) > 2 else "")
        items, seen = [], set()
        for name in sorted(os.listdir(folder)):
            stem, ext = os.path.splitext(name)
            if ext.lower() not in IMG_EXT or name.startswith("."):
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:40].strip("-") or "image"
            ident, n = f"insp-{slug}", 2
            while ident in seen:
                ident, n = f"insp-{slug}-{n}", n + 1
            seen.add(ident)
            url, title = sources.get(name, ("", ""))
            sidecar = os.path.join(folder, name + ".url")
            if os.path.isfile(sidecar):
                for line in read_text(sidecar).splitlines():
                    line = line.strip()
                    if line.startswith("URL="):
                        line = line[4:]
                    if URL_RE.match(line):
                        url = line
                        break
            host = host_of(url)
            pin = host == "pin.it" or host == "pinterest.com" or host.endswith(".pinterest.com") or \
                bool(re.search(r"(^|\.)pinterest\.com\.[a-z]{2}$", host))
            item = {"id": ident, "title": (title or re.sub(r"[-_]+", " ", stem).strip() or ident)[:80],
                    "kind": "pinterest" if pin else "manual", "files": [f"inspiration/{name}"], "inspiration": True}
            if url:
                item["url"] = url
            items.append(item)
        return items

    def _merge(self, key, extra_layers, protected_ids):
        """board.json entries first unless a fragment or inspiration owns the id; board.json fields win."""
        layers = [frag.get(key) or [] for _, frag in self.fragments] + extra_layers
        order, merged = [], {}
        for entries in layers:
            for i, e in enumerate(entries if isinstance(entries, list) else []):
                if not isinstance(e, dict):
                    continue
                ident = entry_key(e, i)
                if ident not in merged:
                    order.append(ident)
                    merged[ident] = {}
                merged[ident].update(e)
        head = []
        base = self.raw.get(key) if isinstance(self.raw.get(key), list) else []
        for i, e in enumerate(base):
            if not isinstance(e, dict):
                continue
            ident = entry_key(e, i)
            if ident in merged:
                if ident in protected_ids:
                    merged[ident].update({k: e[k] for k in ("finalist", "dropped", "notes") if k in e})
                else:
                    merged[ident].update(e)
            else:
                head.append(ident)
                merged[ident] = dict(e)
        return [merged[i] for i in head + order]

    def _merge_scores(self):
        scores = {}
        layers = [frag.get("scores") for _, frag in self.fragments] + [self.raw.get("scores")]
        for layer in layers:
            if isinstance(layer, dict):
                for k, v in layer.items():
                    if isinstance(v, dict):
                        scores.setdefault(k, {}).update(v)
            elif isinstance(layer, list):
                for e in layer:
                    if isinstance(e, dict) and isinstance(e.get("id"), str):
                        scores.setdefault(e["id"], {}).update({k: v for k, v in e.items() if k != "id"})
        return scores

    def _norm_ref(self, e):
        e = dict(e)
        sc = self.scores.get(e.get("id")) or {}
        for k in ("finalist", "dropped"):
            if k not in e and k in sc:
                e[k] = sc[k]
        if "title" not in e and "name" in e:
            e["title"] = e["name"]
        if "notes" not in e and "why" in e:
            e["notes"] = e["why"]
        if isinstance(e.get("dropped"), bool):
            e["dropped"] = {"is": e["dropped"]}
        return e

    def _norm_option(self, e):
        o = dict(e)
        if "title" not in o and "name" in o:
            o["title"] = o["name"]
        if "usedRefs" not in o and "refs_used" in o:
            o["usedRefs"] = o["refs_used"]
        method = dict(as_dict(o.get("method")))
        for src, dst in (("how_made", "how"), ("why", "rationale")):
            if dst not in method and src in o:
                method[dst] = "\n".join(o[src]) if isinstance(o[src], list) else o[src]
        o["method"] = method
        if "what_changes_if_picked" in o:
            o["whatChanges"] = o["what_changes_if_picked"]
        ident = o.get("id")
        o.setdefault("variantFile", f"variants/{ident}.html")
        tok = as_dict(o.get("tokens"))
        pairs = []
        for i, p in enumerate(o.get("fonts") or []):
            if isinstance(p, dict):
                pairs.append({"id": str(p.get("id") or f"f{i + 1}"), "display": p.get("display"),
                              "body": p.get("body"), "mono": p.get("mono")})
        if not pairs and (tok.get("display") or tok.get("body")):
            pairs.append({"id": "f1", "display": tok.get("display"), "body": tok.get("body"), "mono": None})
        o["pairs"] = pairs
        preset = self.preset_by_id.get(tok.get("scale")) if isinstance(tok.get("scale"), str) else None
        o["base"] = preset["base"] if preset and num(preset.get("base")) else 16
        ratios = [r for r in (o.get("ratios") or []) if num(r)]
        if preset and num(preset.get("ratio")) and preset["ratio"] not in ratios:
            ratios.insert(0, preset["ratio"])
        o["ratioList"] = ratios or [1.25]
        pals = []
        for i, p in enumerate(o.get("palettes") or tok.get("palettes") or []):
            if isinstance(p, dict):
                colors = p.get("colors") if isinstance(p.get("colors"), dict) else \
                    {k: v for k, v in p.items() if k not in ("id", "label")}
                pals.append({"id": str(p.get("id") or f"p{i + 1}"), "label": str(p.get("label") or p.get("id") or
                                                                                    f"p{i + 1}"),
                             "colors": norm_colors(colors)})
        if tok.get("colors") and not any(norm_colors(tok["colors"]) == p["colors"] for p in pals):
            pals.insert(0, {"id": "p0", "label": "Base", "colors": norm_colors(tok["colors"])})
        o["paletteList"] = pals
        default_pair = next((p for p in pairs if p["display"] == tok.get("display") and p["body"] == tok.get("body")),
                            pairs[0] if pairs else None)
        o["defaults"] = {"pair": default_pair["id"] if default_pair else None, "ratio": o["ratioList"][0],
                         "palette": pals[0]["id"] if pals else None}
        return o

    # -- helpers
    def ref_code(self, ref):
        return f"R{self.references.index(ref) + 1:02d}"

    def resolve_ref(self, token):
        m = RCODE_RE.match(token)
        if m:
            n = int(m.group(1))
            return self.references[n - 1] if 1 <= n <= len(self.references) else None
        return self.ref_by_id.get(token)

    def font_css(self, font_id, fallback=MONO_STACK):
        f = self.font_by_id.get(font_id)
        if not f:
            return fallback
        fam = str(f.get("family") or "").strip()
        stack = str(f.get("stack") or "").strip() or "system-ui, sans-serif"
        if not fam or stack.lstrip("\"'").startswith(fam):
            return stack
        return f'"{fam}", {stack}'

    def statics(self, option):
        """Static contract values: the variant's own :root wins over the defaults."""
        vals = dict(STATIC_DEFAULTS)
        path = os.path.join(self.dir, option.get("variantFile") or "")
        if inside(option.get("variantFile")) and os.path.isfile(path):
            roots = re.findall(r":root\s*\{([^{}]*)\}", read_text(path))
            for block in roots[:1]:
                for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+)", block):
                    if name in vals:
                        vals[name] = value.strip()
        return vals


# ------------------------------------------------------------------ check
def lim(fails, path, value, n, required=False):
    if value is None or value == "":
        if required:
            fails.append(f"FAIL {path}: required")
        return
    if not isinstance(value, str):
        fails.append(f"FAIL {path}: must be a string")
    elif len(value) > n:
        fails.append(f"FAIL {path}: {len(value)} chars > {n}")


def unknown(warns, path, obj, known):
    if isinstance(obj, dict):
        for k in obj:
            if k not in known:
                warns.append(f"WARN {path}: unknown key {k}")


def check_url(fails, path, v, required=False):
    if v is None or v == "":
        if required:
            fails.append(f"FAIL {path}: required")
    elif not isinstance(v, str) or not URL_RE.match(v):
        fails.append(f"FAIL {path}: not an http(s) URL")


def check_files(b, fails, warns, path, ident, files, implicit):
    """Explicit files must exist; implicit capture paths only WARN until `capture` runs."""
    if files is None:
        if not any(os.path.isfile(os.path.join(b.dir, p)) for p in implicit):
            cap = os.path.join(b.dir, "captures", f"{ident}.json")
            if not os.path.isfile(cap):
                warns.append(f"WARN {path}: not captured yet ({implicit[0]})")
        return
    if not isinstance(files, list):
        fails.append(f"FAIL {path}.files: must be a list")
        return
    for f in files:
        if not inside(f):
            fails.append(f"FAIL {path}.files: {f!r} is not a relative path inside the .design folder")
        elif not os.path.isfile(os.path.join(b.dir, f)):
            fails.append(f"FAIL {f}: missing (referenced by {path}.files)")
        elif escapes(b.dir, f):
            fails.append(f"FAIL {f}: outside .design")


CSS_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb|color)\(|\b(?:white|black)\b", re.I)


def variant_problems(text):
    probs = []
    if "data-board-bridge" not in text:
        probs.append("missing the data-board-bridge snippet")
    if "var(--font-display)" not in text:
        probs.append("never uses var(--font-display)")
    chunks = re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)
    attrs = re.findall(r"\sstyle\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", text, re.I)
    blocks = []
    for c in chunks:
        c = re.sub(r"/\*.*?\*/", "", c, flags=re.S)
        c = re.sub(r":root(?:\[[^\]]*\])?(?:\s*,\s*:root(?:\[[^\]]*\])?)*\s*\{[^{}]*\}", "", c)
        blocks += re.findall(r"\{([^{}]*)\}", c)
    blocks += [a or b for a, b in attrs]
    for decls in blocks:
        for decl in decls.split(";"):
            if ":" not in decl:
                continue
            prop, value = (s.strip() for s in decl.split(":", 1))
            prop = prop.lower()
            if CSS_COLOR.search(value):
                probs.append(f"color literal outside :root ({prop}: {value[:40]})")
            elif prop in ("font-size", "font-family", "font") and "var(" not in value and \
                    value.lower() not in ("inherit", "initial", "unset", "revert"):
                probs.append(f"{prop} literal outside :root ({prop}: {value[:40]})")
    return list(dict.fromkeys(probs))


def check_board(b, render_size=True):
    fails, warns = [], list(b.warns)
    raw = b.raw
    unknown(warns, "board.json", raw, KEYS["top"])
    if raw.get("schema") != 1:
        fails.append("FAIL board.json.schema: must be 1")
    p = raw.get("project")
    if not isinstance(p, dict):
        fails.append("FAIL board.json.project: required object")
    else:
        unknown(warns, "board.json.project", p, KEYS["project"])
        lim(fails, "project.name", p.get("name"), 60, True)
        lim(fails, "project.tagline", p.get("tagline"), 140)
        if p.get("lang") not in (None, "es", "en"):
            fails.append("FAIL project.lang: must be es or en")
    if raw.get("step") not in STEPS:
        fails.append(f"FAIL board.json.step: must be one of {'|'.join(STEPS)}")
    if "stamp" in raw and not isinstance(raw["stamp"], str):
        fails.append("FAIL board.json.stamp: must be a string")
    dec = raw.get("decisions")
    if dec is not None:
        if not isinstance(dec, dict):
            fails.append("FAIL board.json.decisions: must be an object")
        else:
            unknown(warns, "board.json.decisions", dec, KEYS["decisions"])
            if dec.get("chosen") not in (None, *OPTION_IDS):
                fails.append("FAIL decisions.chosen: must be null, a, b or c")
            lim(fails, "decisions.note", dec.get("note"), 280)
            if "file" in dec and not inside(dec["file"]):
                fails.append("FAIL decisions.file: must be a relative path inside the .design folder")
    step = raw.get("step")

    # tokens
    tok = raw.get("tokens")
    if tok is not None and not isinstance(tok, dict):
        fails.append("FAIL board.json.tokens: must be an object")
    unknown(warns, "board.json.tokens", tok, KEYS["tokens"])
    fonts = b.tokens.get("fontShortlist")
    if fonts is not None:
        if not isinstance(fonts, list) or not 2 <= len(fonts) <= 10:
            fails.append("FAIL tokens.fontShortlist: needs 2 to 10 fonts")
        ids = set()
        for i, f in enumerate(fonts if isinstance(fonts, list) else []):
            path = f"tokens.fontShortlist[{i}]"
            if not isinstance(f, dict):
                fails.append(f"FAIL {path}: must be an object")
                continue
            unknown(warns, path, f, KEYS["font"])
            if not isinstance(f.get("id"), str) or not ID_RE.match(f["id"]) or f["id"] in ids:
                fails.append(f"FAIL {path}.id: missing, duplicated or not ^[a-z0-9-]{{1,48}}$")
            ids.add(f.get("id"))
            lim(fails, f"{path}.family", f.get("family"), 60, True)
            lim(fails, f"{path}.stack", f.get("stack"), 200, True)
            for k in ("family", "stack"):
                if isinstance(f.get(k), str) and f[k] and not FONT_TEXT.match(f[k]):
                    fails.append(f"FAIL {path}.{k}: only letters, digits, spaces and , ' \" + - are allowed")
            g = f.get("google")
            if g is not None and (not isinstance(g, str) or not re.match(r"^[A-Za-z0-9 ]+(:[a-z,]+@[0-9;.,]+)?$", g)):
                fails.append(f"FAIL {path}.google: expected \"Family:wght@400;700\" or null")
    presets = b.tokens.get("scalePresets")
    if presets is not None:
        if not isinstance(presets, list) or not 1 <= len(presets) <= 6:
            fails.append("FAIL tokens.scalePresets: needs 1 to 6 presets")
        for i, s in enumerate(presets if isinstance(presets, list) else []):
            path = f"tokens.scalePresets[{i}]"
            if not isinstance(s, dict):
                fails.append(f"FAIL {path}: must be an object")
                continue
            unknown(warns, path, s, KEYS["preset"])
            if not isinstance(s.get("id"), str) or not s["id"]:
                fails.append(f"FAIL {path}.id: required")
            if not num(s.get("base")) or not 14 <= s["base"] <= 20:
                fails.append(f"FAIL {path}.base: must be 14..20")
            if not num(s.get("ratio")) or not 1.067 <= s["ratio"] <= 1.618:
                fails.append(f"FAIL {path}.ratio: must be 1.067..1.618")

    # references
    refs = b.references
    for i, e in enumerate(e for e in raw.get("references") or [] if isinstance(e, dict)):
        unknown(warns, f"board.json.references[{i}]", e, KEYS["reference"])
    for rel, frag in b.fragments:
        for i, e in enumerate(frag.get("references") or []):
            unknown(warns, f"{rel}.references[{i}]", e, KEYS["reference"])
        for i, e in enumerate(frag.get("market") or []):
            unknown(warns, f"{rel}.market[{i}]", e, KEYS["market"])
        for i, e in enumerate(frag.get("options") or []):
            unknown(warns, f"{rel}.options[{i}]", e, KEYS["option"])
    if len(refs) > 60:
        fails.append(f"FAIL references: {len(refs)} > 60")
    seen = set()
    finalists = 0
    for r in refs:
        ident = r.get("id")
        path = f"references.{ident}" if isinstance(ident, str) else "references[?]"
        if not isinstance(ident, str) or not ID_RE.match(ident):
            fails.append(f"FAIL {path}.id: missing or not ^[a-z0-9-]{{1,48}}$")
        elif ident in seen:
            fails.append(f"FAIL {path}.id: duplicated")
        seen.add(ident)
        lim(fails, f"{path}.title", r.get("title"), 80, True)
        check_url(fails, f"{path}.url", r.get("url"), required=not r.get("inspiration"))
        check_url(fails, f"{path}.via", r.get("via"))
        if r.get("kind") not in REF_KINDS:
            fails.append(f"FAIL {path}.kind: must be one of {'|'.join(REF_KINDS)}")
        if not isinstance(r.get("finalist", False), bool):
            fails.append(f"FAIL {path}.finalist: must be true or false")
        drop = r.get("dropped")
        if drop is not None:
            if not isinstance(drop, dict) or not isinstance(drop.get("is", False), bool):
                fails.append(f"FAIL {path}.dropped: must be {{is, why}}")
            elif drop.get("is"):
                lim(fails, f"{path}.dropped.why", drop.get("why"), 160, True)
        if r.get("finalist") is True:
            finalists += 1
        lim(fails, f"{path}.notes", r.get("notes"), 280)
        lim(fails, f"{path}.commerce", r.get("commerce"), 160)
        tags = r.get("tags")
        if tags is not None and (not isinstance(tags, list) or len(tags) > 6 or
                                 not all(isinstance(t, str) for t in tags)):
            fails.append(f"FAIL {path}.tags: up to 6 strings")
        if isinstance(ident, str):
            check_files(b, fails, warns, path, ident, r.get("files"), capture_paths(ident))
    if finalists > 12:
        fails.append(f"FAIL references: {finalists} finalists > 12")

    # market
    if len(b.market) > 16:
        fails.append(f"FAIL market: {len(b.market)} > 16")
    for i, e in enumerate(raw.get("market") or []):
        unknown(warns, f"board.json.market[{i}]", e, KEYS["market"])
    mseen = set()
    for m in b.market:
        ident = m.get("id")
        path = f"market.{ident}" if isinstance(ident, str) else "market[?]"
        if not isinstance(ident, str) or not ID_RE.match(ident) or ident in mseen:
            fails.append(f"FAIL {path}.id: missing, duplicated or not ^[a-z0-9-]{{1,48}}$")
        mseen.add(ident)
        lim(fails, f"{path}.name", m.get("name"), 60, True)
        if m.get("kind") not in MARKET_KINDS:
            fails.append(f"FAIL {path}.kind: must be competitor or adjacent")
        check_url(fails, f"{path}.url", m.get("url"), required=True)
        lim(fails, f"{path}.works", m.get("works"), 160, True)
        lim(fails, f"{path}.commerce", m.get("commerce"), 160)
        lim(fails, f"{path}.doesnt", m.get("doesnt"), 160, True)
        if isinstance(ident, str):
            check_files(b, fails, warns, path, ident, m.get("files"), capture_paths(ident))

    # options
    ids = [o.get("id") for o in b.options]
    if sorted(map(str, ids)) != list(OPTION_IDS):
        fails.append(f"FAIL options: exactly 3 options with ids a, b, c (found {', '.join(map(str, ids)) or 'none'})")
    for i, e in enumerate(raw.get("options") or []):
        unknown(warns, f"board.json.options[{i}]", e, KEYS["option"])
        if isinstance(e, dict):
            unknown(warns, f"board.json.options[{i}].method", e.get("method"), KEYS["method"])
            unknown(warns, f"board.json.options[{i}].tokens", e.get("tokens"), KEYS["optTokens"])
    for o in b.options:
        ident = o.get("id")
        path = f"options.{ident}"
        lim(fails, f"{path}.title", o.get("title"), 60, True)
        lim(fails, f"{path}.idea", o.get("idea"), 280)
        meth = o["method"]
        lim(fails, f"{path}.method.how", meth.get("how"), 1200)
        lim(fails, f"{path}.method.rationale", meth.get("rationale"), 800)
        st = meth.get("steps")
        if st is not None and (not isinstance(st, list) or len(st) > 8 or
                               any(not isinstance(s, str) or len(s) > 160 for s in st)):
            fails.append(f"FAIL {path}.method.steps: up to 8 strings of ≤160 chars")
        for key, pool, label in (("usedRefs", b.ref_by_id, "reference"),
                                 ("usedMarket", {m.get("id"): m for m in b.market}, "market entry")):
            used = o.get(key) or []
            if not isinstance(used, list):
                fails.append(f"FAIL {path}.{key}: must be a list of ids")
                continue
            for u in used:
                target = pool.get(u)
                if target is None:
                    fails.append(f"FAIL {path}.{key}: {u!r} is not a known {label}")
                elif key == "usedRefs" and is_dropped(target):
                    fails.append(f"FAIL {path}.usedRefs: {u!r} is dropped")
        vf = o.get("variantFile")
        if not inside(vf):
            fails.append(f"FAIL {path}.variantFile: must be a relative path inside the .design folder")
        elif not os.path.isfile(os.path.join(b.dir, vf)):
            (warns if step == "references" else fails).append(
                f"{'WARN' if step == 'references' else 'FAIL'} {vf}: missing (variant of option {ident})")
        else:
            for prob in variant_problems(read_text(os.path.join(b.dir, vf))):
                fails.append(f"FAIL {vf}: {prob}")
        shots = o.get("shots")
        if shots is not None:
            if not isinstance(shots, dict):
                fails.append(f"FAIL {path}.shots: must be {{d, m}}")
            else:
                for k, v in shots.items():
                    if k not in ("d", "m") or not inside(v):
                        fails.append(f"FAIL {path}.shots.{k}: expected d|m with a relative path")
                    elif not os.path.isfile(os.path.join(b.dir, v)):
                        fails.append(f"FAIL {v}: missing (shot of option {ident})")
                    elif escapes(b.dir, v):
                        fails.append(f"FAIL {v}: outside .design")
        if o.get("tokens") is not None and not isinstance(o["tokens"], dict):
            fails.append(f"FAIL {path}.tokens: must be an object")
        tok_o = as_dict(o.get("tokens"))
        for k in ("display", "body"):
            if tok_o.get(k) is not None and tok_o[k] not in b.font_by_id:
                fails.append(f"FAIL {path}.tokens.{k}: font {tok_o[k]!r} is not in tokens.fontShortlist")
        if tok_o.get("scale") is not None and tok_o["scale"] not in b.preset_by_id:
            fails.append(f"FAIL {path}.tokens.scale: preset {tok_o['scale']!r} is not in tokens.scalePresets")
        for pair in o["pairs"]:
            for k in ("display", "body", "mono"):
                v = pair.get(k)
                if v is None:
                    continue
                if not isinstance(v, str) or not FONT_TEXT.match(v):
                    fails.append(f"FAIL {path}.fonts.{pair['id']}.{k}: only letters, digits, spaces and , ' \" + - "
                                 f"are allowed")
                elif v not in b.font_by_id:
                    fails.append(f"FAIL {path}.fonts.{pair['id']}.{k}: font {v!r} is not in tokens.fontShortlist")
        for r in o.get("ratios") or []:
            if not num(r) or not 1.067 <= r <= 1.618:
                fails.append(f"FAIL {path}.ratios: {r!r} outside 1.067..1.618")
        pal_src = o.get("palettes") if o.get("palettes") is not None else tok_o.get("palettes")
        if pal_src is not None and (not isinstance(pal_src, list) or len(pal_src) > 4):
            fails.append(f"FAIL {path}.palettes: up to 4 palettes")
        colors_src = [("tokens.colors", tok_o.get("colors"))] if tok_o.get("colors") is not None else []
        for i, pal in enumerate(pal_src if isinstance(pal_src, list) else []):
            if isinstance(pal, dict):
                colors_src.append((f"palettes[{i}]", pal.get("colors") if "colors" in pal else
                                   {k: v for k, v in pal.items() if k not in ("id", "label")}))
        for where, colors in colors_src:
            if not isinstance(colors, dict):
                fails.append(f"FAIL {path}.{where}: must be an object of #RRGGBB colors")
                continue
            for k, v in colors.items():
                if norm_role(k) not in ROLES:
                    warns.append(f"WARN {path}.{where}: unknown color role {k}")
                if not isinstance(v, str) or not HEX_RE.match(v):
                    fails.append(f"FAIL {path}.{where}.{k}: {v!r} is not #RRGGBB")
            missing = [r for r in ROLES if r not in norm_colors(colors)]
            if missing:
                fails.append(f"FAIL {path}.{where}: missing roles {', '.join(missing)}")

    if render_size and not fails:
        assets = Assets(b.dir, thumbs=False)
        size = len(render(b, assets).encode("utf-8"))
        if size > HTML_LIMIT:
            fails.append(f"FAIL board.html: rendered {size // 1024} KB > 400 KB")
        total = sum(os.path.getsize(p) for p in assets.files.values())
        if total > FILES_WARN:
            warns.append(f"WARN files: {total // 1024} KB of assets > 8 MB")
    return fails, warns


# ------------------------------------------------------------------ assets and thumbnails
class Assets:
    def __init__(self, d, thumbs=True):
        self.dir = d
        self.thumbs = thumbs
        self.files = {}
        self.made = 0
        self.kept = 0
        self.warned = False
        self.tool = None
        if thumbs:
            self.tool = next((t for t in ("sips", "magick") if shutil.which(t)), None)

    def url(self, rel):
        path = os.path.join(self.dir, rel)
        self.files[rel] = path
        return urllib.parse.quote(rel, safe="/-_.~") + "?v=" + sha8(path)

    def image(self, rel, tid, k, width):
        if not self.thumbs or os.path.splitext(rel)[1].lower() not in IMG_EXT:
            return self.url(rel)
        out_rel = f"shots/{tid}-{k}-{width}.jpg"
        src, dst = os.path.join(self.dir, rel), os.path.join(self.dir, out_rel)
        if os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            self.kept += 1
            return self.url(out_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        w = image_width(src)
        target = min(width, w) if w else width
        cmd = None
        if self.tool == "sips":
            cmd = ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "80", "--resampleWidth", str(target), src,
                   "--out", dst]
        elif self.tool == "magick":
            cmd = ["magick", src, "-background", "white", "-flatten", "-resize", f"{width}x>", "-strip", "-quality",
                   "80", dst]
        ok = cmd is not None and subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not ok:
            if not self.warned:
                out("WARN thumbs: no sips/magick" if not self.tool else f"WARN thumbs: {self.tool} failed, copying")
                self.warned = True
            shutil.copyfile(src, dst)
        self.made += 1
        return self.url(out_rel)


def media_kind(rel, used):
    m = re.search(r"-([dm])\.\w+$", os.path.basename(rel))
    k = m.group(1) if m else "src"
    base, n = k, 2
    while k in used:
        k, n = f"{base}{n}", n + 1
    used.add(k)
    return k


def entry_media(b, assets, entry, large):
    files = entry.get("files")
    ident = entry["id"]
    if files is None:
        files = [p for p in capture_paths(ident) if os.path.isfile(os.path.join(b.dir, p))]
    media, used = [], set()
    for rel in files:
        if not inside(rel) or not os.path.isfile(os.path.join(b.dir, rel)):
            continue
        k = media_kind(rel, used)
        t = assets.image(rel, ident, k, THUMB)
        media.append({"k": k, "t": t, "l": assets.image(rel, ident, k, LARGE) if large else t})
    return media


def capture_info(b, ident):
    path = os.path.join(b.dir, "captures", f"{ident}.json")
    if not os.path.isfile(path):
        return None
    try:
        data = load_json(path, "capture")
    except Fatal:
        return None
    if not isinstance(data, dict):
        return None
    info = {}
    if data.get("captureError"):
        info["error"] = str(data["captureError"])[:160]
    pal = data.get("palette")
    if isinstance(pal, list):
        info["palette"] = [c for c in pal if isinstance(c, str) and re.match(r"^#[0-9A-Fa-f]{3,8}$", c)][:6]
    return info or None


# ------------------------------------------------------------------ render
def view_model(b, assets):
    refs = []
    for i, r in enumerate(b.references):
        drop = r.get("dropped") if isinstance(r.get("dropped"), dict) else {}
        large = bool(r.get("finalist")) or bool(r.get("inspiration"))
        item = {"id": r["id"], "code": f"R{i + 1:02d}", "title": r.get("title") or r["id"], "url": r.get("url"),
                "via": r.get("via"), "kind": r.get("kind"), "finalist": bool(r.get("finalist")),
                "dropped": bool(drop.get("is")), "why": drop.get("why") if drop.get("is") else None,
                "notes": r.get("notes"), "tags": r.get("tags") or [], "award": r.get("award"),
                "commerce": r.get("commerce"),
                "insp": bool(r.get("inspiration")), "media": entry_media(b, assets, r, large),
                "scores": b.scores.get(r["id"]) or {}, "capture": capture_info(b, r["id"])}
        refs.append({k: v for k, v in item.items() if v not in (None, "", [], {})})
    market = []
    for i, m in enumerate(b.market):
        item = {"id": m["id"], "code": f"M{i + 1:02d}", "name": m.get("name"), "kind": m.get("kind"),
                "url": m.get("url"), "works": m.get("works"), "doesnt": m.get("doesnt"),
                "commerce": m.get("commerce"), "media": entry_media(b, assets, m, False),
                "capture": capture_info(b, m["id"])}
        market.append({k: v for k, v in item.items() if v not in (None, "", [], {})})
    options = []
    chosen = b.decisions.get("chosen")
    for o in b.options:
        ident = o["id"]
        vf = o.get("variantFile")
        variant = assets.url(vf) if inside(vf) and os.path.isfile(os.path.join(b.dir, vf)) else None
        shots = o["shots"] if isinstance(o.get("shots"), dict) else \
            {"d": f"shots/opt-{ident}-d.jpg", "m": f"shots/opt-{ident}-m.jpg"}
        shot = {}
        for k in ("d", "m"):
            rel = shots.get(k)
            if inside(rel) and os.path.isfile(os.path.join(b.dir, rel)):
                shot[k] = {"t": assets.image(rel, f"opt-{ident}", k, THUMB),
                           "l": assets.image(rel, f"opt-{ident}", k, LARGE)}
        item = {"id": ident, "title": o.get("title") or ident.upper(), "idea": o.get("idea"), "variant": variant,
                "shot": shot, "method": o["method"], "usedRefs": o.get("usedRefs") or [],
                "usedMarket": o.get("usedMarket") or [], "whatChanges": o.get("whatChanges"), "cost": o.get("cost"),
                "pairs": o["pairs"], "ratios": o["ratioList"], "base": o["base"], "palettes": o["paletteList"],
                "defaults": o["defaults"], "statics": b.statics(o), "chosen": chosen == ident}
        options.append({k: v for k, v in item.items() if v not in (None, "")})
    fonts = [{"id": f.get("id"), "family": f.get("family"), "google": f.get("google"), "css": b.font_css(f.get("id"))}
             for f in b.fonts]
    return {"lang": b.lang, "project": {"name": b.project.get("name") or "", "tagline": b.project.get("tagline")},
            "step": b.raw.get("step"), "stamp": b.raw.get("stamp"), "chosen": chosen,
            "note": b.decisions.get("note"), "options": options, "refs": refs, "market": market, "fonts": fonts,
            "presets": b.presets, "mono": MONO_STACK}


def fonts_link(b):
    fams = []
    for f in b.fonts:
        g = f.get("google")
        if isinstance(g, str) and g and g not in fams:
            fams.append(g)
    if not fams:
        return ""
    href = GOOGLE_CSS + "&".join("family=" + g.replace(" ", "+") for g in fams) + "&display=swap"
    return ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            f'<link rel="stylesheet" href="{html.escape(href)}">')


def render(b, assets):
    tmpl = read_template("board.html.tmpl")
    ui = UI[b.lang]
    tabs = "\n".join(
        f'<button class="tab" role="tab" type="button" data-tab="{t}" aria-controls="tab-{t}" '
        f'aria-selected="{"true" if i == 0 else "false"}">{html.escape(ui[t])}</button>' for i, t in enumerate(TABS))
    data = json.dumps(view_model(b, assets), ensure_ascii=False, separators=(",", ":"))
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    name = b.project.get("name") or "Design"
    vals = {"lang": b.lang, "title": html.escape(f"{name} · {ui['title']}"), "fonts_link": fonts_link(b),
            "tabs": tabs, "data_json": data}
    return re.sub(r"\{\{(lang|title|fonts_link|tabs|data_json)\}\}", lambda m: vals[m.group(1)], tmpl)


# ------------------------------------------------------------------ tokens (adopt)
def scale_vars(base, ratio):
    return [(f"--step-{n}" if n >= 0 else "--step--1", fmt(base * ratio ** n / 16) + "rem") for n in range(-1, 6)]


def resolve_combo(b, combo):
    parts = combo.split("/")
    if len(parts) != 4 or not all(parts):
        raise Usage(f"combo must be <opt>/<fontId>/<r<ratio>[b<base>]|presetId>/<paletteId>, got {combo!r}")
    oid, fid, rpart, pid = parts
    opt = next((o for o in b.options if o.get("id") == oid), None)
    if opt is None:
        raise Failed(f"FAIL adopt: option {oid!r} not in the board")
    pair = next((p for p in opt["pairs"] if p["id"] == fid), None)
    if pair is None and fid in b.font_by_id:
        base_pair = next((p for p in opt["pairs"] if p["id"] == opt["defaults"]["pair"]), {})
        pair = {"id": fid, "display": fid, "body": base_pair.get("body") or fid, "mono": base_pair.get("mono")}
    if pair is None:
        raise Failed(f"FAIL adopt: font {fid!r} is neither a font pair of option {oid} nor a shortlist font")
    base = opt["base"]
    if rpart in b.preset_by_id:
        preset = b.preset_by_id[rpart]
        base, ratio = preset.get("base", base), preset.get("ratio")
    else:
        m = re.match(r"^r(\d+(?:\.\d+)?)(?:b(\d+(?:\.\d+)?))?$", rpart)
        if not m:
            raise Failed(f"FAIL adopt: {rpart!r} is neither r<ratio>[b<base>] nor a scale preset id")
        ratio = float(m.group(1))
        if m.group(2):
            base = float(m.group(2))
            base = int(base) if base.is_integer() else base
            if not 14 <= base <= 20:
                raise Failed(f"FAIL adopt: base {base!r} outside 14..20")
    if not num(ratio) or not 1.067 <= ratio <= 1.618:
        raise Failed(f"FAIL adopt: ratio {ratio!r} outside 1.067..1.618")
    pal = next((p for p in opt["paletteList"] if p["id"] == pid), None)
    if pal is None:
        raise Failed(f"FAIL adopt: palette {pid!r} not in option {oid}")
    return {"option": oid, "pair": pair, "base": base, "ratio": ratio, "palette": pid, "colors": pal["colors"]}


def selection_from_file(b, path):
    doc = load_json(path, "tokens file")
    if not isinstance(doc, dict):
        raise Fatal(f"tokens file unparseable: {path}")
    oid = doc.get("option")
    opt = next((o for o in b.options if o.get("id") == oid), None)
    if opt is None:
        raise Failed(f"FAIL adopt: option {oid!r} not in the board")
    fonts = doc.get("fonts") if isinstance(doc.get("fonts"), dict) else {}
    for k in ("display", "body", "mono"):
        if fonts.get(k) is not None and fonts[k] not in b.font_by_id:
            raise Failed(f"FAIL adopt: font {fonts[k]!r} is not in tokens.fontShortlist")
    scale = doc.get("scale") if isinstance(doc.get("scale"), dict) else {}
    base, ratio = scale.get("base"), scale.get("ratio")
    if not num(base) or not 14 <= base <= 20 or not num(ratio) or not 1.067 <= ratio <= 1.618:
        raise Failed("FAIL adopt: scale.base must be 14..20 and scale.ratio 1.067..1.618")
    colors = norm_colors(doc.get("colors"))
    bad = [r for r in ROLES if not isinstance(colors.get(r), str) or not HEX_RE.match(colors[r])]
    if bad:
        raise Failed(f"FAIL adopt: colors need #RRGGBB for {', '.join(bad)}")
    pair = {"id": doc.get("pair") or "custom", "display": fonts.get("display"), "body": fonts.get("body"),
            "mono": fonts.get("mono")}
    return {"option": oid, "pair": pair, "base": base, "ratio": ratio, "palette": doc.get("palette") or "custom",
            "colors": colors}


def token_docs(b, sel):
    opt = next(o for o in b.options if o.get("id") == sel["option"])
    pair = sel["pair"]
    statics = b.statics(opt)
    vars_ = [("--font-display", b.font_css(pair.get("display"), "system-ui, sans-serif")),
             ("--font-body", b.font_css(pair.get("body"), "system-ui, sans-serif")),
             ("--font-mono", b.font_css(pair.get("mono"), MONO_STACK))]
    vars_ += scale_vars(sel["base"], sel["ratio"])
    vars_ += [(k, statics[k]) for k in ("--leading-tight", "--leading-body", "--tracking-display")]
    vars_ += [(f"--color-{r}", sel["colors"][r].upper()) for r in ROLES]
    vars_ += [(k, v) for k, v in statics.items() if not k.startswith(("--leading", "--tracking"))]
    base_part = "" if sel["base"] == opt["base"] else f"b{fmt(sel['base'])}"
    combo = f"{sel['option']}/{pair['id']}/r{fmt(sel['ratio'])}{base_part}/{sel['palette']}"
    name = b.project.get("name") or "Design"
    css = [f"/* tokens.css · {name} · {combo}", " * Written by design-board adopt from board.json; re-run adopt instead of editing. */",
           ":root {"]
    css += [f"  {k}: {v};" for k, v in vars_]
    css += ["}", "", "@media (prefers-reduced-motion: reduce) {", "  :root { --dur: 0ms; }", "}", ""]
    doc = {"schema": 1, "combo": combo, "option": sel["option"], "pair": pair["id"],
           "fonts": {"display": pair.get("display"), "body": pair.get("body"), "mono": pair.get("mono")},
           "scale": {"base": sel["base"], "ratio": sel["ratio"]}, "palette": sel["palette"],
           "colors": {r: sel["colors"][r].upper() for r in ROLES}, "vars": dict(vars_)}
    return "\n".join(css), dump_json(doc)


# ------------------------------------------------------------------ markdown outputs (log, pack)
def cell(v):
    s = "—" if v in (None, "") else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def table(head, rows):
    if not rows:
        return "—"
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def score_of(b, ident):
    s = b.scores.get(ident) or {}
    if num(s.get("total")):
        return fmt(s["total"], 2)
    vals = [v for k, v in s.items() if num(v)]
    return fmt(sum(vals), 2) if vals else ""


def verdict_of(b, r):
    s = b.scores.get(r.get("id")) or {}
    if s.get("verdict"):
        return s["verdict"]
    if is_dropped(r):
        return "drop"
    return "finalist" if r.get("finalist") else ""


def log_entry(b, a):
    tmpl = read_template("decision-entry.md.tmpl")
    ui = UI[b.lang]
    kept = [(b.ref_code(r), r.get("id"), r.get("title"), r.get("url"), score_of(b, r.get("id")))
            for r in b.references if r.get("finalist") and not is_dropped(r)]
    dropped = [(b.ref_code(r), r.get("id"), r.get("title"), r["dropped"].get("why")) for r in b.references
               if is_dropped(r)]
    chosen = b.decisions.get("chosen")
    variants = [(o.get("id"), o.get("title"), o.get("idea"), "✓" if o.get("id") == chosen else "")
                for o in b.options]
    vals = {"date": a["date"], "step": a["step"], "decided": a["decided"], "built": a.get("built") or "—",
            "replaces": a.get("replaces") or "—", "findings": a.get("findings") or "—",
            "debt": a.get("debt") or "—", "evidence": a.get("evidence") or "board.html",
            "kept_title": ui["kept"], "dropped_title": ui["dropped"], "variants_title": ui["variants"],
            "kept": table(["#", "id", "title", "url", "score"], kept),
            "dropped": table(["#", "id", "title", "why"], dropped),
            "variants": table(["option", "title", "idea", "chosen"], variants)}
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(vals.get(m.group(1), m.group(0))), tmpl).rstrip("\n") + "\n"


def pack_text(b):
    ui = UI[b.lang]
    name = b.project.get("name") or "Design"
    rows = [(b.ref_code(r), r.get("title"), r.get("url"), r.get("via"), r.get("kind"), score_of(b, r.get("id")),
             verdict_of(b, r), r["dropped"].get("why") if is_dropped(r) else "") for r in b.references]
    mrows = [(m.get("name"), m.get("kind"), m.get("url"), m.get("works"), m.get("doesnt")) for m in b.market]
    lines = [f"# {ui['refs_md']} · {name}", "",
             "Written by design-board pack from board.json; re-run pack instead of editing.", "",
             table(["#", "title", "url", "via", "kind", "score", "verdict", "drop why"], rows), "",
             f"## {ui['market_md']}", "",
             table(["name", "kind", "url", "works", "doesn't"], mrows), ""]
    comp = sum(1 for m in b.market if m.get("kind") == "competitor")
    lines += [f"{comp} competitor(s) · {len(b.market) - comp} adjacent · "
              f"{sum(1 for r in b.references if r.get('finalist') and not is_dropped(r))} finalist(s) · "
              f"{sum(1 for r in b.references if is_dropped(r))} dropped", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ registry
def patch_registry(d, registry, files):
    path = registry or os.path.join(d, "artifacts.json")
    if not os.path.isfile(path):
        if registry:
            raise Fatal(f"registry missing: {registry}")
        return
    data = load_json(path, "registry")
    rows = data.get("artifacts") if isinstance(data, dict) else data
    reg_dir = os.path.dirname(os.path.abspath(path))
    target = os.path.realpath(os.path.join(d, "board.html"))
    row = next((r for r in rows or [] if isinstance(r, dict) and isinstance(r.get("file"), str) and
                os.path.realpath(os.path.join(reg_dir, r["file"])) == target), None)
    if row is None:
        out(f"WARN registry: no row with file board.html in {path}; files not patched")
        return
    new = {k: os.path.relpath(os.path.join(d, k), reg_dir).replace(os.sep, "/") for k in sorted(files)}
    if row.get("files") == new:
        out(f"registry: files unchanged ({len(new)})")
        return
    row["files"] = new
    write_text(path, dump_json(data))
    out(f"registry: files patched ({len(new)})")


# ------------------------------------------------------------------ commands
def report(fails, warns):
    for w in warns:
        out(w)
    for f in fails:
        out(f)


def cmd_check(d, a):
    b = Board(d)
    fails, warns = check_board(b)
    report(fails, warns)
    if fails:
        return 1
    out(f"OK check: {len(b.options)} options · {len(b.references)} references "
        f"({len(b.inspiration)} from inspiration/) · {len(b.market)} market")
    return 0


def cmd_build(d, a):
    b = Board(d)
    fails, warns = check_board(b, render_size=False)
    report(fails, warns)
    if fails:
        return 1
    assets = Assets(b.dir, thumbs=not a["no_thumbs"])
    page = render(b, assets).encode("utf-8")
    if len(page) > HTML_LIMIT:
        out(f"FAIL board.html: rendered {len(page) // 1024} KB > 400 KB")
        return 1
    total = sum(os.path.getsize(p) for p in assets.files.values())
    if total > FILES_WARN:
        out(f"WARN files: {total // 1024} KB of assets > 8 MB")
    if assets.thumbs:
        out(f"thumbs: {assets.made} made · {assets.kept} kept")
    dst = os.path.join(b.dir, "board.html")
    try:
        with open(dst, "rb") as f:
            same = f.read() == page
    except OSError:
        same = False
    if not same:
        with open(dst, "wb") as f:
            f.write(page)
    out(f"board.html: {'unchanged' if same else 'written'} ({len(page) // 1024} KB · {len(assets.files)} files)")
    patch_registry(b.dir, a["registry"], assets.files)
    return 0


def cmd_init(d, a):
    path = os.path.join(d, "board.json")
    if os.path.exists(path):
        out(f"FAIL init: {path} exists; init never overwrites")
        return 1
    lines = read_template("board.json.tmpl").splitlines()
    text = "\n".join(l for l in lines if not l.lstrip().startswith("//")).strip() + "\n"
    try:
        json.loads(text)
    except ValueError as exc:
        raise Fatal(f"template unparseable: {os.path.join(TEMPLATES, 'board.json.tmpl')}: {exc}")
    os.makedirs(os.path.join(d, "board.d"), exist_ok=True)
    os.makedirs(os.path.join(d, "inspiration"), exist_ok=True)
    write_text(path, text)
    out(f"init: wrote {path}, board.d/ and inspiration/")
    return 0


def save_board(b, a, what):
    text = dump_json(b.raw)
    if a["dry"]:
        sys.stdout.write(text)
        return 0
    write_text(b.path, text)
    out(what)
    return 0


def cmd_mark(d, a):
    b = Board(d)
    modes = [m for m in ("drop", "finalist", "undrop") if a.get(m)]
    if len(modes) != 1:
        raise Usage("mark needs exactly one of --drop, --finalist, --undrop")
    mode = modes[0]
    if mode == "drop" and not a.get("why"):
        raise Usage("mark --drop needs --why")
    ref = b.resolve_ref(a[mode])
    if ref is None:
        out(f"FAIL mark: no reference {a[mode]!r}")
        return 1
    ident = ref["id"]
    refs = b.raw.setdefault("references", [])
    entry = next((e for e in refs if isinstance(e, dict) and e.get("id") == ident), None)
    if entry is None:
        entry = {"id": ident}
        refs.append(entry)
    if mode == "drop":
        if len(a["why"]) > 160:
            out("FAIL mark: --why is longer than 160 chars")
            return 1
        entry["dropped"] = {"is": True, "why": a["why"]}
        entry["finalist"] = False
    elif mode == "undrop":
        entry["dropped"] = {"is": False}
    else:
        if is_dropped(ref):
            out(f"FAIL mark: {ident} is dropped; --undrop it first")
            return 1
        count = sum(1 for r in b.references if r.get("finalist") and r["id"] != ident)
        if count >= 12:
            out("FAIL mark: already 12 finalists")
            return 1
        entry["finalist"] = True
    return save_board(b, a, f"mark: {ident} ({b.ref_code(ref)}) {mode}")


def cmd_adopt(d, a):
    b = Board(d)
    if bool(a.get("combo")) == bool(a.get("file")):
        raise Usage("adopt needs a combo or --file <tokens.json>")
    if a.get("file"):
        path = a["file"] if os.path.isfile(a["file"]) else os.path.join(b.dir, a["file"])
        sel = selection_from_file(b, path)
    else:
        sel = resolve_combo(b, a["combo"])
    css, doc = token_docs(b, sel)
    if a["dry"]:
        sys.stdout.write(css + "\n" + doc)
        return 0
    write_text(os.path.join(b.dir, "tokens.css"), css)
    write_text(os.path.join(b.dir, "tokens.json"), doc)
    dec = b.raw.get("decisions")
    if not isinstance(dec, dict):
        dec = b.raw["decisions"] = {"file": "decisions.md", "chosen": None, "note": ""}
    if dec.get("chosen") != sel["option"]:
        dec["chosen"] = sel["option"]
        write_text(b.path, dump_json(b.raw))
    out(f"adopt: wrote tokens.css + tokens.json ({json.loads(doc)['combo']}); decisions.chosen = {sel['option']}")
    return 0


def cmd_log(d, a):
    if not a.get("step") or not a.get("decided") or not a.get("date"):
        raise Usage("log needs --step N --decided \"<text>\" --date YYYY-MM-DD")
    if not DATE_RE.match(a["date"]):
        raise Usage("--date must be YYYY-MM-DD")
    if not re.match(r"^\d+[a-z]?$", a["step"]):
        raise Usage("--step must be a number with an optional letter (5, 5b)")
    b = Board(d)
    entry = log_entry(b, a)
    if a["dry"]:
        sys.stdout.write(entry)
        return 0
    rel = b.decisions.get("file") if inside(b.decisions.get("file")) else "decisions.md"
    path = os.path.join(b.dir, rel)
    if os.path.isfile(path):
        text = read_text(path)
        text = text if text.endswith("\n") else text + "\n"
        text += "\n" + entry
    else:
        text = f"# Decisions · {b.project.get('name') or 'Design'}\n\n" + entry
    write_text(path, text)
    out(f"log: appended step {a['step']} ({a['date']}) to {rel}")
    return 0


def cmd_pack(d, a):
    b = Board(d)
    text = pack_text(b)
    if a["dry"]:
        sys.stdout.write(text)
        return 0
    write_text(os.path.join(b.dir, "references.md"), text)
    out(f"pack: wrote references.md ({len(b.references)} references · {len(b.market)} market)")
    return 0


COMMANDS = {"init": cmd_init, "check": cmd_check, "build": cmd_build, "mark": cmd_mark, "adopt": cmd_adopt,
            "log": cmd_log, "pack": cmd_pack}
VALUE_FLAGS = {"--registry": "registry", "--drop": "drop", "--finalist": "finalist", "--undrop": "undrop",
               "--why": "why", "--file": "file", "--step": "step", "--decided": "decided", "--date": "date",
               "--built": "built", "--replaces": "replaces", "--findings": "findings", "--debt": "debt",
               "--evidence": "evidence"}
ALLOWED = {"init": set(), "check": set(), "build": {"registry", "no_thumbs"},
           "mark": {"drop", "finalist", "undrop", "why", "dry"}, "adopt": {"file", "dry", "combo"},
           "log": {"step", "decided", "date", "built", "replaces", "findings", "debt", "evidence", "dry"},
           "pack": {"dry"}}


def parse(argv):
    if not argv or argv[0] not in COMMANDS:
        raise Usage("unknown or missing command" if argv else "missing command")
    cmd, a, pos = argv[0], {"no_thumbs": False, "dry": False, "registry": None}, []
    it = iter(argv[1:])
    for tok in it:
        if tok in VALUE_FLAGS:
            val = next(it, None)
            if val is None:
                raise Usage(f"{tok} needs a value")
            a[VALUE_FLAGS[tok]] = val
        elif tok == "--no-thumbs":
            a["no_thumbs"] = True
        elif tok == "--dry":
            a["dry"] = True
        elif tok.startswith("--"):
            raise Usage(f"unknown option {tok}")
        else:
            pos.append(tok)
    if cmd == "adopt" and pos and not a.get("file"):
        combos = [p for p in pos if COMBO_RE.match(p) and not os.path.isdir(p)]
        a["combo"] = combos[0] if combos else pos[0]
        pos.remove(a["combo"])
    if len(pos) > 1:
        raise Usage(f"unexpected argument {pos[1]!r}")
    used = {k for k, v in a.items() if v not in (None, False)}
    extra = used - ALLOWED[cmd]
    if extra:
        raise Usage(f"{cmd} does not take --{sorted(extra)[0].replace('_', '-')}")
    return cmd, (pos[0] if pos else "."), a


def main(argv):
    if any(t in ("--help", "-h") for t in argv):
        out(HELP)
        return 0
    try:
        cmd, d, a = parse(argv)
        if cmd != "init" and not os.path.isdir(d):
            raise Fatal(f"board folder missing: {d}")
        return COMMANDS[cmd](d, a)
    except Usage as exc:
        print(f"design-board: {exc}\n\n{HELP}", file=sys.stderr)
        return 64
    except Failed as exc:
        out(str(exc))
        return 1
    except Fatal as exc:
        print(f"design-board: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
