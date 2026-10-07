---
name: read-ticket
description: Read a ticket from the project's tracker (read-only) and turn it into working context — summary, acceptance criteria, likely repos, open questions — saved in the ticket folder. Use when the user says "read PAY-12", "what is PAY-12 about", "open the ticket", "refresh the ticket", or when ship-ticket starts a ticket.
argument-hint: TICKET
---

# Read a ticket

The tracker is `tickets.tracker` in `.claude/project.json`. Reading never changes the ticket.

| Tracker | How | Saved as |
|---|---|---|
| `jira` | `python3 .claude/scripts/jira.py fetch <ticket>` (needs `JIRA_SITE`, `JIRA_API_TOKEN`; `jira.py check` tests them) | `jira.md` |
| `github` | `gh issue view <number> --repo <org>/<repo> --comments` (the number from the key, e.g. GH-42 → 42; the repo the user names or the first in project.json) | `ticket.md` |
| `gitlab` | `glab issue view <number> --repo <org>/<repo> --comments` | `ticket.md` |
| `none` / other | ask the user to paste the summary and acceptance criteria | `ticket.md` |

Save to `.sdlc/tickets/<ticket>/` (outside every repo). For `ticket.md`, keep this shape so the gates can pick the
profile from it:

```markdown
# PAY-12: <title>

| Field | Value |
|---|---|
| Type | Story |
| Status | In Progress |
| Labels | payments, hotfix |
| Link | <url> |

## Description
...

## Acceptance criteria
...
```

Then tell the user: the summary in two lines, the acceptance criteria, the repos it likely touches (use `PROJECT.md`
"Where a change goes"), and open questions. Tickets can mention people or customer data: nothing from them goes
into commits, PRs or chat beyond what the change needs.
