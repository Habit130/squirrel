# ADR-0004: Personal Experimental First-Use Exception

Status: accepted (2026-09-12, owner-confirmed orchestration discussion;
issues [#166](https://github.com/Habit130/squirrel/issues/166),
[#167](https://github.com/Habit130/squirrel/issues/167))

Amends: first-use efficacy and production-lock prerequisites in
[#43](https://github.com/Habit130/squirrel/issues/43) and
[ADR-0003](0003-candidate-conditioned-semantic-representation.md), for one
personal experimental path only.

Does not supersede: ADR-0003's representation, identity, privacy, or
fail-closed rules; [ADR-0001](0001-inference-process-boundary.md);
[ADR-0002](0002-windowed-stateless-scoring.md); the accepted #80
no-qualified-configuration outcome; or the parked #81–#84 production
confirmation chain.

Amended by: [ADR-0005](0005-personal-lora-live-reranking.md), only for the
later personal Qwen3-0.6B-Base + LoRA live-reranking path. The BGE and
`alpha=0` personal-experiment decision recorded here is unchanged.

## Context

ADR-0003 deferred live retrieval evidence until a candidate-conditioned
representation passed frozen quality, safety, and prospective gates. Issue
#80 then terminated the production-lock attempt with no qualified
configuration. The old next step was another census or the #81–#84 unique-lock
chain.

habit approved a separate personal experiment: use one fixed BGE
candidate-conditioned profile, keep recording, apply positive-gamma evidence
when qualifying personal history exists, and report problems during actual
use. That path must not wait for a +3pp proof, a 5000-event milestone, a
unique production lock, or a #81/#82 prospective segment. It also must not
treat the historical 13-event operating-cell suffix as a profile-selection
gate.

This ADR records that narrow authorization change. The versioned engineering
defaults live in
[docs/personal-experiment-profile.md](../personal-experiment-profile.md).
This decision does not enable evidence, change product configuration, or
activate the experiment.

## Decision

For this personal experimental path only:

1. First use does not require +3pp proof, a 5000-event census, a unique
   production lock, a #81/#82 prospective confirmation segment, or a
   14-day/300-event minimum merely to begin using or to give feedback.
2. The experiment uses exactly one named profile, `personal-bge-experiment-v1`.
   Model, adapter, and numeric parameters stay fixed inside that version.
   A later version needs a new named approval; silent runtime tuning is not
   authorized.
3. Actual evidence application starts only after later technical acceptance
   **and** habit's explicit activation. Creating or merging this ADR, #167,
   or #168–#170 does not enable live evidence.
4. habit may stop evidence application at any time. Stopping evidence keeps
   selection-event recording and canonical facts. It is not a fact clear,
   a recording stop, or a derived-state wipe.

Unchanged, including for the experiment:

- Candidate generation and composition stay in Rime. Squirrel `sources/`
  does not generate, score, or rerank candidates.
- Choice-problem keys remain exact hard partitions. Retrieval evidence
  remains positive-only, bounded, and candidate-specific. No qualifying
  history is successful zero evidence. Faults keep whole-window passthrough.
- `alpha=0`. The Qwen causal LM term stays off. Old bigram evidence is not
  combined with semantic evidence.
- At most one heavyweight model is resident. Derived state may be rebuilt
  for the frozen identity; canonical facts are not relabeled or cleared.
- Representation identity, privacy, fact integrity, exact-backend preference,
  and the existing latency, memory, disk, and fallback budgets remain in
  force. Relaxing them is a separate decision.
- #80's no-qualified-configuration result stands. #81–#84 stay parked and
  are not completed by this experiment. This is not a new `unique_lock`.

## Considered Options

- Keep waiting for another census or the #81–#84 chain before any visible
  evidence. Rejected by the owner for this personal path only.
- Fit `tau` / `H` / `K_evidence` / `gamma` / `k` to the historical 13-event
  suffix or a new private-data grid. Rejected: those values would pretend to
  be measured winners.
- Treat this experiment as production certification or as a waiver of
  identity, privacy, input-correctness, or resource budgets. Rejected.

## Consequences

- Authoritative first-use rules now distinguish production confirmation
  (ADR-0003, #80, #81–#84) from this personal experiment (this ADR plus
  `personal-bge-experiment-v1`).
- Downstream implementation consumes the frozen profile. It does not invent
  another numeric menu or revive a disqualified ANN backend merely to start
  the trial.
- Historical freeze documents, including
  [docs/freeze/shadow-baseline-freeze-2026-08-15.md](../freeze/shadow-baseline-freeze-2026-08-15.md),
  remain historical records and are not rewritten.
- The released schema example in
  [docs/reranker-public-contract.md](../reranker-public-contract.md) stays
  the public integration contract (`evidence_enabled: false`). This ADR is
  not a live configuration change.
