"""Stage 08: cloud-distributed multi-frame zoom — SCAFFOLD.

This module is intentionally not runnable yet. It sketches the two
execution shapes s08 will take so that when the supporting infrastructure
(Terraform-provisioned cluster, Docker image in Artifact Registry, GCS
bucket, `orchestration/definitions.py`) lands, the wiring is obvious.

The same per-frame `compute_frame` from `stages.s08_zoom_cloud.compute`
(which re-exports s06's GLSL shader kernel) runs *inside* each Pod. What
this file is about is the dispatcher.

Two execution modes share the file:

  Mode A — `python -m stages.s08_zoom_cloud.run --mode local`
    Inside one Pod, compute a single frame and write its chunk to a
    GCS-backed Zarr. This is the per-Pod entrypoint; the Pod's command
    in `k8s/compute-pod.yaml` invokes it. Plumbing-testable on a `kind`
    cluster (without GPU) by writing to a local Zarr instead.

  Mode B — `python -m stages.s08_zoom_cloud.run --mode dispatch`
    From a control host (laptop or CI), submit N K8s Jobs — one per
    frame — using the Kubernetes Python client, then poll for
    completion. Equivalent to what Dagster's k8s_job_executor will do
    later when `orchestration/definitions.py` exists; this mode is the
    standalone path that doesn't require Dagster.

The Dagster path (Path B in the README) is preferred long-term: same
asset graph as s07, just with `k8s_job_executor` swapped in for the
default multiprocess executor. That path lives in `orchestration/`
once that module exists.

# TODO(s08): implement.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 08: cloud-distributed zoom")
    parser.add_argument(
        "--mode",
        choices=["local", "dispatch"],
        default="local",
        help="local: this Pod computes one frame. dispatch: submit Jobs for all frames.",
    )
    parser.add_argument("--frame-index", type=int, default=0,
                        help="(local mode) Which frame this Pod is computing.")
    parser.add_argument("--n-frames", type=int, default=120)
    parser.add_argument("--resolution", type=int, default=720)
    parser.add_argument("--max-iter", type=int, default=512)
    parser.add_argument("--output", type=str, required=False,
                        help="gs://<bucket>/<path>/run.zarr in cloud mode; "
                             "local path in plumbing-test mode.")
    args = parser.parse_args(argv)

    print(
        "stage 08 zoom_cloud (SCAFFOLD): "
        f"mode={args.mode} frame={args.frame_index} n_frames={args.n_frames} "
        f"resolution={args.resolution} max_iter={args.max_iter}",
        file=sys.stderr,
    )
    print(
        "Not implemented yet. See stages/s08_zoom_cloud/README.md for the "
        "deployment walkthrough and the remaining work.",
        file=sys.stderr,
    )
    sys.exit(2)

    # TODO(s08): mode == "local":
    #   - import stages.s08_zoom_cloud.compute.compute_frame
    #   - import render.gl_context.make_offscreen_context (EGL path on Linux)
    #   - get (center_re, center_im, width) for `args.frame_index` from
    #     common.schedule.canonical_schedule(args.n_frames)
    #   - run compute_frame with shared ctx
    #   - write_frame() into the GCS-backed Zarr at args.output
    #     (needs the GCSIcechunkIOManager or raw Zarr region writes with
    #     a gcsfs-backed FSStore — see DESIGN.md §11)

    # TODO(s08): mode == "dispatch":
    #   - from kubernetes import client, config
    #   - config.load_kube_config() or load_incluster_config()
    #   - build a Job manifest from k8s/compute-pod.yaml as a template;
    #     parameterise frame-index, image tag, output URL
    #   - BatchV1Api().create_namespaced_job(...) for k in 0..n_frames-1
    #   - poll status until all Succeeded or any Failed
    #   - no compute happens on the control host; this just orchestrates


if __name__ == "__main__":
    main()
