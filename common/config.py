"""Run configuration: presets + env-driven overrides.

One place where workload parameters live. Three named presets cover the
range of useful workloads from "laptop in seconds" to "cloud fan-out on
4K deep zoom":

  demo       — 120 frames, 720², shallow. Few seconds on a laptop.
  portfolio  — 600 frames, 1080², moderate depth. ~30s laptop, fits on s09.
  showcase   — 1800 frames, 2160², 1e-10 final width. The fan-out workload.

A `RunConfig` is the resolved set of values. Code reads `RunConfig.from_env()`
which picks a preset via `MANDELFLOW_PRESET` (default `demo`) and lets
individual `MANDELFLOW_*` env vars override specific fields.

Resolution is square; max_iter is scheduled per-frame (cheap outer frames,
expensive deep frames) via `common.schedule.max_iter_schedule`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace

from common.schedule import FINAL_WIDTH, INITIAL_WIDTH


@dataclass(frozen=True)
class RunConfig:
    n_frames: int = 120
    resolution: int = 720          # square
    initial_width: float = INITIAL_WIDTH
    final_width: float = FINAL_WIDTH
    fps: int = 30
    n_pods: int = 4                # = partition count for fan-out executors
    # Constant across frames. Mandelbrot's escape-on-radius + cardioid /
    # period-2 early-exit shortcuts make high `max_iter` nearly free on
    # outer frames where most pixels escape quickly. Pick a value high
    # enough for the deepest frame's interior to render correctly; outer
    # frames pay almost nothing extra.
    max_iter: int = 1024

    @property
    def video_seconds(self) -> float:
        return self.n_frames / self.fps


PRESETS: dict[str, RunConfig] = {
    "demo": RunConfig(
        n_frames=120,
        resolution=720,
        final_width=1e-3,
        n_pods=4,
        max_iter=1024,
    ),
    "portfolio": RunConfig(
        n_frames=600,
        resolution=1080,
        final_width=1e-6,
        n_pods=8,
        max_iter=2048,
    ),
    "showcase": RunConfig(
        n_frames=1800,
        resolution=2160,
        final_width=1e-10,
        n_pods=8,
        max_iter=8192,
    ),
}


_ENV_FIELDS = {
    "n_frames":      ("MANDELFLOW_N_FRAMES",      int),
    "resolution":    ("MANDELFLOW_RESOLUTION",    int),
    "initial_width": ("MANDELFLOW_INITIAL_WIDTH", float),
    "final_width":   ("MANDELFLOW_FINAL_WIDTH",   float),
    "fps":           ("MANDELFLOW_FPS",           int),
    "n_pods":        ("MANDELFLOW_N_PODS",        int),
    "max_iter":      ("MANDELFLOW_MAX_ITER",      int),
}


def from_env(default_preset: str = "demo") -> RunConfig:
    """Resolve a RunConfig from environment.

    1. Pick a preset via `MANDELFLOW_PRESET` (defaults to `default_preset`).
    2. Override any individual fields via `MANDELFLOW_<FIELD>` env vars.

    Unknown preset names raise ValueError.
    """
    preset_name = os.environ.get("MANDELFLOW_PRESET", default_preset).lower()
    if preset_name not in PRESETS:
        raise ValueError(
            f"MANDELFLOW_PRESET={preset_name!r} unknown. "
            f"Available: {sorted(PRESETS)}."
        )
    cfg = PRESETS[preset_name]

    overrides = {}
    for name, (env_key, caster) in _ENV_FIELDS.items():
        if env_key in os.environ:
            overrides[name] = caster(os.environ[env_key])
    if overrides:
        cfg = replace(cfg, **overrides)
    return cfg


def describe(cfg: RunConfig) -> str:
    """One-line summary suitable for logs."""
    return (
        f"n_frames={cfg.n_frames} resolution={cfg.resolution}² "
        f"width={cfg.initial_width:.2g}→{cfg.final_width:.2g} "
        f"max_iter={cfg.max_iter} n_pods={cfg.n_pods} fps={cfg.fps} "
        f"(video={cfg.video_seconds:.1f}s)"
    )


# Hint to suppress unused-import warnings when downstream re-exports fields().
_ = fields
