"""event.py 的測試，以及「換成虛構事件整條流程仍正確」的測試。自己造資料，不讀 data/。"""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

import features
from catalog import load_items
from drone import daily_summary, haversine_km, load_photos
from event import ANGEL, Event, add_event_args, event_from_args
from timeline import build_timeline, load_passes
from wind import build_wind_at_passes

UTC = ZoneInfo("UTC")


def make_event(**kw):
    base = dict(lat=10.0, lon=-50.0, start=date(2030, 1, 10), end=date(2030, 1, 20))
    return Event(**{**base, **kw})


# ---------- Event 本身 ----------

def test_minimal_event_has_no_time_and_default_tz():
    e = make_event()
    assert e.time is None and e.name == "" and e.tz == "Asia/Taipei"


@pytest.mark.parametrize("kw", [
    {"lat": 91.0}, {"lat": -90.5}, {"lon": 180.5}, {"lon": -181.0},
    {"start": date(2030, 2, 1)},                     # 開始日晚於結束日
    {"time": datetime(2030, 1, 12, 5, 0)},           # 沒有時區
    {"tz": "Nowhere/City"},
    {"start": datetime(2030, 1, 10)},                # 要 date，不是 datetime
])
def test_invalid_event_rejected(kw):
    with pytest.raises(ValueError):
        make_event(**kw)


def test_one_day_period_is_allowed():
    make_event(start=date(2030, 1, 10), end=date(2030, 1, 10))


def test_period_includes_both_end_days_in_event_timezone():
    e = make_event(tz="Asia/Taipei")                 # 1/10 00:00 台灣 = 1/9 16:00 UTC
    assert e.in_period(datetime(2030, 1, 9, 16, 0, tzinfo=UTC))
    assert not e.in_period(datetime(2030, 1, 9, 15, 59, tzinfo=UTC))
    assert e.in_period(datetime(2030, 1, 20, 15, 59, tzinfo=UTC))      # 1/20 最後一分鐘
    assert not e.in_period(datetime(2030, 1, 20, 16, 0, tzinfo=UTC))   # 已是 1/21 台灣時間


def test_period_follows_tz_field():
    e = make_event(tz="UTC")
    assert e.in_period(datetime(2030, 1, 10, 0, 0, tzinfo=UTC))
    assert not e.in_period(datetime(2030, 1, 9, 23, 59, tzinfo=UTC))


def test_angel_default_values():
    assert (ANGEL.lat, ANGEL.lon) == pytest.approx((22.609, 120.20683), abs=1e-4)
    assert ANGEL.time == datetime(2023, 7, 21, 5, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    assert ANGEL.in_period(ANGEL.time)


# ---------- 命令列 ----------

def parse(*argv):
    ap = argparse.ArgumentParser()
    add_event_args(ap)
    return ap, ap.parse_args(list(argv))


def test_cli_no_event_args_means_angel():
    ap, args = parse()
    assert event_from_args(ap, args) is ANGEL


def test_cli_full_event():
    ap, args = parse("--lat", "28.7", "--lon", "-88.4", "--start", "2030-01-10", "--end", "2030-01-20",
                     "--event-time", "2030-01-12 05:00", "--tz", "UTC", "--event-name", "x")
    e = event_from_args(ap, args)
    assert (e.lat, e.lon, e.start, e.end, e.name, e.tz) == (28.7, -88.4, date(2030, 1, 10), date(2030, 1, 20), "x", "UTC")
    assert e.time == datetime(2030, 1, 12, 5, 0, tzinfo=UTC)


def test_cli_event_time_is_optional():
    ap, args = parse("--lat", "1", "--lon", "2", "--start", "2030-01-10", "--end", "2030-01-20")
    assert event_from_args(ap, args).time is None


def test_cli_event_time_uses_tz_argument():
    ap, args = parse("--lat", "1", "--lon", "2", "--start", "2030-01-10", "--end", "2030-01-20",
                     "--event-time", "2030-01-12 08:00")
    assert event_from_args(ap, args).time == datetime(2030, 1, 12, 0, 0, tzinfo=UTC)   # 預設台灣 +8


@pytest.mark.parametrize("argv", [
    ["--lat", "1", "--lon", "2"],                                              # 缺期間
    ["--start", "2030-01-10", "--end", "2030-01-20"],                          # 缺位置
    ["--event-time", "2030-01-12 05:00"],                                      # 只給時間
    ["--lat", "99", "--lon", "2", "--start", "2030-01-10", "--end", "2030-01-20"],       # 緯度不合理
    ["--lat", "1", "--lon", "2", "--start", "2030/01/10", "--end", "2030-01-20"],        # 日期格式錯
    ["--lat", "1", "--lon", "2", "--start", "2030-01-10", "--end", "2030-01-20", "--tz", "Nowhere/City"],
])
def test_cli_incomplete_or_invalid_event_exits_with_error(argv):
    ap, args = parse(*argv)
    with pytest.raises(SystemExit):
        event_from_args(ap, args)


# ---------- 虛構事件：整條流程不能殘留天使輪的值 ----------

EVENT_TIME = datetime(2030, 1, 12, 6, 0, tzinfo=timezone(timedelta(hours=-5)))   # 11:00 UTC


def stac_feature(id_, time, event, **props):
    """涵蓋 event 位置的 0.2 度方塊。"""
    x0, x1, y0, y1 = event.lon - 0.1, event.lon + 0.1, event.lat - 0.1, event.lat + 0.1
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {"id": id_, "bbox": [x0, y0, x1, y1],
            "properties": {"datetime": time, "platform": "sentinel-test", "sat:orbit_state": "descending", **props},
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


def stac_file(tmp_path, name, features_):
    p = tmp_path / name
    p.write_text(json.dumps({"links": [], "features": features_}), encoding="utf-8")
    return str(p)


@pytest.fixture
def other():
    return make_event(lat=28.7, lon=-88.4, time=EVENT_TIME, name="虛構事件", tz="UTC",
                      start=date(2030, 1, 10), end=date(2030, 1, 20))


@pytest.fixture
def stac(tmp_path, other):
    s1 = stac_file(tmp_path, "s1.json", [
        stac_feature("a", "2030-01-12T00:00:00Z", other, **{"sar:instrument_mode": "IW"}),   # 事件前 11 h
        stac_feature("b", "2030-01-13T11:00:00Z", other, **{"sar:instrument_mode": "IW"}),   # 事件後 24 h
        stac_feature("old", "2030-01-02T11:00:00Z", other, **{"sar:instrument_mode": "IW"}), # 期間之前
    ])
    s2 = stac_file(tmp_path, "s2.json", [
        stac_feature("c", "2030-01-14T16:00:00Z", other, **{"grid:code": "T1", "eo:cloud_cover": 10.0}),
    ])
    return s1, s2


def test_items_cover_the_other_event_not_angel(stac, other):
    s1, _ = stac
    assert load_items(s1, other)["covers_wreck"].all()
    assert not load_items(s1)["covers_wreck"].any()          # 預設天使輪：這些影像不涵蓋台灣


def test_timeline_for_other_event_without_drone(stac, other):
    s1, s2 = stac
    tl = build_timeline(load_passes(s1, s2, other), None, event=other)
    assert len(tl) == 3                                       # 期間外那筆被排除
    assert list(tl["hours_since_event"]) == [-11.0, 24.0, 53.0]
    assert tl["covers_wreck"].all()
    assert tl["drone_date"].isna().all() and tl["drone_gap_hours"].isna().all() and tl["drone_n_near"].isna().all()


def test_timeline_empty_drone_table_same_as_none(stac, other):
    s1, s2 = stac
    passes = load_passes(s1, s2, other)
    empty = pd.DataFrame(columns=["date", "start_utc", "end_utc", "n_photos", "n_near"])
    a = build_timeline(passes, None, event=other)
    b = build_timeline(passes, empty, event=other)
    pd.testing.assert_frame_equal(a, b)


def test_timeline_accepts_empty_table_without_columns(stac, other):
    s1, s2 = stac
    tl = build_timeline(load_passes(s1, s2, other), pd.DataFrame(), event=other)
    assert len(tl) == 3 and tl["drone_date"].isna().all()


def test_event_without_time_leaves_hours_empty_and_features_have_no_row(stac, other):
    s1, s2 = stac
    no_time = make_event(lat=other.lat, lon=other.lon, tz="UTC", start=other.start, end=other.end)
    tl = build_timeline(load_passes(s1, s2, no_time), None, event=no_time)
    assert len(tl) == 3
    assert tl["hours_since_event"].isna().all()               # 不是 0
    f = features.build_features_long(tl, pd.DataFrame(columns=["sensor", "time_tw", "station", "gap_min", "ws_ms", "wd_deg"]))
    assert "hours_since_event" not in set(f["variable"])
    assert (f["variable"] == "cloud_cover_min").sum() == 1


def test_drone_distance_uses_the_event_location(tmp_path, other):
    photos = pd.DataFrame({
        "file": ["p1.jpg"], "datetime_original": ["2030:01:12 12:00:00"],
        "lat": [other.lat + 0.045], "lon": [other.lon], "focal_35mm": [24],
    })
    path = tmp_path / "exif.csv"
    photos.to_csv(path, index=False)
    d = load_photos(str(path), other)["dist_km"].iloc[0]
    assert d == pytest.approx(5.0, abs=0.05)                  # 0.045 度緯度約 5 km
    assert load_photos(str(path))["dist_km"].iloc[0] > 1000   # 對天使輪則是地球另一端


def test_drone_pairing_for_other_event(stac, other, tmp_path):
    s1, s2 = stac
    photos = pd.DataFrame({
        "file": [f"p{i}.jpg" for i in range(3)],
        "datetime_original": ["2030:01:13 10:30:00", "2030:01:13 11:00:00", "2030:01:13 11:30:00"],
        "lat": [other.lat] * 3, "lon": [other.lon] * 3, "focal_35mm": [24] * 3,
    })
    path = tmp_path / "exif.csv"
    photos.to_csv(path, index=False)
    days = daily_summary(load_photos(str(path), other))
    tl = build_timeline(load_passes(s1, s2, other), days, event=other)
    paired = tl[tl["drone_date"].notna()]
    assert len(paired) >= 1 and (paired["drone_n_near"] == 3).all()


def test_wind_station_distance_uses_the_event_location(stac, other):
    s1, s2 = stac
    tl = build_timeline(load_passes(s1, s2, other), None, event=other)
    stations = pd.DataFrame([{"code": "X", "name": "x", "lat": other.lat + 0.09, "lon": other.lon}])
    wind = pd.DataFrame({"station": [], "time_utc": pd.to_datetime([], utc=True), "time_tw": pd.to_datetime([], utc=True),
                         "ws_ms": [], "wd_deg": []})
    out = build_wind_at_passes(tl, wind, stations, event=other)
    assert out["dist_km"].iloc[0] == pytest.approx(10.0, abs=0.1)
    far = build_wind_at_passes(tl, wind, stations)             # 預設天使輪
    assert far["dist_km"].iloc[0] > 1000


def test_default_event_still_gives_same_timeline_columns():
    from timeline import TIMELINE_COLUMNS
    tl = build_timeline(pd.DataFrame([{
        "sensor": "S1", "time_utc": ANGEL.time.astimezone(UTC), "time_tw": ANGEL.time,
        "orbit_state": "d", "mode": "IW", "covers_wreck": True, "cloud_cover_min": np.nan}]), None)
    assert list(tl.columns) == TIMELINE_COLUMNS
    assert tl["hours_since_event"].iloc[0] == 0.0
