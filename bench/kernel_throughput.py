"""Measure and chart per-stage kernel throughput for s00–s06.

Unlike `predicted_plots`, these are *measurements* taken on the machine you
run this on. Throughput is pixels / best-of-N compute time (Mpx/s) for one
frame of the canonical wide view. One-time setup — numba JIT, torch/MPS
init, the GL context — is amortised via a warmup call and by passing a
prebuilt device/context, so we report the steady-state per-frame kernel
(how these stages are actually used: set up once, render many frames).

GPU stages are probed at a larger resolution than the CPU stages: the
current shader path recompiles its program every call, so at small frames
that fixed cost swamps the on-device compute. The per-stage resolution is
recorded alongside each number.

Run:
    uv run python -m bench.kernel_throughput

Outputs `results/kernel_throughput.{json,svg}`. The JSON is the raw record;
the SVG is the README chart.
"""
from __future__ import annotations

import importlib
import json
import platform
import time
from pathlib import Path

import matplotlib.pyplot as plt

RESULTS_DIR = Path(__file__).parent / "results"

# Canonical wide reference view. max_iter low (256) so most pixels escape
# fast — the standard throughput reference, not a deep-zoom worst case.
CENTER = (-0.75, 0.0)
WIDTH = 3.5
MAX_ITER = 256

# (label, module, resolution, kernel note, prebuilt-kwargs factory)
STAGES = [
    ("s00\nnaive",      "stages.s00_naive.compute",      200,  "interpreter",   None),
    ("s01\nnumpy",      "stages.s01_numpy.compute",      1000, "vectorised",    None),
    ("s02\nnumba",      "stages.s02_numba.compute",      1000, "JIT",           None),
    ("s03\nnumba opt",  "stages.s03_numba_opt.compute",  1000, "+ early exit",  None),
    ("s04\ndask local", "stages.s04_dask_local.compute", 1000, "+ all cores",   None),
    ("s05\ntorch MPS",  "stages.s05_gpu_torch.compute",  2000, "GPU, py-driven", "_torch_kwargs"),
    ("s06\nshader",     "stages.s06_gpu_shader.compute",  2000, "GPU, on-device", "_shader_kwargs"),
]


def _torch_kwargs() -> dict:
    from render.torch_device import get_torch_device
    return {"device": get_torch_device()}


def _shader_kwargs() -> dict:
    from render.gl_context import make_offscreen_context
    return {"ctx": make_offscreen_context(1, 1)}


def _best_time(call, n: int) -> float:
    call()  # warmup: pay JIT / lazy-init / first-compile once
    best = float("inf")
    for _ in range(n):
        t0 = time.perf_counter()
        call()
        best = min(best, time.perf_counter() - t0)
    return best


def measure() -> list[dict]:
    records = []
    for label, module, res, note, kw_factory in STAGES:
        compute_frame = importlib.import_module(module).compute_frame
        kwargs = globals()[kw_factory]() if kw_factory else {}

        def call():
            compute_frame(center_re=CENTER[0], center_im=CENTER[1], width=WIDTH,
                          resolution=res, max_iter=MAX_ITER, **kwargs)

        seconds = _best_time(call, n=3 if res <= 300 else 5)
        mpx_s = (res * res) / seconds / 1e6
        records.append({
            "label": label.replace("\n", " "),
            "plot_label": label,
            "note": note,
            "resolution": res,
            "seconds": seconds,
            "mpx_per_s": mpx_s,
        })
        print(f"{records[-1]['label']:16s} res={res:5d}  {seconds*1e3:9.2f} ms  {mpx_s:11.3f} Mpx/s")
    return records


def chart(records: list[dict], machine: str) -> Path:
    labels = [r["plot_label"] for r in records]
    values = [r["mpx_per_s"] for r in records]
    is_gpu = ["GPU" in r["note"] for r in records]
    colors = ["#e8a33d" if g else "#13aa9b" for g in is_gpu]

    fig, ax = plt.subplots(figsize=(10, 5.2))
    bars = ax.bar(labels, values, color=colors, width=0.66, zorder=3)
    ax.set_yscale("log")
    ax.set_ylabel("kernel throughput  (Mpx / s, log scale)")
    ax.set_ylim(min(values) * 0.4, max(values) * 3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, axis="y", linestyle=":", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)

    for bar, r in zip(bars, records):
        v = r["mpx_per_s"]
        txt = f"{v:.2f}" if v < 10 else f"{v:.0f}"
        ax.text(bar.get_x() + bar.get_width() / 2, v * 1.12, txt,
                ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax.text(bar.get_x() + bar.get_width() / 2, min(values) * 0.46, r["note"],
                ha="center", va="bottom", fontsize=8, color="#555", rotation=0)

    speedup = values[-1] / values[0]
    ax.set_title(f"One Mandelbrot kernel, seven implementations — {speedup:,.0f}× faster, s00 → s06",
                 fontsize=13, fontweight="bold")
    legend = [plt.Rectangle((0, 0), 1, 1, color="#13aa9b"),
              plt.Rectangle((0, 0), 1, 1, color="#e8a33d")]
    ax.legend(legend, ["CPU", "GPU"], frameon=False, loc="upper left")
    fig.text(0.99, 0.01,
             f"Measured on {machine}. Wide view, max_iter={MAX_ITER}, steady-state "
             f"(setup amortised). CPU 1000², GPU 2000², s00 200².",
             ha="right", va="bottom", fontsize=7.5, color="#888", style="italic")

    fig.tight_layout(rect=[0, 0.03, 1, 1])
    out = RESULTS_DIR / "kernel_throughput.svg"
    fig.savefig(out)
    plt.close(fig)
    return out


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    machine = platform.processor() or platform.machine()
    try:  # nicer name on macOS
        import subprocess
        machine = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip() or machine
    except Exception:
        pass

    records = measure()
    (RESULTS_DIR / "kernel_throughput.json").write_text(json.dumps(
        {"machine": machine, "center": CENTER, "width": WIDTH,
         "max_iter": MAX_ITER, "stages": records}, indent=2))
    out = chart(records, machine)
    print(f"\nwrote {out}")
    print(f"wrote {RESULTS_DIR / 'kernel_throughput.json'}")


if __name__ == "__main__":
    main()
