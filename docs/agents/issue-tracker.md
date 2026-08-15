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
"Repository boundary" in `AGENTS.md`. The split is:

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

An orchestration session coordinates issue delivery rather than implementing the tickets it dispatches. Its scope is to inspect the live frontier, prepare prompts for execution sessions, prevent shared-state collisions, and independently accept or reject returned work. Keep product implementation and orchestration in separate sessions so acceptance does not inherit the executor's assumptions.

### Roles, scope, and delivery states

The **orchestration scope** is the set of issues the session currently coordinates. It is task-dependent rather than fixed to one issue, one map, or the whole project. The orchestration session proposes the included issues and explicit exclusions; the owner confirms the scope and any later expansion. An issue cannot belong to two active orchestration scopes. Replacing the orchestration session requires an explicit handoff of the scope, live frontier, active execution sessions, branches and PRs, consumed attempts, outstanding findings, and shared-state allocations; the replacement must still refresh the live state before acting.

The **orchestration session** must be capable of independently understanding and accepting the highest-judgment work in its scope. It shapes work for cost-effective execution, writes self-contained execution prompts, diagnoses failed acceptance, and recommends the required executor capability. It may write only orchestration artifacts listed in `AGENTS.md`; it never implements or repairs a dispatched product-code issue, either directly or through a subagent. The owner starts every execution session by transferring the frozen prompt to a separately chosen agent.

An **execution chain** contains the attempts to deliver one issue. For a code delivery, every attempt continues on the same feature branch and PR. Only one execution session may write to a delivery at a time. The previous writer must hand back and release it, or the owner must explicitly terminate that session, before another executor takes over. Different issues may proceed concurrently only after their worktrees and machine-level shared state have been separated.

An **acceptance subagent** is an optional read-only helper, not an executor and not a third delivery role. Before dispatch, the orchestration session decides whether independent review is required and records its reason in the acceptance contract. The subagent may inspect more deeply or rerun checks, but it uses the exact frozen contract and cannot add criteria. The orchestration session remains responsible for the final decision.

The chain can use three executor attempt tiers:

- The **initial executor** gets the lowest-cost capability that is sufficient for the shaped ticket, with a bias toward the less capable agent when multiple levels are sufficient.
- The **escalated repairer** is a fresh session at a genuinely higher available capability level. It takes over after acceptance exposes a capability mismatch.
- The **recovery executor** is a fresh session at least as capable as the orchestration tier. It is the final planned repair level.

These are attempt tiers, not top-level session roles or model names. Every one still runs as an **Execution session**. The prompt states the tier, capability requirement, and rationale; the owner binds a currently available model when starting the session. Skip any level below the ticket's known minimum requirement, and never describe a same-level retry as a capability upgrade. If no higher sufficient level is available, the issue requires an owner decision.

Use these delivery states precisely:

- **Handback**: an executor returns the requested artifacts for review. This is not proof of correctness.
- **Accepted**: the orchestration session independently verifies the delivery and marks the PR ready for the owner to squash-merge.
- **Completed**: the code PR is verifiably in the correct default branch. For a non-code deliverable, acceptance itself may complete the issue.

### Allocate shared state before parallel work

Every concurrent issue gets a separate git worktree and exclusive ownership of each applicable machine-level resource:

- **The librime build tree** (`librime/build/`, `librime/plugins/`, `lib/`, `bin/`): one owner for any work that runs `install-plugins.sh` or `make librime`. A consumer that only needs a built binary copies it outside the shared tree first.
- **The live Rime deployment** (`~/Library/Rime`): one owner for deployment or live-input verification. Eval and baseline work uses a throwaway `rime_dir`; no session redeploys while another is testing the live data.
- **A quiet machine**: one owner when a ticket's deliverable includes latency or other timing measurements. Builds and unrelated load invalidate that evidence.

Record the allocations in every affected execution prompt. Do not start concurrent work while an ownership edge is unresolved.

### Classify execution autonomy

Classify every ticket at dispatch time by how much implementation judgment remains:

- **Easy**: the issue, spec, ADRs, and code precedents already fix the implementation seam, required behavior, important edge cases, and verification path. The execution session mainly follows established decisions.
- **Hard**: the issue is ready to build, but the execution session must still explore the codebase, choose among valid implementation seams, reconcile competing constraints, or design non-obvious tests. Give it broad end-to-end ownership within the issue boundary.

Difficulty does not measure code volume, duration, or technical prestige. A large mechanical migration can be easy; a small change with an ambiguous lifecycle seam can be hard. Before classifying it, the orchestration session should make the prompt cheaper to execute by gathering known facts, narrowing or splitting scope, and identifying already-decided seams and verification paths. It must not silently make an unresolved product decision or pretend that genuine implementation judgment is mechanical.

Difficulty is separate from triage readiness: `ready-for-agent` permits unattended work, while easy/hard determines the executor autonomy and minimum capability the prompt should request. A ticket with an unresolved product or specification decision is not hard-AFK; remove it from the AFK frontier, apply `ready-for-human`, and resolve that decision with the owner first.

### Dispatch workflow

1. Refresh `origin`, the parent issue's sub-issues, native dependency counts, assignees, open PRs, and recent issue comments. Never dispatch from a stale body alone.
2. Filter to open, unblocked, unclaimed implementation tickets carrying `ready-for-agent`. Exclude specs, maps, and HITL tickets.
3. Determine the code repository and branch base, then allocate the worktree and exclusive machine-level state above before parallel work starts.
4. Shape the execution prompt, classify the resulting ticket as easy or hard, and state the reason. Do not persist difficulty as a label; reassess it whenever the issue, prompt, or blockers change.
5. Select the lowest sufficient capability requirement. Lower cost wins only among levels that can exercise the remaining judgment; a known-hard ticket does not take a deliberately insufficient attempt merely to start cheaply.
6. Decide whether the delivery needs an independent acceptance subagent. Record `required` or `not required` and the orchestration session's rationale; there are no automatic risk categories.
7. Freeze the acceptance contract and execution prompt. Give the execution session one issue only; require it to claim the issue before writing, implement and verify end to end, open the code PR in the correct repository, and leave both PR and issue open for acceptance.
8. Return the prompt to the owner to start the execution session. The orchestration session does not start an implementation subagent itself.

Every execution prompt must be self-contained. It must designate `Session role: Execution`, name the executor attempt tier, issue title and URL, autonomy class and rationale, source repository and branch base, required context documents, accepted and deferred scope, established seams and remaining executor decisions, shared-state ownership, branch and PR rules, acceptance-contract ID and version, criteria and expected evidence, independent-review decision and rationale, and the exact handback artifacts. For an easy ticket, instruct the session to follow the specified path and stop for genuine ambiguity. For a hard ticket, authorize local engineering decisions within the acceptance boundary and require those decisions and tradeoffs in the handback.

A repair prompt must additionally name the current branch and PR, quote the failed contract criterion IDs with primary-artifact references, state the failure classification and remaining attempt, and require the new executor to verify the issue and current artifacts independently. Give an escalated or recovery executor the original contract and current artifacts, not the previous executor's reasoning as assumed fact. A completion summary is only a lead to inspect.

### Freeze one acceptance contract

The **acceptance contract** is the single standard used by the executor's self-check, the orchestration session's acceptance, and any acceptance subagent. Freeze it before the execution session starts. Give it an issue-scoped version such as `AC-101-v1` and express ticket-specific requirements as stable criterion IDs:

```text
Criterion ID -> requirement -> expected evidence
```

The contract incorporates the repo-wide baseline and hard constraints as they exist at dispatch, then adds the issue-specific criteria and prompt contract. It uses the stable baseline IDs below and gives a local ID to each applicable hard constraint. Any linked specification, ADR, or issue text that affects acceptance must be quoted into the prompt or pinned to a repository revision and section. No acceptance participant may add or strengthen criteria after seeing the delivery.

If a clarification genuinely changes scope, a criterion, or required evidence after dispatch, pause execution. The owner must approve a new contract version, the issue and prompt must record it, and the executor must acknowledge it before work resumes. Acceptance uses that one acknowledged version; a later version is never applied retroactively.

The executor's handback names the acknowledged contract ID and version, then mirrors the contract:

```text
Criterion ID -> primary evidence -> executor Pass/Fail
```

It also names the exact branch, PR, commit, verification output, deferred work, and any decisions the prompt left to the executor.

### Repo-wide acceptance baseline

Green light means every criterion in the frozen acceptance contract passes. A passing delivery is accepted rather than re-litigated against a preferred implementation. The repo-wide baseline applies to every ticket and is incorporated into every contract:

- **`BASE-EVIDENCE`**: The handback maps every contract criterion to primary evidence and an executor Pass/Fail result.
- **`BASE-BUILD`**: Every build path applicable to the delivery succeeds (`docs/agents/build.md`): fast path for frontend-only work, from-source path for anything under `librime/` or a source plugin.
- **`BASE-LINT`**: `swiftlint` and `periphery scan` are clean for any change under `sources/`.
- **`BASE-SAFETY`**: The delivery introduces no demonstrable correctness, privacy, security, concurrency, or lifecycle defect; required checks do not fail; no secret or credential is exposed.
- **`BASE-DOCS`**: Behavior or constraint changes are synced into the docs that carry them (`AGENTS.md`, `docs/agents/*.md`, `SKILL.md`, `CONTEXT.md`, an ADR, or the constrained file's own comments) in the same delivery.
- **`BASE-SCOPE`**: Everything outside the contract is either untouched or explicitly recorded as deferred.
- **`BASE-PR`**: A PR-backed delivery's description carries motivation, change summary, and verification evidence.

Ticket-specific criteria come from the issue and the execution prompt: required behavior, established seams, verification commands, evidence, and handback artifacts. The frozen prompt is the self-contained snapshot; later issue edits do not silently alter it.

### Acceptance workflow

The orchestration session performs acceptance from primary artifacts, not from the executor's completion summary:

1. Re-read the acknowledged acceptance-contract version, its quoted or revision-pinned spec/ADR terms, blockers, branch, PR, and every commit in the PR.
2. Review the diff for behavioral correctness, scope expansion, privacy and failure semantics, concurrency or lifecycle risks, and missing tests. These are investigation dimensions, not new standards; every blocking result must still map to a frozen criterion.
3. Re-run the relevant deterministic checks when the machine state is available. Treat reported timing or live-input results as evidence to audit, not automatically reproducible facts; verify their fixtures and environment.
4. If independent review is required, start a read-only acceptance subagent after handback. Give it the exact contract version and primary-artifact locations, not the executor's conclusions as facts. Require `Criterion ID -> evidence -> Pass/Fail`; deeper inspection is allowed, stricter criteria are not.
5. Produce the same evidence matrix in the orchestration session. A blocking finding must map to a frozen criterion ID. Findings with no mapping are non-blocking for this delivery, however useful; style preferences, optional refactors, and correctly deferred scope also cannot consume an escalation attempt.
6. Reconcile any disagreement by checking the criterion and primary evidence, not by voting. The orchestration session makes and records the final decision.
7. If every criterion passes, record the contract ID and version, matrix, and evidence on the issue and mark the PR ready for the owner to squash-merge. Do not merge for the owner. Close the implementation issue only after its code PR is verifiably in the correct default branch, or immediately for a non-code deliverable whose acceptance itself completes the ticket.

Classify failed acceptance before choosing the next route, and cite the evidence for the classification:

- **Local defect**: the seam and approach remain valid, and the finite corrections require no new design judgment. After the initial handback, return a focused repair prompt for at most one same-level revision. If the initial session is unavailable, a new session at the same sufficient capability may consume that same revision slot. A defect found after a later takeover does not create another revision slot.
- **Capability mismatch**: the work shows insufficient exploration, judgment, integration of constraints, or autonomous diagnosis. Skip to the next genuinely higher sufficient capability.
- **Specification blocker**: the next step needs a product, scope, or acceptance decision. Remove `ready-for-agent`, apply `ready-for-human`, record the open decision, and stop the execution chain.
- **Execution-environment blocker**: tooling, platform, credentials, or allocated shared state prevents a fair attempt. Pause and resolve the blocker without consuming a repair attempt.

The bounded escalation sequence is: one initial attempt; at most one same-level revision for a local defect; one takeover by an escalated repairer; and one takeover by a recovery executor. Any stage that passes acceptance ends the chain. An escalated or recovery executor gets one complete takeover, not an unbounded review loop. If the recovery attempt fails, or the chain already uses the highest available sufficient capability, remove `ready-for-agent`, apply `ready-for-human`, and report the failed attempts, unresolved findings, and recommended owner decision.

Persist handback conclusions, blocking findings, failure classifications, routing decisions, and final acceptance evidence on the issue or PR. Keep concrete model identities, prices, and full prompt text in the session handoff rather than the long-lived project rules.

### Feed surprise findings back into the criteria

If acceptance surfaces a finding that the frozen contract did not cover, record it as non-blocking for the current delivery and codify it before dispatching further tickets of the same kind. The orchestration session may update its allowed orchestration artifacts (`AGENTS.md`, `docs/agents/*.md`, `SKILL.md`, `CONTEXT.md`, or an ADR) through the normal branch-and-PR flow. If the durable constraint belongs in product source, build files, runtime configuration, or their local comments, create and dispatch an execution issue instead. A surprise happens once; the next applicable contract includes it. Record the codification PR or issue on the original delivery.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

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
