#!/usr/bin/env python3
"""Before a ship list: how a branch merges into each environment, read-only.

    check_targets.py <repo-dir> <branch> [target ...]     (default targets: project.json git.environments)

Per target (origin/<target>, fetched first):
- clean, or the conflicting files (git merge-tree, nothing checked out)
- for conflicts: whether another target has the same versions of those files, so one resolution serves both
- for clean merges: names the branch's changed JS files import from the app (e.g. `{ SINGLE } from
  "static/constants"`) that the merged result no longer exports, which the build won't catch
Exit 0 always; read the table.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from workspace_paths import project  # noqa: E402

IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']([^\"']+)[\"']")
EXPORTS = (
    r"export\s+(?:const|let|var|function|class)\s+{n}\b",  # export const n
    r"export\s*\{{[^}}]*\b{n}\b[^}}]*\}}",  # export {{ n }}
    r"export\s+const\s*\{{[^}}]*\b{n}\b[^}}]*\}}\s*=",  # export const {{ n }} = slice.actions
)


def git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and p.returncode not in (0, 1):
        raise SystemExit(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p


def show(repo, tree, path):
    p = git(repo, "show", f"{tree}:{path}", check=False)
    return p.stdout if p.returncode == 0 else None


def module_path(repo, tree, importer, spec):
    """App-relative ("static/constants") or relative ("./x") import -> file in the tree, or None."""
    if spec.startswith("."):
        base = os.path.normpath(os.path.join(os.path.dirname(importer), spec))
    elif "/" in spec and not spec.startswith("@"):
        base = os.path.join("src", spec)
    else:
        return None  # a package
    for cand in (base, base + ".js", base + ".jsx", os.path.join(base, "index.js")):
        if show(repo, tree, cand) is not None and not cand.endswith("/"):
            return cand
    return None


def missing_imports(repo, tree, files):
    found = []
    for f in files:
        src = show(repo, tree, f)
        if not src:
            continue
        for names, spec in IMPORT.findall(src):
            mod = module_path(repo, tree, f, spec)
            text = show(repo, tree, mod) if mod else None
            if not text:
                continue
            for n in (x.split(" as ")[0].strip() for x in names.split(",")):
                if n and not any(re.search(p.format(n=re.escape(n)), text) for p in EXPORTS):
                    found.append(f"{os.path.basename(f)}: `{n}` from {spec}")
    return found


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    repo, branch = sys.argv[1], sys.argv[2]
    targets = sys.argv[3:] or [e["branch"] for e in project()["git"]["environments"]]
    if not targets:
        sys.exit("No targets: name them, or list git.environments in project.json.")
    base = project()["git"].get("base", "main")
    git(repo, "fetch", "-q", "origin")
    changed = [f for f in git(repo, "diff", "--name-only", "--diff-filter=AM", f"origin/{base}...{branch}").stdout.split()
               if f.endswith((".js", ".jsx"))]
    seen = {}  # conflicting files + their target versions -> first target with them
    print(f"{branch}: {len(changed)} changed JS file(s)\n")
    print("| Target | Merge | Notes |\n|---|---|---|")
    for t in targets:
        if git(repo, "rev-parse", "-q", "--verify", f"origin/{t}", check=False).returncode:
            print(f"| {t} | – | no such branch |")
            continue
        p = git(repo, "merge-tree", "--write-tree", "--name-only", branch, f"origin/{t}")
        lines = [x for x in p.stdout.split("\n") if x]
        tree = lines[0]
        if p.returncode == 0:
            missing = missing_imports(repo, tree, changed)
            note = ("**missing exports:** " + "; ".join(missing)) if missing else "imports resolve"
            print(f"| {t} | clean → PR `{branch}` → `{t}` | {note} |")
            continue
        files = []
        for x in lines[1:]:
            if x.startswith(("Auto-merging", "CONFLICT")) or not x.strip():
                break
            files.append(x)
        sig = tuple((f, git(repo, "rev-parse", f"origin/{t}:{f}", check=False).stdout.strip()) for f in files)
        reuse = seen.get(sig)
        seen.setdefault(sig, t)
        note = f"same target versions as {reuse}: reuse its resolution" if reuse else "resolve by hand"
        print(f"| {t} | **conflicts** ({len(files)}): {', '.join(os.path.basename(f) for f in files)} → `{branch}-<env>` branch | {note} |")


if __name__ == "__main__":
    main()
