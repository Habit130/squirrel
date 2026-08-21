# ADR-0003: Candidate-Conditioned Semantic Representation

Status: accepted (2026-08-20, owner-confirmed orchestration discussion)

Semantic memory originally represented only the preceding text with hidden states from Qwen3-0.6B-Base. The fixed benchmark in issue #69 eliminated all four first-round representations, issue #77 produced no exact shortlist, and issue #106 kept the language-model coefficient at `alpha=0`. More recorded events can improve statistical power, but cannot repair that fixed representation-quality failure.

## Decision

Semantic memory will represent a **candidate condition**, not preceding text alone. Within one choice problem, each current candidate is represented together with the last 64 characters of preceding text and compared with historical selection events represented by their preceding text and selected candidate. Choice problems remain hard partitions: evidence never crosses between them.

Retrieval evidence remains positive-only, bounded, and candidate-specific. A historical selection event can support only the candidate selected by that event; it never directly subtracts from another candidate. When no qualifying history exists, retrieval evidence is zero. Live ranking remains at `alpha=0` and `gamma=0` until a candidate-conditioned representation passes the frozen quality, safety, and prospective gates.

The model is deliberately deferred to a bounded offline comparison rather than fixed by this ADR. Production may keep at most one heavyweight model: a dedicated embedding model replaces Qwen3-0.6B-Base, while a pooling or learned-projection winner retains it. A small learned projection does not count as a second heavyweight model.

ADR-0001's daemon process boundary and ADR-0002's fixed 64-character, stateless request window remain in force.

## Considered Options

- Continue collecting data and rerun the same context-only representations. Rejected because the fixed #69 failure is structural, not a sample-size result.
- Keep context-only representations but change pooling. Retained only as an offline control; it is not the target representation contract.
- Introduce signed negative evidence from events that selected another candidate. Rejected to preserve the existing positive-only evidence and fail-safe zero semantics.
- Keep both a causal language model and a dedicated embedding model resident. Rejected because the causal LM has no accepted ranking contribution at `alpha=0`.

## Consequences

- The representation fingerprint must bind the model, candidate-conditioned serialization, model adapter or instruction, window rule, pooling or projection rule, vector format, and dimensions.
- Existing derived generations are incompatible with a new representation fingerprint and must be rebuilt rather than relabeled.
- Candidate-conditioned queries may increase per-request computation because each candidate has its own representation. Quality is evaluated before latency, memory, exact-backend, or ANN qualification.
- ANN issues #78 and #79 remain parked until the reset produces an exact shortlist. No prototype result enables live retrieval evidence automatically.
