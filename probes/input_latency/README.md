# Input latency probes (Squirrel#172)

Isolated librime per-key timing for the personal BGE experiment path.

```sh
python3 probes/input_latency/run.py --self-test
python3 probes/input_latency/run.py --collect --config .local/input-latency/config.json --output .local/input-latency/results
python3 probes/input_latency/run.py --repro --config .local/input-latency/config.json
```

`--repro` is expected nonzero when the 50/100 ms event-to-candidate target fails.

Report: `docs/diagnostics/input-latency.md`.
