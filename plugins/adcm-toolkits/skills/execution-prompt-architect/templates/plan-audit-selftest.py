#!/usr/bin/env python3
"""plan-audit-selftest - behavioural tests for plan_audit.py (stdlib only).

Usage: python3 plan-audit-selftest.py [--script PATH] [--only SUBSTR] [--mutation]

One temp brain per case (task.md wave map, detailed-plan.md, execute.md, qa/plan-audit.md); the script runs
as a subprocess with a clean env. Prints `PASS <case>` / `FAIL <case>: why`, then `N/N passed`; exit 1 on any
failure. --mutation copies the script, neutralises ONE line marked `# MUTATION-KEY: <name>`, re-runs the
suite against the mutant and requires it to FAIL (`KILLED <name>`); exit 1 if a mutant survives.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PASS_LINE = 'PLAN-AUDIT: PASS · contradictions 0 · open 0\n'
MUTANTS = {
    'verdict': ("!= 'PASS'", "== 'NEVER'"),
    'open': ('> 0', '> 10 ** 9'),
    'fingerprint': ('!= fps[w]', '== None'),
}

TASK = """# Acme — Task tracker

## Wave map

| Status | Wave | Tasks | Gate | Depends on |
|---|---|---|---|---|
| ☐ | **W1** | T-W1-1 | — | — |
| ☐ | **W2** | T-W2-1 | ⚠ | W1 |
| ☐ | **W10** | T-W10-1 | — | W2 |
| ☐ | **W3** | T-W3-1 | — | W2 |

## Logbook
"""
PLAN = """# Acme — Detailed plan

## Wave W1 — Intake
### ☐ T-W1-1 — Build intake
- [ ] step one
- [ ] step two

## Wave W2 — Export ⚠GATE
### ☐ T-W2-1 — Build export
- [ ] export rows

## Wave W10 — Reports
### ☐ T-W10-1 — Build reports
- [ ] report rows
"""
EXEC = """# Acme — Execution protocol

## 6. Attack checklists

### W2 — ⚠gate
- try to export a deleted row

## 7. Wave prompts

### Wave W1 — Intake — ☐ pending

```text
# GOAL — Wave W1: intake
## Notes
do the intake
```

### W2 · a — Export — ☐ pending

```text
export prompt
```
"""


class Brain:
    def __init__(self, script, root):
        self.script, self.root = script, root
        self.env = {'PATH': os.environ.get('PATH', ''), 'PYTHONDONTWRITEBYTECODE': '1', 'HOME': root,
                    'PYTHONIOENCODING': 'utf-8'}
        for rel, body in (('task.md', TASK), ('detailed-plan.md', PLAN), ('execute.md', EXEC)):
            self.put(rel, body)

    def p(self, rel):
        return os.path.join(self.root, *rel.split('/'))

    def put(self, rel, body):
        os.makedirs(os.path.dirname(self.p(rel)), exist_ok=True)
        with open(self.p(rel), 'w', encoding='utf-8') as fh:
            fh.write(body)

    def get(self, rel):
        with open(self.p(rel), encoding='utf-8') as fh:
            return fh.read()

    def sub(self, rel, old, new):
        s = self.get(rel)
        assert old in s, old
        self.put(rel, s.replace(old, new, 1))

    def report(self, first=PASS_LINE, body='| id | A | B |\n'):
        self.put('qa/plan-audit.md', first + body)

    def run(self, *args, brain=True):
        cmd = [sys.executable, self.script] + (['--brain', self.root] if brain else []) + list(args)
        r = subprocess.run(cmd, env=self.env, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def sealed(self):
        self.report()
        rc, out = self.run('--seal')
        assert rc == 0, out


def eq(got, want, what):
    if got != want:
        raise AssertionError('%s: got %r, want %r' % (what, got, want))


def has(text, needle):
    if needle not in text:
        raise AssertionError('missing %r in %r' % (needle, text[:200]))


def c_missing_report(b):
    rc, out = b.run('--check')
    eq(rc, 1, 'exit')
    has(out, 'no report')


def c_fail_verdict(b):
    b.report('PLAN-AUDIT: FAIL · contradictions 2 · open 0\n')
    rc, out = b.run('--check')
    eq(rc, 1, 'exit')
    has(out, 'FAIL')
    rc, out = b.run('--seal')
    eq(rc, 1, 'seal refuses FAIL')


def c_open_gt_zero(b):
    b.report('PLAN-AUDIT: PASS · contradictions 1 · open 1\n')
    rc, out = b.run('--check')
    eq(rc, 1, 'exit')
    has(out, 'open')
    eq(b.run('--seal')[0], 1, 'seal refuses open > 0')


def c_malformed_first_line(b):
    b.report('Some intro\n' + PASS_LINE)
    eq(b.run('--check')[0], 1, 'verdict must be the FIRST line')


def c_unsealed(b):
    b.report()
    rc, out = b.run('--check')
    eq(rc, 1, 'exit')
    has(out, 'not sealed')


def c_sealed_ok(b):
    b.sealed()
    rc, out = b.run('--check')
    eq(rc, 0, 'exit ' + out)
    s = b.get('qa/plan-audit.md')
    has(s, '<!-- plan-audit:seal:start -->')
    eq(len(re.findall(r'^\| W\d+ \|', s, re.M)), 4, 'one row per wave')


def c_tick_only_ok(b):
    b.sealed()
    b.sub('detailed-plan.md', '- [ ] step one', '- [x] step one')
    b.sub('detailed-plan.md', '### ☐ T-W1-1', '### ✅ T-W1-1')
    eq(b.run('--check')[0], 0, 'tick + glyph')


def c_status_flip_and_date_ok(b):
    b.sealed()
    b.sub('execute.md', '### Wave W1 — Intake — ☐ pending', '### Wave W1 — Intake — ✅ DONE (2026-11-14)')
    b.sub('execute.md', '### W2 · a — Export — ☐ pending', '### W2 · a — Export — 🔄 IN PROGRESS (2026-11-15T10:00Z)  ')
    rc, out = b.run('--check')
    eq(rc, 0, 'header status flip ' + out)


def c_text_change_one_wave(b):
    b.sealed()
    b.sub('detailed-plan.md', '- [ ] export rows', '- [ ] export rows and purge')
    rc, out = b.run('--check', '--json')
    eq(rc, 2, 'exit')
    eq(json.loads(out)['stale_waves'], ['W2'], 'only W2 is stale')
    eq(b.run('--check', '--wave', 'W1')[0], 0, 'W1 unaffected')
    eq(b.run('--check', '--wave', 'W2')[0], 2, 'W2 stale')


def c_change_in_other_wave(b):
    b.sealed()
    b.sub('execute.md', 'do the intake', 'do the intake twice')
    rc, out = b.run('--check', '--json')
    eq(rc, 2, 'exit')
    eq(json.loads(out)['stale_waves'], ['W1'], 'fence content counts, only W1')
    eq(b.run('--check', '--wave', 'W10')[0], 0, 'W10 is not W1')


def c_wave_without_blocks(b):
    b.sealed()
    has(b.get('qa/plan-audit.md'), '| W3 | - | - |')
    eq(b.run('--check')[0], 0, 'empty wave is ok')
    b.put('detailed-plan.md', b.get('detailed-plan.md') + '\n## Wave W3 — Late\n- [ ] new\n')
    rc, out = b.run('--check', '--json')
    eq(rc, 2, 'blocks appeared')
    eq(json.loads(out)['stale_waves'], ['W3'], 'W3 only')


def c_prefix_id_not_confused(b):
    b.sealed()
    b.sub('detailed-plan.md', '- [ ] report rows', '- [ ] report rows plus')
    eq(json.loads(b.run('--check', '--json')[1])['stale_waves'], ['W10'], 'W10 change must not stale W1')


def c_seal_idempotent(b):
    b.sealed()
    first = b.get('qa/plan-audit.md')
    rc, out = b.run('--seal')
    eq(rc, 0, 'second seal')
    eq(b.get('qa/plan-audit.md'), first, 'byte-identical')
    b.sub('detailed-plan.md', '- [ ] export rows', '- [ ] export rows!')
    eq(b.run('--seal')[0], 0, 'reseal after change')
    eq(b.run('--check')[0], 0, 'fresh again')
    eq(b.get('qa/plan-audit.md').count('plan-audit:seal:start'), 1, 'one block')


def c_json_shape(b):
    rc, out = b.run('--check', '--json')
    d = json.loads(out)
    eq(sorted(d), ['reasons', 'sealed_at', 'stale_waves', 'started_waves', 'status'], 'keys')
    eq(d['status'], 'fail', 'status')
    b.sealed()
    d = json.loads(b.run('--check', '--json')[1])
    eq((d['status'], d['reasons'], d['stale_waves']), ('ok', [], []), 'ok shape')
    assert re.match(r'\d{4}-\d\d-\d\dT', d['sealed_at'] or ''), d


def c_module(b):
    b.report()
    os.makedirs(b.p('modules/m'))
    for f in ('task.md', 'detailed-plan.md', 'execute.md'):
        shutil.move(b.p(f), b.p('modules/m/' + f))
    shutil.move(b.p('qa'), b.p('modules/m/qa'))
    eq(b.run('--module', 'modules/m', '--seal')[0], 0, 'seal in module')
    eq(b.run('--module', 'modules/m', '--check')[0], 0, 'check in module')


def c_real_templates(b):
    for rel, tmpl in (('task.md', 'task.md.tmpl'), ('detailed-plan.md', 'detailed-plan.md.tmpl'),
                      ('execute.md', 'execute.md.tmpl')):
        with open(os.path.join(HERE, tmpl), encoding='utf-8') as fh:
            b.put(rel, fh.read())
    b.sealed()
    rows = re.findall(r'^\| (W\d+) \|', b.get('qa/plan-audit.md'), re.M)
    eq(rows, ['W1', 'W2'], 'waves of the template wave map')
    eq(b.run('--check')[0], 0, 'fresh seal on the real templates')
    b.sub('execute.md', '### W2 · b — Gate ☐', '### W2 · b — Gate ✅ DONE (2026-11-14)')
    b.sub('execute.md', '### W1 · a — Implement + DoD ☐', '### W1 · a — Implement + DoD 🔄 IN PROGRESS')
    rc, out = b.run('--check')
    eq(rc, 0, 'glyph flip on phase headings stays ok: ' + out)
    b.sub('execute.md', '### W2 · b — Gate ✅ DONE (2026-11-14)\n\n```text\n{{...}}', '### W2 · b — Gate ✅ DONE (2026-11-14)\n\n```text\nedited')
    rc, out = b.run('--check', '--json')
    eq(rc, 2, 'phase prompt edit is stale')
    eq(json.loads(out)['stale_waves'], ['W2'], 'only W2')


def handoff(b, wave, nn, phase, result):
    b.put('handoffs/%s-%s-%s.md' % (wave, nn, phase),
          '# H\n\n- **Wave:** %s\n- **Phase closed:** %s\n- **Result:** %s\n' % (wave, phase, result))


def c_exempt_done_wave(b):
    b.sealed()
    b.sub('task.md', '| ☐ | **W1** |', '| ✅ | **W1** |')
    b.sub('detailed-plan.md', '- [ ] step one', '- [ ] step one changed')
    eq(b.run('--check')[0], 0, 'done wave edited')
    eq(b.run('--check', '--wave', 'W1')[0], 0, '--wave on a done wave')


def c_exempt_started_wave(b):
    b.sealed()
    handoff(b, 'W2', '01', 'a', 'done')
    b.sub('detailed-plan.md', '- [ ] export rows', '- [ ] export rows edited by doc-sync')
    rc, out = b.run('--check', '--json')
    eq(rc, 0, 'started wave edited ' + out)
    eq(json.loads(out)['started_waves'], ['W2'], 'started_waves')
    eq(b.run('--check', '--wave', 'W2')[0], 0, '--wave on a started wave')
    handoff(b, 'W10', '01', 'a', 'partial')
    eq(json.loads(b.run('--check', '--json')[1])['started_waves'], ['W10', 'W2'], 'partial counts')


def c_failed_phase_a_not_started(b):
    b.sealed()
    handoff(b, 'W2', '01', 'a', 'fail')
    b.sub('detailed-plan.md', '- [ ] export rows', '- [ ] export rows edited')
    rc, out = b.run('--check', '--json')
    eq(rc, 2, 'failed phase a is not started')
    eq(json.loads(out)['stale_waves'], ['W2'], 'W2 stale')
    handoff(b, 'W2', '02', 'b', 'fail')
    eq(b.run('--check')[0], 0, 'a closed gate phase counts as started')


def c_not_started_later_wave_stale(b):
    b.sealed()
    handoff(b, 'W1', '01', 'd', 'done')
    b.sub('detailed-plan.md', '- [ ] report rows', '- [ ] report rows edited')
    rc, out = b.run('--check', '--json')
    eq(rc, 2, 'later wave edited')
    d = json.loads(out)
    eq((d['stale_waves'], d['started_waves']), (['W10'], ['W1']), 'only the not-started wave')
    b.report()
    eq(b.run('--check')[0], 1, 'unsealed still blocks started waves')


def c_usage_64(b):
    eq(b.run(brain=False, *['--check'])[0], 64, 'no --brain')
    eq(b.run('--seal', '--check')[0], 64, 'both modes')
    eq(b.run()[0], 64, 'no mode')
    eq(b.run('--check', '--wave', 'W99')[0], 64, 'unknown wave')
    eq(b.run('--check', '--module', '../x')[0], 64, 'dotdot module')
    eq(b.run('--seal', '--wave', 'W1')[0], 64, '--wave with --seal')
    eq(subprocess.run([sys.executable, b.script, '--brain', b.p('nope'), '--check'], capture_output=True,
                      env=b.env).returncode, 64, 'missing dir')


CASES = [(n[2:], f) for n, f in sorted(globals().items(), key=lambda kv: kv[0]) if n.startswith('c_')]
ORDER = ['missing_report', 'fail_verdict', 'open_gt_zero', 'malformed_first_line', 'unsealed', 'sealed_ok',
         'tick_only_ok', 'status_flip_and_date_ok', 'text_change_one_wave', 'change_in_other_wave',
         'wave_without_blocks', 'prefix_id_not_confused', 'seal_idempotent', 'json_shape', 'module', 'real_templates', 'exempt_done_wave', 'exempt_started_wave',
         'failed_phase_a_not_started', 'not_started_later_wave_stale', 'usage_64']
CASES.sort(key=lambda c: ORDER.index(c[0]))


def run_suite(script, only=None, quiet=False):
    ok = total = 0
    for name, fn in CASES:
        if only and only not in name:
            continue
        total += 1
        root = os.path.realpath(tempfile.mkdtemp(prefix='plan-audit-selftest-'))
        try:
            fn(Brain(script, root))
            ok += 1
            if not quiet:
                print('PASS ' + name)
        except Exception as exc:  # a failing assertion or a crashing script is a failed case
            if not quiet:
                print('FAIL %s: %s' % (name, str(exc)[:200]))
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return ok, total


def mutation(script):
    with open(script, encoding='utf-8') as fh:
        lines = fh.read().split('\n')
    survived = 0
    for key, (old, new) in MUTANTS.items():
        idx = [i for i, l in enumerate(lines) if '# MUTATION-KEY: ' + key in l]
        if len(idx) != 1 or old not in lines[idx[0]]:
            print('FAIL mutant %s: marker line missing or %r not on it' % (key, old))
            survived += 1
            continue
        mut = list(lines)
        mut[idx[0]] = mut[idx[0]].replace(old, new, 1)
        tmp = tempfile.mkdtemp(prefix='plan-audit-mutant-')
        path = os.path.join(tmp, 'plan_audit.py')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(mut))
        ok, total = run_suite(path, quiet=True)
        shutil.rmtree(tmp, ignore_errors=True)
        if ok == total:
            print('SURVIVED %s' % key)
            survived += 1
        else:
            print('KILLED %s (%d/%d cases failed)' % (key, total - ok, total))
    print('%d/%d mutants killed' % (len(MUTANTS) - survived, len(MUTANTS)))
    return 1 if survived else 0


def main():
    ap = argparse.ArgumentParser(description='Behavioural tests for plan_audit.py')
    ap.add_argument('--script', default=os.path.join(HERE, 'plan_audit.py'))
    ap.add_argument('--only')
    ap.add_argument('--mutation', action='store_true')
    args = ap.parse_args()
    script = os.path.abspath(args.script)
    if args.mutation:
        return mutation(script)
    ok, total = run_suite(script, args.only)
    print('%d/%d passed' % (ok, total))
    return 0 if ok == total and total else 1


if __name__ == '__main__':
    sys.exit(main())
