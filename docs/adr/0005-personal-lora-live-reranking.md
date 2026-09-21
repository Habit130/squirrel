# ADR-0005: Personal LoRA Live Reranking

Status: accepted (2026-09-17, owner-confirmed;
issues [#180](https://github.com/Habit130/squirrel/issues/180),
[#181](https://github.com/Habit130/squirrel/issues/181))

Amends: [ADR-0004](0004-personal-experimental-first-use.md)'s personal BGE
and `alpha=0` path, for one named personal Qwen3-0.6B-Base + LoRA
live-reranking path only.

Does not supersede: [ADR-0001](0001-inference-process-boundary.md);
[ADR-0002](0002-windowed-stateless-scoring.md); ADR-0003's production
`alpha=0` / `gamma=0`, representation, privacy, or identity rules; the
accepted [#80](https://github.com/Habit130/squirrel/issues/80)
no-qualified-configuration outcome; the parked #81–#84 production
confirmation chain; or the released public `alpha: 0.0` integration
example.

This record is not deployed behavior. Merging it does not enable live
reranking.

## Context

ADR-0004 authorized a personal BGE experiment with the Qwen causal LM term
off (`alpha=0`). habit later confirmed, on 2026-09-17 in #180, a different
personal exception: local causal Qwen3-0.6B-Base plus one newly trained
personal LoRA may replace resident BGE on that path.

[#178](https://github.com/Habit130/squirrel/issues/178)'s historical
`no_benefit` versus Rime remains accepted history. It is not a gate against
this personal use. Improved training loss is not ranking benefit. First use
does not wait for top-1/MRR improvement, a +3pp proof, a new #176/#178
experiment, or a [#179](https://github.com/Habit130/squirrel/issues/179)
backend contest.

[#182](https://github.com/Habit130/squirrel/issues/182) must supply a new
accepted dataset identity. [#183](https://github.com/Habit130/squirrel/issues/183)
trains a new adapter with the frozen #177 hyperparameters. Deleted
historical #175/#177 files are not deployment artifacts; checksum
coincidence does not restore them. Later live activation belongs to
[#184](https://github.com/Habit130/squirrel/issues/184), which depends on
this ADR and on #183 Completed.

This ADR records that authorization and its constraints. It does not
change product code, data, schema, configuration, training, or live state.

## Decision

For this personal Qwen + LoRA live-reranking path only:

1. The path uses local causal Qwen3-0.6B-Base plus one newly trained,
   selected personal LoRA. That pair replaces resident BGE here. At most
   one heavyweight model is resident. Candidates and composition stay
   Rime-owned. Squirrel `sources/` only renders the already-ranked
   emission order.
2. Personal parameters are `reranking_enabled: true`, `alpha: 1.0`,
   `sys_coeff: 1.0`, `usr_coeff: 1.0`, `evidence_enabled: false`,
   candidate `window: 32`, `deadline_ms: 200`, and a preceding-text
   window of 64 Unicode characters. Do not conflate the candidate window
   with the preceding-text window. Recording stays enabled if it is
   already enabled. Stopping this path does not clear facts or turn
   recording off.
3. Daemon scoring stays `baseline_policy_id=mean-token-lm-v1` and the
   existing protocol, identity, and fallback contract from ADR-0001 and
   ADR-0002. Do not replace it with #178 policy S2 logsum. The two
   layers' policies are not declared equivalent.
4. `alpha=1.0` is an unvalidated personal experimental default, not a
   calibrated winner. Historical #178 `no_benefit` versus Rime remains
   accepted history and is not a first-use gate. Improved training loss
   is not ranking benefit. No top-1/MRR improvement, +3pp proof, new
   #176/#178 experiment, or #179 backend contest is required to begin.
5. #182 supplies a new accepted dataset identity. #183 trains a new
   adapter using the frozen #177 hyperparameters. Deleted historical
   #175/#177 files are not deployment artifacts; checksum coincidence
   does not restore them. #184 must pin dataset,
   base-model, tokenizer, adapter, and runtime identities.
   Stale or mismatched identity fails closed.
6. Technical acceptance for #184 requires: the selected adapter actually
   loaded; controlled same-span/same-category rerank-group emission order
   changed versus `alpha=0`; BGE unloaded; whole-window passthrough on
   timeout, model-unavailable, or identity fault; unblocked commit; and a
   verified stop path to dictionary-only `alpha=0` without fact deletion.
   Merging this ADR or later implementation does not enable live use.
   habit remains the sole explicit enable authority after technical
   acceptance.
7. This amends ADR-0004 only for the named path above. ADR-0003
   production `alpha=0` / `gamma=0`, its representation, privacy, and
   identity rules, accepted #80, and parked #81–#84 are not rewritten or
   completed. ADR-0001 process isolation and ADR-0002 stateless windowed
   scoring remain. No new candidate generation, async reorder, broader
   script support, or old bigram evidence is introduced.
8. Released [docs/reranker-public-contract.md](../reranker-public-contract.md),
   its JSON, and README schema examples remain the `alpha: 0.0`
   integration example. This exception is a separate future activation,
   not a replacement public default. Private snapshots and adapters stay
   local and ignored. Facts are not cleared or uploaded.
9. #184 depends on this ADR and on #183 Completed. [#172](https://github.com/Habit130/squirrel/issues/172)
   is paused during the later live-switch interval. #179 stays optional.
   Resource and activation changes belong to #184, not this
   document-only record.

## Considered Options

- Keep waiting for a quality Pass, +3pp proof, or a new #176/#178/#179
  contest before any personal causal-LM first use. Rejected by the owner
  for this personal path only. Historical `no_benefit` stays history, not
  a gate.
- Keep resident BGE while adding Qwen, or treat training-loss improvement
  as ranking benefit. Rejected: at most one heavyweight model is resident,
  and loss is not ranking benefit.
- Replace daemon scoring with #178 policy S2 logsum, restore deleted
  #175/#177 files by checksum coincidence, or treat this merge as live
  enablement or a new public default. Rejected.

## Consequences

- Authoritative personal-path rules now distinguish the BGE / `alpha=0`
  experiment (ADR-0004) from this later Qwen + LoRA exception (this ADR).
  Production confirmation remains ADR-0003, #80, and parked #81–#84.
- Downstream #184 consumes pinned identities from #182 and #183. It does
  not revive deleted historical artifacts or enable live use by merge.
- The public scoring example stays `alpha: 0.0`. Private adapters and
  snapshots remain local. Stopping the path returns to dictionary-only
  `alpha=0` without clearing facts or stopping recording.
- #172 pauses only during the later live-switch interval. #179 remains
  optional and is not a first-use requirement.
