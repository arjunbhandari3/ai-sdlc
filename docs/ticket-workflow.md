# Ticket workflow

`ship PAY-12` in Claude Code runs a ticket from the tracker to merged PRs. Each stage uses a skill; the order, the
state and the approvals come from `ship-ticket` and `workflow.json`.

| # | Stage | Skill / agent | Output (in `.sdlc/tickets/PAY-12/`) | Gate after it |
|---|---|---|---|---|
| 1 | Start | `read-ticket`, `start-ticket` | `jira.md` / `ticket.md`, feature branches | — |
| 2 | Requirements | — | `frd.md`, `ac.md` | `requirements` |
| 3 | Plan | `service-tracer` for cross-repo changes | `plan.md` (each AC → change → check; deploy order) | `plan` |
| 4 | Build | repo conventions; `after_edit` hook | code on the feature branches | — |
| 5 | Test cases and verify | `verify` | `test-cases.md`, `evidence/` | (`qa`, before promotion) |
| 6 | Review | `review-branch` (`branch-reviewer`, `security-reviewer`) | `reviews/` | — |
| 7 | Ship | `pr-description` | `ship-list.md`, `pr/` | `ship` |
| 8 | Promote | `promote` | PRs into environment branches | `qa` for its targets |
| 9 | Release prep | — | release PR text, deploy order | — |

The profile (from the ticket type) can skip stages: by default a bug has no FRD, a hotfix and a chore only the ship
gate.

## Approvals

When an artifact is ready, Claude shows it and runs `gates.py request PAY-12 <gate>`, then stops. Only these decide:

- **Developer gates:** your next message ("yes", "ok", "go ahead", or "no, …"). The hook records it from your message;
  Claude can't approve for you.
- **PM / QA gates:** the person listed in `workflow.json` comments `Approved: <gate>` (or `Rejected: <gate> why`) on
  the ticket; `sdlc gates sync PAY-12` records it. Only comments after the request count.

Until a gate is approved, the hook denies what it blocks: editing the ticket's code (requirements, plan), commits,
pushes and PR create/update (ship), PRs into the QA gate's target branches (qa). Changing an approved file voids the
approval. `sdlc gates status PAY-12` shows each gate.

**The ship list** is the last approval: every commit (files, message), push, PR (title, source → target), promotion
and comment Claude is about to make. One "yes" covers exactly that list; anything different (a failed step, a
conflict, an extra commit) stops and asks again.

## Where things are

- `sdlc status` lists every ticket; `sdlc status PAY-12` shows one (stage, approvals, AC results, PRs).
- `sdlc dashboard` writes one HTML page of all tickets (`.sdlc/tickets/dashboard.html`).
- `PAY-12 done` (or `sdlc done PAY-12`) lists the ticket's local files and deletes them after a yes. Code, branches,
  commits, PRs and the ticket itself are never touched.

Ticket state is personal (outside every repo). The shared record is the ticket, the commits and the PRs.
