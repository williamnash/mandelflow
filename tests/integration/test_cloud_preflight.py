"""Cloud stages' reproducibility-contract failure mode.

Stages needing GCP credentials must fail with one clear line naming the
missing prerequisite — never a gcsfs/icechunk stack trace from deep
inside the first store write (DESIGN.md §5).
"""

from __future__ import annotations

import pytest
from google.auth.exceptions import DefaultCredentialsError

from stages.s08_zoom_cloud_cpu.run import main as s08_main
from stages.s09_zoom_fanout_cpu.run import run_dispatch as s09_dispatch
from stages.s09_zoom_fanout_cpu.run import run_task as s09_task


@pytest.fixture()
def no_gcp_credentials(monkeypatch):
    def no_creds(*args, **kwargs):
        raise DefaultCredentialsError("no ADC found")

    monkeypatch.setattr("google.auth.default", no_creds)


def test_s08_gs_output_without_credentials_fails_with_one_clear_line(no_gcp_credentials):
    with pytest.raises(SystemExit, match="Stage 08 requires GCP credentials"):
        s08_main(["--output", "gs://nope/run.zarr", "--n-frames", "1", "--resolution", "8"])


def test_s08_local_output_needs_no_credentials(tmp_path, no_gcp_credentials):
    out = tmp_path / "local.zarr"
    s08_main(["--output", str(out), "--n-frames", "1", "--resolution", "8",
              "--max-iter", "16", "--n-workers", "1", "--n-tiles", "1"])
    assert out.exists()


def test_s09_dispatch_without_credentials_fails_with_one_clear_line(
    no_gcp_credentials, monkeypatch
):
    # run_dispatch writes MANDELFLOW_OUTPUT into os.environ; setenv first so
    # monkeypatch restores it and the gs://nope path can't leak to later tests.
    monkeypatch.setenv("MANDELFLOW_OUTPUT", "gs://nope/run.icechunk")
    with pytest.raises(SystemExit, match="Stage 09 requires GCP credentials"):
        s09_dispatch(["--output", "gs://nope/run.icechunk", "--target", "gke"])


def test_s09_task_mode_without_credentials_fails_with_one_clear_line(
    no_gcp_credentials, monkeypatch
):
    # Pod-side path (K8s / Cloud Run task) must fail the same way as the
    # dispatcher when reproduced locally without ADC.
    monkeypatch.setenv("MANDELFLOW_OUTPUT", "gs://nope/run.icechunk")
    with pytest.raises(SystemExit, match="Stage 09 requires GCP credentials"):
        s09_task(0, 1)


@pytest.fixture()
def no_aws_credentials(monkeypatch):
    import botocore.session

    class _NoCreds(botocore.session.Session):
        def get_credentials(self):
            return None

    monkeypatch.setattr(botocore.session, "get_session", lambda: _NoCreds())


def test_s3_output_without_credentials_fails_with_one_clear_line(no_aws_credentials):
    from common.cloud import require_cloud_credentials

    with pytest.raises(SystemExit, match="Stage 09 requires AWS credentials"):
        require_cloud_credentials("Stage 09", "s3://nope/run.icechunk")


def test_local_output_needs_no_cloud_credentials(no_aws_credentials, no_gcp_credentials):
    from common.cloud import require_cloud_credentials

    require_cloud_credentials("Stage 08", "out/local.zarr")  # must not raise


def test_s09_task_mode_s3_without_credentials(no_aws_credentials, monkeypatch):
    monkeypatch.setenv("MANDELFLOW_OUTPUT", "s3://nope/run.icechunk")
    with pytest.raises(SystemExit, match="Stage 09 requires AWS credentials"):
        s09_task(0, 1)
