# Known sharp edges

Known sharp edges. Update this file when a new one is found — the gotcha journal is one of the most valuable artefacts in the repo.

1. **Headless GL on Linux is a known nuisance.** ModernGL needs an OpenGL context; in a container with no display server, you need EGL (`pyopengl-accelerate` + Mesa EGL drivers in the image) or osmesa. Budget extra time for the first successful render inside a container.
2. **Dagster K8s executor has sharp edges** around RBAC and service-account setup. Validate the executor against a local `kind` cluster *before* pointing it at real GKE — diagnosing pod-permission errors against the cloud is slow.
3. **Zarr v3 vs v2.** xarray supports both but the on-disk layout differs and they are not interchangeable. Pin to one in `requirements.txt` and stick with it across all stages, or stage-N's Zarrs won't open in stage-M.
4. **Zarr chunk shape is permanent.** Once a store is written with a chunk shape, you can't change it without rewriting. Decide `(1, H, W)` (frame-aligned, parallel-writable per frame) early in `common/store.py` and don't drift.
5. **xarray + dask + zarr write semantics.** `ds.to_zarr(..., region=...)` writes to a sub-region of an existing store, which is what enables parallel partition writes. Materialising into a freshly created Zarr from multiple workers without `region=` can corrupt chunks. Read the xarray "region writes" docs once before stage 04.
6. **Workload Identity Federation setup has a specific dance** — GitHub OIDC issuer → GCP workload identity pool → attribute mapping → service account impersonation binding. The official Google blog post is the cleanest walkthrough. Don't wing it from Stack Overflow answers.
7. **GKE Standard, not Autopilot.** Autopilot abstracts away the things you're trying to learn.
8. **`kubectl apply` from GitHub Actions** needs the `gke-gcloud-auth-plugin` installed in the runner. Easy to miss; error message is cryptic.
9. **Artifact Registry, not Container Registry.** GCR is in sunset.
10. **Skip a Cloud Load Balancer Ingress for the weekend.** Use `kubectl port-forward` for the demo — Cloud LBs cost ~$18/mo if you forget to delete one. Stage 09's viewer can deploy to Cloud Run instead — scales to zero, has its own URL, no LB needed.
11. **icechunk session lifecycle.** Open a session, write, *commit*. Forgetting to commit (or committing from the wrong process) is the rookie failure mode. Each Dagster job run = one commit; coordinate the commit through the orchestrator, not the partition workers.
12. **Stage 05 uses float32 throughout.** PyTorch's MPS backend has historically lagged on `complex128`, and CPU/GPU equivalence is easier if everything is float32 anyway. Implement stage 05 with separate float32 real and imag tensors, not complex dtypes. Useful zoom caps at ~10⁶ at float32; deep zoom lives in stage 06. Set `PYTORCH_ENABLE_MPS_FALLBACK=1` for any unimplemented ops.
13. **Docker Desktop on Mac doesn't pass through the Apple GPU.** Containers built for GKE's CUDA pool run on your Mac with software rendering (very slow). Use the container locally for "does it compile and start" checks; perf-test only on a real GPU node.
