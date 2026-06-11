"""Colour palettes and iteration→RGB mapping for the renderer.

Two ideas live here:

1. **Cyclic palettes.** A handful of custom gradients whose first and last
   colours match, so they tile seamlessly when the colour index wraps.

2. **Cyclic colouring keyed to √(iteration count).** The colour index is
   `(sqrt(iterations) * freq) mod 1`, so the palette *repeats* as the
   iteration count climbs. Wherever the count changes fastest — the set
   boundary, i.e. the interesting structure — the colour varies fastest and
   richest; the flat fast-escape "sea" changes slowly. This deliberately
   puts the strongest gradient on the structure, the opposite of a global
   normalisation (which spends most of its range on the boring sea). The
   √ spacing evens out the apparent band widths. The set itself (bounded
   pixels carrying the array's maximum value, per the compute contract) is
   painted a solid colour, black by default.

The mapping depends only on each pixel's own iteration count, not on any
per-frame or global statistic — so it is temporally stable and the same
function serves both stills and animation without flicker.

Note on banding: stored iteration counts are integers, so very shallow
views (few distinct counts) still show faint steps. Truly smooth colouring
needs the *fractional* escape value (`n + 1 - log2(log|z|)`), which the
data product doesn't store — the README banner recomputes it for that one
high-quality asset. See `docs/GOTCHAS.md`.
"""
from __future__ import annotations

import matplotlib
import numpy as np
from matplotlib.colors import Colormap, LinearSegmentedColormap


def _cyclic(name: str, colors: list[str]) -> LinearSegmentedColormap:
    """Build a seamless cyclic colormap (first colour repeated at the end)."""
    return LinearSegmentedColormap.from_list(name, colors + [colors[0]])


# Custom cyclic gradients. Stops tuned on the deep-zoom Seahorse view.
_CUSTOM: dict[str, LinearSegmentedColormap] = {
    "dusk": _cyclic("dusk", ["#0b2545", "#13aa9b", "#fdf6e3", "#e8a33d", "#5c2a4d"]),
    "ultrafractal": _cyclic("ultrafractal", ["#00072e", "#1e7bd6", "#edffff", "#ffaa00", "#3a1d00"]),
    "ember": _cyclic("ember", ["#0a0000", "#a3231a", "#ff7a18", "#ffe6a0", "#3b0a00"]),
}

# Built-in maps that are themselves cyclic and fit this data.
_BLESSED_BUILTINS = ("twilight", "twilight_shifted", "hsv")

DEFAULT_PALETTE = "dusk"
DEFAULT_FREQ = 0.10  # colour cycles per √iteration; higher = denser banding.


def available() -> list[str]:
    """Names accepted by `get_cmap` (custom first, then blessed built-ins)."""
    return list(_CUSTOM) + list(_BLESSED_BUILTINS)


def get_cmap(name: str) -> Colormap:
    """Resolve a palette name to a matplotlib Colormap (custom or built-in)."""
    if name in _CUSTOM:
        return _CUSTOM[name]
    return matplotlib.colormaps[name]


def colorize(
    iterations: np.ndarray,
    cmap: str = DEFAULT_PALETTE,
    *,
    freq: float = DEFAULT_FREQ,
    set_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> np.ndarray:
    """Map a 2D iteration array to a uint8 RGB image (H, W, 3).

    The set — bounded pixels carrying the array's maximum value — is painted
    `set_color`. Escaped pixels are coloured by cycling `cmap` as a function
    of `(sqrt(count) * freq) mod 1`, concentrating colour variation on the
    set boundary. The mapping is per-pixel and stat-free, hence temporally
    stable across animation frames.
    """
    arr = iterations.astype(np.float64)
    palette = get_cmap(cmap)

    top = arr.max()
    set_mask = arr >= top if top > 0 else np.zeros_like(arr, dtype=bool)

    index = (np.sqrt(np.clip(arr, 0, None)) * freq) % 1.0
    rgb = palette(index)[..., :3].copy()
    rgb[set_mask] = set_color
    return (rgb * 255).astype(np.uint8)
