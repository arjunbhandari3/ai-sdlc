# Changelog

What changed in ai-sdlc, newest first. After `sdlc update --pull` (or merging `upstream/main` into a team's copy), read
the entries above your old version and do what their **After pulling** line says. Versions: **major** when people
must act, **minor** for something new, **patch** for fixes. Team-owned files (project.json, PROJECT.md,
workflow.json, team-* skills and agents) and docs need no version.

## 0.1.2 (2026-10-07)

- Generated docs: team agents (`agents/team-*`) stay out of the kit's agents table, so a team's copy keeps
  `docs/reference.md` unchanged; list them with a `team-agents` table under `team/`.
- **After pulling:** nothing.

## 0.1.1 (2026-10-07)

- `settings.json`: the read-only `git -C <repo> status|log|diff|branch|fetch` rules now match (they mixed `*` with
  the `:*` prefix syntax, which Claude Code never matches, so those commands asked every time).
- **After pulling:** restart Claude Code.

## 0.1.0 (2026-10-07)

First version, extracted from a production team setup and made configurable.

- `project.json`: repos, git host and branches, ticket keys, commit style, data sensitivity, real-system commands,
  per-repo format/lint/test rules on edit. `sdlc init` drafts it from the repos in a workspace.
- Hooks through one entry point (`hooks/run.py`): `guard_secrets`, `guard_shell`, `gates`, `after_edit`,
  `session_context`; guards fail closed, including on an invalid project.json.
- Ticket workflow (`ship-ticket` and stage skills `read-ticket`, `start-ticket`, `verify`, `review-branch`,
  `pr-description`, `promote`) with approval gates from `workflow.json`; `adopt-sdlc` to set ai-sdlc up for a project.
- Agents: `branch-reviewer`, `security-reviewer`, `service-tracer`.
- `sdlc` command (launcher on your PATH): setup, init, validate, status, dashboard, done, gates, jira, targets, check,
  ci, docs, update, claude.
- `team/` for a team's own scripts, docs, tests (run by CI and `sdlc ci`) and PR template; with `workflows/team-*`, no
  version bump needed.
- CI for GitHub Actions and Bitbucket Pipelines.

**After pulling:** run `python3 .claude/scripts/install.py`, then restart Claude Code.
