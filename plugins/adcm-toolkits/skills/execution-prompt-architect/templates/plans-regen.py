#!/usr/bin/env python3
"""Regenerate plans.html from the four plan docs (+ task.md for wave statuses).

plans.html is GENERATED: never hand-edit it, and the main session never renders it; it
only writes the .md docs. If page and docs disagree the docs win: rerun this script
(stdlib only, deterministic, idempotent, zero model tokens).

Sources, resolved inside --brain by ES/EN file name or named with --docs:
  proposal   propuesta-ejecutiva.md | executive-proposal.md
  master     plan-maestro.md        | master-plan.md
  detailed   plan-detallado.md      | detailed-plan.md
  timeframe  plan-timeframe.md      | timeframe-plan.md
  task.md    optional; its wave-map table is the ONLY source of wave status badges.

Only the inner HTML of <article id="doc-proposal|master|detailed|timeframe"> is patched.
<head>, styles, hero, theme and script stay byte-identical (the script builds the TOC
client-side from each article's .sec > h2, so there is no TOC markup to rewrite).
The shell is built from `plans-html.tmpl` (next to this script) automatically when <out> is
missing. An EXISTING <out> is never rewritten from the template unless you pass `--init --force`
(a hand-maintained page has no doc-* articles: keep its regen `none`, or rebuild it that way).
`--init` alone on an existing <out> exits 1 and leaves the file untouched.

Rules: `## x` -> <section class="sec" id="<p|m|d|t>-slug"><h2>; `## Wave|Ola <ID> ...` ->
id "<prefix>-<id>" + status badge (.ok/.pending/.blocked) from the task.md wave map, and
"⚠" -> badge.gate; `### T-...`/`### Tn` in the detailed plan -> .task card. Wave ids are
`[A-Z][A-Za-z0-9]*(-[A-Za-z0-9]+)*` (W0, WX, W2a, WC-V2, WSKILL-ARCH, WO-1, W18). The wave map takes
each id from the Wave/Ola column of its header (the first bold id-shaped token of the row only when
the header has no such column). In free text (Gantt, task ids) only ids known from the wave map or a
wave heading, or a digit-bearing id like W7, are recognised, longest first, so prose never yields a
false id and `W2a … W3` keeps W2a. HTML comments (docs and task.md) are removed, but a `<!--` inside
an inline code span or a fenced block is literal text and never opens one. Links with a quote,
whitespace or code span in the URL, and non-http(s)/mailto schemes, stay plain text. Timeframe
§0/§1 are located by their leading number ("1. T", "1) T" or "1 T"; first match wins).
§0+§1 become one "Schedule" section: §0 table, pure-CSS Gantt, §1 table. Weeks come from
§1's week column ("1-2", "Wk 3"), else §4 (one row = one period, wave ids in its waves
cell), else the dependency graph; streams from a §1 "stream" column, else lanes inherited
along dependency chains; milestones from §3; .g-today only if task.md shows execution
started. Everything else is mini-markdown (nested lists, [ ]/[x], pipe tables, fenced
code, blockquotes, inline code/bold/italic/strike/links).

Usage:
  python3 plans-regen.py <out.html> --brain <docs_dir> [--lang es|en] [--project NAME]
      [--docs proposal=F,master=F,detailed=F,timeframe=F] [--init [--force]] [--check]
--check writes nothing. Exit 0 = fresh; 1 = stale (a source or task.md is newer than <out>, the
regenerated articles differ, or <out> is missing); 3 = <out> exists but is hand-maintained (no
doc-* articles; message on stderr): keep its regen `none` or pass --init --force.
--init --force rewrites an existing <out> from the template; --init alone refuses (exit 1).
"""
import argparse
import html
import os
import pathlib
import re
import sys
import unicodedata

NAMES = {'proposal': ('propuesta-ejecutiva', 'executive-proposal'), 'master': ('plan-maestro', 'master-plan'),
         'detailed': ('plan-detallado', 'detailed-plan'), 'timeframe': ('plan-timeframe', 'timeframe-plan')}
PREFIX = {'proposal': 'p', 'master': 'm', 'detailed': 'd', 'timeframe': 't'}
GL = '✅⛔⏸🔄☐'
STATUS = {'✅': ('ok', 0), '⛔': ('blocked', 1), '⏸': ('blocked', 2), '🔄': ('pending', 3), '☐': ('pending', 4)}
WID = r'[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*'
WID_DIGIT = r'[A-Z][A-Z0-9]*-?\d[A-Z0-9-]*'  # prose-safe shape (W7): recognised in free text even when not in the wave map
BOLD = re.compile(r'\*\*(?:(?:Wave|Ola)\s+)?([^\s*—–:,(]+)[^*]*\*\*')
CODE_SPAN = re.compile(r'(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)')
STREAMS = ['var(--primary)', '#22C55E', '#F59E0B', '#EC4899', '#06B6D4']
LANG = {
    'es': {'nav': ['Propuesta ejecutiva', 'Plan maestro', 'Plan detallado'],
           'st': ['hecha', 'bloqueada', 'en pausa', 'en curso', 'pendiente'], 'sched': 'Cronograma',
           'wk': 'Sem', 'ses': 'sesiones', 'today': 'Hoy', 'mile': 'Hito', 'stream': 'Flujo'},
    'en': {'nav': ['Executive proposal', 'Master plan', 'Detailed plan'],
           'st': ['done', 'blocked', 'paused', 'in progress', 'pending'], 'sched': 'Schedule',
           'wk': 'Wk', 'ses': 'sessions', 'today': 'Today', 'mile': 'Milestone', 'stream': 'Stream'},
}

def esc(s):
    return html.escape(s, quote=False)

def attr(s):
    return html.escape(s, quote=True)

def plain(s):
    return re.sub(r'[*`~]|\[([^\]]*)\]\([^)]*\)', lambda m: m.group(1) or '', s).strip()

def slug(s):
    s = unicodedata.normalize('NFKD', s.lower()).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:60] or 'sec'

def is_wid(tok):
    """A wave id by shape, for a token the wave map does not vouch for: WID with a digit (W2a, WC-V2) or an
    all-caps W… id (WX, WSKILL-ARCH); never a word like "Summary" or an acronym like "API"."""
    return bool(re.fullmatch(WID, tok)) and (any(c.isdigit() for c in tok) or bool(re.fullmatch(r'W[A-Z]*(?:-[A-Z]+)*', tok)))

def known_alt(known):
    """Regex alternation of the known wave ids, longest first, escaped ("" when there are none)."""
    return '|'.join(re.escape(k) for k in sorted(set(known), key=lambda k: (-len(k), k)))

def wid_at(known):
    """Compiled free-text matcher: a known id (longest first) or a digit-bearing id, never glued to other letters."""
    alt = known_alt(known)
    return re.compile(rf'(?<![\w-])({alt + "|" if alt else ""}{WID_DIGIT})(?![A-Za-z0-9])')

# ---------------------------------------------------------------- inline markdown
def inline(s):
    keep, hrefs = [], []

    def code(m):
        keep.append(m.group(1))
        return f'\x00{len(keep) - 1}\x00'

    def link(m):
        u = m.group(2)
        if re.search(r'[\x00"\'\s]', u):
            return m.group(0)  # a code-span placeholder, quote or space in the URL could break out of href: plain text
        if re.match(r'[a-z][a-z0-9+.-]*:', u, re.I) and not re.match(r'(?:https?|mailto):', u, re.I):
            return m.group(0)  # javascript: and friends stay plain text
        hrefs.append(attr(html.unescape(u)))  # u is already esc()'d: unescape first so attr() does not double-escape
        return f'<a href="\x01{len(hrefs) - 1}\x01">{m.group(1)}</a>'

    s = esc(re.sub(r'`([^`]+)`', code, s))
    s = re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', link, s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'(?<![\w*])\*(?!\s)([^*]+?)(?<!\s)\*(?![\w*])', r'<em>\1</em>', s)
    s = re.sub(r'~~(.+?)~~', r'<del>\1</del>', s)
    s = re.sub(r'\x01(\d+)\x01', lambda m: hrefs[int(m.group(1))], s)
    return re.sub(r'\x00(\d+)\x00', lambda m: f'<code>{esc(keep[int(m.group(1))])}</code>', s)

# ---------------------------------------------------------------- block markdown
LI = re.compile(r'^(\s*)([-*+]|\d+[.)])\s+(.*)$')
FENCE = re.compile(r'^(`{3,}|~{3,})')
HR = re.compile(r'-{3,}|\*{3,}|_{3,}')

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

def first_table(lines):
    """First pipe table in the lines as cell rows (separator dropped, header first)."""
    for i, l in enumerate(lines):
        if l.lstrip().startswith('|'):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith('|'):
                j += 1
            return [c for c in map(cells, lines[i:j]) if not is_sep(c)]
    return []

def render_table(lines):
    rows = [cells(l) for l in lines]
    head, body = '', [r for r in rows if not is_sep(r)]
    if len(rows) > 1 and is_sep(rows[1]):
        if any(body[0]):
            head = '<thead><tr>' + ''.join(f'<th>{inline(c)}</th>' for c in body[0]) + '</tr></thead>'
        body = body[1:]
    trs = ''.join('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in r) + '</tr>' for r in body)
    return f'<div style="overflow-x:auto"><table>{head}<tbody>{trs}</tbody></table></div>'

def render_list(lines):
    items = []  # [indent, ordered, text]
    for ln in lines:
        m = LI.match(ln)
        if m:
            items.append([len(m.group(1).expandtabs(4)), m.group(2)[0].isdigit(), m.group(3).strip()])
        elif items and ln.strip():
            items[-1][2] += ' ' + ln.strip()

    def build(pos):
        base, ordered = items[pos][0], items[pos][1]
        tag, h = ('ol' if ordered else 'ul'), []
        while pos < len(items) and items[pos][0] >= base and not (items[pos][0] == base and items[pos][1] != ordered):
            if items[pos][0] > base:
                sub, pos = build(pos)
                h[-1:] = [h[-1][:-5] + sub + '</li>'] if h else [sub]
                continue
            m = re.match(r'\[([ xX])\]\s+(.*)$', items[pos][2])
            if m:
                chk = '' if m.group(1) == ' ' else ' checked'
                h.append(f'<li style="list-style:none"><input type="checkbox" disabled{chk}> {inline(m.group(2))}</li>')
            else:
                h.append(f'<li>{inline(items[pos][2])}</li>')
            pos += 1
        return f'<{tag}>' + ''.join(h) + f'</{tag}>', pos

    out, pos = [], 0
    while pos < len(items):
        s, pos = build(pos)
        out.append(s)
    return ''.join(out)

def starts_block(ln):
    s = ln.strip()
    return not s or FENCE.match(s) or s.startswith(('#', '|', '>')) or LI.match(ln) or HR.fullmatch(s)

def blocks(lines):
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        m = FENCE.match(s)
        if not s:
            i += 1
        elif m:
            j = i + 1
            while j < len(lines) and fence_next(lines[j], m.group(1)) is not None:
                j += 1
            out.append(f'<pre><code>{esc(chr(10).join(lines[i + 1:j]))}</code></pre>')
            i = j + 1
        elif HR.fullmatch(s):
            out.append('<hr>')
            i += 1
        elif re.match(r'#{3,6}\s', s):
            n = len(s.split()[0])
            out.append(f'<h{n}>{inline(s[n:].strip())}</h{n}>')
            i += 1
        elif s.startswith(('|', '>')) or LI.match(ln):
            j = i
            while j < len(lines):
                nxt = next((l for l in lines[j:] if l.strip()), '')
                t = lines[j].strip()
                if s[0] in '|>' and (t.startswith(s[0])):
                    j += 1
                elif s[0] not in '|>' and (LI.match(lines[j]) or (lines[j].startswith(' ') and t) or (not t and LI.match(nxt))):
                    j += 1
                else:
                    break
            if s[0] == '|':
                out.append(render_table(lines[i:j]))
            elif s[0] == '>':
                out.append('<blockquote>' + blocks([re.sub(r'^\s*>\s?', '', l) for l in lines[i:j]]) + '</blockquote>')
            else:
                out.append(render_list(lines[i:j]))
            i = j
        else:
            j = i + 1
            while j < len(lines) and not starts_block(lines[j]):
                j += 1
            out.append(f'<p>{inline(" ".join(l.strip() for l in lines[i:j]))}</p>')
            i = j
    return '\n'.join(out)

def cut_comments(ln, cmt):
    """(visible text of one line, still inside a comment). A `<!--` opens a comment only outside inline code spans."""
    out, pos = [], 0
    while pos < len(ln):
        if cmt:
            end = ln.find('-->', pos)
            if end < 0:
                break
            pos, cmt = end + 3, False
            continue
        op = ln.find('<!--', pos)
        if op < 0:
            out.append(ln[pos:])
            break
        span = CODE_SPAN.search(ln, pos)
        if span and span.start() < op:  # the code span starts first: its `<!--` is literal text
            out.append(ln[pos:span.end()])
            pos = span.end()
            continue
        out.append(ln[pos:op])
        pos, cmt = op + 4, True
    return ''.join(out), cmt

def uncomment(text):
    """Lines of text without HTML comments; fenced blocks and inline code spans are never scanned.
    Lines swallowed by a comment are dropped, but the visible rest of every line (empty for those) feeds the fence state."""
    out, fence, cmt = [], None, False
    for ln in text.split('\n'):
        swallowed = cmt and '-->' not in ln
        if fence is None and (cmt or not FENCE.match(ln.strip())):
            ln, cmt = cut_comments(ln, cmt)
        fence = fence_next(ln, fence)
        if not swallowed:
            out.append(ln)
    return out

def split_sections(text):
    """[(heading, [lines])] per '## ' outside fences; H1/preamble dropped, HTML comments removed."""
    secs, fence = [], None
    for ln in uncomment(text):
        nxt = fence_next(ln, fence)
        if fence is None and nxt is None and ln.startswith('## '):
            secs.append((ln[3:].strip(), []))
        elif secs:
            secs[-1][1].append(ln)
        fence = nxt
    return secs

# ---------------------------------------------------------------- statuses + headings
TASK_ID = re.compile(r'T-?[A-Za-z0-9-]*\d[A-Za-z0-9-]*')

def wave_cell_id(cell):
    """Wave id held by the wave-map's Wave/Ola cell: its first bold token, else the leading plain token
    ("W6", "Wave W6 — Title"); a plain word that is not of id shape ("Pagos") is a title, not an id."""
    m = BOLD.search(cell)
    if m and re.fullmatch(WID, m.group(1)):
        return m.group(1)
    m = re.match(rf'(?:(?:Wave|Ola)\s+)?({WID})(?![A-Za-z0-9])', plain(cell))
    return m.group(1) if m and is_wid(m.group(1)) else None

def wave_map(task_text):
    """{wave id: glyph} from task.md's wave-map table (the table whose header says Wave/Ola).
    The id comes from the header's Wave/Ola column; only a header without one falls back to the first
    bold id-shaped token in the row's first three cells (never a task id like T-W7-01)."""
    out, in_map, wcol = {}, False, None
    for ln in task_text.split('\n'):
        c = cells(ln)
        if not ln.lstrip().startswith('|'):
            in_map = False
        elif not is_sep(c):
            if not in_map:
                in_map = bool(re.search(r'\b(wave|ola)\b', ln, re.I)) and not re.search(f'[{GL}]', ln)
                wcol = next((i for i, h in enumerate(c) if re.search(r'\b(?:wave|ola)\b', plain(h), re.I)), None)
                continue
            if wcol is not None and wcol < len(c):
                wid = wave_cell_id(c[wcol])
            else:
                wid = next((m.group(1) for x in c[:3] for m in [BOLD.search(x)]
                            if m and is_wid(m.group(1)) and not TASK_ID.fullmatch(m.group(1))), None)
            g = next((m.group(1) for x in c for m in [re.match(rf'\s*([{GL}])', x)] if m), None)
            if wid and g:
                out.setdefault(wid, g)
    return out

def badge(g, L, note=''):
    cls, k = STATUS[g]
    tip = ' title="%s"' % attr(note) if note else ''
    return f'<span class="badge {cls}"{tip}>{g} {L["st"][k]}</span>'

def gate_cut(title):
    """(title before the ⚠, gate note or None when there is no ⚠)."""
    i = title.find('⚠')
    if i < 0:
        return title, None
    return title[:i].strip(), re.sub(rf'^\s*(?:GATE|gate)?[:\s]*|[{GL}]', '', title[i + 1:]).strip()

def gate_badge(note):
    if note is None:
        return ''
    return ' <span class="badge gate"' + (f' title="{attr(note)}"' if note else '') + '>⚠ gate</span>'

def wave_heading(title, waves):
    """(word, id, rest) when the title reads "Wave|Ola <id> ..." with an id from the wave map or of id shape, else None."""
    m = re.match(r'(Ola|Wave)\s+([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)(?!\w)\s*(.*)$', plain(title))
    return m.groups() if m and (m.group(2) in waves or is_wid(m.group(2))) else None

def section_heading(title, waves, L):
    """(h2 inner HTML, plain title, wave id or None)."""
    title, gnote = gate_cut(title)
    hd = wave_heading(title, waves)
    if not hd:
        return inline(title) + gate_badge(gnote), plain(title), None
    word, wid, rest = hd
    g = re.search(f'[{GL}]', rest)
    if g and not rest[:g.start()].strip(' —–-:·'):  # "Wave W4 ✅ — Title": the glyph leads
        name, note = re.sub(r'^[\s—–:-]+', '', rest[g.end():]), ''
    else:  # "Wave W6 — Title ✅ CLOSED 21 Aug": text after the glyph is only a tooltip
        name = (rest[:g.start()] if g else rest).strip(' —–-:·')
        note = re.sub(f'[{GL}]', '', rest[g.end():]).strip() if g else ''
    state = waves.get(wid) or (g.group(0) if g else None)
    h = f'{word} {wid}' + (f' — {inline(name)}' if name else '') + (' ' + badge(state, L, note) if state else '')
    return h + gate_badge(gnote), f'{word} {wid} {name}', wid

def sec_html(seen, base, h2, inner):
    n, sid = 1, base
    while sid in seen:
        n, sid = n + 1, f'{base}-{n + 1}'
    seen.add(sid)
    return f'<section class="sec" id="{sid}">\n<h2>{h2}</h2>\n{inner}\n</section>'

def task_cards(body, task_txt, L, known=()):
    tid_re = r'T-?[A-Za-z0-9-]*\d[A-Za-z0-9-]*'
    if known_alt(known):  # digit-less wave ids too: "T-WX-A"
        tid_re = rf'(?:{tid_re}|T-(?:{known_alt(known)})(?:-[A-Za-z0-9]+)*(?![A-Za-z0-9]))'
    chunks, fence = [[]], None
    for ln in body:
        if ln.startswith('### ') and fence is None:
            chunks.append([])
        chunks[-1].append(ln)
        fence = fence_next(ln, fence)
    out = [blocks(chunks[0])]
    for ch in chunks[1:]:
        m = re.match(rf'(?:([{GL}])\s*)?({tid_re})\s*(?:([{GL}])\s*)?(?:[—–:-]+\s*|\s+)?(.*)$', ch[0][4:].strip())
        if not m:
            out.append(blocks(ch))
            continue
        g1, tid, g2, ttl = m.groups()
        mt = re.search(re.escape(tid) + rf'\s*([{GL}])', task_txt)
        g = g1 or g2 or (mt.group(1) if mt else '☐')
        ttl, gnote = gate_cut(ttl)
        out.append(f'<div class="task"><span class="tid">{esc(tid)}</span> {badge(g, L)}{gate_badge(gnote)}\n'
                   f'<h4>{inline(ttl)}</h4>\n{blocks(ch[1:])}\n</div>')
    return '\n'.join(out)

def render_doc(key, secs, waves, task_txt, L, known=()):
    seen, out = set(), []
    for title, body in secs:
        h2, ptxt, wid = section_heading(title, waves, L)
        inner = task_cards(body, task_txt, L, known) if key == 'detailed' else blocks(body)
        out.append(sec_html(seen, f'{PREFIX[key]}-{wid.lower() if wid else slug(ptxt)}', h2, inner))
    return '\n'.join(out)

# ---------------------------------------------------------------- timeframe + Gantt
def weeks_of(cell):
    """(start, end) from "3", "1-2", "Wk 3 – 4", "Sem 2"; None for dates or prose."""
    w = r'(?:weeks?|wks?|semanas?|sem\.?|w|s)?\s*'
    m = re.fullmatch(rf'(?i){w}(\d+)\s*(?:(?:[-–—]|to|a|al|through)\s*{w}(\d+))?', re.sub(r'[*`_]', '', cell).strip())
    if m and int(m.group(2) or m.group(1)) >= int(m.group(1)):
        return int(m.group(1)), int(m.group(2) or m.group(1))

def col_of(hdr, *keys):
    return next((i for i, h in enumerate(hdr) if any(k in h.lower() for k in keys)), None)

def wave_ids(cell, known, wat):
    out = []
    for m in wat.finditer(plain(cell)):
        w = next((c for c in (m.group(1), m.group(1).split('-')[0]) if c in known), None)
        if w and w not in out:
            out.append(w)
    return out

def gantt(sec0, sec1, sec3, sec4, waves, L, wat):
    rows = first_table(sec1)
    ws = [{'id': m.group(1), 'row': r, 'label': re.sub(rf'\s*[{GL}]', '', plain(r[0]))}
          for r in rows[1:] for m in [wat.search(plain(r[0]))] if m]
    if not ws:
        return ''
    known = [w['id'] for w in ws]
    ci = {k: col_of(rows[0], *v) for k, v in {'wk': ('week', 'semana'), 'st': ('stream', 'flujo', 'carril', 'track'),
                                              'ses': ('session', 'sesion', 'sesión'), 'dep': ('depend',)}.items()}

    def at(w, k):
        return w['row'][ci[k]] if ci[k] is not None and ci[k] < len(w['row']) else ''

    per, buf = [], []  # §4: one row = one period (header label + waves running); buffer-only rows
    t4 = first_table(sec4)
    c4 = col_of(t4[0], 'wave', 'ola', 'running', 'curso') if t4 else None
    for k, r in enumerate(t4[1:], 1):
        ids = wave_ids(r[c4 if c4 is not None else min(1, len(r) - 1)], known, wat)
        per.append({'k': k, 'lab': plain(r[0]), 'ids': ids})
        if not ids and re.search(r'buffer|colch|margen|holgura|reserve', ' '.join(r), re.I):
            buf.append(k)
    for w in ws:
        ps = [p['k'] for p in per if w['id'] in p['ids']]
        w['span'] = weeks_of(at(w, 'wk')) or ((min(ps), max(ps)) if ps else None)
        w['deps'] = wave_ids(at(w, 'dep'), known, wat)
    byid = {}
    for w in ws:
        byid.setdefault(w['id'], w)

    def settle(w, path=()):  # last resort: one period each, laid out after the dependencies (any row order)
        if not w['span']:
            ends = [settle(byid[d], path + (w['id'],))[1] for d in w['deps'] if d not in path and d != w['id']]
            s = max(ends or [0]) + 1
            w['span'] = (s, s)
        return w['span']

    for w in ws:
        settle(w)
    end = max(w['span'][1] for w in ws)
    bs, be = (min(buf), max(buf)) if buf else (end + 1, end + 1)
    total = max(end, be, len(per))
    sname, claimed = [], set()
    order, seen_w = [], set()

    def visit(i):  # dependency order (a row may depend on a wave listed after it); cycles are cut
        if i not in seen_w:
            seen_w.add(i)
            for d in ws[i]['deps']:
                visit(next(k for k, x in enumerate(ws) if x['id'] == d))
            order.append(ws[i])

    for i in range(len(ws)):
        visit(i)
    for w in (ws if ci['st'] is not None else order):
        if ci['st'] is not None:
            n = plain(at(w, 'st'))
            sname += [n] if n not in sname else []
            w['lane'] = sname.index(n) + 1
        else:  # a wave continues the lane of its first dependency that no other wave continued yet
            p = next((d for d in w['deps'] if d not in claimed and 'lane' in byid[d]), None)
            claimed.add(p)
            w['lane'] = byid[p]['lane'] if p else max([x.get('lane', 0) for x in ws] + [0]) + 1
    started = any(g in '✅🔄' for g in waves.values())
    g = [f'<div class="gantt" style="--gw:{total};--gr:{len(ws) + 1}">']
    for k in range(1, total + 1):
        p = next((x for x in per if x['k'] == k and x['lab'] and not weeks_of(x['lab'])), None)
        lab = p['lab'] if p else '%s %d' % (L['wk'], k)
        g.append(f'<div class="g-h" style="grid-column:{k + 1}">{esc(lab)}</div>')
    for i, w in enumerate(ws, 2):
        st = waves.get(w['id'])
        ses = re.sub(r'[*`]', '', at(w, 'ses')).strip()
        tip = ' · '.join(filter(None, [w['id'], f'{ses} {L["ses"]}' if ses else '', L['st'][STATUS[st][1]] if st else '']))
        mark = {'✅': ' ✓', '⛔': ' ⛔', '⏸': ' ⏸'}.get(st, '')
        g.append(f'<div class="g-lab" style="grid-row:{i}">{esc(w["label"])}{mark}</div>')
        g.append(f'<div class="g-bar s{(w["lane"] - 1) % 5 + 1}" style="grid-row:{i};grid-column:{w["span"][0] + 1}/{w["span"][1] + 2}" title="{attr(tip)}"></div>')
    last = len(ws) + 2
    g.append(f'<div class="g-lab" style="grid-row:{last}">Buffer</div>')
    g.append(f'<div class="g-bar buf" style="grid-row:{last};grid-column:{bs + 1}/{be + 2}"></div>')
    miles, t3 = {}, first_table(sec3)
    cw = (col_of(t3[0], 'week', 'date', 'fecha', 'semana', 'límite', 'limite') or 0) if t3 else 0
    cb, ct = (col_of(t3[0], 'block', 'bloque'), col_of(t3[0], 'type', 'tipo')) if t3 else (None, None)
    for r in t3[1:]:
        r = r + [''] * 4
        wk = weeks_of(re.sub(r'(?i)^.*?\b(?:weeks?|wks?|semanas?)\s*(\d+).*$', r'\1', plain(r[cw])))
        k = wk[0] if wk else next((p['k'] for p in per if p['lab'] and p['lab'] == plain(r[cw])), None)
        ids = (wave_ids(r[cb], known, wat) if cb is not None else []) or [w['id'] for w in ws if w['span'][1] == k]
        if k and ids:
            m = miles.setdefault((known.index(ids[0]) + 2, k), [[], False])
            m[0].append(plain(r[1]))
            m[1] = m[1] or (ct is not None and 'human' in r[ct].lower())
    for (row, k), (ts, human) in sorted(miles.items()):
        g.append(f'<div class="g-mile{" human" if human else ""}" style="grid-row:{row};grid-column:{k + 1}" title="{attr("; ".join(ts))}"></div>')
    live = [w['span'][0] for w in ws if waves.get(w['id']) == '🔄']
    todo = [w['span'][0] for w in ws if waves.get(w['id']) != '✅']
    if started and (live or todo):
        g.append(f'<div class="g-today" style="grid-column:{min(live or todo) + 1}" data-label="{L["today"]}"></div>')
    keys = ''.join('<span class="g-key"><span class="g-dot" style="background:%s"></span>%s</span>' % (
        STREAMS[i % 5], esc(sname[i] if i < len(sname) else '%s %d' % (L['stream'], i + 1))) for i in sorted({(w['lane'] - 1) for w in ws}))
    keys += f'<span class="g-key"><span class="g-dot mile"></span>{L["mile"]}</span>'
    keys += ('<span class="g-key"><span class="g-dot" style="background:repeating-linear-gradient(45deg,'
             'var(--border-strong) 0 3px,transparent 3px 6px)"></span>Buffer</span>')
    return ''.join(g) + f'</div><div class="g-legend">{keys}</div>'

def render_timeframe(secs, waves, L, known=()):
    first, seen, out = {}, set(), []  # the leading number only LOCATES §0/§1/§3/§4 (first match); order stays the document's
    for k, (t, _) in enumerate(secs):
        m = re.match(r'\s*(\d+)(?:\s*[.)]|\s)', t)  # "1. Title", "1) Title" and "1 Title"
        if m:
            first.setdefault(int(m.group(1)), k)
    part = lambda n: secs[first[n]][1] if n in first else []
    wat = wid_at(known)
    g = gantt(part(0), part(1), part(3), part(4), waves, L, wat)
    if not g and wat.search(plain(' '.join(part(1)))):
        print('  warning: timeframe §1 has wave ids but no Gantt was produced (is §1 a table whose first column starts with the wave id?)', file=sys.stderr)
    merged = {first[n] for n in (0, 1) if n in first} if g else set()
    for k, (t, body) in enumerate(secs):
        if k in merged:
            if k == min(merged):
                out.append(sec_html(seen, 't-gantt', L['sched'], blocks(part(0)) + g + blocks(part(1))))
            continue
        h2, ptxt, wid = section_heading(t, waves, L)
        out.append(sec_html(seen, f't-{wid.lower() if wid else slug(ptxt)}', h2, blocks(body)))
    return '\n'.join(out)

# ---------------------------------------------------------------- shell + patching
def resolve_docs(brain, custom):
    found = {k: next((brain / f'{n}.md' for n in v if (brain / f'{n}.md').exists()), None) for k, v in NAMES.items()}
    for pair in (custom or '').split(','):
        k, _, v = pair.partition('=')
        if pair and (k.strip() not in NAMES or not v.strip()):
            sys.exit(f'--docs: bad entry "{pair}" (use proposal=,master=,detailed=,timeframe=)')
        if pair:
            found[k.strip()] = brain / v.strip()  # absolute paths win over brain automatically
    miss = [k for k, p in found.items() if p is None or not p.exists()]
    if miss:
        sys.exit(f'{brain}: missing source doc(s) {miss} (expected ES/EN names {NAMES} or --docs)')
    return found

def h1_of(text):
    return next((l[2:].strip() for l in text.split('\n') if l.startswith('# ')), '')

def make_shell(tmpl_path, lang, project, txt, L):
    t = re.sub(r'\A\s*<!--.*?-->\s*', '', tmpl_path.read_text(encoding='utf-8'), count=1, flags=re.S)
    h1 = h1_of(txt['master'])
    para = next((l for _, b in split_sections(txt['proposal']) for l in b if l.strip() and not starts_block(l)), '')
    rep = {'{{lang}}': lang, '{{project_name}}': attr(project),
           '{{initiative_title}}': esc(h1.split(': ', 1)[1].strip() if ': ' in h1 else plain(h1)),
           '{{one-line summary of the initiative}}': esc(re.sub(r'\s+', ' ', plain(para))[:200])}
    for a, b in rep.items():
        t = t.replace(a, b)
    for en, loc in zip(LANG['en']['nav'], L['nav']):
        t = t.replace(f'>{en}<', f'>{loc}<')
    return t

def article_re(key):
    return re.compile(rf'(<article\s+id="doc-{key}"[^>]*>)(.*?)(</article>)', re.S)

def patch(text, articles):
    for key, inner in articles.items():
        m = article_re(key).search(text)
        if not m:
            sys.exit(f'<article id="doc-{key}"> not found in the HTML (use --init to rebuild the shell)')
        ind = re.search(r'\n([ \t]*)$', m.group(2))
        text = text[:m.start(2)] + '\n' + inner + '\n' + (ind.group(1) if ind else '') + text[m.end(2):]
    return text

def main():
    ap = argparse.ArgumentParser(description='Regenerate plans.html from the four plan docs (patches only the article bodies).')
    ap.add_argument('out', help='plans.html to patch (created when missing)')
    ap.add_argument('--brain', required=True, type=pathlib.Path, help='directory holding the plan docs (and task.md)')
    ap.add_argument('--lang', choices=['es', 'en'], help='UI strings language (default: the existing HTML\'s lang, else es when the ES doc names are found, else en)')
    ap.add_argument('--project', help='project name for the shell with --init (default: the master-plan H1 prefix, else the brain parent dir name)')
    ap.add_argument('--docs', help='explicit sources: proposal=F,master=F,detailed=F,timeframe=F (relative to --brain)')
    ap.add_argument('--init', action='store_true', help='rebuild the shell from plans-html.tmpl; on an EXISTING <out> it needs --force (a missing <out> is always initialized)')
    ap.add_argument('--force', action='store_true', help='with --init: allow rewriting an existing <out> from the template (a hand-maintained page loses its layout)')
    ap.add_argument('--check', action='store_true', help='write nothing; exit 0 fresh, 1 stale (source newer or articles differ), 3 <out> is hand-maintained (no doc-* articles)')
    a = ap.parse_args()
    brain, out = a.brain, pathlib.Path(a.out)
    src = resolve_docs(brain, a.docs)
    prev = re.search(r'<html lang="(es|en)"', out.read_text(encoding='utf-8')) if out.exists() else None
    lang = a.lang or (prev.group(1) if prev else 'es' if src['proposal'].name.startswith('propuesta') else 'en')
    L = LANG[lang]
    cur = out.read_text(encoding='utf-8') if out.exists() else None
    fresh = cur is None  # a missing output is initialized without --init (stored regen commands work on a fresh brain)
    hand = not fresh and not all(f'id="doc-{k}"' in cur for k in NAMES)
    if hand and a.check:
        print('hand-maintained layout (no doc-* articles): keep regen none or pass --init --force', file=sys.stderr)
        sys.exit(3)
    if not fresh and a.init and not a.force and not a.check:
        sys.exit(f'{out} already exists: --init needs --force to rewrite it from plans-html.tmpl (nothing written)')
    if hand and not a.init:
        sys.exit(f'{out} has no doc-* articles (pass --init --force to rebuild it from plans-html.tmpl)')
    txt = {k: p.read_text(encoding='utf-8') for k, p in src.items()}
    task_path = brain / 'task.md'
    task_txt = '\n'.join(uncomment(task_path.read_text(encoding='utf-8'))) if task_path.exists() else ''
    waves = wave_map(task_txt)
    secs = {k: split_sections(txt[k]) for k in NAMES}
    known = set(waves) | {h[1] for ss in secs.values() for t, _ in ss for h in [wave_heading(gate_cut(t)[0], waves)] if h}
    articles = {k: render_timeframe(secs[k], waves, L, known) if k == 'timeframe'
                else render_doc(k, secs[k], waves, task_txt, L, known) for k in NAMES}
    shell = fresh or (not a.check and (hand or (a.init and a.force)))
    old = cur
    if shell:
        tmpl = pathlib.Path(__file__).resolve().parent / 'plans-html.tmpl'
        if not tmpl.is_file():
            print('plans-html.tmpl not found next to plans-regen.py; copy both', file=sys.stderr)
            sys.exit(2)
        h1 = h1_of(txt['master'])
        project = a.project or (h1.split(' — ')[0].strip() if ' — ' in h1 else brain.resolve().parent.name)
        cur = make_shell(tmpl, lang, project, txt, L)
    new = patch(cur, articles)
    left = re.findall(r'\{\{[^}]*\}\}', re.sub(r'<article.*?</article>', '', new, flags=re.S))
    if left:
        print(f'  warning: unresolved placeholders in the shell: {left[:4]}', file=sys.stderr)
    newer = [p.name for p in [*src.values(), task_path] if out.exists() and p.exists() and p.stat().st_mtime > out.stat().st_mtime]
    if a.check:
        diff = [k for k in NAMES if shell or article_re(k).search(cur).group(0) != article_re(k).search(new).group(0)]
        print(f'  --check: {out} is ' + (f'STALE · articles differ: {diff or "none"} · sources newer than the HTML: {newer or "none"}'
                                         if shell or diff or newer else 'up to date'))
        sys.exit(1 if shell or diff or newer else 0)
    if new != old:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(new, encoding='utf-8')
    elif newer:
        os.utime(out, None)  # identical content: refresh the mtime so --check reads "fresh"
    print(f'  {"written" if new != old else "unchanged"}: {out} · {len(new) // 1024} KB · lang={lang} · {len(waves)} wave-map rows'
          + (' (initialized: output was missing)' if fresh else ' · shell via --init' if shell else ''))
    for k in NAMES:
        print(f'    {k:9} {articles[k].count("<section class=")} sections · {articles[k].count(chr(34) + "task" + chr(34))} task cards · {src[k].name}')

if __name__ == '__main__':
    main()
