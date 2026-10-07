#!/usr/bin/env python3
"""The `sdlc` command: the local, read-only side of the ai-sdlc. Works from any folder (via the launcher).

    sdlc init [--write]              draft project.json (and PROJECT.md) from the repos in this workspace
    sdlc validate                    check project.json and workflow.json
    sdlc status [TICKET]             every ticket (or one): stage, approvals, test cases, PRs
    sdlc dashboard                   every ticket as one page (.sdlc/tickets/dashboard.html)
    sdlc done TICKET [--yes]         list (then remove) a finished ticket's local files
    sdlc gates enable|request|sync|status ...   a ticket's approval gates (hooks/gates.py)
    sdlc jira fetch|comments|check ...          read Jira (posting stays `jira.py comment`, always asked)
    sdlc targets <repo> <branch> [target ...]   how a branch merges into each environment branch
    sdlc check [--tests]             is this machine ready (tools, tokens, link, hooks, version)?
    sdlc ci                          the CI checks, locally: tests, config, version, docs, lint, syntax
    sdlc docs [--check]              refresh the generated reference tables in docs/ (or check they're current)
    sdlc update [--pull]             fetch ai-sdlc, show new CHANGELOG entries; --pull fast-forwards to them
    sdlc claude [args]               start Claude Code in the workspace root (where hooks and skills load)
    sdlc setup <folder> --from <url>  new machine or project: clone everything and install (handled by the launcher)

Outward steps (PRs, review comments, tracker comments, pushes) are not here on purpose: they stay visible commands
that the guard hooks and permission prompts see.
"""
import os
import re
import shutil
import subprocess
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS)  # ai-sdlc (= <workspace>/.claude)
PY = sys.executable

# command -> (script, fixed args, allowed first args or None for any)
PASS = {
    "init": ("scripts/init_project.py", [], None),
    "dashboard": ("scripts/tickets.py", ["dashboard"], None),
    "done": ("scripts/tickets.py", ["clean"], None),
    "gates": ("hooks/gates.py", [], {"enable", "request", "sync", "status", "validate"}),
    "jira": ("scripts/jira.py", [], {"fetch", "comments", "check"}),
    "targets": ("scripts/check_targets.py", [], None),
    "check": ("scripts/install.py", ["check"], None),
    "docs": ("scripts/docs.py", [], None),
}


def run(args, cwd=ROOT):
    return subprocess.run(args, cwd=cwd).returncode


def git(*args):
    p = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
    return p.returncode, p.stdout


def status(args):
    if args:
        return run([PY, os.path.join(SCRIPTS, "tickets.py"), "status", *args])
    return run([PY, os.path.join(SCRIPTS, "tickets.py"), "overview"])


def validate(_args):
    """project.json (through the hooks' own loader) and workflow.json."""
    sys.path.insert(0, os.path.join(ROOT, "hooks"))
    import _hooklib
    try:
        cfg = _hooklib.config()
        print(f"project.json: valid ({len(cfg['repos'])} repos, tickets {cfg['tickets']['pattern']}, "
              f"commits {cfg['commits']['style']}, protected {', '.join(sorted(_hooklib.protected_branches()))})")
        code = 0
    except _hooklib.ConfigError as e:
        print(e)
        code = 1
    return run([PY, os.path.join(ROOT, "hooks", "gates.py"), "validate"]) or code


def ci(_args):
    """The pipeline's checks, in its order; tools that aren't installed are skipped and said so."""
    steps = [("hook tests", [PY, "-m", "unittest", "discover", "-s", "hooks/tests"]),
             ("script tests", [PY, "-m", "unittest", "discover", "-s", "scripts/tests"]),
             *([("team tests", [PY, "-m", "unittest", "discover", "-s", "team/tests"])]
               if os.path.isdir(os.path.join(ROOT, "team", "tests")) else []),
             ("config", [PY, "scripts/sdlc.py", "validate"]),
             ("version", [PY, "scripts/version_check.py"]
              + (["--base", "origin/main"] if git("rev-parse", "-q", "--verify", "origin/main")[0] == 0 else [])),
             ("docs", [PY, "scripts/docs.py", "--check"])]
    if shutil.which("ruff"):
        steps.append(("lint", ["ruff", "check", "."]))
    else:
        print("lint: skipped (ruff not installed; CI runs it)")
    failed = []
    for name, cmd in steps:
        print(f"== {name}", flush=True)
        if run(cmd):
            failed.append(name)
    print(f"\n{'FAILED: ' + ', '.join(failed) if failed else 'All CI checks passed.'}")
    return 1 if failed else 0


def changelog_since(text, version):
    """The CHANGELOG entries (## headings and their bodies) above the given version."""
    entries, current = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            if re.match(rf"## {re.escape(version)}\b", line):
                break
            current = [line]
            entries.append(current)
        elif current is not None:
            current.append(line)
    return "\n".join("\n".join(e).rstrip() for e in entries)


def update(args):
    if git("fetch", "-q", "origin")[0]:
        print("Couldn't fetch ai-sdlc's origin (offline, or no remote yet).")
        return 1
    _, behind = git("rev-list", "--count", "HEAD..origin/main")
    behind = int(behind.strip() or 0)
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    if not behind:
        print(f"Up to date (v{version}).")
        return 0
    _, changelog = git("show", "origin/main:CHANGELOG.md")
    print(f"origin/main is {behind} commit(s) ahead of your v{version}. New entries:\n")
    print(changelog_since(changelog, version) or "(none: changes without a version bump)")
    if "--pull" not in args:
        print("\nRun `sdlc update --pull` to fast-forward, then do each entry's **After pulling** step.")
        return 0
    code = run(["git", "-C", ROOT, "pull", "--ff-only", "origin", "main"])
    if code == 0:
        print("\nPulled. Do the **After pulling** steps above (restart Claude Code / rerun install.py if they say so).")
    return code


def claude(args):
    """Claude Code must start in the workspace root, or the project hooks, skills and settings don't load."""
    if not shutil.which("claude"):
        print("The claude CLI isn't installed (https://docs.claude.com/claude-code); in an editor, open the workspace folder.")
        return 1
    return run(["claude", *args], cwd=os.path.dirname(ROOT))


OWN = {"status": status, "validate": validate, "ci": ci, "update": update, "claude": claude}


def main():
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("help", [])
    if cmd in OWN:
        sys.exit(OWN[cmd](args))
    if cmd in PASS:
        script, fixed, allowed = PASS[cmd]
        if allowed is not None and (not args or args[0] not in allowed):
            sys.exit(f"sdlc {cmd}: use one of {', '.join(sorted(allowed))}")
        sys.exit(run([PY, os.path.join(ROOT, script), *fixed, *args], cwd=os.getcwd()))
    print(__doc__.strip())
    sys.exit(0 if cmd in ("help", "-h", "--help") else 2)


if __name__ == "__main__":
    main()
