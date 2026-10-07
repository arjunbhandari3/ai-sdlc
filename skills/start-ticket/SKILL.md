---
name: start-ticket
description: Start work on a ticket in one or more workspace repos — create the feature branch named after the ticket from the project's base branch, with a clean tree and dependencies that match. Use when the user says "start PAY-12", "create a branch for PAY-12", "new ticket", or "set up a branch in <repo>".
argument-hint: TICKET [repo ...]
---

# Start a ticket

For each repo (as named, or from ship-ticket): the base is `git.base` in `.claude/project.json` (default `main`).

1. `git -C <repo> status --porcelain` must be empty; otherwise list the files and ask (never stash or discard them).
2. `git -C <repo> fetch origin --prune`.
3. Branch named exactly the ticket key (e.g. `PAY-12`):
   - exists locally: `git -C <repo> switch PAY-12`, then show `git -C <repo> log --oneline origin/<base>..HEAD`;
   - exists only on origin: `git -C <repo> switch --track origin/PAY-12`;
   - new: `git -C <repo> switch -c PAY-12 origin/<base>`.
4. Dependencies: if the lockfile differs from the branch you came from, install with the repo's own tool (the lockfile
   says which: `package-lock.json` → `npm ci`, `yarn.lock` → `yarn install --frozen-lockfile`, `pnpm-lock.yaml` →
   `pnpm install --frozen-lockfile`, `poetry.lock` → `poetry install`, `uv.lock` → `uv sync`).
5. Report per repo: branch, base commit, whether it was new, and anything installed.

Never branch from an environment branch, and never start work on a protected branch.
