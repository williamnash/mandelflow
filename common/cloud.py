"""Scheme-dispatching credential preflight.

Cloud stages call this once with their output path; whichever provider
the scheme implies gets checked, and local paths are a no-op. Keeps the
one-clear-line contract (DESIGN.md §5) provider-agnostic — a stage never
needs to know which clouds exist.
"""

from __future__ import annotations

from common.aws import require_aws_credentials
from common.gcp import require_gcp_credentials


def require_cloud_credentials(stage: str, output: str) -> None:
    require_gcp_credentials(stage, output)
    require_aws_credentials(stage, output)
