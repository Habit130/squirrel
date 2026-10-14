# Input latency diagnosis (Squirrel#172, AC-172-v1)

Diagnosis only. This delivery does not claim the live path is repaired.

## Endpoints

| ID | What is timed | Clock |
| --- | --- | --- |
| `event_to_candidate_update` | Isolated `rime_session` handler: `process_key`/`select` + `get_commit` + `get_context` until the librime candidate page is available | `CLOCK_MONOTONIC` |
| `process_key` / `get_context` | Splits of the same call | same |
| `queue_delay` | In-process parse overhead only. No IMK event queue exists in this harness | same |
| `daemon_evidence` | Isolated Unix-socket evidence request (status/timing only; no candidate text in committed artifacts) | Python `monotonic` |

**Actual vs proxy.** `event_to_candidate_update` is a librime proxy for “candidates are ready to render”. It is **not** IMK host dispatch, marked-text round-trip through a real `IMKTextInput` client, or vsync/panel presentation. Those frontend/presentation endpoints were **not exercised** (no replacement IM install, no live key injection). That is an environment/permission gap, not a silent pass.

## Isolation

Writable roots live under the worktree `.local/input-latency/` plus a 0700 socket dir `/tmp/s172` (AF_UNIX path-length limit). Before probes run, paths are rejected if they resolve to `~/Library/Rime` or `~/Library/Application Support/Squirrel`, including symlink aliases. Shared schema data is read-only from the installed app `SharedSupport`. Facts/socket/HOME are invented and disposable. Live user dir and private fact store are never copied.

Ticket-owned daemon: `--serve --health-only --facts-root <isolated> --socket /tmp/s172/llm-rerank.sock`. No live daemon restart.

## Identities

| Item | Value |
| --- | --- |
| Squirrel base | `20969777183d7d9998ef88780a71e4b2dbe20410` |
| Plugin source pin (read-only) | `Habit130/librime-llm-rerank@060254e544f73187f2b095928943320354d7cbca` |
| Installed plugin SHA-256 | `8b39a34163afa57829e4a61ae2bcb9566b364717fa7e1b367fca6d5fa281d0f0` (matches #170; copy-out, not rebuilt) |
| Installed librime SHA-256 | `b39924157ababcd663384a1f93929b7d6a9eaee1e40fb15705ea360b8e373439` (`1.17.0`) |
| Profile | `personal-bge-experiment-v1`: `alpha=0`, window 32, `deadline_ms=200`, evidence/recording/reranking on for arm A |
| Model | Authorized read-only `BGE-M3`; representation id matches live compiled schema |
| Installed vs source | Installed dylib is the measurement binary. Source pin is reference only |

Compiled disposable schemas (verified after deploy):

- **A:** processors include `llm_rerank_recorder`; filters end with `llm_rerank`; `evidence_enabled: true`
- **B:** same except `evidence_enabled: false`
- **C:** recorder and `llm_rerank` filter removed

Live pre/post hashes of plugin, librime, `luna_pinyin.custom.yaml`, compiled schema, and `evidence.json` were unchanged.

## Commands

```sh
python3 probes/input_latency/run.py --self-test
python3 probes/input_latency/run.py --collect --config .local/input-latency/config.json --output .local/input-latency/results
python3 probes/input_latency/run.py --repro --config .local/input-latency/config.json
```

`--repro` exits 2 when the 50/100 ms assertion fails (expected red).

Raw rows: `.local/input-latency/results/timing.jsonl` (gitignored). Aggregation is nearest-rank p50/p95/p99/max on `event_to_candidate_ns`.

## Machine conditions

Quiet-machine ownership was held for collect/repro intervals. Live Squirrel and the live BGE daemon were left running (contention recorded; not stopped). Load averages during collect were about 2.5–3.7 on 10 CPUs. One ticket-owned BGE daemon at a time.

## Results (nearest-rank; milliseconds)

Warm burst (as-fast-as-possible; 1050 letter keys/arm, 3 runs). **Not** human cadence.

| Arm | n | p50 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- |
| A evidence on | 1050 | 0.357 | 0.452 | 0.516 | 0.746 |
| B evidence off | 1050 | 0.161 | 0.193 | 0.261 | 0.454 |
| C no custom filter | 1050 | 0.026 | 0.037 | 0.056 | 0.184 |

Busy-BGE / live-like cadence (isolated daemon occupied with real BGE evidence; 25 keys):

| Scenario | n | p50 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- |
| A `busy_bge` | 25 | 0.657 | **199.9** | **202.6** | 202.6 |

Direct isolated evidence (2 invented candidates, real BGE): **12.6 s** (`warmup.json`). 32 distinct candidates after warmup: **5.1 s**. Both ≫ 200 ms deadline.

`--repro` (20 keys while BGE busy): n=20, p95=200.7, p99=201.6, **symptom=true**, exit 2.

Cold samples (15 keys/arm) stay separate and are not used as p99 certification.

Apply traces (identity-only): 127 `applied`, 1399 `fallback` across the isolated store. Fallback is the common outcome when the deadline expires or the socket is down.

Live health (status only, no scoring against private facts): Orchestration saw a 3 s timeout; collect saw `ConnectionRefusedError`. Live daemon unresponsiveness is current, not assumed from the old #170 “no generation” note.

## Hypotheses

1. **Candidate generation (librime/octagram) is the per-key cost.** **Rejected.** Arm C p95 0.037 ms.
2. **Custom filter/recording without evidence is the per-key cost.** **Rejected as primary.** Arm B p95 0.193 ms.
3. **Online evidence / BGE encode / daemon queueing on the synchronous filter path.** **Supported.** Real BGE evidence is 5–12 s; schema deadline is 200 ms; when the daemon is busy, `get_context` waits ~200 ms then fallback. Burst typing with a dead socket is fast because connect fails immediately — that is **not** live human cadence.
4. **Frontend/IMK/host presentation.** **Unresolved.** Not exercised. Do not treat daemon or librime times as panel vsync.
5. **Live daemon hung/unresponsive, so every live key pays the 200 ms deadline.** **Supported as the live-shaped cause**, with isolated busy-daemon p95 ~200 ms as the matching mechanism. Isolated burst-A p95 ~0.45 ms does **not** prove live is fast.

## Classification

Observed cost of the reported slow candidate appearance: **online evidence / BGE / daemon queueing on the synchronous 200 ms filter path**, not candidate generation, not recording-only work. Frontend/host remains unknown.

## Limitations

- IMK marked-text and panel presentation: gap.
- Burst 1000-key A/B/C is a complete sample for filter/generation overhead; it is not live-cadence proof.
- `busy_bge` n=25: enough to show the 200 ms deadline, not a 1000-key busy-daemon p99 certification.
- Derived-state builder status from health: `maintenance_state=serving`; no claim that live generation is unpublished based only on #170.
- Instrumentation overhead: empty `clock_gettime` loop ~17 ns/call; negligible vs 200 ms.

## Follow-up (smallest justified scope)

**Repository: `Habit130/librime-llm-rerank`.** Stop blocking candidate emission on BGE evidence. The encode is an order of magnitude above `deadline_ms`; the filter still delays `get_context` up to that deadline before passthrough. Also restore live daemon health/responsiveness (status-only hang). Do not implement ranking in `sources/`. Do not shrink the window or deadline in this diagnosis ticket.

## Cleanup

Ticket-owned `rime_session` and isolated daemon processes were terminated after collect/repro. Quiet-machine ownership released. Fixtures and this report kept. No `sources/` throwaway instrumentation was added.

## Reproduction

Red: `python3 probes/input_latency/run.py --repro --config .local/input-latency/config.json` (exit 2). Endpoint: `event_to_candidate_update` under isolated BGE-busy daemon. Target p95 ≤ 50 ms and p99 ≤ 100 ms is **not** met. That is valid diagnosis evidence, not a failed repair.
