#!/usr/bin/env python3
"""merge-guard — PreToolUse hook (matcher `Bash|mcp__.*merge.*`) de Claude Code (determinista, sin dependencias).

Regla: Claude no mergea. Cada ola termina con su MR abierto y asignado al Reviewer del brain;
el Reviewer revisa y mergea. Este hook niega los comandos de Bash y las herramientas MCP que mergearían
un MR/PR.

Ámbito: SOLO los MRs de código de las olas. Los repos de documentación (ai-brain, marketplaces)
hacen commit + push directo a main, así que el hook NUNCA toca `git commit` ni los pushes simples
(`git push`, `git push origin main`, `git push origin main:main`, `git push -u origin feature/x`).

Lee de stdin el JSON del hook ({"tool_name": ..., "tool_input": {"command": ...}, "cwd": ...}) y responde:
  - deny  → imprime {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision":
            "deny", "permissionDecisionReason": "⛔ merge-guard: Claude no mergea MRs; el Reviewer
            revisa y mergea. Comando: <segmento>"}} y sale con 0 (para una herramienta MCP la razón es
            "⛔ merge-guard: Claude no mergea MRs (herramienta MCP <tool_name>); el Reviewer revisa y mergea.");
  - allow → sin salida, exit 0.
Fail-open en todo: JSON roto, comando ausente, cwd que no es un repo, comilla sin cerrar, HEAD
detached, un `git` colgado (timeout de 2 s)... lo que el hook no pueda juzgar se permite. Siempre
exit 0: el hook nunca rompe una llamada por sí mismo.

Qué se niega:
  Herramientas MCP (`tool_name` distinto de `Bash`): `mcp__…(merge_merge_request|merge_pull_request|
  accept_merge_request|merge_mr|merge_pr)` (sin distinguir mayúsculas). Cualquier otra herramienta que no
  sea Bash se permite en silencio; sin `tool_name` (o si no es un texto) se aplica la ruta de Bash.
  Bash (decide por argv[0], basename; nunca por el texto suelto del comando):
  - `gh pr merge …` y `glab mr merge|accept …`, salvo `--help|-h` (y `--disable-auto` en gh).
  - API de merge con verbo distinto de GET: `gh api` / `glab api` / `curl|http|https|xh|wget` sobre
    `/pulls/N/merge`, `/merges`, `/merge_requests/N/merge`, `/merge_requests/N/merge_when_pipeline_succeeds`;
    `gh api graphql` con `mergePullRequest|enablePullRequestAutoMerge|enqueuePullRequest|mergeBranch`.
    (`gh api`/`glab api` con campos `-f|-F|--field|--raw-field|--input` y sin `-X` son POST.)
  - `git merge <x>`, `git pull <remote> <rama>` (con o sin `--rebase`), `git rebase <ref>` y
    `git reset --hard|--soft|--keep|--merge <ref>` cuando la rama actual es exactamente main, master,
    develop o trunk. La rama es la del repo al que apunta el comando (`cd`, `git -C`), o la que dejó un
    `git checkout|switch` previo del mismo comando; si no, `git -C <dir> symbolic-ref --short -q HEAD`. En
    `git rebase <ref> <rama>` la rama juzgada es <rama> (git la deja en HEAD), también si HEAD estaba en otra.
    Sincronía permitida: la misma rama, `@{u}`, `<cualquier-remoto>/<misma>` (`origin/main`, `upstream/main`:
    el sync de un fork), `HEAD`, `HEAD~N`, `HEAD^N`; y `git merge|rebase --abort|--continue|--skip|--quit`,
    `git pull`, `git pull [--rebase] <remote> <misma>`, `git rebase`, `git reset --hard`. `HEAD@{N}`,
    `ORIG_HEAD`, un sha o cualquier otra rama no lo son: `git reset --hard <sha>` y `git rebase -i <sha>`
    sobre main se niegan y los corre el dueño con `!`.
  - `git push` con una opción de push de auto-merge (`-o|--push-option` o `-o<valor>` con
    `merge_request.merge_when_pipeline_succeeds`, `merge_request.auto_merge` o `auto_merge`) o con un refspec
    `<src>:<dst>` cuyo <dst> es main|master|develop|trunk (también `refs/heads/<dst>`) y <src> distinto de
    <dst> (`HEAD:main`, `feature/x:main`, `+feat:refs/heads/main`, `:main`).

Cómo lee el comando: pre-pase consciente de comillas (quita `\\`+salto, comentarios `#…` sin tragarse
el salto de línea y cuerpos de heredoc) → shlex en modo posix con los separadores como puntuación →
segmentos; descarta redirecciones, palabras reservadas (`if then do …`), `VAR=v` y envoltorios (`env
command exec sudo nohup time nice timeout xargs`); recursa en `bash|sh|zsh -c`, `eval`, `$(…)` y
backticks. Una comilla sin cerrar (ValueError de shlex) cae a una regex solo para `gh pr merge` y
`glab mr merge|accept`.

Límites conocidos (es un barandal, no una frontera de seguridad): comandos dinámicos (`$(echo gh) pr
merge`), envoltorios desconocidos, `make merge`, scripts que llaman la API por su cuenta, el stdin de
un shell (`bash <<< …`) y el cuerpo de un heredoc sin comillas pasan. Tampoco se juzgan `git cherry-pick`,
`git reset` sin `--hard|--soft|--keep|--merge`, `git fetch <remote> <src>:<protegida>`, `git branch -f`,
`git update-ref`, `git push --delete`, `git merge FETCH_HEAD`, una opción de push puesta por config (`-c push.pushOption=…`,
`.git/config`) ni las herramientas MCP de merge con otros nombres; una rama local llamada `x/main` se
toma por el remoto `x`. Todo esto lo cubre la protección de rama del forge.

Instalación (user settings, event PreToolUse):
  {"hooks": {"PreToolUse": [{"matcher": "Bash|mcp__.*merge.*", "hooks": [{"type": "command",
     "command": "python3 ~/.claude/hooks/merge-guard.py", "timeout": 10}]}]}}

Fuente canónica: plugin adcm-toolkits → skills/execution-prompt-architect/templates/merge-guard.py
"""
import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED = frozenset({"main", "master", "develop", "trunk"})
GIT_TIMEOUT = 2  # segundos que se le dan a `git symbolic-ref`; pasado el plazo, se permite
MAX_DEPTH = 5  # profundidad máxima de bash -c / eval / $(…) anidados
MAX_SHOWN = 200  # caracteres del comando que se citan en la razón del deny

PUNCT = ";&|()<>`\n"  # el salto de línea separa comandos, por eso es puntuación y no espacio
REDIRECT = re.compile(r"^(?:<<<|<<-?|<>|<&|>&|>>|>\||&>>|&>|<|>)$")  # operador que consume el token siguiente
FD_REDIRECT = re.compile(r"[0-9]+(?=[<>])")
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
HEREDOC = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([^\s;&|()<>'\"]+))")
HARD_FALLBACK = re.compile(r"\bgh\s+pr\s+merge\b|\bglab\s+mr\s+(?:merge|accept)\b")

RESERVED = frozenset({"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "in",
                      "!", "{", "}", "case", "esac"})
WRAPPERS = frozenset({"env", "command", "exec", "sudo", "nohup", "time", "nice", "timeout", "xargs"})
WRAPPER_VALUE_FLAGS = {  # opciones de envoltorio cuyo valor es el token siguiente
    "env": {"-u", "-C"},
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U"},
    "nice": {"-n"},
    "timeout": {"-s", "-k"},
    "xargs": {"-I", "-n", "-L", "-P", "-s", "-d", "-E", "-a"},
}
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
SHELL_C_FLAG = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")

HTTP_TOOLS = frozenset({"curl", "wget", "http", "https", "xh", "xhs"})
HTTP_VERBS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
METHOD_FLAGS = frozenset({"-X", "--method", "--request"})
API_BODY_FLAGS = frozenset({"-f", "-F", "--field", "--raw-field", "--input"})  # gh api / glab api: sin -X se vuelve POST
CURL_BODY_FLAGS = frozenset({"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode",
                             "-F", "--form", "--json"})
MERGE_ROUTE = re.compile(r"/(?:pulls/\d+/merge|merges|merge_requests/\d+/(?:merge|merge_when_pipeline_succeeds))(?![\w-])")
GRAPHQL_MERGE = re.compile(r"\b(?:mergePullRequest|enablePullRequestAutoMerge|enqueuePullRequest|mergeBranch)\b")

GIT_GLOBAL_VALUE_OPTS = frozenset({"-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"})
GIT_VALUE_FLAGS = frozenset({"-m", "-F", "-s", "-X", "-j", "-o", "-x", "--message", "--file", "--strategy", "--strategy-option",
                             "--cleanup", "--into-name", "--depth", "--deepen", "--shallow-since", "--shallow-exclude",
                             "--jobs", "--server-option", "--upload-pack", "--refmap", "--negotiation-tip",
                             "--onto", "--exec"})
REBASE_CONTROL = frozenset({"--abort", "--continue", "--skip", "--quit", "--edit-todo", "--show-current-patch"})
RESET_MODES = frozenset({"--hard", "--soft", "--keep", "--merge"})
LOCAL_REF = re.compile(r"HEAD(?:[~^]\d*)*")  # solo la propia historia de la rama; HEAD@{N} y ORIG_HEAD pueden apuntar a otra rama
PUSH_VALUE_FLAGS = frozenset({"--repo", "--receive-pack", "--exec"})
AUTO_MERGE_OPT = re.compile(r"merge_request\.merge_when_pipeline_succeeds|merge_request\.auto_merge|auto_merge", re.I)
MCP_MERGE = re.compile(r"mcp__.*(?:merge_merge_request|merge_pull_request|accept_merge_request|merge_mr|merge_pr)", re.I)


def prepass(cmd):
    """Deja el comando listo para shlex: quita `\\`+salto, comentarios `#…` (conserva el salto de línea), el fd
    de las redirecciones (`2>&1`) y los cuerpos de heredoc (conserva la línea `cmd <<TAG` y el salto que la
    cierra). Lo que va entre comillas se copia tal cual. Nunca lanza excepciones: una comilla sin cerrar
    solo deja el resto citado."""
    out = []
    pending = []  # heredocs abiertos en la línea actual: (etiqueta, quita_tabs)
    quote = None
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if quote == "'":
            out.append(ch)
            if ch == "'":
                quote = None
        elif ch == "\\" and i + 1 < n:  # fuera de comillas simples el backslash escapa el siguiente char
            if cmd[i + 1] != "\n":
                out.append(ch)
                out.append(cmd[i + 1])
            i += 2
            continue
        elif quote == '"':
            out.append(ch)
            if ch == '"':
                quote = None
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        elif ch == "$" and cmd.startswith("$((", i) and matching_paren(cmd, i + 2) is not None:
            end = matching_paren(cmd, i + 2)  # `$(( 1 << 2 ))` no abre un heredoc
            out.append(cmd[i:end + 1])
            i = end + 1
            continue
        elif (not out or out[-1] in " \t\r\n;&|(") and FD_REDIRECT.match(cmd, i):
            i = FD_REDIRECT.match(cmd, i).end()  # el fd de `2>&1` o `3<<EOF` no es un argumento
            continue
        elif ch == "#" and (not out or out[-1] in " \t\r\n;&|("):
            while i < n and cmd[i] != "\n":
                i += 1
            continue
        elif ch == "<" and cmd.startswith("<<", i) and not cmd.startswith("<<<", i):
            m = HEREDOC.match(cmd, i)
            if m and not (m.group(4) or "x").isdigit():  # una etiqueta numérica es un desplazamiento (`1<<2`)
                pending.append((m.group(2) or m.group(3) or m.group(4), m.group(1) == "-"))
                out.append(m.group(0))
                i = m.end()
                continue
            out.append(ch)
        elif ch == "\n":
            out.append(ch)
            i += 1
            for tag, strip_tabs in pending:  # el cuerpo empieza en la línea siguiente al operador
                while i < n:
                    end = cmd.find("\n", i)
                    line = cmd[i:n if end < 0 else end]
                    i = n if end < 0 else end + 1
                    if (line.lstrip("\t") if strip_tabs else line) == tag:
                        break
            pending = []
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def tokenize(text):
    """shlex posix con los separadores como puntuación. Lanza ValueError con una comilla sin cerrar."""
    lex = shlex.shlex(text, posix=True, punctuation_chars=PUNCT)
    lex.whitespace_split = True
    lex.commenters = ""  # los comentarios ya los quitó prepass
    lex.whitespace = " \t\r"  # el \n no es espacio: separa comandos
    return list(lex)


def segments(tokens):
    """Parte los tokens en comandos simples (argv). Las redirecciones desaparecen junto con su objetivo;
    cualquier otro operador (`; && || | & ( ) \\n <( >(`) cierra el segmento."""
    segs, cur, skip = [], [], False
    for tok in tokens:
        if skip:
            skip = False
        elif tok and all(c in PUNCT for c in tok):
            if REDIRECT.match(tok):
                skip = True
            else:
                segs.append(cur)
                cur = []
        else:
            cur.append(tok)
    segs.append(cur)
    return [s for s in segs if s]


def substitutions(text):
    """Cuerpos de `$(…)` y de backticks fuera de comillas simples (los de comillas dobles sí cuentan)."""
    bodies = []
    quote = None
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quote == "'":
            if ch == "'":
                quote = None
        elif ch == "\\":
            i += 1
        elif ch == "'" and quote is None:
            quote = "'"
        elif ch == '"':
            quote = None if quote == '"' else '"'
        elif ch == "$" and text.startswith("$(", i):
            end = matching_paren(text, i + 2)
            if end is not None:
                bodies.append(text[i + 2:end])
                i = end
        elif ch == "`":
            j = i + 1
            while j < n and text[j] != "`":
                j += 2 if text[j] == "\\" else 1
            if j < n:
                bodies.append(text[i + 1:j])
                i = j
        i += 1
    return bodies


def matching_paren(text, start):
    """Índice del `)` que cierra el `$(` cuyo cuerpo empieza en `start`, o None si no cierra."""
    depth, quote, i, n = 1, None, start, len(text)
    while i < n:
        ch = text[i]
        if quote == "'":
            if ch == "'":
                quote = None
        elif ch == "\\":
            i += 1
        elif ch in "'\"":
            quote = None if quote == ch else (quote or ch)
        elif quote is None and ch == "(":
            depth += 1
        elif quote is None and ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def drop_wrapper(argv):
    """Quita el envoltorio argv[0] con sus opciones, sus `VAR=v` y (timeout) la duración."""
    name = os.path.basename(argv[0])
    rest = argv[1:]
    if name == "command" and any(a in ("-v", "-V") for a in rest):
        return []  # `command -v gh` solo consulta
    valued = WRAPPER_VALUE_FLAGS.get(name, ())
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--":
            i += 1
            break
        if a in valued:
            i += 2
        elif a.startswith("-") or ASSIGN.match(a):
            i += 1
        else:
            break
    rest = rest[i:]
    return rest[1:] if name == "timeout" and rest else rest


def strip_prefix(argv):
    """Deja el argv desde el programa real: sin palabras reservadas, `VAR=v` ni envoltorios."""
    while argv:
        if argv[0] in RESERVED or ASSIGN.match(argv[0]):
            argv = argv[1:]
        elif os.path.basename(argv[0]) in WRAPPERS:
            argv = drop_wrapper(argv)
        else:
            break
    return argv


def words_of(args):
    """Argumentos que no son opciones (el valor de -R/--repo tampoco cuenta)."""
    words, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-R", "--repo"):
            i += 1
        elif not a.startswith("-"):
            words.append(a)
        i += 1
    return words


def http_method(args, bare_verb=False):
    """Verbo explícito de la petición (mayúsculas) o None. Con bare_verb, httpie/xh: `http PUT url`."""
    method = None
    for i, a in enumerate(args):
        if a in METHOD_FLAGS and i + 1 < len(args):
            method = args[i + 1]
        elif a.startswith(("--method=", "--request=")):
            method = a.split("=", 1)[1]
        elif a.startswith("-X") and len(a) > 2:
            method = a[2:]
        elif bare_verb and method is None and a.upper() in HTTP_VERBS:
            method = a
    return method.upper() if method else None


def merges_over_api(prog, args):
    """True si la llamada a la API del forge mergea: ruta de merge + verbo que no es GET/HEAD."""
    text = " ".join(args)
    if prog in ("gh", "glab") and "graphql" in args and GRAPHQL_MERGE.search(text):
        return True
    if not MERGE_ROUTE.search(text):
        return False
    method = http_method(args, bare_verb=prog in ("http", "https", "xh", "xhs"))
    if method is None:
        if prog in ("gh", "glab"):
            has_body = any(a.split("=", 1)[0] in API_BODY_FLAGS for a in args)
        else:
            has_body = any(a.split("=", 1)[0] in CURL_BODY_FLAGS for a in args)
            if any(a in ("-T", "--upload-file") for a in args):
                method = "PUT"
        method = method or ("POST" if has_body else "GET")
    return method not in ("GET", "HEAD")


def git_branch(path, state):
    """Rama actual de `path` (None si detached, si no es un repo o si git tarda más de GIT_TIMEOUT)."""
    if state["git"]["hung"]:
        return None
    try:
        proc = subprocess.run(["git", "-C", path, "symbolic-ref", "--short", "-q", "HEAD"], capture_output=True,
                              text=True, timeout=GIT_TIMEOUT, stdin=subprocess.DEVNULL)
        return proc.stdout.strip() or None
    except subprocess.TimeoutExpired:
        state["git"]["hung"] = True  # un `git` colgado no se vuelve a preguntar en este comando
        return None
    except Exception:
        return None


def current_head(path, state):
    """Rama prevista para `path`: la que dejó un checkout|switch previo del comando, o la real."""
    key = os.path.realpath(path)
    if key not in state["heads"]:
        state["heads"][key] = git_branch(path, state)
    return state["heads"][key]


def checkout_target(args):
    """Rama en la que queda HEAD tras `git checkout|switch <args>`: nombre, "" si detached, None si no se sabe."""
    if "--" in args:
        return None  # `git checkout <rev> -- <rutas>` restaura archivos; HEAD no se mueve
    for i, a in enumerate(args):
        if a in ("-b", "-B", "-c", "-C") and i + 1 < len(args):
            return args[i + 1]
        if a in ("-d", "--detach"):
            return ""
        if not a.startswith("-"):
            return a
    return None


def split_git_args(args):
    """(flags, posicionales) de `git merge|pull`; los valores de -m/-s/-X/… no son posicionales."""
    flags, pos, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos.extend(args[i + 1:])
            break
        if a in GIT_VALUE_FLAGS:
            flags.append(a)
            i += 1
        elif a.startswith("-") and a != "-":
            flags.append(a)
        else:
            pos.append(a)
        i += 1
    return flags, pos


def is_sync_ref(ref, branch):
    """`ref` solo trae la propia historia de `branch`: ella misma, su upstream, `<cualquier-remoto>/<misma>`
    (origin, upstream… el sync de un fork) o `HEAD`/`HEAD~N`."""
    if ref in (branch, "refs/heads/" + branch) or LOCAL_REF.fullmatch(ref):
        return True
    if re.fullmatch(r"(?:HEAD|" + re.escape(branch) + r")?@\{(?:u|upstream)\}", ref):
        return True
    return re.fullmatch(r"(?:refs/remotes/)?[^/\s]+/" + re.escape(branch), ref) is not None


def merges_into(sub, args, branch):
    """True si `git merge|pull|reset <args>`, estando en la rama protegida `branch`, la lleva a otra rama."""
    flags, pos = split_git_args(args)
    if sub == "merge":
        if any(f in ("--abort", "--continue", "--quit") for f in flags):
            return False
        return any(not is_sync_ref(p, branch) for p in pos)
    if sub == "reset":
        return any(f in RESET_MODES for f in flags) and bool(pos) and not is_sync_ref(pos[0], branch)
    return any(p not in (branch, "refs/heads/" + branch) for p in pos[1:])  # pull, con o sin --rebase: pos[0] es el remoto


def rebases_onto(args, eff, state):
    """True si `git rebase <args>` reescribe una rama protegida sobre un ref que no es de sincronía."""
    flags, pos = split_git_args(args)
    if any(f in REBASE_CONTROL for f in flags):
        return False
    onto = next((a.split("=", 1)[1] for a in args if a.startswith("--onto=")), None)
    if onto is None and "--onto" in args[:-1]:
        onto = args[args.index("--onto") + 1]
    base = onto or (pos[0] if pos else None)
    if base is None:
        return False
    if len(pos) > 1:  # `git rebase <base> <rama>` deja HEAD en <rama>
        state["heads"][os.path.realpath(eff)] = pos[1]
        branch = pos[1]
    else:
        branch = current_head(eff, state)
    return branch in PROTECTED and not is_sync_ref(base, branch)


def pushes_around_review(args):
    """True si `git push <args>` activa el auto-merge del forge (opción de push) o empuja otro ref a una rama
    protegida (`HEAD:main`). Los pushes simples de los repos de documentación no se tocan."""
    pos, i, has_repo = [], 0, False
    while i < len(args):
        a = args[i]
        value = None
        if a == "--":
            pos.extend(args[i + 1:])
            break
        if a in ("-o", "--push-option"):
            value = args[i + 1] if i + 1 < len(args) else ""
            i += 1
        elif a.startswith("--push-option="):
            value = a.split("=", 1)[1]
        elif a.startswith("-o") and not a.startswith("--"):
            value = a[2:]
        elif a in PUSH_VALUE_FLAGS:
            has_repo = has_repo or a == "--repo"
            i += 1
        elif not a.startswith("-") or a == "-":
            pos.append(a)
        if value is not None and AUTO_MERGE_OPT.search(value):
            return True
        i += 1
    for spec in (pos if has_repo else pos[1:]):  # pos[0] es el remoto
        if ":" in spec:
            src, dst = (r[len("refs/heads/"):] if r.startswith("refs/heads/") else r for r in spec.lstrip("+").split(":", 1))
            if dst in PROTECTED and src != dst:
                return True
    return False


def judge_git(rest, state):
    """True si el comando git mergea sobre una rama protegida o esquiva la revisión; de paso sigue `-C` y los checkout|switch."""
    eff, i = state["cwd"], 0
    while i < len(rest):
        a = rest[i]
        if a == "-C" and i + 1 < len(rest):
            eff = os.path.join(eff, os.path.expanduser(rest[i + 1]))
            i += 2
        elif a in GIT_GLOBAL_VALUE_OPTS and i + 1 < len(rest):
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            break
    if i >= len(rest):
        return False
    sub, args = rest[i], rest[i + 1:]
    if sub in ("checkout", "switch"):
        target = checkout_target(args)
        if target is not None:
            state["heads"][os.path.realpath(eff)] = target
        return False
    if sub == "push":
        return pushes_around_review(args)
    if sub == "rebase":
        return rebases_onto(args, eff, state)
    if sub not in ("merge", "pull", "reset"):
        return False
    branch = current_head(eff, state)
    return branch in PROTECTED and merges_into(sub, args, branch)


def fork_state(state):
    """Estado para un subshell (`bash -c`, `$(…)`): hereda cwd y ramas previstas sin devolver sus cambios
    (el aviso de `git` colgado sí se comparte)."""
    return dict(state, heads=dict(state["heads"]))


def shell_body(args):
    """Texto que ejecuta `bash -c <texto>` (acepta `-lc`, `-ec`…), o None si no hay -c."""
    for i, a in enumerate(args):
        if SHELL_C_FLAG.match(a):
            return args[i + 1] if i + 1 < len(args) else None
    return None


def judge(argv, state, depth):
    """Devuelve el argv ofensor (o None) de un comando simple ya sin prefijos."""
    prog, rest = os.path.basename(argv[0]), argv[1:]
    if prog in SHELLS:
        body = shell_body(rest)
        return scan(body, fork_state(state), depth + 1) if body else None
    if prog == "eval":
        return scan(" ".join(rest), state, depth + 1)
    if prog in ("cd", "pushd"):
        target = next((a for a in rest if not a.startswith("-")), None)
        if target:
            state["cwd"] = os.path.join(state["cwd"], os.path.expanduser(target))
        return None
    if prog == "git":
        return argv if judge_git(rest, state) else None
    help_asked = any(a in ("--help", "-h") for a in rest)
    words = words_of(rest)
    if prog == "gh":
        if words[:2] == ["pr", "merge"] and not help_asked and "--disable-auto" not in rest:
            return argv
        if words[:1] == ["api"] and merges_over_api(prog, rest):
            return argv
    elif prog == "glab":
        if words[:2] in (["mr", "merge"], ["mr", "accept"]) and not help_asked:
            return argv
        if words[:1] == ["api"] and merges_over_api(prog, rest):
            return argv
    elif prog in HTTP_TOOLS and merges_over_api(prog, rest):
        return argv
    return None


def scan(text, state, depth=0):
    """Argv del primer comando que mergea dentro de `text`, o None. Propaga ValueError de shlex."""
    if depth > MAX_DEPTH:
        return None
    text = prepass(text)
    for body in substitutions(text):
        hit = scan(body, fork_state(state), depth + 1)
        if hit:
            return hit
    for seg in segments(tokenize(text)):
        argv = strip_prefix(seg)
        hit = judge(argv, state, depth) if argv else None
        if hit:
            return hit
    return None


def decide(command, cwd):
    """Texto del comando ofensor (para citarlo en la razón) o None si se permite."""
    state = {"cwd": cwd, "heads": {}, "git": {"hung": False}}
    try:
        hit = scan(command, state)
    except ValueError:  # comilla sin cerrar: solo los comandos duros, el resto se permite
        text = prepass(command)
        m = HARD_FALLBACK.search(text)
        return text[m.start():m.start() + MAX_SHOWN] if m else None
    return shlex.join(hit)[:MAX_SHOWN] if hit else None


def deny(reason):
    payload = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": reason}}
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        tool_name = data.get("tool_name") if type(data) is dict else None
        if type(tool_name) is str and tool_name != "Bash":  # herramientas MCP: el matcher también las trae aquí
            if MCP_MERGE.search(tool_name):
                deny(f"⛔ merge-guard: Claude no mergea MRs (herramienta MCP {tool_name[:MAX_SHOWN]}); el Reviewer revisa y mergea.")
            return 0
        tool_input = data.get("tool_input") if type(data) is dict else None
        command = tool_input.get("command") if type(tool_input) is dict else None
        if type(command) is not str or not command.strip():
            return 0
        cwd = data.get("cwd")
        shown = decide(command, cwd if type(cwd) is str and cwd else os.getcwd())
        if shown:
            deny(f"⛔ merge-guard: Claude no mergea MRs; el Reviewer revisa y mergea. Comando: {shown}")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
