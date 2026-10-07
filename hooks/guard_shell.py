#!/usr/bin/env python3
"""PreToolUse(Bash): shell command safety, configured by project.json.

Git (inside the workspace):
- Pushes: deny pushing to or deleting a protected branch (git.protectedBranches + the environment branches; explicit
  refspec, HEAD, or a bare push while on or tracking one) and --all/--mirror; ask before force pushes. --dry-run is fine.
- Staging/commits: deny `git add`/`git commit` of env files, private keys, or content that looks like a credential;
  ask before staging data files (data.dataFiles); deny --no-verify.
- Commit messages (commits.*): style "ticket" (subject starts with the branch's ticket, `PAY-12: ...`; branches
  without one use the branch name), "conventional" (`feat(scope): ...`) or "none"; subject length; optionally no
  AI mentions or Co-authored-by / "Generated with" trailers.
- Destructive local commands (reset --hard, clean -f, checkout -- ., branch -D, stash drop): ask.

Real systems (ask first, anywhere):
- Cloud and infra CLIs that change things: aws (except read-only identity/config/help), kubectl apply/delete/...,
  terraform/tofu apply/destroy, helm install/upgrade/uninstall, SAM/Serverless invokes.
- Database shells (psql, mysql, mongosh, redis-cli, ...).
- HTTP writes (curl/wget with a body or non-GET method) to non-localhost URLs.
- The project's own rules (project.json realSystems: command patterns such as "npm run seed*", optionally per repo).
"""
import os
import re
import sys

import fnmatch

from _hooklib import (
    branch_ticket_key, classify_path, commands, config, current_branch, emit, find_secrets, git_calls, git_out,
    in_workspace, program, protected_branches, read_input, repo_of, upstream_branch,
)

PUSH_OPTS_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
FORCE_LONG = re.compile(r"^--(force|force-with-lease(=.*)?|force-if-includes)$")
MAX_SCAN_BYTES = 1_000_000
PR_HINT = "Push a feature branch and open a PR instead."


def short_flag_has(arg, letters):
    return arg.startswith("-") and not arg.startswith("--") and any(c in arg[1:] for c in letters)


def strip_ref(ref):
    for prefix in ("refs/heads/", "refs/remotes/origin/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    return ref


# --- push ---------------------------------------------------------------------

def check_push(call):
    args = call.args
    if "--dry-run" in args or "-n" in args:
        return []
    decisions = []
    positional, i = [], 0
    while i < len(args):
        if args[i] in PUSH_OPTS_WITH_VALUE:
            i += 2
            continue
        if not args[i].startswith("-"):
            positional.append(args[i])
        i += 1
    refspecs = positional[1:]
    deleting = "--delete" in args or any(short_flag_has(a, "d") for a in args)

    if "--all" in args or "--mirror" in args:
        decisions.append(("deny", "push-all", "Pushing all branches (--all/--mirror) would include protected branches."))

    for spec in refspecs:
        dest = strip_ref(spec.lstrip("+").split(":")[-1])
        if dest in ("HEAD", "@"):
            dest = current_branch(call.dir)
            if not dest:
                decisions.append(("ask", "push-unknown-target", "Couldn't resolve HEAD for this push. Check it isn't a protected branch."))
                continue
        if dest in protected_branches():
            action = "delete" if deleting or spec.startswith(":") else "push to"
            protected = ", ".join(sorted(protected_branches()))
            decisions.append(("deny", "push-protected", f"Blocked: this would {action} protected branch '{dest}' (protected: {protected}). {PR_HINT}"))

    if not refspecs and "--tags" not in args and not deleting:
        branch = current_branch(call.dir)
        if not branch:
            decisions.append(("ask", "push-unknown-target", "Couldn't tell which branch this push targets. Check it isn't a protected branch."))
        else:
            hit = sorted(b for b in {branch, upstream_branch(call.dir) or branch} if b in protected_branches())
            if hit:
                decisions.append(("deny", "push-protected", f"Blocked: `git push` from '{branch}' in {os.path.basename(call.dir)} would push to protected branch '{hit[0]}'. {PR_HINT}"))

    if any(FORCE_LONG.match(a) or short_flag_has(a, "f") for a in args) or any(r.startswith("+") for r in refspecs):
        decisions.append(("ask", "push-force", "Force push detected. Confirm this is intended."))
    return decisions


# --- add / commit ---------------------------------------------------------------

def parse_status_z(output):
    """Paths from `git status --porcelain -z`, skipping deletions."""
    paths, entries, i = [], output.split("\0"), 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if "R" in xy or "C" in xy:
            i += 1  # the original path follows a rename/copy
        if "D" not in xy:
            paths.append(path)
    return paths


def scan_file(root, rel):
    path = os.path.join(root, rel)
    try:
        if os.path.getsize(path) > MAX_SCAN_BYTES:
            return []
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    return [] if b"\0" in data[:8192] else find_secrets(data.decode("utf-8", errors="ignore"))


def check_files(paths, root):
    decisions = []
    for rel in paths:
        kind = classify_path(rel)
        if kind:
            decisions.append((kind[0], "stage-env-or-key" if kind[0] == "deny" else "stage-data-file", f"'{rel}' is {kind[1]}."))
            if kind[0] == "deny":
                continue
        for label, _ in scan_file(root, rel):
            decisions.append(("deny", "stage-secret", f"'{rel}' contains what looks like a {label}. Use an env var or the project's secret store instead."))
    return decisions


def check_add(call):
    root = (git_out(call.dir, "rev-parse", "--show-toplevel") or "").strip()
    if not root:
        return []
    pathspecs, all_mode, update_only, after_dashdash = [], False, False, False
    for a in call.args:
        if a == "--":
            after_dashdash = True
        elif not after_dashdash and a in ("-A", "--all", "--no-ignore-removal"):
            all_mode = True
        elif not after_dashdash and a in ("-u", "--update"):
            update_only = True
        elif after_dashdash or not a.startswith("-"):
            pathspecs.append(a)
    status = ["status", "--porcelain", "-z", "--untracked-files=" + ("no" if update_only else "all")]
    if all_mode or update_only or any(p in (".", ":/", "*") for p in pathspecs):
        if pathspecs and not all_mode:
            status += ["--"] + pathspecs
    elif pathspecs:
        status += ["--"] + pathspecs
    else:
        return []
    candidates = parse_status_z(git_out(call.dir, *status) or "")
    # Explicit paths (e.g. `git add -f ignored.env`) are checked even if status doesn't list them.
    for p in pathspecs:
        if p not in (".", ":/", "*") and not any(c.endswith(p) for c in candidates) and classify_path(p):
            candidates.append(p)
    return check_files(candidates, root)


def added_lines(diff):
    return "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))


def check_commit(call):
    decisions, commit_all, skip = [], False, False
    for a in call.args:
        if skip:
            skip = False
            continue
        if a in ("-m", "--message", "-F", "--file", "-C", "-c", "--reuse-message", "--reedit-message",
                 "--author", "--date", "--fixup", "--squash", "-t", "--template", "--trailer"):
            skip = True
            continue
        cluster = re.match(r"^-[a-zA-Z]+$", a)
        if a == "--no-verify" or (cluster and "n" in a):
            decisions.append(("deny", "commit-no-verify", "`git commit --no-verify` skips the repo's commit hooks; fix what they report instead."))
        if a == "--all" or (cluster and "a" in a):
            commit_all = True
        if cluster and a[-1] in "mFCct":  # e.g. -am "message": the value follows
            skip = True
    if not git_out(call.dir, "rev-parse", "--show-toplevel"):
        return decisions
    names = (git_out(call.dir, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z") or "").split("\0")
    diff = git_out(call.dir, "diff", "--cached", "-U0", "--no-color", "--diff-filter=ACMR", timeout=20) or ""
    if commit_all:
        names += (git_out(call.dir, "diff", "--name-only", "--diff-filter=ACMR", "-z") or "").split("\0")
        diff += git_out(call.dir, "diff", "-U0", "--no-color", "--diff-filter=ACMR", timeout=20) or ""
    for name in filter(None, names):
        kind = classify_path(name)
        if kind:
            decisions.append((kind[0], "commit-env-or-key" if kind[0] == "deny" else "commit-data-file", f"The commit includes '{name}', which is {kind[1]}."))
    for label, _ in find_secrets(added_lines(diff)):
        decisions.append(("deny", "commit-secret", f"The staged changes contain what looks like a {label}. Remove it and use an env var or the project's secret store instead."))
    return decisions


# --- commit messages -------------------------------------------------------------

FORBIDDEN = re.compile(r"co-authored-by|anthropic|claude|generated with|\U0001F916", re.I)
FORBIDDEN_AI = re.compile(r"\bAI\b")
CONVENTIONAL = re.compile(r"^(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)(\([^)]+\))?!?: \S")


def subject_prefix(branch):
    """'PAY-12' for PAY-12 / PAY-12-qa / PAY-12-device-filter; else the branch name."""
    return branch_ticket_key(branch) or branch


def messages(call):
    """Return the commit message parts given with -m/--message/-F."""
    msgs, a, i = [], call.args, 0
    while i < len(a):
        arg = a[i]
        takes_next = arg in ("-m", "--message") or re.match(r"^-[a-zA-Z]+m$", arg)
        if takes_next:
            if i + 1 < len(a):
                msgs.append(a[i + 1])
            i += 2
            continue
        if arg.startswith("--message="):
            msgs.append(arg.split("=", 1)[1])
        elif arg in ("-F", "--file") and i + 1 < len(a):
            path = os.path.join(call.dir, a[i + 1])
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    msgs.append(f.read())
            i += 2
            continue
        i += 1
    return [unwrap_heredoc(m) for m in msgs]


def unwrap_heredoc(msg):
    """`$(cat <<'EOF' ... EOF)` -> the heredoc body."""
    if not msg.lstrip().startswith("$(cat <<"):
        return msg
    lines = msg.splitlines()[1:]
    while lines and lines[-1].strip() in (")", "EOF", ""):
        lines.pop()
    return "\n".join(lines)

def check_commit_message(call):
    msgs = messages(call)
    if not msgs:
        return []  # editor, --amend --no-edit, etc.
    rules = config()["commits"]
    decisions, text = [], "\n".join(msgs)
    if rules.get("forbidAiMentions") and (FORBIDDEN.search(text) or FORBIDDEN_AI.search(text)):
        decisions.append(("deny", "commit-message-ai", "Commit message must not mention Claude/Anthropic/AI or include Co-authored-by/'Generated with' trailers (project.json commits.forbidAiMentions). Rewrite the message."))
    subject = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not subject or "$(" in subject:
        return decisions
    if rules["style"] == "ticket":
        branch = current_branch(call.dir)
        prefix = subject_prefix(branch) if branch else ""
        if prefix and not subject.startswith(f"{prefix}: "):
            decisions.append(("deny", "commit-message-prefix", f"Commit subject must start with '{prefix}: ' (the branch's ticket, also on its environment branches). Got: '{subject}'"))
    elif rules["style"] == "conventional" and not CONVENTIONAL.match(subject):
        decisions.append(("deny", "commit-message-prefix", f"Commit subject must be a conventional commit ('feat(scope): ...', 'fix: ...'). Got: '{subject}'"))
    limit = int(rules.get("maxSubjectLength") or 0)
    if limit and len(subject) > limit:
        decisions.append(("deny", "commit-message-length", f"Commit subject is {len(subject)} chars; keep it at {limit} or fewer."))
    return decisions


# --- destructive local commands ------------------------------------------------------

def destructive(call):
    a = call.args
    if call.sub == "reset":
        return "--hard" in a
    if call.sub == "clean":
        return "--force" in a or any(short_flag_has(x, "f") for x in a)
    if call.sub == "checkout":
        return "--" in a or "." in a
    if call.sub == "restore":
        return not ("--staged" in a and "--worktree" not in a and "-W" not in a)
    if call.sub == "branch":
        return "-D" in a or ("--delete" in a and "--force" in a) or any(short_flag_has(x, "D") for x in a)
    if call.sub == "stash":
        return bool(a) and a[0] in ("drop", "clear")
    return False


def evaluate(hook):
    decisions, calls = [], list(git_calls(hook.command, hook.cwd))
    for call in calls:
        if not (in_workspace(call.dir) or in_workspace(hook.cwd)):
            continue
        if call.sub == "push":
            decisions += check_push(call)
        elif call.sub == "add":
            decisions += check_add(call)
        elif call.sub == "commit":
            decisions += check_commit(call) + check_commit_message(call)
        if destructive(call):
            decisions.append(("ask", "git-destructive", "Destructive git command (may discard uncommitted work). Confirm first."))
    # A push hidden in a form we can't parse (eval, sh -c, xargs...).
    if not calls and re.search(r"\bgit\b[^\n]*\bpush\b", hook.command) and in_workspace(hook.cwd):
        decisions.append(("ask", "push-unparsed", "This command runs `git push` in a form the guard couldn't parse. Check it doesn't push a protected branch."))
    return decisions


# --- real systems ----------------------------------------------------------------------

DB_SHELLS = {"psql", "mysql", "mariadb", "sqlcmd", "sqlplus", "mongosh", "mongo", "mongoexport", "mongoimport",
             "mongodump", "mongorestore", "redis-cli", "cqlsh"}
HTTP_TOOLS = {"curl", "wget", "http", "https"}
AWS_VALUE_OPTS = {"--profile", "--region", "--output", "--endpoint-url", "--query", "--color",
                  "--cli-read-timeout", "--cli-connect-timeout", "--ca-bundle"}
AWS_SAFE = [["--version"], ["help"], ["sts", "get-caller-identity"], ["configure", "list"], ["configure", "list-profiles"]]
KUBECTL_WRITES = {"apply", "create", "delete", "edit", "patch", "replace", "scale", "rollout", "drain", "cordon",
                  "exec", "set", "label", "annotate"}
LOCAL_URL = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(:\d+)?(/|$)", re.I)


def builtin_real_systems(prog, args):
    if prog == "aws":
        positional, skip = [], False
        for a in args:
            if skip:
                skip = False
            elif a in AWS_VALUE_OPTS:
                skip = True
            elif not a.startswith("--") or a == "--version":
                positional.append(a)
        if not positional or "help" in positional or any(positional[:len(s)] == s for s in AWS_SAFE):
            return []
        return [("ask", "aws-cli", f"`aws {' '.join(positional[:2])}` talks to a real AWS account.")]
    if prog in DB_SHELLS:
        return [("ask", "db-shell", f"`{prog}` connects to a real database.")]
    if prog == "kubectl" and any(a in KUBECTL_WRITES for a in args[:3]):
        return [("ask", "kubectl-write", "This changes a Kubernetes cluster.")]
    if prog in ("terraform", "tofu") and any(a in ("apply", "destroy", "import") for a in args[:2]):
        return [("ask", "terraform-apply", "This changes real infrastructure.")]
    if prog == "helm" and args[:1] and args[0] in ("install", "upgrade", "uninstall", "rollback", "delete"):
        return [("ask", "helm-write", "This changes a Kubernetes release.")]
    if (prog == "sam" and args[:2] == ["local", "invoke"]) or (prog in ("serverless", "sls") and "invoke" in args):
        return [("ask", "lambda-invoke", "This invokes a Lambda function.")]
    if prog in HTTP_TOOLS:
        urls = [a for a in args if re.match(r"^https?://", a, re.I)]
        external = [u for u in urls if not LOCAL_URL.match(u)]
        method = None
        for i, a in enumerate(args[:-1]):
            if a in ("-X", "--request"):  # case-sensitive: -x is curl's proxy flag
                method = args[i + 1].upper()
        writes = method not in (None, "GET", "HEAD", "OPTIONS") or any(
            a in ("-d", "-F", "-T")  # curl: data, form, upload (-f is --fail, -D dumps headers)
            or a in ("--data", "--data-raw", "--data-binary", "--data-urlencode", "--json", "--form",
                     "--upload-file", "--post-data", "--post-file")
            or a.startswith(("--data=", "--json=", "--form=", "--post-data="))
            for a in args
        )
        if external and writes:
            return [("ask", "external-http-write", f"This sends data to an external service ({external[0].split('?')[0]}).")]
    return []


def project_real_systems(words, here):
    """project.json realSystems: {"command": "npm run seed*", "repo": "api" (optional), "reason": "..."}."""
    line = " ".join(words)
    repo = repo_of(here)[0]
    return [("ask", "project-real-system", rule["reason"]) for rule in config()["realSystems"]
            if fnmatch.fnmatchcase(line, rule["command"]) and rule.get("repo") in (None, repo)]


def real_systems(hook):
    decisions = []
    for words, here in commands(hook.command, hook.cwd):
        decisions += builtin_real_systems(program(words[0]), words[1:])
        if in_workspace(here):
            decisions += project_real_systems(words, here)
    return decisions


def main():
    hook = read_input()
    if not hook.command:
        return
    decisions = real_systems(hook)
    if "git" in hook.command:
        try:
            decisions += evaluate(hook)
        except Exception as exc:  # a guard bug shouldn't silently wave a push through
            print(f"guard_shell error: {exc!r}", file=sys.stderr)
            if re.search(r"\bpush\b", hook.command):
                decisions.append(("ask", "guard-error", f"The git guard hit an error ({type(exc).__name__}). Check this command by hand."))
    emit(decisions)


if __name__ == "__main__":
    main()
