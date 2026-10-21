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
