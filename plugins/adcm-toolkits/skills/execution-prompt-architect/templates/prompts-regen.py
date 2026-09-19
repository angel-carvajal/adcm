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
A header with no title of its own (it starts straight into the status glyph, e.g.
`### Wave W2 — 🔄 IN PROGRESS (...)`) needs its title supplied some other way —
in precedence order: an optional `prompts-titles.json` ({"<ID>": "<title>"}, see
`--titles`), then whatever `<h2>` the wave's card already carries in the HTML
being patched, then finally the wave id itself as a last resort.

Status precedence (one glyph per wave, taken from the START of the header's
status text, else the first glyph found anywhere in it): ✅ > ⛔ > ⏸ > 🔄 > ☐.

Generic port of a venture-specific internal script (same name); the fixes made
during the port: an explicit --brain (nothing hardcoded), a bilingual §7 anchor,
optional prompts-titles.json instead of a hardcoded dict, an ES/EN LANG dict for
the generated UI strings, a shippable HTML shell + --init, and --check.

Usage:
  python3 prompts-regen.py <comma-list-of-wave-ids> <out.html> --brain <dir>
      [--lang es|en] [--project "<name>"] [--titles <path>] [--init] [--check]
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
    },
    'en': {
        'copy_btn': 'Copy prompt',
        'no_prompt': 'No standalone prompt in §7: wave executed under a previous flow.',
        'real_status': 'Real status (task.md wave map):',
        'detail': 'Detail in the <code>task.md</code> logbook and the Pending tab of plans.html.',
    },
}


def parse_s7(exec_text):
    """Parse execute.md §7 into a list of {id, title, status, body, line} dicts,
    one per `### Ola|Wave <ID> ...` header, in document order."""
    lines = exec_text.split('\n')
    start = next((i for i, l in enumerate(lines) if re.match(r'^##\s*7\.', l)), None)
    if start is None:
        sys.exit('execute.md: no §7 header found (expected a line starting with "## 7.")')
    waves, i = [], start
    while i < len(lines):
        m = re.match(r'^### (?:Ola|Wave) ([A-Z][A-Z0-9-]*)\s*(.*)$', lines[i])
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
        j = i + 1
        # the prompt's fence — stop at the next `### `: a header with NO prompt of its own must not
        # swallow the following header's fence and inherit a prompt that isn't its.
        while j < len(lines) and not re.match(r'^```(text)?\s*$', lines[j]) and not lines[j].startswith('### '):
            j += 1
        if j >= len(lines) or lines[j].startswith('### '):
            waves.append({'id': wid, 'title': title, 'status': status, 'body': '', 'line': i + 1})
            i = j
            continue
        k = j + 1
        while k < len(lines) and lines[k].strip() != '```':
            k += 1
        body = '\n'.join(lines[j + 1:k]) if j < len(lines) else ''
        waves.append({'id': wid, 'title': title, 'status': status, 'body': body, 'line': i + 1})
        i = k + 1
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
    """The badge text: the status up to the first parenthesis or 160 chars, no markdown emphasis."""
    s = status.split('(')[0].strip() if len(status) > 160 else status
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
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


def hand_titles(html_text):
    """Fallback titles: whatever <h2> a wave's card already carries in the HTML being patched,
    keyed by its uppercased id. Last resort, used only for headers with no title of their own
    and no prompts-titles.json entry."""
    out = {}
    for m in re.finditer(r'<section class="card" id="([^"]+)">.*?<h2>(.*?)</h2>', html_text, re.S):
        out[m.group(1).upper()] = re.sub(r'<[^>]+>', '', m.group(2)).strip()
    return out


def load_titles(path):
    """Optional {"<ID>": "<title>"} map for headers with no title of their own. Missing file → {}."""
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def build(brain, allow, lang, titles_path, html_text):
    """Compute the patched HTML plus the data used for the console summary."""
    exec_text = (brain / 'execute.md').read_text()
    waves = {w['id']: w for w in parse_s7(exec_text)}
    hand = hand_titles(html_text)
    titles = load_titles(titles_path)
    for wid, tt in titles.items():
        if wid in waves:
            waves[wid]['title'] = tt
    for wid, w in waves.items():
        if w['title'] == wid and wid in hand:
            w['title'] = hand[wid]
    missing = [a for a in allow if a not in waves]
    if missing:
        sys.exit(f'missing from §7: {missing}')

    L = LANG[lang]
    nav = ''.join(f'<a class="nav-a" href="#{a.lower()}">{a}{nav_mark(waves[a]["status"])}</a>\n' for a in allow)
    cards = []
    for a in allow:
        w = waves[a]
        wid = a.lower()
        cards.append(
            f'<section class="card" id="{wid}">\n'
            f'<header class="card-h"><div><span class="tid">{a}</span> '
            f'<span class="badge {badge_class(w["status"])}">{md_inline(short_status(w["status"]))}</span>\n'
            f'<h2>{md_inline(w["title"])}</h2></div>\n'
            + (f'<button class="copy" data-target="pre-{wid}">{L["copy_btn"]}</button>' if w['body'] else '')
            + '</header>\n'
            + (f'<pre id="pre-{wid}"><code>{html.escape(w["body"], quote=False)}</code></pre>\n' if w['body'] else
               f'<p class="muted">{L["no_prompt"]}</p>\n'
               + (f'<p><strong>{L["real_status"]}</strong> {md_inline(wave_map_row(brain, a))}</p>\n'
                  if wave_map_row(brain, a) else '')
               + f'<p class="muted">{L["detail"]}</p>\n')
            + '</section>\n'
        )
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
    ap.add_argument('--init', action='store_true',
                     help='if <out> does not exist, create it from prompts-html.tmpl (next to this script) before patching')
    ap.add_argument('--check', action='store_true',
                     help='exit 1 if the regenerated HTML would differ from <out>; print the differing wave ids and write nothing')
    args = ap.parse_args()

    allow = args.wave_ids.split(',')
    out = pathlib.Path(args.out)
    brain = args.brain
    titles_path = args.titles if args.titles is not None else brain / 'prompts-titles.json'

    if not (brain / 'execute.md').exists():
        sys.exit(f'{brain}/execute.md not found')

    if args.init and not out.exists():
        tmpl_path = pathlib.Path(__file__).resolve().parent / 'prompts-html.tmpl'
        project = args.project or brain.resolve().parent.name
        shell = tmpl_path.read_text(encoding='utf-8').replace('{{PROJECT_NAME}}', project)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(shell, encoding='utf-8')
        print(f'  --init: materialized {out} from {tmpl_path.name} (project={project})')

    if not out.exists():
        sys.exit(f'{out} does not exist (pass --init to create it from prompts-html.tmpl)')

    html_text = out.read_text(encoding='utf-8', errors='replace')
    new_text, waves, nav, cards = build(brain, allow, args.lang, titles_path, html_text)

    if args.check:
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
          f'· {len(new_text) // 1024} KB → {out}')
    for a in allow:
        w = waves[a]
        print(f'    {a:11} {glyph(w["status"])}  {badge_class(w["status"]):8} {w["title"][:60]}')


if __name__ == '__main__':
    main()
