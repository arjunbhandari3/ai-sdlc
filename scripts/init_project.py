#!/usr/bin/env python3
"""Draft project.json from the repos already in this workspace, so a team starts from facts, not a blank file.

    sdlc init                 print the draft (changes nothing)
    sdlc init --write         write project.json (and PROJECT.md from templates/) if they don't exist yet
    sdlc init --write --force overwrite project.json

What it reads (git and files only, no network): the folders with a .git next to ai-sdlc; each repo's origin URL (host,
org), remote branches (base, environment branches), branch names (ticket key pattern), recent commit subjects (commit
style), and package.json / pyproject.toml / go.mod (format and lint rules, seed scripts). Review the draft: roles,
data sensitivity and the "ask first" commands need a human.
"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.environ.get("SDLC_WORKSPACE") or os.path.dirname(KIT)
BASES = ["main", "master"]
ENV_BRANCHES = {"develop": "dev", "development": "dev", "dev": "dev", "qa": "qa", "test": "qa", "staging": "staging",
                "uat": "uat", "preprod": "preprod", "release": "release", "production": "prod", "prod": "prod"}
CONVENTIONAL = re.compile(r"^(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)(\([^)]+\))?!?: ")
HOSTS = {"github.com": "github", "bitbucket.org": "bitbucket", "gitlab.com": "gitlab"}


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def repos():
    kit = os.path.realpath(KIT)
    found = []
    for name in sorted(os.listdir(WORKSPACE)):
        path = os.path.join(WORKSPACE, name)
        if name.startswith(".") or os.path.realpath(path) == kit or not os.path.isdir(os.path.join(path, ".git")):
            continue
        found.append((name, path))
    return found


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def repo_entry(name, path):
    """{name, role, onEdit} from the repo's own tooling."""
    entry, rules = {"name": name, "role": ""}, []
    pkg = read_json(os.path.join(path, "package.json"))
    pyproject = read_text(os.path.join(path, "pyproject.toml"))
    if pkg:
        entry["role"] = pkg.get("description", "")[:60]
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        exts = "*.js,*.jsx,*.ts,*.tsx" + (",*.json,*.css,*.scss,*.md" if "prettier" in deps else "")
        if "prettier" in deps:
            rules.append({"files": exts, "run": "node_modules/.bin/prettier --write --log-level warn {file}", "fix": True})
        if "eslint" in deps:
            rules.append({"files": "*.js,*.jsx,*.ts,*.tsx", "run": "node_modules/.bin/eslint --fix --quiet {file}"})
    if "ruff" in pyproject or os.path.isfile(os.path.join(path, "ruff.toml")):
        rules += [{"files": "*.py", "run": "ruff format {file}", "fix": True}, {"files": "*.py", "run": "ruff check {file}"}]
    elif "black" in pyproject:
        rules.append({"files": "*.py", "run": "black -q {file}", "fix": True})
    if os.path.isfile(os.path.join(path, "go.mod")):
        rules.append({"files": "*.go", "run": "gofmt -w {file}", "fix": True})
    if rules:
        entry["onEdit"] = rules
    return entry


def seed_rules(found):
    rules = []
    for name, path in found:
        scripts = read_json(os.path.join(path, "package.json")).get("scripts", {})
        for script in scripts:
            if re.match(r"(seed|migrate|db:)", script):
                rules.append({"command": f"npm run {script}*", "repo": name,
                              "reason": f"`{script}` in {name} writes to whatever database it is configured for."})
    return rules


def git_section(found):
    url = next((git(p, "remote", "get-url", "origin").strip() for _, p in found if git(p, "remote", "get-url", "origin")), "")
    host = next((v for k, v in HOSTS.items() if k in url), "github")
    m = re.search(r"[:/]([^/:]+)/[^/]+?(\.git)?$", url)
    branches = collections.Counter()
    for _, path in found:
        for line in git(path, "branch", "-r", "--format=%(refname:short)").split():
            branches[line.split("/", 1)[-1]] += 1
    base = next((b for b in BASES if branches[b]), "main")
    envs = [{"name": ENV_BRANCHES[b], "branch": b} for b in ENV_BRANCHES if branches[b] and b != base]
    return {"host": host, "org": m.group(1) if m else "", "base": base, "protectedBranches": [base], "environments": envs}


def ticket_pattern(found):
    keys = collections.Counter()
    for _, path in found:
        for line in git(path, "branch", "-a", "--format=%(refname:short)").split():
            m = re.match(r"(?:origin/)?([A-Z][A-Z0-9]+)-\d+", line.split("/")[-1])
            if m:
                keys[m.group(1)] += 1
    common = [k for k, n in keys.most_common(3) if n >= 2]
    if not common:
        return "[A-Z][A-Z0-9]+-\\d+", "none"
    return (f"{common[0]}-\\d+" if len(common) == 1 else f"(?:{'|'.join(common)})-\\d+"), "jira"


def commit_style(found, pattern):
    subjects = [s for _, p in found for s in git(p, "log", "-50", "--no-merges", "--format=%s").splitlines()]
    if not subjects:
        return "ticket"
    conventional = sum(bool(CONVENTIONAL.match(s)) for s in subjects)
    ticketed = sum(bool(re.match(rf"({pattern}):? ", s)) for s in subjects)
    if conventional > len(subjects) / 2:
        return "conventional"
    return "ticket" if ticketed > len(subjects) / 2 else "none"


def draft():
    found = repos()
    pattern, tracker = ticket_pattern(found)
    return {
        "name": os.path.basename(WORKSPACE),
        "repos": [repo_entry(n, p) for n, p in found],
        "git": git_section(found),
        "tickets": {"tracker": tracker, "pattern": pattern, "envBranch": "{ticket}-{env}"},
        "commits": {"style": commit_style(found, pattern), "maxSubjectLength": 72, "forbidAiMentions": True},
        "data": {"sensitivity": "none", "dataFiles": [".csv", ".xlsx", ".xls", ".pdf"]},
        "realSystems": seed_rules(found),
    }


def main():
    data = draft()
    text = json.dumps(data, indent=2) + "\n"
    target = os.path.join(KIT, "project.json")
    if "--write" not in sys.argv:
        print(text)
        print("Draft only. Review it (roles, data.sensitivity, realSystems), then `sdlc init --write`.", file=sys.stderr)
        return
    if os.path.exists(target) and "--force" not in sys.argv:
        sys.exit(f"{target} exists; compare with `sdlc init`, or overwrite with --write --force.")
    with open(target, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {target} ({len(data['repos'])} repos)")
    project_md = os.path.join(KIT, "PROJECT.md")
    if not os.path.exists(project_md):
        shutil.copyfile(os.path.join(KIT, "templates", "PROJECT.md"), project_md)
        print(f"wrote {project_md} from the template: fill in the system map and conventions")
    print("Next: set data.sensitivity, roles and realSystems; then `sdlc validate` and restart Claude Code.")


if __name__ == "__main__":
    main()
