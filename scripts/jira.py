#!/usr/bin/env python3
"""Read a Jira ticket and save it for the ticket workflow; post a comment when the workflow asks for one.

    python3 .claude/scripts/jira.py check                 can I reach Jira with your token?
    python3 .claude/scripts/jira.py fetch PAY-12         save .sdlc/tickets/PAY-12/jira.md, print a summary
    python3 .claude/scripts/jira.py fetch PAY-12 --comments 20    (default: the last 10 comments)
    python3 .claude/scripts/jira.py comments PAY-12 [--json]     list comments (author, accountId, UTC time, text)
    python3 .claude/scripts/jira.py comment PAY-12 <file.md>     post a comment (the only write; always asked first;
                                                                   needs scope write:jira-work on a scoped token)

Auth: an Atlassian API token that can read Jira. Set these in your shell profile (never in a repo file):
    export JIRA_SITE="<your-site>.atlassian.net"
    export JIRA_EMAIL="you@yourcompany.com"           (defaults to BITBUCKET_EMAIL)
    export JIRA_API_TOKEN="<token>"
Either kind of token works: a classic token (the site URL is called directly) or a token with Jira scopes
(read:jira-work, read:jira-user), which goes through api.atlassian.com with the site's cloud id.

Apart from `comment`, only GET requests: it never changes the ticket. The saved file is local (.sdlc/tickets/, outside every repo) and is
deleted with the ticket's folder when the ticket is done; tickets can mention people or customer data, so nothing from it
goes into commits, PRs or chat beyond what the change needs. Attachments are listed by name, never downloaded.
Standard library only.
"""
import base64
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from workspace_paths import TICKETS  # noqa: E402

GATEWAY = "https://api.atlassian.com/ex/jira/{cloud_id}"
# Custom fields worth keeping, matched on their display name (Jira ids differ per site)
KEEP_CUSTOM = re.compile(r"accept|criteria|reproduce|expected|actual|steps|environment|test|deploy|release|"
                         r"sprint|story point|epic", re.I)


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- HTTP

def config():
    site = os.environ.get("JIRA_SITE", "").strip().rstrip("/")
    email = os.environ.get("JIRA_EMAIL") or os.environ.get("BITBUCKET_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    missing = [n for n, v in (("JIRA_SITE", site), ("JIRA_EMAIL (or BITBUCKET_EMAIL)", email),
                              ("JIRA_API_TOKEN", token)) if not v]
    if missing:
        die(f"{', '.join(missing)} not set. Create an Atlassian API token that can read Jira and export these in "
            "your shell profile (see docs/getting-started.md, 'Jira API token').")
    if not re.match(r"https?://", site):
        site = "https://" + site
    return site, "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def get(url, auth=None, body=None):
    headers = {"Accept": "application/json"}
    if auth:
        headers["Authorization"] = auth
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, headers=headers, data=data, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read().decode(errors="replace")[:300]) from None
    except urllib.error.URLError as e:
        die(f"can't reach {urllib.parse.urlparse(url).netloc}: {e.reason}. If it's a certificate error, fix trust on "
            "this machine; don't turn certificate checks off.")


class HttpError(Exception):
    def __init__(self, code, body):
        super().__init__(f"HTTP {code}")
        self.code, self.body = code, body


class Jira:
    """Picks the route once, with /myself: the site URL for classic tokens, else the API gateway (scoped tokens).
    It can't be decided per request: on the site URL a scoped token counts as anonymous, and Jira answers an
    anonymous request for a ticket with 404 (not 401), which looks like a missing ticket."""

    def __init__(self):
        self.site, self.auth = config()
        self.base = None

    def route(self):
        if self.base:
            return
        try:
            get(self.site + "/rest/api/3/myself", self.auth)
            self.base = self.site
            return
        except HttpError as e:
            if e.code not in (401, 403):
                raise
        cloud_id = get(self.site + "/_edge/tenant_info").get("cloudId")
        if not cloud_id:
            raise HttpError(401, "no cloud id for this site")
        self.base = GATEWAY.format(cloud_id=cloud_id)

    def api(self, path, body=None):
        self.route()
        return get(self.base + path, self.auth, body)


def explain(e, key=None):
    if e.code in (401, 403):
        return ("Jira refused the token (HTTP %d). Check JIRA_EMAIL and JIRA_API_TOKEN, and that the token can read "
                "Jira (classic token, or scopes read:jira-work and read:jira-user)." % e.code)
    if e.code == 404:
        return f"{key or 'that'} wasn't found, or your account can't see it (HTTP 404)."
    return f"Jira answered HTTP {e.code}: {e.body}"


# ---------------------------------------------------------------- Atlassian Document Format -> Markdown

def adf(node, depth=0):
    """Render an ADF node (Jira's rich text) as Markdown. Unknown nodes fall back to their text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    t, kids = node.get("type"), node.get("content", [])
    inner = lambda sep="": sep.join(adf(k, depth) for k in kids)  # noqa: E731
    if t == "doc":
        return "\n\n".join(s for s in (adf(k, depth) for k in kids) if s.strip()).strip()
    if t == "text":
        text = node.get("text", "")
        for m in node.get("marks", []):
            mt = m.get("type")
            if mt == "code":
                text = f"`{text}`"
            elif mt == "strong":
                text = f"**{text}**"
            elif mt == "em":
                text = f"*{text}*"
            elif mt == "strike":
                text = f"~~{text}~~"
            elif mt == "link":
                text = f"[{text}]({m.get('attrs', {}).get('href', '')})"
        return text
    if t == "paragraph":
        return inner()
    if t == "heading":
        return "#" * min(6, node.get("attrs", {}).get("level", 3) + 2) + " " + inner()
    if t == "hardBreak":
        return "\n"
    if t in ("bulletList", "orderedList"):
        lines = []
        for i, item in enumerate(kids, 1):
            body = "\n".join(adf(k, depth + 1) for k in item.get("content", [])).strip()
            body = body.replace("\n", "\n" + "  " * (depth + 1))
            lines.append("  " * depth + (f"{i}. " if t == "orderedList" else "- ") + body)
        return "\n".join(lines)
    if t == "taskList":
        return "\n".join("  " * depth + ("- [x] " if k.get("attrs", {}).get("state") == "DONE" else "- [ ] ")
                         + "".join(adf(c, depth) for c in k.get("content", [])) for k in kids)
    if t == "codeBlock":
        return f"```{node.get('attrs', {}).get('language') or ''}\n{inner()}\n```"
    if t in ("blockquote", "panel"):
        return "\n".join("> " + line for line in "\n\n".join(adf(k, depth) for k in kids).split("\n"))
    if t == "rule":
        return "---"
    if t == "table":
        rows = [[adf(c, depth).replace("\n", " ").replace("|", "/") for c in r.get("content", [])] for r in kids]
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        return "\n".join(["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width] +
                         ["| " + " | ".join(r) + " |" for r in rows[1:]])
    if t in ("tableCell", "tableHeader", "listItem", "nestedExpand", "expand", "layoutSection", "layoutColumn"):
        return "\n".join(adf(k, depth) for k in kids)
    if t == "mention":
        return "@" + node.get("attrs", {}).get("text", "").lstrip("@")
    if t == "emoji":
        return node.get("attrs", {}).get("text") or node.get("attrs", {}).get("shortName", "")
    if t in ("inlineCard", "blockCard", "embedCard"):
        return node.get("attrs", {}).get("url", "")
    if t == "status":
        return f"[{node.get('attrs', {}).get('text', '')}]"
    if t == "date":
        ts = node.get("attrs", {}).get("timestamp")
        return datetime.datetime.utcfromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d") if ts else ""
    if t in ("mediaSingle", "mediaGroup", "media", "mediaInline"):
        name = node.get("attrs", {}).get("alt") or node.get("attrs", {}).get("id", "")
        return f"[attachment {name}]" if t != "mediaSingle" and t != "mediaGroup" else inner("\n")
    return inner()


def text_of(value):
    """A field value as Markdown: ADF docs, plain strings, named objects, lists of those."""
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, dict) and value.get("type") == "doc":
        return adf(value)
    if isinstance(value, dict):
        return value.get("value") or value.get("name") or value.get("displayName") or ""
    if isinstance(value, list):
        return ", ".join(t for t in (text_of(v) for v in value) if t)
    return str(value)


# ---------------------------------------------------------------- the saved file

def render(issue, site, comments_limit):
    f, names, key = issue["fields"], issue.get("names", {}), issue["key"]
    name = lambda v: (v or {}).get("name") or (v or {}).get("displayName") or ""  # noqa: E731
    url = f"{site}/browse/{key}"
    rows = [("Type", name(f.get("issuetype"))), ("Status", name(f.get("status"))),
            ("Priority", name(f.get("priority"))), ("Assignee", name(f.get("assignee")) or "unassigned"),
            ("Reporter", name(f.get("reporter"))), ("Labels", ", ".join(f.get("labels") or [])),
            ("Components", text_of(f.get("components"))), ("Fix versions", text_of(f.get("fixVersions"))),
            ("Parent", f"{f['parent']['key']} {f['parent']['fields'].get('summary', '')}" if f.get("parent") else ""),
            ("Created", (f.get("created") or "")[:10]), ("Updated", (f.get("updated") or "")[:10])]
    custom = []
    for fid, value in f.items():
        label = names.get(fid, "")
        if fid.startswith("customfield_") and KEEP_CUSTOM.search(label) and text_of(value).strip():
            text = text_of(value)
            if label.lower().startswith("sprint") and isinstance(value, list):
                text = ", ".join(s.get("name", "") for s in value if isinstance(s, dict))
            (custom.append((label, text)) if "\n" in text or len(text) > 80 else rows.append((label, text)))

    out = [f"# {key}: {f.get('summary', '')}", "",
           f"Fetched from Jira at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} by "
           "`.claude/scripts/jira.py`. Local only (outside every repo). Tickets can mention people or customer data: don't copy "
           "names or other identifiers into commits, PRs or chat.", "",
           f"Link: {url}", "", "| Field | Value |", "|---|---|"]
    out += [f"| {k} | {str(v).replace('|', '/')} |" for k, v in rows if v]
    out += ["", "## Description", "", text_of(f.get("description")) or "_(empty)_"]
    for label, text in custom:
        out += ["", f"## {label}", "", text]
    if f.get("subtasks"):
        out += ["", "## Sub-tasks", ""] + [f"- {s['key']} [{name(s['fields'].get('status'))}] "
                                           f"{s['fields'].get('summary', '')}" for s in f["subtasks"]]
    links = []
    for link in f.get("issuelinks") or []:
        other = link.get("outwardIssue") or link.get("inwardIssue")
        verb = link["type"]["outward"] if "outwardIssue" in link else link["type"]["inward"]
        if other:
            links.append(f"- {verb} {other['key']} [{name(other['fields'].get('status'))}] "
                         f"{other['fields'].get('summary', '')}")
    if links:
        out += ["", "## Linked issues", ""] + links
    if f.get("attachment"):
        out += ["", "## Attachments (not downloaded)", ""] + [f"- {a.get('filename')} ({a.get('mimeType', '')})"
                                                            for a in f["attachment"]]
    comments = (f.get("comment") or {}).get("comments", [])
    if comments:
        shown = comments[-comments_limit:]
        out += ["", f"## Comments (last {len(shown)} of {len(comments)})"]
        for c in shown:
            out += ["", f"**{name(c.get('author'))}**, {(c.get('created') or '')[:10]}:", "", text_of(c.get("body"))]
    return "\n".join(out).rstrip() + "\n", url


def fetch(key, comments_limit):
    jira = Jira()
    query = urllib.parse.urlencode({"fields": "*all", "expand": "names"})
    try:
        issue = jira.api(f"/rest/api/3/issue/{urllib.parse.quote(key)}?{query}")
    except HttpError as e:
        die(explain(e, key))
    text, url = render(issue, jira.site, comments_limit)
    folder = os.path.join(TICKETS, key)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "jira.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    f = issue["fields"]
    print(f"{key}: {f.get('summary', '')}")
    print(f"  {(f.get('issuetype') or {}).get('name', '')} · {(f.get('status') or {}).get('name', '')} · {url}")
    print(f"  saved .sdlc/tickets/{key}/jira.md")


def utc(stamp):
    """Jira's '2026-10-06T10:00:00.000+0545' -> '2026-10-06T04:15:00+00:00' (comparable with the gates' times)."""
    try:
        parsed = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%f%z")
    except (TypeError, ValueError):
        return stamp or ""
    return parsed.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


def comments(key, as_json):
    jira = Jira()
    try:
        data = jira.api(f"/rest/api/3/issue/{urllib.parse.quote(key)}/comment?orderBy=created&maxResults=100")
    except HttpError as e:
        die(explain(e, key))
    rows = [{"id": c.get("id"), "accountId": (c.get("author") or {}).get("accountId", ""),
             "name": (c.get("author") or {}).get("displayName", ""), "created": utc(c.get("created")),
             "text": text_of(c.get("body"))} for c in data.get("comments", [])]
    if as_json:
        print(json.dumps(rows, indent=1))
        return
    for r in rows:
        print(f"{r['created']}  {r['name']} ({r['accountId']}): {r['text'][:200]}")


def to_adf(md):
    """Small Markdown -> Atlassian Document Format: headings, bullet lists, tables as code blocks, paragraphs."""
    content, blocks = [], [b for b in re.split(r"\n\s*\n", md.strip()) if b.strip()]
    text = lambda t: [{"type": "text", "text": t}] if t else []  # noqa: E731
    for block in blocks:
        lines = block.splitlines()
        if lines[0].startswith("#"):
            level = min(len(lines[0]) - len(lines[0].lstrip("#")), 6)
            content.append({"type": "heading", "attrs": {"level": level}, "content": text(lines[0].lstrip("# ").strip())})
            lines = lines[1:]
            if not lines:
                continue
        if all(line.lstrip().startswith("|") for line in lines):
            content.append({"type": "codeBlock", "content": text("\n".join(lines))})
        elif all(re.match(r"\s*[-*] ", line) for line in lines):
            content.append({"type": "bulletList", "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": text(re.sub(r"^\s*[-*] ", "", line))}]}
                for line in lines]})
        else:
            content.append({"type": "paragraph", "content": text(" ".join(line.strip() for line in lines))})
    return {"type": "doc", "version": 1, "content": content}


def comment(key, path):
    with open(path, encoding="utf-8") as fh:
        body = to_adf(fh.read())
    jira = Jira()
    try:
        made = jira.api(f"/rest/api/3/issue/{urllib.parse.quote(key)}/comment", {"body": body})
    except HttpError as e:
        if e.code in (401, 403):
            die(f"Jira refused the comment (HTTP {e.code}): the token needs write access (scope write:jira-work).")
        die(explain(e, key))
    print(f"commented\t{key}\t{made.get('id')}")


def check():
    jira = Jira()
    try:
        me = jira.api("/rest/api/3/myself")
    except HttpError as e:
        die(explain(e))
    via = "API gateway (scoped token)" if jira.base != jira.site else "site URL"
    print(f"Jira OK: signed in as {me.get('displayName', '?')} via {via}")


def main():
    argv, limit = sys.argv[1:], 10
    if "--comments" in argv:
        i = argv.index("--comments")
        try:
            limit = int(argv[i + 1])
        except (IndexError, ValueError):
            die("--comments needs a number")
        argv = argv[:i] + argv[i + 2:]
    if argv == ["check"]:
        return check()
    if len(argv) == 2 and argv[0] == "fetch" and re.fullmatch(r"[A-Za-z]+-\d+", argv[1]):
        return fetch(argv[1].upper(), limit)
    if len(argv) >= 2 and argv[0] == "comments" and re.fullmatch(r"[A-Za-z]+-\d+", argv[1]):
        return comments(argv[1].upper(), "--json" in argv)
    if len(argv) == 3 and argv[0] == "comment" and re.fullmatch(r"[A-Za-z]+-\d+", argv[1]):
        return comment(argv[1].upper(), argv[2])
    die("usage: jira.py check | fetch PAY-12 [--comments N] | comments PAY-12 [--json] | comment PAY-12 <file.md>")


if __name__ == "__main__":
    main()

