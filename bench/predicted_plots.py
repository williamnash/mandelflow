"""Generate the *predicted* scaling charts for `docs/SCALING.md`.

These are sketches — order-of-magnitude estimates derived from the
per-stage predictions in `docs/SCALING.md`, not measurements. They give
the doc a visual spine before real numbers land. When `bench/results/`
fills up with measured runs, the real `bench/compare` will overwrite
these with charts from data.

Run:
    uv run python -m bench.predicted_plots

Outputs three SVGs under `bench/results/predicted_*.svg`.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

RESULTS_DIR = Path(__file__).parent / "results"

# Predicted pixel throughput (Mpx/s) at the fixed reference scale
# (1000² resolution, max_iter = 256, canonical wide view) on a stock
# Apple M-series laptop. Order-of-magnitude estimates from the
# per-stage analysis in docs/SCALING.md.
KERNEL_STAGES = [
    ("s00\nnaive",      0.001,    "interpreter"),
    ("s01\nnumpy",      0.5,      "vectorised"),
    ("s02\nnumba",      50.0,     "JIT"),
    ("s03\nnumba opt",  200.0,    "+ early exits"),
    ("s04\ndask local", 1_000.0,  "+ 8 cores"),
    ("s05\ntorch MPS",  500.0,    "GPU, py-driven"),
    ("s06\nshader",     50_000.0, "GPU, on-device"),
]

# Predicted multi-frame throughput (frames/s wall) and total
# compute-seconds at 1080p, canonical zoom schedule. None = stage not
# implemented yet (rendered as a hatched placeholder bar).
ORCH_STAGES = [
    ("s07\nlocal zoom",   2.0,   100,    "1 GPU"),
    ("s08\ncloud CPU",    1.0,   2_000,  "1 VM × 8 cores"),
    ("s09\nfanout CPU",   3.0,   1_500,  "8 tasks × 2 vCPU"),
    ("s10\ncloud GPU",    None,  None,   "placeholder"),
    ("s11\nGKE GPU",      10.0,  6_000,  "4 pods × T4"),
]


def _style(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    ax.set_axisbelow(True)


def _predicted_banner(ax: plt.Axes) -> None:
    ax.text(
        0.99, 0.97, "PREDICTED — no measurements yet",
        transform=ax.transAxes, ha="right", va="top",
        fontsize=9, color="#888", style="italic",
    )


def kernel_story_chart() -> Path:
    """s00 → s06: predicted pixel throughput at fixed (1000², 256)."""
    labels = [s[0] for s in KERNEL_STAGES]
    throughputs = [s[1] for s in KERNEL_STAGES]
    annotations = [s[2] for s in KERNEL_STAGES]

    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.bar(labels, throughputs, color="#3a6ea5", edgecolor="#1f3a5f")

    ax.set_yscale("log")
    ax.set_ylabel("Predicted pixel throughput (Mpx/s, log scale)")
    ax.set_title(
        "Kernel story: same problem, seven implementations\n"
        "Predicted throughput at 1000² × max_iter=256, canonical wide view"
    )
    ax.set_ylim(1e-4, 1e6)

    for bar, note in zip(bars, annotations):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.4,
            note, ha="center", va="bottom", fontsize=9, color="#444",
        )

    _style(ax)
    _predicted_banner(ax)
    fig.tight_layout()

    out = RESULTS_DIR / "predicted_kernel_story.svg"
    fig.savefig(out, format="svg")
    plt.close(fig)
    return out


def speedup_bar_chart() -> Path:
    """Speedup vs s00 at the same fixed reference scale."""
    baseline = KERNEL_STAGES[0][1]
    labels = [s[0] for s in KERNEL_STAGES[1:]]
    speedups = [s[1] / baseline for s in KERNEL_STAGES[1:]]

    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.bar(labels, speedups, color="#c0573d", edgecolor="#6f2d1c")

    ax.set_yscale("log")
    ax.set_ylabel("Predicted speedup vs s00 (×, log scale)")
    ax.set_title(
        "Predicted speedup over the naive baseline\n"
        "Same input, same view, same max_iter — only the kernel changes"
    )
    ax.set_ylim(1, 1e9)

    for bar, factor in zip(bars, speedups):
        label = f"{factor:,.0f}×" if factor < 1e4 else f"{factor:.0e}×"
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.4,
            label, ha="center", va="bottom", fontsize=9, color="#444",
        )

    _style(ax)
    _predicted_banner(ax)
    fig.tight_layout()

    out = RESULTS_DIR / "predicted_speedup.svg"
    fig.savefig(out, format="svg")
    plt.close(fig)
    return out


def orchestration_story_chart() -> Path:
    """s07 → s11: predicted wall-time frames/s and total compute-seconds.

    Two subplots side by side. Placeholder stages (s09, s10) are shown
    as hatched grey bars so the gap in the story is visible.
    """
    labels = [s[0] for s in ORCH_STAGES]
    fps = [s[1] for s in ORCH_STAGES]
    compute_s = [s[2] for s in ORCH_STAGES]
    notes = [s[3] for s in ORCH_STAGES]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.5))

    def _plot(ax, values, ylabel, title, color):
        x = np.arange(len(labels))
        plotted = [v if v is not None else 0 for v in values]
        bar_colors = [color if v is not None else "#dddddd" for v in values]
        edge_colors = ["#1f3a5f" if v is not None else "#888888" for v in values]
        hatches = ["" if v is not None else "//" for v in values]

        bars = ax.bar(
            x, plotted, color=bar_colors, edgecolor=edge_colors, hatch=hatches,
        )
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel(ylabel)
        ax.set_title(title)

        for bar, value, note in zip(bars, values, notes):
            if value is None:
                ax.text(
                    bar.get_x() + bar.get_width() / 2, ax.get_ylim()[1] * 0.05,
                    "(placeholder)", ha="center", va="bottom",
                    fontsize=8, color="#888", style="italic", rotation=90,
                )
            else:
                ax.text(
                    bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.05,
                    note, ha="center", va="bottom", fontsize=8, color="#444",
                )
        _style(ax)

    _plot(
        ax1, fps,
        "Predicted wall-time throughput (frames/s)",
        "Wall time: how fast does the animation finish?",
        "#3a6ea5",
    )
    ax1.set_ylim(0, max(v for v in fps if v is not None) * 1.25)
    _plot(
        ax2, compute_s,
        "Predicted total compute-seconds (CPU- or GPU-s)",
        "Total cost: how many machine-seconds did it consume?",
        "#5a8a3a",
    )
    ax2.set_yscale("log")
    ax2.set_ylim(10, 1e5)

    fig.suptitle(
        "Orchestration story: same shader, four deployment shapes\n"
        "1080p canonical zoom; s10 hatched as placeholder (GCP-quota blocked)",
        y=1.02,
    )
    fig.text(
        0.01, 0.99, "PREDICTED — no measurements yet",
        ha="left", va="top", fontsize=9, color="#888", style="italic",
    )
    fig.tight_layout()

    out = RESULTS_DIR / "predicted_orchestration_story.svg"
    fig.savefig(out, format="svg", bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        kernel_story_chart(),
        speedup_bar_chart(),
        orchestration_story_chart(),
    ]
    for p in paths:
        print(f"wrote {p.relative_to(Path(__file__).parent.parent)}")


if __name__ == "__main__":
    main()
