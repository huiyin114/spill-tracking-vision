"""drift_sim.py 的測試。result_to_table 用假的結果物件測（不需要 OpenDrift）；
真的跑 OpenDrift 的測試需要 opendrift，沒裝就跳過。"""
import types

import numpy as np
import pandas as pd
import pytest

import drift_sim

NAN = np.nan
CATS = ["active", "missing_data", "stranded"]
TIMES = pd.date_range("2023-07-20 21:30", periods=4, freq="h")      # 沒有時區，視為 UTC


def fake_result(lon, lat, status):
    wrap = lambda a: types.SimpleNamespace(values=np.array(a, dtype=float))
    return {"lon": wrap(lon), "lat": wrap(lat), "status": wrap(status), "time": types.SimpleNamespace(values=TIMES.values)}


def table():
    lon = [[1, 2, 3, 4],        # 粒子 0：一直 active
           [1, 2, NAN, NAN],    # 粒子 1：第二個時間擱淺，之後 OpenDrift 的位置是空的
           [1, 2, NAN, NAN],    # 粒子 2：第二個時間飄出資料範圍（missing_data）
           [NAN, 5, 6, 7]]      # 粒子 3：一開始沒有狀態
    lat = [[10, 20, 30, 40], [10, 20, NAN, NAN], [10, 20, NAN, NAN], [NAN, 50, 60, 70]]
    st = [[0, 0, 0, 0], [0, 2, NAN, NAN], [0, 1, NAN, NAN], [NAN, 0, 0, 0]]
    return drift_sim.result_to_table(fake_result(lon, lat, st), CATS)


def get(t, particle, k):
    return t[(t["particle"] == particle)].iloc[k]


def test_table_shape_columns_and_utc_times():
    t = table()
    assert list(t.columns) == drift_sim.PARTICLE_COLUMNS and len(t) == 16
    assert str(t["time_utc"].dt.tz) == "UTC"
    assert list(t["particle"].iloc[:5]) == [0, 0, 0, 0, 1]
    assert get(t, 0, 2)["time_utc"] == pd.Timestamp("2023-07-20 23:30:00+00:00")


def test_active_particle_unchanged():
    t = table()
    assert [get(t, 0, k)["lon"] for k in range(4)] == [1, 2, 3, 4]
    assert set(t[t["particle"] == 0]["status"]) == {"active"}


def test_stranded_particle_keeps_its_position_and_status_afterwards():
    t = table()
    for k in (1, 2, 3):
        r = get(t, 1, k)
        assert (r["lon"], r["lat"], r["status"]) == (2, 20, "stranded")
    assert (get(t, 1, 0)["lon"], get(t, 1, 0)["status"]) == (1, "active")


def test_missing_data_particle_has_no_position_afterwards_but_keeps_status():
    t = table()
    assert (get(t, 2, 1)["lon"], get(t, 2, 1)["status"]) == (2, "missing_data")   # 停用當下的位置還在
    for k in (2, 3):
        r = get(t, 2, k)
        assert np.isnan(r["lon"]) and np.isnan(r["lat"]) and r["status"] == "missing_data"


def test_particle_without_initial_status_is_unknown():
    r = get(table(), 3, 0)
    assert r["status"] == "unknown" and np.isnan(r["lon"])
    assert get(table(), 3, 1)["status"] == "active"


def test_stranded_fill_does_not_leak_to_other_particles():
    t = table()
    assert t[t["particle"] == 3]["lon"].tolist()[1:] == [5, 6, 7]


def test_defaults_match_documented_assumptions():
    assert drift_sim.DEFAULT_WIND_DRIFT_FACTOR == 0.03
    assert drift_sim.OIL_TYPE == "AMSA Average Very Low Sulfur Fuel Oil (VLSFO)"
    assert drift_sim.DEFAULT_PARTICLES == 1000 and drift_sim.DEFAULT_SEED == 0


def test_constant_eastward_current_moves_particles_east():
    pytest.importorskip("opendrift")
    from opendrift.models.openoil import OpenOil
    from opendrift.readers import reader_constant

    o = OpenOil(loglevel=50, seed=0)
    o.add_reader(reader_constant.Reader({"x_sea_water_velocity": 1.0, "y_sea_water_velocity": 0.0,
                                         "x_wind": 0.0, "y_wind": 0.0}))
    o.set_config("seed:wind_drift_factor", 0.0)
    o.set_config("drift:current_uncertainty", 0.0)
    o.set_config("drift:wind_uncertainty", 0.0)
    o.set_config("drift:vertical_mixing", False)
    o.set_config("general:use_auto_landmask", False)
    o.set_config("environment:constant:land_binary_mask", 0)
    o.seed_elements(lon=120.0, lat=22.0, time=pd.Timestamp("2023-07-20 21:30").to_pydatetime(), number=5, radius=0)
    o.run(duration=pd.Timedelta(hours=1).to_pytimedelta(), time_step=900, time_step_output=3600)
    t = drift_sim.result_to_table(o.result, o.status_categories)
    last = t[t["time_utc"] == t["time_utc"].max()]
    # 1 m/s × 3600 s = 3.6 km；22°N 的 1 度經度約 103.1 km
    assert (last["lon"] - 120.0).mean() == pytest.approx(3.6 / 103.1, rel=0.03)
    assert (last["lat"] - 22.0).abs().max() < 1e-4


def test_oil_type_exists_in_the_opendrift_database():
    pytest.importorskip("opendrift")
    from opendrift.models.openoil import OpenOil

    assert drift_sim.OIL_TYPE in OpenOil(loglevel=50).oiltypes


def test_wind_drift_factor_moves_oil_by_that_fraction_of_the_wind():
    pytest.importorskip("opendrift")
    from opendrift.models.openoil import OpenOil
    from opendrift.readers import reader_constant

    o = OpenOil(loglevel=50, seed=0)
    o.add_reader(reader_constant.Reader({"x_sea_water_velocity": 0.0, "y_sea_water_velocity": 0.0,
                                         "x_wind": 10.0, "y_wind": 0.0}))
    o.set_config("seed:wind_drift_factor", 0.03)          # 與 drift_sim.run_simulation 用的設定名稱相同
    o.set_config("seed:oil_type", drift_sim.OIL_TYPE)
    for key in ("drift:current_uncertainty", "drift:wind_uncertainty"):
        o.set_config(key, 0.0)
    o.set_config("drift:vertical_mixing", False)
    o.set_config("general:use_auto_landmask", False)
    o.set_config("environment:constant:land_binary_mask", 0)
    o.seed_elements(lon=120.0, lat=22.0, time=pd.Timestamp("2023-07-20 21:30").to_pydatetime(), number=3, radius=0)
    o.run(duration=pd.Timedelta(hours=1).to_pytimedelta(), time_step=900, time_step_output=3600)
    t = drift_sim.result_to_table(o.result, o.status_categories)
    last = t[t["time_utc"] == t["time_utc"].max()]
    # 3% × 10 m/s = 0.3 m/s，一小時 1.08 km
    assert (last["lon"] - 120.0).mean() == pytest.approx(1.08 / 103.1, rel=0.05)


def _write_smoc_like(path, utotal, uo, vsdx):
    """造一個像 SMOC 的小檔案：uo、utotal、vsdx 都有，單位 m/s，全部往東；沒有 y 分量時用 0。"""
    xr = pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")
    t = pd.date_range("2023-07-20 00:00", periods=4, freq="h")
    lat = np.array([21.5, 22.0, 22.5, 23.0])
    lon = np.array([119.5, 120.0, 120.5, 121.0])
    full = lambda v: np.full((4, 1, 4, 4), float(v))
    attrs = lambda name: {"standard_name": name, "units": "m s-1"}
    # utotal、vtotal 放在 uo、vo 前面，確認指定的變數優先，不是靠變數順序
    ds = xr.Dataset(
        {"utotal": (("time", "depth", "latitude", "longitude"), full(utotal), attrs("surface_sea_water_x_velocity")),
         "vtotal": (("time", "depth", "latitude", "longitude"), full(0), attrs("surface_sea_water_y_velocity")),
         "uo": (("time", "depth", "latitude", "longitude"), full(uo), attrs("eastward_sea_water_velocity")),
         "vo": (("time", "depth", "latitude", "longitude"), full(0), attrs("northward_sea_water_velocity")),
         "vsdx": (("time", "depth", "latitude", "longitude"), full(vsdx), attrs("sea_surface_wave_stokes_drift_x_velocity")),
         "vsdy": (("time", "depth", "latitude", "longitude"), full(0), attrs("sea_surface_wave_stokes_drift_y_velocity"))},
        coords={"time": t, "depth": [0.49], "latitude": lat, "longitude": lon})
    ds.to_netcdf(path)


def _write_wind_zero(path):
    xr = pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")
    t = pd.date_range("2023-07-20 00:00", periods=4, freq="h")
    lat = np.array([21.5, 22.0, 22.5, 23.0])
    lon = np.array([119.5, 120.0, 120.5, 121.0])
    z = np.zeros((4, 4, 4))
    attrs = lambda name: {"standard_name": name, "units": "m s-1"}
    xr.Dataset({"eastward_wind": (("time", "latitude", "longitude"), z, attrs("eastward_wind")),
                "northward_wind": (("time", "latitude", "longitude"), z, attrs("northward_wind"))},
               coords={"time": t, "latitude": lat, "longitude": lon}).to_netcdf(path)


def _drift_km_east(model):
    model.set_config("drift:current_uncertainty", 0.0)
    model.set_config("drift:wind_uncertainty", 0.0)
    model.set_config("drift:vertical_mixing", False)
    model.set_config("general:use_auto_landmask", False)
    model.set_config("environment:constant:land_binary_mask", 0)
    model.seed_elements(lon=120.0, lat=22.0, time=pd.Timestamp("2023-07-20 00:30").to_pydatetime(), number=3, radius=0)
    model.run(duration=pd.Timedelta(hours=1).to_pytimedelta(), time_step=900, time_step_output=3600)
    t = drift_sim.result_to_table(model.result, model.status_categories)
    last = t[t["time_utc"] == t["time_utc"].max()]
    return float((last["lon"] - 120.0).mean()) * 103.1


def test_smoc_like_total_current_is_used_and_stokes_is_not_counted_twice(tmp_path):
    pytest.importorskip("opendrift")
    cur, wind = tmp_path / "c.nc", tmp_path / "w.nc"
    _write_smoc_like(cur, utotal=1.0, uo=0.0, vsdx=1.0)          # 總和 1 m/s；環流 0；Stokes 1 m/s（已含在總和裡）
    _write_wind_zero(wind)
    m = drift_sim.build_model(cur, wind, wind_drift_factor=0.0, current_variables=("utotal", "vtotal"))
    assert _drift_km_east(m) == pytest.approx(3.6, rel=0.03)      # 只算總和：3.6 km；若又加 Stokes 會是 7.2 km；若用 uo 會是 0


def test_without_current_variables_the_file_is_read_by_standard_names(tmp_path):
    pytest.importorskip("opendrift")
    cur, wind = tmp_path / "c.nc", tmp_path / "w.nc"
    _write_smoc_like(cur, utotal=5.0, uo=1.0, vsdx=0.0)           # 沒指定時用 uo（1 m/s），不是 utotal（5 m/s）
    _write_wind_zero(wind)
    m = drift_sim.build_model(cur, wind, wind_drift_factor=0.0)
    assert _drift_km_east(m) == pytest.approx(3.6, rel=0.03)


# ---- 模擬提早結束（粒子都停用）時延續最後的狀態 ----

def _final_table(statuses, lons=None):
    t = pd.Timestamp("2023-07-23 04:30", tz="UTC")
    lons = lons or [120.0 + 0.1 * i for i in range(len(statuses))]
    return pd.DataFrame({"time_utc": [t] * len(statuses), "particle": range(len(statuses)),
                         "lon": [x if s != "missing_data" else np.nan for x, s in zip(lons, statuses)],
                         "lat": [23.0] * len(statuses), "status": statuses})


def test_hold_until_keeps_stranded_positions_and_clears_other_positions():
    t = _final_table(["stranded", "missing_data"])
    out = drift_sim.hold_until(t, pd.Timestamp("2023-07-23 07:30", tz="UTC"), 3600)
    later = out[out["time_utc"] > t["time_utc"].max()]
    assert sorted(later["time_utc"].unique()) == [pd.Timestamp(f"2023-07-23 0{h}:30", tz="UTC") for h in (5, 6, 7)]
    s = later[later["particle"] == 0]
    assert (s["status"] == "stranded").all() and (s["lon"] == 120.0).all() and (s["lat"] == 23.0).all()
    m = later[later["particle"] == 1]
    assert (m["status"] == "missing_data").all() and m["lon"].isna().all()


def test_hold_until_does_nothing_when_the_run_already_reaches_the_end():
    t = _final_table(["stranded"])
    assert drift_sim.hold_until(t, pd.Timestamp("2023-07-23 04:30", tz="UTC"), 3600) is t
    assert drift_sim.hold_until(t, pd.Timestamp("2023-07-23 05:20", tz="UTC"), 3600) is t     # 不足一個輸出步長


def test_hold_until_refuses_when_particles_are_still_active():
    with pytest.raises(ValueError, match="active"):
        drift_sim.hold_until(_final_table(["stranded", "active"]), pd.Timestamp("2023-07-24", tz="UTC"), 3600)


def test_hold_until_uses_the_output_step_and_original_rows_are_unchanged():
    t = _final_table(["stranded"])
    out = drift_sim.hold_until(t, pd.Timestamp("2023-07-23 06:30", tz="UTC"), 1800)
    assert len(out) == 1 + 4
    assert out.iloc[0].to_dict() == t.iloc[0].to_dict()


def test_hold_until_uses_final_states_for_particles_that_stopped_after_the_last_output():
    t = _final_table(["stranded", "active", "active"])
    final = pd.DataFrame({"particle": [1, 2], "status": ["stranded", "missing_data"],
                          "lon": [121.5, 119.0], "lat": [23.2, 23.3]})
    out = drift_sim.hold_until(t, pd.Timestamp("2023-07-23 06:30", tz="UTC"), 3600, final)
    nxt = out[out["time_utc"] == pd.Timestamp("2023-07-23 05:30", tz="UTC")].set_index("particle")
    assert nxt.loc[1, "status"] == "stranded" and nxt.loc[1, "lon"] == 121.5 and nxt.loc[1, "lat"] == 23.2
    assert nxt.loc[2, "status"] == "missing_data" and nxt.loc[2, "lon"] == 119.0     # 停用當下的位置還在
    assert nxt.loc[0, "lon"] == 120.0                                   # 原本就擱淺的不受影響
    last = out[out["time_utc"] == pd.Timestamp("2023-07-23 06:30", tz="UTC")].set_index("particle")
    assert last.loc[1, "lon"] == 121.5 and np.isnan(last.loc[2, "lon"])    # 擱淺的位置繼續延續，missing_data 之後沒有位置
    assert out["time_utc"].nunique() == 3 and not (out["status"] == "active").iloc[len(t):].any()


def test_hold_until_final_state_frame_is_not_added_when_the_run_reached_its_end():
    t = _final_table(["stranded", "active"])
    final = pd.DataFrame({"particle": [1], "status": ["stranded"], "lon": [121.5], "lat": [23.2]})
    assert drift_sim.hold_until(t, pd.Timestamp("2023-07-23 04:30", tz="UTC"), 3600, final) is t


def test_hold_until_refuses_when_a_still_active_particle_has_no_final_state():
    t = _final_table(["stranded", "active", "active"])
    final = pd.DataFrame({"particle": [1], "status": ["stranded"], "lon": [121.5], "lat": [23.2]})
    with pytest.raises(ValueError, match="沒有最後的狀態"):
        drift_sim.hold_until(t, pd.Timestamp("2023-07-24", tz="UTC"), 3600, final)


def test_hold_until_final_state_when_only_one_step_remains():
    t = _final_table(["active"])
    final = pd.DataFrame({"particle": [0], "status": ["stranded"], "lon": [121.5], "lat": [23.2]})
    out = drift_sim.hold_until(t, pd.Timestamp("2023-07-23 05:30", tz="UTC"), 3600, final)
    assert len(out) == 2 and out.iloc[1]["status"] == "stranded" and out.iloc[1]["lon"] == 121.5


def test_deactivated_table_converts_openDrift_elements():
    ed = types.SimpleNamespace(ID=np.array([709, 3]), status=np.array([1.0, 2.0]),
                               lon=np.array([120.05, 119.0]), lat=np.array([23.18, 23.5]))
    model = types.SimpleNamespace(elements_deactivated=ed, status_categories=["active", "stranded", "missing_data"])
    t = drift_sim.deactivated_table(model)
    assert list(t.columns) == ["particle", "status", "lon", "lat"]
    assert t["particle"].tolist() == [709, 3] and t["status"].tolist() == ["stranded", "missing_data"]
    assert t["lon"].tolist() == [120.05, 119.0] and t["lat"].tolist() == [23.18, 23.5]
