---
name: adopt-sdlc
description: Set ai-sdlc up for a team's project — draft project.json from the repos in the workspace, fill PROJECT.md with the system map, tune workflow.json gates, validate, and explain what the team should commit to their kit repo. Use when the user says "set up ai-sdlc for our project", "adopt ai-sdlc", "configure project.json", "fill PROJECT.md", or right after cloning ai-sdlc into a new workspace.
---

# Adopt ai-sdlc for a project

Goal: a team-owned copy of ai-sdlc (their own repo) whose `project.json`, `PROJECT.md` and `workflow.json` describe
their project, so every hook, skill and command fits it. Nothing here touches the project's repos.

1. **Workspace.** The project's repos should sit next to ai-sdlc folder. If they don't, ask which repos belong to
   the project and where they're hosted (or have the user clone them).
2. **Draft config:** `sdlc init` (prints a draft from the repos: host and org, base and environment branches, ticket
   key pattern from branch names, commit style from history, format/lint rules from each repo's tooling, seed or
   migrate scripts). Show it and confirm with the user, one topic at a time:
   - repos and their roles; any repo whose clone URL isn't `<host>/<org>/<name>` gets a `"url"`;
   - protected branches and environments (name → branch), and the base branch;
   - ticket tracker and key pattern; commit style (`ticket`, `conventional`, `none`), subject length, AI mentions;
   - **data sensitivity** (`phi`, `pii`, `financial`, `none`) and which file types are data files: always ask;
   - commands that touch real systems (`realSystems`: seeds, migrations, deploys, local runs against shared
     resources), optionally per repo;
   - `onEdit` rules per repo: formatter (`fix: true`), linter, and the related-test mapping if the repo has one.
   Then `sdlc init --write` (or edit `project.json` directly) and `sdlc validate`.
3. **PROJECT.md.** From the code: what the product does, each repo's role and runtime, how they talk (calls, queues,
   events, shared databases), shared contracts and their source of truth, where a change goes, how to run and verify
   locally without touching real systems, known issues. Keep it to what isn't obvious from the code. Use the
   `service-tracer` agent for cross-repo flows. Never include secrets, hostnames of production systems or customer data.
4. **Workflow.** Walk through `workflow.json`: which ticket types map to which profile; which gates each profile has;
   who approves (developer, or PM / QA listed under `people` with their tracker account ids); the `qa` gate's target
   branches (set them to the team's environment branches). `sdlc validate` again.
5. **Try it:** restart Claude Code in the workspace (hooks and settings load at start). The session start should list
   the repos; `sdlc check --tests` should say Ready; a push to a protected branch should be denied.
6. **Hand-off:** list the files to commit in the team's ai-sdlc repo (`project.json`, `PROJECT.md`, `workflow.json`, any
   team skills under `skills/`), and bump `VERSION` with a `CHANGELOG.md` entry. Committing and pushing need the
   user's go-ahead. Teammates then run `sdlc setup <folder> --from <their ai-sdlc repo url>`.
