#!/usr/bin/env python3
"""The `ai-sdlc` command on your PATH, also as `sdlc` (install.py copies this file to ~/.local/bin/ai-sdlc and
links ~/.local/bin/sdlc to it). Standard library only.

    sdlc setup <folder> [--from <team's ai-sdlc repo url>] [--https]
        New machine or new project: put the team's ai-sdlc copy in <folder> (clones --from, or uses the copy this
        file runs from), clone every repo in its project.json next to it (keeping any already there), run install.py.
    ai-sdlc <anything else> (or sdlc ...)
        Runs <workspace>/.claude/scripts/sdlc.py, so commands always match that workspace's copy (`sdlc help`).

The workspace is the first of: $SDLC_WORKSPACE, the nearest folder above the current one with .claude/scripts/sdlc.py,
or the default install.py saved in ~/.config/ai-sdlc/workspace. One person can have several workspaces (one per
project); `cd` into one and `sdlc` uses it.
Repo URLs: a repo's "url" in project.json, else git.host + git.org (SSH; --https or $SDLC_GIT_BASE change that).
"""
# ai-sdlc-launcher (install.py only replaces a ~/.local/bin/ai-sdlc that carries this marker)
import json
import os
import subprocess
import sys

CONFIG = os.path.join(os.path.expanduser("~"), ".config", "ai-sdlc", "workspace")
CLI = os.path.join(".claude", "scripts", "sdlc.py")
HOSTS = {"github": ("git@github.com:", "https://github.com/"), "bitbucket": ("git@bitbucket.org:", "https://bitbucket.org/"),
         "gitlab": ("git@gitlab.com:", "https://gitlab.com/")}


def workspace():
    if os.environ.get("SDLC_WORKSPACE"):
        ws = os.environ["SDLC_WORKSPACE"]
        if not os.path.isfile(os.path.join(ws, CLI)):
            sys.exit(f"SDLC_WORKSPACE={ws} has no {CLI}; unset it or point it at your workspace folder.")
        return ws
    here = os.getcwd()
    while True:
        if os.path.isfile(os.path.join(here, CLI)):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    try:
        with open(CONFIG, encoding="utf-8") as f:
            saved = f.read().strip()
        return saved if os.path.isfile(os.path.join(saved, CLI)) else None
    except OSError:
        return None


def clone(url, target):
    print(f"  clone  {os.path.basename(target)}", flush=True)
    if subprocess.run(["git", "clone", "-q", url, target]).returncode:
        sys.exit(f"Couldn't clone {url}. Check your access (SSH key, or --https), then rerun; clones already made are kept.")


def repo_url(project, repo, https):
    if repo.get("url"):
        return repo["url"]
    base = os.environ.get("SDLC_GIT_BASE")
    if not base:
        git = project.get("git", {})
        host = HOSTS.get(git.get("host", "github"))
        if not host or not git.get("org"):
            sys.exit(f"No URL for {repo['name']}: set its \"url\", or git.host and git.org in project.json.")
        base = host[1 if https else 0] + git["org"] + "/"
    return f"{base}{repo['name']}.git"


def setup(args):
    folders = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--from")]
    if not folders:
        sys.exit("usage: sdlc setup <folder> [--from <team's ai-sdlc repo url>] [--https]")
    ws = os.path.abspath(os.path.expanduser(folders[0]))
    os.makedirs(ws, exist_ok=True)
    if "--from" in args:
        url = args[args.index("--from") + 1]
        kit = os.path.join(ws, os.path.basename(url.rstrip("/")).removesuffix(".git"))
        if not os.path.isdir(os.path.join(kit, ".git")):
            clone(url, kit)
    else:
        kit = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        if not os.path.isfile(os.path.join(kit, "scripts", "sdlc.py")):
            sys.exit("Run this from your team's ai-sdlc clone, or pass --from <team's ai-sdlc repo url>.")
        if os.path.dirname(kit) != os.path.realpath(ws):
            sys.exit(f"The ai-sdlc copy at {kit} isn't inside {ws}. Clone it there first, or pass --from <url>.")
    try:
        with open(os.path.join(kit, "project.json"), encoding="utf-8") as f:
            project = json.load(f)
    except (OSError, ValueError):
        project = {"repos": []}
        print("  (no project.json in the copy yet: nothing to clone; `sdlc init` drafts one from the repos you add)")
    for repo in project.get("repos", []):
        target = os.path.join(ws, repo["name"])
        if os.path.isdir(os.path.join(target, ".git")):
            print(f"  have   {repo['name']}")
        else:
            clone(repo_url(project, repo, "--https" in args), target)
    print("\nRunning install.py ...", flush=True)
    sys.exit(subprocess.run([sys.executable, os.path.join(kit, "scripts", "install.py")], cwd=ws).returncode)


def main():
    args = sys.argv[1:]
    if args[:1] == ["setup"]:
        setup(args[1:])
    ws = workspace()
    if not ws:
        sys.exit("No ai-sdlc workspace found. cd into one, set SDLC_WORKSPACE, or create one: sdlc setup <folder> --from <url>")
    os.execv(sys.executable, [sys.executable, os.path.join(ws, CLI), *args])


if __name__ == "__main__":
    main()
