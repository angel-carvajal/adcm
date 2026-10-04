#!/usr/bin/env python3
"""status_digest.py - "where did we leave off?" for a project brain, without reading task.md.

Reads <brain>/task.md (+ git + the artifact-courier preflight) and prints a digest of at most
--lines (40) lines, each cut to --width (160) chars with an ellipsis. Read-only, stdlib only,
Python >= 3.8, deterministic (no clock, stable ordering, UTF-8 stdout). The main session reads
this digest instead of the tracker; when the tracker does not parse (exit 2) one Sonnet agent
with status-brief.md produces the same layout.

Usage
  status_digest.py --brain DOCS_DIR [--module REL] [--lines 40] [--width 160] [--json]
                   [--entry [K]] [--no-git] [--courier PATH] [--version]
  --module REL   read <brain>/REL/task.md and pass `--module REL` to the preflight (no `..`)
  --width N      N >= 60; the DIGEST line is never cut
  --entry [K]    the K-th most recent logbook entry (default 1): <= 40 lines, the last one is
                 `ENTRY K/N @La-b · <status>`; K beyond N is a usage error
  --json         same data as one JSON object; its "text" key holds the plain lines
  --courier P    courier_preflight.py to run; default <script_dir>/../../artifact-courier/scripts/
                 courier_preflight.py, then <brain>/scripts/courier_preflight.py, then the newest
                 installed adcm-toolkits copy (highest version dir in the plugin cache of
                 $CLAUDE_CONFIG_DIR, else of ~/.claude*; the path is built from parts on purpose)

Exit codes
  0 ok        header, wave map and logbook section parsed
  1 partial   H1 missing, or exactly one of {wave map, logbook} missing or unreadable: rows with an
              id but no status glyph (`k unparsed rows`), or only undated `###` headings in the
              logbook (`k undated headings`) count as missing (digest still printed)
  2 unparsed  no task.md / TASKS.md only / not a regular file / > 20 MB / empty / wave map and
              logbook both missing / --module not found / internal error
  64 usage    bad flags (argparse's own exit 2 would trigger the fallback)
  Problems with git, pending items or artifacts never change the code; they show on their line.

Layout (fixed order; a line is left out when its data does not exist)
  STATUS <Project> — <subtitle>          brain <dir>[ · module REL][ · modules: a, b (use --module)]
  git <branch> <sha7> <date> "<subject>" · clean|dirty n · unpushed n|?[ · worktree|submodule]
      (git: none = not a repo, git: off = --no-git, git ? = git failed or timed out)
  WAVES N: ✅ a · 🔄 b · ⛔ c (tag n) ...[ · k irregular rows][ · k unparsed rows], <=3 🔄 / <=3 ⛔ lines
  NEXT ☐ ready: <ids> | none ready (waiting on <ids>)
  LAST LOG <date>[ (sfx)] · <wave>[ · PARTIAL][ · STOP] · @L<a>-<b>[ · order ...], heading,
    next/blocked/agents, 2 `prev:` lines  |  LAST LOG none yet[ · k undated headings]
  PENDING-HUMAN <open>/<total> open · <shape> · §"<section>" | ? · §"<section>" unparsed | none tracked
  RESUME <first bullet of "Punto de retomada">
  ARTIFACTS <preflight --summary line> | no registry | preflight not found | preflight error (exit n)
  DIGEST: ok | partial(<header,waves,logbook>) | unparsed (<reason>)          (always last)
Over --lines the digest sheds, in order: prev, RESUME, pending > 3, blocked > 1, in-progress > 1,
the heading line of LAST LOG, then everything except the never-cut lines: STATUS, git, WAVES,
LAST LOG, PENDING-HUMAN, ARTIFACTS and DIGEST (printed even when --lines is smaller).
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import unicodedata

__version__ = "0.15.1"

KNOWN = "✅⛔⏸🔄☐🔀🔬"  # keep in sync with plans-regen.py GL ('✅⛔⏸🔄☐'), which this set extends
GLYPH_ORDER = KNOWN[0] + KNOWN[3] + KNOWN[1:3] + KNOWN[4:]  # display order: done, doing, blocked, paused, ...
FE0F = "️"
MAX_BYTES = 20 * 1024 * 1024
REGISTRY_CANDIDATES = ("artifacts.json", "ai/ai-brain/artifacts.json", "ai-brain/artifacts.json")
GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
GIT_ENV.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
SECTION_KINDS = (  # first match wins, so the logbook is never mistaken for a pending list
    ("log", r"(?:logbook|bitacora)\b|log$"),
    ("waves", r"(?:wave map|mapa de olas|olas)\b"),
    ("resume", r"(?:punto de retomada|resume point|where we left off|donde nos quedamos)"),
    ("pending", r"(?:dod-human|bloqueante|blocker|pendiente|pending|preguntas abiertas|open questions)"),
)
LABELS = (  # normalised label prefix -> entry field
    ("next", ("next", "siguiente")),
    ("blocked", ("blocked", "blocker", "bloquead", "bloqueo", "dod-human", "abierto")),
    ("agents", ("agents used", "agentes usados")),
    ("closed", ("tasks closed", "tareas cerradas", "tasks cerradas")),
    ("branch", ("branch/mr", "branch", "rama")),
)
ENTRY = re.compile(r"###\s+(\d{4}-\d{2}-\d{2})(?:\s*\((\d{1,3}|[a-z])\))?\s*[—–-]?\s*(.*)$")
BULLET = re.compile(r"\s*[-*]\s+\*\*(.+?)\*\*\s*:?\s*(.*)$")
INLINE = re.compile(r"\s+·\s+\*\*([^*]+?)\*\*\s*:?\s*")
BOLD_ID = re.compile(r"\*\*(?:(?:Wave|Ola)\s+)?([^\s*]+)")
LOOSE_ID = re.compile(r"\s*(?:(?:Wave|Ola)\s+)?([A-Za-z][\w/-]*\d[\w/-]*)")
CHECK = re.compile(r"\s*[-*+]\s+\[([ xX])\]\s+(.*)$")
EMPTYISH = re.compile(r"(?:none|n/a|na|nada|nothing|ninguno|ninguna|no blockers?|sin bloqueos?|—|–|-)(?=\s*$|\s*[.,;:(]|\s+[—–-])", re.I)  # a dash only after a space: "NA-12 vendor down" is a real item
EMPTY_WORDS = frozenset("none ninguno ninguna nada n/a na nothing right now for por ahora yet currently todavia "
                        "todavía hasta — – -".split())
NOT_A_WAVE = re.compile(r"(?:sub)?totals?|suma|legend|leyenda", re.I)
PLACEHOLDER = re.compile(r"\{[^{}\n]+\}|<[^>\n]*>")  # {{x}}, {x} and <x> template placeholders
HR = re.compile(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
MUST = re.compile(r"(?:STATUS|git|WAVES|NEXT|LAST LOG|PENDING-HUMAN|ARTIFACTS|DIGEST:)")


# ---------------------------------------------------------------- helpers copied from plans-regen.py
def plain(s):
    """Markdown stripped to text: links, ** and ~~ and backtick markers, paired *em*; a lone `*` stays."""
    s = re.sub(r'\[([^\]\n]{0,300})\]\([^)\n]{0,300}\)', r'\1', s)
    s = re.sub(r'\*\*|~~|`', '', s)
    return re.sub(r'(?<![\w*])\*(?=\S)([^*\n]*?\S)\*(?![\w*])', r'\1', s).strip()


def norm(s):
    """Lower-case ASCII (accents and glyphs dropped) with collapsed spaces."""
    s = unicodedata.normalize('NFKD', s.lower()).encode('ascii', 'ignore').decode()
    return ' '.join(s.split())


FENCE = re.compile(r'^(`{3,}|~{3,})')


def fence_next(ln, fence):
    """Fence state after this line: opening marker, or None when closed/outside."""
    s = ln.strip()
    if fence is None:
        m = FENCE.match(s)
        return m.group(1) if m else None
    return None if set(s) == {fence[0]} and len(s) >= len(fence) else fence


def cells(row):
    row = row.strip()
    row = row[1:] if row.startswith('|') else row
    row = row[:-1] if row.endswith('|') and not row.endswith('\\|') else row
    out, cur, tick, k = [], '', False, 0
    while k < len(row):
        ch = row[k]
        if ch == '\\' and row[k + 1:k + 2] == '|':
            cur, k = cur + '|', k + 2
            continue
        tick ^= ch == '`'
        if ch == '|' and not tick:
            out.append(cur.strip())
            cur = ''
        else:
            cur += ch
        k += 1
    return out + [cur.strip()]


def is_sep(c):
    return bool(c) and all(re.fullmatch(r':?-+:?', x) for x in c)


def tables(lines):
    """Every pipe table in the lines as cell rows (separator dropped, header first)."""
    out, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith('|'):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith('|'):
                j += 1
            out.append([c for c in map(cells, lines[i:j]) if not is_sep(c)])
            i = j
        else:
            i += 1
    return out


def strip_comments(text):
    """Lines of text with HTML comments and fenced blocks blanked; the line count is preserved.
    A comment opens only when `<!--` starts the line (<= 3 spaces); a mid-line `<!--` is text."""
    out, fence, cmt = [], None, False
    for ln in text.split('\n'):
        if fence is None:
            while cmt or re.match(r' {0,3}<!--', ln):
                end = ln.find('-->', 0 if cmt else ln.index('<!--') + 4)
                if end < 0:
                    cmt, ln = True, ''
                    break
                cmt, ln = False, ln[end + 3:]
        nxt = fence_next(ln, fence)
        out.append('' if fence is not None or nxt is not None else ln)
        fence = nxt
    return out


# ---------------------------------------------------------------- small utilities
def tidy(s):
    """plain() text (input cut to 4k chars) with U+FE0F removed and every whitespace run collapsed."""
    return ' '.join(plain(s[:4000]).replace(FE0F, '').split())


def clip(s, n):
    return s if len(s) <= n else s[:max(n - 1, 0)].rstrip() + '…'


def col(header, *pats):
    """Index of the first normalised header cell matching one of the patterns, else None."""
    for i, h in enumerate(header):
        if any(re.match(p, h) for p in pats):
            return i
    return None


def glyph_of(cell):
    """(glyph, tag) from a status cell: first symbol after '*', U+FE0F and spaces; tag = next <=3 words."""
    s = cell.replace(FE0F, '').lstrip('*_~ \t')
    if not s:
        return None
    ch = s[0]
    if ch in KNOWN:
        g = ch
    elif ord(ch) > 0x2000 and unicodedata.category(ch) == 'So':
        g = 'other:' + ch
    else:
        return None
    words = re.findall(r'[^\W\d_][\w-]*', tidy(s[1:]).lower())
    return g, (' '.join(words[:3]) or None)


def first_glyph(cs):
    return next((g for g in map(glyph_of, cs) if g), None)


def wave_id(cell):
    """(id, end offset) of the first bold id in a cell: handles `Wave W1`, `W8 — X`, `W10:`, `OPS/métricas`."""
    for m in BOLD_ID.finditer(cell):
        tok = re.split(r'[—–]', m.group(1), maxsplit=1)[0].rstrip('—–,(:;.')
        if tok and tok[0].isalnum():
            return tok, m.start(1) + len(tok)
    return None


def id_rx(ids):
    """Regex matching any known wave id as a whole token, longest id first (never matches without ids)."""
    alt = '|'.join(re.escape(i) for i in sorted(ids, key=len, reverse=True))
    return r'(?<![\w-])(?:%s)(?![\w-])' % alt if alt else r'(?!)'


CONNECTORS = re.compile(r'\b(?:and|y|e|none|ninguna?|n/a|na)\b', re.I)


def parse_deps(text, order, tok):
    """(known dependency ids in text order, has_other_text). Expands `Wa–Wb` / `Wa..Wb` in map order."""
    t = tidy(text)
    rx = re.compile(r'(%s)\s*(?:–|—|\.\.+|…)\s*(%s)|(%s)' % (tok, tok, tok))
    deps = []
    for m in rx.finditer(t):
        a, b, one = m.groups()
        if one:
            span = [one]
        elif order.index(a) <= order.index(b):
            span = order[order.index(a):order.index(b) + 1]
        else:
            span = [a, b]
        deps.extend(x for x in span if x not in deps)
    return deps, bool(re.search(r'[^\W_]', CONNECTORS.sub(' ', rx.sub(' ', t))))


# ---------------------------------------------------------------- sections, header
def sections(lines):
    secs = [{'level': len(m.group(1)), 'heading': tidy(m.group(2)), 'start': i, 'kind': None, 'norm': ''}
            for i, ln in enumerate(lines) for m in [re.match(r'(#{1,2})\s+(.*)$', ln)] if m]
    for k, s in enumerate(secs):
        s['end'] = secs[k + 1]['start'] if k + 1 < len(secs) else len(lines)
        if s['level'] == 2:
            s['norm'] = re.sub(r'^[^a-z]+', '', norm(s['heading']))
            s['kind'] = next((kind for kind, rx in SECTION_KINDS if re.match(rx, s['norm'])), None)
    if not any(s['kind'] == 'log' for s in secs):  # "Log de decisiones" only counts when no real logbook exists
        for s in secs:
            if s['level'] == 2 and s['kind'] is None and re.match(r'log\b', s['norm']):
                s['kind'] = 'log'
    return secs


def parse_header(lines, secs):
    stop = next((s['start'] for s in secs if s['level'] == 2), len(lines))
    for ln in lines[:stop]:
        m = re.match(r'#\s+(\S.*)$', ln)
        if m:
            a, sep, b = tidy(m.group(1)).partition(' — ')
            return a.strip(), (b.strip() or None) if sep else None
    return None, None


# ---------------------------------------------------------------- wave map
def wave_header(row):
    """Column indexes of a wave-map header (cell test `wave|ola`, no glyph, >= 4 columns) or None."""
    if len(row) < 4 or re.search('[%s]' % KNOWN, ' '.join(row)):
        return None
    h = [norm(plain(c)) for c in row]
    wave = col(h, r'.*\b(?:wave|ola)\b')
    if wave is None:
        return None
    return {'wave': wave, 'status': col(h, r'(?:status|estado)'), 'tasks': col(h, r'(?:tasks|tareas)'),
            'gate': col(h, r'gate'), 'depends': col(h, r'(?:depends|depende)')}


def wave_row(c, ix, n):
    """Row dict (glyph None when the id has no recognisable status glyph) or None when there is no id."""
    if len(c) == n:
        gl = (glyph_of(c[ix['status']]) if ix['status'] is not None else None) or first_glyph(c[:2])
        wi = ix['wave']
        wid = wave_id(c[wi])
        bold = wid is not None
        if wid is None:
            m = LOOSE_ID.match(tidy(c[wi]))
            wid = (m.group(1), m.end()) if m else None
            base = tidy(c[wi])
        else:
            base = c[wi]
        tasks = c[ix['tasks']] if ix['tasks'] is not None else (c[wi + 1] if wi + 1 < n else '')
        gate = c[ix['gate']] if ix['gate'] is not None else ''
        dep = c[ix['depends']] if ix['depends'] is not None else ''
        irregular = False
    else:  # 5/8/9-cell rows: glyph in cells 0-1, id in cells 0-2, depends = last cell
        gl = first_glyph(c[:2])
        wi, wid, base = next(((k, wave_id(x), x) for k, x in enumerate(c[:3]) if wave_id(x)), (0, None, ''))
        bold = True
        tasks = c[wi + 1] if wi + 1 < len(c) else ''
        g = c[wi + 2] if wi + 2 < len(c) else ''
        gate = g if re.match(r'\s*(?:—|-|⚠|⛔)', plain(g)) else ''
        dep = c[-1] if ix['depends'] is not None else ''
        irregular = True
    if wid is None or (gl is None and (not bold or NOT_A_WAVE.fullmatch(wid[0]))):
        return None  # no id; a glyphless row counts as unparsed only with a bold id that is not a Total/legend row
    tid, end = wid
    gate = tidy(gate)
    return {'id': tid, 'glyph': gl[0] if gl else None, 'tag': gl[1] if gl else None,
            'title': tidy(base[end:]).lstrip(' —–:,-')[:120], 'tasks': tidy(tasks)[:200],
            'gate': None if gate in ('', '—', '-') else gate, 'dep': dep, 'irregular': irregular}


def parse_waves(lines, secs):
    chunks = [lines[s['start'] + 1:s['end']] for s in secs if s['kind'] == 'waves'] or [lines]
    allrows, seen = [], set()
    for chunk in chunks:
        for tb in tables(chunk):
            ix = wave_header(tb[0]) if len(tb) > 1 else None
            for c in (tb[1:] if ix else []):
                r = wave_row(c, ix, len(tb[0]))
                if r and r['id'] not in seen:
                    seen.add(r['id'])
                    allrows.append(r)
    order = [r['id'] for r in allrows]  # glyphless ids stay known: dependencies on them are unmet
    tok = id_rx(order)
    for r in allrows:
        r['depends'], r['cond'] = parse_deps(r.pop('dep'), order, tok)
    rows = [r for r in allrows if r['glyph']]
    bad = [r['id'] for r in allrows if not r['glyph']]
    state = {r['id']: r['glyph'] for r in rows}
    waiting = set()
    for r in rows:
        unmet = [d for d in r['depends'] if state.get(d) != '✅'] if r['glyph'] == '☐' else None
        r['ready'] = unmet is not None and not unmet
        waiting.update(unmet or [])
    by, tags = {}, {}
    for r in rows:
        by[r['glyph']] = by.get(r['glyph'], 0) + 1
        if r['tag']:
            tags.setdefault(r['glyph'], {})[r['tag']] = tags.get(r['glyph'], {}).get(r['tag'], 0) + 1
    glyphs = [g for g in GLYPH_ORDER if g in by] + sorted(g for g in by if g not in GLYPH_ORDER)
    return {'count': len(rows), 'by_glyph': {g: by[g] for g in glyphs}, 'tags': tags,
            'irregular': sum(r['irregular'] for r in rows), 'unparsed': len(bad), 'unparsed_ids': bad,
            'rows': rows, 'ready': [r['id'] for r in rows if r['ready']],
            'waiting_on': [i for i in order if i in waiting]}


# ---------------------------------------------------------------- logbook
def sfx_key(s):
    return 0 if not s else int(s) if s.isdigit() else ord(s) - 96


def parse_bullets(body):
    """{next, blocked, closed: [str], branch: str|None, agents: dict|None} from the entry's labelled bullets."""
    items, cur = [], None
    for ln in body:
        ln = ln[:4000]
        m = BULLET.match(ln)
        if m:
            cur = [m.group(1), m.group(2).strip()]
            items.append(cur)
        elif cur is not None and ln.startswith(('  ', '\t')) and ln.strip():
            cur[1] = (cur[1] + ' ' + re.sub(r'^[-*]\s+', '', ln.strip())).strip()
        else:
            cur = None
    out = {'next': [], 'blocked': [], 'closed': [], 'branch': None, 'agents': None}
    for label, value in items:
        parts = INLINE.split(value)
        for lab, val in [(label, parts[0])] + list(zip(parts[1::2], parts[2::2])):
            key = re.sub(r'\([^)]*\)', '', norm(plain(lab))).strip().rstrip(':').strip()
            field = next((f for f, pre in LABELS if key.startswith(pre)), None)
            val = tidy(val)
            if field == 'agents':
                m = re.search(r'(\d+)\s*/\s*(\d+)', val)
                if m:
                    o, s = re.search(r'opus\s+(\d+)', val), re.search(r'sonnet\s+(\d+)', val)
                    out['agents'] = {'used': int(m.group(1)), 'budget': int(m.group(2)),
                                     'opus': int(o.group(1)) if o else None, 'sonnet': int(s.group(1)) if s else None}
            elif field == 'branch':
                out['branch'] = out['branch'] or val or None
            elif field and val and not (field == 'blocked' and EMPTYISH.match(val)):
                out[field].append(val)
    return out


def entry_wave(rest, tok):
    """Wave of a logbook heading: the first known id, longest match (ABC-12 / T-W9-3 are not in the map)."""
    m = re.search(tok, rest)
    return m.group(0) if m else None


def parse_log(lines, secs, ids):
    logs = [s for s in secs if s['kind'] == 'log']
    regions = [(s['start'] + 1, s['end']) for s in logs] or [(0, len(lines))]
    es, undated = [], 0
    for lo, hi in regions:
        cur = None
        for i in range(lo, hi):
            m = ENTRY.match(lines[i])
            if m:
                cur = {'i': i, 'end': i, 'date': m.group(1), 'suffix': m.group(2), 'rest': m.group(3)}
                es.append(cur)
            elif re.match(r'\s{0,3}#{1,6}\s', lines[i]):
                head = re.match(r'\s{0,3}(#{1,6})\s', lines[i]).group(1)
                looks_dated = re.search(r'\d|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|ene|abr|ago|dic)\w*', lines[i], re.I)
                undated += bool(logs and len(head) >= 3 and looks_dated and not PLACEHOLDER.search(lines[i]))  # '#### Files' is a subsection, not a lost entry
                cur = None if len(head) <= 3 else cur
            elif cur is not None and lines[i].strip() and not HR.match(lines[i]):
                cur['end'] = i
    keys = [(e['date'], sfx_key(e['suffix'])) for e in es]
    up = any(b > a for a, b in zip(keys, keys[1:]))
    down = any(b < a for a, b in zip(keys, keys[1:]))
    order = 'none' if not es else 'single' if len(es) == 1 else 'mixed' if up and down else \
        'oldest-first' if up else 'newest-first' if down else 'ambiguous'
    later = order in ('oldest-first', 'mixed', 'ambiguous')  # ties: the later line is the newer (append)
    ranked = sorted(range(len(es)), key=lambda p: (keys[p], p if later else -p), reverse=True)
    tok = id_rx(ids)
    out = []
    for p in ranked:
        e = es[p]
        title = tidy(e['rest'])
        head = tidy(lines[e['i']][3:])
        d = {'date': e['date'], 'suffix': e['suffix'], 'heading': head, 'title': title,
             'wave': entry_wave(title, tok), 'partial': bool(re.search(r'\b(?:PARTIAL|PARCIAL)\b', head)),
             'stop': bool(re.search(r'\[STOP\]|(?:^|\s)STOP$', head)), 'lines': [e['i'] + 1, e['end'] + 1]}
        if not out:  # only the newest entry needs its labelled bullets
            d.update(parse_bullets(lines[e['i'] + 1:e['end'] + 1]))
        out.append(d)
    return {'found': bool(logs or es), 'order': order, 'entries': len(es), 'undated': undated,
            'last': out[0] if out else None, 'prev': [{k: v for k, v in x.items() if k in (
                'date', 'suffix', 'heading', 'title', 'wave', 'partial', 'stop', 'lines')} for x in out[1:3]],
            'all': out}


# ---------------------------------------------------------------- pending human actions, resume
def pend_item(raw, ref=None, blocks=None, resolved=None):
    s = raw.strip().lstrip('*_ ')
    res = s.startswith(('~~', '✅')) if resolved is None else resolved
    t = tidy(raw)
    hard = t.startswith('⛔') and not res
    t = re.sub(r'[\s✅]+$', '', re.sub(r'^[⛔✅\s]+', '', t))
    blocks = tidy(blocks or '')
    return {'ref': ref or None, 'text': t, 'blocks': None if blocks in ('', '—', '-') else blocks,
            'resolved': res, 'hard': hard}


def pend_table(body):
    """(shape, items) of the first table with a known header; a header-only table is that shape with no items."""
    header_only = None
    for tb in tables(body):
        h = [norm(plain(c)) for c in tb[0]]
        c_blk = col(h, r'(?:bloquea|blocks)\b')
        c_item, shape = col(h, r'(?:que|what)\b'), 'table/Qué-Bloquea'
        if c_item is None or c_blk is None:
            c_item, shape = col(h, r'item\b'), 'table/Ítem-Dueño'
            if c_item is None or col(h, r'(?:dueno|owner)\b') is None:
                continue
        c_ref = col(h, r'(?:#|no\.?|id|num\w*)$')
        items = []
        for c in tb[1:]:
            get = lambda k: c[k] if k is not None and k < len(c) else ''
            if get(c_item).strip():
                items.append(pend_item(get(c_item), plain(get(c_ref)) or None, get(c_blk)))
        if items:
            return shape, items
        header_only = header_only or (shape, [])
    return header_only


def pend_checklist(body):
    raws = []
    for ln in body:
        m = CHECK.match(ln)
        if m:
            raws.append([m.group(2), m.group(1) != ' '])
        elif raws and ln.startswith(('  ', '\t')) and ln.strip():
            raws[-1][0] += ' ' + ln.strip()
    return ('checklist', [pend_item(r, resolved=done) for r, done in raws]) if raws else None


def empty_body(body):
    """True when a section body holds only 'nothing here' words (None / ninguno / n/a / — / None right now.)."""
    words = re.findall(r'[^\W_]+(?:/[^\W_]+)?|[—–-]', tidy(re.sub(r'(?m)^\s*[-*+]\s+', '', '\n'.join(body))).lower())
    return bool(words) and all(w in EMPTY_WORDS for w in words)


def parse_pending(lines, secs, last):
    found, odd, empty = [s for s in secs if s['kind'] == 'pending'], None, None
    for s in found:
        body = lines[s['start'] + 1:s['end']]
        got = pend_table(body) or pend_checklist(body)
        if got:
            return {'shape': got[0], 'open': sum(not i['resolved'] for i in got[1]), 'total': len(got[1]),
                    'section': s['heading'], 'items': got[1]}
        if empty_body(body):
            empty = empty or s  # the section says there is nothing pending
        else:
            odd = odd or s
    if odd:  # a pending section exists but matches none of the known shapes: say so, do not guess
        return {'shape': 'unparsed', 'open': None, 'total': None, 'section': odd['heading'], 'items': []}
    if empty:
        return {'shape': 'none', 'open': 0, 'total': 0, 'section': empty['heading'], 'items': []}
    items = [pend_item(b) for b in (last['blocked'] if last else [])]
    return {'shape': 'logbook-fallback' if items else 'none', 'open': len(items), 'total': len(items),
            'section': None, 'items': items}


def parse_resume(lines, secs):
    for s in secs:
        if s['kind'] != 'resume':
            continue
        body = lines[s['start'] + 1:s['end']]
        for k, ln in enumerate(body):
            m = re.match(r'\s*(?:[-*+]|\d+[.)])\s+(.*)$', ln)
            if m:
                text = m.group(1)
                for nxt in body[k + 1:]:
                    if not nxt.strip() or not nxt.startswith(('  ', '\t')) or re.match(r'\s*(?:[-*+]|\d+[.)])\s', nxt):
                        break
                    text += ' ' + nxt.strip()
                return tidy(text) or None
        para = next((x for x in body if x.strip() and not x.lstrip().startswith(('|', '>'))), None)
        return tidy(para) if para else None
    return None


# ---------------------------------------------------------------- git, artifacts
def run(cmd, timeout=5, env=None):
    """(rc, stdout, stderr); rc is None when the command could not run (stderr 'missing'/'failed') or timed out."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return None, '', 'missing'
    except subprocess.TimeoutExpired:
        return None, '', 'timeout'
    except (OSError, subprocess.SubprocessError):
        return None, '', 'failed'
    return p.returncode, p.stdout, p.stderr


def git_info(path):
    """kind: repo|worktree|submodule, none (not a repo / no git), unknown (git failed or timed out)."""
    info = {'kind': 'unknown', 'branch': None, 'sha': None, 'date': None, 'subject': None, 'head': None,
            'dirty': None, 'unpushed': None}

    hung = []

    def git(*a):
        if hung:  # one timeout is enough: the remaining fields stay unknown instead of costing 5 s each
            return None, 'timeout'
        rc, out, err = run(['git', '-C', path] + list(a), env=GIT_ENV)
        if rc is None:
            hung.append(1)
        return (out.strip() if rc == 0 else None), err.lower()

    top, err = git('rev-parse', '--show-toplevel')
    if not top:
        info['kind'] = 'none' if err == 'missing' or 'not a git repository' in err else 'unknown'
        return info
    info['kind'] = 'repo'
    try:
        with open(os.path.join(top, '.git'), encoding='utf-8', errors='replace') as fh:
            ref = fh.read().replace('\\', '/')
        info['kind'] = 'worktree' if '/worktrees/' in ref else 'submodule' if '/modules/' in ref else 'repo'
    except OSError:
        pass
    info['branch'] = git('rev-parse', '--abbrev-ref', 'HEAD')[0] or git('symbolic-ref', '--short', '-q', 'HEAD')[0]
    log, err = git('log', '-1', '--format=%h%x09%cs%x09%s')
    if log:
        info['sha'], info['date'], info['subject'] = (log.split('\t', 2) + ['', ''])[:3]
    info['head'] = 'ok' if log else 'none' if 'any commits yet' in err or 'bad default revision' in err else 'unknown'
    status = git('status', '--porcelain')[0]
    info['dirty'] = len(status.splitlines()) if status is not None else None
    ahead = git('rev-list', '--count', '@{u}..HEAD')[0]
    info['unpushed'] = int(ahead) if ahead and ahead.isdigit() else None
    return info


def installed_courier():
    """Newest installed plugin copy of courier_preflight.py, or None (highest version dir wins)."""
    env = os.environ.get('CLAUDE_CONFIG_DIR')
    roots = [os.path.expanduser(env)] if env else sorted(glob.glob(os.path.expanduser('~/.claude*')))
    found = []
    for root in roots:
        pat = os.path.join(glob.escape(root), 'plugins', 'cache', '*', 'adcm-toolkits', '*',
                           'skills', 'artifact-courier', 'scripts', 'courier_preflight.py')
        for path in glob.glob(pat):
            if os.path.isfile(path):
                ver = os.path.basename(os.path.normpath(os.path.join(os.path.dirname(path), '..', '..', '..')))
                if re.fullmatch(r'\d+(?:\.\d+)+', ver):  # hash or other dirs never win
                    found.append((tuple(int(x) for x in ver.split('.')), path))
    return max(found)[1] if found else None


def artifacts_info(brain, module, courier_arg):
    def res(state, code, line):
        return {'state': state, 'exit': code, 'line': line}

    if not any(os.path.isfile(os.path.join(brain, *r.split('/'))) for r in REGISTRY_CANDIDATES):
        return res('no-registry', None, 'no registry')
    here = os.path.dirname(os.path.abspath(__file__))
    if courier_arg:
        cands = [os.path.abspath(os.path.expanduser(courier_arg))]
    else:
        cands = [os.path.normpath(os.path.join(here, '..', '..', 'artifact-courier', 'scripts', 'courier_preflight.py')),
                 os.path.join(brain, 'scripts', 'courier_preflight.py')]
    courier = next((p for p in cands if os.path.isfile(p)), None) or (None if courier_arg else installed_courier())
    if courier is None:
        return res('not-found', None, 'preflight not found (pass --courier)')
    rc, out, _ = run([sys.executable, courier, brain, '--summary'] + (['--module', module] if module else []),
                     timeout=15)
    if rc != 0:
        return res('error', rc, 'preflight error (exit %s)' % ('?' if rc is None else rc))
    line = next((x for x in out.splitlines() if x.strip()), '')
    return res('ok', 0, ' '.join((line.partition('courier-preflight:')[2] or line).split()) or 'no output')


# ---------------------------------------------------------------- analysis
def list_modules(brain):
    base = os.path.join(brain, 'modules')
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    out = []
    for n in names:
        try:
            if 'task.md' in os.listdir(os.path.join(base, n)):
                out.append('modules/' + n)
        except OSError:
            pass
    return out


def analyse(text):
    """Pure parse of task.md text; git, artifacts and module info are filled in by the caller."""
    lines = strip_comments(text)
    secs = sections(lines)
    title, subtitle = parse_header(lines, secs)
    waves = parse_waves(lines, secs)
    log = parse_log(lines, secs, [r['id'] for r in waves['rows']])
    last = log['last']
    missing = [k for k, ok in (
        ('header', title is not None),
        ('waves', waves['count'] > 0 and not waves['unparsed']),
        ('logbook', log['found'] and not (log['undated'] and not log['entries']))) if not ok]
    unparsed = 'waves' in missing and 'logbook' in missing
    return {
        'version': __version__, 'status': 'unparsed' if unparsed else 'partial' if missing else 'ok',
        'missing': missing, 'reason': 'no usable wave map and logbook' if unparsed else None,
        'project': {'title': title, 'subtitle': subtitle, 'module': None, 'modules': []},
        'git': None,
        'waves': {k: waves[k] for k in ('count', 'by_glyph', 'tags', 'irregular', 'unparsed', 'unparsed_ids', 'rows')},
        'ready': waves['ready'], 'waiting_on': waves['waiting_on'],
        'logbook': {'order': log['order'], 'entries': log['entries'], 'undated': log['undated'],
                    'last': last, 'prev': log['prev']},
        'pending': parse_pending(lines, secs, last), 'resume': parse_resume(lines, secs),
        'artifacts': None, '_entries': log['all'],
    }


# ---------------------------------------------------------------- rendering
def brain_line(brain, module, modules, width):
    tail = ''
    if module:
        tail = ' · module ' + module
    elif modules:
        names = [os.path.basename(m) for m in modules]
        tail = ' · modules: %s%s (use --module)' % (', '.join(names[:6]), ' +%d' % (len(names) - 6) if len(names) > 6 else '')
    room = max(width - len('brain ') - len(tail), 2)
    return 'brain ' + (brain if len(brain) <= room else '…' + brain[-(room - 1):]) + tail


def git_line(g):
    if g['kind'] in ('off', 'none'):
        return 'git: ' + g['kind']
    if g['kind'] == 'unknown':
        return 'git ?'
    num = lambda v: '?' if v is None else str(v)
    head = {'ok': '%s %s "%s"' % ((g['sha'] or '')[:7], g['date'], clip(g['subject'] or '', 60)),
            'none': 'no commits'}.get(g['head'], 'log ?')
    tail = ' · %s · unpushed %s' % ('clean' if g['dirty'] == 0 else 'dirty ' + num(g['dirty']), num(g['unpushed']))
    return 'git %s %s%s%s' % (g['branch'] or '?', head, tail, '' if g['kind'] == 'repo' else ' · ' + g['kind'])


def entry_tag(e):
    return e['date'] + (' (%s)' % e['suffix'] if e['suffix'] else ''), e['wave'] or '—'


def waves_lines(R, trim):
    w, rows = R['waves'], R['waves']['rows']
    bad = ' · %d unparsed rows' % w['unparsed'] if w['unparsed'] else ''
    if not rows:
        return ['WAVES 0: none parsed' + bad]
    parts = []
    for g, n in w['by_glyph'].items():
        tg = w['tags'].get(g)
        parts.append('%s %d%s' % (g.replace('other:', ''), n, ' (%s)' % ', '.join(
            '%s %d' % kv for kv in sorted(tg.items())) if tg else ''))
    if w['irregular']:
        parts.append('%d irregular rows' % w['irregular'])
    out = ['WAVES %d: %s%s' % (w['count'], ' · '.join(parts), bad)]
    prog = [r for r in rows if r['glyph'] == '🔄']
    blocked = [r for r in rows if r['glyph'] == '⛔' and (not r['tag'] or re.search(r'blocked|bloquead|dod-human', r['tag']))]
    for glyph, group, keep in (('🔄', prog, 1 if trim >= 5 else 3), ('⛔', blocked, 1 if trim >= 4 else 3)):
        for r in group[:keep]:
            s = '  %s %s' % (glyph, r['id']) + (' ' + clip(r['title'], 40) if r['title'] else '')
            if glyph == '🔄' and r['tasks']:
                s += ' · ' + clip(r['tasks'], 80)
            if glyph == '⛔':
                if r['gate']:
                    s += ' · gate ' + clip(r['gate'].lstrip('⛔ '), 50)
                if r['depends']:
                    s += ' · deps ' + clip(', '.join(r['depends']), 20)
            out.append(s)
        if len(group) > keep:
            out.append('  %s +%d more' % (glyph, len(group) - keep))
    if R['ready']:
        out.append('NEXT ☐ ready: ' + ', '.join(r['id'] + (' (+cond)' if r['cond'] else '') for r in rows if r['ready']))
    elif any(r['glyph'] == '☐' for r in rows):
        out.append('NEXT ☐ none ready (waiting on %s)' % ', '.join(R['waiting_on']))
    else:
        out.append('NEXT ☐ none ready (no ☐ waves)')
    return out


def log_lines(R, width, trim):
    lg = R['logbook']
    last = lg['last']
    if not last:
        return ['LAST LOG none yet' + (' · %d undated headings' % lg['undated'] if lg['undated'] else '')]
    d, wv = entry_tag(last)
    out = ['LAST LOG %s · %s%s%s · @L%d-%d%s' % (
        d, wv, ' · PARTIAL' if last['partial'] else '', ' · STOP' if last['stop'] else '', last['lines'][0],
        last['lines'][1], ' · order ' + lg['order'] if lg['order'] in ('mixed', 'oldest-first', 'ambiguous') else '')]
    if lg['undated']:
        out[0] += ' · %d undated headings' % lg['undated']
    if trim < 6 and last['title']:
        out.append('  ' + clip(last['title'], 140))
    segs = []
    if last['next']:
        segs.append('next: ' + clip(' / '.join(last['next'][:2]), 70))
    if last['blocked']:
        segs.append('blocked: ' + clip(' / '.join(last['blocked'][:2]), 55))
    if last['agents']:
        a = last['agents']
        segs.append('agents: %d/%d%s' % (a['used'], a['budget'], ' (opus %d · sonnet %d)' % (
            a['opus'], a['sonnet']) if a['opus'] is not None and a['sonnet'] is not None else ''))
    cur = ''
    for sg in segs:
        cand = cur + '   ' + sg if cur else '  ' + sg
        if cur and len(cand) > width:
            out.append(cur)
            cand = '  ' + sg
        cur = cand
    if cur:
        out.append(cur)
    if trim < 1:
        for e in lg['prev']:
            d, wv = entry_tag(e)
            out.append('  prev: %s · %s%s%s' % (d, wv, ' · PARTIAL' if e['partial'] else '',
                                                 ' — ' + clip(e['title'], 80) if e['title'] else ''))
    return out


def pending_lines(R, trim):
    pe = R['pending']
    if pe['shape'] == 'none':
        return ['PENDING-HUMAN none tracked' + (' · §"%s"' % clip(pe['section'], 40) if pe['section'] else
                                                ' · from last log' if R['logbook']['last'] else '')]
    if pe['shape'] == 'unparsed':
        return ['PENDING-HUMAN ? · §"%s" unparsed' % clip(pe['section'], 40)]
    out = ['PENDING-HUMAN %d/%d open · %s · %s' % (pe['open'], pe['total'], pe['shape'], (
        '§"%s"' % clip(pe['section'], 40)) if pe['section'] else 'from last log')]
    todo = sorted((i for i in pe['items'] if not i['resolved']), key=lambda i: not i['hard'])
    keep = 3 if trim >= 3 else 6
    for i in todo[:keep]:
        out.append('  %s %s%s%s' % (i['ref'] or '•', '⛔ ' if i['hard'] else '', clip(i['text'], 90),
                                    ' → ' + clip(i['blocks'], 30) if i['blocks'] else ''))
    if len(todo) > keep:
        out.append('  +%d more' % (len(todo) - keep))
    return out


def build(R, width, trim):
    p = R['project']
    out = ['STATUS ' + (p['title'] + (' — ' + p['subtitle'] if p['subtitle'] else '') if p['title'] else R['_dirname']),
           brain_line(R['_brain'], p['module'], p['modules'], width), git_line(R['git'])]
    out += waves_lines(R, trim) + log_lines(R, width, trim) + pending_lines(R, trim)
    if R['resume'] and trim < 2:
        out.append('RESUME ' + clip(R['resume'], 140))
    out.append('ARTIFACTS ' + R['artifacts']['line'])
    out.append('DIGEST: ' + ('ok' if R['status'] == 'ok' else 'partial(%s)' % ','.join(R['missing'])))
    return out


def render(R, width, cap):
    """Shed optional lines level by level; if even level 6 is too long keep the never-cut lines and
    refill up to `cap` with the surviving optional lines in document order."""
    for trim in range(7):
        out = build(R, width, trim)
        if len(out) <= cap:
            break
    else:
        room = cap - sum(1 for x in out if MUST.match(x))
        optional = [i for i, x in enumerate(out) if not MUST.match(x)][:max(room, 0)]
        out = [x for i, x in enumerate(out) if MUST.match(x) or i in optional]
    return [x if x.startswith('DIGEST:') else clip(x, width) for x in out]


# ---------------------------------------------------------------- CLI
class Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would exit 2, which is the "unparsed" code
        self.print_usage(sys.stderr)
        sys.stderr.write('%s: error: %s\n' % (self.prog, message))
        sys.exit(64)


def at_least(minimum):
    def conv(v):
        try:
            n = int(v)
        except ValueError:
            raise argparse.ArgumentTypeError('not an integer: %r' % v)
        if n < minimum:
            raise argparse.ArgumentTypeError('must be >= %d: %r' % (minimum, v))
        return n
    return conv


def emit(args, data, lines, code):
    data['text'] = lines
    if args.json:
        print(json.dumps({k: v for k, v in data.items() if not k.startswith('_')}, ensure_ascii=False, indent=2))
    else:
        print('\n'.join(lines))
    return code


def emit_unparsed(args, brain, module, reason, missing=()):
    lines = [clip(brain_line(brain, module, [], args.width), args.width), 'DIGEST: unparsed (%s)' % reason]
    return emit(args, {'version': __version__, 'status': 'unparsed', 'missing': list(missing), 'reason': reason},
                lines, 2)


def internal_error(args, exc):
    """Any bug in the digest becomes the exit-2 unparsed block (the caller's fallback), never a traceback."""
    reason = 'internal error: %s' % type(exc).__name__[:30]
    try:
        return emit_unparsed(args, os.path.abspath(os.path.expanduser(args.brain)), args.module, reason)
    except Exception:
        print('DIGEST: unparsed (%s)' % reason)
        return 2


def run_digest(args):
    brain = os.path.abspath(os.path.expanduser(args.brain))
    module = args.module.strip('/') if args.module else None
    tdir = os.path.join(brain, module) if module else brain
    if not os.path.isdir(brain):
        return emit_unparsed(args, brain, module, 'brain dir not found')
    if not os.path.isdir(tdir):
        return emit_unparsed(args, brain, module, 'module dir not found: %s' % clip(module, 20))
    names = os.listdir(tdir)
    path = os.path.join(tdir, 'task.md')
    if 'task.md' not in names:
        return emit_unparsed(args, brain, module, 'unsupported format (TASKS.md, no task.md)'
                             if any(n.lower() == 'tasks.md' for n in names) else 'no task.md')
    if not os.path.isfile(path):
        return emit_unparsed(args, brain, module, 'task.md is not a regular file')
    if os.path.getsize(path) > MAX_BYTES:
        return emit_unparsed(args, brain, module, 'task.md is larger than 20 MB')
    with open(path, encoding='utf-8', errors='replace') as fh:
        text = fh.read().lstrip('﻿')
    if not text.strip():
        return emit_unparsed(args, brain, module, 'task.md is empty')
    R = analyse(text)
    if R['status'] == 'unparsed':
        return emit_unparsed(args, brain, module, R['reason'], R['missing'])
    R['project'].update(module=module, modules=list_modules(brain))
    R['_brain'], R['_dirname'] = brain, os.path.basename(tdir)
    if args.entry:
        es = R['_entries']
        if args.entry > len(es):
            sys.stderr.write('status_digest.py: error: --entry %d: only %d dated entries\n' % (args.entry, len(es)))
            return 64
        a, z = es[args.entry - 1]['lines']
        body = [clip(x, args.width) for x in text.split('\n')[a - 1:z]]
        if len(body) > 39:
            body = body[:38] + ['… +%d more lines' % (len(body) - 38)]
        body.append('ENTRY %d/%d @L%d-%d · %s' % (args.entry, len(es), a, z, R['status']))
        return emit(args, {'version': __version__, 'status': R['status'],
                           'entry': {'k': args.entry, 'n': len(es), 'lines': [a, z]}}, body, 0)
    R['git'] = {'kind': 'off'} if args.no_git else git_info(brain)
    R['artifacts'] = artifacts_info(brain, module, args.courier)
    return emit(args, R, render(R, args.width, args.lines), 0 if R['status'] == 'ok' else 1)


def main(argv=None):
    ap = Parser(prog='status_digest.py', allow_abbrev=False,
                description='Digest of a project brain: waves, last logbook entry, pending human actions.')
    ap.add_argument('--brain', required=True, help='docs dir holding task.md')
    ap.add_argument('--module', metavar='REL', help='module dir relative to --brain (modules/<m>)')
    ap.add_argument('--lines', type=at_least(1), default=40)
    ap.add_argument('--width', type=at_least(60), default=160)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--entry', nargs='?', const=1, type=at_least(1), metavar='K')
    ap.add_argument('--no-git', action='store_true')
    ap.add_argument('--courier', metavar='PATH')
    ap.add_argument('--version', action='version', version='status_digest.py ' + __version__)
    args = ap.parse_args(argv)
    if args.module and '..' in re.split(r'[\\/]+', args.module):
        ap.error('--module must not contain ".."')
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        return run_digest(args)
    except Exception as exc:
        return internal_error(args, exc)


if __name__ == '__main__':
    sys.exit(main())
