import zipfile
from datetime import datetime

import numpy as np
import pytest

import cwa_extract as e
from test_cwa_probe import RangeHandler, server  # noqa: F401  (server 是 pytest fixture)


def test_parse_hours_since_with_fractional_seconds():
    assert e.parse_hours_since("hours since 1800-01-01 00:00:0.0") == datetime(1800, 1, 1)
    assert e.parse_hours_since("hours since 2023-07-01 06:30:15") == datetime(2023, 7, 1, 6, 30, 15)


@pytest.mark.parametrize("bad", ["days since 1800-01-01 00:00:00", "hours since yesterday", ""])
def test_parse_hours_since_rejects_other_units(bad):
    with pytest.raises(ValueError, match="時間單位"):
        e.parse_hours_since(bad)


def test_time_slice_is_inclusive_on_both_ends():
    hours = np.arange(0, 100)               # 自 base 起算的小時
    base = datetime(2023, 7, 1)
    assert e.time_slice(hours, base, datetime(2023, 7, 1, 10), datetime(2023, 7, 1, 12)) == slice(10, 13)


def test_time_slice_rejects_range_outside_file():
    with pytest.raises(ValueError, match="沒有資料"):
        e.time_slice(np.arange(10), datetime(2023, 7, 1), datetime(2024, 1, 1), datetime(2024, 1, 2))


def test_mask_missing_replaces_both_fill_values_only():
    a = e.mask_missing([-9999.0, -999.0, 0.0, -998.0, 0.5])
    assert np.isnan(a[0]) and np.isnan(a[1]) and np.isnan(a[2:3]).sum() == 0
    assert a[2] == 0.0 and a[3] == -998.0 and a[4] == 0.5 and a.dtype == np.float32


def build_cwa_like_zip(tmp_path, names=("UCURR", "VCURR")):
    h5py = pytest.importorskip("h5py")
    lats, lons = np.linspace(21.0, 24.0, 61), np.linspace(119.0, 122.0, 61)
    times = np.arange(48, dtype="int32") + 1959120          # hours since 1800-01-01 → 2023-07-01 起
    zp = tmp_path / "c.zip"
    expected = {}
    with zipfile.ZipFile(zp, "w", compression=zipfile.ZIP_STORED) as zf:
        for k, name in enumerate(names):
            nc = tmp_path / f"{name}.202307.nc"
            data = (np.arange(48 * 61 * 61, dtype="float32").reshape(48, 1, 61, 61) / 1000.0) + k
            data[:, :, 0, 0] = -9999.0
            with h5py.File(nc, "w") as f:
                f["lat"], f["lon"], f["time"] = lats, lons, times
                f["time"].attrs["units"] = "hours since 1800-01-01 00:00:0.0"
                f.create_dataset(name, data=data, chunks=(1, 1, 61, 61))
                f[name].attrs["units"] = "m/s"
            zf.write(nc, nc.name)
            expected[name] = data
    return zp, expected, lats, lons


def test_extract_variable_returns_window_and_masks_fill(server, tmp_path):
    pytest.importorskip("requests")
    zp, expected, lats, lons = build_cwa_like_zip(tmp_path)
    url = server(zp.read_bytes())
    times, la, lo, vals, nbytes, attrs = e.extract_variable(
        url, "UCURR", (21.0, 21.5, 119.0, 119.5), datetime(2023, 7, 1, 2), datetime(2023, 7, 1, 5), False, 8, step_batch=2)
    assert [str(t)[:13] for t in times] == ["2023-07-01T02", "2023-07-01T03", "2023-07-01T04", "2023-07-01T05"]
    assert la.min() >= 21.0 - 1e-9 and la.max() <= 21.5 + 1e-9 and lo.min() >= 119.0 - 1e-9 and lo.max() <= 119.5 + 1e-9
    assert vals.shape == (4, la.size, lo.size)
    ys = np.where((lats >= 21.0) & (lats <= 21.5))[0]
    xs = np.where((lons >= 119.0) & (lons <= 119.5))[0]
    want = expected["UCURR"][2:6, 0][:, ys][:, :, xs].copy()
    want[want == -9999.0] = np.nan
    assert np.allclose(vals, want, equal_nan=True)
    assert np.isnan(vals[:, 0, 0]).all()            # 填充值已換成 NaN
    assert attrs == {"units": "m/s", "source_member": "UCURR.202307.nc"}
    assert 0 < nbytes <= 2 * zp.stat().st_size      # 讀 zip 目錄與讀成員各算一次，所以可能略大於 zip


def test_main_writes_dataset_for_several_variables(server, tmp_path, monkeypatch, capsys):
    xr = pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")
    pytest.importorskip("requests")
    zp, expected, lats, lons = build_cwa_like_zip(tmp_path)
    url = server(zp.read_bytes())
    out = tmp_path / "out" / "f.nc"
    monkeypatch.setattr("sys.argv", ["cwa_extract.py", "--url", url, "--variables", "UCURR", "VCURR", "--bbox", "21", "21.5", "119", "119.5",
                                     "--start", "2023-07-01 00:00", "--end", "2023-07-01 03:00", "--block-kb", "8", "--out", str(out)])
    e.main()
    d = xr.open_dataset(out)
    assert set(d.data_vars) == {"UCURR", "VCURR"} and d.sizes["time"] == 4
    assert "UTC" in d.attrs["note"]
    assert float(d.VCURR.isel(time=0, lat=1, lon=1)) == pytest.approx(float(expected["VCURR"][0, 0, 1, 1]), rel=1e-5)


def test_build_dataset_rejects_inconsistent_coordinates():
    pytest.importorskip("xarray")
    t = np.array(["2023-07-01T00", "2023-07-01T01"], dtype="datetime64[ns]")
    a = (t, np.array([21.0, 21.025]), np.array([119.0, 119.025]), np.zeros((2, 2, 2), dtype="float32"), 0, {})
    b = (t, np.array([21.0, 21.05]), np.array([119.0, 119.025]), np.zeros((2, 2, 2), dtype="float32"), 0, {})
    with pytest.raises(ValueError, match="不一致"):
        e.build_dataset({"A": a, "B": b})
    d = (t, a[1], np.array([119.0, 119.05]), a[3], 0, {})
    with pytest.raises(ValueError, match="不一致"):
        e.build_dataset({"A": a, "B": d})
    assert set(e.build_dataset({"A": a, "B": a}).data_vars) == {"A", "B"}


def test_extract_variable_keeps_last_partial_batch(server, tmp_path):
    pytest.importorskip("requests")
    zp, expected, lats, lons = build_cwa_like_zip(tmp_path)
    url = server(zp.read_bytes())
    times, la, lo, vals, nbytes, attrs = e.extract_variable(
        url, "VCURR", (21.0, 21.5, 119.0, 119.5), datetime(2023, 7, 1, 2), datetime(2023, 7, 1, 6), False, 8, step_batch=2)
    assert len(times) == 5 and vals.shape[0] == 5      # 5 步、每批 2 步：最後一批只有 1 步
    assert np.allclose(vals[4, 1, 1], expected["VCURR"][6, 0, 1, 1])


def test_build_dataset_keeps_only_common_times():
    pytest.importorskip("xarray")
    t = np.array(["2023-07-01T00", "2023-07-01T01", "2023-07-01T02"], dtype="datetime64[ns]")
    la, lo = np.array([21.0, 21.025]), np.array([119.0, 119.025])
    a = (t, la, lo, np.arange(12, dtype="float32").reshape(3, 2, 2), 0, {})
    b = (t[:2], la, lo, np.arange(8, dtype="float32").reshape(2, 2, 2) + 100, 0, {})
    ds = e.build_dataset({"A": a, "B": b})
    assert ds.sizes["time"] == 2 and float(ds.A.isel(time=1, lat=0, lon=0)) == 4.0
    none = (t[:1] + np.timedelta64(5, "D"), la, lo, np.zeros((1, 2, 2), dtype="float32"), 0, {})
    with pytest.raises(ValueError, match="共同"):
        e.build_dataset({"A": a, "B": none})


def test_batch_path_depends_on_range_and_none_without_cache(tmp_path):
    assert e.batch_path(None, "U", 0, 24, (1, 2, 3, 4)) is None
    p1 = e.batch_path(tmp_path, "U", 0, 24, (21, 23.5, 119, 121.5))
    assert p1 != e.batch_path(tmp_path, "U", 0, 24, (21, 23.5, 119, 122))
    assert p1 != e.batch_path(tmp_path, "U", 24, 48, (21, 23.5, 119, 121.5))
    assert p1 != e.batch_path(tmp_path, "V", 0, 24, (21, 23.5, 119, 121.5))


def test_extract_variable_resumes_from_cached_batches(server, tmp_path):
    pytest.importorskip("requests")
    zp, expected, lats, lons = build_cwa_like_zip(tmp_path)
    url = server(zp.read_bytes())
    cache = tmp_path / "parts"
    args = (url, "VCURR", (21.0, 21.5, 119.0, 119.5), datetime(2023, 7, 1, 2), datetime(2023, 7, 1, 6), False, 8)
    first = e.extract_variable(*args, step_batch=2, cache_dir=cache)
    files = sorted(cache.glob("*.npy"))
    assert len(files) == 3                                   # 5 步、每批 2 步 → 3 批
    np.save(files[0], np.full_like(np.load(files[0]), 7.0))  # 把第一批換成記號值；重跑若真的用暫存就會看到
    again = e.extract_variable(*args, step_batch=2, cache_dir=cache)
    assert np.all(again[3][:2] == 7.0)
    assert np.allclose(again[3][2:], first[3][2:], equal_nan=True)


def test_group_by_grid_separates_different_resolutions():
    t = np.array(["2023-07-01T00"], dtype="datetime64[ns]")
    fine = (t, np.linspace(21, 23.5, 101), np.linspace(119, 121.5, 101), None, 0, {})
    coarse = (t, np.linspace(21, 23.5, 19), np.linspace(119, 121.5, 19), None, 0, {})
    r = {"UCURR": fine, "U10M": coarse, "VCURR": fine, "V10M": coarse}
    assert e.group_by_grid(r) == [["UCURR", "VCURR"], ["U10M", "V10M"]]


def test_build_dataset_reports_shapes_when_grids_differ():
    pytest.importorskip("xarray")
    t = np.array(["2023-07-01T00"], dtype="datetime64[ns]")
    a = (t, np.zeros(101), np.zeros(101), np.zeros((1, 101, 101), dtype="float32"), 0, {})
    b = (t, np.zeros(19), np.zeros(19), np.zeros((1, 19, 19), dtype="float32"), 0, {})
    with pytest.raises(ValueError, match="不一致.*101"):
        e.build_dataset({"A": a, "B": b})
