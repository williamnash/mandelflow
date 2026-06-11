"""AWS credential preflight for cloud stages — the s3:// twin of
common/gcp.py. On AWS hosts (instance roles, IRSA on EKS) the default
botocore chain resolves without local setup, so the check is a no-op
there.
"""

from __future__ import annotations


def require_aws_credentials(stage: str, output: str) -> None:
    """Exit with one clear line if `output` is an s3:// path and the
    standard AWS credential chain resolves nothing."""
    if not output.startswith("s3://"):
        return
    import botocore.session

    if botocore.session.get_session().get_credentials() is None:
        raise SystemExit(
            f"{stage} requires AWS credentials for s3:// output. "
            "Set AWS_PROFILE / AWS_ACCESS_KEY_ID (or run on a host with an "
            "instance role), or pass a local --output path."
        )
