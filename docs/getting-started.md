# Getting started

## 1. Prerequisites

- Python 3.9+ and git.
- Claude Code (the `claude` CLI, or the VS Code / JetBrains extension).
- Access to your project's repos (SSH key, or HTTPS with `--https`).
- For PRs: Bitbucket uses an API token (below); GitHub uses the `gh` CLI (`gh auth login`); GitLab uses `glab`.

## 2. Set up a workspace

A workspace is one folder holding the project's repos side by side, plus the team's ai-sdlc copy linked as `.claude`.

```sh
mkdir -p ~/work/payments && cd ~/work/payments
git clone <team's ai-sdlc repo url>                       # e.g. payments-sdlc
python3 payments-sdlc/scripts/launcher.py setup . # clones the repos, links .claude, installs `sdlc`, checks
```

Several projects? One workspace each; `sdlc` uses the workspace you're in (`cd` into it), or the last one set up.
Another project later: `sdlc setup ~/work/mobile --from <their ai-sdlc repo url>`.

If `~/.local/bin` isn't on your PATH, the installer prints the line to add to your shell profile.

## 3. Tokens (only what your project uses)

Put these in your shell profile (`~/.zshrc`, `~/.bashrc`), never in a file in a repo, never in a chat.

**Jira** (`tickets.tracker: "jira"`): id.atlassian.com → Security → API tokens → create a token with scopes
`read:jira-work` and `read:jira-user` (add `write:jira-work` only if PMs/QA approve gates through ticket comments and
you want Claude to post the artifacts).

```sh
export JIRA_SITE="<your-site>.atlassian.net"
export JIRA_EMAIL="you@yourcompany.com"
export JIRA_API_TOKEN="<token>"
```

**Bitbucket** (`git.host: "bitbucket"`): an API token with `read:pullrequest` and `write:pullrequest`.

```sh
export BITBUCKET_EMAIL="you@yourcompany.com"
export BITBUCKET_API_TOKEN="<token>"
```

Check: `sdlc jira check`, `python3 .claude/scripts/bitbucket.py check`, `gh auth status`.

## 4. Check and start

```sh
sdlc check --tests      # tools, tokens (set or not, never their values), link, config, hooks, version
sdlc claude             # Claude Code in the workspace root
```

Always start Claude Code in the workspace root (not inside one repo): the hooks, skills and settings load from
`.claude` there. The session starts with a list of the repos and their branches.

## 5. Your first ticket

In Claude Code: `ship PAY-12`. Claude reads the ticket, writes the requirements and acceptance criteria and waits for
your "yes"; then the plan (another "yes"); builds; verifies every AC; reviews; and shows one ship list of commits,
pushes and PRs for a final "yes". `sdlc status PAY-12` shows where it is. See [ticket-workflow.md](ticket-workflow.md).

## Staying current

When the session start says ai-sdlc is behind: `sdlc update` shows the new changelog entries, `sdlc update --pull`
takes them. Do what each entry's **After pulling** line says (restart Claude Code, or rerun `install.py`).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No repo list at session start, no hooks | Claude Code started inside a repo, or `.claude` isn't linked | start in the workspace root; rerun `install.py` |
| Every tool call denied with "project.json is invalid" | a config error (the guards fail closed) | `sdlc validate`, fix the field it names |
| `sdlc: command not found` | `~/.local/bin` not on PATH | add the line the installer printed; or `python3 .claude/scripts/sdlc.py` |
| A command is blocked that you need | a guard rule | read the reason; if the rule is wrong for your project, change `project.json` or the hook (with a test) |
