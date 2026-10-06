#!/usr/bin/env python3
"""merge-guard-selftest — behavioural tests for merge-guard.py (stdlib only).

Usage:
  python3 merge-guard-selftest.py [--guard PATH] [--only TEXT]

merge-guard.py is a PreToolUse hook (matcher Bash|mcp__.*merge.*): Claude never merges an MR/PR, the
Reviewer does. It reads stdin {"tool_name": ..., "tool_input": {"command": ...}, "cwd": ...} and either prints a deny
({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
"permissionDecisionReason": "... merge-guard ..."}}) or stays silent. Both end with exit 0: the hook
never fails a tool call by itself and never blocks on its own errors (fail-open).

Every case runs `python3 -B merge-guard.py` as a subprocess (HOME = a throwaway dir, no git config)
against throwaway repos made by `make_repo(tmp, branch)` (`git init -b <branch>` + one commit with
identity Test <test@example.com>) and prints `PASS|FAIL <group>/<case>[: why]`. Eight groups:

  1 hard denies          gh pr merge / glab mr merge|accept, with or without flags
  2 API                  merge endpoints with a non-GET verb are denied; GET and non-merge calls pass
  3 false positives      text that merely mentions a merge command, git plumbing, comments, heredocs
  4 evasions             wrappers, VAR=v, absolute paths, nested shells, substitutions, separators
  5 git                  `git merge <x>` / `git pull <remote> <branch>` (also with --rebase) /
                         `git rebase <ref>` / `git reset --hard|--soft|--keep|--merge <ref>` are denied on
                         main|master|develop|trunk (the current branch, or the one a leading `git checkout|
                         switch` / `cd` / `git -C` points at) and allowed elsewhere; sync forms stay allowed
                         on main (`<any-remote>/<same>`, `@{u}`, the same name, HEAD~N)
  6 fail-open            bad input, non-git cwd, unbalanced quote, detached HEAD, a hung `git`
  7 git push             auto-merge push options and `<src>:<protected>` refspecs are denied; the plain
                         pushes of the docs repos (`git push`, `git push origin main`) stay allowed
  8 MCP tool_name        MCP merge tools are denied by tool_name; any other non-Bash tool is allowed
                         silently; a missing/odd tool_name leaves the Bash path unchanged

The last line is `merge-guard-selftest: N/N`; exit code 1 when any case fails (2 on bad arguments).
The guard under test defaults to the merge-guard.py that sits next to this file; pass --guard to test an
installed copy. A missing guard is not special-cased: every case fails with "merge-guard.py not found".
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SLOW_GIT_LIMIT = 3.5  # seconds: the hook asks git with a 2 s timeout, so a 5 s `git` must cost ~2 s, not 5


def clean_env(home, path_first=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=home, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")
    if path_first:
        env["PATH"] = path_first + os.pathsep + env.get("PATH", "")
    return env


def make_repo(tmp, branch, name=None):
    """`git init -b <branch>` plus one commit (identity Test <test@example.com>); returns the path."""
    path = os.path.join(tmp, name or "repo-" + branch.replace("/", "-"))
    os.makedirs(path)
    env = clean_env(tmp)
    subprocess.run(["git", "init", "-q", "-b", branch, path], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", path, "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True, capture_output=True, env=env)
    return path


class Ctx:
    """The guard under test plus the throwaway world its cases run in."""

    def __init__(self, guard, tmp):
        self.guard, self.tmp = guard, tmp
        self.env = clean_env(tmp)
        self.plain = os.path.join(tmp, "plain")  # a directory that is not a git repo
        os.makedirs(self.plain)
        self.main = make_repo(tmp, "main")
        self.feat = make_repo(tmp, "feature/x")
        self.master = make_repo(tmp, "master")
        self.develop = make_repo(tmp, "develop")
        self.hotfix = make_repo(tmp, "main-hotfix")  # only the exact names are protected
        self.detached = make_repo(tmp, "main", name="repo-detached")
        subprocess.run(["git", "-C", self.detached, "checkout", "-q", "--detach"],
                       check=True, capture_output=True, env=self.env)
        self.slow_dir = os.path.join(tmp, "slow-bin")  # a `git` that hangs for 5 s
        os.makedirs(self.slow_dir)
        shim = os.path.join(self.slow_dir, "git")
        with open(shim, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nsleep 5\n")
        os.chmod(shim, 0o755)

    def run_raw(self, stdin_text, env=None):
        if not os.path.isfile(self.guard):
            return 2, "", "merge-guard.py not found"
        p = subprocess.run([sys.executable, "-B", self.guard], input=stdin_text, capture_output=True, text=True,
                           env=env or self.env, cwd=self.plain, timeout=30)
        return p.returncode, p.stdout.strip(), p.stderr.strip()

    def run(self, command, cwd=None, env=None):
        payload = {"tool_input": {"command": command}}
        if cwd is not None:
            payload["cwd"] = cwd
        return self.run_raw(json.dumps(payload), env)


def tail(err):
    return f" ({err.splitlines()[-1][:100]})" if err else ""


def expect_deny(res, mention=None):
    """exit 0 + hookSpecificOutput.permissionDecision == "deny" with a reason that names merge-guard."""
    rc, out, err = res
    if rc != 0:
        return f"exit {rc}, expected 0{tail(err)}"
    try:
        data = json.loads(out)
        hso = data.get("hookSpecificOutput")
        hso = hso if type(hso) is dict else {}
    except Exception:
        return f"expected a deny JSON, got: {out[:120] or '(no output)'}"
    if hso.get("permissionDecision") != "deny":
        return f"expected permissionDecision 'deny', got: {out[:140] or '(no output)'}"
    reason = hso.get("permissionDecisionReason") or ""
    if "merge-guard" not in reason:
        return f"deny reason lacks 'merge-guard': {reason[:120]!r}"
    if mention and mention not in reason:
        return f"deny reason does not quote the command {mention!r}: {reason[:160]!r}"
    return None


def expect_allow(res):
    """exit 0 and nothing on stdout."""
    rc, out, err = res
    if rc != 0:
        return f"exit {rc}, expected 0{tail(err)}"
    if out:
        return f"expected no output, got: {out[:160]}"
    return None


def q(path):
    return shlex.quote(path)


def build_groups(c):
    """[(group title, [(case name, thunk -> problem-or-None)])], with the repos of `c` already made."""

    def deny(name, command, cwd, mention=None):
        return name, lambda: expect_deny(c.run(command, cwd), mention)

    def allow(name, command, cwd):
        return name, lambda: expect_allow(c.run(command, cwd))

    def raw_allow(name, stdin_text):
        return name, lambda: expect_allow(c.run_raw(stdin_text))

    def slow_git():
        t0 = time.monotonic()
        res = c.run("git merge feat", c.main, clean_env(c.tmp, path_first=c.slow_dir))
        elapsed = time.monotonic() - t0
        problem = expect_allow(res)
        if problem:
            return f"{problem} (a hung git must never deny)"
        if elapsed > SLOW_GIT_LIMIT:
            return f"took {elapsed:.1f}s (limit {SLOW_GIT_LIMIT}s): a hung git must never wedge the hook"
        return None

    f, m = c.feat, c.main

    g1 = [  # hard denies: they decide by argv alone, in any repo
        deny("gh_pr_merge_12", "gh pr merge 12", f, mention="gh pr merge 12"),
        deny("gh_pr_merge_squash", "gh pr merge 12 --squash --delete-branch", f),
        deny("glab_mr_merge", "glab mr merge", f),
        deny("glab_mr_merge_5", "glab mr merge 5", f),
        deny("glab_mr_accept_5", "glab mr accept 5", f),
        deny("gh_pr_merge_auto", "gh pr merge --auto", f),
        deny("glab_mr_merge_when_pipeline_succeeds", "glab mr merge --when-pipeline-succeeds", f),
        ("no_cwd_still_denies", lambda: expect_deny(c.run_raw(json.dumps({"tool_input": {"command": "gh pr merge 12"}})))),
    ]

    api_pr = "repos/acme/app/pulls/3/merge"
    api_mr = "projects/7/merge_requests/5"
    host = "https://gitlab.example.com/api/v4/" + api_mr
    g2 = [
        deny("gh_api_put_pull_merge", f"gh api -X PUT {api_pr}", f),
        deny("gh_api_method_put_pull_merge", f"gh api --method PUT {api_pr} -f merge_method=squash", f),
        deny("gh_api_post_merges", "gh api -X POST repos/acme/app/merges -f base=main -f head=feat", f),
        deny("gh_api_graphql_merge_mutation",
             "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"X\"}) { clientMutationId } }'", f),
        deny("glab_api_put_mr_merge", f"glab api -X PUT {api_mr}/merge", f),
        deny("glab_api_put_merge_when_pipeline_succeeds", f"glab api --method PUT {api_mr}/merge_when_pipeline_succeeds", f),
        deny("curl_put_mr_merge", f'curl -X PUT -H "PRIVATE-TOKEN: x" {host}/merge', f),
        deny("curl_request_put_mr_merge", f"curl --request PUT {host}/merge", f),
        allow("gh_api_get_default", f"gh api {api_pr}", f),
        allow("gh_api_get_explicit", f"gh api -X GET {api_pr}", f),
        allow("gh_api_graphql_query_only", "gh api graphql -f query='query { viewer { login } }'", f),
        allow("glab_api_get_mr", f"glab api {api_mr}", f),
        allow("curl_get_explicit", "curl -X GET https://api.example.com/repos/acme/app/pulls/3/merge", f),
        allow("curl_put_unrelated_route", "curl -X PUT https://api.example.com/items/3", f),
        allow("gh_pr_view", "gh pr view 3", f),
        allow("gh_pr_checks", "gh pr checks 3", f),
        allow("gh_pr_diff", "gh pr diff 3", f),
        allow("glab_mr_create", "glab mr create --fill", f),
    ]

    g3 = [  # false positives: the words are there, the command is not
        allow("echo_quoted", 'echo "gh pr merge 12"', m),
        allow("echo_bare", "echo gh pr merge 3", m),
        allow("commit_message", 'git commit -m "docs: gh pr merge and glab mr merge are reserved for the Reviewer"', m),
        allow("grep_pattern", "grep -rn 'glab mr merge' docs/", m),
        allow("python_string", "python3 -c \"print('gh pr merge 3')\"", m),
        allow("git_merge_base", "git merge-base origin/main HEAD", m),
        allow("git_merge_base_is_ancestor", "git merge-base --is-ancestor origin/feat HEAD", m),
        allow("git_merge_file", "git merge-file a b c", m),
        allow("git_mergetool", "git mergetool", m),
        allow("git_log_merges", "git log --merges --oneline -5", m),
        allow("git_branch_merged", "git branch --merged", m),
        allow("glab_mr_merge_help", "glab mr merge --help", m),
        allow("glab_mr_merge_h", "glab mr merge -h", m),
        allow("gh_pr_merge_help", "gh pr merge --help", m),
        allow("gh_pr_merge_disable_auto", "gh pr merge --disable-auto 12", m),
        allow("comment_only", "# gh pr merge 3", m),
        allow("heredoc_quoted_body", "cat <<'EOF'\ngh pr merge 3\nEOF", m),
        allow("heredoc_to_file", "cat > notes.md <<EOF\nglab mr merge 5\nEOF", m),
        allow("git_push_feature_branch", "git push origin feature/x", m),
        allow("plain_commands", "ls -la && npm test", m),
    ]

    g4 = [  # evasions: still a merge command, so denied
        deny("var_assignment_abs_path_global_flag", "FOO=1 /usr/bin/gh -R o/r pr merge 3", f),
        deny("abs_path_glab", "/usr/local/bin/glab mr merge 5", f),
        deny("bash_c", 'bash -c "gh pr merge 3"', f),
        deny("sh_c_single_quotes", "sh -c 'glab mr merge 5'", f),
        deny("bash_c_second_statement", "bash -c 'echo hi; glab mr accept 5'", f),
        deny("eval", 'eval "gh pr merge 3"', f),
        deny("dollar_paren_substitution", 'echo "$(gh pr merge 3)"', f),
        deny("backticks", "echo `gh pr merge 3`", f),
        deny("comment_then_newline", "ls # c\ngh pr merge 3", f),
        deny("heredoc_then_real_command", "cat <<'EOF'\nnotes\nEOF\ngh pr merge 3", f),
        deny("if_then_fi", "if true; then gh pr merge 1; fi", f),
        deny("and_chain", "true && glab mr merge 5", f),
        deny("xargs", "echo 3 | xargs gh pr merge", f),
        deny("subshell", "(cd /tmp && gh pr merge 3)", f),
        deny("env_wrapper", "env GH_TOKEN=x gh pr merge 3", f),
        deny("command_wrapper", "command glab mr merge 5", f),
        deny("sudo_wrapper", "sudo gh pr merge 3", f),
        deny("quoted_subcommand", 'gh pr "merge" 3', f),
        deny("backslash_newline_continuation", "gh pr \\\nmerge 3", f),
        deny("help_in_a_comment_is_not_help", "gh pr merge 3 # see --help", f),
        deny("help_belongs_to_the_next_command", "gh pr merge 3; echo --help", f),
        deny("unbalanced_quote_with_hard_pattern", 'echo "oops; gh pr merge 3', f),
        deny("git_backslash_newline_merge_on_main", "git \\\nmerge x", m),
    ]

    g5 = [
        # on main: merging a feature branch into it is the Reviewer's job
        deny("main_merge_feat", "git merge feat", m),
        deny("main_merge_no_ff", 'git merge --no-ff feature/x -m "wave"', m),
        deny("main_pull_origin_feat", "git pull origin feat", m),
        deny("main_pull_origin_feature_x", "git pull origin feature/x", m),
        # ...while the sync forms stay allowed: they only bring main up to its own upstream
        allow("main_merge_origin_main", "git merge origin/main", m),
        allow("main_merge_ff_only_origin_main", "git merge --ff-only origin/main", m),
        allow("main_merge_upstream", "git merge @{u}", m),
        allow("main_merge_abort", "git merge --abort", m),
        allow("main_merge_continue", "git merge --continue", m),
        allow("main_merge_quit", "git merge --quit", m),
        allow("main_pull_bare", "git pull", m),
        allow("main_pull_origin_main", "git pull origin main", m),
        deny("main_pull_rebase_origin_feat", "git pull --rebase origin feat", m),
        deny("main_pull_r_origin_feature_x", "git pull -r origin feature/x", m),
        deny("main_pull_rebase_merges_origin_feat", "git pull --rebase=merges origin feat", m),
        allow("main_pull_rebase_bare", "git pull --rebase", m),
        allow("main_pull_rebase_origin_main", "git pull --rebase origin main", m),
        allow("main_pull_rebase_upstream_main", "git pull --rebase upstream main", m),
        # fork sync: <any-remote>/<same-branch> is a sync form, any other branch of it is not
        allow("main_merge_upstream_main", "git merge upstream/main", m),
        allow("main_merge_ff_only_upstream_main", "git merge --ff-only upstream/main", m),
        deny("main_merge_upstream_feat", "git merge upstream/feat", m),
        deny("main_merge_origin_feature_x", "git merge origin/feature/x", m),
        allow("main_pull_upstream_main", "git pull upstream main", m),
        deny("main_pull_upstream_feat", "git pull upstream feat", m),
        # rebase onto another ref rewrites main on top of it
        deny("main_rebase_feat", "git rebase feat", m),
        deny("main_rebase_origin_feature_x", "git rebase origin/feature/x", m),
        deny("main_rebase_onto_feat", "git rebase --onto feat main", m),
        deny("main_rebase_interactive_feat", "git rebase -i feat", m),
        allow("main_rebase_bare", "git rebase", m),
        allow("main_rebase_origin_main", "git rebase origin/main", m),
        allow("main_rebase_upstream_main", "git rebase upstream/main", m),
        allow("main_rebase_at_upstream", "git rebase @{u}", m),
        allow("main_rebase_abort", "git rebase --abort", m),
        allow("main_rebase_continue", "git rebase --continue", m),
        allow("main_rebase_skip", "git rebase --skip", m),
        allow("main_rebase_interactive_head", "git rebase -i HEAD~3", m),
        allow("main_rebase_onto_origin_main", "git rebase --onto origin/main HEAD~2", m),
        allow("main_rebase_feature_branch_given", "git rebase origin/main feature/x", m),
        allow("feature_rebase_main", "git rebase main", f),
        allow("feature_rebase_origin_feat", "git rebase origin/feat", f),
        deny("feature_rebase_feat_onto_main", "git rebase feat main", f),
        # reset moves the protected branch to another ref
        deny("main_reset_hard_feat", "git reset --hard feat", m),
        deny("main_reset_hard_origin_feature_x", "git reset --hard origin/feature/x", m),
        deny("main_reset_soft_feat", "git reset --soft feat", m),
        deny("main_reset_keep_feat", "git reset --keep feat", m),
        deny("main_reset_hard_reflog", "git reset --hard HEAD@{1}", m),
        allow("main_reset_hard_bare", "git reset --hard", m),
        allow("main_reset_hard_head", "git reset --hard HEAD", m),
        allow("main_reset_hard_head_tilde", "git reset --hard HEAD~1", m),
        allow("main_reset_hard_origin_main", "git reset --hard origin/main", m),
        allow("main_reset_hard_upstream_main", "git reset --hard upstream/main", m),
        allow("main_reset_hard_at_upstream", "git reset --hard @{u}", m),
        allow("main_reset_soft_head_tilde", "git reset --soft HEAD~1", m),
        allow("main_reset_unstage_path", "git reset HEAD notes.md", m),
        allow("feature_reset_hard_feat", "git reset --hard feat", f),
        allow("feature_reset_hard_origin_feature_x", "git reset --hard origin/feature/x", f),
        deny("master_rebase_feat", "git rebase feat", c.master),
        deny("develop_reset_hard_feat", "git reset --hard feat", c.develop),
        allow("main_hotfix_rebase_feat", "git rebase feat", c.hotfix),
        allow("main_hotfix_reset_hard_feat", "git reset --hard feat", c.hotfix),
        allow("main_push_feature", "git push origin feature/x", m),
        # the repo the command acts on is the one it points at, not the one the shell happens to be in
        deny("dash_C_main_from_elsewhere", f"git -C {q(m)} merge x", c.plain),
        deny("cd_main_then_merge_from_feature", f"cd {q(m)} && git merge x", f),
        allow("dash_C_feature_from_main", f"git -C {q(f)} merge x", m),
        allow("cd_feature_then_merge_from_main", f"cd {q(f)} && git merge x", m),
        # on a feature branch anything goes, but a checkout of main first makes it main
        allow("feature_merge_origin_main", "git merge origin/main", f),
        allow("feature_merge_main", "git merge main", f),
        allow("feature_merge_feat", "git merge feat", f),
        allow("feature_pull_origin_main", "git pull origin main", f),
        allow("feature_push_feature", "git push origin feature/x", f),
        deny("feature_checkout_main_then_merge", "git checkout main && git merge feat", f),
        deny("feature_switch_main_then_merge", "git switch main && git merge feat", f),
        allow("main_checkout_feature_then_merge", "git checkout feature/x && git merge x", m),
        # protected names are exact: master, develop, trunk, main
        deny("master_merge_feat", "git merge feat", c.master),
        allow("master_merge_origin_master", "git merge origin/master", c.master),
        deny("develop_merge_feat", "git merge feat", c.develop),
        allow("main_hotfix_merge_feat", "git merge feat", c.hotfix),
    ]

    g6 = [  # fail-open: whatever the guard cannot judge is allowed
        raw_allow("bad_json", "{not json"),
        raw_allow("empty_stdin", ""),
        raw_allow("json_not_an_object", "[1, 2]"),
        raw_allow("no_tool_input", json.dumps({"cwd": m})),
        raw_allow("no_command", json.dumps({"tool_input": {}, "cwd": m})),
        raw_allow("command_not_a_string", json.dumps({"tool_input": {"command": 123}, "cwd": m})),
        allow("empty_command", "", m),
        allow("non_git_cwd_merge", "git merge feat", c.plain),
        allow("non_git_cwd_pull", "git pull origin feat", c.plain),
        allow("cwd_does_not_exist", "git merge feat", os.path.join(c.tmp, "does-not-exist")),
        allow("unbalanced_quote_plain", 'echo "unterminated', m),
        allow("unbalanced_quote_git_merge", 'git merge "feat', m),
        allow("detached_head_merge", "git merge feat", c.detached),
        allow("detached_head_pull", "git pull origin feat", c.detached),
        allow("detached_head_rebase", "git rebase feat", c.detached),
        allow("detached_head_reset_hard", "git reset --hard feat", c.detached),
        allow("non_git_cwd_rebase", "git rebase feat", c.plain),
        ("slow_git_still_allows_within_limit", slow_git),
    ]

    g7 = [  # git push: only auto-merge options and cross-ref refspecs into a protected name are denied
        allow("main_push_bare", "git push", m),
        allow("main_push_origin_main", "git push origin main", m),
        allow("main_push_origin_main_main", "git push origin main:main", m),
        allow("main_push_full_refs_same", "git push origin refs/heads/main:refs/heads/main", m),
        allow("main_push_force_same", "git push origin +main:main", m),
        allow("main_push_set_upstream_feature", "git push -u origin feature/x", m),
        allow("feature_push_set_upstream", "git push -u origin feature/x", f),
        allow("feature_push_force_with_lease", "git push --force-with-lease origin feature/x", f),
        allow("feature_push_force_with_lease_ref", "git push --force-with-lease=feature/x:abc123 origin feature/x", f),
        allow("feature_push_head", "git push origin HEAD", f),
        allow("feature_push_src_dst_other", "git push origin feature/x:feature/y", f),
        allow("push_to_nonprotected_dst", "git push origin main:feature/x", m),
        allow("push_option_mr_create", "git push -o merge_request.create origin feature/x", f),
        allow("push_option_ci_skip", "git push --push-option=ci.skip origin feature/x", f),
        allow("push_option_mr_target", "git push -o merge_request.target=main origin feature/x", f),
        allow("push_text_only_echo", 'echo "git push origin HEAD:main"', f),
        allow("push_text_only_commit_message", 'git commit -m "docs: never git push origin HEAD:main"', f),
        allow("push_non_git_cwd_plain", "git push origin main", c.plain),
        deny("push_option_when_pipeline_succeeds",
             "git push -o merge_request.merge_when_pipeline_succeeds origin feature/x", f),
        deny("push_option_auto_merge", "git push -o merge_request.auto_merge origin feature/x", f),
        deny("push_option_bare_auto_merge", "git push -o auto_merge origin feature/x", f),
        deny("push_option_long_equals", "git push --push-option=merge_request.merge_when_pipeline_succeeds origin feature/x", f),
        deny("push_option_long_separate", "git push --push-option merge_request.auto_merge origin feature/x", f),
        deny("push_option_glued_short", "git push -omerge_request.merge_when_pipeline_succeeds origin feature/x", f),
        deny("push_option_after_refspec", "git push origin feature/x -o merge_request.auto_merge", f),
        deny("push_option_from_main", "git push -o merge_request.auto_merge", m),
        deny("push_head_main", "git push origin HEAD:main", f, mention="git push origin HEAD:main"),
        deny("push_head_main_from_main", "git push origin HEAD:main", m),
        deny("push_feature_main", "git push origin feature/x:main", f),
        deny("push_force_plus_full_ref", "git push origin +feat:refs/heads/main", f),
        deny("push_head_full_ref_master", "git push origin HEAD:refs/heads/master", f),
        deny("push_head_develop", "git push origin HEAD:develop", f),
        deny("push_head_trunk", "git push origin HEAD:trunk", f),
        deny("push_set_upstream_head_main", "git push -u origin HEAD:main", f),
        deny("push_force_feat_main", "git push --force origin feat:main", f),
        deny("push_delete_by_refspec", "git push origin :main", f),
        deny("push_second_refspec", "git push origin feature/x HEAD:main", f),
        deny("push_repo_flag", "git push --repo origin HEAD:main", f),
        deny("push_dash_C_head_main", f"git -C {q(f)} push origin HEAD:main", c.plain),
        deny("push_after_commit_chain", 'git commit -am x && git push origin HEAD:main', f),
        deny("push_inside_bash_c", 'bash -c "git push origin HEAD:main"', f),
        deny("push_non_git_cwd_head_main", "git push origin HEAD:main", c.plain),
    ]

    def mcp(tool_name, tool_input=None, **extra):
        payload = dict(extra, tool_name=tool_name)
        if tool_input is not None:
            payload["tool_input"] = tool_input
        return json.dumps(payload)

    def mcp_deny(name, tool_name):
        def thunk():
            res = c.run_raw(mcp(tool_name, {}, cwd=f))
            problem = expect_deny(res, mention=f"herramienta MCP {tool_name}")
            if problem:
                return problem
            reason = json.loads(res[1])["hookSpecificOutput"]["permissionDecisionReason"]
            want = f"\u26d4 merge-guard: Claude no mergea MRs (herramienta MCP {tool_name}); el Reviewer revisa y mergea."
            return None if reason == want else f"reason is {reason!r}, expected {want!r}"
        return name, thunk

    def mcp_allow(name, tool_name, tool_input=None):
        return raw_allow(name, mcp(tool_name, tool_input if tool_input is not None else {}, cwd=f))

    def bash_deny(name, stdin_text):
        return name, lambda: expect_deny(c.run_raw(stdin_text))

    merge_cmd = {"command": "gh pr merge 12"}
    g8 = [
        mcp_deny("gitlab_merge_merge_request", "mcp__gitlab__merge_merge_request"),
        mcp_deny("plugin_gitlab_merge_merge_request", "mcp__plugin_gitlab_gitlab__merge_merge_request"),
        mcp_deny("github_merge_pull_request", "mcp__github__merge_pull_request"),
        mcp_deny("accept_merge_request", "mcp__gitlab__accept_merge_request"),
        mcp_deny("merge_mr", "mcp__forge__merge_mr"),
        mcp_deny("merge_pr", "mcp__forge__merge_pr"),
        mcp_deny("case_insensitive", "mcp__GitLab__Merge_Merge_Request"),
        ("mcp_merge_without_tool_input", lambda: expect_deny(c.run_raw(json.dumps({"tool_name": "mcp__gitlab__merge_merge_request"})))),
        mcp_allow("gitlab_get_merge_request", "mcp__gitlab__get_merge_request"),
        mcp_allow("gitlab_list_merge_requests", "mcp__gitlab__list_merge_requests"),
        mcp_allow("gitlab_create_merge_request", "mcp__gitlab__create_merge_request"),
        mcp_allow("gitlab_get_merge_request_diffs", "mcp__gitlab__get_merge_request_diffs"),
        mcp_allow("github_create_pull_request", "mcp__github__create_pull_request"),
        mcp_allow("github_get_pull_request", "mcp__github__get_pull_request"),
        mcp_allow("non_mcp_tool_named_like_merge", "merge_merge_request"),
        mcp_allow("read_tool", "Read", {"file_path": "/tmp/x"}),
        mcp_allow("edit_tool", "Edit", {"file_path": "/tmp/x", "old_string": "a", "new_string": "b"}),
        mcp_allow("non_bash_tool_with_merge_command", "Task", merge_cmd),
        raw_allow("non_bash_empty_name", mcp("", merge_cmd, cwd=f)),
        # a missing / odd tool_name leaves the Bash path exactly as it was
        bash_deny("no_tool_name_bash_path", json.dumps({"tool_input": merge_cmd, "cwd": f})),
        bash_deny("tool_name_bash", json.dumps({"tool_name": "Bash", "tool_input": merge_cmd, "cwd": f})),
        bash_deny("tool_name_null_bash_path", json.dumps({"tool_name": None, "tool_input": merge_cmd, "cwd": f})),
        bash_deny("tool_name_not_a_string_bash_path", json.dumps({"tool_name": 7, "tool_input": merge_cmd, "cwd": f})),
        bash_deny("tool_name_bash_git_merge_on_main",
                  json.dumps({"tool_name": "Bash", "tool_input": {"command": "git merge feat"}, "cwd": m})),
        raw_allow("no_tool_name_benign", json.dumps({"tool_input": {"command": "ls -la"}, "cwd": f})),
        raw_allow("tool_name_bash_benign", json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "cwd": f})),
    ]

    return [("1 hard denies", g1), ("2 API", g2), ("3 false positives", g3),
            ("4 evasions", g4), ("5 git on main vs feature", g5), ("6 fail-open", g6),
            ("7 git push", g7), ("8 MCP tool_name", g8)]


def main():
    guard = os.path.join(HERE, "merge-guard.py")
    only = None
    argv = sys.argv[1:]
    try:
        if "--guard" in argv:
            guard = os.path.abspath(os.path.expanduser(argv[argv.index("--guard") + 1]))
        if "--only" in argv:
            only = argv[argv.index("--only") + 1]
    except IndexError:
        print("usage: merge-guard-selftest.py [--guard PATH] [--only TEXT]")
        return 2
    if not os.path.isfile(guard):
        print(f"NOTE merge-guard.py not found: {guard} (every case will fail)")

    tmp = os.path.realpath(tempfile.mkdtemp(prefix="merge-guard-selftest-"))
    total = failed = 0
    try:
        ctx = Ctx(guard, tmp)
        for title, cases in build_groups(ctx):
            shown = False
            for name, thunk in cases:
                label = f"g{title.split()[0]}/{name}"
                if only and only not in label:
                    continue
                if not shown:
                    print(f"== group {title}")
                    shown = True
                total += 1
                try:
                    problem = thunk()
                except Exception as exc:  # a broken harness is a failure, not a crash
                    problem = f"harness error: {exc!r}"
                if problem:
                    failed += 1
                    print(f"FAIL {label}: {problem}")
                else:
                    print(f"PASS {label}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"merge-guard-selftest: {total - failed}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
