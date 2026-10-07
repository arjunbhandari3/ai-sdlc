# Configuration

Three files describe a team's project. `sdlc validate` checks the first and the third; the guards fail closed (deny)
while `project.json` is invalid, so a mistake can't silently switch a rule off.

## project.json

`sdlc init` drafts it from your repos. Anything left out takes the default shown.

```json
{
  "name": "Payments",
  "repos": [
    { "name": "payments-api", "role": "Backend API", "url": "git@github.com:acme/payments-api.git",
      "onEdit": [
        { "files": "*.js,*.ts", "run": "node_modules/.bin/prettier --write {file}", "fix": true },
        { "files": "*.js,*.ts", "run": "node_modules/.bin/eslint --fix --quiet {file}" },
        { "files": "src/*.js", "run": "node_modules/.bin/mocha {test}", "test": "test/{name}.spec.js" }
      ] }
  ],
  "git": { "host": "github", "org": "acme", "base": "main", "protectedBranches": ["main"],
           "environments": [{ "name": "dev", "branch": "develop" }, { "name": "qa", "branch": "qa" }] },
  "tickets": { "tracker": "jira", "pattern": "PAY-\\d+", "envBranch": "{ticket}-{env}" },
  "commits": { "style": "ticket", "maxSubjectLength": 72, "forbidAiMentions": true },
  "data": { "sensitivity": "financial", "dataFiles": [".csv", ".xlsx", ".pdf"] },
  "realSystems": [
    { "command": "npm run seed*", "reason": "Seeds write to whatever database is configured." },
    { "command": "npm start", "repo": "payments-api", "reason": "Starts against the real queue." }
  ]
}
```

| Field | Default | Meaning |
|---|---|---|
| `name` | folder name | shown at session start |
| `repos[].name` | — | folder name in the workspace (also the clone name) |
| `repos[].role` | — | shown at session start and used by the skills to place a change |
| `repos[].url` | `<host>/<org>/<name>` | clone URL when it doesn't follow the host/org pattern |
| `repos[].onEdit[]` | none | after Claude edits a file matching `files` (comma-separated globs on the path in the repo or the file name), run `run` in the repo. `{file}` absolute path, `{rel}` path in the repo, `{name}` name without extension, `{test}` the `test` template filled in (the rule runs only if that test exists). `fix: true` = formatter (exit code ignored); otherwise a failure goes back to Claude to fix. A relative program path that doesn't exist (tools not installed) skips the rule. |
| `git.host` | `github` | `github`, `bitbucket` or `gitlab`: clone URLs and PR commands |
| `git.org` | — | the org / workspace / group owning the repos |
| `git.base` | `main` | where feature branches start; what verification compares against |
| `git.protectedBranches` | `["main", "master"]` | never pushed to or deleted |
| `git.environments[]` | none | `{name, branch}` per environment; their branches are protected too, and `promote` / `sdlc targets` use them |
| `tickets.tracker` | `none` | `jira` (scripts/jira.py), `github`, `gitlab` (their CLIs), or `none` (paste the ticket) |
| `tickets.pattern` | `[A-Z][A-Z0-9]+-\d+` | ticket key regex; feature branches start with it (`PAY-12`, `PAY-12-retry`) |
| `tickets.envBranch` | `{ticket}-{env}` | branch used to resolve conflicts for one environment |
| `commits.style` | `ticket` | `ticket`: subject starts `PAY-12: ` (the branch's ticket; branches without one use the branch name). `conventional`: `feat(scope): ...`. `none`: no prefix rule |
| `commits.maxSubjectLength` | `72` | `0` turns the length check off |
| `commits.forbidAiMentions` | `true` | deny Claude/AI mentions and Co-authored-by / "Generated with" trailers in commit messages |
| `data.sensitivity` | `none` | `phi`, `pii`, `financial` or `none`: wording of warnings and the security reviewer's focus |
| `data.dataFiles` | `.csv .xlsx .xls .pdf` | staging these asks first; their names are never logged |
| `realSystems[]` | none | `{command, reason, repo?}`: a shell glob on the whole simple command (`npm run seed*`); Claude Code asks before running it (in that repo only, if `repo` is set) |

Built in, whatever the config: env files and keys, secret-looking content, `--no-verify`, pushes with
`--all`/`--mirror`, force pushes (ask), destructive git commands (ask), cloud and infra CLIs that change things
(ask), database shells (ask), external HTTP writes (ask).

## workflow.json

```json
{
  "profiles": {
    "story": { "match": { "types": ["Story", "Task"] }, "gates": ["requirements", "plan", "ship", "qa"],
               "stages": ["start", "requirements", "plan", "build", "verify", "review", "ship", "promote", "release"] },
    "hotfix": { "match": { "labels": ["hotfix"] }, "gates": ["ship"] }
  },
  "defaultProfile": "story",
  "gates": {
    "requirements": { "artifacts": ["frd.md", "ac.md"], "approvers": ["developer", "pm"], "blocks": "code" },
    "plan": { "artifacts": ["plan.md"], "approvers": ["developer"], "blocks": "code" },
    "ship": { "artifacts": ["ship-list.md"], "approvers": ["developer"], "blocks": "push" },
    "qa": { "artifacts": ["test-cases.md"], "approvers": ["qa", "developer"], "blocks": "promote", "targets": ["qa"] }
  },
  "people": { "pm": [{ "name": "Pat", "accountId": "<tracker account id>" }], "qa": [] }
}
```

- A ticket's **profile** comes from its type or labels (labels first). It lists the gates and the stages that apply.
- A **gate** names its artifacts (files in the ticket folder), its approvers and what it blocks until approved:
  `code` (editing the ticket's repo files on its branches), `push` (commits, pushes, PR create/update) or `promote`
  (PRs into its `targets`). Editing an approved artifact voids the approval.
- **Approvers:** `developer` is the person at the terminal, deciding with their own reply. `pm` and `qa` are the
  people listed under `people`, deciding with a ticket comment `Approved: <gate>` (Jira; `sdlc gates sync PAY-12`
  reads it). Any one listed approver role is enough.

## PROJECT.md

Free text Claude reads every session (imported by `CLAUDE.md`). [templates/PROJECT.md](../templates/PROJECT.md) has
the sections: what the system is, repos, how they talk, shared contracts, where a change goes, local development and
verification, known issues. Keep it to what the code doesn't make obvious; no secrets, production hostnames or
customer data.
