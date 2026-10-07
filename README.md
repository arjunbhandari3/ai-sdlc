# AI SDLC

A ready-made Claude Code setup for a team's project: guardrails, a ticket-to-PR workflow with approval gates, review
agents and a `sdlc` command. Each team keeps its own copy and describes its project in three files; everything else
reads them.

## What a team gets

- **Guardrails (hooks)**: no reading `.env` files or keys, no secrets written into code or commits, no pushes to
  protected or environment branches, commit messages in the team's style, a confirmation before anything touches a
  real system (cloud CLIs, database shells, external writes, the team's own seed/deploy commands). Each edited file
  is formatted and checked with the repo's own tools.
- **Ticket workflow (`ship-ticket`)**: read the ticket → requirements and acceptance criteria → plan → build → test
  cases from the ACs, verified before and after → review → one approved "ship list" of commits, pushes and PRs →
  promotion to each environment. Approvals are enforced by a hook, not by trust, and can come from a PM or QA on the
  ticket.
- **Agents**: a branch reviewer, a security reviewer tuned to the project's data sensitivity, a cross-repo tracer.
- **`sdlc` command**: `sdlc setup` (new machine: clone everything, install), `sdlc status`, `sdlc check`, `sdlc ci`,
  `sdlc update`, `sdlc claude`, and more (`sdlc help`).

Works with GitHub, Bitbucket or GitLab; Jira, GitHub issues or no tracker; one repo or many. Python 3.9+ standard
library only.

## Adopt it for your project (once per team)

1. Create your team's copy of this repo (template, fork or import), e.g. `acme/payments-sdlc`, and add this repo as
   `upstream` so you can take ai-sdlc updates later.
2. Put it next to your project's repos and run the installer:
   ```sh
   cd ~/work/payments                       # the folder with your repos
   git clone git@github.com:acme/payments-sdlc.git
   python3 payments-sdlc/scripts/install.py
   ```
3. Describe the project. In Claude Code (`sdlc claude`), say **"adopt ai-sdlc for our project"**, or by hand:
   - `sdlc init` drafts `project.json` from your repos (branches, ticket keys, commit style, linters); review it and
     `sdlc init --write`. Set `data.sensitivity` and the commands that touch real systems.
   - Fill `PROJECT.md`: what the system is, how the repos talk, where a change goes, known issues.
   - Adjust `workflow.json`: profiles per ticket type, gates, approvers, the QA gate's target branches.
   - `sdlc validate`, restart Claude Code, then `sdlc check --tests`.
4. Commit those files to your team's copy. Examples for common setups are in [examples/](examples/).

## Join a team (each teammate)

```sh
git clone <team's ai-sdlc repo url> ~/work/payments/payments-sdlc
python3 ~/work/payments/payments-sdlc/scripts/launcher.py setup ~/work/payments
sdlc claude
```

`setup` clones every repo in `project.json` next to ai-sdlc (keeping any already there), links `.claude`, installs
the `sdlc` command and checks the machine. Then, in Claude Code: `ship PAY-12`. Tokens (Jira, Bitbucket) go in your
shell profile; see [docs/getting-started.md](docs/getting-started.md).

## Layout

| Path | Owned by | Contents |
|---|---|---|
| `project.json` | team | repos, git host and branches, ticket keys, commit style, data sensitivity, real-system commands, per-repo format/lint/test rules |
| `PROJECT.md` | team | the system map Claude reads every session |
| `workflow.json` | team | ticket profiles, approval gates, approvers |
| `skills/team-*`, `agents/team-*`, `workflows/team-*` | team | your own skills, agents and Claude workflows |
| `team/` | team | your own scripts (`team/scripts`), docs (`team/docs`), tests run by CI (`team/tests`) and PR template (`team/templates/pr.md`, overrides the kit's) |
| `CLAUDE.md`, `settings.json` | ai-sdlc | instructions and hook registration |
| `hooks/` | ai-sdlc | guardrails, with tests |
| `skills/`, `agents/` | ai-sdlc | the workflow skills and reviewers |
| `scripts/` | ai-sdlc | `sdlc` command, installer, launcher, ticket/Jira/Bitbucket helpers, with tests |
| `templates/`, `examples/` | ai-sdlc | PROJECT.md and PR templates; sample project.json files |
| `docs/` | ai-sdlc | guides and reference |
| `VERSION`, `CHANGELOG.md` | ai-sdlc | ai-sdlc version and what changed |
| `<workspace>/.sdlc/tickets/` | each person | ticket state, approvals, evidence (outside every repo) |

Keeping to this split means ai-sdlc updates merge cleanly into your copy: `git pull upstream main`.

## Docs

- [Getting started](docs/getting-started.md): setup, tokens, first ticket.
- [Configuration](docs/configuration.md): every `project.json` and `workflow.json` field.
- [Ticket workflow](docs/ticket-workflow.md): stages, gates, who approves.
- [Guardrails](docs/guardrails.md): what each hook blocks and what to do.
- [Reference](docs/reference.md): skills, agents, scripts.
- [Contributing](docs/contributing.md): changing ai-sdlc, versions, taking upstream updates.
