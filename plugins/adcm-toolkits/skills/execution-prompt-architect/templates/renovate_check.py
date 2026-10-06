#!/usr/bin/env python3
"""renovate_check.py - what does an existing brain lack against the current execution protocol?

Reads <brain>/execute.md, task.md, artifacts.json and scripts/ and reports, block by block, whether the
brain carries the current protocol (adcm-toolkits 0.16.0) or what a renovation has to add. Read-only,
stdlib only, Python >= 3.8, deterministic (no clock, stable ordering, UTF-8 stdout). The only write is
--copy-scripts; execute.md, task.md, the registry and any memory/CLAUDE.md note are corrected by an executor
from this report, never by this script.

Usage
  renovate_check.py --brain DOCS_DIR [--all-modules | --module REL] [--skill-dir PATH]
                    [--copy-scripts [--force-outdated]] [--memory-dir PATH] [--no-rules]
                    [--invariants] [--json] [--version]
  --module REL      check <brain>/REL instead of the root (scripts stay n/a)
  --all-modules     also check modules/*/task.md; `modules` joins needed when one lacks anything
  --skill-dir PATH  templates live in PATH/templates/<name>, then PATH/<name>; courier_preflight.py (skill
                    artifact-courier) in PATH/../artifact-courier/scripts, then PATH/../../artifact-courier/
                    scripts (default PATH: this script's dir)
  --copy-scripts    copy the MISSING files of scripts/ from the templates; --force-outdated also
                    overwrites files whose sha256 differs (a project copy may be customised); files
                    flagged cache-dep are never touched
  --memory-dir PATH memory dir to scan instead of the resolved one (see RULES); --no-rules skips RULES
  --invariants      counts renovation must not change: s7_wave_headers, h2_sections, logbook_entries,
                    wave_rows (fences and HTML comments ignored); the execute.md line count is
                    informational (`stats.execute_lines`, plain `lines=n`): renovation adds lines
  --json            one object: version, target, brain, module, protocol, blocks, needed, invariants,
                    stats, text

Blocks (ok | missing | partial | outdated | n/a)
  SCRIPTS    the seven files of scripts/; a file that differs from its template is a project copy
             (`custom`, informational: only a missing file makes the block needed). `cache-dep` (fix):
             a *.py or *.sh directly under scripts/ or .build/ whose text contains the plugin-cache
             path reads a templates copy that a cache purge deletes; JSON `blocks.scripts.cache_dep`
             lists the sorted brain-relative paths (`.build/y.sh`, `scripts/x.py`) and the block is
             needed (point the script to the local scripts/*.tmpl copies)
  ARTIFACTS  registry rows without `regen` (`none` counts ok) with the suggested --set-regen command;
             a registry with rows that declares no `active_account`/`cuenta_activa` (missing or empty)
             adds the advice line `· review: no active_account declared → courier-preflight <docs_dir>
             --set-active-account <name>` (never needed; JSON `blocks.artifacts.no_active_account`,
             shed with the registry rows under the 40-line cap)
  EXECUTE    role types, digest line, LAST LOG in section 4, Next/blocked labels in 2b, model rule,
             `> **Protocol:**` line, SKILLS line per pending wave of section 7; since 0.16.0 also the
             `> **Reviewer:**` header line (reviewer-line), `Claude never merges` inside section 3
             (merge-rule), `exactly once per delivery close` in section 2b (links-once); the retired
             automatic-merge policy text inside section 3 or the section 7 prompt of a pending wave (not a ✅ one) is
             named in `lacks` (`auto-` followed by `merge`). A Reviewer
             value that is still the placeholder adds `· review: reviewer pending → owner sets @handle`
             (never needed; JSON `markers.reviewer_pending`)
  TASK       `## DoD-human pending` (canonical) or an equivalent legacy section
  RULES      obsolete protocol notes (STALE_RULES) in the project's auto-memory (+ MEMORY.md hooks) and in
             CLAUDE.md/AGENTS.md/README.md of the container: only `fix` findings make it needed. Targets:
             memory = $CLAUDE_CONFIG_DIR (else ~/.claude)/projects/<container path, non-alphanumerics -> '-'>/
             memory (container = DOCS_DIR minus a trailing [ai|docs]/ai-brain; also the DOCS_DIR-named dir);
             CLAUDE.md and AGENTS.md in the container, <container>/ai and DOCS_DIR; DOCS_DIR/README.md.
             Notes already corrected (`Superseded (protocol`, `<!-- renovate:`) are ignored. Root run only.
  CONTEXT    code-project-context skill named by execute.md (informational, never needed)
  HOOKS      informational, never needed: the hooks dir ($CLAUDE_CONFIG_DIR/hooks, else ~/.claude/hooks)
             holds merge-guard.py and an artifact-guard.py equal to the sibling templates/artifact-guard.py;
             each gap adds a `review:` line naming the hook (merge-guard missing · artifact-guard missing |
             outdated; no template next to the checker → `unknown`, no line). JSON `blocks.hooks` =
             {merge_guard: bool, artifact_guard: ok|missing|outdated|unknown}. The owner installs hooks
             (run with `!`); renovation never touches them

Output is at most 40 lines; the last is `RENOVATE: up-to-date | needed(a,b) | unparsed (...)`.
Exit codes: 0 up-to-date, 1 needed, 2 unparsed (no brain/execute.md, unreadable, internal error), 64 usage.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata

__version__ = "0.16.0"
TARGET = __version__

SCRIPTS = ("status_digest.py", "status-brief.md", "plans-regen.py", "plans-html.tmpl",
           "prompts-regen.py", "prompts-html.tmpl", "courier_preflight.py")
CACHE_MARK = "plugins" + "/cache/"  # built from parts: this file must not trip its own cache-dep check
CACHE_FIX = "point the script to the local scripts/*.tmpl copies"
TYPES = ("executor", "auditor", "researcher", "courier", "digester")
BLOCKS = ("scripts", "artifacts", "execute", "task", "rules", "context", "modules")
NEED = ("missing", "partial", "unparsed", "needed", "cache-dep")
FLAGS = (("digest_line", "digest-line"), ("last_log_s4", "last-log-s4"), ("next_label", "next-label"),
         ("blocked_label", "blocked-label"), ("model_rule", "model-rule"), ("protocol_line", "protocol-line"),
         ("reviewer_line", "reviewer-line"), ("merge_rule", "merge-rule"), ("links_once", "links-once"))
RETIRED = "auto" + "-merge"  # the pre-0.16 policy text, built from parts so grepping for it finds only stale docs
RETIRED_RX = re.compile(RETIRED.replace("-", "-?"), re.I)
DOCS_ES = ("propuesta-ejecutiva.md", "plan-maestro.md", "plan-detallado.md")
KNOWN = "✅⛔⏸🔄☐🔀🔬"
DONE = "✅🔀"
FE0F = "\ufe0f"
MAX_BYTES = 20 * 1024 * 1024
MAX_LINES = 40

SECTION_KINDS = (  # first match wins, so the logbook is never mistaken for a pending list
    ("log", r"(?:logbook|bitacora)\b|log$"),
    ("waves", r"(?:wave map|mapa de olas|olas)\b"),
    ("resume", r"(?:punto de retomada|resume point|where we left off|donde nos quedamos)"),
    ("pending", r"(?:dod-human|bloqueante|blocker|pendiente|pending|preguntas abiertas|open questions)"),
)
ENTRY = re.compile(r"###\s+(\d{4}-\d{2}-\d{2})(?:\s*\((\d{1,3}|[a-z])\))?\s*[—–-]?\s*(.*)$")
HR = re.compile(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
BOLD_ID = re.compile(r"\*\*(?:(?:Wave|Ola)\s+)?([^\s*]+)")
LOOSE_ID = re.compile(r"\s*(?:(?:Wave|Ola)\s+)?([A-Za-z][\w/-]*\d[\w/-]*)")
NOT_A_WAVE = re.compile(r"(?:sub)?totals?|suma|legend|leyenda", re.I)
FENCE = re.compile(r"^(`{3,}|~{3,})")
NEXT_LABEL = re.compile(r"(?:\*\*|^\s*[-*]\s+)(?:Next|Siguiente)\b[^:*\n]{0,24}(?::|\*\*)", re.I)
# a section-7 wave header, optionally led by status glyphs and CAPS words, e.g. `### ✅ DONE (28 ago) Ola W8 — x`
S7_HEADER = re.compile(r"###\s+(?:(?:[^\w\s]+|[A-Z]{2,}(?:\s*\([^)\n]{0,30}\))?)\s+){0,6}\*{0,2}(?:Wave|Ola)\s+\*{0,2}([^\s—–:,(*]+)")
LOAD_SKILL = re.compile(r"(?:Load|Carga)\s+(?:the|el)\s+skills?\b[^`\n]*`([^`\n]+)`")
PROTOCOL = re.compile(r">\s*\*\*Protocol:\*\*\s*adcm-toolkits\s+(\d+\.\d+(?:\.\d+)?)")
REVIEWER = re.compile(r">\s*\*\*Reviewer:\*\*(.*)$")
PLACEHOLDER = re.compile(r"_?pending\b|owner sets|\{\{", re.I)


# ---------------------------------------------------------------- helpers copied from status_digest.py
def plain(s):
    """Markdown stripped to text: links, ** and ~~ and backtick markers, paired *em*; a lone `*` stays."""
    s = re.sub(r'\[([^\]\n]{0,300})\]\([^)\n]{0,300}\)', r'\1', s)
    s = re.sub(r'\*\*|~~|`', '', s)
    return re.sub(r'(?<![\w*])\*(?=\S)([^*\n]*?\S)\*(?![\w*])', r'\1', s).strip()


def norm(s):
    """Lower-case ASCII (accents and glyphs dropped) with collapsed spaces."""
    s = unicodedata.normalize('NFKD', s.lower()).encode('ascii', 'ignore').decode()
    return ' '.join(s.split())


def tidy(s):
    return ' '.join(plain(s[:4000]).replace(FE0F, '').split())


def fence_next(ln, fence):
    """Fence state after this line: opening marker, or None when closed/outside."""
    s = ln.strip()
    if fence is None:
        m = FENCE.match(s)
        return m.group(1) if m else None
    return None if set(s) == {fence[0]} and len(s) >= len(fence) else fence


def strip_comments(text, blank_fences=True):
    """Lines of text with HTML comments (and, by default, fenced blocks) blanked; the line count is
    preserved. A comment opens only when `<!--` starts the line (<= 3 spaces)."""
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
        out.append('' if blank_fences and (fence is not None or nxt is not None) else ln)
        fence = nxt
    return out


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


def tables(lines):
    """Every pipe table in the lines as cell rows (separator dropped, header first)."""
    out, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith('|'):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith('|'):
                j += 1
            out.append([c for c in map(cells, lines[i:j]) if not (c and all(re.fullmatch(r':?-+:?', x) for x in c))])
            i = j
        else:
            i += 1
    return out


def glyph_of(cell):
    """First status symbol of a cell (after '*', U+FE0F and spaces), else None."""
    ch = cell.replace(FE0F, '').lstrip('*_~ \t')[:1]
    if ch and ch in KNOWN:
        return ch
    return 'other:' + ch if ch and ord(ch) > 0x2000 and unicodedata.category(ch) == 'So' else None


def wave_id(cell):
    """First bold id of a cell: handles `Wave W1`, `W8 — X`, `W10:`."""
    for m in BOLD_ID.finditer(cell):
        tok = re.split(r'[—–]', m.group(1), maxsplit=1)[0].rstrip('—–,(:;.')
        if tok and tok[0].isalnum():
            return tok
    return None


def wave_header(row):
    """Column indexes of a wave-map header (`wave|ola` cell, no glyph, >= 4 columns) or None."""
    if len(row) < 4 or re.search('[%s]' % KNOWN, ' '.join(row)):
        return None
    h = [norm(plain(c)) for c in row]
    col = lambda rx: next((i for i, x in enumerate(h) if re.match(rx, x)), None)
    wave = col(r'.*\b(?:wave|ola)\b')
    return None if wave is None else {'wave': wave, 'status': col(r'(?:status|estado)')}


def wave_row(c, ix, n):
    """(id, glyph or None) of a wave-map row, or None when the row has no id."""
    if len(c) == n:
        gl = (glyph_of(c[ix['status']]) if ix['status'] is not None else None) or next(
            (g for g in map(glyph_of, c[:2]) if g), None)
        wid = wave_id(c[ix['wave']])
        bold = wid is not None
        if wid is None:
            m = LOOSE_ID.match(tidy(c[ix['wave']]))
            wid = m.group(1) if m else None
    else:  # 5/8/9-cell rows: glyph in cells 0-1, id in cells 0-2
        gl = next((g for g in map(glyph_of, c[:2]) if g), None)
        wid, bold = next((w for w in map(wave_id, c[:3]) if w), None), True
    if wid is None or (gl is None and (not bold or NOT_A_WAVE.fullmatch(wid))):
        return None
    return wid, gl


def sections(lines):
    """H1/H2 sections: start, end, level, heading and (H2 only) the kind of SECTION_KINDS."""
    heads = [(i, len(m.group(1)), tidy(m.group(2))) for i, ln in enumerate(lines)
             for m in [re.match(r'(#{1,2})\s+(.*)$', ln)] if m]
    out = []
    for k, (i, level, head) in enumerate(heads):
        n = re.sub(r'^[^a-z]+', '', norm(head)) if level == 2 else ''
        kind = next((kd for kd, rx in SECTION_KINDS if re.match(rx, n)), None)
        out.append({'start': i, 'level': level, 'heading': head, 'kind': kind,
                    'end': heads[k + 1][0] if k + 1 < len(heads) else len(lines)})
    return out


def sfx_key(s):
    return 0 if not s else int(s) if s.isdigit() else ord(s) - 96


def list_modules(brain):
    base = os.path.join(brain, 'modules')
    names = sorted(os.listdir(base)) if os.path.isdir(base) else []
    return ['modules/' + n for n in names if os.path.isfile(os.path.join(base, n, 'task.md'))]


# ---------------------------------------------------------------- readers
def read_text(path):
    """File text (BOM dropped, bad bytes replaced) or None when it is not a readable regular file <= 20 MB."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read().lstrip('\ufeff')
    except OSError:
        return None


def region(lines, start_rx, end_rx):
    """(lo, hi): the lines after the first start match up to the next end match; None without a start."""
    lo = next((i for i, ln in enumerate(lines) if re.match(start_rx, ln)), None)
    if lo is None:
        return None
    return lo + 1, next((i for i in range(lo + 1, len(lines)) if re.match(end_rx, lines[i])), len(lines))


def seen(rx, lines, flags=0):
    return any(re.search(rx, ln, flags) for ln in lines)


def read_task(text):
    """Wave rows, pending-section shape and logbook facts of a task.md (fences and comments ignored)."""
    lines = strip_comments(text)
    secs = sections(lines)
    rows, ids = [], set()
    for chunk in [lines[s['start'] + 1:s['end']] for s in secs if s['kind'] == 'waves'] or [lines]:
        for tb in tables(chunk):
            ix = wave_header(tb[0]) if len(tb) > 1 else None
            for c in (tb[1:] if ix else []):
                r = wave_row(c, ix, len(tb[0]))
                if r and r[0] not in ids:
                    ids.add(r[0])
                    rows.append(r)
    canon = next((s for s in secs if s['level'] == 2 and re.match(r'dod-human pending\b', s['heading'], re.I)), None)
    legacy = next((s for s in secs if s['kind'] == 'pending'), None)
    pend = canon or legacy
    entries = []
    for lo, hi in [(s['start'] + 1, s['end']) for s in secs if s['kind'] == 'log'] or [(0, len(lines))]:
        cur = None
        for i in range(lo, hi):
            m = ENTRY.match(lines[i])
            if m:
                cur = {'i': i, 'end': i, 'key': (m.group(1), sfx_key(m.group(2)))}
                entries.append(cur)
            elif re.match(r'\s{0,3}#{1,3}\s', lines[i]):
                cur = None
            elif cur is not None and lines[i].strip() and not HR.match(lines[i]):
                cur['end'] = i
    keys = [e['key'] for e in entries]
    up = any(b > a for a, b in zip(keys, keys[1:]))
    down = any(b < a for a, b in zip(keys, keys[1:]))
    has_next = False
    if entries:  # newest entry: highest (date, suffix); ties go to the later line unless the log runs newest-first
        later = up or not down
        e = entries[max(range(len(entries)), key=lambda p: (keys[p], p if later else -p))]
        has_next = any(NEXT_LABEL.search(ln) for ln in lines[e['i'] + 1:e['end'] + 1])
    return {'rows': rows, 'entries': len(entries), 'has_next': has_next,
            'shape': 'canonical' if canon else 'legacy' if legacy else 'missing', 'heading': pend['heading'] if pend else None}


def read_context(prose):
    """Context-skill block from the `Load the skill `...`` sentence of execute.md (it may wrap across lines)."""
    for m in LOAD_SKILL.finditer(re.sub(r'(?<!\n)\n(?!\n)', ' ', '\n'.join(prose))):
        n = re.fullmatch(r'(?:([\w.-]+):)?(code-project-context-[\w.-]+)', m.group(1).strip())
        if n:
            return {'state': 'ok', 'skill': n.group(2), 'plugin': n.group(1), 'last_scanned': scanned(n.group(2), n.group(1))}
    return {'state': 'n/a', 'skill': None, 'plugin': None, 'last_scanned': None}


def scanned(skill, plugin):
    """`last_scanned` of the skill's SKILL.md in the plugin caches under $HOME, or None."""
    pat = os.path.join(glob.escape(os.path.expanduser('~')), '.claude*', 'plugins', 'cache', '*',
                       plugin or '*', '*', 'skills', skill, 'SKILL.md')
    for path in sorted(glob.glob(pat), reverse=True):
        text = read_text(path)
        m = re.search(r'^last_scanned:\s*["\']?(\d{4}-\d{2}-\d{2})', (text or '')[:8000], re.M)
        if m:
            return m.group(1)
    return None


def read_execute(text, glyphs):
    """Marker block, protocol, context block and counters of an execute.md."""
    struct, prose = strip_comments(text), strip_comments(text, False)
    s2, s2b, s3, s4, s7 = (region(struct, r'##\s*2\b', r'##\s*\d'), region(struct, r'##\s*2b\b', r'##\s'),
                           region(struct, r'##\s*3\b', r'##\s'), region(struct, r'##\s*4\.', r'##\s'),
                           region(struct, r'##\s*7\.', r'##\s(?!\s*(?:Executor|Simplifier|Capture|Courier) brief)'))  # unfenced brief headings stay inside §7
    heads = [i for i in range(*s7) if S7_HEADER.match(struct[i])] if s7 else []
    pending = have = 0
    retired_s7 = False  # the retired policy text inside the §7 prompt of a pending wave (what a session actually runs)
    for i in heads:
        hi = next((j for j in range(i + 1, s7[1]) if re.match(r'#{1,3}\s', struct[j])), s7[1])
        wid = S7_HEADER.match(struct[i]).group(1).rstrip('.;')
        g = glyphs[wid] if wid in glyphs else next(iter(re.findall('[%s]' % KNOWN, struct[i])), None)
        if g is None or g not in DONE:
            pending += 1
            have += seen(r'^\s*-\s*SKILLS:', prose[i + 1:hi])
            wave_end = next((j for j in heads if j > i), s7[1])  # the whole wave, brief sub-headings included
            retired_s7 = retired_s7 or bool(RETIRED_RX.search(' '.join(' '.join(prose[i + 1:wave_end]).split())))
    labels = prose[s2b[0]:s2b[1]] if s2b else prose
    found = next((p.group(1) for p in map(PROTOCOL.match, struct) if p), None)
    rev = next((r for r in map(REVIEWER.match, struct) if r), None)
    rev_val = rev.group(1).split('·')[0].strip() if rev else ''  # the value before `· **Merge policy:** ...`
    flat = lambda lines: ' '.join(' '.join(lines).split())  # a sentence may wrap across lines
    sec3, sec2b = flat(prose[s3[0]:s3[1]]) if s3 else '', flat(labels)
    m = {'types': {t: seen(r'adcm-toolkits:%s\b' % t, prose) for t in TYPES},
         'digest_line': bool(s2) and seen(r'scripts/status_digest\.py\s+--brain', prose[s2[0]:s2[1]]),
         'last_log_s4': bool(s4) and seen(r'\bLAST LOG\b', prose[s4[0]:s4[1]]),
         'next_label': seen(r'\*\*(?:Next|Siguiente):?\*\*', labels, re.I),
         'blocked_label': seen(r'\*\*(?:blocked|bloquead\w*):?\*\*', labels, re.I),
         'model_rule': seen(r"per-call .model. overrides the type.s default", prose)
         or any('adcm-toolkits:*' in ln and 'model' in ln and re.search(r'per-call|por llamada', ln) for ln in prose),
         'protocol_line': found == TARGET, 'reviewer_line': rev is not None,
         'merge_rule': 'Claude never merges' in sec3, 'links_once': 'exactly once per delivery close' in sec2b,
         'auto_merge': bool(RETIRED_RX.search(sec3)) or retired_s7,
         'reviewer_pending': rev is not None and (not rev_val or bool(PLACEHOLDER.search(rev_val))),
         'skills_lines': {'have': have, 'pending_waves': pending}}
    flags = list(m['types'].values()) + [m[k] for k, _ in FLAGS]
    state = ('ok' if all(flags) and have == pending and not m['auto_merge']
             else 'missing' if not any(flags) and have == 0 else 'partial')
    if found:
        inferred = '.'.join(found.split('.')[:2])
    elif any(m['types'].values()) or m['model_rule']:
        inferred = '0.14'
    elif m['digest_line'] or m['last_log_s4']:
        inferred = '0.13'
    else:
        inferred = '0.11' if seen(r'code-simplifier|prompts-regen', prose) else '0.8'
    counts = {'execute_lines': text.count('\n') + (0 if text.endswith('\n') or not text else 1),
              's7_wave_headers': len(heads), 'h2_sections': sum(bool(re.match(r'##[ \t]', ln)) for ln in struct)}
    return ({'state': state, 'markers': m}, {'found': found, 'inferred': inferred}, read_context(prose), counts)


def read_artifacts(path, lang, ids):
    """Registry block: rows without `regen` (absent or empty; `none` and project builders count ok)."""
    if not os.path.lexists(path):
        return {'state': 'n/a', 'total': 0, 'rows_without_regen': [], 'no_active_account': False}
    try:
        data = json.loads(read_text(path) or '')
    except ValueError:
        data = None
    rows = data.get('artifacts') if isinstance(data, dict) else data
    if not isinstance(rows, list):  # present but not a registry: a renovation cannot guess its rows
        return {'state': 'unparsed', 'total': 0, 'rows_without_regen': [], 'no_active_account': False}
    rows = [r for r in rows if isinstance(r, dict)]
    bad = []
    for r in rows:
        regen = r.get('regen')
        if not (regen.strip() if isinstance(regen, str) else regen) or (isinstance(regen, str) and regen.strip().lower().startswith('blocked:')):  # a stored 'blocked:' hint is not a regen
            f = str(r.get('file') or r.get('path') or '?')
            base = os.path.basename(f)
            cmd = ('python3 scripts/plans-regen.py --brain . --lang %s %s' % (lang, f) if base == 'plans.html' else
                   'python3 scripts/prompts-regen.py --brain . --lang %s --init %s %s' % (lang, ','.join(ids), f)
                   if base == 'prompts.html' and ids else 'blocked: needs wave ids' if base == 'prompts.html' else 'none')
            bad.append({'file': f, 'suggest': cmd})
    declared = isinstance(data, dict) and any(isinstance(data.get(k), str) and data[k].strip()
                                              for k in ('active_account', 'cuenta_activa'))
    return {'state': 'missing' if bad else 'ok', 'total': len(rows), 'rows_without_regen': bad,
            'no_active_account': isinstance(data, dict) and bool(rows) and not declared}


def review(tdir, lang):
    """The execute, task, artifacts and context blocks (+ protocol and invariants) of one directory."""
    ex, tk = read_text(os.path.join(tdir, 'execute.md')), read_text(os.path.join(tdir, 'task.md'))
    task = read_task(tk) if tk and tk.strip() else None
    rows = task['rows'] if task else []
    counts = {'execute_lines': 0, 's7_wave_headers': 0, 'h2_sections': 0}  # execute_lines is stats, not an invariant
    exe, protocol, ctx = {'state': 'n/a', 'markers': None}, {'found': None, 'inferred': 'unknown'}, read_context([])
    if ex is not None:
        exe, protocol, ctx, counts = read_execute(ex, dict(rows))
    tsk = ({'state': 'n/a', 'shape': None, 'heading': None, 'last_entry_has_next': False} if task is None else
           {'state': 'missing' if task['shape'] == 'missing' else 'ok', 'shape': task['shape'],
            'heading': task['heading'], 'last_entry_has_next': task['has_next']})
    blocks = {'artifacts': read_artifacts(os.path.join(tdir, 'artifacts.json'), lang, [w for w, _ in rows]),
              'execute': exe, 'task': tsk, 'context': ctx}
    stats = {'execute_lines': counts.pop('execute_lines')}
    inv = dict(counts, logbook_entries=task['entries'] if task else 0, wave_rows=len(rows))
    return {'blocks': blocks, 'protocol': protocol, 'inv': inv, 'stats': stats,
            'needed': [b for b in ('artifacts', 'execute', 'task') if blocks[b]['state'] in NEED]}


def cache_dep(brain):
    """Sorted brain-relative paths (`.build/y.sh`, `scripts/x.py`) of the *.py|*.sh directly under scripts/ and
    .build/ that mention the plugin cache."""
    found = set()
    for sub in ('scripts', '.build'):
        d = os.path.join(brain, sub)
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if n.endswith(('.py', '.sh')) and CACHE_MARK in (read_text(os.path.join(d, n)) or ''):
                found.add(sub + '/' + n)
    return sorted(found)


def sha(path):
    try:
        with open(path, 'rb') as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def scripts_block(brain, skill_dir, copy, force):
    """SCRIPTS block against the templates; --copy-scripts fills the gaps first and the state reflects the disk."""
    sdir = os.path.join(brain, 'scripts')
    root = os.path.join(os.path.realpath(brain), 'scripts')
    paths = lambda n: (os.path.join(skill_dir, 'templates', n), os.path.join(skill_dir, n),
                       os.path.join(skill_dir, '..', 'artifact-courier', 'scripts', n),
                       os.path.join(skill_dir, '..', '..', 'artifact-courier', 'scripts', n))
    source = lambda n: next((p for p in paths(n) if os.path.isfile(p)), None)

    def scan():
        miss = [n for n in SCRIPTS if not os.path.isfile(os.path.join(sdir, n))]
        old = [n for n in SCRIPTS if n not in miss and source(n) and sha(source(n)) != sha(os.path.join(sdir, n))]
        return miss, old

    missing, outdated = scan()
    copied, failed, dep = [], [], cache_dep(brain)
    for n in SCRIPTS if copy else ():
        dst = os.path.join(sdir, n)
        if 'scripts/' + n in dep:  # a cache-dep file is edited by hand, never overwritten
            continue
        if n in missing or (force and n in outdated):
            if os.path.islink(dst) or os.path.islink(sdir) or os.path.dirname(os.path.realpath(dst)) != root:
                failed.append(n + ' (symlink)')  # never write through a link or out of scripts/
                continue
            try:
                if source(n) is None:
                    raise OSError(n)
                os.makedirs(sdir, exist_ok=True)
                shutil.copy(source(n), dst)
                copied.append(n)
            except OSError:
                failed.append(n)
    if copied or failed:
        missing, outdated = scan()
    dep = cache_dep(brain) if copied or failed else dep
    return {'state': 'missing' if missing else 'cache-dep' if dep else 'ok', 'missing': missing,
            'outdated': outdated, 'copied': copied, 'failed': failed, 'cache_dep': dep}


def hooks_dir():
    return os.path.join(os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR') or '~/.claude'), 'hooks')


def hooks_block(skill_dir):
    """HOOKS block (informational): merge-guard.py installed? artifact-guard.py installed and equal to the template
    next to the checker (ok | missing | outdated | unknown when that template is not found)."""
    hd = hooks_dir()
    guard = os.path.join(hd, 'artifact-guard.py')
    tpl = next((p for p in (os.path.join(skill_dir, 'templates', 'artifact-guard.py'),
                            os.path.join(skill_dir, 'artifact-guard.py')) if os.path.isfile(p)), None)
    state = ('missing' if not os.path.isfile(guard) else 'unknown' if tpl is None
             else 'ok' if sha(guard) == sha(tpl) else 'outdated')
    return {'merge_guard': os.path.isfile(os.path.join(hd, 'merge-guard.py')), 'artifact_guard': state}


# ---------------------------------------------------------------- RULES: obsolete notes in memory and CLAUDE.md
# (id, severity, regex on the plain line, the line is left out when it also matches, correction)
STALE_RULES = (
    ('old-version', 'fix',
     r'(?:toolkits?|execution-prompt-architect|protocolo|(?:adcm|execution|brain)\s+protocol|brain(?: a)?|'
     r'(?:adcm-toolkits|execution-prompt-architect|brain|protocolo?|toolkits?)[^.\n]{0,30}?(?:subi[oó]|actualizad[oa]|updated|bumped)\s+(?:a|to))(?:\s+(?:en|in|at|on|is|es|v))?\s*\**v?0\.(?:[6-9]|1[0-3])(?:\.\d+)?\b',
     None,  # skipped when the line cites 0.14+ or says current right after the version
     'protocol is <target>: roles are adcm-toolkits:* agent types, status via status_digest.py, close via adcm-toolkits:courier'),
    ('roles-old', 'fix', r'\bopus\W{0,4}(?:ejecuta|implementa|executes|implements)|\bsonnet\W{0,4}(?:audita|audits)',
     r'adcm-toolkits:|0\.1[4-9]|\b(?:only|solo|s[oó]lo)\b.{0,12}gate|\b(?:cuota|quota)\b|agotad|exhaust',  # "Opus executes only ⚠gate waves" is the new rule
     'since 0.14 Opus audits (adcm-toolkits:auditor) and executes only ⚠gate waves (executor + model: opus); Sonnet executes (adcm-toolkits:executor)'),
    ('prompts-only-regen', 'review', r'prompts-regen\.py', r'plans-regen|regen: none|0\.1[4-9]',  # file level: first mention
     'review: plans.html is regenerated too (plans-regen.py); confirm this note about prompts-regen.py alone still holds'),
    ('plans-by-hand', 'review', r'plans\.html.*(?:a mano|by hand|hand-?render)', r'regen: none|plans-regen|0\.1[4-9]',
     'review: plans.html is regenerated by plans-regen.py unless its registry row says regen: none'),
    ('guard-main-only', 'review', r'guard.*(?:solo|only).*(?:cuenta|count).*(?:principal|main|texto|text)', None,
     'review: the artifact guard rules changed in the current protocol; confirm this note still holds'),
    ('courier-general-purpose', 'fix', r'general-purpose.{0,60}(?:courier|cierre|artifacts)',
     r'fallback|without (?:the )?(?:agent )?types|sin (?:los )?tipos|not loaded',
     'the close is adcm-toolkits:courier (Sonnet pinned)'),
    ('reads-task-md', 'fix', r'\b(?:lee|leer|read|reads|leyendo)\b.{0,20}task\.md.{0,40}'
     r'\b(?:al arrancar|arranque|al inicio|at (?:session )?start|on start|to resume|para retomar|retomar)\b',
     r"\b(?:nunca|never|not|no|don.t|jam[aá]s)\b|digest",
     'the main session never reads task.md: run status_digest.py --brain <docs_dir>'),
    ('courier-missing', 'fix', r"artifact-courier.{0,40}(?:no existe|not exist|doesn.t exist)", None,
     'artifact-courier is a skill + the adcm-toolkits:courier agent type (plugin ≥ 0.14.0; reload plugins)'),
    ('subagent-sends-media', 'fix', r'(?:courier|sub-?agent\w*).{0,50}SendUserFile',
     r'ha(?:s|ve) no|no tiene|not available|cannot|can.t|never|nunca|\bsin\b|main session|sesi[oó]n principal',
     'sub-agents have no SendUserFile: they return MEDIA: unsent paths and the main session sends them'),
)
FILE_LEVEL, QUIET_RULES = 'prompts-only-regen', ('prompts-only-regen', 'plans-by-hand')
IGNORED_NAME = re.compile(r'renovate|refresh-01[4-9]', re.I)
INDEX_LINK = re.compile(r'^\s*-\s*\[[^\]]*\]\([^)]*\)\s*')


def fold(s):
    return re.sub(r'[\W_]+', ' ', s.lower()).strip()


def scan_file(text, hook, only_version):
    """[(line, rule id, severity, snippet)] of one file. Skipped: a correction note (a line starting
    `Superseded (protocol` plus the indented / `(line` lines after it; everything after `<!-- renovate:`) and
    any finding whose first 40 folded snippet chars a note of the same file quotes. `hook`: MEMORY.md index,
    only the text after the `- [title](file)` link."""
    lines = text.split('\n')
    skip, notes, in_note, after = set(), [], False, False
    for i, ln in enumerate(lines):
        if after or '<!-- renovate:' in ln:
            after = True
        elif 'superseded (protocol' in ln.lower():
            in_note = re.match(r'[\s>*_-]*superseded \(protocol', ln, re.I) is not None
        elif not (in_note and ln.strip() and (ln[0] in ' \t' or ln.startswith('(line'))):
            in_note = False
            continue
        skip.add(i)
        notes.append(ln)
    act = []
    for i, ln in enumerate(lines):
        m = INDEX_LINK.match(ln)
        t = (ln[m.end():].lstrip(' —–-:') if m else '') if hook else ln
        t = ' '.join(plain(t[:4000]).split())
        if i not in skip and t:
            act.append((i + 1, t))
    quoted, out = fold(' '.join(notes)), []
    body = '\n'.join(t for _, t in act)
    quiet = re.search(r'0\.1[4-9]\.\d', body) or re.search(r'(?:regen|plans\.html)\W{0,12}none\b', body)
    for k, (rid, sev, rx, skp, corr) in enumerate(STALE_RULES):
        if (only_version and rid != 'old-version') or (quiet and rid in QUIET_RULES):
            continue
        hits = [(n, t, m) for n, t in act for m in [re.search(rx, t, re.I)] if m]
        if rid == FILE_LEVEL:  # one finding per file (first mention), unless the file also says plans regenerate
            hits = [] if any(re.search(skp, t, re.I) for _, t in act) else hits[:1]
        elif rid == 'old-version':
            hits = [h for h in hits if not re.search(r'0\.1[4-9]', h[1])
                    and not re.search(r'\b(?:vigente|current|target)\b', h[1][h[2].end():h[2].end() + 40], re.I)
                    and not re.search(r'\b(?:MCP|HTTP|TLS|SSH|OAuth|git)\b', h[1][max(0, h[2].start() - 25):h[2].start()], re.I)]
        elif skp:
            hits = [h for h in hits if not re.search(skp, h[1], re.I)]
        for n, t, m in hits:
            st = max(0, m.start() - 20) if m.start() > 40 else 0
            snip, history = t[st:st + 60], rid == 'old-version' and re.search(r'\b(?:ejecutada|added|shipped|desde|since)\b', t, re.I)
            if not (fold(snip)[:40] and fold(snip)[:40] in quoted):
                out.append((n, k, 'review' if history else sev, snip))
    return [(n, STALE_RULES[k][0], sev, snip) for n, k, sev, snip in sorted(out)]


def container_of(brain):
    """X for a brain at X/ai/ai-brain, X/docs/ai-brain or X/ai-brain; None for any other name."""
    parts = brain.rstrip(os.sep).split(os.sep)
    if parts[-1] != 'ai-brain' or len(parts) < 2:
        return None
    return os.sep.join(parts[:-2] if len(parts) > 2 and parts[-2] in ('ai', 'docs') else parts[:-1]) or os.sep


def empty_rules(**kw):
    return dict({'state': 'n/a', 'memory_dir': None, 'memory_dirs': [], 'files_scanned': 0, 'claude_files': 0, 'findings': []}, **kw)


def rules_block(brain, args):
    """RULES block: scans memory files, CLAUDE.md/AGENTS.md and the brain README; never writes anything."""
    block = empty_rules()
    if args.no_rules:
        return dict(block, skipped=True)
    home = os.path.expanduser('~')
    cfg = os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR') or '~/.claude')
    proj = os.path.join(cfg, 'projects')
    cfgs = {os.path.realpath(d) for d in glob.glob(os.path.join(glob.escape(home), '.claude*')) + [cfg]}
    heads = [brain, os.path.realpath(brain)]  # abspath and realpath spellings of the brain and its container
    conts = [c for c in (container_of(h) for h in heads) if c]
    conts += [os.path.realpath(c) for c in conts]
    names = list(dict.fromkeys(conts + heads))
    if args.memory_dir:
        mdirs = [os.path.abspath(os.path.expanduser(args.memory_dir))]
    else:  # derived dirs count only inside <config>/projects/
        mdirs = [d for d in (os.path.join(proj, re.sub(r'[^A-Za-z0-9]', '-', n), 'memory') for n in names)
                 if os.path.realpath(d).startswith(os.path.realpath(proj) + os.sep)]
    mdirs = [d for k, d in enumerate(mdirs) if os.path.isdir(d) and os.path.realpath(d) not in map(os.path.realpath, mdirs[:k])]
    srcs = []  # (path, shown, hook text only, version rule only, is CLAUDE.md/AGENTS.md)
    for d in mdirs:
        try:
            listing = sorted(n for n in os.listdir(d) if n.endswith('.md') and not IGNORED_NAME.search(n))
        except OSError:
            listing = []
        for n in listing:
            path = os.path.join(d, n)
            shown = n if len(mdirs) < 2 else os.path.relpath(path, proj) if path.startswith(proj + os.sep) else path
            srcs.append((path, shown, n == 'MEMORY.md', False, False))
    for base in dict.fromkeys(conts + [os.path.join(c, 'ai') for c in conts] + heads):
        for n in ('CLAUDE.md', 'AGENTS.md'):
            srcs.append((os.path.join(base, n), os.path.join(base, n), False, False, True))
    srcs.append((os.path.join(brain, 'README.md'),) * 2 + (False, True, False))
    done = set()
    for path, shown, hook, ver, claude in srcs:
        real = os.path.realpath(path)
        guarded = os.path.dirname(real) in cfgs and os.path.basename(real).lower() in ('claude.md', 'agents.md', 'orchestrator.md')
        text = None if real in done or guarded else read_text(path)  # a config dir's own instruction files are never targets
        if text is None:
            continue
        done.add(real)
        block['files_scanned'] += 1
        block['claude_files'] += claude
        for n, rid, sev, snip in scan_file(text, hook, ver):
            info = next(r for r in STALE_RULES if r[0] == rid)
            block['findings'].append({'file': shown, 'line': n, 'id': rid, 'severity': sev, 'snippet': snip,
                                      'correction': info[4].replace('<target>', TARGET)})
    fix = sum(f['severity'] == 'fix' for f in block['findings'])
    block.update(memory_dir=mdirs[0] if mdirs else None, memory_dirs=mdirs,
                 state='needed' if fix else 'ok' if block['files_scanned'] else 'n/a')
    return block


# ---------------------------------------------------------------- rendering
def lacks(m, found):
    gone = [t for t in TYPES if not m['types'][t]]
    out = ['types(%s)' % ','.join(gone)] if gone else []
    out += [('protocol-line(%s≠%s)' % (found, TARGET) if key == 'protocol_line' and found else name)
            for key, name in FLAGS if not m[key]]
    out += [RETIRED] if m.get('auto_merge') else []
    k = m['skills_lines']
    return out + (['skills %d/%d pending(☐🔄⛔⏸)' % (k['have'], k['pending_waves'])] if k['have'] != k['pending_waves'] else [])


def hook_lines(h):
    """`review:` lines for the hooks that are missing or differ from the template (advice only: never in `needed`)."""
    where = '$CLAUDE_CONFIG_DIR/hooks' if os.environ.get('CLAUDE_CONFIG_DIR') else '~/.claude/hooks'
    out = []
    if not h['merge_guard']:
        out.append('  · review: merge-guard hook missing in %s → the owner installs templates/merge-guard.py (PreToolUse, matcher Bash|mcp__.*merge.*) with !' % where)
    if h['artifact_guard'] == 'missing':
        out.append('  · review: artifact-guard hook missing in %s → the owner installs templates/artifact-guard.py (Stop) with !' % where)
    elif h['artifact_guard'] == 'outdated':
        out.append('  · review: artifact-guard hook outdated in %s (differs from templates/artifact-guard.py) → the owner refreshes it with !' % where)
    return out


def render(brain, module, args, p, b, mods, inv, stats, needed):
    unk = p['found'] or 'unknown' + (' (~%s)' % p['inferred'] if p['inferred'] != 'unknown' else '')
    pre = ['RENOVATE %s%s · protocol %s → target %s' % (brain, ' · module ' + module if module else '', unk, TARGET)]
    s, a, e, t, c = (b[k] for k in ('scripts', 'artifacts', 'execute', 'task', 'context'))
    pre.append('SCRIPTS n/a (root only)' if s['state'] == 'n/a' else 'SCRIPTS %s' % s['state'] + ''.join(
        ' · %s %s' % (lab, ', '.join(s[k])) for k, lab in (('missing', 'missing'), ('outdated', 'custom:'),
                                                          ('copied', 'copied'), ('failed', 'failed'),
                                                          ('cache_dep', 'cache-dep:')) if s[k])
               + (' → ' + CACHE_FIX if s['cache_dep'] else ''))
    r = a['rows_without_regen']
    pre.append('ARTIFACTS n/a (no registry)' if a['state'] == 'n/a' else
               'ARTIFACTS unparsed (artifacts.json is not a registry)' if a['state'] == 'unparsed' else
               'ARTIFACTS %s · %d rows%s' % (a['state'], a['total'], ' · %d without regen' % len(r) if r else ''))
    rows_l = ['  %s → %s' % (x['file'], x['suggest']) for x in r]
    rev_l = (['  · review: no active_account declared → courier-preflight <docs_dir> --set-active-account <name>']
             if a.get('no_active_account') else [])  # advice only: never in `needed`
    why = lacks(e['markers'], p['found']) if e['markers'] else []
    exe_l = (['  · review: reviewer pending → owner sets @handle in the `> **Reviewer:**` header line']
             if e['markers'] and e['markers']['reviewer_pending'] else [])  # advice only: never in `needed`
    mid = ['EXECUTE n/a (no execute.md)' if e['state'] == 'n/a' else
           'EXECUTE %s%s' % (e['state'], ' · lacks ' + ', '.join(why) if why else '')]
    nxt = ' · last entry Next: %s' % ('yes' if t['last_entry_has_next'] else 'no')
    mid.append('TASK n/a (no task.md)' if t['state'] == 'n/a' else
               'TASK missing · no DoD-human pending section' + nxt if t['state'] == 'missing' else
               'TASK ok%s%s' % (' · DoD-human pending' if t['shape'] == 'canonical' else
                                ' (legacy shape: %s)' % t['heading'], nxt))
    ru, rules_l = b['rules'], []
    if ru.get('skipped') or module:
        mid.append('RULES n/a · skipped' if ru.get('skipped') else 'RULES n/a (root only)')
    else:
        fx = sum(f['severity'] == 'fix' for f in ru['findings'])
        mid.append('RULES %s · memory %s · claude.md %d · findings %d (fix %d · review %d)' % (
            ru['state'], ru['memory_dir'] or 'none', ru['claude_files'], len(ru['findings']), fx, len(ru['findings']) - fx))
        rules_l = ['  %s:%d %s — %s' % (f['file'], f['line'], f['id'], f['snippet']) for f in ru['findings'][:6]]
        rules_l += ['  … +%d more (use --json)' % (len(ru['findings']) - 6)] if len(ru['findings']) > 6 else []
    hook_l = hook_lines(b['hooks'])
    after = [('CONTEXT n/a (business-context only)' if c['state'] == 'n/a' else 'CONTEXT ok (%s)%s · last_scanned %s' % (
        c['skill'], ' · plugin ' + c['plugin'] if c['plugin'] else '', c['last_scanned'] or 'unknown'))]
    mod_l = []
    if args.all_modules:
        after.append('MODULES %d' % len(mods) if mods else 'MODULES none')
        mod_l = ['  %s %s' % (m['module'], 'needed(%s)' % ','.join(m['needed']) if m['needed'] else 'up-to-date') for m in mods]
    inv_l = []
    if inv:
        fmt = lambda x, n: ' '.join('%s=%d' % kv for kv in x.items()) + ' · lines=%d' % n['execute_lines']
        inv_l = ['INVARIANTS ' + fmt(inv, stats)] + ['INVARIANTS %s %s' % (m['module'], fmt(m['invariants'], m['stats'])) for m in mods]
    last = 'RENOVATE: needed(%s)' % ','.join(needed) if needed else 'RENOVATE: up-to-date'
    head = lambda: pre + rows_l + rev_l + mid[:1] + exe_l + mid[1:] + rules_l + hook_l + after + mod_l
    fits = lambda: len(head() + inv_l) + 1 <= MAX_LINES
    if not fits() and (rows_l or rev_l):  # shed order: registry rows (+ the review line), reviewer/hook advice, module lines, RULES findings, module INVARIANTS (the root one stays)
        rows_l = ['  … %d rows without regen (use --json)' % len(rows_l)] if rows_l else []
        rev_l = []
    if not fits() and (exe_l or hook_l):
        exe_l, hook_l = [], []
    if not fits() and mod_l:
        mod_l = ['  … %d modules, %d need work (use --json)' % (len(mods), sum(bool(m['needed']) for m in mods))]
    if not fits() and rules_l:
        rules_l = ['  … %d findings (use --json)' % len(ru['findings'])]
    if not fits():
        room = MAX_LINES - len(head()) - 1
        inv_l = inv_l[:room - 1] + ['INVARIANTS … %d module lines not shown (use --json)' % (len(inv_l) - room + 1)]
    return head() + inv_l + [last]


def emit(args, data, lines, code):
    data['text'] = lines
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else '\n'.join(lines))
    return code


def run(args):
    brain = os.path.abspath(os.path.expanduser(args.brain))
    module = args.module.strip('/') if args.module else None
    skill_dir = os.path.abspath(os.path.expanduser(args.skill_dir)) if args.skill_dir else os.path.dirname(os.path.abspath(__file__))
    base = {'version': __version__, 'target': TARGET, 'brain': brain, 'module': module}
    tdir = os.path.join(brain, module) if module else brain

    def fail(reason):
        return emit(args, base, ['RENOVATE %s%s' % (brain, ' · module ' + module if module else ''),
                                 'RENOVATE: unparsed (%s)' % reason], 2)

    if not os.path.isdir(brain):
        return fail('brain dir not found')
    if not os.path.isdir(tdir):
        return fail('module dir not found: %s' % module)
    ex = os.path.join(tdir, 'execute.md')
    if read_text(ex) is None and (module is None or os.path.lexists(ex) or not os.path.isfile(os.path.join(tdir, 'task.md'))):  # a module may lack execute.md, never both
        big = os.path.isfile(ex) and os.path.getsize(ex) > MAX_BYTES
        return fail('execute.md too large' if big else
                    'execute.md is not readable' if os.path.lexists(ex) else 'no execute.md')
    lang = 'es' if any(os.path.isfile(os.path.join(brain, n)) for n in DOCS_ES) else 'en'
    rev = review(tdir, lang)
    scripts = ({'state': 'n/a', 'missing': [], 'outdated': [], 'copied': [], 'failed': [], 'cache_dep': []} if module else
               scripts_block(brain, skill_dir, args.copy_scripts, args.force_outdated))
    mods = []
    for rel in list_modules(brain) if args.all_modules else ():
        sub = review(os.path.join(brain, rel), lang)
        mods.append(dict({'module': rel, 'needed': sub['needed']},
                         **({'invariants': sub['inv'], 'stats': sub['stats']} if args.invariants else {})))
    rb = rev['blocks']
    rules = rules_block(brain, args) if not module else empty_rules()
    blocks = {'scripts': scripts, 'artifacts': rb['artifacts'], 'execute': rb['execute'], 'task': rb['task'],
              'rules': rules, 'context': rb['context'], 'modules': mods, 'hooks': hooks_block(skill_dir)}
    needed = [b for b in BLOCKS if (b == 'modules' and any(m['needed'] for m in mods)) or (
        b not in ('modules', 'context') and blocks[b]['state'] in NEED)]
    inv = rev['inv'] if args.invariants else None
    data = dict(base, protocol=rev['protocol'], blocks=blocks, needed=needed, invariants=inv, stats=rev['stats'])
    lines = render(brain, module, args, rev['protocol'], blocks, mods, inv, rev['stats'], needed)
    return emit(args, data, lines, 1 if needed else 0)


class Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would exit 2, which is the "unparsed" code
        self.exit(64, '%s\n%s: error: %s\n' % (self.format_usage().rstrip(), self.prog, message))


def main(argv=None):
    args = None
    try:
        ap = Parser(prog='renovate_check.py', allow_abbrev=False,
                    description='What an existing brain lacks against the current execution protocol.')
        ap.add_argument('--brain', required=True, help='docs dir holding execute.md and task.md')
        ap.add_argument('--module', metavar='REL', help='module dir relative to --brain (modules/<m>)')
        ap.add_argument('--skill-dir', metavar='PATH', help='holds templates/<name> (default: this script\'s directory)')
        ap.add_argument('--copy-scripts', action='store_true', help='copy the missing scripts/ files from the templates')
        ap.add_argument('--force-outdated', action='store_true', help='with --copy-scripts: overwrite differing copies too')
        ap.add_argument('--memory-dir', metavar='PATH', help='scan this memory dir instead of the resolved one')
        ap.add_argument('--no-rules', action='store_true', help='skip the RULES block')
        for flag in ('--all-modules', '--invariants', '--json'):
            ap.add_argument(flag, action='store_true')
        ap.add_argument('--version', action='version', version='renovate_check.py ' + __version__)
        args = ap.parse_args(argv)
        if args.module and args.all_modules:
            ap.error('--module and --all-modules are mutually exclusive')
        if args.module and '..' in re.split(r'[\\/]+', args.module):
            ap.error('--module must not contain ".."')
        if args.force_outdated and not args.copy_scripts:
            ap.error('--force-outdated needs --copy-scripts')
        for stream in (sys.stdout, sys.stderr):
            stream.reconfigure(encoding='utf-8', errors='replace')
        return run(args)
    except Exception as exc:
        line = 'RENOVATE: unparsed (internal error: %s)' % type(exc).__name__[:30]
        if args is not None and args.json:
            print(json.dumps({'version': __version__, 'text': [line]}, ensure_ascii=False, indent=2))
        else:
            print(line)
        return 2


if __name__ == '__main__':
    sys.exit(main())
