"""Reference tables generated from the files they describe, so the docs can't drift (standard library only).

Each table sits in a doc between `<!-- generated:NAME -->` and `<!-- /generated:NAME -->`; build_docs_site.py
rewrites those blocks (or, with --check, reports them stale). Sources:
    skills       skills/*/SKILL.md frontmatter: first sentence of `description`; "Say" = its quoted phrases
    agents       agents/*.md frontmatter `description`
    workflows    workflows/*.js `meta.description`
    scripts      each script's docstring or header comment (first sentence)
    hooks        HOOKS in hooks/run.py + each module's docstring
    permissions  settings.json allow / ask lists
"""
import ast
import json
import os
import re
import sys

FIRST_SKILLS = ["ship-ticket"]  # shown first; the rest alphabetically
BLOCK = re.compile(r"(<!-- generated:([\w-]+)[^>]*-->\n)(.*?)(<!-- /generated:\2 -->)", re.S)


def first_sentence(text, limit=130):
    """The first sentence (wrapped lines joined; "e.g. x" doesn't end one), cut at " — " when it runs long."""
    text = " ".join(text.split("\n\n")[0].split())
    m = re.match(r"(.+?[.!?])(?=\s+[A-Z(\"`]|$)", text)
    text = (m.group(1) if m else text).rstrip(".")
    if len(text) > limit and " — " in text:
        text = text.split(" — ")[0]
    return text[:1].upper() + text[1:]


def cell(text):
    return text.replace("|", "\\|")


def frontmatter(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    return dict(re.findall(r"^(\w[\w-]*):\s*(.*)$", m.group(1), re.M)) if m else {}


def skills(root, team=False):
    """The kit's skills, or (team=True) the team's own skills/team-*."""
    names = sorted((n for n in os.listdir(os.path.join(root, "skills")) if n.startswith("team-") == team),
                   key=lambda n: (n not in FIRST_SKILLS, n))
    rows = ["| Skill | Say | Does |", "|---|---|---|"]
    for name in names:
        path = os.path.join(root, "skills", name, "SKILL.md")
        if not os.path.isfile(path):
            continue
        desc = frontmatter(path).get("description", "")
        say = ", ".join(f"`{q}`" for q in re.findall(r'"([^"]{3,40})"', desc)[:3]) or "–"
        rows.append(f"| `{name}` | {cell(say)} | {cell(first_sentence(desc))} |")
    return rows


def agents(root):
    rows = ["| Agent | Does |", "|---|---|"]
    for f in sorted(os.listdir(os.path.join(root, "agents"))):
        if f.endswith(".md"):
            fm = frontmatter(os.path.join(root, "agents", f))
            rows.append(f"| `{fm.get('name', f[:-3])}` | {cell(first_sentence(fm.get('description', '')))} |")
    return rows


def workflows(root):
    rows = ["| Workflow | Does |", "|---|---|"]
    folder = os.path.join(root, "workflows")
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if f.endswith(".js"):
            with open(os.path.join(root, "workflows", f), encoding="utf-8") as fh:
                text = fh.read()
            desc = re.search(r"description:\s*'((?:[^'\\]|\\.)*)'", text)
            rows.append(f"| `{f[:-3]}` | {cell(first_sentence(desc.group(1) if desc else ''))} |")
    return rows


def summary(path):
    """First sentence of a Python docstring, a JSDoc block, or the leading # / // comment lines."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith(".py"):
        return first_sentence(ast.get_docstring(ast.parse(text)) or "")
    m = re.search(r"/\*\*(.*?)\*/", text, re.S)
    if m and text.index("/**") < 400:
        body = "\n".join(re.sub(r"^\s*\* ?", "", line) for line in m.group(1).splitlines())
        return first_sentence(body.strip())
    lines = [re.sub(r"^\s*(//|#)\s?", "", line) for line in text.splitlines()
             if re.match(r"^\s*(//|#)(?!!)", line)][:6]
    return first_sentence("\n".join(lines))


def scripts(root):
    rows = ["| Script | Language | Use |", "|---|---|---|"]
    base = os.path.join(root, "scripts")
    found = []
    for d, dirs, files in os.walk(base):
        dirs[:] = sorted(x for x in dirs if x not in ("node_modules", "tests", "fixtures", "scenarios", "out", "logs",
                                                         "assets", "__pycache__"))
        found += [os.path.join(d, f) for f in files if f.endswith((".py", ".js", ".sh"))]
    for path in sorted(found, key=lambda p: (os.path.dirname(p) != base, p)):
        lang = {".py": "Python", ".js": "Node", ".sh": "shell"}[os.path.splitext(path)[1]]
        rows.append(f"| `{os.path.relpath(path, base)}` | {lang} | {cell(summary(path))} |")
    return rows


def unlisted_hooks(root):
    """Modules in run.py's HOOKS that the hand-written table in docs/guardrails.md doesn't describe."""
    sys.path.insert(0, os.path.join(root, "hooks"))
    import run  # noqa: E402
    with open(os.path.join(root, "docs", "guardrails.md"), encoding="utf-8") as f:
        text = BLOCK.sub("", f.read())
    return sorted({m for entries in run.HOOKS.values() for m, _, _ in entries if f"| `{m}` |" not in text})


def hooks(root):
    sys.path.insert(0, os.path.join(root, "hooks"))
    import run  # noqa: E402  (hooks/run.py; main() only runs as a script)
    rows = ["| Module | Event | Tools | Kind | Does |", "|---|---|---|---|---|"]
    for event, entries in run.HOOKS.items():
        for module, tools, kind in entries:
            doc = summary(os.path.join(root, "hooks", f"{module}.py"))
            doc = re.sub(r"^\w+(\([^)]*\))?:\s*", "", doc)  # "PreToolUse(Bash): x" -> "X"
            doc = doc[:1].upper() + doc[1:]
            tools = "all" if tools is None else ", ".join(sorted(tools))
            kind = "guard (fails closed)" if kind == "guard" else "helper (fails open)"
            rows.append(f"| `{module}` | {event} | {tools} | {kind} | {cell(doc)} |")
    return rows


def permissions(root):
    with open(os.path.join(root, "settings.json"), encoding="utf-8") as f:
        perms = json.load(f).get("permissions", {})
    rows = ["| Command | Claude Code |", "|---|---|"]
    for kind, label in (("ask", "always asks"), ("allow", "runs without asking")):
        for rule in perms.get(kind, []):
            m = re.match(r"Bash\((.*?)(:\*)?\)$", rule)
            rows.append(f"| `{m.group(1).strip() + (' …' if m.group(2) else '') if m else rule}` | {label} |")
    return rows


TABLES = {"skills": skills, "team-skills": lambda root: skills(root, team=True), "agents": agents, "workflows": workflows, "scripts": scripts, "hooks": hooks,
          "permissions": permissions}


def refresh(root, write):
    """Rewrite every generated block in README.md, docs/, team/README.md and team/docs/; return the files that were (or would be)
    changed."""
    changed = []
    paths = [os.path.join(root, "README.md"), os.path.join(root, "team", "README.md")] + [os.path.join(d, f) for top in ("docs", os.path.join("team", "docs"))
                                                 for d, _, fs in os.walk(os.path.join(root, top))
                                                 for f in fs if f.endswith(".md")]
    cache = {}
    for path in sorted(p for p in paths if os.path.isfile(p)):
        with open(path, encoding="utf-8") as f:
            text = f.read()

        def fill(m):
            name = m.group(2)
            if name not in TABLES:
                raise SystemExit(f"{os.path.relpath(path, root)}: unknown generated table '{name}'")
            if name not in cache:
                cache[name] = "\n".join(TABLES[name](root)) + "\n"
            return m.group(1) + cache[name] + m.group(4)

        new = BLOCK.sub(fill, text)
        if new != text:
            changed.append(os.path.relpath(path, root))
            if write:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
    return changed
