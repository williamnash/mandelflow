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


def test_s09_gs_output_without_credentials_fails_with_one_clear_line(no_gcp_credentials):
    with pytest.raises(SystemExit, match="Stage 09 requires GCP credentials"):
        s09_dispatch(["--output", "gs://nope/run.icechunk", "--target", "gke"])
