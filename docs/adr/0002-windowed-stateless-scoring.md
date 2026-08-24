# ADR-0002: Windowed, Stateless Per-Request LLM Scoring

Status: accepted (2026-07-31; supersedes the append-only context decision implied in spec #16)

## Context

After phase one shipped, the daemon's memory (physical footprint) grew monotonically with typing: ~1.x GB → 6 GB in real use, and 17 GB in a growing-context reproduction. ADR-0001's designed operating point was a 1.85 GB inference peak; the growth far exceeded it. The 5-minute idle unload reset it to zero, but during active typing it only ever climbed.

Mechanism (verified): `server.py` rebuilt the **full** prefix KV cache from scratch on every context change (every commit) and persisted it across requests (`ModelState._prefix_cache`), then expanded it ×n (rerank window ≤ 32) per request. MLX's Metal memory pool grows to its high-water mark and is only cleared on the idle unload — never during active typing — so the footprint ratcheted up to the largest, most-expanded request seen and never shrank.

Two facts shaped the decision:

1. **The cross-request cache almost never hit.** Context changes on every commit, so `prefix_text != self._prefix_text` held on every keystroke and the cache was rebuilt anyway. The persistence bought no latency — only memory accumulation.
2. **Spec #16 chose append-only, non-sliding context so the prefix cache could be reused incrementally — but incremental reuse was never implemented.** The code paid the cost of append-only (a growing cache) without getting the benefit (incremental reuse).

Measured single-request peaks (fresh daemon, `phys_footprint_peak`): 64 chars / n=32 → 1.93 GB; 128 chars / n=32 → 2.08 GB; 64 chars / n=8 → 1.57 GB. The ×n expansion is the dominant, n-linear overhead.

## Decision

- **Fixed tail window.** Condition the model on the last N characters of 上文, default **N = 64**, reversing append-only. The window is a **daemon parameter** (`server.py` default plus `--context-window`, overridable in the launchd plist), not schema config — the daemon does not read schema config, and the socket protocol is unchanged. The schema key `window` is a different limit: the **candidate count** pulled for one rerank window (default 32), not the 上文 character budget.
- **Stateless per-request scoring.** Remove the cross-request `_prefix_cache` persistence. Build the window's KV fresh on each request, share it across the candidate batch within that request (keep the batched ×n expansion), and discard it after. `ModelState` retains only the loaded model/tokenizer — the 1.2 GB floor, still idle-unloaded at 5 minutes.
- **Keep batched ×n (Option A).** Do not decouple memory from n. The alternative (scoring candidates one at a time or in sub-batches against a single shared prefix) gives more headroom but changes the latency profile; latency is the hard priority, and the batched path is the one measured in #3 / ADR-0001.
- **Entire fix in `server.py`.** No C++/engine change, no app reinstall, protocol unchanged. The window is applied before the existing tokenization-seam logic (#12: shared `[:-4]` prefix, per-candidate `[-4:]+candidate` tail), which is preserved.

## Consequences

- Footprint becomes **flat** at the single-request peak (~1.9 GB at 64 chars / n=32 — the designed operating point per ADR-0001) instead of growing with session length. ~2 GB is a soft reference, not a hard cap; latency ranks above a strict ceiling.
- Latency is essentially unchanged: the cross-request cache was already missing and rebuilding on every keystroke, so removing it alters no compute path; the batched ×n (the latency-relevant part) is preserved.
- Long-range context is lost — the model sees only the last 64 characters. Accepted: IME next-word prediction is dominated by local context, and the owner's typing is short phrases and sentences where longer history adds little. N is tunable if the headless eval (#8) shows quality regression.
- Reverses the spec's append-only decision. The anti-sliding argument there presupposed incremental cache reuse that was never built, so it no longer binds.
- Relates to ADR-0001 (inference process boundary): the daemon remains the isolation boundary; this fixes the daemon's own memory rather than revisiting the boundary choice.
- Deferred (out of scope): incremental cross-request KV cache, ×n-decoupled scoring, model/KV quantization, and an active memory-threshold watchdog (unnecessary once memory is flat).
