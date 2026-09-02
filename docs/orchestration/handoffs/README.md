# Orchestration Handoffs

This directory's README and naming contract are tracked. Frozen handoff bodies are local,
gitignored owner-machine artifacts.

Use:

```text
AC-<issue>-v<contract>-a<attempt>-execution.md
AC-<issue>-v<contract>-a<attempt>-acceptance.md
ORCH-<scope>-<timestamp>.md
```

After freezing a file, record its repository-relative path and SHA-256 on the issue. A
published digest makes that file immutable; create a new version or attempt instead of
overwriting it.

Protocol: [`docs/agents/delivery.md`](../../agents/delivery.md). Pin that file's SHA in
every Execution handoff.

## Execution brief

Write a short brief. Omit unused sections. Omission means empty, not an unbounded promise.
Copy ticket-specific contract text; pin claim, git, and BASE rules to the protocol SHA
instead of recopying them. Each ticket invariant has one home — do not restate it as scope,
scenario, and criterion.

Same contract version, local-defect repair: new file with a `## Repair` prefix; point at
the original prompt hash; do not rewrite Established or Criteria. A new contract version
(`AC-N-v2`) is a full new execution handoff.

Live issue text is not acceptance input. Pin `path@SHA` or a comment ID. If the issue body
constrains the ticket, quote it into Established at freeze.

```text
# AC-<issue>-v<n> Execution Prompt

Session role: Execution
Executor attempt tier: initial executor | same-level revision | escalated repairer | recovery
Issue: [#N title](url)
Contract: AC-N-vN
Protocol: docs/agents/delivery.md@<fullsha>
Autonomy: Easy | Hard — <one clause>
Independent review: required | not required — <one clause>

## Binding
- Code: <repo> `<branch>` from `<base-sha>`
- Worktree: <path>
- Claim #N and acknowledge AC-N-vN before writing.

## Established
<rules; the single home for ticket invariants>

## Scope
Accepted: ...
Deferred: ...

## Criteria
- `ACN-1` -> <requirement or Established pointer> -> <evidence>
- `BASE-VERIFY` -> <commands>
```

Write a BASE line only to name ticket-specific commands or mark an item N/A. Unmentioned
BASE items apply as defined at the protocol pin.

Optional, only when they add information:

```text
## Repair                 # failed IDs, classification, original path+SHA, branch/PR/head
## Context                # extra pinned path@SHA or comment IDs
## Executor decisions
## Shared state           # only a non-default allocation or prohibition
## Scenarios              # SCN-* fault combinations that Criteria do not already cover
## Risks                  # RISK-* accepted risks
## Verification           # commands not already named as evidence
## Handback               # extras beyond Criterion ID -> evidence -> Pass/Fail
```
