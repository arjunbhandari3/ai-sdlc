#!/usr/bin/env python3
"""A ticket's local working files: status for the team, a dashboard of all tickets, and cleanup when it's done.

    python3 .claude/scripts/tickets.py status PAY-12 [--out <file.md>]     stage, gates (who approved, when), ACs,
                                                                          PRs per env, recent history (Markdown)
    python3 .claude/scripts/tickets.py dashboard [--out <file.html>]      every ticket in one self-contained page
                                                                          (default: .sdlc/tickets/dashboard.html)
    python3 .claude/scripts/tickets.py overview [--out <file.md>]         every ticket as Markdown (the docs site's
                                                                          local "My tickets" page)
    python3 .claude/scripts/tickets.py clean PAY-12 [--yes]
        list what would be removed (changes nothing); --yes removes it

<workspace>/.sdlc/tickets/PAY-12/ (outside every repo) holds everything made for the ticket (all its branches: PAY-12 and its
environment branches): ticket.json,
jira.md, frd.md, ac.md, plan.md, test-cases.md, test-results.json, ship-list.md, gates/, scenarios/, screenshots/,
pr/, reviews/. Clean also removes generated harness output (verify_api/logs, verify_api/assets, verify_ui/out).
Never touched: code in the repos, git branches, commits, PRs, other tickets' folders, and the shared
harness code, fixtures and scenarios in scripts/. Standard library only.
"""
import html
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from workspace_paths import REPO, TICKETS, is_ticket  # noqa: E402
WORKSPACE = os.path.dirname(REPO)  # paths are shown from here: .sdlc/tickets/...


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def gate_rows(ticket):
    """[(gate, state, by, at)] from the gates hook's own logic, so the page matches what it enforces."""
    sys.path.insert(0, os.path.join(REPO, "hooks"))
    import gates  # noqa: E402
    if not gates.is_gated(ticket):
        return []
    recorded = gates.approval_entries(ticket)
    pending = read_json(os.path.join(gates.gates_dir(ticket), "pending.json"), {}).get("gate")
    rows = []
    for g in gates.ticket_gates(ticket):
        s = gates.state(ticket, g)
        a = recorded.get(g, {})
        rows.append((g, "pending" if g == pending and s != "approved" else s, a.get("by", ""), a.get("at", "")[:16]))
    return rows


def ac_rows(ticket):
    """[(ac, now 'n/m', before 'n/m' or '')] from run_ticket.js's test-results.json."""
    res = read_json(os.path.join(TICKETS, ticket, "test-results.json"), {})
    now = res.get("now", {}).get("results", [])
    before = {f"{r['scenario']}|{r['case']}": r for r in res.get("before", {}).get("results", [])}
    acs = sorted({a for r in now for a in r.get("ac", [])}, key=lambda a: int(re.sub(r"\D", "", a) or 0))
    rows = []
    for ac in acs:
        cases = [r for r in now if ac in r.get("ac", [])]
        b = [before[k] for k in (f"{r['scenario']}|{r['case']}" for r in cases) if k in before]
        rows.append((ac, f"{sum(r['ok'] for r in cases)}/{len(cases)}", f"{sum(r['ok'] for r in b)}/{len(b)}" if b else ""))
    return rows


def info(ticket):
    t = read_json(os.path.join(TICKETS, ticket, "ticket.json"), {})
    prs = {f"{repo}: {env}": url for repo, st in (t.get("repo_state") or {}).items() for env, url in (st.get("pr") or {}).items()}
    return {"ticket": ticket, "summary": t.get("summary", ""), "stage": t.get("stage", ""),
            "jira": (t.get("tracker") or t.get("jira") or {}).get("status", ""),
            "url": (t.get("tracker") or t.get("jira") or {}).get("url", ""),
            "gates": gate_rows(ticket), "acs": ac_rows(ticket), "prs": prs, "history": (t.get("history") or [])[-5:]}


def pr_link(value):
    """'https://…/pull-requests/6153 (draft)' -> '[#6153](https://…/pull-requests/6153) (draft)'"""
    url, _, note = value.partition(" ")
    num = url.rstrip("/").rsplit("/", 1)[-1]
    return f"[#{num}]({url})" + (f" {note}" if note else "") if url.startswith("http") else value


def status_md(ticket):
    i = info(ticket)
    out = [f"# {ticket}: {i['summary']}", "", f"Stage: **{i['stage'] or '–'}** · Ticket: {i['jira'] or '–'}"
           + (f" · {i['url']}" if i["url"] else ""), ""]
    if i["gates"]:
        out += ["## Approvals", "", "| Gate | State | By | At (UTC) |", "|---|---|---|---|"]
        out += [f"| {g} | {s} | {by} | {at} |" for g, s, by, at in i["gates"]] + [""]
    if i["acs"]:
        out += ["## Acceptance criteria (UI checks, fake data)", "", "| AC | Now | Before (main) |", "|---|---|---|"]
        out += [f"| {a} | {n} | {b or '–'} |" for a, n, b in i["acs"]] + [""]
    if i["prs"]:
        out += ["## Pull requests", ""] + [f"- {k}: {pr_link(v)}" for k, v in i["prs"].items()] + [""]
    if i["history"]:
        out += ["## Recent", ""] + [f"- {h.get('at', '')[:16]} {h.get('stage', '')}: {h.get('note', '')}" for h in i["history"]]
    return "\n".join(out).rstrip() + "\n"


def overview_md():
    """Every ticket: a summary table, then each ticket's status (headings one level down)."""
    tickets = sorted(t for t in os.listdir(TICKETS) if is_ticket(t)) if os.path.isdir(TICKETS) else []
    out = ["# My tickets", "",
           "Your local ticket state (`.sdlc/tickets/`, outside every repo), from `sdlc status`. Nobody else sees this page.", ""]
    if not tickets:
        return "\n".join(out + ["No tickets yet. Start one with `ship PAY-12`."]) + "\n"
    out += ["| Ticket | Summary | Stage | Approvals | Test cases (now) | PRs |", "|---|---|---|---|---|---|"]
    infos = [info(t) for t in tickets]
    for i in infos:
        gates = ", ".join(f"{g}: {s}" for g, s, _, _ in i["gates"]) or "–"
        cases = read_json(os.path.join(TICKETS, i["ticket"], "test-results.json"), {}).get("now", {}).get("results", [])
        acs = sum(r["ok"] for r in cases), len(cases)  # each case once, even when it covers several ACs
        summary = i["summary"].replace("|", "/")
        out.append(f"| [{i['ticket']}](#{i['ticket'].lower()}) | {summary} | {i['stage'] or '–'} | {gates} | "
                   + (f"{acs[0]}/{acs[1]}" if acs[1] else "–") + f" | {len(i['prs'])} |")
    for t in tickets:
        body = status_md(t).splitlines()
        out += ["", f"## {t}", ""] + [("#" + line if line.startswith("## ") else line) for line in body[1:]]
    return "\n".join(out).rstrip() + "\n"


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tickets</title><style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#17202a;--muted:#5d6b78;--line:#dde2e7;--ok:#2e7d32;--bad:#c62828;--wait:#b26a00;--accent:#94BA33}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1b1f24;--fg:#e4e8ec;--muted:#9aa6b2;--line:#2c333a;--ok:#81c784;--bad:#ef9a9a;--wait:#ffb74d}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px -apple-system,Segoe UI,sans-serif}
header{padding:16px;border-bottom:3px solid var(--accent);background:var(--card)}h1{margin:0;font-size:18px}
main{max-width:1200px;margin:0 auto;padding:16px;display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(min(340px,100%),1fr))}
.t{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}.t h2{font-size:15px;margin:0 0 4px}
.m{color:var(--muted);font-size:12px}table{border-collapse:collapse;width:100%;margin-top:8px;font-size:13px}
td,th{text-align:left;padding:3px 6px;border-bottom:1px solid var(--line)}.approved{color:var(--ok)}
.rejected,.changed{color:var(--bad)}.pending,.missing{color:var(--wait)}a{color:inherit}
</style></head><body><header><h1>Tickets</h1><div class="m">__WHEN__ · local working state from .sdlc/tickets</div></header>
<main>__CARDS__</main></body></html>
"""


def card(i):
    e = lambda s: html.escape(str(s))  # noqa: E731
    title = f'<a href="{e(i["url"])}">{e(i["ticket"])}</a>' if i["url"] else e(i["ticket"])
    rows = "".join(f'<tr><td>{e(g)}</td><td class="{e(s)}">{e(s)}</td><td class="m">{e(by)}</td></tr>' for g, s, by, _ in i["gates"])
    acs = " · ".join(f"{e(a)} {e(n)}" for a, n, _ in i["acs"])
    prs = "".join(f'<div class="m">{e(k)}: <a href="{e(v)}">{e(v.rsplit("/", 1)[-1])}</a></div>' for k, v in i["prs"].items())
    return (f'<section class="t"><h2>{title}: {e(i["summary"])}</h2><div class="m">stage {e(i["stage"] or "–")} · Jira '
            f'{e(i["jira"] or "–")}</div>' + (f"<table>{rows}</table>" if rows else "")
            + (f'<div class="m" style="margin-top:6px">ACs: {acs}</div>' if acs else "") + prs + "</section>")


def dashboard(out):
    import datetime
    tickets = sorted(t for t in os.listdir(TICKETS) if os.path.isdir(os.path.join(TICKETS, t))) if os.path.isdir(TICKETS) else []
    cards = "".join(card(info(t)) for t in tickets)
    with open(out, "w", encoding="utf-8") as f:
        f.write(PAGE.replace("__WHEN__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")).replace("__CARDS__", cards))
    print(f"dashboard\t{out}\t{len(tickets)} tickets")


def size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs)


def human(n):
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def clean(ticket):
    """List (or with --yes remove) the ticket's folder."""
    folder = os.path.join(TICKETS, ticket)
    if not os.path.isdir(folder):
        print(f"Nothing to clean for {ticket}.")
        return
    rows = [(os.path.relpath(os.path.join(folder, n), WORKSPACE), size(os.path.join(folder, n)))
            for n in sorted(os.listdir(folder))]
    yes = "--yes" in sys.argv
    print(f"{'Removing' if yes else 'Would remove'} for {ticket}:")
    for rel, n in rows:
        print(f"  {rel:<64} {human(n):>9}")
    print(f"  {'total':<64} {human(sum(n for _, n in rows)):>9}")
    if not yes:
        print("\nNothing changed. Run again with --yes to remove these.")
        return
    shutil.rmtree(folder)
    print(f"\nDone. Code, branches, commits and PRs for {ticket} are untouched.")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    args = [a for a in args if a != out]
    cmd = args[0] if args else ""
    key = args[1] if len(args) > 1 and is_ticket(args[1]) else None
    if cmd == "status" and key:
        text = status_md(key)
        if out:
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"status\t{out}")
        else:
            print(text)
    elif cmd == "dashboard":
        dashboard(out or os.path.join(TICKETS, "dashboard.html"))
    elif cmd == "overview":
        text = overview_md()
        if out:
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"overview\t{out}")
        else:
            print(text)
    elif cmd == "clean" and key:
        clean(key)
    else:
        sys.exit("usage: tickets.py status PAY-12 [--out f.md] | dashboard [--out f.html] | overview [--out f.md] | "
                 "clean PAY-12 [--yes]")


if __name__ == "__main__":
    main()
