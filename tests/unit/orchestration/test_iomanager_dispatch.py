"""IOManager storage dispatch must match common.store's backend list.

Review finding on the s3:// PR: the stage-level paths gained s3 support
but IcechunkFrameIOManager._open_repo still fell through to
local_filesystem_storage for s3:// — every pod would 'succeed' writing
to an ephemeral local `s3:/…` directory and the data would evaporate
with the pod. Dispatch now goes through common.store.icechunk_storage;
this pins it.
"""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture()
def fake_icechunk(monkeypatch):
    calls = {}

    def _record(key):
        def factory(**kw):
            calls[key] = kw
            return f"{key.upper()}-STORAGE"

        return factory

    fake = types.SimpleNamespace(
        gcs_storage=_record("gcs"),
        s3_storage=_record("s3"),
        local_filesystem_storage=lambda p: "LOCAL-STORAGE",
        Repository=types.SimpleNamespace(
            open=lambda st: calls.setdefault("open", st),
            open_or_create=lambda st: calls.setdefault("open_or_create", st),
        ),
    )
    monkeypatch.setitem(sys.modules, "icechunk", fake)
    return calls


def test_icechunk_iomanager_dispatches_s3(fake_icechunk):
    from orchestration.definitions import IcechunkFrameIOManager

    mgr = IcechunkFrameIOManager(
        path="s3://my-bucket/runs/r.icechunk", n_frames=4, resolution=8
    )
    mgr._open_repo()
    assert fake_icechunk["s3"]["bucket"] == "my-bucket"
    assert fake_icechunk["s3"]["prefix"] == "runs/r.icechunk"
    assert fake_icechunk["open_or_create"] == "S3-STORAGE"


def test_icechunk_iomanager_gs_unchanged(fake_icechunk):
    from orchestration.definitions import IcechunkFrameIOManager

    mgr = IcechunkFrameIOManager(
        path="gs://my-bucket/runs/r.icechunk", n_frames=4, resolution=8
    )
    mgr._open_repo()
    assert fake_icechunk["gcs"] == {"bucket": "my-bucket", "prefix": "runs/r.icechunk"}
    assert fake_icechunk["open_or_create"] == "GCS-STORAGE"
