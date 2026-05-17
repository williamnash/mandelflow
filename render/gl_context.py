"""Offscreen GL context provider.

Picks the right backend per platform so stage 06's shader and stage 09's
/render route share the same renderer code:

- macOS:  hidden pygame window (Apple's OpenGL 4.1; no EGL on Darwin).
- Linux:  moderngl standalone EGL context (no display server needed,
          works in containers).
"""

from __future__ import annotations

import sys


def has_gl() -> bool:
    """Non-raising preflight: can we make a GL 4.1 offscreen context?

    Imports moderngl / pygame lazily and actually creates+releases a
    1x1 context to verify drivers work, not just that the libraries
    are installed. Used by test parametrize lists to skip s06 when
    GL isn't reachable.
    """
    try:
        ctx = make_offscreen_context(1, 1)
        ctx.release()
        return True
    except Exception:
        return False


def make_offscreen_context(width: int = 1, height: int = 1):
    """Return a moderngl Context suitable for offscreen rendering.

    The shader targets `#version 410 core`; both backends honour that.
    Caller is responsible for releasing the context.
    """
    import moderngl

    if sys.platform == "darwin":
        # Note: pygame.HIDDEN may briefly flash a window on screen on the first
        # call. Acceptable for batch rendering (stage 06, bench). For long-running
        # processes that render repeatedly, initialise this context once at
        # process start and reuse — do not call per request.
        import pygame

        pygame.display.init()
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 4)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
        pygame.display.gl_set_attribute(
            pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE
        )
        pygame.display.set_mode(
            (width, height), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN
        )
        return moderngl.create_context()

    return moderngl.create_standalone_context(require=410)
