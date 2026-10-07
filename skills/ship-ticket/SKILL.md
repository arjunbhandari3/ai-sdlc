---
name: ship-ticket
description: Run a ticket through the whole delivery flow in order — read the ticket, start the branches, write the requirements (FRD) and acceptance criteria, plan, build, turn the ACs into test cases and verify them, review, commit and open PRs, promote to each environment, release prep — with a resumable per-ticket state file and the approval gates in workflow.json. Use when the user says "ship PAY-12", "work on PAY-12 end to end", "continue PAY-12", "where is PAY-12", "next step for PAY-12", "PAY-12 done", or "/ship-ticket PAY-12 [stage|done]".
argument-hint: TICKET [stage|done]
---

# Ship a ticket

Arguments: `$ARGUMENTS` = the ticket key (matches `tickets.pattern` in `.claude/project.json`) and optionally a stage.
Run commands from the workspace root (the folder holding `.claude/`). This skill orders the work, keeps state and asks
for approvals; each stage uses the skill named below.

## State

`.sdlc/tickets/<ticket>/ticket.json` (create the folder). Read it first; if it exists, say where the ticket is and
resume at `stage` unless the user named another one.

```json
{
  "ticket": "PAY-12", "summary": "Retry failed card payments",
  "tracker": { "url": "https://…/PAY-12", "status": "In Progress", "fetchedAt": "2026-10-02T14:00:00Z" },
  "profile": "story", "repos": ["payments-api"], "stage": "verify",
  "requirements": { "frd": "frd.md", "ac": ["AC-1", "AC-2"], "openQuestions": 0 },
  "plan": { "deployOrder": ["payments-worker", "payments-api"] },
  "testCases": { "total": 9, "passed": 9, "byAc": { "AC-1": "5/5", "AC-2": "4/4" } },
  "repo_state": { "payments-api": { "branch": "PAY-12", "verifiedCommit": "d759c5d", "reviewedCommit": null,
                                    "pr": { "develop": "https://…/pull/41" }, "envBranches": {}, "promotedTo": ["dev"] } },
  "history": [{ "at": "2026-10-02T14:30:00Z", "stage": "verify", "note": "9 cases pass" }]
}
```

Update it after every stage (append to `history`; facts only: commits, links, results). Everything made for the
ticket goes in its folder: `ticket.md` or `jira.md` (the ticket as read), `frd.md`, `ac.md`, `plan.md`,
`test-cases.md` (templates: [requirements.md](requirements.md)), `ship-list.md`, `evidence/`, `pr/`, `reviews/`. Never
put real customer data, tokens or secrets there.

## Approvals (enforced by `hooks/gates.py`)

At stage 1 run `python3 .claude/hooks/gates.py enable <ticket>`: it picks the **profile** (story, bug, hotfix, chore)
from the ticket's type or labels via `workflow.json`, which lists its gates and stages. When an artifact is ready,
show it, then run `python3 .claude/hooks/gates.py request <ticket> <gate>` and stop.

- **developer** approvers: the user's next message decides ("yes" / "ok" / "go ahead", or "no …"). Only the hook
  records it, from their own message; you can't approve a gate yourself.
- **pm / qa** approvers (listed in workflow.json `people`): they comment `Approved: <gate>` or `Rejected: <gate> <why>`
  on the ticket; then run `gates.py sync <ticket>`. Posting the artifact there is a ticket comment: ask first.

Default gates: `requirements` (frd.md + ac.md) and `plan` block editing the ticket's repo files; `ship` (ship-list.md)
blocks commits, pushes and PR create/update; `qa` (test-cases.md) blocks PRs into its target branches. Editing an
approved artifact voids its approval. `gates.py status <ticket>` shows each gate.

**The ship list** (`ship-list.md`): every outward step about to happen, per repo: each commit (files + message), the
push, each PR (title, source → target, reviewers) or PR update, promotions the user asked for (direct PR or env
branch, from the dry-run merge), comments to post. One approval covers exactly that list; anything that differs
(a failed step, a conflict, an extra commit, `--force`) stops and needs a new approval for the changed part.

## Stages

Print `<ticket> · stage N/9 <name> · repos …` before each stage and a short result after. Skip the stages the profile
leaves out.

1. **Start**: `read-ticket` (saves the ticket; read-only). Record summary, tracker status and criteria. If the ticket
   is done or someone else's, ask before going on. Confirm the repos (from the ticket, `PROJECT.md`'s "where a change
   goes", or the user), then `start-ticket` for each. `gates.py enable <ticket>`.
2. **Requirements**: `frd.md` and `ac.md` from the ticket **and the code** (screens, roles, entry points, states it
   touches). Tracker criteria first, then the ones the FRD adds; every open question asked, never assumed. Gate.
3. **Plan**: `plan.md`: each AC → the change → how it's verified (test, check, or "manual: why"). Several repos or a
   shared contract (schema, payload, event): trace every producer and consumer first (agent `service-tracer`) and
   record the deploy order (consumers tolerant first). Gate.
4. **Build**: the smallest change that meets the ACs, in the repo's existing patterns. The `after_edit` hook formats
   and checks each edited file with the repo's own `onEdit` rules; fix what it reports. Mention any known issue from
   `PROJECT.md` the change touches.
5. **Test cases and verify**: `verify`: expand `ac.md` into `test-cases.md` (each AC's roles × entry points ×
   states) and run every case on the branch ("now"); behaviour changes and bug fixes also on `git.base` ("before").
   Report per AC: met, not testable here (why), or not met (back to 4). Record `testCases`, `verifiedCommit`.
6. **Review**: `review-branch` (agents `branch-reviewer`, plus `security-reviewer` when the diff touches data, auth,
   logging or outbound calls). Fix blockers (back to 4–5). Record `reviewedCommit`.
7. **Ship**: draft the commits, the push and the PR text (`pr-description`), write `ship-list.md`, show it, request
   the `ship` gate. After approval, carry out the whole list and record PR links.
8. **Promote**: only to the environments the user names: `promote` (dry-run merge per environment; clean → PR the
   feature branch; conflicts → `<ticket>-<env>` branch, resolved the same way everywhere). Follow-up changes go on the
   feature branch (stage 4 → 5) and are promoted again.
9. **Release prep** (only when asked): the release PR text and, for multi-repo tickets, the deploy order.

## Status ("where is PAY-12")

`sdlc status <ticket>` (or `python3 .claude/scripts/tickets.py status <ticket>`) prints stage, approvals, AC results
and PRs. Re-read the ticket if `fetchedAt` is over a day old and say what changed; re-verify if a repo's `HEAD` moved
past `verifiedCommit`. Give the next action.

## Done ("PAY-12 done")

Clears the ticket's local files; never code, branches or anything remote.
1. Check it's finished: open PRs, environments not promoted, uncommitted changes. If any, list them and ask
   "Mark it done anyway?".
2. `sdlc done <ticket>` lists the ticket folder with sizes (changes nothing). Ask "Delete these?"; after a clear yes,
   `sdlc done <ticket> --yes`.
3. Offer, don't do: deleting merged local branches (`git -C <repo> branch -d`).

## When something blocks

- Tracker unreachable or not configured: say so once, ask the user to paste the summary and criteria, continue.
- A hook denial: stop that step, say what was blocked and why, offer the manual step. Never work around it.
- Network or TLS failures: don't disable certificate checks; name the host that failed.
