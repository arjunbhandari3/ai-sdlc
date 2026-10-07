# Requirements, acceptance criteria and test cases (ship-ticket stages 2 and 5)

Templates for the files `ship-ticket` writes in `.sdlc/tickets/<ticket>/`. Draft them from the ticket **and the code**
(which roles, screens, endpoints, entry points and states the change touches), not from the ticket alone. Anything the
ticket doesn't settle is an open question, never an assumption. Describe behaviour with roles and fake examples only.

## frd.md — feature requirements

```markdown
# PAY-12: <summary>

## Problem
<1–3 sentences: what is wrong or missing today, for whom. Link to the ticket.>

## Users and roles
<who is affected; which accounts, permissions or settings matter>

## Scope
- <behaviour that changes, one per bullet, in user terms>

## Out of scope
- <related things this ticket deliberately doesn't change>

## Where it shows
<screens, entry points, endpoints, queues, events, jobs touched>

## Rules and edge cases
- <states, empty and error cases, permissions, limits>

## Today (on the base branch)
<current behaviour for what the ACs touch, from the code. Any "as today" claim an AC relies on is checked by running
it on the base branch before the gate, not only read from the code.>

## Open questions
- <each with the options; resolved ones move into Scope or Rules with the answer>

## Decisions
- <date: what was decided mid-flow and why; ACs that changed say so>
```

## ac.md — acceptance criteria

Numbered, testable, one behaviour each. The ticket's criteria come first (reworded only to make them testable; say
so), then the ones the FRD adds. Every AC names the matrix it must hold for.

```markdown
# PAY-12 acceptance criteria

| AC | Given / When / Then | Roles | Entry points | States | Source | Test |
|---|---|---|---|---|---|---|
| AC-1 | Given a failed card payment, when the retry job runs, then it retries up to 3 times with backoff | system | retry job | failed, declined | Ticket | unit test |
| AC-2 | ... | | | | FRD | UI check / API check / manual: why |
```

An AC that can't be met as written goes to the user before the gate, not into the plan.

## test-cases.md — generated from ac.md (stage 5)

Expand each AC's matrix into rows (role × entry point × state), keeping impossible combinations listed with `–` and
the reason so coverage gaps are visible. Each row is one check (a test, a scripted UI or API check, or a manual step
with evidence in `evidence/`).

```markdown
| Case | AC | Role | Entry point | State | Check | Before (base) | Now (branch) |
|---|---|---|---|---|---|---|---|
| TC-1 | AC-1 | system | retry job | declined | test/retry.spec.js "retries 3 times" | ❌ no retry | ✅ |

<!-- notes -->
```

**Now** is required for every row. **Before** (the same check on the base branch, in a temporary worktree) is for
behaviour changes and bug fixes; skip it for brand-new features.
