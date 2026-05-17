"""Stage 08: single cloud-VM multi-frame zoom — SCAFFOLD.

This is s07's exact multi-frame loop, designed to run inside one
GCE VM with a T4 GPU. The only deployment-aware difference is that
`--output` accepts a `gs://bucket/path.zarr` URL — xarray + zarr
speaks GCS through gcsfs (already in pyproject deps), so the same
`store.write_frame(region=...)` API targets either filesystem
without code changes.

Not runnable yet — wired up against placeholder URLs. When the
infrastructure in `terraform/` is provisioned and the image is in
Artifact Registry, this should work end-to-end with:

    python -m stages.s08_zoom_cloud.run \\
        --n-frames 120 \\
        --resolution 1080 \\
        --max-iter 512 \\
        --output gs://<bucket>/runs/dev.zarr

# TODO(s08): finalise the gs:// path in store.create_iterations_dataset
# / store.write_frame. xarray.to_zarr already accepts gcs URLs; verify
# the region-write path works against GCS the same way it does against
# local FS, and that gcsfs auth picks up the VM's attached SA.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 08: single-VM cloud zoom")
    parser.add_argument("--n-frames", type=int, default=120)
    parser.add_argument("--resolution", type=int, default=720)
    parser.add_argument("--max-iter", type=int, default=512)
    parser.add_argument(
        "--output",
        type=str,
        default="gs://REPLACE_ME-mandelflow-zarr/runs/dev.zarr",
        help="Output Zarr path. `gs://bucket/path.zarr` for cloud; "
             "local path for plumbing tests.",
    )
    args = parser.parse_args(argv)

    print(
        "stage 08 zoom_cloud (SCAFFOLD): "
        f"n_frames={args.n_frames} resolution={args.resolution} "
        f"max_iter={args.max_iter} output={args.output}",
        file=sys.stderr,
    )
    print(
        "Not implemented yet. See stages/s08_zoom_cloud/README.md for the "
        "deployment walkthrough.",
        file=sys.stderr,
    )
    sys.exit(2)

    # TODO(s08): when implemented, this is essentially s07's run.py with
    # `args.output` allowed to be a gs:// URL:
    #   - has_gl() preflight (the VM must have NVIDIA drivers + EGL)
    #   - canonical_schedule(args.n_frames)
    #   - make_offscreen_context(1, 1) once
    #   - loop: compute_frame(... , ctx=shared_ctx) → write_frame(...)
    #   - tear down context
    # write_frame already speaks gs:// via xarray + gcsfs; no API change
    # needed in common/store.py.


if __name__ == "__main__":
    main()
