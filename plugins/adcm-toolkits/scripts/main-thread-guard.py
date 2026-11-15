#!/usr/bin/env python3
"""main-thread-guard - keeps the main thread of a session orchestrating (stdlib only, Python 3.8+).

One entry point for SessionStart, UserPromptSubmit, PreCompact, PreToolUse and PostToolUse (hooks/hooks.json).
Always exits 0; any internal error fails open and appends one line to <state>/errors.log.

Main thread <=> the event has no `agent_id`. Sub-agent events only meet T0 (tamper) and M1 (memory index lines), plus
the handoff stamp on PostToolUse. Unattended sessions (CLAUDE_CODE_SESSION_ATTENDED=0, or unset with an `sdk*`
entrypoint) count and get notes but are denied only by T0. ADCM_GUARD_FORCE=1 forces attended.

PreToolUse rules, first match wins: T0 tamper (state dir, the running plugin, escape phrases laundered through
scheduling / messaging tools) · R1 lock at the 3rd compaction · R1b handoff gate at the 2nd · M1 memory index line
<= 150 · R6 status turn (3 calls) · R3 heavy reads · X1 no browser / Artifact · X2 edit cap · R2 budget
(Bash+Grep+Glob+LS 25, Read 8). Direct mode (`modo directo`, `sin tanto lío`; off with `modo orquestador`) switches off
R2, R3, R6, X1 and X2 only.

State: one JSON per session under $ADCM_GUARD_STATE_DIR, else $CLAUDE_PLUGIN_DATA/orchestrator-guard-state, else
<config>/adcm-toolkits/orchestrator-guard-state; flock (when available) + atomic replace. projects/<hash>.json
remembers the last handoff. Env ADCM_GUARD_BASH_CAP / ADCM_GUARD_READ_CAP can only lower the caps.
"""
import json
import os
import re
import sys
import time
from contextlib import contextmanager

LOCK_AT, GATE_AT, STATUS_CAP = 3, 2, 3
EDIT_CAP, EXEMPT_CAP, BASH_LINES, MEMORY_LINE, HANDOFF_MIN = 20, 300, 25, 150, 300
BASH_CAP, READ_CAP = 25, 8
HEAVY_BYTES, PEEK_BYTES, TRANSCRIPT_BYTES = 40 * 1024, 8 * 1024, 5 * 1024 * 1024
WHOLE_PROMPT, EDGE_LINE, STATUS_PROMPT = 280, 200, 160
PRUNE_SECONDS, PENDING_SECONDS, CHUNK = 14 * 86400, 72 * 3600, 1 << 20
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".bmp", ".tif", ".tiff", ".heic", ".avif"}
PROTECTED = {"task.md", "execute.md", "plan-detallado.md", "detailed-plan.md", "plans.html", "prompts.html"}
DUMPERS = {"cat", "bat", "less", "more", "nl", "tac"}
READERS = {"cat", "jq", "tail", "head", "less", "more", "bat", "grep", "egrep", "awk", "sed", "cut", "strings"}
SHELLS = {"bash", "sh", "zsh"}
READ_ONLY = {"cd", "ls", "cat", "head", "tail", "wc", "nl", "stat", "file", "grep", "egrep", "fgrep", "diff", "md5", "md5sum",
             "shasum", "sha1sum", "sha256sum", "test", "[", "realpath", "readlink", "du", "pwd"}
ASSIGNERS = {"export", "declare", "typeset", "readonly", "local"}
INTERPRETERS = {"python", "node", "ruby", "perl", "php", "deno", "bun", "osascript"}
BUDGET = {"Bash": "bash", "Grep": "bash", "Glob": "bash", "LS": "bash", "Read": "read"}
EDITORS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
LAUNDERERS = {"ScheduleWakeup", "CronCreate", "RemoteTrigger"}
ESCAPES = ("modo directo", "modo orquestador", "sin tanto lio", "direct mode", "orchestrator mode")
ARTIFACT_OK = {"open", "list", "pin", "unpin"}
SEGMENT = "orchestrator-guard-state"
XARGS = "\x00xargs-stdin"
ENV_PREFIX = "\x00env-prefix"
ASSIGN = "\x00assign"
NEEDLE = b'"subtype":"compact_boundary"'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD_FILES = (os.path.join(".claude-plugin", "plugin.json"), os.path.join("hooks", "hooks.json"),
               os.path.join("scripts", "main-thread-guard.py"))
HANDOFF_RE = re.compile(r"(?i)^handoff[\w.-]*\.md$")
CONFIG_PROJECTS_RE = re.compile(r"/\.claude[^/]*/projects/")
MEMORY_RE = re.compile(r"/\.claude[^/]*/projects/[^/]+/memory/")
STAMP_RE = re.compile(r"^\s*- \*\*Main thread:\*\*")
SUBST_RE = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
BRACE_RE = re.compile(r"\{([^{}]*,[^{}]*)\}")
QUOTED_RE = re.compile(r"<pasted_content\b.*?(?:</pasted_content>|\Z)|```.*?(?:```|\Z)|`[^`\n]*`|\"[^\"\n]*\"|"
                       r"“[^”\n]*”|«[^»\n]*»", re.S)
NEGATION_RE = re.compile(r"\b(no|nunca|sin|desactiva\w*|apaga\w*|quita\w*|sal(?:ir)? del?)\b")
NEGATION_AFTER_RE = re.compile(r"^\s*(no|off|nunca|fuera)\b")
NOT_OWNER_RE = re.compile(r"^\s*(?:<[A-Za-z!/?_]|\[(?:SYSTEM|Subagent|Artifact|Cross-session))", re.I)
_ITEM = r"(?:mrs?|prs?|links?)"
STATUS_RE = re.compile(
    r"(?:(?:oye|ok|okay|hey|bueno|entonces|y|a ver) )*"
    rf"(?:en que (?:nos )?quedamos|donde (?:nos )?quedamos|donde estan los {_ITEM}(?: (?:y|e) (?:los )?{_ITEM})*|status|"
    r"que sigue|como vamos|estado del proyecto|where did we leave off|whats next|project status)"
    r"(?: (?:del proyecto|de la ola(?: [a-z]{0,3}\d\w*)?|de [a-z]{0,3}\d\w*|hoy|ahora|vamos|por favor))*")
HEAD = "⛔ main-thread-guard [{}]: "
HANDOFF_NEEDS = ("el handoff (≥ 300 caracteres) debe tener estado, pendientes, agentes vivos, siguiente paso y prompt "
                 "de reanudación")
DELEGATE = "delega en adcm-toolkits:executor o adcm-toolkits:researcher con un brief ≤ 40 líneas"
STATUS_NOTE = ("Pregunta de estado: 1 llamada — `status-digest --brain <docs_dir> --mrs`; responde con sus links; "
               "si imprime STALE dilo y ofrece profundizar; nunca investigues en silencio.")
MODE_TEXT = {
    "sticky": "[adcm-guard] modo directo ACTIVO hasta `modo orquestador`: R2, R3, R6, X1 y X2 apagadas; T0, R1, R1b y M1 siguen.",
    "turn": "[adcm-guard] modo directo solo este turno (`sin tanto lío`): R2, R3, R6, X1 y X2 apagadas; T0, R1, R1b y M1 siguen.",
    "off": "[adcm-guard] modo orquestador: todas las reglas activas (T0, R1, R1b, M1, R6, R3, X1, X2, R2).",
}


# ---------------------------------------------------------------- environment and paths

def is_sub(d):
    return bool(d.get("agent_id"))  # MUTATION-KEY: discriminator


def attended():
    if os.environ.get("ADCM_GUARD_FORCE") == "1":  # MUTATION-KEY: force
        return True
    flag = os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") or ""
    if flag == "0":  # MUTATION-KEY: attended
        return False
    return bool(flag) or not os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk")


def env_cap(name, default):
    """An env cap may only lower the default."""
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return min(value, default) if value >= 0 else default


def caps():
    return {"bash": env_cap("ADCM_GUARD_BASH_CAP", BASH_CAP), "read": env_cap("ADCM_GUARD_READ_CAP", READ_CAP)}


def state_dir():
    forced = os.environ.get("ADCM_GUARD_STATE_DIR")
    if forced:
        return os.path.abspath(os.path.expanduser(forced))
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        return os.path.join(os.path.abspath(data), SEGMENT)
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(os.path.abspath(os.path.expanduser(config)), "adcm-toolkits", SEGMENT)


def absolute(path, cwd):
    path = os.path.expanduser(str(path or ""))
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    return os.path.normpath(path)


def forms(path):
    return {path, os.path.realpath(path)}


def inside(path, roots):
    """True when `path` is one of `roots` or below one: case-folded, then by samefile on existing ancestors."""
    folded = [r.casefold() for r in roots]
    for p in forms(path):
        pc = p.casefold()
        if any(pc == r or pc.startswith(r.rstrip(os.sep) + os.sep) for r in folded):
            return True
    real = [r for r in roots if os.path.exists(r)]
    probe = path
    while real and probe:
        if os.path.exists(probe):
            for r in real:
                try:
                    if os.path.samefile(probe, r):
                        return True
                except OSError:
                    pass
        parent = os.path.dirname(probe)
        probe = None if parent == probe else parent
    return False


def is_ancestor(path, roots):
    pcs = {p.casefold().rstrip(os.sep) for p in forms(path)}
    return any(r.casefold() == p or r.casefold().startswith(p + os.sep) for r in roots for p in pcs)


def is_handoff(path):
    if not path:
        return False
    base, parent = os.path.basename(path), os.path.basename(os.path.dirname(path))
    return bool(HANDOFF_RE.match(base)) or (base.lower().endswith(".md") and parent == "handoffs")  # MUTATION-KEY: handoff


def real_handoff(path, d):
    """Only a real handoff is stamped, indexed and releases R1b: template header labels, or the fallback dir."""
    fallback = os.path.join(os.path.dirname(str(d.get("transcript_path") or "")), "handoffs")
    if os.path.dirname(path).casefold() == os.path.normpath(fallback).casefold():
        return True
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(65536)
    except OSError:
        return False
    return "- **Wave:**" in text and ("- **Phase closed:**" in text or "- **Result:**" in text)  # MUTATION-KEY: real_handoff


def is_memory(path):
    if not path:
        return False
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    roots = forms(os.path.join(absolute(config, "/"), "projects")) if config else set()
    for p in forms(path):
        if MEMORY_RE.search(p):
            return True
        for root in roots:
            rest = p[len(root) + 1:].split(os.sep) if p.startswith(root + os.sep) else []
            if len(rest) >= 3 and rest[1] == "memory":
                return True
    return False


def under_config_projects(path):
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    roots = forms(os.path.join(absolute(config, "/"), "projects")) if config else set()
    return any(CONFIG_PROJECTS_RE.search(p) or any(p.startswith(r + os.sep) for r in roots) for p in forms(path))


def tool_input(d):
    ti = d.get("tool_input")
    if isinstance(ti, str):
        try:
            ti = json.loads(ti)
        except ValueError:
            ti = {}
    return ti if isinstance(ti, dict) else {}


def target_of(ti, cwd):
    raw = ti.get("file_path") or ti.get("notebook_path") or ""
    return absolute(raw, cwd) if raw else ""


def fold(text):
    import unicodedata
    text = unicodedata.normalize("NFKD", str(text)).replace("’", "'")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


# ---------------------------------------------------------------- state

def safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(name or "unknown"))[:96] or "unknown"


def write_text(path, text):
    import tempfile
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False))


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


DEFAULTS = {"compactions": 0, "compact_log": [], "bash": 0, "read": 0, "direct": "off", "status": False,
            "status_calls": 0, "handoff_written": False, "handoff_path": ""}


def no_lock_once(folder, exc):
    marker = os.path.join(folder, ".nolock-logged")
    if not os.path.exists(marker):
        open(marker, "w").close()
        log_error(RuntimeError(f"sin bloqueo de archivo ({exc}); reglas activas solo con reemplazo atómico"))


@contextmanager
def session_state(sid):
    folder = state_dir()
    os.makedirs(folder, exist_ok=True)
    key = safe(sid)
    path = os.path.join(folder, key + ".json")
    try:
        import fcntl
    except ImportError as exc:
        fcntl = None
        no_lock_once(folder, exc)
    with open(os.path.join(folder, key + ".lock"), "a+") as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        st = dict(DEFAULTS, **read_json(path))
        before = json.dumps(st, sort_keys=True)
        yield st
        if json.dumps(st, sort_keys=True) != before:
            write_json(path, st)


def index_path(d):
    import hashlib
    key = hashlib.sha256(os.path.dirname(str(d.get("transcript_path") or "")).encode("utf-8")).hexdigest()[:20]
    return os.path.join(state_dir(), "projects", key + ".json")


def prune(current):
    now = time.time()
    folder = state_dir()
    for sub in (folder, os.path.join(folder, "projects")):
        try:
            names = os.listdir(sub)
        except OSError:
            continue
        for name in names:
            path = os.path.join(sub, name)
            if name.startswith(current) or not name.endswith((".json", ".lock")):
                continue
            try:
                if now - os.path.getmtime(path) > PRUNE_SECONDS:
                    os.remove(path)
            except OSError:
                pass


def log_error(exc):
    try:
        folder = state_dir()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "errors.log")
        if os.path.exists(path) and os.path.getsize(path) > 256 * 1024:
            os.remove(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {type(exc).__name__}: {str(exc)[:300]!r}\n")
    except Exception:
        pass


# ---------------------------------------------------------------- output

def deny(rule, text):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": HEAD.format(rule) + text}}


def inject(event, notes, system=None):
    notes = [n for n in notes if n]
    if not notes and not system:
        return None
    out = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n".join(notes)}}
    if system:
        out["systemMessage"] = system
    return out


def counter_line(st):
    c = caps()
    line = (f"[adcm-guard] principal: {st['bash']}/{c['bash']} Bash · {st['read']}/{c['read']} Read · "
            f"{st['compactions']}/{LOCK_AT} compactaciones")
    return line + (f" · modo directo: {st['direct']}" if st["direct"] != "off" else "")


def handoff_target(d, st):
    known = st.get("handoff_path") or read_json(index_path(d)).get("path") or ""
    if known and os.path.basename(os.path.dirname(known)) == "handoffs":
        return os.path.join(os.path.dirname(known), "<Wave>-<nn>-<phase>.md")
    sid8 = str(d.get("session_id") or "unknown")[:8]
    base = os.path.dirname(str(d.get("transcript_path") or "")) or os.getcwd()
    return os.path.join(base, "handoffs", f"handoff-{time.strftime('%Y%m%d')}-{sid8}.md")


# ---------------------------------------------------------------- Bash parsing (shared by T0 and R3)

def strip_prefixes(argv):
    while argv:
        word, base = argv[0], os.path.basename(argv[0])
        if re.match(r"^[A-Za-z_]\w*=", word):
            argv = argv[1:]
        elif base == "xargs":
            argv = argv[1:]
            while argv and argv[0].startswith("-"):
                argv = argv[2:] if argv[0] in ("-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a") else argv[1:]
        elif base in ("env", "sudo", "command", "time", "nohup", "exec"):
            argv = argv[1:]
            while argv and (argv[0].startswith("-") or (base == "env" and re.match(r"^[A-Za-z_]\w*=", argv[0]))):
                takes = base == "sudo" and argv[0] in ("-u", "-g", "-C", "-h", "-p", "-U")
                argv = argv[2:] if takes else argv[1:]
        elif base == "timeout":
            argv = argv[1:]
            while argv and argv[0].startswith("-"):
                argv = argv[2:] if argv[0] in ("-s", "-k", "--signal", "--kill-after") else argv[1:]
            argv = argv[1:]
        elif base == "rtk":
            argv = argv[2:] if argv[1:2] == ["proxy"] else argv[1:]
            if argv[:1] == ["read"]:
                argv = ["cat"] + argv[1:]
        else:
            break
    return argv


def shell_script(argv):
    for i, arg in enumerate(argv[1:], 1):
        if not arg.startswith("-"):
            return None
        if not arg.startswith("--") and "c" in arg[1:]:
            return argv[i + 1] if i + 1 < len(argv) else None
    return None


def commands(cmd, cwd, depth=0):
    """(argv, cwd) per simple command, tracking `cd`; one level into $(...), backticks and `sh -c`."""
    import shlex
    inner = [m.group(1) if m.group(1) is not None else m.group(2) for m in SUBST_RE.finditer(cmd)] if depth == 0 else []
    lex = shlex.shlex(SUBST_RE.sub(" _subst_ ", cmd).replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    groups, cur = [], []
    for tok in list(lex) + [";"]:
        if tok and set(tok) <= set("();&|"):
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(tok)
    out = []
    for group in groups:
        argv = strip_prefixes(group)
        if not argv:
            if any(re.match(r"^[A-Za-z_]\w*=", t) for t in group):
                out.append(([ASSIGN], cwd))
            continue
        stripped = group[:len(group) - len(argv)]
        if "xargs" in [os.path.basename(t) for t in stripped]:
            argv = argv + [XARGS]
        assigned = [t for t in stripped if re.match(r"^[A-Za-z_]\w*=", t)]
        if assigned:
            argv = argv + [ENV_PREFIX] + assigned
        prog = os.path.basename(argv[0])
        out.append((argv, cwd))
        if prog == "cd":
            cwd = (expand(argv[1], cwd) or [cwd])[0] if len(argv) > 1 else os.path.expanduser("~")
        elif prog in SHELLS and depth == 0:
            script = shell_script(argv)
            if script is not None:
                out.extend(commands(script, cwd, depth + 1))
        elif prog == "eval" and depth == 0 and len(argv) > 1:
            out.extend(commands(" ".join(argv[1:]), cwd, depth + 1))
    for body in inner:
        out.extend(commands(body, cwd, 1))
    return out


def braces(word, budget=64):
    m = BRACE_RE.search(word)
    if not m:
        return [word]
    out = []
    for alt in m.group(1).split(","):
        out.extend(braces(word[:m.start()] + alt + word[m.end():], budget))
        if len(out) >= budget:
            break
    return out[:budget]


def expand(tok, cwd):
    """Paths a shell word may name: ~, $HOME, $PWD, brace lists and globs, against cwd."""
    home = os.path.expanduser("~")
    word = re.sub(r"\$(?:HOME\b|\{HOME\})", lambda _: home, tok)
    word = re.sub(r"\$(?:PWD\b|\{PWD\})", lambda _: cwd or os.getcwd(), word)
    word = re.sub(r"\$(?:CLAUDE_PLUGIN_ROOT\b|\{CLAUDE_PLUGIN_ROOT\})", lambda _: os.environ.get("CLAUDE_PLUGIN_ROOT") or PLUGIN_ROOT, word)
    out = []
    for w in braces(word):
        w = os.path.normpath(absolute(w, cwd))
        if any(ch in w for ch in "*?["):
            import glob
            out.extend(glob.glob(w) or [w])
        else:
            out.append(w)
    return out


def is_redirect(tok):
    return set(tok) <= set("<>&|0123456789") and ("<" in tok or ">" in tok)


def words(argv):
    """Non-option words of a command; the target of an output redirection is skipped, an input one kept."""
    out, skip = [], False
    for tok in argv[1:]:
        if skip:
            skip = False
            continue
        if is_redirect(tok):
            skip = "<" not in tok or tok.startswith("<<")
            continue
        if tok and not tok.startswith("-"):
            out.append(tok)
    return out


# ---------------------------------------------------------------- PreToolUse rules

def split_redirects(argv):
    """(words, writes): non-option words (input redirections included) and output-redirection targets."""
    out, writes, mode = [], [], None
    for tok in argv[1:]:
        if mode:
            if mode == "w":
                writes.append(tok)
            elif mode == "r":
                out.append(tok)
            mode = None
            continue
        if is_redirect(tok):
            mode = "s" if tok.startswith("<<") else ("r" if "<" in tok else "w")
            continue
        if tok and not tok.startswith("-"):
            out.append(tok)
    return out, writes


def read_only(prog, argv):
    """Verbs allowed to touch the protected set: they only read."""
    if prog == "find":
        return not any(a == "-delete" or a.startswith(("-exec", "-ok", "-fprint", "-fls")) for a in argv[1:])
    flags = [a for a in argv[1:] if a.startswith("-")]
    if prog == "file" and any(a == "--compile" or (not a.startswith("--") and "C" in a[1:]) for a in flags):
        return False
    return prog in READ_ONLY  # MUTATION-KEY: read_only


def operands(argv):
    """Every word a command names: positional words plus the values of `key=value` and `--opt=value` tokens."""
    out, skip = [], False
    for tok in argv[1:]:
        if skip:
            skip = False
            continue
        if is_redirect(tok):
            skip = True
            continue
        if "=" in tok:
            value = tok.split("=", 1)[1]
            out.extend([value] + [w for w in value.split() if w != value and not w.startswith("-")])
        elif tok and not tok.startswith("-"):
            out.append(tok)
    return out


def sources_of_mv(argv, args):
    if "-t" in argv[:-1]:
        dest = argv[argv.index("-t") + 1]
        return [a for a in args if a != dest]
    return args[:-1]


def wipes_ancestor(prog, argv, args, here, hit):
    """A destructive command aimed AT a folder above the protected set."""
    short = [a for a in argv[1:] if a.startswith("-") and not a.startswith("--")]
    recursive = "--recursive" in argv or any(set(a[1:]) & {"r", "R"} for a in short)
    if prog == "rm":
        return recursive and hit(args)
    if prog in ("chmod", "chown"):
        return ("-R" in short or any("R" in a[1:] for a in short) or "--recursive" in argv) and hit(args)
    if prog == "find" and not read_only(prog, argv):
        starts = []
        for a in argv[1:]:
            if a.startswith(("-", "(", "!")):
                break
            starts.append(a)
        return hit(starts or [here])
    if prog == "rsync" and any(a.startswith("--delete") for a in argv):
        return hit(args[-1:])
    if prog == "git" and "clean" in argv[1:]:
        after = argv[argv.index("clean") + 1:]
        dry = any(a in ("-n", "--dry-run") or (a.startswith("-") and not a.startswith("--") and "n" in a[1:]) for a in after)
        where = argv[argv.index("-C") + 1] if "-C" in argv[:argv.index("clean")] else here
        return not dry and hit([where])
    if prog == "mv":
        return hit(sources_of_mv(argv, args))
    return False


def tamper(tool, ti, cwd):
    roots, plugin = forms(state_dir()), forms(PLUGIN_ROOT)
    guard_paths = [os.path.join(r, f) for r in plugin for f in GUARD_FILES]
    guard_files = {g.casefold() for g in guard_paths}
    guard_dirs = {os.path.dirname(g).casefold() for g in guard_paths} | {r.casefold() for r in plugin}

    def protected(path):
        return any(p.casefold() in guard_files for p in forms(path))

    def guard_set(path):
        return protected(path) or any(p.casefold().rstrip(os.sep) in guard_dirs for p in forms(path))
    if tool in LAUNDERERS:
        text = fold(json.dumps(ti, ensure_ascii=False))
        if any(p in text for p in ESCAPES):
            return "las frases de escape son solo de A, escritas por A; no se programan ni se reenvían."
    if tool in EDITORS:
        path = target_of(ti, cwd)
        if path and inside(path, roots):
            return "el estado del guard no se edita con herramientas; si hay que reiniciarlo, A lo borra a mano."
        if path and protected(path):
            return "el plugin que corre este guard no se edita desde la sesión; el cambio va al repo fuente por un executor."
    if tool != "Bash":
        return None
    try:
        parsed = commands(str(ti.get("command") or ""), cwd)
    except ValueError:
        return None
    state_msg = ("el estado del guard solo se lee desde Bash (ls, cat, grep, find…); cualquier otro comando sobre él "
                 "se niega; si hay que reiniciarlo, A lo borra a mano.")
    guard_msg = ("el guard, sus carpetas y su hooks.json / plugin.json solo se leen desde la sesión; el cambio va al repo "
                 "fuente por un executor.")
    names = [root.casefold() for root in plugin] + ["$claude_plugin_root", "${claude_plugin_root}"]
    feeders = [t for argv, _ in parsed for t in operands(argv) if t not in (XARGS, ENV_PREFIX)]
    assigns = any(ENV_PREFIX in argv or argv[0] == ASSIGN or os.path.basename(argv[0]) in ASSIGNERS or (
        os.path.basename(argv[0]) == "set" and any(a.startswith("-") and "a" in a[1:] for a in argv[1:])) for argv, _ in parsed)
    for argv, here in parsed:
        prog = os.path.basename(argv[0])
        args, writes = split_redirects(argv)
        named = [t for t in operands(argv) if t not in (XARGS, ENV_PREFIX)] + (feeders if XARGS in argv else [])
        if prog == "git":  # MUTATION-KEY: git_cwd
            named.append(here)

        def resolve(toks):
            return [p for t in toks for p in expand(t, here)]
        written, touched = resolve(writes), resolve(named)
        if any(inside(p, roots) for p in written) or any(guard_set(p) for p in written):  # MUTATION-KEY: redirect
            return state_msg if any(inside(p, roots) for p in written) else guard_msg
        in_state = any(inside(p, roots) for p in touched)
        in_guard = any(guard_set(p) for p in touched)
        if (in_state or in_guard) and not read_only(prog, argv):  # MUTATION-KEY: tamper
            return state_msg if in_state else guard_msg
        moved = os.path.normpath(here) != os.path.normpath(cwd or os.getcwd())
        if moved and (inside(here, roots) or guard_set(here)) and not read_only(prog, argv):  # MUTATION-KEY: cwd_rule
            return state_msg if inside(here, roots) else guard_msg
        if (in_state or in_guard) and assigns:  # MUTATION-KEY: env_prefix
            return state_msg if in_state else guard_msg
        if prog.rstrip("0123456789.") in INTERPRETERS:
            text = " ".join(argv).casefold()
            bare = any(SEGMENT in t.casefold() for t in argv[1:] if not re.search(r"\s", t))
            if bare or any(r.casefold() in text for r in roots):  # MUTATION-KEY: interpreter
                return state_msg
            if any(n in text for n in names) and any(f in text for f in ("main-thread-guard.py", "hooks.json", "plugin.json")):
                return guard_msg

        def hits_tree(toks):
            return any(is_ancestor(p, roots) for p in resolve(toks))

        def hits_guard_tree(toks):
            return any(is_ancestor(p, guard_paths) for p in resolve(toks))
        if wipes_ancestor(prog, argv, args, here, hits_tree):  # MUTATION-KEY: ancestor
            return state_msg
        if wipes_ancestor(prog, argv, args, here, hits_guard_tree):  # MUTATION-KEY: guard_tree
            return guard_msg
    return None


def edits_of(tool, ti):
    if tool == "MultiEdit":
        return [e for e in ti.get("edits") or [] if isinstance(e, dict)]
    return [ti]


def memory_line(tool, ti, cwd):
    if tool not in ("Write", "Edit", "MultiEdit"):
        return None
    path = target_of(ti, cwd)
    if os.path.basename(path) != "MEMORY.md" or os.path.basename(os.path.dirname(path)) != "memory":
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
    except (OSError, UnicodeDecodeError):
        old = ""
    if tool == "Write":
        new = str(ti.get("content") or "")
    else:
        new, added = old, []
        for e in edits_of(tool, ti):
            was, now = str(e.get("old_string") or ""), str(e.get("new_string") or "")
            if was and was in new:
                new = new.replace(was, now) if e.get("replace_all") else new.replace(was, now, 1)
            else:
                added.append(now)
        new = "\n".join([new] + added)
    seen = set(old.splitlines())
    long = [l for l in new.splitlines() if l not in seen and len(l) > MEMORY_LINE]  # MUTATION-KEY: memory_line
    if long:
        return (f"una línea nueva del índice mide {len(long[0])} caracteres: el detalle va en el archivo de "
                f"memoria; la línea del índice ≤ {MEMORY_LINE}. Escribe el detalle en su archivo y deja aquí una línea corta.")
    return None


def whole_refusal(path):
    """Why a whole-file read of `path` is refused on the main thread, or None."""
    names = {os.path.basename(path).lower(), os.path.basename(os.path.realpath(path)).lower()}
    if any(os.path.splitext(n)[1] in IMAGE_EXT for n in names):  # MUTATION-KEY: image
        return "image"
    if not os.path.isfile(path):
        return None
    if names & PROTECTED:
        return "protected"
    if os.path.getsize(path) > HEAVY_BYTES:  # MUTATION-KEY: size
        return "big"
    return None


def peek_bytes(path, offset, limit):
    total = 0
    try:
        start = max(int(offset or 1), 1)
    except (TypeError, ValueError):
        start = 1
    with open(path, "rb") as fh:
        for n, line in enumerate(fh, 1):
            if n < start:
                continue
            if n >= start + limit:
                break
            total += len(line)
            if total > PEEK_BYTES:
                break
    return total


def read_limit(value):
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def heavy_read(ti, cwd):
    path = target_of(ti, cwd)
    why = whole_refusal(path) if path else None
    if why == "image":
        return (f"{os.path.basename(path)} es imagen o PDF: envíala con SendUserFile sin leerla; la revisión "
                "visual es de un sub-agente.")
    if not why:
        return None
    name, kb = os.path.basename(path), os.path.getsize(path) // 1024
    limit = read_limit(ti.get("limit"))
    if limit < 1:
        return (f"{name} ({kb} KB{', doc protegido' if why == 'protected' else ''}) no se lee entero en el hilo "
                "principal: lee un tramo con offset/limit (≤ 8 KB) o delega en adcm-toolkits:researcher.")
    try:
        size = peek_bytes(path, ti.get("offset"), limit)
    except OSError:
        return None
    if size > PEEK_BYTES:  # MUTATION-KEY: peek
        return (f"el tramo pedido de {name} pasa de 8 KB: pide menos líneas con offset/limit o delega en "
                "adcm-toolkits:researcher.")
    return None


def heavy_bash(cmd, cwd):
    try:
        parsed = commands(cmd, cwd)
    except ValueError:
        return None
    for argv, here in parsed:
        prog = os.path.basename(argv[0])
        if prog not in READERS and prog not in DUMPERS:
            continue
        for tok in words(argv):
            for path in expand(tok, here):
                if not os.path.isfile(path) and os.path.splitext(path)[1].lower() not in IMAGE_EXT:
                    continue
                if prog in DUMPERS and whole_refusal(path):
                    return (f"`{prog}` volcaría {os.path.basename(path)} entero en el hilo principal: usa Read con "
                            "offset/limit (≤ 8 KB) o delega en adcm-toolkits:researcher.")
                big = path.endswith(".jsonl") and os.path.isfile(path) and os.path.getsize(path) > TRANSCRIPT_BYTES  # MUTATION-KEY: jsonl
                if big and under_config_projects(path):
                    return "los transcripts son trabajo de un researcher: delega en adcm-toolkits:researcher con un brief."
    return None


def browser(tool, ti):
    low = tool.lower()
    if low.startswith("mcp__") and any(k in low for k in ("chrome", "playwright", "puppeteer", "browser")):  # MUTATION-KEY: browser
        return ("el navegador es de un sub-agente: delega en adcm-toolkits:researcher (o adcm-toolkits:executor-frontend "
                "para la revisión visual).")
    if tool == "Artifact" and str(ti.get("action") or "publish") not in ARTIFACT_OK:
        return "publicar y leer Artifacts es del courier: delega en adcm-toolkits:courier."
    return None


def lines_of(text):
    return len(str(text or "").splitlines())


def edit_cap(tool, ti, path):
    if tool in EDITORS:
        if tool == "Write":
            n = lines_of(ti.get("content"))
        elif tool == "NotebookEdit":
            n = lines_of(ti.get("new_source"))
        else:
            n = max([max(lines_of(e.get("old_string")), lines_of(e.get("new_string"))) for e in edits_of(tool, ti)] or [0])
        exempt = is_handoff(path) or is_memory(path) or (
            path.lower().endswith(".md") and os.path.basename(os.path.dirname(path)) == "qa")
        cap = EXEMPT_CAP if exempt else EDIT_CAP
        if n > cap:  # MUTATION-KEY: edit_cap
            return (f"edición de {n} líneas (> {cap}) en el hilo principal: delega en adcm-toolkits:executor "
                    "con un brief ≤ 40 líneas.")
    if tool == "Bash":
        n = lines_of(ti.get("command"))
        if n > BASH_LINES:
            return (f"comando Bash de {n} líneas (> {BASH_LINES}): eso es un script; delega en adcm-toolkits:executor "
                    "con un brief ≤ 40 líneas.")
    return None


def lock_allows(tool, ti, path):
    if tool == "ToolSearch" and str(ti.get("query") or "").strip() == "select:PushNotification":
        return True
    return tool == "PushNotification" or (
        tool in ("Write", "Edit", "MultiEdit", "Read") and (is_handoff(path) or is_memory(path)))


def budget_key(tool, path):
    key = BUDGET.get(tool)
    return None if key == "read" and (is_handoff(path) or is_memory(path)) else key


def count(st, tool, path):
    key = budget_key(tool, path)
    if key:
        st[key] += 1


def memory_deny(tool, ti, cwd):
    why = memory_line(tool, ti, cwd)
    return deny("M1", why) if why else None


def decide(d, st, tool, ti, cwd):
    path = target_of(ti, cwd)
    if not attended():
        return count(st, tool, path)  # MUTATION-KEY: unattended_count
    comp = st["compactions"]
    if comp >= LOCK_AT:  # MUTATION-KEY: lock
        if not lock_allows(tool, ti, path):
            return deny("R1", "3.ª compactación: guarda estado en el handoff y la memoria y pide /clear a A.")
        return memory_deny(tool, ti, cwd)
    if comp == GATE_AT and not st["handoff_written"]:  # MUTATION-KEY: gate
        if not lock_allows(tool, ti, path):
            return deny("R1b", f"2.ª compactación: escribe el handoff YA en {handoff_target(d, st)}; "
                               f"{HANDOFF_NEEDS} (solo Write/Edit/Read del handoff y la memoria hasta entonces).")
        return memory_deny(tool, ti, cwd)
    found = memory_deny(tool, ti, cwd)
    if found:
        return found
    relaxed = st["direct"] != "off"  # MUTATION-KEY: direct
    if relaxed:
        count(st, tool, path)
        return None
    if st["status"] and tool not in ("ToolSearch", "Skill"):
        st["status_calls"] += 1
        if st["status_calls"] > STATUS_CAP:  # MUTATION-KEY: status
            return deny("R6", "turno de estado: responde ya con digest + git + MRs y ofrece profundizar.")
    why = None
    if tool == "Read":
        why = heavy_read(ti, cwd)
    elif tool == "Bash":
        why = heavy_bash(str(ti.get("command") or ""), cwd)
    if why:
        return deny("R3", why)
    why = browser(tool, ti)
    if why:
        return deny("X1", why)
    why = edit_cap(tool, ti, path)
    if why:
        return deny("X2", why)
    key = budget_key(tool, path)
    if key:
        cap = caps()[key]
        if st[key] >= cap:  # MUTATION-KEY: cap
            return deny("R2", f"presupuesto del hilo principal agotado ({st[key]}/{cap}): {DELEGATE}; solo A lo "
                              "levanta con `modo directo`.")
        st[key] += 1
    return None


def pre_tool(d):
    tool, ti, cwd = str(d.get("tool_name") or ""), tool_input(d), str(d.get("cwd") or "")
    why = tamper(tool, ti, cwd)
    if why:
        return deny("T0", why)
    if is_sub(d):
        return memory_deny(tool, ti, cwd) if attended() else None
    with session_state(d.get("session_id")) as st:
        return decide(d, st, tool, ti, cwd)


# ---------------------------------------------------------------- UserPromptSubmit

def phrase_region(prompt):
    clean = QUOTED_RE.sub(" ", prompt)
    if len(prompt) <= WHOLE_PROMPT:  # MUTATION-KEY: phrase_region
        return fold(clean)
    lines = [l for l in clean.splitlines() if l.strip()]
    return fold("\n".join(l for l in lines[:1] + lines[-1:] if len(l) <= EDGE_LINE))


def next_direct(current, prompt):
    region = phrase_region(prompt)
    if "modo orquestador" in region:
        return "off"
    verdict = None
    for sentence in re.split(r"[.!?;\n]+", region):
        at = sentence.find("modo directo")
        if at >= 0:
            after = sentence[at + len("modo directo"):]
            negated = NEGATION_RE.search(sentence[:at]) or NEGATION_AFTER_RE.match(after)
            verdict = "off" if negated else "sticky"
    if verdict:
        return verdict
    if "sin tanto lio" in region:
        return "sticky" if current == "sticky" else "turn"
    return "off" if current == "turn" else current


def is_status(prompt):
    if len(prompt) > STATUS_PROMPT:
        return False
    text = " ".join(re.sub(r"[^\w\s]", " ", fold(prompt).replace("'", "")).split())
    return bool(STATUS_RE.fullmatch(text))  # MUTATION-KEY: status_match


def prompt_submit(d):
    if is_sub(d):
        return None
    prompt = str(d.get("prompt") or "")
    owner = not NOT_OWNER_RE.match(prompt)  # MUTATION-KEY: handback
    notes, system = [], None
    with session_state(d.get("session_id")) as st:
        st["status"], st["status_calls"] = False, 0
        if owner:
            mode = next_direct(st["direct"], prompt)
            if mode != st["direct"]:
                st["direct"] = mode
                system = MODE_TEXT[mode]
                notes.append(system)
            if is_status(prompt):
                st["status"] = True
                notes.append(STATUS_NOTE)
        c = caps()
        near = st["compactions"] >= 1 or any(c[k] and st[k] >= 0.8 * c[k] for k in ("bash", "read"))
        if owner or near:
            notes.append(counter_line(st))
    return inject("UserPromptSubmit", notes, system)


# ---------------------------------------------------------------- compaction and session start

def count_boundaries(path):
    total, tail = 0, b""
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(CHUNK)
                if not chunk:
                    break
                buf = tail + chunk
                total += buf.count(NEEDLE)
                tail = buf[-(len(NEEDLE) - 1):]
    except OSError:
        return 0
    return total


def pre_compact(d):
    if is_sub(d):
        return None
    with session_state(d.get("session_id")) as st:
        st["compactions"] += 1
        st["compact_log"] = (st["compact_log"] + [{"trigger": str(d.get("trigger") or ""), "time": int(time.time())}])[-20:]
        n, target = st["compactions"], handoff_target(d, st)
    if n >= 2:
        return (f"[adcm-guard] compactación {n}/{LOCK_AT}: conserva en el resumen la ruta del handoff ({target}), la "
                "ola y la fase en curso y los ids de los agentes vivos.")
    return None


def memory_check(d):
    import subprocess
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check-memory-index.py")
    memory = os.path.join(os.path.dirname(str(d.get("transcript_path") or "")), "memory", "MEMORY.md")
    if not os.path.isfile(script) or not os.path.isfile(memory):
        return None
    try:
        p = subprocess.run([sys.executable, script, "--brief", "--file", memory], capture_output=True, text=True,
                           timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() or None


def session_start(d):
    if is_sub(d):
        return None
    sid = str(d.get("session_id") or "")
    prune(safe(sid))
    source = d.get("source")
    notes = []
    if source in ("compact", "resume"):
        seen = count_boundaries(str(d.get("transcript_path") or ""))  # MUTATION-KEY: transcript
        with session_state(sid) as st:
            st["compactions"] = max(st["compactions"], seen)
            n, target = st["compactions"], handoff_target(d, st)
        if n == 1:
            notes.append("[adcm-guard] compactación 1/3: a la 2.ª se exige el handoff y a la 3.ª el hilo "
                         "principal se bloquea; delega desde ya.")
        elif n == 2:
            notes.append(f"[adcm-guard] COMPACTACIÓN 2/3: escribe el handoff YA en {target}; {HANDOFF_NEEDS}; hasta entonces solo "
                         "Write/Edit/Read del handoff y la memoria.")
        elif n >= 3:
            notes.append("[adcm-guard] 3.ª compactación: hilo principal bloqueado; guarda estado en el handoff y "
                         "la memoria y pide /clear a A.")
    elif source in ("startup", "clear"):
        last = read_json(index_path(d))
        if last.get("path") and time.time() - float(last.get("time") or 0) < PENDING_SECONDS:
            notes.append(f"[adcm-guard] HANDOFF pendiente: {last['path']}")
        notes.append(memory_check(d))
    return inject("SessionStart", notes)


# ---------------------------------------------------------------- PostToolUse: handoff record + stamp

def stamp(path, line):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    lines = text.split("\n")
    hits = [i for i, l in enumerate(lines) if STAMP_RE.match(l)]
    if hits:
        lines[hits[0]] = line
        for i in reversed(hits[1:]):
            del lines[i]
    else:
        start = next((i for i, l in enumerate(lines) if l.startswith("- **")), None)
        if start is None:
            lines = (lines[:-1] if lines and lines[-1] == "" else lines) + [line, ""]
        else:
            end = start
            while end + 1 < len(lines) and lines[end + 1].startswith("- **"):
                end += 1
            lines.insert(end + 1, line)
    new = "\n".join(lines)
    if new != text:
        write_text(path, new)


def post_tool(d):
    if d.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return None
    path = target_of(tool_input(d), str(d.get("cwd") or ""))
    if not is_handoff(path) or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        size = len(fh.read())
    opens = size >= HANDOFF_MIN  # MUTATION-KEY: handoff_size
    real = real_handoff(path, d)
    if not opens and not real:
        return None
    sid = str(d.get("session_id") or "")
    with session_state(sid) as st:
        if opens:
            st["handoff_written"] = True
        st["handoff_path"] = path
        line = (f"- **Main thread:** {st['bash']} Bash · {st['read']} Read · {st['compactions']} compactions "
                f"(session {sid[:8]})")
    if real:
        write_json(index_path(d), {"path": path, "time": time.time(), "session": sid})
        stamp(path, line)
    return None


HANDLERS = {"PreToolUse": pre_tool, "UserPromptSubmit": prompt_submit, "PreCompact": pre_compact,
            "SessionStart": session_start, "PostToolUse": post_tool}


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    if not isinstance(data, dict):
        raise ValueError("hook input is not an object")
    handler = HANDLERS.get(data.get("hook_event_name"))
    out = handler(data) if handler else None
    if out:
        text = json.dumps(out, ensure_ascii=False) if isinstance(out, dict) else str(out)
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
        sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:  # fail open: never break a tool call
        log_error(exc)
    sys.exit(0)
