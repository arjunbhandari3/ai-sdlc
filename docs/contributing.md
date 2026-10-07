# Contributing

Two kinds of change, in two places:

- **Your project** (repos, branches, rules, approvers, system map, team skills): in your team's copy, in the files
  the team owns: `project.json`, `PROJECT.md`, `workflow.json`, `skills/team-*`, `agents/team-*`, `workflows/team-*`
  and everything under `team/` (scripts, docs, tests, `templates/pr.md`). No version bump.
- **ai-sdlc** (hooks, its skills and agents, scripts, templates, `CLAUDE.md`, `settings.json`): in this repo
  (upstream), so every team gets it. Teams then take it with `git pull upstream main`.

## Changing ai-sdlc

1. Branch from `main`, make the change, add or update tests:
   - hooks: `hooks/tests/test_hooks.py` builds a throwaway workspace with its own `project.json`; add a case that
     must still be blocked, not only one that's allowed;
   - scripts: `scripts/tests/test_scripts.py`.
2. Keep hooks and scripts on the Python standard library (3.9+). Anything project-specific goes in `project.json`, not
   in code.
3. Bump `VERSION` and add a `CHANGELOG.md` entry on top: **major** when people must act (config format, hook
   registrations in `settings.json`, folder moves), **minor** for something new, **patch** for a fix. End the entry
   with an **After pulling:** line when people must restart Claude Code (any `settings.json` change) or rerun
   `install.py`.
4. `sdlc ci` runs what CI runs: hook and script tests, `sdlc validate`, the version check, `sdlc docs --check`, ruff.
5. PR with one reviewer. Loosening a guard (allowing something that was blocked) needs a reviewer who knows why it
   was blocked.

## Docs

`docs/` is plain Markdown. The skills, agents and scripts tables (reference.md) and the hook and permission tables
(guardrails.md) are generated between `<!-- generated:NAME -->` markers by `sdlc docs` from: each skill's and agent's
`description` (first sentence; quoted phrases become "Say"), each script's docstring, `HOOKS` in `hooks/run.py`, and
`settings.json`. A new hook module also needs a row in the hand-written guardrails table; `sdlc docs` says so.

## Taking ai-sdlc updates into a team's copy

```sh
git -C .claude remote add upstream <ai-sdlc repo url>     # once
git -C .claude fetch upstream && git -C .claude merge upstream/main
```

Conflicts should only appear in files you changed that ai-sdlc also owns; keep your changes in the team-owned files
and they won't. Read the new `CHANGELOG.md` entries and do their **After pulling** steps, then push to your team's
copy (teammates get it with `sdlc update --pull`).
