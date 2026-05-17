"""Stage 09: GKE multi-Pod fan-out — SCAFFOLD.

s09 takes s08's "ship s07 to one cloud machine" and scales it across
several machines via per-Pod frame ranges. The kernel inside each Pod
is unchanged (s06's GLSL shader); what changes is that N Pods, each
holding a different frame range, write concurrently into the same
GCS-backed Zarr.

Two execution modes share this file:

  --mode pod (per-Pod entrypoint, run inside each container)
    Compute frames `[frame_start, frame_end)` against a shared GL
    context and write each chunk to the target Zarr. This is the
    inner work — essentially s07's loop bounded to a range.

  --mode dispatch (control-host driver)
    Compute the frame-range partitioning (n_frames / n_pods, with
    remainder distributed), build one K8s Job manifest per Pod, submit
    them via the Kubernetes Python client, poll for completion. No
    compute on the dispatch host.

Path A (direct K8s submission) is what this file sketches. Path B
(Dagster k8s_job_executor) is the same logic going through Dagster's
asset graph; it lives in orchestration/definitions.py once that
module exists.

# TODO(s09): implement.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 09: GKE fan-out zoom")
    parser.add_argument(
        "--mode",
        choices=["pod", "dispatch"],
        default="dispatch",
        help="pod: this Pod computes a frame range. "
             "dispatch: submit N Pods covering all frames.",
    )
    parser.add_argument("--frame-start", type=int, default=0,
                        help="(pod mode) Inclusive start of this Pod's frame range.")
    parser.add_argument("--frame-end", type=int, default=None,
                        help="(pod mode) Exclusive end of this Pod's frame range.")
    parser.add_argument("--n-frames", type=int, default=120)
    parser.add_argument("--n-pods", type=int, default=4,
                        help="(dispatch mode) Number of Pods to fan across. "
                             "Frame range per Pod = ceil(n_frames / n_pods).")
    parser.add_argument("--resolution", type=int, default=720)
    parser.add_argument("--max-iter", type=int, default=512)
    parser.add_argument(
        "--output",
        type=str,
        default="gs://REPLACE_ME-mandelflow-zarr/runs/dev.zarr",
    )
    parser.add_argument(
        "--image",
        type=str,
        default="REPLACE_ME-docker.pkg.dev/REPLACE_ME/mandelflow/compute:dev",
        help="(dispatch mode) Container image to launch Pods with.",
    )
    args = parser.parse_args(argv)

    print(
        f"stage 09 zoom_fanout (SCAFFOLD): mode={args.mode} "
        f"n_frames={args.n_frames} n_pods={args.n_pods} "
        f"resolution={args.resolution} max_iter={args.max_iter}",
        file=sys.stderr,
    )
    print(
        "Not implemented yet. See stages/s09_zoom_fanout/README.md for "
        "the deployment walkthrough.",
        file=sys.stderr,
    )
    sys.exit(2)

    # TODO(s09): mode == "pod":
    #   - has_gl() preflight (the Pod must have NVIDIA + EGL drivers)
    #   - canonical_schedule(args.n_frames) → full schedule arrays
    #   - slice to [args.frame_start, args.frame_end)
    #   - make_offscreen_context(1, 1) once
    #   - for k in range(args.frame_start, args.frame_end):
    #       iters = compute_frame(cr[k], ci[k], w[k], ..., ctx=shared)
    #       write_frame(args.output, k, iters, ...)        # gs:// path
    #   - tear down context

    # TODO(s09): mode == "dispatch":
    #   - import kubernetes
    #   - load_kube_config() (laptop) or load_incluster_config() (in-cluster)
    #   - compute frame ranges:
    #       chunk = math.ceil(n_frames / n_pods)
    #       ranges = [(i*chunk, min((i+1)*chunk, n_frames)) for i in range(n_pods)]
    #   - for each range, render a Job manifest from k8s/compute-pod.yaml
    #     with --frame-start / --frame-end / --output substituted
    #   - BatchV1Api().create_namespaced_job(...) for each
    #   - poll until all .status.succeeded == 1 or any .status.failed > 0
    #   - on completion, the multi-frame Zarr at args.output is complete


if __name__ == "__main__":
    main()
