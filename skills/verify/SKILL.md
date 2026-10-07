---
name: verify
description: Verify a ticket's change against its acceptance criteria with fake data — expand ac.md into test cases, run each on the branch (and on the base branch for behaviour changes), and record results and evidence per AC. Use after building, or when the user says "verify PAY-12", "test the change", "does it meet the ACs", "run the test cases".
argument-hint: TICKET
---

# Verify a ticket

Inputs: `.sdlc/tickets/<ticket>/ac.md` (approved) and `plan.md`. Output: `test-cases.md` with results, evidence in
`evidence/`, and `testCases` in `ticket.json`.

1. **Cases.** Expand each AC's matrix into rows in `test-cases.md` ([template](../ship-ticket/requirements.md)):
   role × entry point × state, impossible combinations kept with `–` and the reason. Each row names its check.
2. **Checks, cheapest that proves the AC:**
   - A unit or integration test in the repo (add one when the AC is new behaviour; follow the repo's test style).
   - A scripted check against a local run with fake data (an API call with `curl` to localhost, a browser check with
     the repo's own e2e tool if it has one). Never point a check at a shared or production system; the hooks ask
     before external writes, database shells and cloud CLIs.
   - Manual, with a reason and a screenshot or output saved in `evidence/`.
3. **Now:** run every case on the branch. **Before:** for behaviour changes and bug fixes, run the same checks on the
   base branch in a temporary worktree (`git -C <repo> worktree add <tmp> origin/<base>`; remove it afterwards), so
   the PR shows what changed.
4. **Whole suite:** run each touched repo's test and lint commands (from its README or package scripts) on the branch.
5. **Report per AC:** met (cases n/n, evidence), not testable here (why), or not met → back to build. Look at every
   screenshot you take before calling a case passed.

Fake data only: no real customer records in fixtures, screenshots or evidence (`data.sensitivity` in project.json
says how careful to be).
