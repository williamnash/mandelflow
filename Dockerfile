# syntax=docker/dockerfile:1.7
#
# mandelflow base image. One image, three deployments:
#   - Stage 06's headless GLSL renderer in Linux environments (EGL via Mesa)
#   - Stage 08's compute pods on GKE (CUDA + EGL + full stack)
#   - Stage 09's viewer (tile server) on Cloud Run
#
# Local development on macOS does NOT use this image; see docs/LOCAL_DEV.md.

ARG CUDA_VERSION=12.5.1
ARG UBUNTU_VERSION=24.04
ARG PYTHON_VERSION=3.12

# ─── Builder: resolve project deps with uv ────────────────────────────────
FROM ghcr.io/astral-sh/uv:0.11-python${PYTHON_VERSION}-trixie AS builder

WORKDIR /app

# Layer-cache deps separately from project source
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra gpu --extra cloud --no-install-project --no-dev

# Install the project itself (fast — source only, deps already resolved)
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra gpu --extra cloud --no-dev

# ─── Runtime: CUDA + Mesa EGL + the resolved venv ─────────────────────────
FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION}

ARG PYTHON_VERSION=3.12

# Ubuntu 24.04 ships python3.12 by default — no deadsnakes PPA needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-venv \
        libegl1 \
        libgl1 \
        libgles2 \
        mesa-utils \
        ffmpeg \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 # uv's venv symlinks `python` → /usr/local/bin/python3 (the builder image's
 # Python path); the apt install above puts Python at /usr/bin/python3.12.
 # Add the compatibility symlink so the copied venv resolves cleanly. See
 # docs/CLOUD_SETUP.md gotcha #6.
 && ln -sf /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python3

WORKDIR /app

# Pull the venv + source from the builder
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# No default CMD — every deployment sets one:
#   Stage 08 compute pod: ["dagster", "job", "execute", ...]
#   Stage 09 viewer:      ["uvicorn", "stages.s09_viewer_fastapi.main:app", "--host", "0.0.0.0", "--port", "8080"]
ENTRYPOINT []
CMD ["python", "-c", "raise SystemExit('Override CMD in the K8s pod spec or Cloud Run service config')"]
