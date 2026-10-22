import numpy as np
import pytest

import cwa_prepare as p

pytest.importorskip("scipy")
xr = pytest.importorskip("xarray")


def test_fill_nearest_uses_closest_valid_cell_and_keeps_valid_values():
    f = np.array([[1.0, np.nan, np.nan], [np.nan, np.nan, 9.0]])
    g = p.fill_nearest(f)
    assert g[0, 0] == 1.0 and g[1, 2] == 9.0
    assert g[0, 1] == 1.0 and g[0, 2] == 9.0 and g[1, 0] == 1.0     # 各自最近的有值格點
    assert not np.isnan(g).any()


def test_fill_nearest_leaves_all_nan_and_no_nan_untouched():
    assert np.isnan(p.fill_nearest(np.full((2, 2), np.nan))).all()
    full = np.arange(4.0).reshape(2, 2)
    assert (p.fill_nearest(full) == full).all()


def test_fill_cube_interpolates_missing_time_steps_linearly():
    cube = np.zeros((4, 1, 2))
    cube[3] = 3.0
    cube[1:3] = np.nan                      # 整個時間步缺
    out = p.fill_cube(cube)
    assert np.allclose(out[:, 0, 0], [0, 1, 2, 3]) and out.dtype == np.float32


def test_fill_cube_fills_space_from_same_time_step_when_time_cannot_help():
    cube = np.array([[[1.0, np.nan]], [[2.0, 5.0]]])   # 第一步右格缺：時間內插不外推，改用同一步最近格點
    out = p.fill_cube(cube)
    assert out[0, 0, 1] == 1.0 and out[1, 0, 1] == 5.0


def _ds(names):
    t = np.array(["2023-07-01T00", "2023-07-01T01"], dtype="datetime64[ns]")
    return xr.Dataset({n: (("time", "lat", "lon"), np.full((2, 2, 2), float(i + 1))) for i, n in enumerate(names)},
                      coords={"time": t, "lat": [21.0, 21.1], "lon": [119.0, 119.1]})


def test_prepare_current_sets_cf_standard_names_and_keeps_component_order():
    out = p.prepare_current(_ds(["UCURRd10", "VCURRd10"]))
    assert out.uo.attrs["standard_name"] == "eastward_sea_water_velocity" and float(out.uo[0, 0, 0]) == 1.0
    assert out.vo.attrs["standard_name"] == "northward_sea_water_velocity" and float(out.vo[0, 0, 0]) == 2.0
    assert out.latitude.attrs["units"] == "degrees_north"


def test_prepare_wind_maps_u_to_eastward_and_v_to_northward():
    out = p.prepare_wind(_ds(["U10M", "V10M"]))
    assert float(out.eastward_wind[0, 0, 0]) == 1.0 and float(out.northward_wind[0, 0, 0]) == 2.0
    assert out.eastward_wind.attrs["standard_name"] == "eastward_wind"
