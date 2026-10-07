#!/usr/bin/env python3
"""Set up and check a workspace for ai-sdlc. Standard library only; safe to run again; never deletes anything.

    python3 <ai-sdlc>/scripts/install.py [--dry-run]      set up, from the workspace folder (ai-sdlc's parent)
    sdlc check [--tests]                              read-only readiness check (+ hook tests); exit 1 on a failure

Setting up, in order:
  1. checks the workspace: the repos listed in project.json should sit next to ai-sdlc (`sdlc setup` clones them)
  2. makes <workspace>/.claude a relative link to ai-sdlc; a real .claude folder already there is renamed to
     .claude.backup-<date> first
  3. creates <workspace>/.sdlc/tickets/ for personal ticket state (outside every repo)
  4. warns if ~/.claude/settings.json also registers these hooks (they would run twice); it doesn't edit it
  5. installs the `ai-sdlc` command (~/.local/bin/ai-sdlc, a copy of scripts/launcher.py) and its short name `sdlc`
     (a link); another program's file at either path is left alone. Saves this workspace as the default
     (~/.config/ai-sdlc/workspace)
  6. runs the check with --tests
The check never changes anything and never prints secret values (only whether they are set).
"""
import datetime
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from workspace_paths import TICKETS, ConfigError, project  # noqa: E402

REPO = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKSPACE = os.environ.get("SDLC_WORKSPACE") or os.path.dirname(REPO)
LINK = os.path.join(WORKSPACE, ".claude")
LAUNCHER = os.path.join(os.path.expanduser("~"), ".local", "bin", "ai-sdlc")
ALIAS = os.path.join(os.path.dirname(LAUNCHER), "sdlc")  # short name, a link to the launcher
LAUNCHER_CONFIG = os.path.join(os.path.expanduser("~"), ".config", "ai-sdlc", "workspace")
LAUNCHER_SRC = os.path.join(REPO, "scripts", "launcher.py")
RED, YELLOW, RESET = "\033[31m", "\033[33m", "\033[0m"
DRY = "--dry-run" in sys.argv


def say(step, msg):
    print(f"[{step}] {msg}", flush=True)


def act(description, fn):
    if DRY:
        print(f"      would {description}", flush=True)
    else:
        fn()
        print(f"      {description}", flush=True)


def configured_repos():
    try:
        return [r["name"] for r in project()["repos"]]
    except ConfigError:
        return []


def launcher_state():
    """'missing', 'current', 'stale' (ours, older) or 'foreign' (someone else's file at that path)."""
    if not os.path.exists(LAUNCHER):
        return "missing"
    try:
        with open(LAUNCHER, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return "foreign"
    if "# ai-sdlc-launcher" not in text:
        return "foreign"
    with open(LAUNCHER_SRC, encoding="utf-8") as f:
        return "current" if f.read() == text else "stale"


def install_launcher():
    os.makedirs(os.path.dirname(LAUNCHER), exist_ok=True)
    shutil.copyfile(LAUNCHER_SRC, LAUNCHER)
    os.chmod(LAUNCHER, 0o755)


def alias_free():
    """The short name `sdlc` can point at the launcher: missing, or already our link."""
    return not os.path.lexists(ALIAS) or (os.path.islink(ALIAS) and os.readlink(ALIAS) == os.path.basename(LAUNCHER))


def link_alias():
    if not os.path.lexists(ALIAS):
        os.symlink(os.path.basename(LAUNCHER), ALIAS)


def save_workspace():
    os.makedirs(os.path.dirname(LAUNCHER_CONFIG), exist_ok=True)
    with open(LAUNCHER_CONFIG, "w", encoding="utf-8") as f:
        f.write(WORKSPACE + "\n")


def personal_hooks():
    try:
        with open(os.path.expanduser("~/.claude/settings.json"), encoding="utf-8") as f:
            personal = json.load(f)
    except (OSError, ValueError):
        return []
    return [h.get("command", "") for ev in personal.get("hooks", {}).values() for m in ev for h in m.get("hooks", [])
            if "/.claude/hooks/run.py" in h.get("command", "")]


def install():
    say(1, f"workspace: {WORKSPACE}")
    missing = [r for r in configured_repos() if not os.path.isdir(os.path.join(WORKSPACE, r, ".git"))]
    if missing:
        say(1, f"not cloned yet: {', '.join(missing)} (sdlc setup {WORKSPACE} clones them)")
    elif not configured_repos():
        say(1, "project.json lists no repos yet: run `sdlc init` after this")
    else:
        say(1, f"all {len(configured_repos())} repos found")

    if os.path.islink(LINK):
        if os.path.realpath(LINK) == REPO:
            say(2, f".claude already links to {os.path.basename(REPO)}")
        else:
            say(2, f".claude links somewhere else ({os.readlink(LINK)}). Remove or rename that link yourself, then rerun.")
            sys.exit(1)
    elif os.path.basename(REPO) == ".claude":
        say(2, "ai-sdlc is cloned as .claude itself; no link needed")
    else:
        if os.path.exists(LINK):
            backup = os.path.join(WORKSPACE, ".claude.backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
            act(f"rename the existing .claude folder to {os.path.basename(backup)}", lambda: os.rename(LINK, backup))
        act(f"link .claude -> {os.path.basename(REPO)}", lambda: os.symlink(os.path.basename(REPO), LINK))

    if os.path.isdir(TICKETS):
        say(3, f"ticket state folder exists ({os.path.relpath(TICKETS, WORKSPACE)})")
    else:
        act(f"create {os.path.relpath(TICKETS, WORKSPACE)}/ for personal ticket state", lambda: os.makedirs(TICKETS))

    dup = personal_hooks()
    if dup:
        say(4, f"~/.claude/settings.json also registers {len(dup)} of these hooks, so they'd run twice. Remove them from")
        say(4, "its \"hooks\" section yourself (ai-sdlc's settings.json registers them). Not changed by this script.")
    else:
        say(4, "no duplicate hook registrations in ~/.claude/settings.json")

    state = launcher_state()
    if state == "foreign":
        say(5, f"{LAUNCHER} exists and isn't ours; left alone. Use python3 .claude/scripts/sdlc.py instead")
    else:
        if state != "current":
            act(f"{'update' if state == 'stale' else 'install'} the ai-sdlc command at {LAUNCHER}", install_launcher)
        if alias_free():
            if not os.path.lexists(ALIAS):
                act(f"link the short name {ALIAS} -> ai-sdlc", link_alias)
        else:
            say(5, f"{ALIAS} is another program's; use `ai-sdlc` (the short name `sdlc` isn't installed)")
        act(f"remember this workspace as the default ({LAUNCHER_CONFIG})", save_workspace)
        if os.path.dirname(LAUNCHER) not in os.environ.get("PATH", "").split(os.pathsep):
            say(5, f"add {os.path.dirname(LAUNCHER)} to your PATH (shell profile): export PATH=\"$HOME/.local/bin:$PATH\"")
        else:
            say(5, "ai-sdlc (and its short name sdlc) is on your PATH: try `sdlc help`")

    if DRY:
        say(6, "would run: install.py check --tests")
        return
    say(6, "running: install.py check --tests")
    sys.exit(check(run_tests=True))


def check(run_tests=False):
    failures = []

    def item(label, ok, detail="", required=True):
        mark = "ok  " if ok else ("FAIL" if required else "warn")
        color = "" if ok else (RED if required else YELLOW)
        print(f"  {color}{mark}{RESET}  {label:<44} {detail}")
        if not ok and required:
            failures.append(label)

    def version(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            return ""

    item("python3 3.9+", sys.version_info >= (3, 9), sys.version.split()[0])
    item("git", bool(shutil.which("git")), version(["git", "--version"]) or "not found")
    item("claude CLI", bool(shutil.which("claude")), version(["claude", "--version"]) or "optional with an editor extension",
         required=False)
    linked = os.path.basename(REPO) == ".claude" or os.path.realpath(LINK) == REPO
    item(".claude is ai-sdlc", linked, "" if linked else "run install.py from the workspace folder")
    try:
        cfg = project()
        item("project.json valid", True, f"{len(cfg['repos'])} repos")
    except ConfigError as e:
        cfg = None
        item("project.json valid", False, str(e))
    if cfg:
        missing = [r["name"] for r in cfg["repos"] if not os.path.isdir(os.path.join(WORKSPACE, r["name"], ".git"))]
        item("repos cloned", not missing, "missing: " + ", ".join(missing) if missing else WORKSPACE, required=False)
        host, tracker = cfg["git"].get("host"), cfg["tickets"].get("tracker")
        needs = {"bitbucket": ["BITBUCKET_EMAIL", "BITBUCKET_API_TOKEN"]}.get(host, [])
        needs += ["JIRA_SITE", "JIRA_API_TOKEN"] if tracker == "jira" else []
        for var in needs:
            item(f"{var} set", bool(os.environ.get(var)), "" if os.environ.get(var) else "see docs/getting-started.md",
                 required=False)
        cli = {"github": "gh", "gitlab": "glab"}.get(host)
        if cli:
            item(f"{cli} CLI (PRs on {host})", bool(shutil.which(cli)), version([cli, "--version"]) or "not found",
                 required=False)
    gates = subprocess.run([sys.executable, os.path.join(REPO, "hooks", "gates.py"), "validate"], capture_output=True, text=True)
    item("workflow.json valid", gates.returncode == 0, (gates.stdout or gates.stderr).strip().split(": ", 1)[-1][:70])
    try:
        with open(os.path.join(REPO, "settings.json"), encoding="utf-8") as f:
            n = sum(len(m.get("hooks", [])) for ev in json.load(f).get("hooks", {}).values() for m in ev)
        item("hooks registered in settings.json", n > 0, f"{n} hooks")
    except (OSError, ValueError) as e:
        item("hooks registered in settings.json", False, str(e))
    item("no duplicate hooks in ~/.claude/settings.json", not personal_hooks(), "", required=False)
    with open(os.path.join(REPO, "VERSION"), encoding="utf-8") as f:
        kit_version = f.read().strip()
    behind = subprocess.run(["git", "-C", REPO, "rev-list", "--count", "HEAD..origin/main"], capture_output=True, text=True)
    behind = int(behind.stdout) if behind.returncode == 0 and behind.stdout.strip().isdigit() else 0
    item(f"ai-sdlc up to date (v{kit_version})", not behind,
         f"origin/main is {behind} commit(s) ahead: sdlc update --pull" if behind else "as of the last fetch", required=False)
    state = launcher_state()
    item("ai-sdlc command installed", state == "current",
         {"current": LAUNCHER, "missing": "run install.py", "stale": "older than scripts/launcher.py; rerun install.py",
          "foreign": f"{LAUNCHER} is another program's"}[state], required=False)
    if run_tests:
        p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", os.path.join(REPO, "hooks", "tests")],
                           capture_output=True, text=True)
        last = [line for line in p.stderr.strip().splitlines() if line.strip()][-2:]
        item("hook tests", p.returncode == 0, " ".join(last))
    print("\nReady." if not failures else f"\n{len(failures)} required check(s) failed.")
    return 1 if failures else 0


def main():
    if sys.argv[1:2] == ["check"]:
        sys.exit(check(run_tests="--tests" in sys.argv))
    install()


if __name__ == "__main__":
    main()
