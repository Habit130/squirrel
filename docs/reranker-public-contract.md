# Reranker public contract

Pinned released plugin: [`Habit130/librime-llm-rerank@v1.0.2`](https://github.com/Habit130/librime-llm-rerank/releases/tag/v1.0.2) (`7ca5966135faf8a3f2c8710ef88b4a97af772ccf`). Squirrel's fast path downloads that tag from `action-install.sh`. Current plugin source still matches the scoring keys, empty-only socket home expansion, protocol v2 identity fields, 200 ms deadline, and whole-window fallback below. Later evidence-only keys are not part of this public scoring example.

Machine-readable copy: [`reranker-public-contract.json`](reranker-public-contract.json). Drift check:

```sh
python3 scripts/check-reranker-public-contract.py
```

## Executable schema example

Copy-paste against plugin `v1.0.2`. Omit `socket_path` so the filter builds `$HOME/Library/Application Support/Squirrel/llm-rerank.sock`. An explicit value is used literally; `~` is not expanded.

```yaml
engine:
  filters:
    - llm_rerank
llm_rerank:
  reranking_enabled: true
  recording_enabled: false
  evidence_enabled: false
  window: 32
  alpha: 0.0
  sys_coeff: 1.0
  usr_coeff: 1.0
  gamma: 2.0
  saturate_k: 3.0
  deadline_ms: 200
  baseline_policy_id: mean-token-lm-v1
```

`alpha` must be greater than `0.0` before the filter opens the daemon socket. The default `0.0` keeps the language-model term off. With any v2 switch present, omitted v2 switches default to `false`; write all three explicitly.

## Schema keys

| Key | Default | Meaning | v1.0.2 source |
| --- | --- | --- | --- |
| `reranking_enabled` | true when no switch keys are set; false if any v2 switch is present and this key is omitted | Visible rerank | [`src/llm_rerank_config.cc`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_config.cc) |
| `recording_enabled` | false | Selection-event recording | [`src/llm_rerank_config.h:39`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_config.h#L39) |
| `evidence_enabled` | false | Apply retrieval evidence | [`src/llm_rerank_config.h:40`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_config.h#L40) |
| `window` | 32 | Candidate count in one rerank window, not preceding-text characters | [`src/llm_rerank_filter.h:142`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.h#L142) |
| `alpha` | 0.0 | Language-model coefficient; daemon scoring only when `> 0` | [`src/llm_rerank_filter.h:147`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.h#L147) |
| `sys_coeff` | 1.0 | System-dictionary weight coefficient | [`src/llm_rerank_filter.h:148`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.h#L148) |
| `usr_coeff` | 1.0 | User-dictionary weight coefficient | [`src/llm_rerank_filter.h:149`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.h#L149) |
| `gamma` | 2.0 | Evidence coefficient; v2 with `evidence_enabled: false` forces the plan term to 0 | [`src/llm_rerank_filter.h:150`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.h#L150) |
| `saturate_k` | 3.0 | Evidence saturation | [`src/llm_rerank_filter.h:151`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.h#L151) |
| `deadline_ms` | 200 | Synchronous daemon budget for connect, write, and read | [`src/llm_rerank_filter.h:152`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.h#L152) |
| `verbose` | false | Extra filter/scorer logs | [`src/llm_rerank_filter.h:153`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.h#L153) |
| `baseline_policy_id` | mean-token-lm-v1 | Scoring-policy identity sent on the wire | [`src/llm_rerank_filter.h:157`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.h#L157) |
| `socket_path` | `$HOME/Library/Application Support/Squirrel/llm-rerank.sock` | Daemon socket; see expansion rules | [`src/llm_rerank_filter.cc:409-414`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.cc#L409-L414) |

Stale key: `enable` is legacy. Alone, it still toggles reranking. Any v2 switch makes `enable` ignored. Do not document it as the public switch.

## Two windows

| Limit | Owner | Default | What it counts |
| --- | --- | --- | --- |
| `llm_rerank/window` | schema | 32 | Candidates pulled for one rerank window |
| `--context-window` | daemon (`CONTEXT_WINDOW`) | 64 | Trailing preceding-text characters (上文) |

They are not interchangeable. The daemon does not read schema config ([ADR-0002](adr/0002-windowed-stateless-scoring.md)). Source: [`daemon/server.py:39`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/daemon/server.py#L39).

## Socket path expansion

| Value | Filter (`v1.0.2`) | Daemon default |
| --- | --- | --- |
| Omitted or empty | `getenv("HOME")` + `/Library/Application Support/Squirrel/llm-rerank.sock` | `os.path.expanduser("~/Library/Application Support/Squirrel/llm-rerank.sock")` |
| Explicit string | Used literally. A leading `~` is not expanded and will not match the daemon socket. | `--socket` is used as given; the built-in default is the only path the daemon expands. |

## Scoring protocol (version 2)

Newline-delimited JSON over the Unix socket. Identity fields are required.

Request members: `version`, `request_id`, `plan_identity`, `baseline_policy_id`, `context`, `candidates`.

```json
{
  "version": 2,
  "request_id": "llm-score-request-v1:<pid>:<n>",
  "plan_identity": "<plan identity>",
  "baseline_policy_id": "mean-token-lm-v1",
  "context": "<preceding text>",
  "candidates": ["c1", "c2"]
}
```

Success response members: `version`, `request_id`, `plan_identity`, `scores`.

```json
{
  "version": 2,
  "request_id": "llm-score-request-v1:<pid>:<n>",
  "plan_identity": "<plan identity>",
  "scores": [0.0, 0.0]
}
```

Identity-bound error members: `version`, `request_id`, `plan_identity`, `error`. The `error` object members are exactly `code`, `message`, `occurred_at`, `retryable`, `phase`, `remediation`, `cause` (`cause` is JSON `null`). Any extra or missing member is a protocol failure.

Source: [`src/llm_scorer.cc`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_scorer.cc) (`kLlmScoringProtocolVersion = 2`).

## Blocking, deadline, fallback

The released filter performs a **synchronous** bounded daemon exchange on the candidate path. `deadline_ms` (default **200**) covers connect, write, and read. This adds up to that budget to panel appearance. It does not wait past the deadline, and it does not block text commit.

Any timeout, transport failure, protocol/identity mismatch, non-finite score, or scoring fault emits the **entire original window** in arrival order. The candidate set is unchanged.

Source: [`src/llm_rerank_filter.cc`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_rerank_filter.cc) (`if (!reranked)` passthrough) and [`src/llm_scorer.cc`](https://github.com/Habit130/librime-llm-rerank/blob/7ca5966135faf8a3f2c8710ef88b4a97af772ccf/src/llm_scorer.cc).
