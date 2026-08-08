# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Which repo

Issues live on **`origin` = `Habit130/squirrel`** (your fork). Never `upstream`
(`rime/squirrel`) — that's the official project, pull-only.

This repo has two remotes, so `gh` does **not** reliably infer the right one: with no
default set it resolved to `rime/squirrel`. The default is pinned via
`gh repo set-default Habit130/squirrel` (stored as `remote.origin.gh-resolved` in
`.git/config`). Verify with `gh repo set-default --view` before any write operation; if it
ever reports `rime/squirrel`, stop and re-pin it.

Issues were disabled on the fork (GitHub's default for forks) and have been enabled via
`gh api -X PATCH repos/Habit130/squirrel -f has_issues=true`.

### Tickets whose code lives in another repo

The candidate-reranking plugin, including later-phase implementation tickets, is written in a separate repository — see
"Plugin source repository" in `AGENTS.md`. The split is:

- **Issues, map, spec, decisions, blocking edges** — always here, `Habit130/squirrel`. A
  session working in the plugin repo still claims, comments on and closes its ticket here.
- **Code PRs** — in the plugin repo, against its own default branch. Nothing about the
  plugin's source is mirrored into this repo.

So `gh repo set-default Habit130/squirrel` stays correct for every `gh issue` call; only
`gh pr` calls run with the plugin repo as the working directory.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

## Dispatch and acceptance sessions

An orchestration session coordinates issue delivery rather than implementing the tickets it dispatches. Its scope is to inspect the live frontier, prepare prompts for execution sessions, prevent shared-state collisions, and independently accept or reject returned work. Keep feature implementation and orchestration in separate sessions so the acceptance pass does not inherit the executor's assumptions.

### Classify execution autonomy

Classify every ticket at dispatch time by how much implementation judgment remains:

- **Easy**: the issue, spec, ADRs, and code precedents already fix the implementation seam, required behavior, important edge cases, and verification path. The execution session mainly follows established decisions.
- **Hard**: the issue is ready to build, but the execution session must still explore the codebase, choose among valid implementation seams, reconcile competing constraints, or design non-obvious tests. Give it broad end-to-end ownership within the issue boundary.

Difficulty does not measure code volume, duration, or technical prestige. A large mechanical migration can be easy; a small change with an ambiguous lifecycle seam can be hard. This classification is also separate from triage readiness: `ready-for-agent` permits unattended work, while easy/hard determines the executor autonomy the prompt should request. A ticket with an unresolved product or specification decision is not hard-AFK; remove it from the AFK frontier and resolve that decision with the owner first.

### Dispatch workflow

1. Refresh `origin`, the parent issue's sub-issues, native dependency counts, assignees, open PRs, and recent issue comments. Never dispatch from a stale body alone.
2. Filter to open, unblocked, unclaimed implementation tickets carrying `ready-for-agent`. Exclude specs, maps, and HITL tickets.
3. Determine the code repository and branch base, then allocate exclusive machine-level state listed in `AGENTS.md` before parallel work starts.
4. Classify the ticket as easy or hard and state the reason in the handoff. Do not persist this as a label; reassess it whenever the issue or its blockers change.
5. Give the execution session one issue only. Require it to claim the issue before writing, keep scope to that issue and its explicit acceptance criteria, implement and verify end to end, open the code PR in the correct repository, and leave both PR and issue open for independent acceptance.

Every execution prompt must name the issue title and URL, autonomy class and rationale, source repository, required context documents, accepted scope and deferred scope, shared-state ownership, verification commands or evidence expected, and the exact handback artifacts. For an easy ticket, instruct the session to follow the specified path and stop for genuine ambiguity. For a hard ticket, authorize local engineering decisions within the acceptance boundary and require those decisions and tradeoffs in the handback.

### Acceptance workflow

The orchestration session performs acceptance from primary artifacts, not from the executor's completion summary:

1. Re-read the issue body, blockers, later clarifications, linked spec/ADR terms, and every commit in the PR.
2. Review the diff for behavioral correctness, scope expansion, privacy and failure semantics, concurrency or lifecycle risks, and missing tests. Check deferred work really belongs to another ticket.
3. Re-run the relevant deterministic checks when the machine state is available. Treat reported timing or live-input results as evidence to audit, not automatically reproducible facts; verify their fixtures and environment.
4. If acceptance fails, leave concrete findings with file or commit references and keep the issue and PR open for the same execution session to revise.
5. If acceptance passes, record the checklist and evidence on the issue and mark the PR ready for the user to squash-merge. Do not merge for the user. Close the implementation issue only after its code PR is verifiably in the correct default branch, or immediately for a non-code deliverable whose acceptance itself completes the ticket.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies** — the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only — the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.

  Not every unblocked child is a work item. A `spec` child holds the PRD the tickets implement and is never itself implemented; a `wayfinder:map` child is a nested map. Both are open, unassigned and unblocked forever, so they win the raw frontier — **filter them out**.

- **AFK dispatch frontier**: the frontier above **plus `--label ready-for-agent`**. That label is the single gate for handing a ticket to an unattended session; it is what separates a fully-specified ticket from one that still needs the owner. `wayfinder:grilling` and `wayfinder:prototype` are HITL by definition and must not carry it — they stay claimable by the owner through the plain frontier query, never by an AFK session.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
