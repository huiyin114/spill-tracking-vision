"""features.py 的測試：自己造小資料，不讀 data/。"""
import numpy as np
import pandas as pd
import pytest

import features


def make_timeline():
    """兩次過境：S2 有雲量、配對到無人機；S1 沒有雲量、沒有無人機。"""
    return pd.DataFrame([
        {"sensor": "S2", "time_tw": "2023-07-24 10:25:39+08:00", "time_utc": "2023-07-24 02:25:39+00:00",
         "hours_since_event": 77.0, "orbit_state": "", "mode": "", "covers_wreck": True,
         "cloud_cover_min": 12.5, "drone_date": "2023-07-25", "drone_gap_hours": 20.0, "drone_n_near": 8},
        {"sensor": "S1", "time_tw": "2023-07-22 06:00:00+08:00", "time_utc": "2023-07-21 22:00:00+00:00",
         "hours_since_event": 24.5, "orbit_state": "ascending", "mode": "IW", "covers_wreck": False,
         "cloud_cover_min": np.nan, "drone_date": np.nan, "drone_gap_hours": np.nan, "drone_n_near": np.nan},
    ])


def make_wind():
    """S2 夾在兩個整點之間（兩列），S1 一列，另有一列沒有觀測值。"""
    base = {"covers_wreck": True, "station_name": "鼓山", "dist_km": 7.2}
    return pd.DataFrame([
        {**base, "sensor": "S2", "time_tw": "2023-07-24 10:25:39+08:00", "station": "C0V690",
         "obs_time_tw": "2023-07-24 10:00:00+08:00", "gap_min": -25.65, "ws_ms": 3.0, "wd_deg": 90.0},
        {**base, "sensor": "S2", "time_tw": "2023-07-24 10:25:39+08:00", "station": "C0V690",
         "obs_time_tw": "2023-07-24 11:00:00+08:00", "gap_min": 24.35, "ws_ms": 5.0, "wd_deg": 100.0},
        {**base, "sensor": "S1", "time_tw": "2023-07-22 06:00:00+08:00", "station": "C0V690",
         "obs_time_tw": "2023-07-22 06:00:00+08:00", "gap_min": 0.0, "ws_ms": np.nan, "wd_deg": np.nan},
    ])


def get(f, pid, variable, source=None):
    r = f[(f["pass_id"] == pid) & (f["variable"] == variable)]
    if source is not None:
        r = r[r["source"] == source]
    return r


S2 = "S2_20230724T022539Z"
S1 = "S1_20230721T220000Z"


def test_pass_id_uses_utc_to_the_second():
    t = pd.Timestamp("2023-07-24 10:25:39+08:00")
    assert features.make_pass_id("S2", t) == S2


def test_pass_id_rejects_naive_time():
    with pytest.raises(ValueError):
        features.make_pass_id("S2", pd.Timestamp("2023-07-24 10:25:39"))


def test_build_passes_one_row_per_pass_sorted_by_time():
    p = features.build_passes(make_timeline())
    assert list(p["pass_id"]) == [S1, S2]
    assert list(p.columns) == features.PASS_COLUMNS


def test_build_passes_rejects_duplicate_pass():
    t = make_timeline()
    t = pd.concat([t, t.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError):
        features.build_passes(t)


def test_event_and_cloud_values_land_correctly():
    f = features.build_features_long(make_timeline(), make_wind())
    assert get(f, S2, "hours_since_event")["value"].iloc[0] == 77.0
    assert get(f, S1, "hours_since_event")["value"].iloc[0] == 24.5
    assert get(f, S2, "cloud_cover_min")["value"].iloc[0] == 12.5
    assert get(f, S2, "cloud_cover_min")["source"].iloc[0] == "stac"


def test_not_applicable_variables_have_no_rows():
    f = features.build_features_long(make_timeline(), make_wind())
    assert get(f, S1, "cloud_cover_min").empty
    assert get(f, S1, "drone_gap_hours").empty
    assert get(f, S1, "drone_n_near").empty


def test_drone_values():
    f = features.build_features_long(make_timeline(), make_wind())
    assert get(f, S2, "drone_gap_hours")["value"].iloc[0] == 20.0
    assert get(f, S2, "drone_n_near")["value"].iloc[0] == 8.0


def test_two_wind_rows_for_one_pass_are_both_kept():
    f = features.build_features_long(make_timeline(), make_wind())
    ws = get(f, S2, "wind_speed", "C0V690").sort_values("gap_min")
    assert list(ws["value"]) == [3.0, 5.0]
    assert list(ws["gap_min"]) == [-25.65, 24.35]
    wd = get(f, S2, "wind_direction", "C0V690").sort_values("gap_min")
    assert list(wd["value"]) == [90.0, 100.0]


def test_missing_wind_stays_empty_not_zero():
    f = features.build_features_long(make_timeline(), make_wind())
    r = get(f, S1, "wind_speed", "C0V690")
    assert len(r) == 1 and np.isnan(r["value"].iloc[0])


def test_units_come_from_registry():
    f = features.build_features_long(make_timeline(), make_wind())
    assert set(get(f, S2, "wind_speed")["unit"]) == {"m/s"}
    assert set(get(f, S2, "wind_direction")["unit"]) == {"deg"}
    assert set(get(f, S2, "hours_since_event")["unit"]) == {"h"}
    assert f["unit"].notna().all()


def test_non_observation_variables_have_empty_gap():
    f = features.build_features_long(make_timeline(), make_wind())
    assert get(f, S2, "cloud_cover_min")["gap_min"].isna().all()


def test_wind_pass_not_in_timeline_is_rejected():
    w = make_wind()
    w.loc[2, "time_tw"] = "2023-07-23 06:00:00+08:00"
    with pytest.raises(ValueError, match="對不上"):
        features.build_features_long(make_timeline(), w)


def test_duplicate_wind_rows_are_rejected():
    w = pd.concat([make_wind(), make_wind().iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError):
        features.build_features_long(make_timeline(), w)


def test_every_variable_in_output_is_registered():
    f = features.build_features_long(make_timeline(), make_wind())
    assert set(f["variable"]) <= set(features.VARIABLES)


def test_to_wide_one_row_per_pass_with_source_in_column_name():
    w = features.to_wide(features.build_features_long(make_timeline(), make_wind()))
    assert sorted(w["pass_id"]) == [S1, S2]
    assert {"wind_speed@C0V690", "hours_since_event@event", "cloud_cover_min@stac"} <= set(w.columns)


def test_to_wide_round_trip_values_match_timeline():
    tl = make_timeline()
    w = features.to_wide(features.build_features_long(tl, make_wind())).set_index("pass_id")
    assert w.loc[S2, "hours_since_event@event"] == 77.0
    assert w.loc[S1, "hours_since_event@event"] == 24.5
    assert w.loc[S2, "drone_n_near@drone"] == 8.0
    assert np.isnan(w.loc[S1, "cloud_cover_min@stac"])


def test_to_wide_nearest_picks_smaller_abs_gap():
    w = features.to_wide(features.build_features_long(make_timeline(), make_wind())).set_index("pass_id")
    assert w.loc[S2, "wind_speed@C0V690"] == 5.0      # |24.35| < |-25.65|
    assert w.loc[S2, "wind_direction@C0V690"] == 100.0


def test_to_wide_tie_takes_earlier():
    w = make_wind()
    w.loc[0, "gap_min"] = -25.0
    w.loc[1, "gap_min"] = 25.0
    wide = features.to_wide(features.build_features_long(make_timeline(), w)).set_index("pass_id")
    assert wide.loc[S2, "wind_speed@C0V690"] == 3.0


def test_to_wide_tie_takes_earlier_even_if_rows_are_in_reverse_order():
    w = make_wind()
    w.loc[0, "gap_min"] = -25.0
    w.loc[1, "gap_min"] = 25.0
    long = features.build_features_long(make_timeline(), w)
    wide = features.to_wide(long.iloc[::-1]).set_index("pass_id")
    assert wide.loc[S2, "wind_speed@C0V690"] == 3.0


def test_to_wide_chosen_missing_value_is_not_replaced_by_other_row():
    w = make_wind()
    w.loc[1, "ws_ms"] = np.nan   # 較近的那筆是空值
    wide = features.to_wide(features.build_features_long(make_timeline(), w)).set_index("pass_id")
    assert np.isnan(wide.loc[S2, "wind_speed@C0V690"])


def test_to_wide_rejects_unknown_pick():
    with pytest.raises(ValueError):
        features.to_wide(features.build_features_long(make_timeline(), make_wind()), pick="mean")


def test_new_variable_needs_no_schema_change():
    """加一個新來源（例如另一個測站）只是多幾列，欄位不變。"""
    w = make_wind()
    extra = w.iloc[[2]].copy()
    extra["station"] = "C0V890"
    extra["ws_ms"] = 4.0
    extra["wd_deg"] = 45.0
    f = features.build_features_long(make_timeline(), pd.concat([w, extra], ignore_index=True))
    assert list(f.columns) == features.LONG_COLUMNS
    assert get(f, S1, "wind_speed", "C0V890")["value"].iloc[0] == 4.0


# ---- 模型海流與風 ----

def make_ocean_rows():
    """S2 一列（有值）、S1 一列（速度 0，方向為空）。"""
    return pd.DataFrame([
        {"sensor": "S2", "time_tw": "2023-07-24 10:25:39+08:00", "obs_time_utc": "2023-07-24 02:00:00+00:00",
         "gap_min": -25.65, "current_speed": 0.5, "current_direction_to": 270.0,
         "model_wind_speed": 6.0, "model_wind_direction_from": 135.0},
        {"sensor": "S1", "time_tw": "2023-07-22 06:00:00+08:00", "obs_time_utc": "2023-07-21 22:00:00+00:00",
         "gap_min": 0.0, "current_speed": 0.0, "current_direction_to": np.nan,
         "model_wind_speed": 2.0, "model_wind_direction_from": 0.0},
    ])


def test_ocean_rows_become_four_variables_with_sources_units_and_gap():
    f = features.build_features_long(make_timeline(), make_wind(), make_ocean_rows())
    for variable, source, value, unit in [
            ("current_speed", "cmems_phy_001_024", 0.5, "m/s"),
            ("current_direction_to", "cmems_phy_001_024", 270.0, "deg"),
            ("model_wind_speed", "cmems_wind_012_006", 6.0, "m/s"),
            ("model_wind_direction_from", "cmems_wind_012_006", 135.0, "deg")]:
        r = get(f, S2, variable)
        assert len(r) == 1
        assert r["source"].iloc[0] == source and r["value"].iloc[0] == value
        assert r["unit"].iloc[0] == unit and r["gap_min"].iloc[0] == -25.65


def test_ocean_nan_direction_keeps_row_and_speed_zero_is_not_dropped():
    f = features.build_features_long(make_timeline(), make_wind(), make_ocean_rows())
    d = get(f, S1, "current_direction_to")
    assert len(d) == 1 and np.isnan(d["value"].iloc[0])
    assert get(f, S1, "current_speed")["value"].iloc[0] == 0.0


def test_ocean_is_optional_and_does_not_change_existing_rows():
    base = features.build_features_long(make_timeline(), make_wind())
    with_ocean = features.build_features_long(make_timeline(), make_wind(), make_ocean_rows())
    assert not base["variable"].isin(features.OCEAN_VARIABLES).any()
    kept = with_ocean[~with_ocean["variable"].isin(features.OCEAN_VARIABLES)].reset_index(drop=True)
    pd.testing.assert_frame_equal(kept, base)


def test_ocean_rows_with_unknown_pass_raise():
    o = make_ocean_rows()
    o.loc[0, "time_tw"] = "2023-07-30 10:25:39+08:00"
    with pytest.raises(ValueError, match="模型表"):
        features.build_features_long(make_timeline(), make_wind(), o)


def test_model_wind_does_not_mix_with_station_wind_in_wide_table():
    f = features.build_features_long(make_timeline(), make_wind(), make_ocean_rows())
    w = features.to_wide(f).set_index("pass_id")
    assert w.loc[S2, "wind_speed@C0V690"] == 5.0                  # 測站風仍取最近的整點（+24.35 分比 −25.65 分近）
    assert w.loc[S2, "model_wind_speed@cmems_wind_012_006"] == 6.0
    assert w.loc[S2, "current_direction_to@cmems_phy_001_024"] == 270.0


def test_ocean_variables_are_registered():
    for variable, _ in features.OCEAN_VARIABLES.values():
        assert variable in features.VARIABLES
