---
name: promote
description: Promote a ticket's feature branch to an environment — dry-run merge it into the environment branch; clean → PR the feature branch directly; conflicts → create or update the <ticket>-<env> branch, merge the target into it, resolve the same way in every environment, verify, push and open the PR. Use when the user says "promote PAY-12 to qa", "PR to develop/staging", "create the -qa branch", or "resolve conflicts for the PR".
argument-hint: <repo> TICKET to <env> [and <env> ...]
---

# Promote to an environment

Environments and their branches: `git.environments` in `.claude/project.json`; env branch names: `tickets.envBranch`
(default `{ticket}-{env}`). Git always as `git -C <repo>`. Never PR into a protected release branch from here.

## Per environment, in the order named

1. **Preflight:** clean tree; the feature branch isn't protected or an env branch; `fetch origin --prune`;
   fast-forward the feature branch to `origin/<feature>` if it's behind (stop if diverged).
2. **Dry run:** `python3 .claude/scripts/check_targets.py <repo> <feature> <target>` (or
   `git -C <repo> merge-tree --write-tree --name-only <feature> origin/<target>`: exit 0 clean, 1 conflicts).
3. **Clean:** PR `<feature>` → `<target>` directly; no env branch, even if one exists from earlier.
4. **Conflicts:** use `<ticket>-<env>`: create it from `<feature>` if missing, else merge `<feature>` into it; then
   `git -C <repo> merge --no-edit origin/<target>` and resolve:
   - Resolve by intent: the ticket's change and everything the target gained both survive. Read both sides' history
     first (`git log -5 origin/<target> -- <file>`).
   - Same resolution in every environment: check how an earlier env branch for this ticket resolved the same hunk
     and repeat it; if it can't apply, stop and ask.
   - Lockfiles: take the target's, regenerate if dependencies changed. Env-specific config (CI, deploy files): prefer
     the target's. Unclear business logic: stop and ask.
   - No conflict markers left (`grep -nE '^(<<<<<<<|=======|>>>>>>>)'`), `git diff --check`, stage files by name,
     `git commit --no-edit`.
5. **Verify:** only this ticket's commits (`git log --oneline --no-merges origin/<target>..<source>`); run the repo's
   tests and lint. A fix that isn't merge-specific goes on the feature branch, then promote again.
6. **Ship it:** push `<source>` and open the PR with `pr-description` (list each resolved conflict and how), only as
   part of an approved ship list (or the user's explicit go-ahead). PR commands by host:
   - Bitbucket: `python3 .claude/scripts/bitbucket.py create-pr <repo> <source> <target> "<title>" <description.md>`
   - GitHub: `gh pr create --repo <org>/<repo> --head <source> --base <target> --title "<title>" --body-file <file>`
   - GitLab: `glab mr create --source-branch <source> --target-branch <target> --title "<title>" --description "$(cat <file>)"`
7. Switch back to the feature branch. Report per environment: dry run, source (direct or env branch), conflicts and
   their resolutions, tests, PR link.
