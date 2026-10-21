import numpy as np
import pytest

import merge_hycom as m


def t(*hours):
    return np.array([np.datetime64("2023-07-20T00:00") + np.timedelta64(h, "h") for h in hours])


def test_merge_plan_keeps_first_occurrence_and_sorts():
    plan, dups = m.merge_plan([t(0, 3, 6), t(6, 9)])
    assert plan == [(0, 0), (0, 1), (0, 2), (1, 1)]
    assert dups == [((0, 2), (1, 0))]


def test_merge_plan_sorts_files_given_out_of_order():
    plan, dups = m.merge_plan([t(6, 9), t(0, 3, 6)])
    assert [p for p in plan] == [(1, 0), (1, 1), (0, 0), (0, 1)]
    assert dups == [((0, 0), (1, 2))]


def test_merge_plan_without_overlap_has_no_duplicates():
    plan, dups = m.merge_plan([t(0, 3), t(6, 9)])
    assert len(plan) == 4 and dups == []


def test_merge_plan_empty():
    assert m.merge_plan([]) == ([], [])


def test_check_regular_accepts_fixed_step():
    m.check_regular(t(0, 3, 6, 9), 3)


def test_check_regular_rejects_gap():
    with pytest.raises(ValueError, match="固定"):
        m.check_regular(t(0, 3, 9), 3)


def test_check_regular_rejects_wrong_step():
    with pytest.raises(ValueError, match="固定"):
        m.check_regular(t(0, 1, 2), 3)


def test_check_regular_rejects_single_time():
    with pytest.raises(ValueError, match="兩筆"):
        m.check_regular(t(0), 3)


def make_file(path, hours, u_fill=0.1, depths=(0.0,), land=False):
    xr = pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")
    times = np.array([np.datetime64("2023-07-20T00:00") + np.timedelta64(h, "h") for h in hours])
    shape = (len(times), len(depths), 2, 3)
    u = np.full(shape, u_fill, dtype="float32")
    if land:
        u[..., 0, 0] = np.nan  # 陸地格點整段都是缺值
    ds = xr.Dataset(
        {"water_u": (("time", "depth", "lat", "lon"), u),
         "water_v": (("time", "depth", "lat", "lon"), np.full(shape, -0.2, dtype="float32"))},
        coords={"time": times, "depth": list(depths), "lat": [22.0, 22.04], "lon": [120.0, 120.04, 120.08]})
    ds.to_netcdf(path)


def test_merge_files_joins_overlapping_days(tmp_path):
    make_file(tmp_path / "a.nc", [0, 3, 6])
    make_file(tmp_path / "b.nc", [6, 9, 12])
    out = tmp_path / "out.nc"
    times = m.merge_files([str(tmp_path / "a.nc"), str(tmp_path / "b.nc")], str(out))
    assert len(times) == 5
    import xarray as xr
    d = xr.open_dataset(out)
    assert d.sizes["time"] == 5 and float(d.water_v.isel(time=4, depth=0, lat=0, lon=0)) == pytest.approx(-0.2)


def test_merge_files_rejects_differing_duplicate(tmp_path):
    make_file(tmp_path / "a.nc", [0, 3, 6])
    make_file(tmp_path / "b.nc", [6, 9], u_fill=0.5)
    with pytest.raises(ValueError, match="數值不同"):
        m.merge_files([str(tmp_path / "a.nc"), str(tmp_path / "b.nc")], str(tmp_path / "o.nc"))


def test_merge_files_rejects_missing_day(tmp_path):
    make_file(tmp_path / "a.nc", [0, 3])
    make_file(tmp_path / "b.nc", [12, 15])
    with pytest.raises(ValueError, match="固定"):
        m.merge_files([str(tmp_path / "a.nc"), str(tmp_path / "b.nc")], str(tmp_path / "o.nc"))


def test_merge_files_rejects_multiple_depths(tmp_path):
    make_file(tmp_path / "a.nc", [0, 3], depths=(0.0, 2.0))
    with pytest.raises(ValueError, match="depth"):
        m.merge_files([str(tmp_path / "a.nc")], str(tmp_path / "o.nc"))


def test_merge_files_rejects_missing_variable(tmp_path):
    xr = pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")
    ds = xr.Dataset({"water_u": (("time",), np.zeros(2, dtype="float32"))},
                    coords={"time": t(0, 3)})
    ds.to_netcdf(tmp_path / "a.nc")
    with pytest.raises(ValueError, match="缺少變數"):
        m.merge_files([str(tmp_path / "a.nc")], str(tmp_path / "o.nc"))


def test_merge_files_accepts_land_cells_in_duplicates(tmp_path):
    make_file(tmp_path / "a.nc", [0, 3, 6], land=True)
    make_file(tmp_path / "b.nc", [6, 9], land=True)
    times = m.merge_files([str(tmp_path / "a.nc"), str(tmp_path / "b.nc")], str(tmp_path / "o.nc"))
    assert len(times) == 4
