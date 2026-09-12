# Personal experiment profile `personal-bge-experiment-v1`

Status: frozen engineering default for the personal path in
[ADR-0004](adr/0004-personal-experimental-first-use.md). Not enabled.
Not a production lock, not a +3pp Pass, and not a rewrite of
[#80](https://github.com/Habit130/squirrel/issues/80).

Parent spec: [#166](https://github.com/Habit130/squirrel/issues/166).
This document is the #167 profile. Later tickets
[#168](https://github.com/Habit130/squirrel/issues/168),
[#169](https://github.com/Habit130/squirrel/issues/169), and
[#170](https://github.com/Habit130/squirrel/issues/170) consume it after
their own frozen contracts. habit remains the sole activation authority.

Inspection base: plugin
[`Habit130/librime-llm-rerank@a7cef187d363976f77b46059000e9ce7539a80c5`](https://github.com/Habit130/librime-llm-rerank/tree/a7cef187d363976f77b46059000e9ce7539a80c5).
No model run, grid, private-fact read, snapshot, or live configuration
change was performed to choose these values.

## First-use goal

This is an explicit personal experiment with intended actual evidence
application after later activation. It does not claim improved accuracy,
coverage, or production certification. Unfamiliar choice problems keep the
existing baseline. Faults keep whole-window passthrough.

This delivery does not change product, runtime, or live configuration.
The released public example remains `evidence_enabled: false`
([docs/reranker-public-contract.md](reranker-public-contract.md)).

## Profile table

Exactly one value per parameter. Numeric fields are heuristic defaults:
unvalidated hypotheses, not calibrated winners. They are not fitted to the
historical 13-event suffix, a 5000 census, or any other private sample.

| Field | Value |
| --- | --- |
| Profile id | `personal-bge-experiment-v1` |
| Ranking coefficient `alpha` | `0` |
| Baseline weight policy | `baseline_policy_id=mean-token-lm-v1`; `sys_coeff=1.0`; `usr_coeff=1.0`; no Qwen LM term; no bigram evidence mixed with semantic evidence |
| Shadow comparator | existing frozen baseline; this profile does not rewrite [docs/freeze/shadow-baseline-freeze-2026-08-15.md](freeze/shadow-baseline-freeze-2026-08-15.md) |
| Embedding route | `bge-m3-dense-1024` |
| Adapter | `bge-m3` |
| Instruction | `none` (no BGE or FlagEmbedding query prefix) |
| Pooling | `dense-mean` of `last_hidden_state` over attention-masked tokens |
| Tokenizer special tokens | `add_special_tokens=False` |
| Payload schema | `candidate-conditioned-concat-v1` |
| Serialization | `last64-preceding-plus-candidate:no-separator:no-special` |
| Window | last at most 64 Unicode characters of session-committed preceding text, then the candidate; no host-document scraping |
| Dimensions | `1024` |
| Vector format | `fp32-l2` |
| Metric | cosine |
| Architecture requirement | HuggingFace `model_type=xlm-roberta`, `hidden_size=1024` |
| Upstream model identity | [`BAAI/bge-m3`](https://huggingface.co/BAAI/bge-m3) revision `5617a9f61b028005a4858fdac845db406aefb181` |
| Isolated embedding dependencies | `torch==2.7.1`, `transformers==4.52.4`, `tokenizers==0.21.1`, `safetensors==0.5.3` |
| Installed-file digests and local model path | deferred to activation ([#170](https://github.com/Habit130/squirrel/issues/170)) |
| Representation id version | `dedicated-embedding-repr-v1` |
| `tau` | `0.5` |
| Usage-age half-life `H` | `128` (finite; same-key later-event count, not calendar time) |
| `K_evidence` | `8` |
| `gamma` | `1.0` |
| Saturation `k` | `3.0` |
| One-event increment | `gamma / (1 + k) = 0.25` when one kept event has `a_i = 1` and is the only mass |
| Retrieval backend | `exact` |
| Candidate window | `32` |
| Deadline | `200` ms |
| Recording (intended at activation) | enabled |
| Evidence application (this delivery) | not enabled |
| Heavyweight models | one: this BGE adapter. No resident Qwen LM. No second embedding model. |

Sparse, ColBERT, hybrid, and sentence-transformers pooling outputs are not
part of this identity. The route name `BGE-M3` alone is not sufficient.

`representation_id` at runtime is:

```text
dedicated-embedding-repr-v1:route=bge-m3-dense-1024:payload=candidate-conditioned-concat-v1:serialization=last64-preceding-plus-candidate:no-separator:no-special:model=<installed-model-digest>:tokenizer=<installed-tokenizer-digest>:adapter=bge-m3:instruction=none:pool=dense-mean:dim=1024:format=fp32-l2:metric=cosine:deps=torch@2.7.1,transformers@4.52.4,tokenizers@0.21.1,safetensors@0.5.3
```

`config_identity` at runtime is:

```text
evidence-v1:repr=<representation_id>:tau=0.5:kev=8:H=128:sat=3:gamma=1
```

Doubles use the existing six-significant-digit identity domain. Local path
and installed-file verification remain activation work.

## Formula (unchanged)

Existing positive-only bounded evidence, not a new scoring rule:

```text
r_i = clamp((cos_i - tau) / (1 - tau), 0, 1)
u_i = count of later same-key active events
d_i = 2 ** (-u_i / H)
a_i = r_i * d_i
kept = at most K_evidence events with a_i > 0, largest a_i first
s_c = (m_c / M) * m_c / (m_c + k)  if M > 0 else 0
score(c) = base_score(c) + gamma * s_c
```

Evidence uses strict `cosine > tau` (`r_i > 0`). Cosine top-K before aging
is not the oracle. An event supports only its selected candidate after the
choice-problem hard partition.

## Numeric rationales

All numeric defaults below are unvalidated. They are not grid-search
winners, not promised accuracy or coverage, and not dependent on the
historical 13-event suffix or a 5000 census.

### `alpha = 0`

[#106](https://github.com/Habit130/squirrel/issues/106) kept the language-model
coefficient at zero. The personal experiment reuses personal evidence, not
the causal LM term. Re-enabling Qwen scoring would add a second heavyweight
model and contradict ADR-0003 / ADR-0004.

### Baseline weights `sys_coeff = 1.0`, `usr_coeff = 1.0`

Keep the existing dictionary-weight policy and the frozen shadow comparator.
The experiment adds `gamma * s_c` only. It does not retune dictionary
coefficients.

### `tau = 0.5`

`r_i` scales cosine above `tau` into `[0, 1]`. The value must be in
`[0, 1)` and is model-specific: it is a threshold on this adapter's
L2-normalized 1024-d cosine, not a portable similarity percent.

This default is an experimental hypothesis, not an imported Qwen threshold
and not a Q95 hard-negative calibration. Public diagnosis of the earlier
candidate-conditioned benchmark showed that BGE Q95 `tau ≈ 0.96` put every
positive example below threshold. That result forbids copying a Q95
production-gate threshold into this experiment; it does not calibrate a
replacement. `0.5` is a round midpoint of the legal range that still
requires clearly positive same-candidate cosine before evidence can form.

Whether non-identical preceding text actually clears `0.5` on this adapter
is unknown. If later real-model use shows the default is unhelpful, that is
a named-version revision, not silent tuning.

### `H = 128`

`H` is a finite usage-age half-life in later **same-key** active events,
not calendar time. `d_i = 2^(-u_i / 128)`: one later event barely decays a
prior event (`2^(-1/128) ≈ 0.995`); 128 later same-key events halve it.
Infinity is rejected because the owner required bounded recency. Very small
`H` would erase common syllables almost immediately. `128` is a finite
engineering scale for that tradeoff, unvalidated.

### `K_evidence = 8`

The oracle evaluates every same-key active event, then keeps at most eight
by final weight `a_i`. The bound exists so evidence mass cannot grow with
the entire same-key history. Eight is also the daemon's documented
non-winner default; it is reused here as a small finite cap, not as a
measured optimum.

### `gamma = 1.0`, `k = 3.0`

One perfect kept event that is the only mass yields

```text
s_c = 1 / (1 + 3) = 0.25
gamma * s_c = 0.25
```

That is the intended weak one-event influence. Repeated same-candidate mass
saturates toward `gamma` (`s_c → 1` as `m_c >> k` with share 1), so the
maximum evidence term is `1.0` in the same units as `base_score`. Schema
default `gamma=2.0` is an unselected prototype coefficient, not imported as
a winner. These values are unvalidated; they are not a claim that 0.25 will
flip any particular homophone pair.

### Backend `exact`, window `32`, deadline `200` ms

Exact same-key retrieval is the preferred backend. Disqualified ANN
backends are not revived to start the trial. The candidate window and
synchronous deadline stay at the existing public-contract defaults. This
profile does not relax latency, memory, disk, or fallback budgets.

## Behavior

Examples are **illustrative**. They are not private history, not an
accuracy gate, and not a reason to retune the profile to one sentence.

### Non-identical preceding-text reuse

Choice-problem key remains exact:
`schema_id + category + canonical_segment_input`. Preceding text is compared
only semantically, and only after that hard partition, by cosine of
candidate-conditioned vectors for the **same** selected/current candidate.

Illustrative same-key pair (not real user text):

- Historical committed choice: preceding `周末想去那座`, selected `城市`
- Current group: preceding `计划搬去那座`, candidates include `城市` and at
  least one same-span, same-category competitor

If the real BGE cosine for (`周末想去那座`+`城市`) vs (`计划搬去那座`+`城市`)
is `> 0.5` and the event is kept, `城市` may receive positive `s_c`. If the
cosine is not above `tau`, the result is successful zero evidence for that
history, not a fault.

Exact 64-character equality is not required and must not be used as a
retrieval predicate.

### No-history behavior

Empty store, no same-key active events, nothing above `tau`, or no kept
event matching a current candidate is successful zero evidence: `s_c = 0`
for every candidate, baseline order, `status: ok`. That is distinct from a
fault.

### Fault passthrough

Identity mismatch, missing or incompatible generation, unavailable model,
timeout, non-finite scores, later-group failure, or other true faults emit
the **entire original window** in arrival order. No partial application.
Committed text is not lost, duplicated, or blocked by scoring failure.

### Committed-choice memory

A committed explicit choice in a competitive `word` group becomes a
canonical selection event. Later requests may use it as evidence under this
same frozen profile. The model and numeric parameters do not update. Derived
vectors may be rebuilt for the same identity; facts are not relabeled.

### Fixed-within-version parameters

Poor coverage or a bad promotion may motivate `personal-bge-experiment-v2`.
It is not permission to change `tau`, `H`, `K_evidence`, `gamma`, or `k`
at runtime.

### Local feedback

Owner complaints should bind to the actually applied profile/version and
the client apply-or-fallback outcome, not merely a server-computed order.
Missing acknowledgment is unknown, not success. Traces must not duplicate
raw preceding text, candidate text, or vectors. Absence of a complaint is
not a correct-label oracle. Correlation work belongs to
[#169](https://github.com/Habit130/squirrel/issues/169).

### Stop evidence without deleting facts

Set evidence application off. Selection-event recording and canonical facts
continue. Derived state is not required to be wiped. Recording stop,
evidence stop, fact clear, and generation rebuild remain distinct
operations.

## Downstream real-model demonstration

For [#168](https://github.com/Habit130/squirrel/issues/168) only: implement
the illustrative non-identical pair above (or an equivalent invented pair
with the same structure) through the real pinned BGE adapter and this
profile.

It is a behavior demonstration that semantic reuse is possible without
exact preceding-text equality. It is **not** an efficacy gate for this
documentation delivery, not a universal embedding accuracy test, and not
permission to retune until that one pair promotes.

#168 must still separately verify: normal zero evidence; identity mismatch;
unavailable runtime; timeout; later-group failure; a new committed choice
becoming later evidence; no partial application; no loss or duplication of
committed text.

## Deployment prerequisites (not claimed met)

Preserve existing numerical budgets. Any requested relaxation is out of
scope.

| Prerequisite | Later ticket | Current status |
| --- | --- | --- |
| Builder, delta, and desired-provider identity agree on this representation/profile; incompatible state fails closed | [#168](https://github.com/Habit130/squirrel/issues/168) | Not met. Plugin `a7cef18` wires `provider_kind=bge_m3` in evidence/delta construction, but staging `_build_desired_provider` still accepts only `fixture`, `candidate_fixture`, and `seed_vectors`. |
| Actual client emission, not server-predicted order, is the success signal | [#169](https://github.com/Habit130/squirrel/issues/169) | Not met. |
| Single heavyweight BGE runtime; no extra resident Qwen LM | [#168](https://github.com/Habit130/squirrel/issues/168), [#170](https://github.com/Habit130/squirrel/issues/170) | Not verified on an allocated machine. |
| Bounded hot-path work and storage; do not re-encode the full history on every input request | [#168](https://github.com/Habit130/squirrel/issues/168) | Not verified. Query caching and fingerprint work remain planning leads. |
| Existing latency / resource / fallback checks: synchronous deadline **200 ms**, whole-window passthrough, designed ~2 GB operating point as a soft reference not a new cap | [#170](https://github.com/Habit130/squirrel/issues/170) | Not run. Offline throughput or fixture-only passes do not substitute. |
| Installed model/tokenizer file digests match the frozen identity; local paths authorized | [#170](https://github.com/Habit130/squirrel/issues/170) | Deferred. |
| habit explicit activation after technical acceptance | [#170](https://github.com/Habit130/squirrel/issues/170) | Not authorized by this document. |

## Source references

Read-only plugin inspection at `a7cef187d363976f77b46059000e9ce7539a80c5`:

- [`daemon/embeddings.py`](https://github.com/Habit130/librime-llm-rerank/blob/a7cef187d363976f77b46059000e9ce7539a80c5/daemon/embeddings.py) — `bge-m3-dense-1024`, `adapter=bge-m3`, `instruction=none`, `pooling=dense-mean`, 1024-d fp32 L2 cosine, `xlm-roberta` check, `local_files_only=True`
- [`docs/dedicated-embedding-adapters.md`](https://github.com/Habit130/librime-llm-rerank/blob/a7cef187d363976f77b46059000e9ce7539a80c5/docs/dedicated-embedding-adapters.md) — payload is last 64 characters plus candidate, no separator, no special tokens; sparse/ColBERT/hybrid not loaded
- [`daemon/representations.py`](https://github.com/Habit130/librime-llm-rerank/blob/a7cef187d363976f77b46059000e9ce7539a80c5/daemon/representations.py) — `CANDIDATE_PAYLOAD_SCHEMA`, `CANDIDATE_SERIALIZATION`, `WINDOW_CHARS=64`
- [`daemon/oracle.py`](https://github.com/Habit130/librime-llm-rerank/blob/a7cef187d363976f77b46059000e9ce7539a80c5/daemon/oracle.py) — `r_i`, `d_i`, `a_i`, `K_evidence`, `s_c`
- [`daemon/evidence.py`](https://github.com/Habit130/librime-llm-rerank/blob/a7cef187d363976f77b46059000e9ce7539a80c5/daemon/evidence.py) — `BACKEND_ORACLE="exact"`, config identity, `bge_m3` provider kind
- [`daemon/delta.py`](https://github.com/Habit130/librime-llm-rerank/blob/a7cef187d363976f77b46059000e9ce7539a80c5/daemon/delta.py) — `bge_m3` construction
- [`daemon/staging.py`](https://github.com/Habit130/librime-llm-rerank/blob/a7cef187d363976f77b46059000e9ce7539a80c5/daemon/staging.py) — desired-provider factory without `bge_m3`
- [`daemon/requirements-embeddings.txt`](https://github.com/Habit130/librime-llm-rerank/blob/a7cef187d363976f77b46059000e9ce7539a80c5/daemon/requirements-embeddings.txt) — isolated dependency pins
- [`src/llm_rerank_filter.h`](https://github.com/Habit130/librime-llm-rerank/blob/a7cef187d363976f77b46059000e9ce7539a80c5/src/llm_rerank_filter.h) — `window=32`, `deadline_ms=200`, `alpha=0.0`

Squirrel documents used as constraints, not as live enablement:

- [ADR-0001](adr/0001-inference-process-boundary.md), [ADR-0002](adr/0002-windowed-stateless-scoring.md), [ADR-0003](adr/0003-candidate-conditioned-semantic-representation.md), [ADR-0004](adr/0004-personal-experimental-first-use.md)
- [CONTEXT.md](../CONTEXT.md)
- [docs/reranker-public-contract.md](reranker-public-contract.md)

Desensitized in-repo diagnosis informed only the negative constraint “do not
import Q95 `tau`”:
[docs/orchestration/ac112-all-fail-diagnosis.md](orchestration/ac112-all-fail-diagnosis.md).
No raw input, vector, or private path from that work was reused.

## Inspection record

| Action | Result |
| --- | --- |
| Model download, grid, or forward pass | Not run |
| Private facts / live Rime / extra worktree | Not read |
| 13-event or 5000-event fitting | Not used as a selection gate |
| Product YAML / `sources/` / freeze records | Unchanged |
