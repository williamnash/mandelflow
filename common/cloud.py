"""Scheme-dispatching credential preflight.

Cloud stages call this once with their output path. The scheme picks the
provider check; local paths are a no-op; an *unrecognized* remote scheme
(az://, or a gcs:// typo of gs://) is rejected here with one clear line
rather than surfacing later as a deep fsspec "Protocol not known" trace.
Keeps the contract (DESIGN.md §5) provider-agnostic — a stage never
needs to know which clouds exist.
"""

from __future__ import annotations

from common.aws import require_aws_credentials
from common.gcp import require_gcp_credentials

_CHECKS = {
    "gs://": require_gcp_credentials,
    "s3://": require_aws_credentials,
}


def require_cloud_credentials(stage: str, output: str) -> None:
    if "://" not in output:
        return
    for scheme, check in _CHECKS.items():
        if output.startswith(scheme):
            check(stage, output)
            return
    supported = ", ".join(_CHECKS)
    raise SystemExit(
        f"{stage}: unsupported output scheme in {output!r}. "
        f"Supported: local paths, {supported}."
    )
