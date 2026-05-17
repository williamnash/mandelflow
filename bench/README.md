# bench/

Aggregates per-stage timing + metadata into the talk-style scaling charts that go in the top-level README.

Operational notes (file layout, CLI) live here. The *interpretation* of those numbers — what each stage is supposed to teach about scaling, what's fair to compare, what hardware was used — lives in [`../docs/SCALING.md`](../docs/SCALING.md).

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

### Predicted-shape sketches

Until real runs land, `bench/predicted_plots.py` emits order-of-magnitude SVGs from the predictions in [`../docs/SCALING.md`](../docs/SCALING.md):

```bash
uv run python -m bench.predicted_plots
```

Outputs `results/predicted_kernel_story.svg`, `results/predicted_speedup.svg`, `results/predicted_orchestration_story.svg`. These will be overwritten by `bench.compare` when measured runs replace them.
