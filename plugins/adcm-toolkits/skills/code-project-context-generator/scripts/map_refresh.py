#!/usr/bin/env python3
"""map-refresh - render and refresh a brain's reuse map from a scan of the project (stdlib only).

Writes <brain>/map/utilities.md, patterns.md and where-to-look.md (a module brain keeps its own map/
under modules/<mod>/). Each file holds one block per project, opened by the marker

  <!-- map-refresh: scan YYYY-MM-DD · project <path relative to the container> · format 1 — rows regenerate; ✍ columns are human and preserved -->

and closed by `<!-- end map-refresh -->`, followed by `## Curated (human)` and `## Retired (review)`.
Rows inside a block regenerate from scan_project.py; a column whose header starts with `✍ ` is human
text that every refresh keeps, keyed by (Symbol, Path) for utilities, the pattern slug for patterns and
Path for where-to-look. A row that leaves the scan with ✍ text moves to Retired with the date; without
text it is dropped; a symbol that moved to another path keeps its text.

Usage:
  map-refresh --project <root> [--brain <dir>] [--update <paths,>] [--human '<Symbol>@<path>=<what>|<when>']...
              [--context-skill <dir>] [--max-depth N] [--dry-run] [--json]
  map-refresh --brain <dir> --check
  map-refresh --brain <dir> --init

It writes only into the brain named by --brain or by the project's `ai-brain` symlink; a brain found by
searching upward is only suggested (exit 2). A symlinked map/ or map file is refused. Files are replaced
atomically, and a file whose rows did not change is left untouched, so a second run is byte-identical.
The check mode writes nothing: it rescans the project named by each block and compares keys, Kind and
Signature (utilities), keys, Status and count (patterns) and keys (where-to-look). The init mode writes
the three shells with no project block; such shells count as fresh.

Exit 0 written | unchanged | fresh · 1 stale · 2 missing | unresolved · 64 usage. At most 40 lines;
the last one is `MAP: <state>`.
"""
import argparse
import datetime
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_project  # noqa: E402
from scan_project import ProjectScanner, delta  # noqa: E402

MAP_FORMAT = 1
FILES = ('utilities.md', 'patterns.md', 'where-to-look.md')
TEMPLATES = Path(__file__).resolve().parent.parent / 'templates' / 'map'
MAX_LINES = 40
EMPTY = '—'
COLUMNS = {
    'utilities.md': ('Symbol', 'Kind', 'Path', 'Signature', 'Consumers', 'Exemplar',
                     '✍ What it does', '✍ When to use'),
    'patterns.md': ('Pattern', 'Kind', 'Status', 'Evidence', 'Exemplar', '✍ When to apply', '✍ Anti-pattern'),
    'where-to-look.md': ('Path', 'Kind', 'Label', '✍ Answers'),
}
KEYS = {'utilities.md': ('Symbol', 'Path'), 'patterns.md': ('Pattern',), 'where-to-look.md': ('Path',)}
TAIL = ' — rows regenerate; ✍ columns are human and preserved -->'
BLOCK_RX = re.compile(r'^<!-- map-refresh: scan (\d{4}-\d{2}-\d{2}) · project (.+?) · format (\d+)'
                      + re.escape(TAIL) + r'\n(.*?)^<!-- end map-refresh -->$', re.M | re.S)
END = '<!-- end map-refresh -->'
CURATED, RETIRED = '## Curated (human)', '## Retired (review)'
WHERE_KIND = {'Project README': 'readme', 'Claude instructions': 'agent-instructions',
              'Agent instructions': 'agent-instructions', 'OpenAPI spec': 'openapi'}
CONTEXT_DOCS = ('usage-map', 'business-flows', 'security', 'tech-debt')
EXIT = {'written': 0, 'unchanged': 0, 'fresh': 0, 'stale': 1, 'missing': 2, 'unresolved': 2}


class Unresolved(Exception):
    pass


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


def container_of(brain):
    """X for a brain at X/ai/ai-brain, X/docs/ai-brain or X/ai-brain; None for any other name."""
    parts = brain.rstrip(os.sep).split(os.sep)
    if parts[-1] != 'ai-brain' or len(parts) < 2:
        return None
    return os.sep.join(parts[:-2] if len(parts) > 2 and parts[-2] in ('ai', 'docs') else parts[:-1]) or os.sep


# ------------------------------------------------------------------ cells and rows
def code(text):
    return f'`{text}`' if text and '`' not in text else (text or EMPTY)


def bare(cell):
    return cell[1:-1] if len(cell) >= 2 and cell[0] == cell[-1] == '`' else cell


def esc(text):
    text = str(text).replace('\r', ' ').replace('\n', ' ').strip()
    return text.replace('|', '\\|') if text else EMPTY


def line(values):
    return '| ' + ' | '.join(esc(v) for v in values) + ' |'


def table(cols, rows):
    return [line(cols), '|' + '|'.join('---' for _ in cols) + '|'] + [line(r.get(c, EMPTY) for c in cols) for r in rows]


def parse_table(lines):
    """The first pipe table in `lines` as (header, rows as {column: cell}); ([], []) when there is none."""
    start = next((i for i, x in enumerate(lines) if x.lstrip().startswith('|')), None)
    if start is None:
        return [], []
    end = start
    while end < len(lines) and lines[end].lstrip().startswith('|'):
        end += 1
    found = [c for c in map(cells, lines[start:end]) if not all(re.fullmatch(r':?-+:?', x) for x in c)]
    return (found[0], [dict(zip(found[0], r)) for r in found[1:]]) if found else ([], [])


def key_of(name, row):
    return tuple(bare(row.get(c, '')) for c in KEYS[name])


def human(col):
    return col.startswith('✍ ')


def has_text(row):
    return any(human(c) and v not in ('', EMPTY) for c, v in row.items())


def bucket(n):
    if n < 1:
        return '0'
    if n == 1:
        return '1'
    if n <= 5:
        return '2–5'
    if n <= 20:
        return '6–20'
    return '20+'


def heading(path):
    try:
        with open(path, encoding='utf-8', errors='ignore') as fh:
            head = fh.read(2000)
    except OSError:
        head = ''
    found = re.search(r'^#[ \t]+(.+?)[ \t#]*$', head, re.M)
    return found.group(1) if found else re.sub(r'[-_]+', ' ', Path(path).stem).strip()


def brain_rows(brain):
    """Where-to-look rows for the brain's own docs, its decisions and the skills its protocol loads."""
    out = []
    for sub, kind in (('', 'brain-doc'), ('decisiones', 'decision'), ('decisions', 'decision')):
        folder = os.path.join(brain, sub)
        names = sorted(n for n in os.listdir(folder) if n.endswith('.md')
                       and os.path.isfile(os.path.join(folder, n))) if os.path.isdir(folder) else []
        for n in names[:scan_project.MAP_MAX_DOCS]:
            out.append({'Path': code('ai-brain/' + (sub + '/' if sub else '') + n), 'Kind': kind,
                        'Label': heading(os.path.join(folder, n))})
    protocol = os.path.join(brain, 'execute.md')
    if os.path.isfile(protocol):
        with open(protocol, encoding='utf-8', errors='ignore') as fh:
            named = {s for x in fh if 'Load the skill' in x for s in re.findall(r'`([\w:.-]+)`', x)}
        out.extend({'Path': code(s), 'Kind': 'skill', 'Label': 'skill loaded by the protocol'} for s in sorted(named))
    return out


def context_rows(skill):
    """Where-to-look rows for the usage-map, business-flows, security and tech-debt docs of a context skill."""
    name, out = os.path.basename(os.path.normpath(skill)), []
    for stem in CONTEXT_DOCS:
        rel = next((r for r in (stem + '.md', 'references/' + stem + '.md')
                    if os.path.isfile(os.path.join(skill, r))), None)
        if rel:
            out.append({'Path': code(f'{name}/{rel}'), 'Kind': 'context', 'Label': heading(os.path.join(skill, rel))})
    return out


def scan_rows(project, brain, depth, ctx_rows):
    """(scanner result, {file: rendered rows}) for one project."""
    result = ProjectScanner(Path(project), max_depth=depth).scan()
    m = result['map']
    utilities = [{'Symbol': code(u['symbol']), 'Kind': u['kind'], 'Path': code(u['path']),
                  'Signature': code(u['signature']), 'Consumers': bucket(u['consumers_count']),
                  'Exemplar': code(u['exemplar'])} for u in m['utilities']]
    patterns = []
    for p in m['patterns']:
        evidence = [str(p['count'])]
        if p['base'] and p['kind'] == 'types':
            evidence.append(p['base'])
        elif p['base'] and p['kind'] == 'shape':
            evidence.append('base ' + code(p['base']))
        if p['evidence_paths']:
            evidence.append(', '.join(code(e) for e in p['evidence_paths']))
        patterns.append({'Pattern': code(p['name']), 'Kind': p['kind'], 'Status': p['status'],
                         'Evidence': ' · '.join(evidence), 'Exemplar': code(p['exemplar'])})
    where = {w['path']: {'Path': code(w['path']), 'Kind': WHERE_KIND.get(w['topic'], 'doc'), 'Label': w['topic']}
             for w in m['where_to_look']}
    for r in brain_rows(brain) + (ctx_rows or []):
        where.setdefault(bare(r['Path']), r)
    return result, {'utilities.md': utilities, 'patterns.md': patterns,
                    'where-to-look.md': [where[k] for k in sorted(where)]}


def merge(name, new_rows, old_rows, retired_rows, today):
    """The new rows carrying their ✍ text, the updated Retired rows and how many rows were dropped.

    Text comes from the same key in the old block, else (utilities) from a vanished row of the same
    Symbol, else from a Retired row of the same key, which then leaves Retired.
    """
    hcols = [c for c in COLUMNS[name] if human(c)]
    old = {key_of(name, r): r for r in old_rows}
    keys = {key_of(name, r) for r in new_rows}
    gone = [r for k, r in old.items() if k not in keys]
    moved = {}
    for r in gone if name == 'utilities.md' else ():
        moved.setdefault(bare(r['Symbol']), r)
    retired = {key_of(name, r): r for r in retired_rows}
    rows, taken = [], set()
    for r in new_rows:
        k = key_of(name, r)
        src = old.get(k)
        if src is None and name == 'utilities.md' and id(moved.get(k[0])) not in taken:
            src = moved.get(k[0])
        if src is None:
            src = retired.pop(k, None)
        if src is not None:
            taken.add(id(src))
        rows.append(dict(r, **{c: (src or {}).get(c) or EMPTY for c in hcols}))
    dropped, leaving = 0, []
    for r in gone:
        if id(r) in taken:
            continue
        if has_text(r):
            retired.pop(key_of(name, r), None)
            leaving.append(dict(r, Retired=today))
        else:
            dropped += 1
    return rows, list(retired.values()) + leaving, dropped, len(leaving)


# ------------------------------------------------------------------ files
def marker(date, rel):
    return f'<!-- map-refresh: scan {date} · project {rel} · format {MAP_FORMAT}{TAIL}'


def shell(name, title):
    text = (TEMPLATES / (name + '.tmpl')).read_text(encoding='utf-8')
    return text.replace('{{PROJECT_NAME}}', title).replace('{{BLOCKS}}\n\n', '')


def anchor(text):
    """Offset of the first line naming the Curated or the Retired heading, else None."""
    for head in (CURATED, RETIRED):
        found = re.search('^' + re.escape(head) + '[ \t]*$', text, re.M)
        if found:
            return found.start()
    return None


def retired_table(text):
    """(start, end, rows) of the table in the Retired section; start == end where none exists yet."""
    head = re.search('^' + re.escape(RETIRED) + '[ \t]*$', text, re.M)
    if not head:
        return None
    nxt = re.compile(r'^## ', re.M).search(text, head.end())
    stop = nxt.start() if nxt else len(text)
    spans = list(re.finditer(r'^[ \t]*\|.*$', text[head.end():stop], re.M))
    if not spans:
        return stop, stop, []
    first, last = spans[0], spans[0]
    for x in spans[1:]:
        if text[head.end() + last.end():head.end() + x.start()] != '\n':
            break
        last = x
    start, end = head.end() + first.start(), head.end() + last.end()
    return start, end, parse_table(text[start:end].split('\n'))[1]


def refresh_text(name, text, title, rel, new_rows, today, humans, keep_context):
    """(new text, stats) for one map file; `text` is None when the file does not exist yet."""
    text = shell(name, title) if text is None else text
    mine = next((b for b in BLOCK_RX.finditer(text) if b.group(2) == rel), None)
    old_rows = parse_table(mine.group(4).split('\n'))[1] if mine else []
    if keep_context:
        have = {key_of(name, r) for r in new_rows}
        carried = [{c: r.get(c, EMPTY) for c in COLUMNS[name] if not human(c)} for r in old_rows
                   if r.get('Kind') == 'context' and key_of(name, r) not in have]
        new_rows = sorted(new_rows + carried, key=lambda r: bare(r['Path']))
    span = retired_table(text)
    rows, retired, dropped, left = merge(name, new_rows, old_rows, span[2] if span else [], today)
    for r in rows if humans else ():
        what, when = humans.get(key_of(name, r), ('', ''))
        r['✍ What it does'] = what or r['✍ What it does']
        r['✍ When to use'] = when or r['✍ When to use']
    body = '\n'.join([f'### Project `{rel}`', ''] + table(COLUMNS[name], rows)) + '\n'
    date = mine.group(1) if mine and mine.group(4) == body else today
    blk = marker(date, rel) + '\n' + body + END
    if mine:
        text = text[:mine.start()] + blk + text[mine.end():]
    else:
        at = anchor(text)
        text = (text[:at] + blk + '\n\n' + text[at:]) if at is not None else text.rstrip('\n') + '\n\n' + blk + '\n'
    span = retired_table(text)
    if retired != (span[2] if span else []):
        lines = '\n'.join(table(COLUMNS[name] + ('Retired',), retired))
        if span is None:
            text = text.rstrip('\n') + f'\n\n{RETIRED}\n\n{lines}\n'
        elif span[0] == span[1]:
            rest = text[span[0]:]
            text = text[:span[0]].rstrip('\n') + '\n\n' + lines + '\n' + ('\n' + rest if rest else '')
        else:
            text = text[:span[0]] + lines + text[span[1]:]
    old_keys = {key_of(name, o) for o in old_rows}
    new = [r for r in rows if key_of(name, r) not in old_keys]
    return text, {'rows': len(rows), 'new': [' @ '.join(key_of(name, r)) for r in new],
                  'retired': left, 'dropped': dropped}


def guard(brain):
    """Why the brain's map/ must not be written or read through, else None."""
    folder = os.path.join(brain, 'map')
    if os.path.islink(folder):
        return 'map/ is a symlink; nothing written'
    if os.path.exists(folder) and not os.path.isdir(folder):
        return 'map is not a directory'
    for f in FILES:
        if os.path.islink(os.path.join(folder, f)):
            return f'map/{f} is a symlink; nothing written'
    return None


def write(brain, name, text):
    folder = os.path.join(brain, 'map')
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, name)
    if os.path.islink(folder) or os.path.islink(target) or os.path.dirname(os.path.realpath(target)) != folder:
        raise Unresolved(f'map/{name} resolves outside the brain; nothing written')
    mode = stat.S_IMODE(os.stat(target).st_mode) if os.path.exists(target) else 0o644
    fd, tmp = tempfile.mkstemp(dir=folder, prefix='.' + name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read(path):
    with open(path, encoding='utf-8', newline='') as fh:
        return fh.read()


# ------------------------------------------------------------------ resolution
def shown(path):
    """The path relative to the working directory; a far one keeps only its last two parts, so output
    never names a home or user folder."""
    rel = os.path.relpath(path).replace(os.sep, '/')
    common = os.path.commonpath([os.getcwd(), path])
    far = rel.split('/').count('..') > 3 or common in (os.sep, os.path.dirname(os.path.expanduser('~')))
    return '…/' + '/'.join(rel.split('/')[-2:]) if far else rel


def module_root(brain):
    """The root brain of a module brain (<root>/modules/<m>), else the brain itself."""
    parent = os.path.dirname(brain)
    return os.path.dirname(parent) if os.path.basename(parent) == 'modules' else brain


def base_of(brain):
    """The directory that block headers name projects from: the container, else the brain's parent."""
    root = module_root(brain)
    return container_of(root) or os.path.dirname(root)


def title_of(brain):
    if module_root(brain) != brain:
        return os.path.basename(brain)
    c = container_of(brain)
    return os.path.basename(c) if c and c != os.sep else os.path.basename(brain)


def found_above(project):
    here = project
    while True:
        for rel in ('ai/ai-brain', 'ai-brain', 'docs/ai-brain'):
            p = os.path.join(here, *rel.split('/'))
            if os.path.isdir(p):
                return p
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def brain_dir(path):
    brain = os.path.realpath(path)
    if not os.path.isdir(brain):
        raise Unresolved('brain not found')
    err = guard(brain)
    if err:
        raise Unresolved(err)
    return brain


# ------------------------------------------------------------------ modes
def run_project(a, out):
    project = os.path.realpath(a.project)
    if not os.path.isdir(project):
        raise Unresolved('project not found')
    link = os.path.join(project, 'ai-brain')
    if a.brain:
        brain = brain_dir(a.brain)
    elif os.path.islink(link) and os.path.isdir(link):
        brain = brain_dir(link)
    else:
        hit = found_above(project)
        if hit is None:
            raise Unresolved('no brain: pass --brain <dir>')
        mods = os.path.isdir(os.path.join(hit, 'modules'))
        out['text'].append(f'  brain found above the project: pass --brain {shown(hit)}' + ('/modules/<mod>' if mods else ''))
        raise Unresolved('no --brain and no ai-brain symlink; nothing written')
    ctx_rows = None
    if a.context_skill:
        if not os.path.isdir(a.context_skill):
            raise Unresolved('context skill not found')
        ctx_rows = context_rows(a.context_skill)
    rel = os.path.relpath(project, base_of(brain)).replace(os.sep, '/')
    today = datetime.date.today().isoformat()
    out.update(brain=shown(brain), projects=[rel])
    out['text'].append(f'MAP {shown(brain)} · project {rel} · scan {today}')
    result, fresh_rows = scan_rows(project, brain, a.max_depth, ctx_rows)
    humans = {}
    for h in a.human:
        key, _, text = h.partition('=')
        sym, _, path = key.partition('@')
        what, _, when = text.partition('|')
        humans[(sym.strip(), path.strip().strip('/'))] = (what.strip(), when.strip())
    texts, changed = {}, []
    for name in FILES:
        path = os.path.join(brain, 'map', name)
        old = read(path) if os.path.exists(path) else None
        texts[name], st = refresh_text(name, old, title_of(brain), rel, fresh_rows[name], today,
                                       humans if name == 'utilities.md' else {},
                                       name == 'where-to-look.md' and ctx_rows is None)
        if texts[name] != old:
            changed.append(name)
        out['files'][name] = 'written' if name in changed else 'unchanged'
        out['new_rows'][name] = st['new']
        out['text'].append(f'  {name:<17} {st["rows"]} rows · +{len(st["new"])} new · {st["retired"]} retired · '
                           f'{st["dropped"]} dropped · ' + ('would write' if a.dry_run and name in changed
                                                            else out['files'][name]))
    if a.update:
        paths = [p.strip().strip('/') for p in a.update.split(',') if p.strip()]
        hit = delta(result, paths)['affected_map_rows']
        out['text'].append(f'  update: {len(hit["utilities"])} utilities · {len(hit["patterns"])} patterns '
                           f'touched by {len(paths)} path(s)')
    known = {key_of('utilities.md', r) for r in fresh_rows['utilities.md']}
    for k in sorted(humans):
        out['text'].append(f'  human: {"filled" if k in known else "unknown key (not written)"} {k[0]}@{k[1]}')
    if a.dry_run:
        for name in FILES:
            out['files'][name] = 'stale' if name in changed else 'unchanged'
        return f'stale({",".join(changed)})' if changed else 'unchanged'
    for name in changed:
        write(brain, name, texts[name])
    return 'written' if changed else 'unchanged'


def run_check(a, out):
    brain = brain_dir(a.brain)
    out['brain'] = shown(brain)
    out['text'].append(f'MAP {shown(brain)} · check')
    texts, missing = {}, []
    for name in FILES:
        path = os.path.join(brain, 'map', name)
        texts[name] = read(path) if os.path.isfile(path) else ''
        if 'map-refresh: scan' not in texts[name]:
            missing.append(name)
            out['files'][name] = 'missing'
    if missing:
        return f'missing({",".join(missing)})'
    base, scans = base_of(brain), {}
    projects = sorted({b.group(2) for t in texts.values() for b in BLOCK_RX.finditer(t)})
    out['projects'] = projects
    for rel in projects:
        project = os.path.normpath(os.path.join(base, rel))
        if not os.path.isdir(project):
            raise Unresolved(f'project {rel} not found')
        scans[rel] = scan_rows(project, brain, a.max_depth, None)[1]
    if not projects:
        out['text'].append('  note: no project block')
    stale = []
    for name in FILES:
        drift = []
        for b in BLOCK_RX.finditer(texts[name]):
            old, new = compared(name, parse_table(b.group(4).split('\n'))[1]), compared(name, scans[b.group(2)][name])
            if old != new:
                ko, kn = {r[0] for r in old}, {r[0] for r in new}
                drift.append(f'{b.group(2)}: +{len(kn - ko)} −{len(ko - kn)} ~{len(set(new) - set(old)) - len(kn - ko)}')
        out['files'][name] = 'stale' if drift else 'fresh'
        out['text'].append(f'  {name:<17} ' + ('stale · ' + ' · '.join(drift) if drift else 'fresh'))
        if drift:
            stale.append(name)
    return f'stale({",".join(stale)})' if stale else 'fresh'


def compared(name, rows):
    """What the check compares per row; Consumers and the ✍ text are informative only."""
    if name == 'utilities.md':
        return sorted((key_of(name, r), r.get('Kind'), r.get('Signature')) for r in rows)
    if name == 'patterns.md':
        count = lambda r: (re.match(r'\d+', r.get('Evidence', '')) or [None])[0]
        return sorted((key_of(name, r), r.get('Status'), count(r)) for r in rows)
    return sorted((key_of(name, r),) for r in rows if r.get('Kind') != 'context')


def run_init(a, out):
    brain = brain_dir(a.brain)
    out['brain'] = shown(brain)
    out['text'].append(f'MAP {shown(brain)} · init')
    wrote = []
    for name in FILES:
        if os.path.exists(os.path.join(brain, 'map', name)):
            out['files'][name] = 'unchanged'
        else:
            write(brain, name, shell(name, title_of(brain)))
            out['files'][name] = 'written'
            wrote.append(name)
        out['text'].append(f'  {name:<17} {out["files"][name]}')
    return 'written' if wrote else 'unchanged'


class Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would exit 2, which is the "missing | unresolved" code
        self.exit(64, '%s\n%s: error: %s\n' % (self.format_usage().rstrip(), self.prog, message))


def parse(argv):
    ap = Parser(prog='map-refresh', allow_abbrev=False,
                description='Render and refresh <brain>/map/{utilities,patterns,where-to-look}.md from a project '
                            'scan; ✍ columns are human text and survive every refresh.')
    ap.add_argument('--project', metavar='ROOT', help='project to scan and write the block of')
    ap.add_argument('--brain', metavar='DIR', help="brain dir (default: the project's ai-brain symlink)")
    ap.add_argument('--update', metavar='PATHS', help='comma-separated changed paths: report the map rows they touch')
    ap.add_argument('--human', action='append', default=[], metavar="'SYMBOL@PATH=WHAT|WHEN'",
                    help='fill the ✍ cells of that utility row (repeatable); an unknown key is reported')
    ap.add_argument('--context-skill', metavar='DIR', help="add that context skill's usage-map, business-flows, "
                                                           'security and tech-debt docs to where-to-look')
    ap.add_argument('--max-depth', type=int, default=8, metavar='N', help='scan depth (default: 8)')
    ap.add_argument('--dry-run', action='store_true', help='write nothing; report what would change')
    ap.add_argument('--json', action='store_true', help='print {brain, projects, files, state, new_rows, text}')
    ap.add_argument('--check', action='store_true', help='with --brain: rescan every block, write nothing')
    ap.add_argument('--init', action='store_true', help='with --brain: write the three shells, no project block')
    a = ap.parse_args(argv)
    if sum(map(bool, (a.project, a.check, a.init))) != 1:
        ap.error('pass exactly one of --project, --check, --init')
    if (a.check or a.init) and not a.brain:
        ap.error('--check and --init need --brain')
    if not a.project and (a.update or a.human or a.context_skill or a.dry_run):
        ap.error('--update, --human, --context-skill and --dry-run need --project')
    if a.max_depth < 1:
        ap.error('--max-depth must be at least 1')
    for h in a.human:
        if not re.fullmatch(r'[^@=]+@[^=]+=.*', h, re.S):
            ap.error(f"--human takes '<Symbol>@<path>=<what>|<when>', got {h!r}")
    return a


def main(argv=None):
    a = parse(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', errors='replace')
    out = {'brain': None, 'projects': [], 'files': {}, 'state': None, 'new_rows': {}, 'text': []}
    if a.check:
        mode = run_check
    elif a.init:
        mode = run_init
    else:
        mode = run_project
    try:
        state = mode(a, out)
    except Unresolved as exc:
        state = f'unresolved ({exc})'
    except Exception as exc:
        state = f'unresolved (internal error: {type(exc).__name__[:30]})'
    out['state'], lines = state, out['text']
    if a.json:
        print(json.dumps(dict(out, text=lines + ['MAP: ' + state]), ensure_ascii=False, indent=2))
    else:
        if len(lines) > MAX_LINES - 1:
            lines = lines[:MAX_LINES - 2] + [f'  … {len(lines) - MAX_LINES + 2} more lines (use --json)']
        print('\n'.join(lines + ['MAP: ' + state]))
    return EXIT[re.match(r'[a-z]+', state).group(0)]


if __name__ == '__main__':
    sys.exit(main())
