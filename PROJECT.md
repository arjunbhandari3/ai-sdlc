# <Project name>

<!-- Claude reads this every session (CLAUDE.md imports it). Keep it to what isn't obvious from the code: what the
system is for, how the repos fit together, and the traps. The `adopt-sdlc` skill can draft it with you. -->

<One paragraph: what the product does, who uses it, what data it handles.>

## Repos

| Repo | Role | Runs as | Talks to |
|---|---|---|---|
| `<repo>` | <Backend API> | <Docker on Kubernetes> | <database, queue, other repos> |

## How the pieces talk

<Calls, queues, events and shared databases between the repos: who publishes, who consumes, the message shape
lives where. A small ASCII diagram is fine.>

## Shared data and contracts

<Schemas, types or constants copied between repos (and which copy is the source of truth). When one changes, the
others must change in the same ticket.>

## Where a change goes

| I want to... | Change | Also check |
|---|---|---|
| <Add an endpoint> | `<api repo>` | <the client that calls it> |

## Local development and verification

<How to run each repo locally without touching real systems; which commands are safe; how to verify a change
(tests, fake-data UI checks) and where evidence for PRs goes.>

## Known issues

<Bugs, security gaps and drift that aren't fixed yet, so nobody copies the pattern.>
