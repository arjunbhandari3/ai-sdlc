#!/usr/bin/env python3
"""PostToolUse(Edit|Write|MultiEdit): tidy and check the file Claude just edited, with the repo's own tools.

project.json, per repo:
    "onEdit": [
      {"files": "*.js,*.ts", "run": "node_modules/.bin/prettier --write {file}", "fix": true},
      {"files": "*.js,*.ts", "run": "node_modules/.bin/eslint --fix --quiet {file}"},
      {"files": "src/*.py", "run": "python -m pytest {test}", "test": "tests/test_{name}.py"}
    ]
- `files`: comma-separated globs, matched against the path inside the repo (and its file name).
- `run`: a command run in the repo folder. {file} = the edited file, {rel} = its path in the repo, {name} = its name
  without extension, {test} = the `test` template filled in. A relative program path that doesn't exist (tools not
  installed) skips the step.
- `fix: true`: a formatter; its exit code is ignored. Otherwise a non-zero exit is reported to Claude (exit 2).
- `test`: only run when that test file exists.
"""
import fnmatch
import os
import shlex

from _hooklib import block, config, in_workspace, read_input, repo_of, run

TIMEOUT = 170


def tail(out, n):
    return "\n".join(out.strip().splitlines()[-n:])


def matches(rel, patterns):
    return any(fnmatch.fnmatch(rel, p.strip()) or fnmatch.fnmatch(os.path.basename(rel), p.strip())
               for p in patterns.split(","))


def step(repo_dir, rel, rule):
    """Run one onEdit rule; a problem message, or None."""
    name = os.path.splitext(os.path.basename(rel))[0]
    values = {"file": os.path.join(repo_dir, rel), "rel": rel, "name": name, "dir": os.path.dirname(rel)}
    if rule.get("test"):
        values["test"] = rule["test"].format(**values)
        if not os.path.isfile(os.path.join(repo_dir, values["test"])):
            return None
    args = [a.format(**values) for a in shlex.split(rule["run"])]
    if os.sep in args[0] and not os.path.isabs(args[0]) and not os.access(os.path.join(repo_dir, args[0]), os.X_OK):
        return None  # e.g. node_modules/.bin/prettier before `npm install`
    code, out = run(args, cwd=repo_dir, timeout=TIMEOUT)
    if code != 0 and not rule.get("fix"):
        return f"`{' '.join(args)}` failed after editing {rel}:\n{tail(out, 40)}"
    return None


def main():
    path = read_input().file_path
    if not (path and os.path.isfile(path) and in_workspace(path)) or "/node_modules/" in path:
        return
    name, repo_dir = repo_of(path)
    if not name:
        return
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(repo_dir))
    repo = next((r for r in config()["repos"] if r["name"] == name), {})
    problems = [p for rule in repo.get("onEdit", []) if matches(rel, rule.get("files", "*"))
                for p in [step(repo_dir, rel, rule)] if p]
    if problems:
        block("\n\n".join(problems), "after-edit")


if __name__ == "__main__":
    main()
