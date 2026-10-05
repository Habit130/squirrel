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
   or overlong path stays off. Every existing path component is checked, so a
   symlink or Finder alias in an ancestor is refused as well as one at the
   socket itself. Overlong paths are refused; the frontend does not `chdir`.
2. A locally fresh observation that the collector's desired policy is
   `enabled`. Initial, unknown, stale, `off`, and `paused` observations do not
   admit text and are not a global-effectiveness acknowledgement.

The collector policy acknowledgement scope remains
`collector_durable_desired_policy`. This frontend does not wait for policy on
the input path and does not change the legacy selection-recording switch.
Legacy selection recording may continue; archive pause does not stop it.

## What is recorded

Only confirmed `luna_pinyin` observations from ordinary clients are admitted
with text. The schema is read from librime for that operation. A cached or
hard-coded Luna identity is not enough. Initial, unknown, and switched schemas
do not admit commit or raw-finalization text; they may emit a content-free
exclusion notice. An exclusion notice elsewhere does not make a later terminal
payload eligible. The platform secure-input flag (`IsSecureEventInputEnabled`)
also omits text. That flag does not detect every credential
field. Same-app invisible field, window, or caret changes are not observed;
they stay an uncertainty, not a host-document interruption.

An Input Process is one observed composition. An Observed Continuity Segment
is cut on retarget, deactivation, schema/source change, pause/resume, known
loss, session recreation, and socket rebinding. A composition crossing a
socket rebind is excluded until its empty or terminal boundary; observations
admitted before the rebind are never redirected to the new collector. A
completed process is not itself a host-document claim.

A composition whose prefix was never observed is never admitted later. When an
observation with content is refused (capture not locally effective, unknown or
unsupported schema, secure input), the composition stays excluded. It becomes
eligible again only after the empty or terminal boundary closes it. Continuing
with the same preedit is not proof that nothing was hidden while capture was
paused or the input was sensitive. So enabling, resuming, or recovering
mid-composition does not backfill unobserved keys; the next composition starts
a new process, while a composition that was always observed is unaffected.

Global finalization is observed before the session is invalidated. The raw
terminal is recorded from the process and segment of the composition it closes,
and the continuity cut for deactivation is applied after that observation. If
pending text exists but the client is unavailable, a content-free unavailable
terminal is recorded; no text is inserted. An `insertText` return proves only
that call, not host persistence.

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
retries the same capture identity at most three times for retryable failures.
Every queued item is bound to the socket and binding generation active at
admission. Rebinding clears work that is still queued and invalidates an
in-flight policy reply from the old binding; an already-started send remains
confined to its original endpoint and is never replayed at the new endpoint.
Malformed or mismatched replies are not treated as successful acknowledgements.

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
live input source. Besides the contract and schema-gate scenarios it drives
`transition-edge` (a composition that becomes eligible part way through),
`terminal-provenance` (raw finalization through deactivation), `fault-burst`
(a held or absent collector), and `concurrent-status` (bounded management
queries during composition). `binding-controls` holds a policy reply across a
rebind and holds a real queued item immediately before drain, then checks both
collectors through their public query interfaces with positive and negative
identity controls. The contract suite asserts on the persisted
public query result, not only on observation kinds: a raw terminal that closes
an observed composition must carry that composition's `process_id` and
`continuity_segment_id`, and no stored payload may contain text composed while
ineligible. Stop only the collector that check started:

```sh
/usr/bin/python3 -m archive.cli --root "$ROOT" --socket "$SOCKET" collector stop
```

## Measured incremental cost

Attempt 1 and attempt 2 timing results are not certification for this repair.
A new MEAS-189-v1 manifest must be published before any attempt-3 sampling.
Unavailable primary endpoints stay unavailable; handler return is a separate
measurement. Backspace events must carry a character so production `handle`
reaches `processKey`. Attempt 2 pre-run manifest SHA-256
`3137367a399865810ba01f3fb69e9be5cd2dc56c236cb8853fbd2a8a611d13ec`.
The timing command exited 1. Every stratum had 2,000 pairs and zero
unavailable primary endpoints. short, long, and backspace met the paired
p95/p99 target. retype, number, space, mouse, and paging did not. That is
not a Pass. It is not pixels, host persistence, or ranking benefit.

Attempt 3 has not produced a certified timing run. Its sampling gate requires
a naturally Secure-Input-off, confirmed quiet window, and the secure-input flag
was observed on when the run was attempted. That is an environment blocker, not
a Pass, a noise waiver, or a relaxed threshold. The frozen target is unchanged:
per-stratum paired p95 <= 1 ms and p99 <= 3 ms including the whole
handler/action return, with the predeclared strata, warm-up, sample, and block
rules.

Attempt 4 repairs the binding, terminal, and ancestor-path regressions with
controlled producer-path gates and persisted public-query destination checks.
No attempt-4 timing sample is certified unless the naturally observed secure
input state is off and habit confirms the allocated quiet window. A missing
quiet window remains an environment blocker; it does not change the frozen
measurement procedure or target. Attempt 4 preflight found no confirmed quiet
window, started zero samples, and did not observe Secure Input state. The timing
driver returned `environment_blocker`; no timing result or certification
manifest was produced.

Attempt 2 overwrote two files under the original `.local/ac189-timing` root
while a fresh root was allocated for that attempt. Those original identities
cannot be restored, so the frozen preservation criterion stays a Fail for this
delivery regardless of later repairs. The disclosed current bytes and modes are
left as they are.

## Limits

No host-document read, no global keyboard hook, no model or GPU use, and no
claim that capture is complete, globally effective, or beneficial to ranking.
A successful collector control does not mean this frontend has observed it.
Restart does not unpause or backfill.
