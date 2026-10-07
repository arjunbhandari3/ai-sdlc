---
name: pr-description
description: Write a pull request title and description in the team's template (team/templates/pr.md, else templates/pr.md), built from the ticket's acceptance criteria and verification results, and create or update the PR on the project's git host when approved. Use when the user asks for a PR, pull request, merge request, PR description, or "write up these changes for review".
argument-hint: <repo> [TICKET] [target]
---

# PR description

1. **Facts:** the commits and diff (`git -C <repo> log --oneline origin/<target>..<branch>`, `diff --stat`), the
   ticket's `ac.md` and `test-cases.md` results, `plan.md` (deploy order, config or migration notes), and the
   resolved conflicts if this is an env branch.
2. **Title:** in the commit style (`commits.style`): `PAY-12: Retry failed card payments` or
   `feat(payments): retry failed card payments`.
3. **Body:** fill `.claude/team/templates/pr.md` if the team has one, else `.claude/templates/pr.md`. Short and concrete: what changes for users, each AC with its result and
   evidence, how it was verified, deploy notes. No customer data, no secrets, no AI mentions unless the team allows
   them (`commits.forbidAiMentions`).
4. Save as `.sdlc/tickets/<ticket>/pr/<repo>-<target>.md` and show it.
5. **Create or update only inside an approved ship list** (or on the user's explicit go-ahead):
   - Bitbucket: `python3 .claude/scripts/bitbucket.py create-pr <repo> <source> <target> "<title>" <file>` (adds the
     repo's default reviewers), or `update-pr <repo> <id> <file>`. Screenshots: `bitbucket.py assets` + `preview`.
   - GitHub: `gh pr create --repo <org>/<repo> --head <source> --base <target> --title "<title>" --body-file <file>`
     (`gh pr edit <n> --body-file <file>` to update).
   - GitLab: `glab mr create --source-branch <source> --target-branch <target> --title "<title>" --description "$(cat <file>)"`.
   Record the link in `ticket.json`.
