#!/usr/bin/env python3
"""plan-audit - deterministic gate for the planning-time contradiction audit (stdlib only).

The auditor (templates/plan-audit-brief.md) returns a report that is saved verbatim as
`<brain>/qa/plan-audit.md`; its first line must be `PLAN-AUDIT: PASS|FAIL · contradictions <n> · open <n>`.
`--seal` stamps a script-owned block at the end of that report: one row per wave with the sha256 of the
wave's NORMALISED heading blocks in the detailed plan and in execute.md. `--check` proves the report
exists, passed with nothing open, is sealed, and that no sealed wave changed since.

Usage:
  plan_audit.py --brain DIR [--module M] (--seal | --check [--wave ID]) [--json]

Exit codes: 0 ok · 1 missing report / FAIL / open > 0 / unsealed / nothing to seal ·
2 stale only (some sealed wave changed; --json lists them) · 64 usage.
--json prints {status, reasons, stale_waves, sealed_at, started_waves}.
Done waves (✅ in the wave-map row) and started waves (a handoff closing phase b-e, or phase a with Result
done|partial) are exempt from the fingerprint comparison: never stale, also under --wave. --seal covers all.

Waves = the bold ids of the `## Wave map` table of task.md (fallback: execute.md). A wave's blocks =
every heading (outside code fences) that names the wave id as a whole token, with its content up to the
next heading of the same or higher level; blocks nested in an already taken block are not repeated.
Normalised away before hashing: checkbox ticks, status glyphs and the status text a heading carries after
them, dates, runs of spaces, blank lines. A wave with no block in a file hashes as `-`.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

START, END = '<!-- plan-audit:seal:start -->', '<!-- plan-audit:seal:end -->'
FIRST = re.compile(r'^PLAN-AUDIT:\s*(PASS|FAIL)\s*·\s*contradictions\s+(\d+)\s*·\s*open\s+(\d+)\s*$')
GL = '✅⛔⏸🔄☐'
PLANS = ('detailed-plan.md', 'plan-detallado.md')
ROW = re.compile(r'^\|\s*([A-Z][A-Za-z0-9-]*)\s*\|\s*([0-9a-f]{64}|-)\s*\|\s*([0-9a-f]{64}|-)\s*\|\s*$')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        print('usage error: ' + message, file=sys.stderr)
        sys.exit(64)


def read(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


def wave_map(base):
    """([wave ids], {done ids}) of the wave-map table (task.md, else execute.md), in document order.
    Done = a cell of the row that starts with ✅."""
    for name in ('task.md', 'execute.md'):
        text = read(os.path.join(base, name))
        if text is None:
            continue
        sec = re.search(r'^##\s+(?:\d+\.\s*)?(?:wave map|mapa de olas)\b.*?$(.*?)(?=^##\s|\Z)', text, re.M | re.S | re.I)
        ids, done = [], set()
        for line in (sec.group(1) if sec else '').split('\n'):
            if line.lstrip().startswith('|'):
                for cell in line.split('|')[1:]:
                    m = re.match(r'\s*\*\*([A-Z][A-Za-z0-9-]*)\*\*', cell)
                    if m and m.group(1) not in ids:
                        ids.append(m.group(1))
                        if any(c.strip().startswith('✅') for c in line.split('|')[1:]):
                            done.add(m.group(1))
                        break
        if ids:
            return ids, done
    return [], set()


def started_waves(base):
    """Waves with a handoff `<base>/handoffs/<Wave>-<nn>-<phase>.md` that closes phase b-e, or phase a with
    Result done|partial (a phase-a handoff with Result fail does not count)."""
    out, hdir = set(), os.path.join(base, 'handoffs')
    for name in sorted(os.listdir(hdir)) if os.path.isdir(hdir) else []:
        m = re.match(r'^(.+)-\d{2,}-[a-e]\.md$', name)
        text = read(os.path.join(hdir, name)) or ''
        ph = re.search(r'^\s*[-*]\s+\*\*Phase closed:\*\*\s*([a-eA-E])\b', text, re.M)
        res = re.search(r'^\s*[-*]\s+\*\*Result:\*\*\s*(\w+)', text, re.M)
        if m and ph and (ph.group(1).lower() != 'a' or (res and res.group(1).lower() in ('done', 'partial'))):
            out.add(m.group(1))
    return out


def headings(lines):
    """[(index, level, text)] of ATX headings outside code fences."""
    out, fence = [], None
    for i, line in enumerate(lines):
        f = re.match(r'^\s*(`{3,}|~{3,})', line)
        if f:
            if fence is None:
                fence = f.group(1)
            elif f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence) and line.strip() == f.group(1):
                fence = None
            continue
        h = re.match(r'^(#{1,6})\s+(.*)$', line)
        if fence is None and h:
            out.append((i, len(h.group(1)), h.group(2)))
    return out


def norm_line(line, heading):
    if heading:
        m = re.match(r'^(#{1,6}\s+)(?:[%s]\s*)?(.*)$' % GL, line)  # a leading glyph is removed below
        if m:
            line = m.group(1) + re.sub(r'\s+(?:[—–-]\s+|\(\s*)?(?=[%s]).*$' % GL, '', m.group(2))
    line = re.sub(r'\[[xX ]\]', '[ ]', line)
    line = re.sub('[%s️]' % GL, '', line)
    line = re.sub(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?', '', line)
    line = re.sub(r'\(\s*\)', '', line)
    return re.sub(r'\s+', ' ', line).strip()


def wave_blocks(text, wid):
    """Normalised text of every block whose heading names `wid`, or '' when there is none."""
    lines = text.split('\n')
    hs = headings(lines)
    token = re.compile(r'(?<![A-Za-z0-9-])%s(?![A-Za-z0-9-])' % re.escape(wid))
    heads = {j for j, _, _ in hs}
    taken, last_end = [], -1
    for n, (i, lvl, title) in enumerate(hs):
        if i < last_end or not token.search(title):
            continue
        end = next((j for j, l2, _ in hs[n + 1:] if l2 <= lvl), len(lines))
        body = [norm_line(l, k in heads) for k, l in enumerate(lines[i:end], i)]
        taken.append('\n'.join(b for b in body if b))
        last_end = end
    return '\n--\n'.join(taken)


def digest(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest() if s else '-'


def fingerprints(base):
    """The ONE fingerprint computation: ({wave: (detailed sha | '-', execute sha | '-')}, ordered ids)."""
    ids = wave_map(base)[0]
    plan = '\n'.join(t for t in (read(os.path.join(base, n)) for n in PLANS) if t)
    exe = read(os.path.join(base, 'execute.md')) or ''
    return {w: (digest(wave_blocks(plan, w)), digest(wave_blocks(exe, w))) for w in ids}, ids


def report_state(report):
    """(problems, text): everything the verdict line alone proves."""
    text = read(report)
    if text is None:
        return ['no report at qa/plan-audit.md'], None
    m = FIRST.match(text.split('\n', 1)[0].strip().lstrip('﻿'))
    if not m:
        return ['first line of the report is not PLAN-AUDIT: PASS|FAIL · contradictions <n> · open <n>'], text
    out = []
    if m.group(1) != 'PASS':  # MUTATION-KEY: verdict
        out.append('report verdict is FAIL (%s contradictions)' % m.group(2))
    if int(m.group(3)) > 0:  # MUTATION-KEY: open
        out.append('%s open question(s) in the report' % m.group(3))
    return out, text


def read_seal(text):
    """({wave: (d, e)}, sealed_at) of the seal block, or (None, None) when there is none."""
    a, b = text.find(START), text.find(END)
    if a < 0 or b < a:
        return None, None
    rows, at = {}, None
    for line in text[a + len(START):b].split('\n'):
        m = ROW.match(line.strip())
        if m:
            rows[m.group(1)] = (m.group(2), m.group(3))
        elif line.startswith('sealed:'):
            at = line.split(':', 1)[1].strip()
    return rows, at


def do_check(base, wave, fps, ids):
    """(status, reasons, stale_waves, sealed_at, started_waves). Done and started waves are never stale."""
    done, started = wave_map(base)[1], started_waves(base)
    problems, text = report_state(os.path.join(base, 'qa', 'plan-audit.md'))
    if problems:
        return 'fail', problems, [], None, sorted(started)
    seal, at = read_seal(text)
    if seal is None:
        return 'fail', ['report is not sealed (run plan-audit --seal after a PASS)'], [], None, sorted(started)
    scope = [wave] if wave else ids
    stale = [w for w in scope if w not in done and w not in started and seal.get(w) != fps[w]]  # MUTATION-KEY: fingerprint
    if stale:
        return 'stale', ['wave text changed since the seal: ' + ', '.join(stale)], stale, at, sorted(started)
    return 'ok', [], [], at, sorted(started)


def do_seal(base, fps, ids):
    path = os.path.join(base, 'qa', 'plan-audit.md')
    problems, text = report_state(path)
    if problems:
        return 'refused: ' + '; '.join(problems)
    if not ids:
        return 'refused: no waves found in the wave map'
    old, _ = read_seal(text)
    if old == {w: fps[w] for w in ids}:
        return 'sealed: unchanged (%d waves)' % len(ids)
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    block = [START, 'sealed: ' + now, '| Wave | Detailed plan | execute.md |', '|---|---|---|']
    block += ['| %s | %s | %s |' % (w, fps[w][0], fps[w][1]) for w in ids] + [END]
    a, b = text.find(START), text.find(END)
    if a >= 0 and b > a:
        text = text[:a] + '\n'.join(block) + text[b + len(END):]
    else:
        text = text.rstrip('\n') + '\n\n' + '\n'.join(block) + '\n'
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    return 'sealed: %d waves' % len(ids)


def main(argv=None):
    ap = Parser(description='Seal and check the planning-time contradiction audit.')
    ap.add_argument('--brain', required=True)
    ap.add_argument('--module')
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--seal', action='store_true')
    mode.add_argument('--check', action='store_true')
    ap.add_argument('--wave')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    if args.module and '..' in re.split(r'[\\/]+', args.module):
        ap.error('--module must not contain ".."')
    if args.wave and not args.check:
        ap.error('--wave goes with --check')
    base = os.path.abspath(os.path.expanduser(args.brain))
    if args.module:
        base = os.path.join(base, args.module.strip('/'))
    if not os.path.isdir(base):
        ap.error('brain dir not found: %s' % base)
    fps, ids = fingerprints(base)
    if args.wave and args.wave not in fps:
        ap.error('unknown wave %s (wave map: %s)' % (args.wave, ', '.join(ids) or 'none'))
    if args.seal:
        msg = do_seal(base, fps, ids)
        print('PLAN-AUDIT: ' + msg)
        return 1 if msg.startswith('refused') else 0
    status, reasons, stale, at, started = do_check(base, args.wave, fps, ids)
    if args.json:
        print(json.dumps({'status': status, 'reasons': reasons, 'stale_waves': stale, 'sealed_at': at, 'started_waves': started}))
    else:
        print('PLAN-AUDIT: %s%s' % (status, ' — ' + '; '.join(reasons) if reasons else ''))
    return {'ok': 0, 'fail': 1, 'stale': 2}[status]


if __name__ == '__main__':
    sys.exit(main())
