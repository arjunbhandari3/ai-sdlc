#!/usr/bin/env python3
"""SessionStart: print each project repo's branch and working-tree state, and ai-sdlc's version (stdout becomes
session context). Behind counts come from the last fetch; this hook never touches the network."""
import os

from _hooklib import CLAUDE, WORKSPACE, config, current_branch, in_workspace, protected_branches, read_input, run


def setup_line():
    """The shared setup (.claude): version, and a pull hint when the last fetch saw newer commits on origin/main."""
    try:
        with open(os.path.join(CLAUDE, "VERSION"), encoding="utf-8") as f:
            version = f.read().strip()
    except OSError:
        version = "unknown"
    code, behind = run(["git", "-C", CLAUDE, "rev-list", "--count", "HEAD..origin/main"])
    behind = int(behind) if code == 0 and behind.strip().isdigit() else 0
    hint = (f"; origin/main is {behind} commit(s) ahead: tell the user to run `sdlc update --pull` and read "
            "CHANGELOG.md (entries say when to restart Claude Code or rerun install.py)") if behind else ""
    if run(["git", "-C", CLAUDE, "rev-parse", "--is-inside-work-tree"])[0] != 0:
        return f"- .claude (shared Claude setup) v{version}: not a git clone (updates come from a fresh copy)"
    _, status = run(["git", "-C", CLAUDE, "status", "--porcelain"])
    changed = len([line for line in status.splitlines() if line.strip()])
    return f"- .claude (shared Claude setup) v{version}: {current_branch(CLAUDE) or 'detached'}, {changed} changed file(s){hint}"


def repo_line(repo):
    name, path = repo["name"], os.path.join(WORKSPACE, repo["name"])
    role = f" ({repo['role']})" if repo.get("role") else ""
    if not os.path.isdir(os.path.join(path, ".git")):
        return f"- {name}{role}: not cloned (sdlc setup clones it)"
    branch = current_branch(path) or "detached"
    _, status = run(["git", "-C", path, "status", "--porcelain"])
    changed = len([line for line in status.splitlines() if line.strip()])
    code, counts = run(["git", "-C", path, "rev-list", "--left-right", "--count", "@{u}...HEAD"])
    ahead_behind = ""
    if code == 0 and len(counts.split()) == 2:
        behind, ahead = counts.split()
        ahead_behind = f", behind {behind}, ahead {ahead}"
    flag = " [PROTECTED]" if branch in protected_branches() else ""
    return f"- {name}{role}: {branch}{flag}, {changed} changed file(s){ahead_behind}"


def main():
    hook = read_input()
    if not in_workspace(hook.cwd):
        return
    cfg = config()
    title = cfg["name"] or os.path.basename(WORKSPACE)
    print(f"{title} workspace (each repo is its own git repo; run git inside the repo dir; see .claude/PROJECT.md):")
    print(setup_line())
    for repo in cfg["repos"]:
        print(repo_line(repo))
    if not cfg["repos"]:
        print("- no repos listed yet: run `sdlc init` to draft project.json from the folders here")


if __name__ == "__main__":
    main()
