"""Store backend dispatch: the code must match DESIGN.md §3's claim that
the data product opens from local FS, gs://, and s3://.

Cloud SDKs are faked via sys.modules / monkeypatch — these tests pin the
dispatch logic (which backend gets which path pieces), not the network.
"""

from __future__ import annotations

import sys
import types

import pytest
import xarray as xr

from common.store import list_stores, open_iterations_dataset


class _FakeRepo:
    def __init__(self, marker):
        self.marker = marker

    def readonly_session(self, branch):
        assert branch == "main"
        return types.SimpleNamespace(store=("SESSION-STORE", self.marker))


@pytest.fixture()
def capture_open_zarr(monkeypatch):
    opened = {}
    monkeypatch.setattr(xr, "open_zarr", lambda store: opened.setdefault("store", store))
    return opened


def _fake_icechunk(monkeypatch, calls):
    def _record(key):
        def factory(**kw):
            calls[key] = kw
            return f"{key.upper()}-STORAGE"

        return factory

    fake = types.SimpleNamespace(
        gcs_storage=_record("gcs"),
        s3_storage=_record("s3"),
        local_filesystem_storage=lambda p: "LOCAL-STORAGE",
        Repository=types.SimpleNamespace(open=lambda st: _FakeRepo(st)),
    )
    monkeypatch.setitem(sys.modules, "icechunk", fake)


def test_s3_icechunk_dispatch(monkeypatch, capture_open_zarr):
    calls = {}
    _fake_icechunk(monkeypatch, calls)
    open_iterations_dataset("s3://my-bucket/runs/deep.icechunk")
    assert calls["s3"]["bucket"] == "my-bucket"
    assert calls["s3"]["prefix"] == "runs/deep.icechunk"
    # Credentials must come from the standard AWS chain, not hardcoded args.
    assert calls["s3"].get("from_env") is True
    assert capture_open_zarr["store"][1] == "S3-STORAGE"


def test_gs_icechunk_dispatch_unchanged(monkeypatch, capture_open_zarr):
    calls = {}
    _fake_icechunk(monkeypatch, calls)
    open_iterations_dataset("gs://my-bucket/runs/deep.icechunk")
    assert calls["gcs"] == {"bucket": "my-bucket", "prefix": "runs/deep.icechunk"}


def test_s3_raw_zarr_goes_straight_to_xarray(capture_open_zarr):
    open_iterations_dataset("s3://my-bucket/runs/flat.zarr")
    assert capture_open_zarr["store"] == "s3://my-bucket/runs/flat.zarr"


def test_list_stores_local(tmp_path):
    (tmp_path / "a.zarr").mkdir()
    (tmp_path / "b.icechunk").mkdir()
    (tmp_path / "noise.txt").write_text("")
    (tmp_path / "c.mp4").write_text("")
    assert list_stores(str(tmp_path)) == ["a.zarr", "b.icechunk"]


@pytest.mark.parametrize(
    "scheme,module,fs_class",
    [("gs", "gcsfs", "GCSFileSystem"), ("s3", "s3fs", "S3FileSystem")],
)
def test_list_stores_remote(monkeypatch, scheme, module, fs_class):
    entries = ["bkt/runs/a.zarr", "bkt/runs/b.icechunk/", "bkt/runs/junk.txt"]
    fake_fs = types.SimpleNamespace(ls=lambda p: entries)
    monkeypatch.setitem(
        sys.modules, module, types.SimpleNamespace(**{fs_class: lambda: fake_fs})
    )
    assert list_stores(f"{scheme}://bkt/runs") == ["a.zarr", "b.icechunk"]


def test_list_stores_missing_local_root_is_empty(tmp_path):
    assert list_stores(str(tmp_path / "nope")) == []
