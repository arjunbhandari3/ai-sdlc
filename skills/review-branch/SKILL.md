---
name: review-branch
description: Review the commits on a branch (or an open PR) in a workspace repo and draft line-anchored review comments; post them only after the user approves. Use when the user says "review my branch", "review the PR", "review the latest commits", "review PAY-12", or "/review-branch <repo> [branch] [base]".
argument-hint: <repo> [branch] [base]
---

# Review a branch

1. **Scope:** repo and branch (default: the repo's current branch); base = the PR's target, else `git.base` from
   `.claude/project.json`. `git -C <repo> fetch origin`, then the diff `origin/<base>...<branch>`. For a re-review,
   only the commits since the last reviewed one (`.sdlc/tickets/<ticket>/reviews/last-review-<repo>`).
2. **Review:** run the `branch-reviewer` agent on that range. Also run `security-reviewer` when the diff touches
   data handling, auth, logging, error responses, exports, emails/notifications or outbound calls (always when
   `data.sensitivity` isn't `none`). Run them in parallel.
3. **Check the findings** against the code before showing them: drop what the code already handles, keep the rest
   with file:line, why it matters, and a concrete fix. Rank: blocker, major, minor, nit.
4. **Show** the findings and save them to `.sdlc/tickets/<ticket>/reviews/<repo>-<date>.md`. Fixing them is the
   user's call (in ship-ticket, blockers send the ticket back to build).
5. **Post (only on request, after approval of the exact comments):**
   - Bitbucket: write the comments JSON, then `python3 .claude/scripts/bitbucket.py post <repo> <pr-id> <comments.json>`
     (it always asks), and `bitbucket.py mark <repo> <branch> <sha>` to remember the reviewed commit.
   - GitHub: `gh pr review <number> --repo <org>/<repo> --comment --body-file <file>` (line comments via `gh api`).
   - GitLab: `glab mr note <number> --message "$(cat <file>)"`.
