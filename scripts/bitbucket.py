#!/usr/bin/env python3
"""Bitbucket Cloud helper: find, create and update PRs (with default reviewers), put screenshots in descriptions, post review comments.

    bitbucket.py check
    bitbucket.py find-pr <repo-dir> <branch>
    bitbucket.py create-pr <repo-dir> <source> <target> <title> <description.md> [--draft]
    bitbucket.py update-pr <repo-dir> <pr-id> <description.md> [title]
    bitbucket.py preview <description.md>   (no auth; writes <description>.html next to it)
    bitbucket.py assets  <repo-dir> <description.md> [...]   (no auth, no push; see assets())
    bitbucket.py post    <repo-dir> <pr-id> <comments.json> [summary.md]
    bitbucket.py mark    <repo-dir> <branch> <head-sha>

Auth: an Atlassian API token with Bitbucket scopes (read:pullrequest, write:pullrequest).
Set these in your shell profile (never in a repo file):
    export BITBUCKET_EMAIL="you@yourcompany.com"
    export BITBUCKET_API_TOKEN="<token>"
"""
import base64
import html
import re
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.bitbucket.org/2.0"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from workspace_paths import TICKETS, project, ticket_key  # noqa: E402


def bookmark_path(repo_dir, branch):
    """tickets/<ticket>/reviews/last-review-<repo>__<branch>: the commit a branch was last reviewed at."""
    ticket = ticket_key(branch)
    name = f"last-review-{os.path.basename(os.path.normpath(repo_dir))}__{branch.replace('/', '_')}"
    return os.path.join(TICKETS, ticket, "reviews", name)


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def auth_header():
    email, token = os.environ.get("BITBUCKET_EMAIL"), os.environ.get("BITBUCKET_API_TOKEN")
    if not (email and token):
        die("BITBUCKET_EMAIL / BITBUCKET_API_TOKEN not set. Create an Atlassian API token with Bitbucket "
            "PR read/write scopes and export both in your shell profile.")
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def bb(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, headers={"Authorization": auth_header(), "Accept": "application/json"})
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None


def slug(repo_dir):
    """workspace/repo from the origin remote, e.g. git@bitbucket.org:acme/payments-api.git"""
    url = subprocess.run(["git", "-C", repo_dir, "remote", "get-url", "origin"], capture_output=True, text=True, check=True).stdout.strip()
    url = url[:-4] if url.endswith(".git") else url
    for sep in ("bitbucket.org:", "bitbucket.org/"):
        if sep in url:
            return url.split(sep, 1)[1]
    die(f"origin of {repo_dir} is not a Bitbucket remote: {url}")


def check():
    """Read one PR of the first project repo: the call the PR scopes allow (scoped tokens usually can't read /user)."""
    cfg = project()
    if not cfg["repos"] or not cfg["git"].get("org"):
        die("project.json needs git.org and at least one repo to check Bitbucket access")
    repo = cfg["repos"][0]["name"]
    page = bb("GET", f"/repositories/{cfg['git']['org']}/{repo}/pullrequests?pagelen=1&state=MERGED")
    print(f"OK: pull requests readable ({page.get('size', '?')} merged in {repo})")


def find_pr(repo_dir, branch):
    q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"')
    for pr in bb("GET", f"/repositories/{slug(repo_dir)}/pullrequests?q={q}").get("values", []):
        print(f"{pr['id']}\t{pr['destination']['branch']['name']}\t{pr['title']}\t{pr['links']['html']['href']}")


def keep_sent(description_file, pr_id, description):
    """Inside a ticket's pr/ folder, keep exactly what Bitbucket got as pr/<pr-id>.md and drop the draft files it
    came from (<name>.md and its <name>-assets.md / <name>.html). Elsewhere, leave files alone."""
    folder = os.path.dirname(os.path.abspath(description_file))
    if os.path.basename(folder) != "pr" or not folder.startswith(os.path.abspath(TICKETS)):
        return
    with open(os.path.join(folder, f"{pr_id}.md"), "w", encoding="utf-8") as f:
        f.write(description)
    stem = re.sub(r"-assets$", "", os.path.splitext(os.path.basename(description_file))[0])
    if stem.isdigit():
        return  # already a sent description (pr/<id>.md), not a draft
    for name in (f"{stem}.md", f"{stem}-assets.md", f"{stem}.html"):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and name != f"{pr_id}.md":
            os.remove(path)


def create_pr(repo_dir, source, target, title, description_file, draft=False):
    """Open a PR source -> target with the repo's default reviewers (as a draft with --draft), or print the
    open one if it exists."""
    repo = slug(repo_dir)
    q = urllib.parse.quote(f'source.branch.name="{source}" AND destination.branch.name="{target}" AND state="OPEN"')
    existing = bb("GET", f"/repositories/{repo}/pullrequests?q={q}").get("values", [])
    if existing:
        pr = existing[0]
        print(f"exists\t{pr['id']}\t{pr['links']['html']['href']}")
        return
    with open(description_file, encoding="utf-8") as f:
        description = f.read()
    reviewers = [r["user"] for r in bb("GET", f"/repositories/{repo}/effective-default-reviewers?pagelen=50").get("values", [])]
    body = {"title": title, "description": description, "close_source_branch": False,
            "source": {"branch": {"name": source}}, "destination": {"branch": {"name": target}}, "draft": draft}
    for _ in range(2):
        body["reviewers"] = [{"uuid": r["uuid"]} for r in reviewers]
        try:
            pr = bb("POST", f"/repositories/{repo}/pullrequests", body)
            break
        except RuntimeError as e:
            # Bitbucket rejects the PR author as a reviewer and names them in the error: drop them, retry once
            author = [r for r in reviewers if r.get("display_name") and r["display_name"] in str(e)]
            if "author" not in str(e) or not author:
                raise
            reviewers = [r for r in reviewers if r not in author]
    names = ", ".join(r.get("display_name", "?") for r in reviewers) or "none"
    kind = "draft" if pr.get("draft") else "open"
    keep_sent(description_file, pr["id"], description)
    print(f"created\t{pr['id']}\t{pr['links']['html']['href']}\t{kind}\treviewers: {names}")


def update_pr(repo_dir, pr_id, description_file, title=None):
    """Replace a PR's description, and its title when given (reviewers and branches are left as they are)."""
    with open(description_file, encoding="utf-8") as f:
        body = {"description": f.read()}
    if title:
        body["title"] = title
    pr = bb("PUT", f"/repositories/{slug(repo_dir)}/pullrequests/{pr_id}", body)
    keep_sent(description_file, pr["id"], body["description"])
    print(f"updated\t{pr['id']}\t{pr['links']['html']['href']}")


DRAG_IN = re.compile(r"^\(drag in (\S+)\)$")
PREVIEW_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>PR preview</title>
<style>
:root{--bg:#fff;--fg:#17202a;--muted:#5d6b78;--line:#dde2e7;--code:#eef1f4;--accent:#94BA33;--mark:#fff4c2}
@media (prefers-color-scheme:dark){:root{--bg:#16191d;--fg:#e4e8ec;--muted:#9aa6b2;--line:#2c333a;--code:#23292f;--mark:#4a4220}}
body{background:var(--bg);color:var(--fg);font:14px -apple-system,Segoe UI,sans-serif;line-height:1.5;margin:0}
.bar{position:sticky;top:0;z-index:1;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button{font:inherit;border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:6px;padding:5px 12px;cursor:pointer}
button.ghost{background:transparent;color:var(--fg)}
button:disabled{opacity:.5;cursor:default}
#status{color:var(--muted)}
.how{max-width:900px;margin:12px auto 0;padding:0 16px;color:var(--muted);font-size:13px}
main{max-width:900px;margin:0 auto;padding:8px 16px 40px}
h2{border-bottom:1px solid var(--line);padding-bottom:4px;margin-top:28px}
code{background:var(--code);padding:1px 4px;border-radius:3px;font-size:12px}
ul{padding-left:20px}li{margin:3px 0}
figure{margin:8px 0;padding:6px;border-radius:8px}figure.next{background:var(--mark)}
figure img{max-width:100%;border:1px solid var(--line);border-radius:6px;display:block}
figcaption{font-weight:600;margin-bottom:4px}
figure button{margin-top:4px;font-size:12px;padding:2px 8px}
</style></head><body>
<div class="bar"><button onclick="copyText()">1. Copy text</button>
<button id="next" onclick="copyNext()">2. Copy image 1</button>
<button class="ghost" onclick="restart()">Start over</button><span id="status"></span></div>
<p class="how">Bitbucket's editor only takes images one at a time. In the PR, Edit and clear the description, paste the
text (step 1), then for each image: copy it here (step 2, or press N), select its <b>[Image N]</b> marker in Bitbucket and paste
over it.</p>
<main id="content">__BODY__</main>
<script>
const MD = __MD__;
const figs = [...document.querySelectorAll("figure")];
let next = 0;
const say = (t) => { document.getElementById("status").textContent = t; };
function mark() {
  figs.forEach((f, i) => f.classList.toggle("next", i === next));
  const b = document.getElementById("next");
  b.disabled = next >= figs.length;
  b.textContent = next >= figs.length ? "All images copied" : `2. Copy image ${next + 1} of ${figs.length}`;
}
async function write(item, fallbackText) {
  try { await navigator.clipboard.write([new ClipboardItem(item)]); return true; }
  catch (e) {
    if (fallbackText === undefined) return false;
    const a = document.createElement("textarea"); a.value = fallbackText; document.body.appendChild(a);
    a.select(); document.execCommand("copy"); a.remove(); return true;
  }
}
async function copyText() {
  const c = document.getElementById("content").cloneNode(true);
  c.querySelectorAll("figure").forEach((f, i) => { const p = document.createElement("p"); p.textContent = `[Image ${i + 1}]`; f.replaceWith(p); });
  await write({ "text/html": new Blob([c.innerHTML], { type: "text/html" }), "text/plain": new Blob([MD], { type: "text/plain" }) }, MD);
  next = 0; mark();
  say(`Text copied with ${figs.length} [Image N] markers. Paste it into the PR description.`);
}
async function copyImage(i) {
  const blob = await (await fetch(figs[i].querySelector("img").src)).blob();
  if (!(await write({ [blob.type]: blob }))) { say("This browser can't copy images; use Chrome, or drag the image instead."); return; }
  next = i + 1; mark();
  say(`Image ${i + 1} copied: select [Image ${i + 1}] in Bitbucket and press Cmd+V.`);
  figs[Math.min(next, figs.length - 1)].scrollIntoView({ block: "center", behavior: "smooth" });
}
const copyNext = () => next < figs.length && copyImage(next);
function restart() { next = 0; mark(); say(""); }
document.addEventListener("keydown", (e) => { if (e.key.toLowerCase() === "n" && !e.metaKey && !e.ctrlKey) copyNext(); });
mark();
</script></body></html>
"""


def md_to_html(md):
    """The small Markdown subset the PR template uses: ## headings, - [x] / - [ ] / - lists, **bold**, `code`,
    [links](...), and "(drag in <png>)" lines, which become numbered images ("Image N")."""
    def inline(t):
        t = html.escape(t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    out, in_list, n = [], False, 0
    for line in md.splitlines():
        is_item = line.startswith("- ")
        if is_item != in_list:
            out.append("<ul>" if is_item else "</ul>")
            in_list = is_item
        img = DRAG_IN.match(line)
        if img:
            n += 1
            with open(img.group(1), "rb") as f:
                data = base64.b64encode(f.read()).decode()
            out.append(f'<figure><figcaption>Image {n}</figcaption>'
                       f'<img src="data:image/png;base64,{data}" alt="{html.escape(os.path.basename(img.group(1)))}">'
                       f'<button class="ghost" onclick="copyImage({n - 1})">Copy image {n}</button></figure>')
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif is_item:
            box = {"- [x] ": "&#9745; ", "- [ ] ": "&#9744; "}.get(line[:6], "")
            out.append(f"<li>{box}{inline(line[6:] if box else line[2:])}</li>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def preview(description_file):
    """Local page to move the description and its screenshots into Bitbucket's editor (the API can't attach images,
    and the editor drops images pasted with text): text with [Image N] markers, then each image in turn."""
    with open(description_file, encoding="utf-8") as f:
        md = f.read()
    n = iter(range(1, 1000))
    marked = "\n".join(f"[Image {next(n)}]" if DRAG_IN.match(line) else line for line in md.splitlines())
    page = PREVIEW_PAGE.replace("__BODY__", md_to_html(md)).replace("__MD__", json.dumps(marked).replace("</", "<\\/"))
    out = os.path.splitext(description_file)[0] + ".html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"preview\t{out}")


def git(repo_dir, *args, data=None):
    return subprocess.run(["git", "-C", repo_dir, *args], input=data, capture_output=True, check=True).stdout


def assets(repo_dir, *description_files):
    """Put the "(drag in <png>)" screenshots of one or more PR descriptions in Bitbucket as images.

    One parentless commit holds every PNG the descriptions use (each file once; git plumbing, so the checkout,
    index and branches are untouched). Each <description>.md gets a <description>-assets.md with its drag-in lines
    replaced by Markdown images of their raw URLs at that commit, so dev, qa and uat PRs share one push. Prints the
    commit and the branch; pushing and deleting stay plain `git push` commands the git guard hook sees:
        git -C <repo> push origin "${C}:refs/heads/<ticket>-assets"
        git -C <repo> push origin --delete <ticket>-assets
    Screenshots must be fake-data ones from the ticket folder (anyone with repo access can open them).
    """
    docs = {}
    for path in description_files:
        with open(path, encoding="utf-8") as f:
            docs[path] = f.read()
    shots = list(dict.fromkeys(m.group(1) for md in docs.values() for m in map(DRAG_IN.match, md.splitlines()) if m))
    if not shots:
        die("no (drag in <png>) lines in the descriptions")
    ticket = ticket_key(os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(description_files[0])))))
    entries, names = [], {}
    for n, shot in enumerate(shots, 1):
        names[shot] = f"{n:02d}-{os.path.basename(shot)}"
        with open(shot, "rb") as f:
            blob = git(repo_dir, "hash-object", "-w", "--stdin", data=f.read()).decode().strip()
        entries.append(f"100644 blob {blob}\t{names[shot]}")
    tree = git(repo_dir, "mktree", data=("\n".join(entries) + "\n").encode()).decode().strip()
    commit = git(repo_dir, "commit-tree", tree, "-m", f"{ticket}: PR screenshots (test data)").decode().strip()
    base = f"https://bitbucket.org/{slug(repo_dir)}/raw/{commit}"

    def image(line):
        m = DRAG_IN.match(line)
        return f"![{names[m.group(1)][3:]}]({base}/{names[m.group(1)]})" if m else line

    print(f"commit\t{commit}\nbranch\t{ticket}-assets\nimages\t{len(shots)}")
    for path, md in docs.items():
        out = os.path.splitext(path)[0] + "-assets.md"
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(image(line) for line in md.splitlines()) + "\n")
        print(f"description\t{out}")


def post(repo_dir, pr_id, comments_file, summary_file=None):
    base = f"/repositories/{slug(repo_dir)}/pullrequests/{pr_id}/comments"
    posted = 0
    if summary_file and os.path.getsize(summary_file) > 0:
        with open(summary_file, encoding="utf-8") as f:
            bb("POST", base, {"content": {"raw": f.read()}})
        posted += 1
    with open(comments_file, encoding="utf-8") as f:
        comments = json.load(f)
    for c in comments:
        path, line, text = c.get("path"), c.get("line"), c["body"]
        if path and line:
            try:
                bb("POST", base, {"content": {"raw": text}, "inline": {"path": path, "to": int(line)}})
            except RuntimeError:
                # Line outside the PR diff: fall back to a general comment, keeping the location.
                bb("POST", base, {"content": {"raw": f"`{path}:{line}` {text}"}})
        else:
            bb("POST", base, {"content": {"raw": (f"`{path}`: " if path else "") + text}})
        posted += 1
    print(f"posted {posted} comment(s) to PR #{pr_id}")


def mark(repo_dir, branch, sha):
    path = bookmark_path(repo_dir, branch)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(sha + "\n")
    print(f"recorded {sha} as last reviewed for {os.path.basename(os.path.normpath(repo_dir))} {branch}")


COMMANDS = {"check": (check, 0), "find-pr": (find_pr, 2), "create-pr": (create_pr, 5), "update-pr": (update_pr, 3),
            "preview": (preview, 1), "assets": (assets, 2), "post": (post, 3),
            "mark": (mark, 3)}

if __name__ == "__main__":
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    flags = {a for a in args if a.startswith("--")}
    args = [a for a in args if not a.startswith("--")]
    if cmd not in COMMANDS or len(args) < COMMANDS[cmd][1]:
        print(__doc__)
        sys.exit(1)
    try:
        COMMANDS[cmd][0](*args, **({"draft": True} if cmd == "create-pr" and "--draft" in flags else {}))
    except RuntimeError as e:
        die(str(e))
