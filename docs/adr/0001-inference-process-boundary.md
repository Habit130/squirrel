# ADR-0001: Inference Process Boundary

Status: accepted (2026-07-31, issue #4)

## Context

The candidate reranking plugin needs Qwen3-0.6B-Base inference to score candidates. #3 measured the latency budget on Apple M5 / 24 GB:

| Metric | Value |
|--------|-------|
| Hot refresh N=32 (KV cached, batched suffix) | 42.5 ms (p95 43.3) |
| Hot refresh N=8 / N=16 | 23.3 / 29.7 ms |
| Cold start (load + first forward) | 0.33 s |
| Context KV miss rebuild | 19.6 ms |
| Resident memory (RSS) | 1.45 GB |
| Inference peak (Metal) | 1.85 GB |
| Unix socket round-trip (few KB payload) | < 1 ms |

The IME keystroke budget is tens of ms. Synchronous in-keystroke-path inference at N=32 already exceeds it. The inference cost is bandwidth-bound (~1.2 GB weights + 151936-dim lm_head per forward); the per-candidate marginal cost is cheap (~0.6 ms) but the fixed per-forward cost (~18-20 ms) cannot be reduced without quantization.

Two options were considered:

- **In-process**: link the inference runtime into the librime plugin dylib, running inside the IMKServer process.
- **Daemon**: a separate process holds the model; the filter communicates via unix socket.

## Decision

**Daemon.** A standalone Python + MLX process serves scoring requests over a unix domain socket. The librime filter sends a synchronous JSON request and blocks until scores return.

### Lifecycle

- **launchd** manages the process: auto-start at login, auto-restart on crash, cleanup at logout.
- **5-minute idle timeout** unloads the model (releases 1.45 GB). Next request triggers lazy reload (0.33 s cold start). Lock screen / sleep achieves the same effect naturally: no typing → no requests → timeout fires.
- Model is **not** loaded at daemon startup; first request pays the 0.33 s once.

### Fault tolerance

- Daemon unreachable (not started, crashed, or response > 200 ms timeout): filter degrades to identity passthrough (original candidate order). Typing is never blocked.
- This is the first rung of the degradation ladder decided in #14.

### Communication

- Socket path: `~/Library/Application Support/Squirrel/llm-rerank.sock`
- Protocol: JSON over unix stream socket
  - Request: `{"context": "<preceding text>", "candidates": ["c1", "c2", ...]}`
  - Response: `{"scores": [s1, s2, ...]}`
- Payload is a few KB; JSON parse < 0.1 ms; human-readable for debugging (`socat`).

### Implementation

- Python + MLX (validated by #3). Daemon = a Python script + a launchd plist.
- Socket is accessible to any local process — future general-purpose completion endpoints can be added without protocol breakage.

### Synchronous, for now

The filter blocks until scores arrive, then emits the final reranked order. The ~42 ms is added to panel appearance latency. This is accepted for phase 1; async rerank (show original order immediately, refresh when scores arrive) is a future optimization to be evaluated after real-world experience.

## Consequences

- The IMK process stays lightweight; model memory and crash domain are isolated.
- Model can be swapped (different checkpoint, quantized variant) by restarting the daemon — no C++ recompilation.
- A launchd plist must be installed alongside the input method (packaging concern for `make package`).
- First keystroke after idle pays 0.33 s cold start (acceptable; subsequent are hot).
- Synchronous blocking means panel appearance is ~42 ms slower than without LLM. If this proves noticeable in daily use, the async path (filter passthrough + background refresh via Squirrel frontend) is the escape hatch — it requires a Swift-side panel-refresh channel but no daemon changes.
- The socket is a shared local service by design; other tools on the machine can query the same model.
