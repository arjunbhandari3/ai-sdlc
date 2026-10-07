# Workspace

This folder is a workspace: the project's git repos side by side, plus ai-sdlc (linked as `.claude`). It is not a
git repo itself. What the project is, its repos and how they talk to each other:

@PROJECT.md

The rules the hooks enforce come from `.claude/project.json` (repos, protected and environment branches, ticket key
pattern, commit style, data sensitivity, commands that touch real systems) and `.claude/workflow.json` (approval
gates). Read them when a rule matters; don't restate them from memory. `sdlc validate` checks both.

## Conventions

- Each folder is its own git repo on its own branch. Always `git -C <repo> ...`; never assume one branch.
- Feature branches are named after the ticket (`tickets.pattern`, e.g. `PAY-12`), cut from `git.base`. Never push to
  a protected or environment branch (the hook blocks it); changes reach them through PRs.
- Promotion (skill `promote`): the feature branch is PR'd into each environment branch separately. A clean dry-run
  merge → PR the feature branch directly; conflicts → an env branch `<ticket>-<env>` (from the feature branch),
  resolved there, the same way in every environment. New changes always go on the feature branch.
- Commits follow `commits.style` in project.json (the hook checks it); commit each repo separately, only when asked
  (an approved ship list counts for the commits it lists). Stage specific paths, never `git add -A`, never env files,
  keys or data files. Never skip hooks (`--no-verify`).
- Secrets come from the project's secret store or env vars documented in `.env.example`. Never read, print or grep
  `.env` files or keys; the hooks block it.
- Data sensitivity is `data.sensitivity` in project.json. Treat ticket text, logs, exports and fixtures accordingly:
  only fake data in tests, screenshots, commits, PRs and comments.

## Writing code (every feature and fix)

- **Docs:** short doc comments on exported functions and components whose purpose or parameters aren't obvious; a
  comment only where the code can't say why. No restating the code, no history or TODO noise.
- **Names:** short, clear and consistent with the surrounding code and the repo's existing terms.
- **Simple:** the smallest change that meets the acceptance criteria; follow the existing pattern.
- **Suggest, don't sneak in:** list improvements outside the ticket's scope (what, why, rough effort) instead of
  doing them.

## ai-sdlc (`.claude/`)

- Ticket flow: `ship-ticket` reads the ticket (`read-ticket`), writes the requirements and acceptance criteria
  (`frd.md`, `ac.md`), plans, builds, turns the ACs into test cases and verifies them, reviews, and ships, with the
  approvals in `workflow.json`: only the user's own reply (or a listed approver's ticket comment) approves; edits,
  commits, pushes and PRs wait for their gate. Everything for a ticket lives in `<workspace>/.sdlc/tickets/<ticket>/`.
- Hooks (`.claude/hooks/`, one entry point `run.py`; guards fail closed, helpers fail open): `guard_secrets`,
  `guard_shell` (git safety, commit rules, real systems), `gates`, `after_edit` (each repo's `onEdit` format/lint/test
  rules), `session_context`. Don't work around a block; report it. After changing a hook run
  `python3 -m unittest discover -s .claude/hooks/tests`.
- Team-owned files: `project.json`, `PROJECT.md`, `workflow.json`, `skills/team-*`, `agents/team-*`, `workflows/team-*`
  and `team/` (the team's scripts, docs, tests and PR template). Team skills call team scripts as
  `.claude/team/scripts/...`.
- `sdlc` (`.claude/scripts/sdlc.py`) wraps the local, read-only scripts. Never add outward steps (PRs, comments, pushes)
  to it, so the guards keep seeing them.
- Outward steps (commit, push, PR, review or ticket comments) only after the user approves that exact step or the
  ship list containing it.
- A skill started without a required argument (its `argument-hint`, e.g. the ticket for `/ship-ticket`): ask for it
  in one short question before running any command.
