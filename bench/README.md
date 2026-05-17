# bench/

Aggregates per-stage timing + metadata into the talk-style scaling charts that go in the top-level README.

## Output convention

Committed bench outputs are **SVG for charts** and **JSON for raw numbers**. PNG is excluded by `.gitignore` and reserved for transient local previews — SVG is text, diffs cleanly in git, and scales without quality loss.

- `results/<run-id>.json` — wall time, peak memory, iteration count, scale parameters per stage. Small (~1 KB each).
- `results/scaling.svg` — regenerable comparison chart across stages.
- `results/speedup.svg` — speedup bar chart against stage 00.

Regenerate everything from the committed JSONs:

```bash
uv run python -m bench.compare
```

Stages call `bench.record(stage_id, run_metadata)` from their `run.py` to drop a new JSON in `results/`.
