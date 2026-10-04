#!/usr/bin/env python3
"""Regenerate prompts.html's nav + cards from execute.md §7.

Why this exists: a hand-built prompts.html tends to carry each wave's status in TWO
places (the nav badge and the card badge) that get edited separately — and drift
apart. Here both are derived from the SAME §7 header, every run. If this page and
execute.md ever disagree, execute.md wins: just rerun this script.

Preserves the shell (head, styles, protocol section, copy-button/theme script)
untouched. It only replaces two things, found by three literal string markers:
  - the `nav-a` list: from the first `<a class="nav-a"` up to (not including) the
    next `<button class="btn" id="theme"`.
  - the wave cards: from the first `<section class="card"` up to (not including)
    the next `</main>`.
`templates/prompts-html.tmpl` (next to this script) is a standalone shell that
carries exactly those three hooks plus one placeholder nav entry and one
placeholder card, so `--init` can materialize a fresh prompts.html before the
first patch.

§7 header convention (see `templates/execute.md.tmpl`):
  `### Ola <ID> [— <title>] [— <status glyph + text>]`   (Spanish)
  `### Wave <ID> [— <title>] [— <status glyph + text>]`  (English)
`<ID>` is `[A-Z][A-Za-z0-9-]*`: digits, dashes and lowercase suffixes are fine (`W2`,
`WSEC-3`, `W2a`, `W2b` are four distinct cards; `hand_titles` matches ids case-insensitively).
A header with no title of its own (it starts straight into the status glyph, e.g.
`### Wave W2 — 🔄 IN PROGRESS (...)`) needs its title supplied some other way —
in precedence order: an optional `prompts-titles.json` ({"<ID>": "<title>"}, see
`--titles`), then whatever `<h2>` the wave's card already carries in the HTML
being patched, then finally the wave id itself as a last resort.

Status precedence (one glyph per wave, taken from the START of the header's
status text, else the first glyph found anywhere in it): ✅ > ⛔ > ⏸ > 🔄 > ☐.

Several deliveries per wave: every ```` ```text ```` fence between a wave header and the next
`### ` is a prompt. A fence preceded by a `## Entrega …` / `## Delivery …` heading carries that
heading (rendered as an `<h3>` with its own copy button and `<pre id="pre-<id>-N">`); a leading
fence with no heading keeps the header copy button (`<pre id="pre-<id>">`), so a single-delivery
wave renders exactly as it always did. Collecting stops at the next `## ` that is not an
Entrega/Delivery heading, so a later `## Notas` fence is never absorbed into the wave.

Closed waves (`--closed summary`, the default): a wave whose status glyph is ✅ — from its §7
header, or, when the header carries no status of its own, from the first cell (else the status
cell) of its `task.md` wave-map row — renders title · badge · short status · a one-line
"closed wave — prompt archived in execute.md §7" note, with NO `<pre>` and NO copy button
(the nav and badge show ✅ even when only the wave map said so, prompt or not). A wave with no prompt
keeps the "no standalone prompt" note. `--closed full` renders every prompt in full. Pending / in-progress / blocked
waves always render in full, so the page stays small as waves close.

Generic port of a venture-specific internal script (same name); the fixes made
during the port: an explicit --brain (nothing hardcoded), a bilingual §7 anchor,
optional prompts-titles.json instead of a hardcoded dict, an ES/EN LANG dict for
the generated UI strings, a shippable HTML shell + --init, and --check.

Usage:
  python3 prompts-regen.py <comma-list-of-wave-ids> <out.html> --brain <dir>
      [--lang es|en] [--project "<name>"] [--titles <path>] [--closed summary|full]
      [--init] [--check]

Exit codes: 0 ok/up to date · 1 --check stale (or <out> missing) or a usage error ·
2 --init but prompts-html.tmpl (next to this script) is missing.
`--init --check` never creates <out>: it reports that --init would and exits 1.
"""
import argparse
import html
import json
import pathlib
import re
import sys

GLYPH = re.compile(r'(✅|⛔|⏸|🔄|☐)')

# UI strings the script writes INTO each generated card. Everything else in the
# shell (hero, protocol box, copy-button/theme JS) lives in prompts-html.tmpl and
# is not touched here.
LANG = {
    'es': {
        'copy_btn': 'Copiar prompt',
        'no_prompt': 'Sin prompt propio en §7: ola ejecutada con el flujo anterior.',
        'real_status': 'Estado real (wave map de task.md):',
        'detail': 'Detalle en la bitácora de <code>task.md</code> y en la pestaña Pendientes de plans.html.',
        'closed': 'ola cerrada — prompt archivado en execute.md §7',
        'delivery': 'Entrega',
    },
    'en': {
        'copy_btn': 'Copy prompt',
        'no_prompt': 'No standalone prompt in §7: wave executed under a previous flow.',
        'real_status': 'Real status (task.md wave map):',
        'detail': 'Detail in the <code>task.md</code> logbook and the Pending tab of plans.html.',
        'closed': 'closed wave — prompt archived in execute.md §7',
        'delivery': 'Delivery',
    },
}


def parse_s7(exec_text):
    """Parse execute.md §7 into a list of {id, title, status, bodies, line} dicts,
    one per `### Ola|Wave <ID> ...` header, in document order. `bodies` is the wave's
    list of {heading, text} prompts (see the module docstring): `heading` is the text of
    the `## Entrega|Delivery …` line a fence sits under, or None for a headingless fence."""
    lines = exec_text.split('\n')
    start = next((i for i, l in enumerate(lines) if re.match(r'^##\s*7\.', l)), None)
    if start is None:
        sys.exit('execute.md: no §7 header found (expected a line starting with "## 7.")')
    waves, i = [], start
    while i < len(lines):
        m = re.match(r'^### (?:Ola|Wave) ([A-Z][A-Za-z0-9-]*)\s*(.*)$', lines[i])
        if not m:
            i += 1
            continue
        wid, rest = m.group(1), m.group(2).strip()
        rest = rest[2:].strip() if rest.startswith('— ') else rest
        # title = everything before the first " — <glyph>" (or " (<glyph>"); status = from the glyph on.
        cut = re.search(r'\s—\s(?=[✅⛔⏸🔄☐])|\s\((?=[✅⛔⏸🔄☐])', rest)
        if GLYPH.match(rest):
            # the header starts straight into the status (`### Wave W2 — 🔄 IN PROGRESS (…)`): no title of its own.
            title, status = wid, rest
        elif cut is None:
            title, status = rest, '☐'
        elif cut.start() == 0:
            title, status = wid, rest
        else:
            title, status = rest[:cut.start()].strip(), rest[cut.end():].strip()
        # title in parens (`### Wave WX (title) — 🔄 …`) → drop the parens themselves.
        if title.startswith('(') and title.endswith(')'):
            title = title[1:-1]
        # the prompts: every fence up to the next `### ` (a header with NO prompt of its own must not
        # swallow the following header's fence), pairing each with the `## Entrega|Delivery …` heading
        # above it; any other `## ` (a later `## Notas`, the next section) ends the wave. The first prompt
        # fence may be bare (legacy), later ones must be ```text; every other fence (```bash, a bare one after
        # the first prompt, 4+ backticks) is skipped opener-to-closer, so its closing ``` never opens a prompt
        # and a `## ` / `### ` line inside it never ends the wave.
        bodies, heading, j = [], None, i + 1
        while j < len(lines) and not lines[j].startswith('### '):
            line = lines[j]
            fence = re.match(r'^(`{3,})(.*)$', line)
            if line.startswith('## '):
                if not re.match(r'^##\s+(?:Entrega|Delivery)\b', line):
                    break
                heading = line[2:].strip()
            elif fence and len(fence.group(1)) == 3 and (fence.group(2).strip() == 'text' or
                                                          (not bodies and not fence.group(2).strip())):
                k = j + 1
                while k < len(lines) and lines[k].strip() != '```':
                    k += 1
                text = '\n'.join(lines[j + 1:k])
                if text:
                    bodies.append({'heading': heading, 'text': text})
                j = k
            elif fence:
                closer = re.compile(r'^`{%d,}\s*$' % len(fence.group(1)))
                j += 1
                while j < len(lines) and not closer.match(lines[j].strip()):
                    j += 1
            j += 1
        waves.append({'id': wid, 'title': title, 'status': status, 'bodies': bodies, 'line': i + 1})
        i = j
    return waves


def glyph(status):
    # The status's LEADING glyph wins (a 🔄 wave with "Phase 1 ✅" inside stays 🔄, like the wave map);
    # if the status doesn't start with a glyph, fall back to precedence ✅ > ⛔ > ⏸ > 🔄 over the full text.
    m = re.match(r'\s*(✅|⛔|⏸|🔄|☐)', status)
    if m:
        return m.group(1)
    for g in ('✅', '⛔', '⏸', '🔄'):
        if g in status:
            return g
    return '☐'


def badge_class(status):
    s = glyph(status)
    if s == '✅':
        return 'ok'
    if s == '⛔':
        return 'blocked'
    if '⚠' in status:
        return 'gate'
    if s in ('⏸', '🔄'):
        return 'blocked'
    return 'pending'


def nav_mark(status):
    s = glyph(status)
    return {'✅': ' ✅', '⛔': ' ⛔', '⏸': ' ⏸', '🔄': ' ★'}.get(s, '')


def short_status(status):
    """The badge text: the status up to the first parenthesis or 160 chars. The `**…**` emphasis is left
    for md_inline (the one place that turns it into <strong>) — converting it here too would be escaped."""
    s = status.split('(')[0].strip() if len(status) > 160 else status
    s = s.replace('`', '')
    return s[:220]


def md_inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    return s


def wave_map_row(brain, wid):
    """The task/status column of task.md's wave-map row for this wave (what's actually left).
    Optional: returns '' if task.md doesn't exist or has no row for this wave."""
    try:
        t = (brain / 'task.md').read_text()
    except OSError:
        return ''
    m = re.search(r'^\|\s*[^|]*\|\s*\*\*' + re.escape(wid) + r'\*\*\s*\|\s*(.*?)\s*\|', t, re.M)
    return m.group(1).strip() if m else ''


def wave_map_glyph(brain, wid):
    """The leading status glyph of task.md's wave-map row for this wave: its first cell, else the cell
    after the id. None if task.md or the row or a glyph is missing."""
    try:
        t = (brain / 'task.md').read_text()
    except OSError:
        return None
    m = re.search(r'^\|\s*([^|]*?)\s*\|\s*\*\*' + re.escape(wid) + r'\*\*\s*\|', t, re.M)
    for cell in ((m.group(1) if m else ''), wave_map_row(brain, wid)):
        g = GLYPH.match(cell)
        if g:
            return g.group(1)
    return None


def is_closed(brain, w):
    """True for a ✅ wave: its §7 header glyph, or — when the header carries no status of its own
    (the bare ☐ parse_s7 assigns) — the task.md wave-map glyph. An explicit status in the header wins."""
    if w['status'] != '☐':
        return glyph(w['status']) == '✅'
    return wave_map_glyph(brain, w['id']) == '✅'


def hand_titles(html_text):
    """Fallback titles: whatever <h2> a wave's card already carries in the HTML being patched,
    keyed by its UPPERCASED id (look it up with `wid.upper()`: card ids are lowercase, wave ids may
    carry a lowercase suffix like `W2a`). Last resort, used only for headers with no title of
    their own and no prompts-titles.json entry."""
    out = {}
    for m in re.finditer(r'<section class="card" id="([^"]+)">.*?<h2>(.*?)</h2>', html_text, re.S):
        out[m.group(1).upper()] = re.sub(r'<[^>]+>', '', m.group(2)).strip()
    return out


def load_titles(path):
    """Optional {"<ID>": "<title>"} map for headers with no title of their own. Missing file → {}."""
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def render_prompts(wid, bodies, L):
    """The prompt part of one card: (header copy button, markup after the header). The first
    headingless prompt keeps the header button and the bare `pre-<wid>` id; every other delivery
    gets its own `<h3>` + button + `pre-<wid>-N` (N = its 1-based position)."""
    btn, parts = '', []
    for n, b in enumerate(bodies, 1):
        lead = n == 1 and not b['heading']
        pre_id = f'pre-{wid}' if lead else f'pre-{wid}-{n}'
        if lead:
            btn = f'<button class="copy" data-target="{pre_id}">{L["copy_btn"]}</button>'
        else:
            h = md_inline(b['heading'] or f'{L["delivery"]} {n}')
            parts.append(f'<header class="card-h"><div><h3>{h}</h3></div>\n'
                         f'<button class="copy" data-target="{pre_id}">{L["copy_btn"]}</button></header>\n')
        parts.append(f'<pre id="{pre_id}"><code>{html.escape(b["text"], quote=False)}</code></pre>\n')
    return btn, ''.join(parts)


def build(brain, allow, lang, titles_path, html_text, closed='summary'):
    """Compute the patched HTML plus the data used for the console summary. `closed` is 'summary'
    (✅ waves render without their prompt) or 'full' (every prompt in full); a collapsed wave
    gets `collapsed: True` in its dict."""
    exec_text = (brain / 'execute.md').read_text()
    waves = {w['id']: w for w in parse_s7(exec_text)}
    hand = hand_titles(html_text)
    titles = load_titles(titles_path)
    for wid, tt in titles.items():
        if wid in waves:
            waves[wid]['title'] = tt
    for wid, w in waves.items():
        if w['title'] == wid and wid.upper() in hand:
            w['title'] = hand[wid.upper()]
    missing = [a for a in allow if a not in waves]
    if missing:
        sys.exit(f'missing from §7: {missing}')

    L = LANG[lang]
    cards, nav_links = [], []
    for a in allow:
        w = waves[a]
        wid = a.lower()
        resolved_closed = closed == 'summary' and is_closed(brain, w)
        w['collapsed'] = bool(w['bodies']) and resolved_closed
        btn, prompts = render_prompts(wid, [] if w['collapsed'] else w['bodies'], L)
        # a header with no status of its own that the task.md wave map closed: badge and nav show the resolved ✅
        # (with or without a prompt; only a wave that has one is collapsed)
        shown = '✅' if resolved_closed and w['status'] == '☐' else w['status']
        nav_links.append(f'<a class="nav-a" href="#{wid}">{a}{nav_mark(shown)}</a>\n')
        cards.append(
            f'<section class="card" id="{wid}">\n'
            f'<header class="card-h"><div><span class="tid">{a}</span> '
            f'<span class="badge {badge_class(shown)}">{md_inline(short_status(shown))}</span>\n'
            f'<h2>{md_inline(w["title"])}</h2></div>\n'
            + btn
            + '</header>\n'
            + (prompts if prompts else
               f'<p class="muted">{L["closed"] if w["collapsed"] else L["no_prompt"]}</p>\n'
               + (f'<p><strong>{L["real_status"]}</strong> {md_inline(wave_map_row(brain, a))}</p>\n'
                  if wave_map_row(brain, a) else '')
               + f'<p class="muted">{L["detail"]}</p>\n')
            + '</section>\n'
        )
    nav = ''.join(nav_links)
    t = html_text
    a0 = t.find('<a class="nav-a"')
    a1 = t.rfind('</a>', 0, t.find('<button class="btn" id="theme"')) + 4
    t = t[:a0] + nav.rstrip('\n') + t[a1:]
    c0 = t.find('<section class="card"')
    c1 = t.rfind('</section>', 0, t.find('</main>')) + len('</section>')
    t = t[:c0] + ''.join(cards).rstrip('\n') + t[c1:]
    return t, waves, nav, cards


def main():
    ap = argparse.ArgumentParser(
        description='Regenerate prompts.html nav + cards from execute.md §7 (one status per wave, no drift).')
    ap.add_argument('wave_ids', help='comma-separated wave ids, in the order the nav should list them (e.g. W1,W2,WSEC-3)')
    ap.add_argument('out', help='path to the prompts.html to patch (or to create first, with --init)')
    ap.add_argument('--brain', required=True, type=pathlib.Path,
                     help='directory holding execute.md (and optionally task.md, prompts-titles.json)')
    ap.add_argument('--lang', choices=['es', 'en'], default='es',
                     help='language for the strings this script writes into each card (default: es)')
    ap.add_argument('--project',
                     help='project name substituted for {{PROJECT_NAME}} when --init materializes the shell '
                          '(default: the brain directory\'s parent directory name)')
    ap.add_argument('--titles', type=pathlib.Path, default=None,
                     help='path to a {"<ID>": "<title>"} JSON map for headers with no title of their own '
                          '(default: <brain>/prompts-titles.json)')
    ap.add_argument('--closed', choices=['summary', 'full'], default='summary',
                     help='how ✅ waves render: summary (default) = title, badge, short status and a one-line '
                          '"closed wave" note, no <pre> and no copy button; full = every prompt in full. '
                          'Pending, in-progress and blocked waves always render in full')
    ap.add_argument('--init', action='store_true',
                     help='if <out> does not exist, create it from prompts-html.tmpl (next to this script) before '
                          'patching; exit 2 if that template is missing. With --check it never creates <out>')
    ap.add_argument('--check', action='store_true',
                     help='exit 1 if the regenerated HTML would differ from <out> (or <out> is missing); '
                          'print the differing wave ids and write nothing')
    args = ap.parse_args()

    allow = args.wave_ids.split(',')
    out = pathlib.Path(args.out)
    brain = args.brain
    titles_path = args.titles if args.titles is not None else brain / 'prompts-titles.json'

    if not (brain / 'execute.md').exists():
        sys.exit(f'{brain}/execute.md not found')

    would_init = False
    if args.init and not out.exists():
        tmpl_path = pathlib.Path(__file__).resolve().parent / 'prompts-html.tmpl'
        if not tmpl_path.is_file():
            print(f'--init: {tmpl_path} not found (prompts-html.tmpl must sit next to this script); nothing written',
                  file=sys.stderr)
            sys.exit(2)
        project = args.project or brain.resolve().parent.name
        shell = tmpl_path.read_text(encoding='utf-8').replace('{{PROJECT_NAME}}', project)
        if args.check:
            would_init = True
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(shell, encoding='utf-8')
            print(f'  --init: materialized {out} from {tmpl_path.name} (project={project})')

    if would_init:
        html_text = shell
    elif not out.exists():
        sys.exit(f'{out} does not exist (pass --init to create it from prompts-html.tmpl)')
    else:
        html_text = out.read_text(encoding='utf-8', errors='replace')
    new_text, waves, nav, cards = build(brain, allow, args.lang, titles_path, html_text, args.closed)

    if args.check:
        if would_init:
            print(f'  --check: {out} does not exist ({tmpl_path.name} would be materialized by --init); nothing written')
            sys.exit(1)
        if new_text == html_text:
            print(f'  --check: {out} is up to date ({len(allow)} waves)')
            return
        diffing = []
        for a in allow:
            wid = a.lower()
            pat = rf'<section class="card" id="{re.escape(wid)}">.*?</section>'
            old_card = re.search(pat, html_text, re.S)
            new_card = re.search(pat, new_text, re.S)
            if (old_card.group(0) if old_card else None) != (new_card.group(0) if new_card else None):
                diffing.append(a)
        print(f'  --check: {out} is STALE, {len(diffing)}/{len(allow)} waves differ: {diffing}')
        sys.exit(1)

    out.write_text(new_text, encoding='utf-8')
    print(f'  waves: {len(allow)} · nav: {nav.count("nav-a")} · cards: {"".join(cards).count("<section")} '
          f'· {len(new_text.encode("utf-8")) // 1024} KiB → {out}')
    for a in allow:
        w = waves[a]
        print(f'    {a:11} {glyph(w["status"])}  {badge_class(w["status"]):8} {w["title"][:60]}')
    collapsed = [a for a in allow if waves[a].get('collapsed')]
    if collapsed:
        print(f'  closed waves rendered as summaries ({len(collapsed)}): {",".join(collapsed)} '
              f'(--closed full keeps their prompts)')


if __name__ == '__main__':
    main()
