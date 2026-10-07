# Guardrails

Hooks in `.claude/hooks/` run around every tool call Claude makes. `settings.json` registers one entry point,
`hooks/run.py`, which runs the modules for each event in one process and combines their answers (block beats deny
beats ask). A guard that crashes denies the call with the error (fail closed); a helper that crashes is skipped (fail
open). While `project.json` is invalid, the guards deny with the reason until it's fixed.

| Hook | When | Blocks or asks | If it stops you |
|---|---|---|---|
| `guard_secrets` | reads, edits, writes, searches, shell | reading or writing `.env` files, keys and credential files; dumping environment variables; fetching secrets from a cloud secret store; writing credentials into files (asks for likely secrets such as JWTs) | intended: use `.env.example` for variable names and load secrets at runtime |
| `guard_shell` | shell | pushes to protected or environment branches, `--all`/`--mirror`, `--no-verify`; committing env files, keys or secrets; commit messages that break `commits.*`; **asks** before force pushes, destructive git commands, data files, cloud/infra CLIs that change things, database shells, external HTTP writes and the project's `realSystems` commands | use a feature branch and a PR; fix the message; approve a real-system command only if you mean it |
| `gates` | your messages; edits, shell | for tickets with gates on: editing the ticket's code before its requirements and plan are approved; commits, pushes and PRs before the ship list is approved; PRs into the QA gate's targets before QA approves; any write to the approval records | answer the pending approval; `sdlc gates status PAY-12` |
| `after_edit` | after edits | runs the repo's `onEdit` rules on the edited file (formatters, linters, the related test) | fix what it reports |
| `session_context` | session start | lists the repos, their branches and state, and ai-sdlc version | — |

Every block, deny and ask is logged by hook and rule id (never content, commands or file names of data files) in
`~/.claude/logs/tool_audit.jsonl`.

## When a hook blocks something legitimate

Claude is told not to work around a block (no renaming files to dodge a pattern, no splitting a command). If a rule
is wrong for your project, change `project.json`; if it's wrong for everyone, change the hook in a PR with a test.

### Registered modules

<!-- generated:hooks from HOOKS in hooks/run.py and each module's docstring; edit there, then run sdlc docs -->
| Module | Event | Tools | Kind | Does |
|---|---|---|---|---|
| `session_context` | session-start | all | helper (fails open) | Print each project repo's branch and working-tree state, and ai-sdlc's version (stdout becomes session context) |
| `gates` | prompt | all | guard (fails closed) | Approval gates for tickets shipped with ship-ticket, configured in workflow.json |
| `guard_secrets` | pre-tool | Bash, Edit, Glob, Grep, MultiEdit, NotebookEdit, Read, Write | guard (fails closed) | Keep secrets out of reach |
| `guard_shell` | pre-tool | Bash | guard (fails closed) | Shell command safety, configured by project.json |
| `gates` | pre-tool | Bash, Edit, MultiEdit, NotebookEdit, Write | guard (fails closed) | Approval gates for tickets shipped with ship-ticket, configured in workflow.json |
| `after_edit` | post-tool | Edit, MultiEdit, Write | helper (fails open) | Tidy and check the file Claude just edited, with the repo's own tools |
<!-- /generated:hooks -->

### Command permissions

From `settings.json`: commands Claude Code runs without asking, and ones it always asks about. Everything else asks as
usual, and the hooks above still apply.

<!-- generated:permissions from settings.json; edit there, then run sdlc docs -->
| Command | Claude Code |
|---|---|
| `python3 .claude/scripts/bitbucket.py post …` | always asks |
| `python3 .claude/scripts/jira.py comment …` | always asks |
| `python3 .claude/scripts/sdlc.py status …` | runs without asking |
| `python3 .claude/scripts/sdlc.py dashboard …` | runs without asking |
| `python3 .claude/scripts/sdlc.py validate …` | runs without asking |
| `python3 .claude/scripts/sdlc.py gates status …` | runs without asking |
| `python3 .claude/scripts/sdlc.py gates request …` | runs without asking |
| `python3 .claude/scripts/sdlc.py gates enable …` | runs without asking |
| `python3 .claude/scripts/sdlc.py gates sync …` | runs without asking |
| `python3 .claude/scripts/sdlc.py gates validate …` | runs without asking |
| `python3 .claude/scripts/sdlc.py jira fetch …` | runs without asking |
| `python3 .claude/scripts/sdlc.py jira comments …` | runs without asking |
| `python3 .claude/scripts/sdlc.py jira check …` | runs without asking |
| `python3 .claude/scripts/sdlc.py targets …` | runs without asking |
| `python3 .claude/scripts/sdlc.py check …` | runs without asking |
| `python3 .claude/scripts/sdlc.py ci …` | runs without asking |
| `python3 .claude/scripts/sdlc.py docs …` | runs without asking |
| `python3 .claude/scripts/sdlc.py init …` | runs without asking |
| `python3 .claude/scripts/sdlc.py update` | runs without asking |
| `python3 .claude/scripts/jira.py fetch …` | runs without asking |
| `python3 .claude/scripts/jira.py comments …` | runs without asking |
| `python3 .claude/scripts/jira.py check` | runs without asking |
| `python3 .claude/scripts/bitbucket.py check` | runs without asking |
| `python3 .claude/scripts/bitbucket.py find-pr …` | runs without asking |
| `python3 .claude/scripts/bitbucket.py preview …` | runs without asking |
| `python3 .claude/scripts/tickets.py status …` | runs without asking |
| `python3 .claude/scripts/check_targets.py …` | runs without asking |
| `python3 .claude/hooks/gates.py status …` | runs without asking |
| `python3 .claude/hooks/gates.py request …` | runs without asking |
| `python3 .claude/hooks/gates.py enable …` | runs without asking |
| `python3 .claude/hooks/gates.py sync …` | runs without asking |
| `python3 -m unittest …` | runs without asking |
| `git -C * status …` | runs without asking |
| `git -C * log …` | runs without asking |
| `git -C * diff …` | runs without asking |
| `git -C * branch …` | runs without asking |
| `git -C * fetch …` | runs without asking |
| `git status …` | runs without asking |
| `git log …` | runs without asking |
| `git diff …` | runs without asking |
| `git show …` | runs without asking |
| `git branch …` | runs without asking |
| `git fetch …` | runs without asking |
<!-- /generated:permissions -->
