# Frontend input archive

Squirrel observes already-produced input and page state and admits owned
snapshots to the accepted `input-archive-v1` collector. It does not generate,
score, or rerank candidates, and it does not open archive storage.

Install, upgrade, and merge leave capture off. Finding a running collector is
not opt-in. No input-path code launches a collector or spawns a process.

## Opt-in

Both of these are required before any input text is admitted:

1. `input_archive/socket` in the Squirrel config, an absolute non-aliased local
   socket path that is not a known synchronized destination and that fits
   macOS `sun_path` (103 bytes). Absence, empty, symlink, alias, cloud path,
   or overlong path stays off. Overlong paths are refused; the frontend does
   not `chdir`.
2. A locally fresh observation that the collector's desired policy is
   `enabled`. Initial, unknown, stale, `off`, and `paused` observations do not
   admit text and are not a global-effectiveness acknowledgement.

The collector policy acknowledgement scope remains
`collector_durable_desired_policy`. This frontend does not wait for policy on
the input path and does not change the legacy selection-recording switch.
Legacy selection recording may continue; archive pause does not stop it.

## What is recorded

Only confirmed `luna_pinyin` observations from ordinary clients are admitted
with text. Unsupported or unknown schemas and the platform secure-input flag
(`IsSecureEventInputEnabled`) produce a content-free exclusion notice, or
nothing if capture is not enabled. That flag does not detect every credential
field. Same-app invisible field, window, or caret changes are not observed;
they stay an uncertainty, not a host-document interruption.

An Input Process is one observed composition. An Observed Continuity Segment
is cut on retarget, deactivation, schema/source change, pause/resume, known
loss, and session recreation. A completed process is not itself a
host-document claim. Enabling mid-composition does not backfill unobserved
keys. An `insertText` return proves only that call, not host persistence.

Normal engine commit, raw finalization, unavailable client, and unknown
outcome are distinct. Candidate texts are copied in the order librime already
returned. No extra candidate request or panel refresh is added for capture.

## Session metadata

Before each engine operation the controller publishes content-free tokens as
Rime session properties:

| Property | Meaning |
| --- | --- |
| `squirrel_archive_source` | Frontend source instance |
| `squirrel_archive_process` | Current Input Process |
| `squirrel_archive_update` | Current update |
| `squirrel_archive_segment` | Current continuity segment |
| `squirrel_archive_association` | `valid` or `invalid` |

These are not an LM request join. Later plugin work may read them with
`get_property`. They are invalidated at boundaries and ineligibility. Setting
them does not request candidates or refresh the panel.

## Transport and loss

The input path copies owned Swift values and attempts a bounded queue
insertion. It does not serialize, compress, connect, flush, or wait for the
collector, a full queue, or a management lock.

| Bound | Value |
| --- | --- |
| Queue count | 256 |
| Queue bytes | 1048576 |
| Event budget | 65536 |
| Batch | 64 |
| Freshness | 2000 ms |
| Heartbeat | 500 ms |

Commit, raw finalization, cancellation, unavailable/unknown outcomes, and loss
notices outrank intermediate snapshots. A refused or displaced snapshot is not
reported as durable. Admitted is not durable. Queue saturation, collector
capacity stop, storage failure, and an unknowable crash tail stay separate.
The frontend does not invent dropped counts it cannot prove.

Background transport speaks `admit_batch` and `policy_observe` on the accepted
Interface: 4-byte big-endian length plus UTF-8 JSON. Connect uses the absolute
socket path and does not change the process working directory. A failed send
retries the same capture identity.

## Timing

Keyboard latency starts at `handle(_:client:)` entry and ends when the
corresponding marked-text or panel update call returns. If neither happens,
the endpoint is `unavailable`. Mouse selection and paging start at
`selectCandidate` and `page(up:)`, not at a fabricated key entry. These are
update-call completions, not pixels, host persistence, or ranking benefit.
`NSEvent.timestamp` is not treated as `mach_absolute_time`; event-queue wait
stays `unknown` unless a compatible timestamp exists.

The isolated check is `scripts/check-input-archive-frontend.py`. It compiles
the production controller, panel, and librime paths with an invented
`luna_pinyin` fixture. It is not a pure planner and it does not install a
live input source. Stop only the collector that check started:

```sh
/usr/bin/python3 -m archive.cli --root "$ROOT" --socket "$SOCKET" collector stop
```

## Measured incremental cost

MEAS-189-v1 pre-run manifest SHA-256
`f14e3a2027cd357dfb9f5ee47643009ba1cce36719d35883e60cb0fc5d3f24ee`.
The timing command exited 1. Retained raw
`.local/ac189-timing/raw-1790989786.json` has 2,000 pairs in each of the
eight strata. Paired p50 added cost is about 0.01–0.04 ms. Paired p95/p99
exceed 1/3 ms for retype, number, space, mouse, and paging because those
operations already vary by several milliseconds with capture off; the spikes
do not line up across a pair. That run is not a Pass. It is not pixels, host
persistence, or ranking benefit.

## Limits

No host-document read, no global keyboard hook, no model or GPU use, and no
claim that capture is complete, globally effective, or beneficial to ranking.
A successful collector control does not mean this frontend has observed it.
Restart does not unpause or backfill.
