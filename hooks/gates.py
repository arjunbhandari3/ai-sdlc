#!/usr/bin/env python3
"""Approval gates for tickets shipped with ship-ticket, configured in workflow.json.

A ticket with .sdlc/tickets/<ticket>/gates/enabled.json has a profile (story, bug, hotfix, chore) that lists its gates. Each
gate has artifacts in the ticket folder, approvers and what it blocks: "code" (edits to the ticket's repo files),
"push" (git commit / push, PR create / update) or "promote" (PRs into its target branches). An approval covers the
artifacts as they were (sha256); editing them voids it.

- UserPromptSubmit: if the pending gate's approvers include "developer", the user's own reply decides it ("yes" /
  "approve" / "ok" / "go ahead", or "no" / "reject").
- `gates.py sync <ticket>`: reads the ticket's tracker comments (Jira); "Approved: <gate>" / "Rejected: <gate> ..." from
  a person listed for that gate's role (workflow.json "people", by tracker account id) after the request decides it.
- PreToolUse: denies what an unapproved gate blocks, and any write to gates/ other than pending.json.
Only this file writes gates/approvals.json.

CLI: gates.py enable <ticket> [profile] | request <ticket> <gate> | sync <ticket> | status <ticket>
"""
import hashlib
import json
import os
import re
import subprocess
import sys

from _hooklib import (
    CLAUDE, TICKETS, WORKSPACE, branch_ticket_key, commands, current_branch, decide, git_calls, read_input, repo_of,
    ticket_re,
)

APPROVE = re.compile(r"^\W*(yes|y|yeah|yep|ok|okay|approved?|go ahead|proceed|lgtm|sure)\b", re.I)
REJECT = re.compile(r"^\W*(no|nope|rejected?|don'?t|stop|not approved)\b", re.I)
DEFAULT_WORKFLOW = {
    "profiles": {"story": {"gates": ["requirements", "plan", "ship"]}},
    "defaultProfile": "story",
    "gates": {"requirements": {"artifacts": ["frd.md", "ac.md"], "approvers": ["developer"], "blocks": "code"},
              "plan": {"artifacts": ["plan.md"], "approvers": ["developer"], "blocks": "code"},
              "ship": {"artifacts": ["ship-list.md"], "approvers": ["developer"], "blocks": "push"}},
    "people": {},
}


# --- config and state ----------------------------------------------------------

def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


ROLES = {"developer", "pm", "qa"}
BLOCKS = {"code", "push", "promote"}


def validate(wf):
    """Problems in a workflow.json, as readable strings (empty = valid)."""
    errors = []
    gates, profiles = wf.get("gates"), wf.get("profiles")
    if not isinstance(gates, dict) or not gates:
        return ["'gates' must be an object with at least one gate"]
    if not isinstance(profiles, dict) or not profiles:
        return ["'profiles' must be an object with at least one profile"]
    for name, g in gates.items():
        where = f"gates.{name}"
        if not isinstance(g, dict):
            errors.append(f"{where} must be an object")
            continue
        if not g.get("artifacts") or not all(isinstance(a, str) and a.endswith(".md") for a in g.get("artifacts", [])):
            errors.append(f"{where}.artifacts must list .md files in the ticket folder")
        bad = set(g.get("approvers") or []) - ROLES
        if not g.get("approvers") or bad:
            errors.append(f"{where}.approvers must be some of {sorted(ROLES)}" + (f" (unknown: {sorted(bad)})" if bad else ""))
        if g.get("blocks") not in BLOCKS:
            errors.append(f"{where}.blocks must be one of {sorted(BLOCKS)}")
        if g.get("blocks") == "promote" and not g.get("targets"):
            errors.append(f"{where}.targets must list the branches it guards (e.g. qa, staging)")
    for name, p in profiles.items():
        unknown = [x for x in (p.get("gates") or []) if x not in gates]
        if unknown:
            errors.append(f"profiles.{name}.gates names unknown gates {unknown}")
    if wf.get("defaultProfile") not in profiles:
        errors.append(f"defaultProfile '{wf.get('defaultProfile')}' isn't a profile")
    for role, people in (wf.get("people") or {}).items():
        if role not in ROLES - {"developer"}:
            errors.append(f"people.{role}: only {sorted(ROLES - {'developer'})} are listed")
        for i, person in enumerate(people or []):
            if not isinstance(person, dict) or not person.get("name") or not account(person):
                errors.append(f"people.{role}[{i}] needs a name and an accountId (their tracker account)")
    return errors


def account(person):
    return person.get("accountId") or person.get("jiraAccountId")


def workflow():
    """workflow.json if present and valid; the built-in default if absent. Invalid -> WorkflowError (fail closed)."""
    path = os.path.join(CLAUDE, "workflow.json")
    if not os.path.isfile(path):
        return DEFAULT_WORKFLOW
    wf = read_json(path, None)
    errors = ["not valid JSON"] if wf is None else validate(wf)
    if errors:
        raise WorkflowError("workflow.json is invalid: " + "; ".join(errors))
    return wf


class WorkflowError(Exception):
    pass


def gates_dir(ticket):
    return os.path.join(TICKETS, ticket, "gates")


def is_gated(ticket):
    return os.path.isfile(os.path.join(gates_dir(ticket), "enabled.json"))


def ticket_gates(ticket):
    """The ticket's gates in order, from its profile."""
    wf = workflow()
    profile = read_json(os.path.join(gates_dir(ticket), "enabled.json"), {}).get("profile") or wf.get("defaultProfile")
    return wf["profiles"].get(profile, {}).get("gates", [])


def gate_def(gate):
    return workflow()["gates"][gate]


def fingerprint(ticket, gate):
    """sha256 of the gate's artifacts, or None if one is missing."""
    h = hashlib.sha256()
    for name in gate_def(gate)["artifacts"]:
        path = os.path.join(TICKETS, ticket, name)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            h.update(name.encode() + b"\0" + f.read() + b"\0")
    return h.hexdigest()


def state(ticket, gate):
    """approved | changed (edited after approval) | rejected | missing"""
    entry = read_json(os.path.join(gates_dir(ticket), "approvals.json"), {}).get(gate)
    if not entry:
        return "missing"
    if entry.get("status") == "rejected":
        return "rejected"
    return "approved" if entry.get("hash") == fingerprint(ticket, gate) else "changed"


def approval_entries(ticket):
    """{gate: {status, by, at, ...}} as recorded (read-only; for status pages)."""
    return read_json(os.path.join(gates_dir(ticket), "approvals.json"), {})


def blocking(ticket, kinds, target=None):
    """First of the ticket's gates that blocks one of `kinds` (for `target`, if a promote gate) and isn't approved."""
    for gate in ticket_gates(ticket):
        g = gate_def(gate)
        applies = g["blocks"] in kinds and (g["blocks"] != "promote" or target in g.get("targets", []))
        if applies and state(ticket, gate) != "approved":
            return gate, state(ticket, gate)
    return None


def record(ticket, gate, status, by, reason=None):
    path = os.path.join(gates_dir(ticket), "approvals.json")
    approvals = read_json(path, {})
    approvals[gate] = {"status": status, "hash": fingerprint(ticket, gate), "by": by, "at": now(),
                       **({"reason": reason[:300]} if reason else {})}
    write_json(path, approvals)
    pending = os.path.join(gates_dir(ticket), "pending.json")
    if os.path.isfile(pending):
        os.remove(pending)


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- UserPromptSubmit ------------------------------------------------------------

def context(text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}))
    sys.exit(0)


def on_prompt(prompt):
    pending = []
    if os.path.isdir(TICKETS):
        for t in os.listdir(TICKETS):
            p = read_json(os.path.join(gates_dir(t), "pending.json"), None)
            if p and is_gated(t):
                pending.append((t, p))
    if not pending:
        return
    if len(pending) > 1:  # several tickets waiting: the message must name one
        named = set(ticket_re().findall(prompt))
        pending = [x for x in pending if x[0] in named]
        if len(pending) != 1:
            context("Approval gates pending for several tickets; the user didn't name one, so nothing was decided.")
    ticket, p = pending[0]
    gate = p.get("gate")
    approve, reject = APPROVE.search(prompt), REJECT.search(prompt)
    if bool(approve) == bool(reject):
        context(f"{ticket} gate '{gate}' is still pending: the user's message neither approves nor rejects it.")
    approvers = gate_def(gate)["approvers"]
    if "developer" not in approvers:
        context(f"{ticket} gate '{gate}' is approved by {', '.join(approvers)} on the ticket (a comment 'Approved: {gate}'), "
                f"not here; after they comment, run `python3 .claude/hooks/gates.py sync {ticket}`.")
    if approve and fingerprint(ticket, gate) != p.get("hash"):
        context(f"{ticket} gate '{gate}' NOT approved: its files changed after approval was requested. "
                f"Show the current version and request the gate again.")
    record(ticket, gate, "approved" if approve else "rejected", "developer (terminal)", prompt.strip() if reject else None)
    verdict = "APPROVED" if approve else "REJECTED (revise and request the gate again)"
    context(f"{ticket} gate '{gate}' {verdict} by the user's message (recorded in gates/approvals.json).")


# --- PreToolUse ----------------------------------------------------------------------

def branch_ticket(repo):
    return branch_ticket_key(current_branch(repo)) if repo and os.path.isdir(repo) else None


def pr_target(words):
    """For a PR create/update command, (True, target branch or None); else (False, None). Recognises bitbucket.py
    create-pr/update-pr, `gh pr create/edit --base`, `glab mr create/update --target-branch`."""
    if any(w.endswith("bitbucket.py") for w in words) and any(w in ("create-pr", "update-pr") for w in words):
        sub = next(w for w in words if w in ("create-pr", "update-pr"))
        i = words.index(sub)
        return True, (words[i + 3] if sub == "create-pr" and len(words) > i + 3 else None)
    if words[:1] in (["gh"], ["glab"]) and len(words) > 2 and words[1] in ("pr", "mr") \
            and words[2] in ("create", "edit", "update"):
        flags = ("--base", "-B") if words[0] == "gh" else ("--target-branch", "-b")
        target = next((words[i + 1] for i, w in enumerate(words[:-1]) if w in flags), None)
        return True, target or next((w.split("=", 1)[1] for w in words if w.startswith(flags[0] + "=")), None)
    return False, None


def deny(ticket, found, action):
    gate, s = found
    why = {"missing": "isn't approved yet", "rejected": "was rejected", "changed": "changed after it was approved"}[s]
    who = " / ".join(gate_def(gate)["approvers"])
    decide("deny", f"{ticket}: the '{gate}' gate ({who}) {why}, so {action} is blocked. Show the artifact, run "
                   f"`python3 .claude/hooks/gates.py request {ticket} {gate}` and wait for the approval.", f"gate-{gate}")


def protects_gates(hook):
    """Only pending.json may be written under tickets/*/gates/."""
    target = hook.file_path if hook.tool_name != "Bash" else hook.command
    if "gates/" not in target:
        return
    if hook.tool_name != "Bash":
        if os.path.basename(target) != "pending.json" and "/tickets/" in target:
            decide("deny", "Approval records are written only by the gates hook.", "gate-files")
        return
    if re.search(r"approvals\.json|enabled\.json|gates/?\s*($|[;&|])", target) and not re.match(r"^\s*(cat|ls|grep|head|tail|jq)\b", target):
        decide("deny", "Approval records are written only by the gates hook.", "gate-files")


def writes_approvals(hook):
    """Content mentioning approvals.json may only be written into the gate code itself."""
    ti = hook.tool_input
    text = " ".join(str(ti.get(k) or "") for k in ("content", "new_string", "new_source"))
    text += " ".join(str(e.get("new_string") or "") for e in ti.get("edits") or [] if isinstance(e, dict))
    allowed = hook.file_path.endswith(("/hooks/gates.py", "/hooks/tests/test_hooks.py"))
    if "approvals.json" in text and not allowed:
        decide("deny", "Approval records are written only by the gates hook.", "gate-files")


def on_tool(hook):
    protects_gates(hook)
    if hook.tool_name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        writes_approvals(hook)
        ticket = branch_ticket(repo_of(hook.file_path)[1] if hook.file_path else None)
        if ticket and is_gated(ticket):
            found = blocking(ticket, ("code",))
            if found:
                deny(ticket, found, "editing the ticket's code")
        return
    if hook.tool_name != "Bash":
        return
    checks = []  # (ticket, kinds, target)
    for call in git_calls(hook.command, hook.cwd):
        if call.sub in ("commit", "push"):
            names = set(ticket_re().findall(" ".join(call.args)))
            t = branch_ticket(repo_of(call.dir)[1] or call.dir)
            checks += [(x, ("code", "push"), None) for x in names | ({t} if t else set())]
    for words, here in commands(hook.command, hook.cwd):
        is_pr, target = pr_target(words)
        if not is_pr:
            continue
        names = {t for w in words for t in ticket_re().findall(w)}
        repo = next((os.path.join(WORKSPACE, w) for w in words if os.path.isdir(os.path.join(WORKSPACE, w, ".git"))),
                    repo_of(here)[1])
        t = branch_ticket(repo)
        checks += [(x, ("code", "push", "promote"), target) for x in names | ({t} if t else set())]
    for ticket, kinds, target in checks:
        if is_gated(ticket):
            found = blocking(ticket, kinds, target)
            if found:
                deny(ticket, found, f"PRs into {target}" if gate_def(found[0])["blocks"] == "promote" else "commits, pushes and PRs")


# --- command line (Claude runs these) ---------------------------------------------------

def profile_for(ticket):
    """Profile from the saved ticket (Type row and labels in ticket.md / jira.md) matched against workflow.json."""
    wf = workflow()
    jira = ""
    for name in ("ticket.md", "jira.md"):
        try:
            with open(os.path.join(TICKETS, ticket, name), encoding="utf-8") as f:
                jira = f.read()
            break
        except OSError:
            continue
    if not jira:
        return wf.get("defaultProfile")
    jtype = (re.search(r"^\|\s*Type\s*\|\s*([^|]+?)\s*\|", jira, re.M) or [None, ""])[1]
    labels = (re.search(r"^\|\s*Labels\s*\|\s*([^|]+?)\s*\|", jira, re.M) or [None, ""])[1].lower()
    for name, p in wf["profiles"].items():  # labels first (e.g. hotfix), then types
        if any(lbl.lower() in labels for lbl in p.get("match", {}).get("labels", [])):
            return name
    for name, p in wf["profiles"].items():
        if jtype in p.get("match", {}).get("types", []) + p.get("match", {}).get("jiraTypes", []):
            return name
    return wf.get("defaultProfile")


def cli_enable(ticket, profile=None):
    profile = profile or profile_for(ticket)
    if profile not in workflow()["profiles"]:
        sys.exit(f"unknown profile {profile}; one of {', '.join(workflow()['profiles'])}")
    write_json(os.path.join(gates_dir(ticket), "enabled.json"), {"at": now(), "profile": profile})
    print(f"{ticket}: gates on, profile '{profile}' ({', '.join(ticket_gates(ticket))})")


def cli_request(ticket, gate):
    gates = ticket_gates(ticket)
    if not is_gated(ticket):
        sys.exit(f"{ticket}: gates aren't on (gates.py enable {ticket})")
    if gate not in gates:
        sys.exit(f"{ticket}: '{gate}' isn't a gate of this profile ({', '.join(gates)})")
    earlier = next(((g, state(ticket, g)) for g in gates[: gates.index(gate)] if state(ticket, g) != "approved"), None)
    if earlier:
        sys.exit(f"{ticket}: '{earlier[0]}' is {earlier[1]}; it must be approved before '{gate}'")
    digest = fingerprint(ticket, gate)
    if not digest:
        sys.exit(f"{ticket}: write {' and '.join(gate_def(gate)['artifacts'])} in the ticket folder first")
    write_json(os.path.join(gates_dir(ticket), "pending.json"), {"gate": gate, "hash": digest, "at": now()})
    who = gate_def(gate)["approvers"]
    how = "the user's next reply" if "developer" in who else f"a ticket comment 'Approved: {gate}' by {' / '.join(who)}, then `gates.py sync {ticket}`"
    print(f"{ticket}: '{gate}' pending ({', '.join(gate_def(gate)['artifacts'])}); decided by {how}")


def cli_sync(ticket):
    """Record a pending gate's decision from Jira comments by its approvers (workflow.json people)."""
    p = read_json(os.path.join(gates_dir(ticket), "pending.json"), None)
    if not p:
        print(f"{ticket}: no gate pending")
        return
    gate = p["gate"]
    people = workflow().get("people", {})
    allowed = {account(x): x.get("name", "") for role in gate_def(gate)["approvers"] if role != "developer"
               for x in people.get(role, []) if account(x)}
    if not allowed:
        sys.exit(f"{ticket}: no approvers with a tracker accountId configured for '{gate}' (workflow.json people)")
    fake = os.environ.get("SDLC_GATES_TEST_COMMENTS")  # tests only: a JSON file instead of the tracker
    if fake:
        with open(fake, encoding="utf-8") as f:
            found = json.load(f)
    else:
        out = subprocess.run([sys.executable, os.path.join(CLAUDE, "scripts", "jira.py"), "comments", ticket, "--json"],
                             capture_output=True, text=True)
        if out.returncode:
            sys.exit(out.stderr.strip() or "jira.py comments failed")
        found = json.loads(out.stdout)
    pattern = re.compile(rf"^\s*(approved|rejected)\s*:\s*{re.escape(gate)}\b(.*)", re.I | re.M)
    for c in sorted(found, key=lambda c: c["created"]):
        if c["accountId"] in allowed and c["created"] >= p["at"]:
            m = pattern.search(c["text"])
            if m:
                if fingerprint(ticket, gate) != p["hash"]:
                    sys.exit(f"{ticket}: '{gate}' files changed after it was requested; post them again and re-request")
                status = "approved" if m.group(1).lower() == "approved" else "rejected"
                record(ticket, gate, status, f"{allowed[c['accountId']]} (tracker)", m.group(2).strip() if status == "rejected" else None)
                print(f"{ticket}: '{gate}' {status.upper()} by {allowed[c['accountId']]} on the ticket")
                return
    print(f"{ticket}: '{gate}' still pending (no 'Approved: {gate}' from {', '.join(allowed.values()) or 'the approvers'} yet)")


def cli_status(ticket):
    if not is_gated(ticket):
        print(f"{ticket}: gates off")
        return
    approvals = read_json(os.path.join(gates_dir(ticket), "approvals.json"), {})
    pending = read_json(os.path.join(gates_dir(ticket), "pending.json"), {}).get("gate")
    print(f"{ticket}: profile '{read_json(os.path.join(gates_dir(ticket), 'enabled.json'), {}).get('profile')}'")
    for g in ticket_gates(ticket):
        a = approvals.get(g, {})
        detail = f"  by {a['by']} at {a['at']}" if a.get("by") and state(ticket, g) in ("approved", "rejected") else ""
        print(f"  {g:13} {state(ticket, g)}{'  (pending)' if g == pending else ''}{detail}")


def cli_validate(path=None):
    path = path or os.path.join(CLAUDE, "workflow.json")
    wf = read_json(path, None)
    errors = ["not valid JSON (or missing)"] if wf is None else validate(wf)
    if errors:
        sys.exit(f"{path}:\n  " + "\n  ".join(errors))
    print(f"{path}: valid ({len(wf['profiles'])} profiles, {len(wf['gates'])} gates)")


CLI = {"enable": (cli_enable, 1), "request": (cli_request, 2), "sync": (cli_sync, 1), "status": (cli_status, 1),
       "validate": (cli_validate, 0)}


def main():
    if len(sys.argv) > 1:
        cmd, rest = sys.argv[1], sys.argv[2:]
        if cmd not in CLI or len(rest) < CLI[cmd][1]:
            sys.exit("usage: gates.py enable <ticket> [profile] | request <ticket> <gate> | sync <ticket> | "
                     "status <ticket> | validate [workflow.json]")
        try:
            CLI[cmd][0](*rest)
        except WorkflowError as e:
            sys.exit(str(e))
        return
    hook = read_input()
    prompt = hook.data.get("hook_event_name") == "UserPromptSubmit" or "prompt" in hook.data
    try:
        on_prompt(hook.data.get("prompt") or "") if prompt else on_tool(hook)
    except WorkflowError as e:  # fail closed: nothing gated moves until the config is fixed
        if prompt:
            context(f"{e}. Gate decisions are on hold until it's fixed (gates.py validate).")
        decide("deny", f"{e}. Fix it (python3 .claude/hooks/gates.py validate) before gated work continues.", "workflow-invalid")


if __name__ == "__main__":
    main()
