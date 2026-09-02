# Delivery Protocol

This document defines how issue-scoped work moves from a frozen contract to verified
completion. The issue is the only acceptance-contract body.

Tracker operations, the `Habit130/squirrel` vs `rime/squirrel` split, plugin-ticket routing,
and wayfinder queries live in `docs/agents/issue-tracker.md`.

## Roles

### Orchestration

An Orchestration session owns an explicit set of included and excluded issues. One issue
cannot belong to two active orchestration scopes.

Orchestration may write governance artifacts: issues and tracker state, specifications,
ADRs, roadmaps, AGENTS and `docs/agents/`, frozen handoffs, and acceptance records. It
does not implement or repair product code.

Before dispatch, Orchestration:

1. refreshes issues, dependencies, assignees, branches, PRs, comments, and shared state;
2. freezes the complete issue contract;
3. decides `Independent acceptance: required|not required` and records the rationale;
4. allocates one branch/worktree and every machine-level shared resource;
5. writes an immutable Execution handoff and records its path and SHA-256 on the issue.

Replacing Orchestration requires an `ORCH-<scope>-<timestamp>.md` handoff containing the
live frontier, issues, PRs, attempts, findings, and resource allocations. The replacement
refreshes live state before acting.

### Execution

Execution owns one issue, one branch/worktree, one PR, and one active writer. Before
editing it assigns the issue to itself and comments with the acknowledged contract ID,
branch, worktree, and attempt.

For plugin implementation tickets, the issue and contract stay in `Habit130/squirrel`; the
code PR is opened in `Habit130/librime-llm-rerank` against that repository's default branch.

Execution may choose implementation seams, code structure, and test design inside the
frozen contract. A product decision, scope expansion, or acceptance change stops work for
a new contract version. Read-only helpers are allowed; writing helpers do not share the
delivery.

Classify remaining judgment in the handoff, not as a tracker label:

- **Easy**: the issue, spec, ADRs, and code precedents already fix the seam, behavior,
  important edges, and verification path.
- **Hard**: the session must still explore, choose among valid seams, or design
  non-obvious tests. Authorize local engineering decisions inside the acceptance boundary.

Execution hands back:

- acknowledged contract ID and exact branch, PR, and head;
- `Criterion ID -> primary evidence -> Pass/Fail` for every BASE and ticket criterion;
- commands run and material output;
- deferred work and out-of-contract findings;
- decisions the contract intentionally left to implementation.

Execution leaves the issue and PR open and releases write ownership.

### Acceptance

Acceptance is a fresh session started by habit. It may run checks and write issue/PR
acceptance records. It does not modify the delivery branch, product code, or governance
files.

Acceptance reads the frozen issue contract, every PR commit, diff, directly affected
interaction edges, Execution's evidence matrix, verification output, and Codex review.
Execution reasoning and conclusions are leads, not facts.

Acceptance produces its own complete criterion/evidence Pass/Fail matrix and dispositions
for every Codex or newly observed finding. A Pass is the technical gate for habit; it does
not authorize the Acceptance session to merge.

## Issue contract

Every post-bootstrap PR links one executable issue. The issue contains:

- Goal;
- included and excluded Scope;
- Dependencies;
- Independent acceptance decision and rationale;
- all six expanded BASE criteria;
- ticket criteria with stable IDs and expected evidence.

Starting Execution from a frozen handoff confirms that contract version. A material
clarification creates a new version in the issue and a new immutable handoff. Acceptance
uses only the version acknowledged by the active Execution.

## Repository baseline

Every executable issue expands these definitions in full:

- **BASE-EVIDENCE**: Execution maps every criterion to primary evidence and Pass/Fail.
  Independent Acceptance, when triggered, provides its own complete mapping.
- **BASE-VERIFY**: Every build, lint, test, typecheck, packaging, or focused command named
  in the issue succeeds in the required order, with output identified as evidence.
- **BASE-SEVERITY**: The PR introduces no independently confirmed P0/P1. Codex findings
  are explicitly confirmed or rejected with evidence under the narrow taxonomy below.
- **BASE-SCOPE**: Work outside included scope is untouched or explicitly recorded as
  deferred; excluded scope is not implemented.
- **BASE-DOCS**: Behavior, interface, workflow, or constraint changes update the
  authoritative documentation in the same delivery.
- **BASE-PR**: The PR links the issue and states Motivation, Changes, and Verification.

Ticket-specific criteria add finite behavior and evidence. They do not use a broad
"no bugs" or "all edge cases" clause.

Write a BASE-VERIFY line to name ticket-specific commands or mark an item N/A. Use
`docs/agents/build.md` to choose the path:

| Change | Named VERIFY commands |
| --- | --- |
| Swift/AppKit frontend, checked-in data, packaging, or project configuration | fast path: `./action-install.sh` when staged libs are missing, then `make`, `swiftlint`, and `periphery scan --relative-results --skip-build --index-store-path build/Index.noindex/DataStore` |
| librime engine source or a locally checked-out librime plugin | from-source path in `docs/agents/build.md`, plus `make -C librime test` when the ticket requires it |
| Governance or docs-only | the structural commands named in the issue; `make`, `swiftlint`, and `periphery` are N/A when `sources/` is unchanged |

A separately delivered plugin also follows that repository's own tests.

## Severity taxonomy

- **P0**: a catastrophic defect introduced by the PR with system-wide or broadly
  irreversible impact, such as widespread unrecoverable data loss, a credential exposure
  that enables unauthorized access, or complete loss of the primary product for nearly
  all supported use. It has no reasonable containment before merge.
- **P1**: a concrete defect introduced by the PR on a supported path that breaks a core
  operation, corrupts canonical or persisted data, or violates an established security or
  privacy boundary, with substantial impact and no acceptable workaround for the affected
  path.
- **P2/P3**: all lower-severity defects, maintainability concerns, optional refactors,
  stronger test suggestions, and out-of-contract improvements. Record them as non-blocking
  follow-up work.

In this repository the following are P0/P1 when the delivery introduces them on a
supported path:

- supported input loses, corrupts, duplicates, or fails to commit user text, or the input
  method becomes unusable without the documented fallback;
- a supported fact operation reports success after corrupting canonical facts outside its
  declared outcome or exposing a partial old/new state;
- private user content or credentials cross an existing declared trust boundary;
- stale or incompatible versioned state is returned as a successful semantic result instead
  of the documented failure or fallback;
- `sources/` generates, scores, or reranks candidates.

A Codex P0/P1 blocks only after Acceptance independently confirms its trigger, impact,
primary evidence, and severity. An ordinary override comment cannot waive a confirmed
P0/P1. Changing the underlying product or security boundary requires a new issue/ADR and
a new contract.

Codex review on `Habit130/squirrel` is automatic via `chatgpt-codex-connector`. If the bot
does not review a PR, comment exactly `@codex review`. A trigger comment is not proof that
review completed.

## Conditional independent Acceptance

Orchestration decides before dispatch whether independent Acceptance is required. It uses
blast radius, reversibility, cross-boundary effects, implementation judgment, and the
strength of deterministic verification, then records the decision and reason in the issue.

Independent Acceptance is required when:

- Orchestration predeclares it;
- Codex reports a P0/P1;
- Codex review is unavailable or incomplete;
- the repository has no GitHub review path.

When Acceptance was `not required`, Execution's complete self-check plus a completed Codex
review with no P0/P1 is the technical merge recommendation.

Acceptance cannot fail a delivery against a newly preferred implementation, stronger test,
or unlisted scenario. A finding outside ticket criteria is non-blocking unless it is a
confirmed P0/P1 under BASE-SEVERITY.

## Review boundary

Acceptance reviews the contract, all PR commits, the diff, and direct interaction edges
changed by the diff. It does not audit unrelated unchanged code.

After repair, reopen:

- each failed criterion;
- each previously passed criterion whose implementation, evidence, or direct interaction
  edge changed in the repair diff.

Other passed criteria stay closed unless primary evidence proves regression.

## Failure routing and bounded repair

Classify every Fail:

- **Local defect**: the approach remains valid and a finite correction needs no new design
  judgment. Resume the original Execution for one focused revision when possible.
- **Capability mismatch**: the attempt lacked necessary exploration, integration, or
  judgment. Start a fresh, genuinely stronger Execution takeover.
- **Specification blocker**: progress needs a product, scope, or contract decision. Apply
  `ready-for-human` and stop for habit.
- **Execution-environment blocker**: tooling, credentials, platform, or allocated shared
  state prevents a fair attempt. Pause and resolve it without consuming an attempt.

The execution chain has at most three attempts: initial, one focused revision, and one
fresh escalated takeover. Failure after the last available attempt moves the issue to
`ready-for-human` with the evidence and recommended decision.

## Handoffs

Frozen handoffs live under `docs/orchestration/handoffs/` and are gitignored. The issue
records repository-relative path, contract version, attempt, role, and SHA-256.

Use:

```text
AC-<issue>-v<contract>-a<attempt>-execution.md
AC-<issue>-v<contract>-a<attempt>-acceptance.md
ORCH-<scope>-<timestamp>.md
```

Never overwrite a handoff after publishing its digest. Write Execution handoffs as the
short brief in `docs/orchestration/handoffs/README.md`.

## Completion

Acceptance Pass marks a PR ready for habit. habit squash-merges. The PR uses
`Closes #<issue>`, but Orchestration records Completed only after verifying the exact
delivery on the write remote default branch. It then cleans the local worktree and branch.
