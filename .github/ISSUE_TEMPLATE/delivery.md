---
name: Delivery contract
about: Freeze one issue-scoped delivery and its acceptance evidence
title: ""
labels: needs-triage
assignees: ""
---

Contract: `AC-<issue>-v1`

## Goal

<!-- State the observable outcome and motivation. -->

## Scope

### Included

- <!-- Finite included work. -->

### Excluded

- <!-- Explicit non-goals. -->

## Dependencies

- <!-- Blocking issues, decisions, repositories, or `None`. -->

## Independent Acceptance

- Decision: `required` | `not required`
- Rationale: <!-- Blast radius, reversibility, cross-boundary effects, implementation
  judgment, and deterministic verification strength. -->

## Repository Baseline

- [ ] **BASE-EVIDENCE**: Execution maps every criterion to primary evidence and Pass/Fail.
  Independent Acceptance, when triggered, provides its own complete mapping.
- [ ] **BASE-VERIFY**: Every build, lint, test, typecheck, packaging, or focused command
  named in this issue succeeds in the required order, with output identified as evidence.
- [ ] **BASE-SEVERITY**: The PR introduces no independently confirmed P0/P1. Codex findings
  are explicitly confirmed or rejected with primary evidence under this taxonomy:
  - **P0**: a catastrophic defect introduced by the PR with system-wide or broadly
    irreversible impact, such as widespread unrecoverable data loss, a credential exposure
    that enables unauthorized access, or complete loss of the primary product for nearly
    all supported use. It has no reasonable containment before merge.
  - **P1**: a concrete defect introduced by the PR on a supported path that breaks a core
    operation, corrupts canonical or persisted data, or violates an established security or
    privacy boundary, with substantial impact and no acceptable workaround for the affected
    path.
  - **P2/P3**: lower-severity defects, maintainability concerns, optional refactors,
    stronger test suggestions, and out-of-contract improvements. They are non-blocking
    follow-up work.
- [ ] **BASE-SCOPE**: Work outside Included scope is untouched or explicitly recorded as
  deferred; Excluded scope is not implemented.
- [ ] **BASE-DOCS**: Behavior, interface, workflow, or constraint changes update the
  authoritative documentation in the same delivery.
- [ ] **BASE-PR**: The PR links this issue and states Motivation, Changes, and Verification.

## Ticket Criteria

- [ ] **TICKET-1**: <!-- Requirement. -->
  - Expected evidence: <!-- Primary artifact, command, or observable result. -->

## Verification Commands

```text
<!-- Exact commands and required order, or `N/A` with reason. -->
```

## Contract Changes

<!-- Append version, habit decision, changed criteria, and Execution acknowledgement.
Do not rewrite the history of an acknowledged version. -->
