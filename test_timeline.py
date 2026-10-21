"""timeline.py 的單元測試。用法：pytest

測試資料全部在這裡自己造，不讀 data/ 裡的真實檔案。
"""
import json
from datetime import timedelta

import pandas as pd
import pytest

from event import SINKING_TIME, WRECK_LAT, WRECK_LON
from timeline import build_timeline, gap_hours, load_passes


# ---------- 造測試資料的小工具 ----------

def utc(s):
    """字串（視為 UTC）或已帶時區的時間，統一轉成 UTC 的 Timestamp。"""
    t = pd.Timestamp(s)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def make_pass(time, sensor="S2", covers=True, cloud=float("nan")):
    t = utc(time)
    return {"sensor": sensor, "time_utc": t, "time_tw": t.tz_convert("Asia/Taipei"),
            "orbit_state": "descending", "mode": None, "covers_wreck": covers, "cloud_cover_min": cloud}


def make_day(date, start, end, n_near=10):
    return {"date": date, "start_utc": utc(start), "end_utc": utc(end), "n_photos": n_near, "n_near": n_near}


def days_df(*rows):
    return pd.DataFrame(list(rows), columns=["date", "start_utc", "end_utc", "n_photos", "n_near"])


def timeline(passes, days, **kwargs):
    return build_timeline(pd.DataFrame(passes), days, **kwargs)


# ---------- gap_hours ----------

@pytest.mark.parametrize("t, expected", [
    ("2023-07-24 01:00", 0.0),     # 落在時段內
    ("2023-07-23 22:00", 2.0),     # 衛星早 2 小時：無人機在衛星之後，正值
    ("2023-07-24 05:00", -3.0),    # 衛星晚 3 小時：無人機在衛星之前，負值
])
def test_gap_hours_sign(t, expected):
    assert gap_hours(utc(t), utc("2023-07-24 00:00"), utc("2023-07-24 02:00")) == expected


# ---------- build_timeline ----------

def test_hours_since_event():
    after = pd.Timestamp(SINKING_TIME + timedelta(hours=24.4)).tz_convert("UTC")
    before = pd.Timestamp(SINKING_TIME - timedelta(hours=2)).tz_convert("UTC")
    result = timeline([make_pass(after), make_pass(before)], days_df())
    assert list(result["hours_since_event"]) == [-2.0, 24.4]


def test_pairs_with_same_day_drone():
    # 無人機台灣時間 7/24 07:36–07:45 = UTC 7/23 23:36–23:45；衛星 UTC 7/24 02:25:41
    day = make_day("2023-07-24", "2023-07-23 23:36:40", "2023-07-23 23:45:05")
    row = timeline([make_pass("2023-07-24 02:25:41")], days_df(day)).iloc[0]
    assert row["drone_date"] == "2023-07-24"
    assert row["drone_gap_hours"] == pytest.approx(-2.7)
    assert row["drone_n_near"] == 10


def test_pass_inside_drone_session_has_zero_gap():
    day = make_day("2023-07-24", "2023-07-24 00:00", "2023-07-24 05:00")
    row = timeline([make_pass("2023-07-24 02:00")], days_df(day)).iloc[0]
    assert row["drone_gap_hours"] == 0.0


def test_gap_beyond_limit_is_not_paired():
    day = make_day("2023-07-24", "2023-07-23 23:00", "2023-07-24 00:00")
    passes = [make_pass("2023-07-25 06:00")]                      # 衛星晚 30 小時
    assert pd.isna(timeline(passes, days_df(day)).iloc[0]["drone_date"])
    relaxed = timeline(passes, days_df(day), max_gap_hours=48).iloc[0]
    assert relaxed["drone_date"] == "2023-07-24"
    assert relaxed["drone_gap_hours"] == -30.0


def test_limit_is_inclusive():
    day = make_day("2023-07-24", "2023-07-23 23:00", "2023-07-24 00:00")
    exactly = timeline([make_pass("2023-07-25 00:00:00")], days_df(day)).iloc[0]      # 剛好 24 小時
    just_over = timeline([make_pass("2023-07-25 00:00:01")], days_df(day)).iloc[0]    # 多 1 秒
    assert exactly["drone_date"] == "2023-07-24"
    assert pd.isna(just_over["drone_date"])


def test_pass_not_covering_wreck_is_kept_but_not_paired():
    day = make_day("2023-07-24", "2023-07-24 00:00", "2023-07-24 05:00")
    result = timeline([make_pass("2023-07-24 02:00", covers=False)], days_df(day))
    assert len(result) == 1
    assert bool(result.iloc[0]["covers_wreck"]) is False
    assert pd.isna(result.iloc[0]["drone_date"])


def test_days_without_photos_near_the_wreck_are_excluded():
    far = make_day("2023-07-30", "2023-07-24 00:00", "2023-07-24 02:00", n_near=0)    # 衛星落在這天之內
    near = make_day("2023-07-24", "2023-07-24 12:00", "2023-07-24 13:00", n_near=5)
    row = timeline([make_pass("2023-07-24 01:00")], days_df(far, near)).iloc[0]
    assert row["drone_date"] == "2023-07-24"
    assert row["drone_gap_hours"] == 11.0


def test_nearest_day_is_chosen_and_sign_is_kept():
    before = make_day("2023-07-23", "2023-07-23 19:00", "2023-07-23 20:00")   # 衛星前 4 小時
    after = make_day("2023-07-24", "2023-07-24 08:00", "2023-07-24 09:00")    # 衛星後 8 小時
    row = timeline([make_pass("2023-07-24 00:00")], days_df(before, after)).iloc[0]
    assert row["drone_date"] == "2023-07-23"
    assert row["drone_gap_hours"] == -4.0


def test_no_drone_days_does_not_crash():
    result = timeline([make_pass("2023-07-24 02:00")], days_df())
    assert len(result) == 1
    assert pd.isna(result.iloc[0]["drone_date"])


def test_all_passes_kept_and_sorted_by_time():
    result = timeline([make_pass("2023-08-03 02:00"), make_pass("2023-07-22 02:00"),
                       make_pass("2023-07-27 02:00")], days_df())
    assert len(result) == 3
    assert list(result["time_utc"]) == sorted(result["time_utc"])


# ---------- load_passes ----------

def stac_feature(id_, time, **props):
    x0, x1 = WRECK_LON - 0.1, WRECK_LON + 0.1
    y0, y1 = WRECK_LAT - 0.1, WRECK_LAT + 0.1
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {"id": id_, "bbox": [x0, y0, x1, y1],
            "properties": {"datetime": time, "platform": "sentinel-test", "sat:orbit_state": "descending", **props},
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


def stac_file(tmp_path, name, features):
    path = tmp_path / name
    path.write_text(json.dumps({"links": [], "features": features}), encoding="utf-8")
    return str(path)


def test_load_passes_merges_both_sensors_in_time_order(tmp_path):
    s1 = stac_file(tmp_path, "s1.json", [
        stac_feature("a", "2023-07-21T21:53:01Z", **{"sar:instrument_mode": "IW"}),
        stac_feature("b", "2023-07-21T21:53:26Z", **{"sar:instrument_mode": "IW"}),   # 同一次過境
    ])
    s2 = stac_file(tmp_path, "s2.json", [
        stac_feature("c", "2023-07-19T02:25:39Z", **{"grid:code": "MGRS-50QRL", "eo:cloud_cover": 92.0}),
        stac_feature("d", "2023-07-19T02:25:39Z", **{"grid:code": "MGRS-51QTF", "eo:cloud_cover": 94.0}),
    ])
    passes = load_passes(s1, s2)
    assert list(passes["sensor"]) == ["S2", "S1"]              # 7/19 的 S2 早於 7/21 的 S1
    assert passes.iloc[0]["cloud_cover_min"] == 92.0
    assert pd.isna(passes.iloc[1]["cloud_cover_min"])          # S1 沒有雲量
    assert passes.iloc[1]["mode"] == "IW"
    assert passes["covers_wreck"].all()
