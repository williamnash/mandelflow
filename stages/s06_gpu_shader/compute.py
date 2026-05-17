"""Stage 06: Mandelbrot via GLSL fragment shader.

The entire iteration loop runs inside a single fragment shader — one
shader invocation per pixel, executed by the GPU's rasteriser. Unlike
s05 (PyTorch), there is *no* Python loop over iterations: the GPU
schedules `max_iter` arithmetic steps per fragment internally, with
zero per-step CPU dispatch.

Output is an `R32F` texture (single-channel 32-bit float). The
fragment writes the escape count as a float; CPU readback casts to
uint16 to match the canonical schema. R32F is overkill in precision
but is the simplest portable choice — uint integer FBO attachments
have format-binding gotchas on macOS.

The shader uses linspace-equivalent sampling (`(j / (N-1))` rather
than the default pixel-centre `((j + 0.5) / N)`) so each pixel maps
to *exactly* the same complex-plane point as s00's `np.linspace`.
That keeps boundary divergence to float32 precision alone, not a
half-pixel grid offset.
"""

from __future__ import annotations

import sys

import numpy as np

from common.store import ITERATIONS_DTYPE
from render.gl_context import make_offscreen_context

_VERTEX_SHADER = """
#version 410 core
in vec2 in_position;
void main() {
    gl_Position = vec4(in_position, 0.0, 1.0);
}
"""

_FRAGMENT_SHADER = """
#version 410 core
out float f_escape;

uniform vec2  u_center;
uniform float u_width;
uniform vec2  u_resolution;
uniform int   u_max_iter;

void main() {
    float j = floor(gl_FragCoord.x);
    float i = floor(gl_FragCoord.y);

    float u = (u_resolution.x > 1.0) ? j / (u_resolution.x - 1.0) : 0.0;
    float v = (u_resolution.y > 1.0) ? i / (u_resolution.y - 1.0) : 0.0;

    float half_w = 0.5 * u_width;
    float cr = (u_center.x - half_w) + u * u_width;
    float ci = (u_center.y - half_w) + v * u_width;

    // Cardioid + period-2 early exits
    float cr_shift = cr - 0.25;
    float q = cr_shift * cr_shift + ci * ci;
    if (q * (q + cr_shift) < 0.25 * ci * ci) {
        f_escape = float(u_max_iter);
        return;
    }
    float cr_p1 = cr + 1.0;
    if (cr_p1 * cr_p1 + ci * ci < 0.0625) {
        f_escape = float(u_max_iter);
        return;
    }

    float zr  = 0.0;
    float zi  = 0.0;
    float zr2 = 0.0;
    float zi2 = 0.0;
    for (int k = 0; k < u_max_iter; k++) {
        zi  = 2.0 * zr * zi + ci;
        zr  = zr2 - zi2 + cr;
        zr2 = zr * zr;
        zi2 = zi * zi;
        if (zr2 + zi2 > 4.0) {
            f_escape = float(k);
            return;
        }
    }
    f_escape = float(u_max_iter);
}
"""


def compute_frame(
    center_re: float,
    center_im: float,
    width: float,
    resolution: int,
    max_iter: int,
) -> np.ndarray:
    import moderngl

    ctx = make_offscreen_context(1, 1)
    try:
        program = ctx.program(
            vertex_shader=_VERTEX_SHADER,
            fragment_shader=_FRAGMENT_SHADER,
        )
        program["u_center"] = (center_re, center_im)
        program["u_width"] = width
        program["u_resolution"] = (resolution, resolution)
        program["u_max_iter"] = max_iter

        quad = np.array([-1.0, -1.0,  1.0, -1.0,
                         -1.0,  1.0,  1.0,  1.0], dtype="f4")
        vbo = ctx.buffer(quad.tobytes())
        vao = ctx.vertex_array(program, [(vbo, "2f", "in_position")])

        tex = ctx.texture((resolution, resolution), 1, dtype="f4")
        fbo = ctx.framebuffer(color_attachments=[tex])

        fbo.use()
        ctx.viewport = (0, 0, resolution, resolution)
        vao.render(moderngl.TRIANGLE_STRIP)

        data = fbo.read(components=1, dtype="f4")
        arr = np.frombuffer(data, dtype=np.float32).reshape(resolution, resolution)

        fbo.release()
        tex.release()
        vao.release()
        vbo.release()
        program.release()
    finally:
        ctx.release()
        if sys.platform == "darwin":
            import pygame
            pygame.display.quit()

    return arr.astype(ITERATIONS_DTYPE)
