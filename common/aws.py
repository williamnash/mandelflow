"""AWS credential preflight for cloud stages — the s3:// twin of
common/gcp.py. On AWS hosts (instance roles, IRSA on EKS) the default
chain resolves without local setup, so the check is a no-op there.

Two ways naive checks fall short, both learned in review:
botocore *raises* for several misconfigurations (stale AWS_PROFILE →
ProfileNotFound, expired SSO tokens) rather than returning None, and
credentials-without-region passes a creds-only check but then dies in
icechunk's Rust S3 client, which resolves region from the environment.
"""

from __future__ import annotations

import os


def require_aws_credentials(stage: str, output: str) -> None:
    """Exit with one clear line unless the standard AWS chain yields
    credentials *and* a region is resolvable for `output`'s s3:// path."""
    if not output.startswith("s3://"):
        return
    import botocore.session

    try:
        session = botocore.session.get_session()
        credentials = session.get_credentials()
        region = session.get_config_variable("region")
    except Exception as exc:
        raise SystemExit(
            f"{stage} requires working AWS credentials for s3:// output "
            f"({type(exc).__name__}: {exc}). Fix AWS_PROFILE / `aws sso login`, "
            "or pass a local --output path."
        )
    if credentials is None:
        raise SystemExit(
            f"{stage} requires AWS credentials for s3:// output. "
            "Set AWS_PROFILE / AWS_ACCESS_KEY_ID (or run on a host with an "
            "instance role), or pass a local --output path."
        )
    if not region and not os.environ.get("AWS_REGION") and not os.environ.get("AWS_DEFAULT_REGION"):
        raise SystemExit(
            f"{stage} requires AWS_REGION (or AWS_DEFAULT_REGION) for s3:// "
            "output — icechunk's S3 client resolves region from the environment."
        )
