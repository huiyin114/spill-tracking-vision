"""page_data.py 的測試：自己造資料，不讀 data/。"""
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

import page_data
from event import Event

TW = ZoneInfo("Asia/Taipei")
S2 = "S2_20230724T022541Z"
S1 = "S1_20230726T220124Z"


def make_event(**kw):
    base = dict(lat=22.6, lon=120.2, start=date(2023, 7, 20), end=date(2023, 7, 28),
                time=datetime(2023, 7, 21, 5, 30, tzinfo=TW), name="測試事件")
    return Event(**{**base, **kw})


def passes():
    return pd.DataFrame([
        {"pass_id": S1, "sensor": "S1", "time_utc": "2023-07-26 22:01:24+00:00", "covers_wreck": True,
         "orbit_state": "descending", "mode": "IW", "drone_date": np.nan},
        {"pass_id": S2, "sensor": "S2", "time_utc": "2023-07-24 02:25:41+00:00", "covers_wreck": True,
         "orbit_state": "descending", "mode": np.nan, "drone_date": "2023-07-25"},
    ])


def feat(pid, variable, source, value, gap=np.nan):
    return {"pass_id": pid, "variable": variable, "source": source, "value": value, "unit": "x", "gap_min": gap}


def features():
    return pd.DataFrame([
        feat(S2, "hours_since_event", "event", 77.0), feat(S1, "hours_since_event", "event", 160.5),
        feat(S2, "cloud_cover_min", "stac", 48.4),
        feat(S2, "drone_gap_hours", "drone", 20.0), feat(S2, "drone_n_near", "drone", 8.0),
        feat(S2, "wind_speed", "A", 3.0, -25.7), feat(S2, "wind_direction", "A", 90.0, -25.7),
        feat(S2, "wind_speed", "A", 5.0, 24.3), feat(S2, "wind_direction", "A", np.nan, 24.3),
        feat(S1, "wind_speed", "A", np.nan, 0.0), feat(S1, "wind_direction", "A", np.nan, 0.0),
    ])


def reference():
    return pd.DataFrame([
        {"ref_id": "r1", "sensor": "S2", "date": "2023-07-24", "variable": "oil_area", "value": 20.3, "unit": "km2",
         "source": "文獻", "note": "估計", "pass_id": S2, "pass_time_tw": "x", "match": "matched"},
        {"ref_id": "r2", "sensor": "S1", "date": "2023-08-01", "variable": "oil_area", "value": 1.0, "unit": "km2",
         "source": "文獻", "note": np.nan, "pass_id": np.nan, "pass_time_tw": np.nan, "match": "no_pass"},
    ])


def hourly():
    t = pd.date_range("2023-07-19 00:00", "2023-07-30 00:00", freq="6h", tz="UTC")
    return pd.DataFrame({"station": "A", "time_utc": t.astype(str), "ws_ms": 2.0, "wd_deg": 90.0})


def stations():
    return pd.DataFrame([{"code": "A", "name": "甲", "lat": 22.6 + 0.09, "lon": 120.2}])


def drone_days():
    return pd.DataFrame([{"date": "2023-07-25", "start_utc": pd.Timestamp("2023-07-25 01:00", tz="UTC"),
                          "end_utc": pd.Timestamp("2023-07-25 03:00", tz="UTC"), "n_photos": 12, "n_near": 8}])


def build(**over):
    args = dict(event=make_event(), passes=passes(), features=features(), reference=reference(),
                wind_hourly=hourly(), stations=stations(), drone_days=drone_days())
    return page_data.build_page_data(**{**args, **over})


def by_id(d, pid):
    return next(p for p in d["passes"] if p["pass_id"] == pid)


def test_output_is_valid_json_without_nan():
    text = page_data.to_json(build())
    assert "NaN" not in text and json.loads(text)["event"]["name"] == "測試事件"


def test_to_json_rejects_nan():
    with pytest.raises(ValueError):
        page_data.to_json({"x": float("nan")})


def test_passes_sorted_by_time():
    assert [p["pass_id"] for p in build()["passes"]] == [S2, S1]


def test_time_is_utc_milliseconds():
    p = by_id(build(), S2)
    assert p["time"] == int(pd.Timestamp("2023-07-24 02:25:41", tz="UTC").timestamp() * 1000)


def test_pass_values_land_on_the_right_pass():
    d = build()
    p2, p1 = by_id(d, S2), by_id(d, S1)
    assert (p2["hours_since_event"], p2["cloud"], p2["drone_gap_hours"], p2["drone_n_near"]) == (77.0, 48.4, 20.0, 8.0)
    assert p2["drone_date"] == "2023-07-25"
    assert p1["hours_since_event"] == 160.5


def test_not_applicable_values_are_null_not_zero():
    p1 = by_id(build(), S1)
    assert p1["cloud"] is None and p1["drone_gap_hours"] is None and p1["drone_n_near"] is None
    assert p1["drone_date"] is None and p1["mode"] == "IW"
    assert by_id(build(), S2)["mode"] is None


def test_both_wind_rows_kept_with_own_gap():
    w = by_id(build(), S2)["wind"]
    assert [(r["gap_min"], r["ws"], r["wd"]) for r in w] == [(-25.7, 3.0, 90.0), (24.3, 5.0, None)]


def test_missing_wind_stays_null():
    w = by_id(build(), S1)["wind"]
    assert w == [{"station": "A", "gap_min": 0.0, "ws": None, "wd": None}]


def test_pass_without_wind_has_empty_list():
    f = features()
    f = f[~f["variable"].str.startswith("wind")]
    assert by_id(build(features=f), S2)["wind"] == []


def test_event_without_time_gives_null_time_and_hours():
    f = features()
    f = f[f["variable"] != "hours_since_event"]
    d = build(event=make_event(time=None), features=f)
    assert d["event"]["time"] is None and by_id(d, S2)["hours_since_event"] is None


def test_event_fields():
    e = build()["event"]
    assert (e["lat"], e["lon"], e["tz"], e["start"], e["end"]) == (22.6, 120.2, "Asia/Taipei", "2023-07-20", "2023-07-28")
    assert e["time"] == int(datetime(2023, 7, 21, 5, 30, tzinfo=TW).timestamp() * 1000)


def test_hourly_wind_trimmed_to_period():
    rows = build()["wind_hourly"]["A"]
    ms = [r[0] for r in rows]
    a, b = make_event().period_utc()
    assert min(ms) >= int(a.timestamp() * 1000) and max(ms) < int(b.timestamp() * 1000)
    assert len(rows) < len(hourly())


def test_hourly_wind_values_kept():
    assert all(r[1] == 2.0 and r[2] == 90.0 for r in build()["wind_hourly"]["A"])


def test_station_distance_from_event():
    assert build()["stations"][0]["dist_km"] == pytest.approx(10.0, abs=0.1)


def test_reference_rows():
    r = build()["reference"]
    assert r[0]["pass_id"] == S2 and r[0]["value"] == 20.3 and r[0]["match"] == "matched"
    assert r[1]["pass_id"] is None and r[1]["note"] is None and r[1]["match"] == "no_pass"


def test_drone_days_optional():
    assert build(drone_days=None)["drone_days"] == []
    d = build()["drone_days"][0]
    assert d["date"] == "2023-07-25" and d["n_photos"] == 12 and d["n_near"] == 8
    assert d["start"] < d["end"]


def test_no_wind_at_all_is_fine():
    f = features()
    f = f[~f["variable"].str.startswith("wind")]
    d = build(features=f, wind_hourly=hourly().iloc[0:0], stations=stations().iloc[0:0])
    assert d["wind_hourly"] == {} and d["stations"] == []


def test_feature_pass_missing_from_passes_is_rejected():
    f = pd.concat([features(), pd.DataFrame([feat("S2_unknown", "cloud_cover_min", "stac", 1.0)])], ignore_index=True)
    with pytest.raises(ValueError, match="不在過境表"):
        build(features=f)


def test_two_values_for_a_single_value_variable_rejected():
    f = pd.concat([features(), pd.DataFrame([feat(S2, "cloud_cover_min", "stac", 2.0)])], ignore_index=True)
    with pytest.raises(ValueError, match="多筆"):
        build(features=f)


def test_duplicate_wind_rows_rejected():
    f = pd.concat([features(), features().iloc[[5]]], ignore_index=True)
    with pytest.raises(ValueError, match="重複"):
        build(features=f)


def test_speed_and_direction_pair_by_gap_not_by_position():
    f = features().iloc[::-1]          # 順序顛倒也要對得起來
    w = by_id(build(features=f), S2)["wind"]
    assert [(r["gap_min"], r["ws"], r["wd"]) for r in w] == [(-25.7, 3.0, 90.0), (24.3, 5.0, None)]


def test_naive_time_rejected():
    with pytest.raises(ValueError):
        page_data._ms(pd.Timestamp("2023-07-24 02:00"))


def test_hourly_boundary_start_included_end_excluded():
    a, b = make_event().period_utc()
    t = [a - pd.Timedelta(minutes=1), a, b - pd.Timedelta(minutes=1), b]
    h = pd.DataFrame({"station": "A", "time_utc": [x.isoformat() for x in t], "ws_ms": 1.0, "wd_deg": 1.0})
    ms = [r[0] for r in build(wind_hourly=h)["wind_hourly"]["A"]]
    assert ms == [int(a.timestamp() * 1000), int((b - pd.Timedelta(minutes=1)).timestamp() * 1000)]


def test_wind_row_with_only_speed_keeps_its_gap():
    f = features()
    f = f[~((f["pass_id"] == S2) & (f["variable"] == "wind_direction") & (f["gap_min"] == 24.3))]
    w = by_id(build(features=f), S2)["wind"]
    assert [(r["gap_min"], r["ws"], r["wd"]) for r in w] == [(-25.7, 3.0, 90.0), (24.3, 5.0, None)]


def test_wind_row_with_only_direction_keeps_its_gap():
    f = features()
    f = f[~((f["pass_id"] == S2) & (f["variable"] == "wind_speed") & (f["gap_min"] == -25.7))]
    w = by_id(build(features=f), S2)["wind"]
    assert [(r["gap_min"], r["ws"], r["wd"]) for r in w] == [(-25.7, None, 90.0), (24.3, 5.0, None)]


def test_covers_flag_follows_the_pass():
    p = passes()
    p.loc[p["pass_id"] == S1, "covers_wreck"] = False
    d = build(passes=p)
    assert by_id(d, S1)["covers"] is False and by_id(d, S2)["covers"] is True


def test_event_period_is_utc_milliseconds_start_inclusive_end_exclusive():
    a, b = make_event().period_utc()
    assert build()["event"]["period"] == [int(a.timestamp() * 1000), int(b.timestamp() * 1000)]
    assert build()["event"]["period"][1] - build()["event"]["period"][0] == 9 * 86400 * 1000   # 7/20–7/28 共 9 天
