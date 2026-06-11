"""Paint-race GIF: the same Mandelbrot tile painted by every stage at its
real measured throughput.

Seven tiles show the identical dusk fractal. Each paints top-to-bottom at a
pace set by that stage's `mpx_per_s` from `results/kernel_throughput.json`,
counters tick the Mpx/s, and tiles flash ✓ when done. The honest punchline
is the s05 dip — the PyTorch/MPS tile gets lapped by optimised CPU.

Time is log-compressed: the true span is ~1000×, which is unwatchable
literally (s06 finishes in one frame, s00 never moves). Mapping pace to
log10(throughput) keeps every stage visibly progressing while preserving the
ORDERING and the gaps — including s05 < s03/s04. The footer says as much.

Run (after `bench.kernel_throughput` has produced the JSON):
    uv run python -m bench.paint_race

Writes `docs/assets/paint_race.gif`.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from matplotlib import font_manager

from common.schedule import ZOOM_CENTER
from render.palettes import colorize
from stages.s03_numba_opt.compute import compute_frame

RESULTS = Path(__file__).parent / "results" / "kernel_throughput.json"
OUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "paint_race.gif"

TILE = 200
GAP = 18
PAD = 24
TITLE_H = 58
LABEL_H = 58
N_FRAMES = 60
HOLD_FRAMES = 14
FRAME_MS = 80
FILL_WINDOW = 0.78          # slowest stage finishes by this fraction of the loop
SLOWEST_REL = 0.12          # log-compressed fastest:slowest pace ratio

BG = (13, 17, 23)
TEAL = (19, 170, 155)
AMBER = (232, 163, 61)
INK = (230, 240, 238)
MUTED = (140, 140, 140)


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = font_manager.findfont(font_manager.FontProperties(
        family="DejaVu Sans", weight="bold" if bold else "normal"))
    return ImageFont.truetype(path, size)


def _build_frames() -> tuple[list[Image.Image], int, int]:
    data = json.loads(RESULTS.read_text())
    stages = data["stages"]
    mpx = np.array([s["mpx_per_s"] for s in stages])
    is_gpu = ["GPU" in s["note"] for s in stages]

    logs = np.log10(mpx)
    pace = SLOWEST_REL + (1 - SLOWEST_REL) * (logs - logs.min()) / (logs.max() - logs.min())
    inv = 1.0 / pace
    complete_at = inv / inv.max() * FILL_WINDOW
    speedup = mpx.max() / mpx.min()

    f_title = _font(24)
    f_call = _font(22)
    f_label = _font(20)
    f_num = _font(22)
    f_foot = _font(13, bold=False)

    iters = compute_frame(center_re=ZOOM_CENTER[0], center_im=ZOOM_CENTER[1],
                          width=1.6e-3, resolution=TILE, max_iter=1500)
    base = np.flipud(colorize(iters, "dusk"))
    dim = (base.astype(np.float32) * 0.05).astype(np.uint8)

    n = len(stages)
    W = PAD * 2 + n * TILE + (n - 1) * GAP
    H = TITLE_H + PAD + TILE + LABEL_H + PAD
    top_tiles = TITLE_H + PAD

    def frame(tfrac: float) -> Image.Image:
        px = np.full((H, W, 3), BG, dtype=np.uint8)
        for i in range(n):
            x0 = PAD + i * (TILE + GAP)
            p = min(tfrac / complete_at[i], 1.0) if complete_at[i] > 0 else 1.0
            rows = int(p * TILE)
            tile = dim.copy()
            if rows > 0:
                tile[:rows] = base[:rows]
            if 0 < rows < TILE:
                lo = max(0, rows - 2)
                tile[lo:rows] = np.clip(tile[lo:rows].astype(int) + 90, 0, 255)
            px[top_tiles:top_tiles + TILE, x0:x0 + TILE] = tile
        img = Image.fromarray(px)
        d = ImageDraw.Draw(img)

        d.text((PAD, TITLE_H // 2), "One fractal, painted at each stage's real speed",
               font=f_title, fill=INK, anchor="lm")
        d.text((W - PAD, TITLE_H // 2), f"{speedup:,.0f}× faster · s00 → s06",
               font=f_call, fill=AMBER, anchor="rm")

        for i, s in enumerate(stages):
            x0 = PAD + i * (TILE + GAP)
            accent = AMBER if is_gpu[i] else TEAL
            p = min(tfrac / complete_at[i], 1.0) if complete_at[i] > 0 else 1.0
            done = p >= 1.0
            d.rectangle([x0, top_tiles, x0 + TILE - 1, top_tiles + TILE - 1],
                        outline=accent if done else (60, 70, 80),
                        width=3 if done else 1)
            d.text((x0 + TILE / 2, top_tiles + TILE + 9),
                   s["plot_label"].replace("\n", " "), font=f_label, fill=INK, anchor="ma")
            val = mpx[i] * p
            txt = (f"{val:.2f}" if mpx[i] < 10 else f"{val:.0f}") + " Mpx/s"
            d.text((x0 + TILE / 2, top_tiles + TILE + 33), txt, font=f_num,
                   fill=accent, anchor="ma")
            if done:
                d.text((x0 + TILE - 8, top_tiles + 6), "✓", font=f_num, fill=accent, anchor="ra")

        d.text((W - PAD, H - 10),
               "tiles paint at measured Mpx/s · pace ∝ log throughput (true span ~1000×)",
               font=f_foot, fill=MUTED, anchor="rs")
        return img

    frames = [frame(k / (N_FRAMES - 1)) for k in range(N_FRAMES)]
    frames += [frames[-1]] * HOLD_FRAMES
    return frames, W, H


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames, W, H = _build_frames()
    frames[0].save(OUT, save_all=True, append_images=frames[1:],
                   duration=FRAME_MS, loop=0, disposal=2, optimize=True)
    print(f"wrote {OUT}  {W}x{H}  {len(frames)} frames")


if __name__ == "__main__":
    main()
