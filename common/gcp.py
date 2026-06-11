"""GCP credential preflight for cloud stages.

The reproducibility contract (DESIGN.md §5) says cloud stages fail with
one clear line naming the missing prerequisite — never a gcsfs or
icechunk stack trace from deep inside the first store write. On cloud
hosts (GCE metadata server, Workload Identity) `google.auth.default()`
resolves without any local setup, so the check is a no-op there.
"""

from __future__ import annotations


def require_gcp_credentials(stage: str, output: str) -> None:
    """Exit with one clear line if `output` is a gs:// path and no
    Application Default Credentials are resolvable."""
    if not output.startswith("gs://"):
        return
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError

    try:
        google.auth.default()
    except DefaultCredentialsError:
        raise SystemExit(
            f"{stage} requires GCP credentials for gs:// output. "
            "Run `gcloud auth application-default login`, or pass a local --output path."
        )
