# Reference

The tables below are generated from the files they describe (`sdlc docs`); edit the source, not the table.

## Skills (`skills/`)

<!-- generated:skills from each SKILL.md's description; edit there, then run sdlc docs -->
| Skill | Say | Does |
|---|---|---|
| `ship-ticket` | `ship PAY-12`, `work on PAY-12 end to end`, `continue PAY-12` | Run a ticket through the whole delivery flow in order |
| `adopt-sdlc` | `set up ai-sdlc for our project`, `adopt ai-sdlc`, `configure project.json` | Set ai-sdlc up for a team's project |
| `pr-description` | `write up these changes for review` | Write a pull request title and description in the team's template (team/templates/pr.md, else templates/pr.md), built from the ticket's acceptance criteria and verification results, and create or update the PR on the project's git host when approved |
| `promote` | `promote PAY-12 to qa`, `PR to develop/staging`, `create the -qa branch` | Promote a ticket's feature branch to an environment |
| `read-ticket` | `read PAY-12`, `what is PAY-12 about`, `open the ticket` | Read a ticket from the project's tracker (read-only) and turn it into working context |
| `review-branch` | `review my branch`, `review the PR`, `review the latest commits` | Review the commits on a branch (or an open PR) in a workspace repo and draft line-anchored review comments; post them only after the user approves |
| `start-ticket` | `start PAY-12`, `create a branch for PAY-12`, `new ticket` | Start work on a ticket in one or more workspace repos |
| `verify` | `verify PAY-12`, `test the change`, `does it meet the ACs` | Verify a ticket's change against its acceptance criteria with fake data |
<!-- /generated:skills -->

Team skills live next to these as `skills/team-<name>/SKILL.md`. To list them in your own docs, put a
`<!-- generated:team-skills -->` / `<!-- /generated:team-skills -->` pair in a page under `team/docs/`; `sdlc docs`
fills it.

## Agents (`agents/`)

<!-- generated:agents from each agent's description; edit there, then run sdlc docs -->
| Agent | Does |
|---|---|
| `branch-reviewer` | Reviews the commits on a branch in a workspace repo (or a PR's changes) and returns line-anchored review comments ready to post |
| `security-reviewer` | Reviews a diff in a workspace repo for leaks of sensitive data (patient, personal or financial, per data.sensitivity in project.json) and for security issues |
| `service-tracer` | Read-only tracer across the workspace repos |
<!-- /generated:agents -->

## Scripts (`scripts/`)

<!-- generated:scripts from each script's docstring or header comment; edit there, then run sdlc docs -->
| Script | Language | Use |
|---|---|---|
| `bitbucket.py` | Python | Bitbucket Cloud helper: find, create and update PRs (with default reviewers), put screenshots in descriptions, post review comments |
| `check_targets.py` | Python | Before a ship list: how a branch merges into each environment, read-only |
| `docs.py` | Python | Refresh the generated reference tables in README.md and docs/*.md (skills, agents, scripts, hooks, permissions) |
| `init_project.py` | Python | Draft project.json from the repos already in this workspace, so a team starts from facts, not a blank file |
| `install.py` | Python | Set up and check a workspace for ai-sdlc |
| `jira.py` | Python | Read a Jira ticket and save it for the ticket workflow; post a comment when the workflow asks for one |
| `launcher.py` | Python | The `ai-sdlc` command on your PATH, also as `sdlc` (install.py copies this file to ~/.local/bin/ai-sdlc and links ~/.local/bin/sdlc to it) |
| `sdlc.py` | Python | The `sdlc` command: the local, read-only side of the ai-sdlc |
| `tickets.py` | Python | A ticket's local working files: status for the team, a dashboard of all tickets, and cleanup when it's done |
| `version_check.py` | Python | CI: ai-sdlc's version and changelog agree, and a PR that changes behaviour bumps the version |
| `lib/reference_tables.py` | Python | Reference tables generated from the files they describe, so the docs can't drift (standard library only) |
| `lib/workspace_paths.py` | Python | Shared bits for the Python scripts: where things are, and the project config (read through hooks/_hooklib.py, so the scripts and the guards always agree) |
<!-- /generated:scripts -->

Python, standard library only, so nobody needs `pip install` to use ai-sdlc.
