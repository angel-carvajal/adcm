#!/usr/bin/env python3
"""spend_report.py - token spend of one Claude Code session in at most 10 lines.

Reads the session transcripts (main thread + sub-agents + workflow agents) and prints a handoff line
(`Spend: ...`), one row per model family and one `ALARM <code>: <why>` line per alarm. Read-only,
stdlib only, stdout only, Python >= 3.8.

Usage
  spend_report.py [--session ID] [--project PATH|SLUG] [--until ISO8601Z] [--phase plan|a|b|c|d|e] [--selftest]
  --session ID   session id (a unique prefix is fine); default = newest main transcript of the project
  --project P    a projects folder, a project path or its slug; default = the slug of the current directory
  --until TS     drop every record after this UTC timestamp (string compare on the ISO value)
  --phase X      phase of the session; default = first `PHASE <letter>` / `fase <letter>` word of the first user message
  --selftest     synthetic fixtures in a temp dir; exit 0/1
Config dir: $CLAUDE_CONFIG_DIR or ~/.claude (transcripts live in <config>/projects/<slug>/).

Dedupe: streaming writes several lines per API response; usage is kept once per message.id (last line).
Context of a request = input + cache read + cache write tokens. Visible output = chars/4 of text and tool
input. Dollars use the PRICES table at the top (list prices, 5m and 1h cache writes priced apart).

Alarms (signal -> transcript field)
  effort-max         phases a-e only; main assistant `effort` == max, or an `ultra_effort_enter` attachment
  hidden-reasoning   > 70% of main output tokens not visible as text/tool input (usage.output_tokens vs content)
  status-turns       > 5 main turns started by a user message or task notification with no tool_use at all
  subagent-context   a sub-agent request context > 200k
  phase-c-fanout     phase c only; Workflow tool calls / workflow-agent transcripts / auditor agents (meta agentType)
"""
import argparse, collections, glob, json, os, re, sys, tempfile

FAMILIES = ("fable", "opus", "sonnet", "haiku")
# List prices, USD per million tokens, from the claude-api skill model table (cached 2026-11-03):
# (input, output, cache read, cache write 5m, cache write 1h). Writes are 1.25x / 2x the input price.
# Haiku's higher rate above a 100K prompt is not modelled. Update here when prices change.
PRICES = dict(fable=(8.0, 40.0, 0.20, 10.0, 16.0), opus=(4.0, 20.0, 0.20, 5.0, 8.0),
              sonnet=(2.0, 10.0, 0.10, 2.5, 4.0), haiku=(0.10, 0.50, 0.01, 0.125, 0.20))
CTX_LIMIT = 200000
HIDDEN_LIMIT = 0.70
STATUS_LIMIT = 5
MAX_LINES = 10


def jl(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def usage_of(m):
    u = m.get("usage") or {}
    cc = u.get("cache_creation") or {}
    w = u.get("cache_creation_input_tokens", 0) or 0
    w1 = cc.get("ephemeral_1h_input_tokens", 0) or 0
    w5 = cc.get("ephemeral_5m_input_tokens")
    if w5 is None:
        w5 = max(w - w1, 0)
    return dict(input=u.get("input_tokens", 0) or 0, output=u.get("output_tokens", 0) or 0,
                cache_read=u.get("cache_read_input_tokens", 0) or 0, cache_write=w, w5=w5, w1=w1)


def usd(fm, c):
    p = PRICES[fm]
    return (c["input"] * p[0] + c["output"] * p[1] + c["cache_read"] * p[2] + c["w5"] * p[3] + c["w1"] * p[4]) / 1e6


def money(x):
    return "$%.2f" % x


def family(model):
    m = (model or "").lower()
    return next((f for f in FAMILIES if f in m), None)


def fmt(n):
    if n >= 1e6:
        return "%.1fM" % (n / 1e6)
    if n >= 1e3:
        return "%.1fk" % (n / 1e3)
    return str(int(n))


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def find_project(arg):
    base = os.path.join(config_dir(), "projects")
    cands = []
    if arg:
        cands += [arg, os.path.join(base, arg), os.path.join(base, slug(os.path.abspath(os.path.expanduser(arg))))]
    else:
        cands.append(os.path.join(base, slug(os.getcwd())))
    for c in cands:
        c = os.path.expanduser(c)
        if os.path.isdir(c) and glob.glob(os.path.join(c, "*.jsonl")):
            return c
    return None


def find_session(proj, sid):
    files = glob.glob(os.path.join(proj, "*.jsonl"))
    if sid:
        files = [f for f in files if os.path.basename(f)[:-6].startswith(sid)]
        if len(files) != 1:
            return None
    return max(files, key=os.path.getmtime) if files else None


def discover(main_path):
    out = [dict(path=main_path, main=True, wf=False, atype="")]
    sdir = main_path[:-len(".jsonl")]
    for p in sorted(glob.glob(os.path.join(sdir, "**", "agent-*.jsonl"), recursive=True)):
        meta = {}
        try:
            with open(p[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            pass
        out.append(dict(path=p, main=False, wf=("%sworkflows%s" % (os.sep, os.sep)) in p,
                        atype=str(meta.get("agentType") or "")))
    return out


def plain_user_text(d):
    """Text of a user message typed/sent to the thread; '' for tool results and command wrappers."""
    c = (d.get("message") or {}).get("content")
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return ""
        c = "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(c, str):
        return ""
    head = c.lstrip()[:20]
    if head.startswith("<command-") or head.startswith("<local-command"):
        return ""
    return c


def load(f, until):
    """reqs: id -> dict; turns: [bool has_tool] per user/notification-started main turn; first user text; effort flags."""
    reqs = collections.OrderedDict()
    turns, cur = [], None
    first_text, effort_max, ultra = None, False, False
    wf_calls = 0
    seen = False  # any record at or before the cut
    for d in jl(f["path"]):
        ts, t = d.get("timestamp"), d.get("type")
        if until and ts and ts > until:
            continue
        if ts or not until:
            seen = True  # untimestamped records (api-request-blob) never place an agent before the cut
        if t == "assistant":
            m = d.get("message") or {}
            mid = m.get("id")
            if not mid:
                continue
            r = reqs.get(mid)
            if r is None:
                r = reqs[mid] = dict(model=m.get("model"), usage=None, blocks={}, tools=0)
            r["usage"] = usage_of(m)
            if d.get("effort") == "max" or d.get("perTurnEffort") == "max":
                effort_max = True
            for b in m.get("content") or []:
                bt = b.get("type")
                if bt == "tool_use":
                    if b.get("id") not in r["blocks"]:
                        r["blocks"][b.get("id")] = len(json.dumps(b.get("input", {})))
                        r["tools"] += 1
                        if b.get("name") == "Workflow":
                            wf_calls += 1
                        if cur is not None:
                            cur["tool"] = True
                elif bt == "text":
                    r["blocks"][("t", d.get("apiBlockIndex"), len(b.get("text", "")))] = len(b.get("text", ""))
            if cur is not None:
                cur["asst"] = True
        elif t == "user" and f["main"]:
            txt = plain_user_text(d)
            if txt:
                if first_text is None:
                    first_text = txt
                cur = dict(asst=False, tool=False)
                turns.append(cur)
        elif t == "attachment" and f["main"]:
            a = d.get("attachment") or {}
            if a.get("type") == "ultra_effort_enter":
                ultra = True
            elif a.get("type") == "queued_command" and "<task-notification>" in str(a.get("prompt") or ""):
                cur = dict(asst=False, tool=False)
                turns.append(cur)
    return dict(reqs=reqs, turns=turns, first_text=first_text, effort_max=effort_max or ultra, wf_calls=wf_calls, seen=seen)


def detect_phase(text):
    m = re.search(r"\b(?:phase|fase)\s+([a-e])\b", text or "", re.I)
    return m.group(1).lower() if m else None


def build(main_path, until, phase_arg):
    fam = collections.OrderedDict((f, dict(main=collections.Counter(), sub=collections.Counter())) for f in FAMILIES)
    main_models = collections.Counter()
    max_sub_ctx, big_subs = 0, 0
    n_wf_agents = n_auditors = 0
    main = None
    for f in discover(main_path):
        L = load(f, until)
        if f["main"]:
            main = L
        n_wf_agents += f["wf"] and L["seen"]
        n_auditors += "auditor" in f["atype"].lower() and L["seen"]
        for r in L["reqs"].values():
            fm, u = family(r["model"]), r["usage"]
            if not fm or not u:
                continue
            if f["main"]:
                main_models[r["model"]] += 1
            ctx = u["input"] + u["cache_read"] + u["cache_write"]
            if not f["main"]:
                max_sub_ctx = max(max_sub_ctx, ctx)
                big_subs += ctx > CTX_LIMIT
            fam[fm]["main" if f["main"] else "sub"].update(u)
    phase = phase_arg or detect_phase(main["first_text"])
    mreqs = list(main["reqs"].values())
    out_tok = sum(r["usage"]["output"] for r in mreqs if r["usage"])
    hidden = sum(max(r["usage"]["output"] - sum(r["blocks"].values()) // 4, 0) for r in mreqs if r["usage"])
    status = sum(1 for t in main["turns"] if t["asst"] and not t["tool"])
    alarms, na = [], []
    if phase in ("a", "b", "c", "d", "e") and main["effort_max"]:
        alarms.append(("effort-max", "main thread ran at max effort / multi-agent mode in phase %s" % phase))
    if out_tok:
        if hidden / out_tok > HIDDEN_LIMIT:
            alarms.append(("hidden-reasoning", "%d%% of main output (%s tok) is not visible text or tool input"
                           % (round(100.0 * hidden / out_tok), fmt(hidden))))
    else:
        na.append("hidden-reasoning")
    if status > STATUS_LIMIT:
        alarms.append(("status-turns", "%d main turns answered with no tool call" % status))
    if max_sub_ctx > CTX_LIMIT:
        alarms.append(("subagent-context", "%d sub-agent request(s) over 200k context (max %s)" % (big_subs, fmt(max_sub_ctx))))
    if phase == "c" and (main["wf_calls"] or n_wf_agents or n_auditors):
        alarms.append(("phase-c-fanout", "phase c used %d Workflow call(s), %d workflow agent(s), %d auditor agent(s)"
                       % (main["wf_calls"], n_wf_agents, n_auditors)))
    cost = dict(main=sum(usd(f, v["main"]) for f, v in fam.items()), sub=sum(usd(f, v["sub"]) for f, v in fam.items()))
    return dict(cost=cost, fam=fam, main_model=main_models.most_common(1)[0][0] if main_models else "n/a",
                phase=phase, alarms=alarms, na=na)


def render(sid, R):
    names = dict(fable="Fable", opus="Opus", sonnet="Sonnet", haiku="Haiku")
    rows = []
    for f, v in R["fam"].items():
        t = v["main"] + v["sub"]
        if not sum(t.values()):
            continue
        rows.append("%-6s ≈%s (main %s/sub %s) | in %s | out %s | cache r %s | cache w %s" % (
            names[f], money(usd(f, t)), money(usd(f, v["main"])), money(usd(f, v["sub"])),
            fmt(t["input"]), fmt(t["output"]), fmt(t["cache_read"]), fmt(t["cache_write"])))
    al = R["alarms"]
    c = R["cost"]
    head = "Spend: %s %s ≈%s (main %s/sub %s) phase %s alarms %d%s%s" % (
        sid[:8], R["main_model"].replace("claude-", ""), money(c["main"] + c["sub"]), money(c["main"]), money(c["sub"]), R["phase"] or "n/a", len(al),
        (" " + ",".join(a[0] for a in al)) if al else "",
        (" n/a:" + ",".join(R["na"])) if R["na"] else "")
    room = MAX_LINES - 1 - len(rows)
    lines = ["ALARM %s: %s" % a for a in al]
    if len(lines) > room:
        keep = max(room - 1, 0)
        lines = lines[:keep] + ["+%d more alarms" % (len(lines) - keep)]
    return [head[:200]] + rows + lines


def run(argv, out=None):
    ap = argparse.ArgumentParser(prog="spend_report.py", description="Token spend of one session in at most 10 lines.")
    ap.add_argument("--session")
    ap.add_argument("--project")
    ap.add_argument("--until")
    ap.add_argument("--phase", choices=["plan", "a", "b", "c", "d", "e"])
    ap.add_argument("--selftest", action="store_true")
    fixed, i = [], 0
    while i < len(argv):  # a slug starts with '-': join it to its flag so argparse keeps it as a value
        if argv[i] in ("--project", "--session", "--until") and i + 1 < len(argv):
            fixed.append("%s=%s" % (argv[i], argv[i + 1]))
            i += 1
        else:
            fixed.append(argv[i])
        i += 1
    a = ap.parse_args(fixed)
    if a.selftest:
        return selftest()
    proj = find_project(a.project)
    if not proj:
        print("spend_report: no project transcripts found", file=sys.stderr)
        return 2
    path = find_session(proj, a.session)
    if not path:
        print("spend_report: no matching session transcript", file=sys.stderr)
        return 2
    lines = render(os.path.basename(path)[:-6], build(path, a.until, a.phase))
    print("\n".join(lines))
    return 0


# ------------------------------------------------------------------ selftest
def _asst(ts, mid, model, out, content, effort=None, inp=10, cr=100, cw=50, idx=0):
    d = dict(type="assistant", timestamp=ts, apiBlockIndex=idx, message=dict(
        id=mid, model=model, content=content,
        usage=dict(input_tokens=inp, output_tokens=out, cache_read_input_tokens=cr, cache_creation_input_tokens=cw)))
    if effort:
        d["effort"] = effort
    return d


def _text(n):
    return [dict(type="text", text="x" * n)]


def _tool(i):
    return [dict(type="tool_use", id="tu%s" % i, name="Bash", input=dict(command="ls"))]


def _user(ts, s):
    return dict(type="user", timestamp=ts, message=dict(role="user", content=s))


def _write(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")


def selftest():
    import contextlib, io, shutil
    tmp = tempfile.mkdtemp(prefix="spend-report-selftest-")
    old = os.environ.get("CLAUDE_CONFIG_DIR")
    os.environ["CLAUDE_CONFIG_DIR"] = tmp
    res = []

    def check(name, ok, why=""):
        res.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" - " + why) if (why and not ok) else ""))

    def call(argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(argv)
        return rc, buf.getvalue().splitlines()

    def session(proj, sid, main_recs, subs=(), wfs=()):
        base = os.path.join(tmp, "projects", proj)
        _write(os.path.join(base, sid + ".jsonl"), main_recs)
        for i, (recs, atype) in enumerate(subs):
            p = os.path.join(base, sid, "subagents", "agent-s%d.jsonl" % i)
            _write(p, recs)
            _write(p[:-6] + ".meta.json", [dict(agentType=atype)])
        for i, recs in enumerate(wfs):
            _write(os.path.join(base, sid, "subagents", "workflows", "wf_%d" % i, "agent-w%d.jsonl" % i), recs)

    F, O, S = "claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5"
    try:
        # clean session: tool use everywhere, visible output, phase from the first message
        T = "2026-01-01T00:00:%02dZ"
        clean = [_user(T % 1, "PHASE b go"),
                 _asst(T % 2, "m1", F, 100, _tool(1) + _text(400)),
                 _asst(T % 2, "m1", F, 100, _text(400), idx=1),           # streaming duplicate of m1
                 dict(type="user", timestamp=T % 3, message=dict(content=[dict(type="tool_result", tool_use_id="tu1", content="ok")])),
                 _asst(T % 4, "m2", F, 100, _tool(2) + _text(400)),
                 _asst(T % 50, "m3", F, 5000, _text(10))]               # after the cut
        sub = [_asst(T % 5, "s1", O, 40, _text(160), cr=1000, cw=0), _asst(T % 6, "s2", S, 40, _text(160))]
        session("-fx-proj", "aaaaaaaa-1111", clean, subs=[(sub, "x:executor")], wfs=[[_asst(T % 7, "w1", S, 20, _text(80))]])
        rc, ln = call(["--project", "-fx-proj", "--session", "aaaaaaaa", "--until", T % 10])
        check("discovery+output shape", rc == 0 and ln[0].startswith("Spend: aaaaaaaa fable-5-2") and "phase b" in ln[0] and "alarms 0" in ln[0], str(ln[:1]))
        check("<=10 lines, head <=200 chars", len(ln) <= 10 and len(ln[0]) <= 200)
        fr = [l for l in ln if l.startswith("Fable")]
        check("dedupe + until cut", bool(fr) and "out 200 " in fr[0] and "in 20 " in fr[0], str(fr))
        orow = [l for l in ln if l.startswith("Opus")]
        srow = [l for l in ln if l.startswith("Sonnet")]
        check("sub-agent + workflow inclusion", bool(orow) and "out 40 " in orow[0] and bool(srow) and "out 60 " in srow[0], str(srow))
        check("price: fable main = 200 out, 20 in, 200 cr, 100 cw (5m)", "≈$0.01" in ln[0], ln[0])
        check("absent family prints nothing", not any(l.startswith("Haiku") for l in ln))
        check("no alarm when clean", not any(l.startswith("ALARM") for l in ln))
        rc, ln2 = call(["--project", "-fx-proj"])
        fr2 = [l for l in ln2 if l.startswith("Fable")]
        check("newest session without --until", rc == 0 and bool(fr2) and "out 5.2k" in fr2[0], str(fr2))
        # no ids / no project
        rc, _ = call(["--project", "-nope"])
        check("missing project exit 2", rc == 2)

        # every alarm: phase c, max effort, hidden, status turns, big sub, workflow + auditor
        bad = [_user(T % 1, "fase C: arreglos"), dict(type="attachment", timestamp=T % 1, attachment=dict(type="ultra_effort_enter"))]
        for i in range(7):
            bad += [_user(T % (2 + 2 * i), "status?"), _asst(T % (3 + 2 * i), "b%d" % i, F, 1000, _text(40), effort="max")]
        big = [dict(type="api-request-blob"), _asst(T % 30, "g1", O, 10, _text(40), cr=250000)]  # an untimestamped blob is not a record before the cut
        session("-fx-bad", "bbbbbbbb-2222", bad, subs=[(big, "x:auditor")])
        rc, ln = call(["--project", "-fx-bad"])
        codes = [l.split(":")[0][6:] for l in ln if l.startswith("ALARM")]
        for c in ("effort-max", "hidden-reasoning", "status-turns", "subagent-context", "phase-c-fanout"):
            check("alarm fires: " + c, c in codes, str(codes))
        check("alarms listed on head line + <=10 lines", "alarms 5" in ln[0] and len(ln) <= 10, str(len(ln)))
        rc, ln = call(["--project", "-fx-bad", "--until", T % 20])
        codes = [l.split(":")[0][6:] for l in ln if l.startswith("ALARM")]
        check("--until: an auditor with no record before the cut is not counted", "phase-c-fanout" not in codes, str(codes))
        # phase override and unknown phase
        rc, ln = call(["--project", "-fx-bad", "--phase", "plan"])
        codes = [l.split(":")[0][6:] for l in ln if l.startswith("ALARM")]
        check("plan phase skips effort-max and fanout", "effort-max" not in codes and "phase-c-fanout" not in codes and "hidden-reasoning" in codes, str(codes))
        rc, ln = call(["--project", "-fx-bad", "--phase", "d"])
        codes = [l.split(":")[0][6:] for l in ln if l.startswith("ALARM")]
        check("phase d: effort-max fires, fanout does not", "effort-max" in codes and "phase-c-fanout" not in codes, str(codes))
        # unknown phase
        quiet = [_user(T % 1, "just do things"), _asst(T % 2, "q1", F, 10, _tool(1) + _text(40), effort="max")]
        session("-fx-q", "cccccccc-3333", quiet)
        rc, ln = call(["--project", "-fx-q"])
        check("unknown phase prints phase n/a, no effort-max", "phase n/a" in ln[0] and "effort-max" not in ln[0], ln[0])
        # not firing at the limits: 5 status turns, hidden 70%, sub ctx 200k exactly
        ok = [_user(T % 1, "PHASE c")]
        for i in range(5):
            ok += [_user(T % (2 + 2 * i), "?"), _asst(T % (3 + 2 * i), "k%d" % i, F, 100, _text(280))]
        ok += [_asst(T % 20, "k9", F, 100, _tool(1) + _text(100))]
        session("-fx-ok", "dddddddd-4444", ok, subs=[([_asst(T % 5, "e1", S, 5, _text(20), inp=0, cr=150000, cw=50000)], "x:executor")])
        rc, ln = call(["--project", "-fx-ok"])
        check("limits are exclusive (5 turns, 200k, 70%)", not any(l.startswith("ALARM") for l in ln), str(ln))
        # alarm overflow folding
        R = dict(cost=dict(main=0, sub=0), fam=collections.OrderedDict((f, dict(main=collections.Counter(), sub=collections.Counter())) for f in FAMILIES),
                 main_model="m", phase="c", alarms=[("c%d" % i, "w") for i in range(12)], na=[])
        lines = render("zzzzzzzz", R)
        check("overflow folds into +N more", len(lines) == MAX_LINES and lines[-1].startswith("+") and "more" in lines[-1], str(lines[-1]))
    finally:
        if old is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = old
        shutil.rmtree(tmp, ignore_errors=True)
    print("%d/%d checks passed" % (sum(res), len(res)))
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
