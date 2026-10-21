"""ocean.py 的測試：自己造小資料，不讀 data/。"""
import numpy as np
import pandas as pd
import pytest

import ocean


def make_ocean(rows):
    """rows: [(UTC 時間字串, cu, cv, wu, wv), ...]"""
    return pd.DataFrame(rows, columns=ocean.REQUIRED_COLUMNS).assign(
        time_utc=lambda d: pd.to_datetime(d["time_utc"], utc=True))


def make_timeline(*times_utc, sensor="S2"):
    return pd.DataFrame([{"sensor": sensor, "time_utc": t,
                          "time_tw": str(pd.Timestamp(t).tz_convert("Asia/Taipei"))} for t in times_utc])


# ---- 方向與速度 ----

@pytest.mark.parametrize("u,v,to,frm", [
    (0, 1, 0, 180),      # 往北 → 來自南
    (1, 0, 90, 270),     # 往東 → 來自西
    (0, -1, 180, 0),     # 往南 → 來自北（北風是 0 不是 360）
    (-1, 0, 270, 90),    # 往西 → 來自東
    (1, 1, 45, 225),
])
def test_direction_conventions(u, v, to, frm):
    assert ocean.direction_to(u, v) == pytest.approx(to)
    assert ocean.direction_from(u, v) == pytest.approx(frm)


def test_direction_never_reaches_360():
    # 極小的負 u、v 朝北：-1e-20 % 360 在浮點下會等於 360.0
    assert ocean.direction_to(-1e-20, 1.0) == 0.0
    assert ocean.direction_from(-1e-20, -1.0) == 0.0


def test_calm_has_no_direction_but_has_speed():
    assert ocean.speed(0, 0) == 0
    assert np.isnan(ocean.direction_to(0, 0))
    assert np.isnan(ocean.direction_from(0, 0))


def test_nan_input_gives_nan():
    assert np.isnan(ocean.speed(np.nan, 1.0))
    assert np.isnan(ocean.direction_to(np.nan, 1.0))
    assert np.isnan(ocean.direction_to(1.0, np.nan))


def test_speed_and_direction_work_on_arrays():
    u = np.array([3.0, 0.0, 0.0])
    v = np.array([4.0, 0.0, -2.0])
    assert ocean.speed(u, v).tolist() == [5.0, 0.0, 2.0]
    d = ocean.direction_to(u, v)
    assert d[0] == pytest.approx(36.8699, abs=1e-3)
    assert np.isnan(d[1])
    assert d[2] == pytest.approx(180)


# ---- 讀檔 ----

def test_load_ocean_sorts_and_parses_utc(tmp_path):
    p = tmp_path / "o.csv"
    p.write_text("time_utc,current_u,current_v,wind_u,wind_v\n"
                 "2023-07-20 02:00:00+00:00,1,2,3,4\n"
                 "2023-07-20 01:00:00+00:00,5,6,7,8\n", encoding="utf-8")
    df = ocean.load_ocean(p)
    assert list(df["current_u"]) == [5, 1]
    assert str(df["time_utc"].dt.tz) == "UTC"


def test_load_ocean_rejects_missing_column(tmp_path):
    p = tmp_path / "o.csv"
    p.write_text("time_utc,current_u,current_v,wind_u\n2023-07-20 01:00:00+00:00,1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="wind_v"):
        ocean.load_ocean(p)


def test_load_ocean_rejects_duplicate_time(tmp_path):
    p = tmp_path / "o.csv"
    p.write_text("time_utc,current_u,current_v,wind_u,wind_v\n"
                 "2023-07-20 01:00:00+00:00,1,2,3,4\n2023-07-20 01:00:00+00:00,1,2,3,4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="重複"):
        ocean.load_ocean(p)


# ---- 對齊 ----

OC = make_ocean([
    ("2023-07-24 02:00:00+00:00", 0.0, 1.0, 3.0, 4.0),    # 海流往北；風往東北偏北（3,4）
    ("2023-07-24 03:00:00+00:00", 1.0, 0.0, 0.0, -2.0),
])


def test_picks_nearest_hour_and_gap_sign_is_model_minus_pass():
    # 過境 02:25:39 → 02:00 差 -25.65 分（模型在前），03:00 差 +34.35 分
    out = ocean.ocean_at_passes(make_timeline("2023-07-24 02:25:39+00:00"), OC)
    assert len(out) == 1
    r = out.iloc[0]
    assert r["gap_min"] == pytest.approx(-25.65)
    assert r["obs_time_utc"] == pd.Timestamp("2023-07-24 02:00:00+00:00")
    assert r["current_speed"] == pytest.approx(1.0)
    assert r["current_direction_to"] == pytest.approx(0.0)
    assert r["model_wind_speed"] == pytest.approx(5.0)
    assert r["model_wind_direction_from"] == pytest.approx((np.degrees(np.arctan2(3, 4)) + 180) % 360)


def test_later_hour_has_positive_gap():
    out = ocean.ocean_at_passes(make_timeline("2023-07-24 02:40:00+00:00"), OC)
    r = out.iloc[0]
    assert r["gap_min"] == pytest.approx(20.0)
    assert r["current_direction_to"] == pytest.approx(90.0)
    assert r["model_wind_direction_from"] == pytest.approx(0.0)  # 風往南 → 來自北


def test_tie_takes_the_earlier_hour():
    out = ocean.ocean_at_passes(make_timeline("2023-07-24 02:30:00+00:00"), OC)
    assert out.iloc[0]["gap_min"] == pytest.approx(-30.0)
    assert out.iloc[0]["current_direction_to"] == pytest.approx(0.0)


def test_tie_takes_the_earlier_hour_even_if_rows_are_in_reverse_order():
    out = ocean.ocean_at_passes(make_timeline("2023-07-24 02:30:00+00:00"), OC.iloc[::-1].reset_index(drop=True))
    assert out.iloc[0]["gap_min"] == pytest.approx(-30.0)
    assert out.iloc[0]["current_direction_to"] == pytest.approx(0.0)


def test_beyond_max_gap_gives_no_row():
    out = ocean.ocean_at_passes(make_timeline("2023-07-24 03:31:00+00:00"), OC)
    assert out.empty
    assert list(out.columns) == ocean.ALIGNED_COLUMNS


def test_exactly_max_gap_is_kept_and_max_gap_is_configurable():
    t = make_timeline("2023-07-24 03:30:00+00:00")
    assert len(ocean.ocean_at_passes(t, OC)) == 1
    assert ocean.ocean_at_passes(t, OC, max_gap_min=29).empty


def test_missing_model_value_keeps_row_with_nan_not_zero():
    oc = make_ocean([("2023-07-24 02:00:00+00:00", np.nan, 1.0, 3.0, 4.0)])
    out = ocean.ocean_at_passes(make_timeline("2023-07-24 02:00:00+00:00"), oc)
    assert len(out) == 1
    assert np.isnan(out.iloc[0]["current_speed"])
    assert np.isnan(out.iloc[0]["current_direction_to"])
    assert out.iloc[0]["model_wind_speed"] == pytest.approx(5.0)


def test_calm_current_keeps_speed_zero_and_direction_nan():
    oc = make_ocean([("2023-07-24 02:00:00+00:00", 0.0, 0.0, 3.0, 4.0)])
    r = ocean.ocean_at_passes(make_timeline("2023-07-24 02:00:00+00:00"), oc).iloc[0]
    assert r["current_speed"] == 0.0
    assert np.isnan(r["current_direction_to"])


def test_each_pass_gets_its_own_row_and_columns_are_copied():
    tl = pd.concat([make_timeline("2023-07-24 02:00:00+00:00", sensor="S1"),
                    make_timeline("2023-07-24 03:00:00+00:00", sensor="S2"),
                    make_timeline("2023-08-30 03:00:00+00:00", sensor="S2")], ignore_index=True)
    out = ocean.ocean_at_passes(tl, OC)
    assert list(out["sensor"]) == ["S1", "S2"]           # 第三次不在模型涵蓋範圍
    assert list(out["time_tw"]) == list(tl["time_tw"].iloc[:2])
    assert list(out["gap_min"]) == [0.0, 0.0]
    assert list(out.columns) == ocean.ALIGNED_COLUMNS


def test_empty_ocean_gives_empty_table():
    out = ocean.ocean_at_passes(make_timeline("2023-07-24 02:00:00+00:00"), OC.iloc[0:0])
    assert out.empty
    assert list(out.columns) == ocean.ALIGNED_COLUMNS
