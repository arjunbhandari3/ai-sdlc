#!/usr/bin/env python3
"""CI: ai-sdlc's version and changelog agree, and a PR that changes behaviour bumps the version.

    python3 scripts/version_check.py [--base <ref>]      (CI passes --base origin/<PR destination>)

- VERSION is MAJOR.MINOR.PATCH and CHANGELOG.md's first `## ` heading starts with it.
- With --base: if the branch changes ai-sdlc itself (hooks, skills, agents, scripts, templates, settings.json,
  CLAUDE.md), VERSION must be higher than the base's. A team's own files (project.json, PROJECT.md, workflow.json,
  skills/team-*, agents/team-*, workflows/team-*, team/), docs, tests and CI files need no bump.
Exit 1 with the reasons on failure. Standard library only.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Docs, tests and CI need no bump; neither do the files a team owns in its copy of ai-sdlc (VERSION is ai-sdlc's).
NO_BUMP = re.compile(r"^(docs/|examples/|hooks/tests/|scripts/tests/|\.github/|README\.md$|CHANGELOG\.md$|"
                     r"bitbucket-pipelines\.yml$|\.gitlab-ci\.yml$|ruff\.toml$|\.gitignore$|"
                     r"project\.json$|PROJECT\.md$|workflow\.json$|skills/team-|agents/team-|workflows/team-|team/)")


def parse(version):
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", (version or "").strip())
    return tuple(map(int, m.groups())) if m else None


def git(*args):
    p = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
    return p.returncode, p.stdout


def problems(base=None):
    errors = []
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    if not parse(version):
        return [f"VERSION '{version}' is not MAJOR.MINOR.PATCH"]
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        top = next((line for line in f if line.startswith("## ")), "")
    if not re.match(rf"## {re.escape(version)}\b", top):
        errors.append(f"CHANGELOG.md's first entry is '{top.strip()}', expected '## {version} ...'")
    if base:
        code, out = git("diff", "--name-only", f"{base}...HEAD")
        if code:
            return errors + [f"can't diff against {base}"]
        behaviour = [f for f in out.split() if not NO_BUMP.match(f)]
        code, base_version = git("show", f"{base}:VERSION")
        old = parse(base_version) if code == 0 else None
        if behaviour and old and parse(version) <= old:
            errors.append(f"these change behaviour, so bump VERSION above {base_version.strip()} and add a CHANGELOG "
                          f"entry: {', '.join(behaviour[:8])}" + (" ..." if len(behaviour) > 8 else ""))
    return errors


def main():
    base = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else None
    errors = problems(base)
    for e in errors:
        print(f"version check: {e}")
    if errors:
        sys.exit(1)
    print("version check: ok")


if __name__ == "__main__":
    main()
