"""drone.py 的單元測試。用法：pytest

測試資料全部在這裡自己造，不讀 data/drone/ 的真實清單。
"""
import math

import pandas as pd
import pytest

from drone import NEAR_KM, daily_summary, haversine_km, load_photos
from event import WRECK_LAT, WRECK_LON

KM_PER_DEG_LAT = 2 * math.pi * 6371.0088 / 360  # 緯度 1 度約 111.2 km


# ---------- 造測試資料的小工具 ----------

def photo(time, km=0.0, focal=24):
    """一張照片：拍攝時間（EXIF 格式）、在沉船正北方 km 公里處、等效焦距。"""
    return {
        "datetime_original": time,
        "lat": WRECK_LAT + km / KM_PER_DEG_LAT,
        "lon": WRECK_LON,
        "focal_35mm": focal,
    }


def load(tmp_path, photos):
    df = pd.DataFrame(photos)
    df.insert(0, "file", [f"p{i}.jpg" for i in range(len(df))])
    path = tmp_path / "photos.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return load_photos(path)


# ---------- haversine_km ----------

def test_haversine_same_point_is_zero():
    assert haversine_km(22.6, 120.2, 22.6, 120.2) == pytest.approx(0.0)


def test_haversine_one_degree_of_latitude():
    assert haversine_km(22.0, 120.0, 23.0, 120.0) == pytest.approx(111.2, rel=1e-3)


def test_haversine_one_degree_of_longitude_is_shorter_at_this_latitude():
    expected = 111.2 * math.cos(math.radians(22.6))  # 經度 1 度的長度隨緯度縮短
    assert haversine_km(22.6, 120.0, 22.6, 121.0) == pytest.approx(expected, rel=1e-3)


# ---------- load_photos ----------

def test_exif_time_is_taiwan_time(tmp_path):
    photos = load(tmp_path, [photo("2023:07:24 07:36:40")])
    row = photos.iloc[0]
    assert row["time_utc"] == pd.Timestamp("2023-07-23 23:36:40", tz="UTC")
    assert row["time_tw"].utcoffset() == pd.Timedelta(hours=8)


def test_unparseable_time_raises(tmp_path):
    with pytest.raises(ValueError, match="無法解讀"):
        load(tmp_path, [photo("not a time")])


def test_photos_sorted_by_time(tmp_path):
    photos = load(tmp_path, [photo("2023:07:25 06:00:00"), photo("2023:07:24 06:00:00")])
    assert list(photos["date_tw"]) == ["2023-07-24", "2023-07-25"]


def test_distance_is_measured_from_the_wreck(tmp_path):
    photos = load(tmp_path, [photo("2023:07:24 07:00:00", km=0.0), photo("2023:07:24 07:01:00", km=2.0)])
    assert photos.loc[0, "dist_km"] == pytest.approx(0.0, abs=1e-6)
    assert photos.loc[1, "dist_km"] == pytest.approx(2.0, rel=1e-3)


# ---------- daily_summary ----------

def test_summary_groups_by_taiwan_date_not_utc_date(tmp_path):
    # 台灣 07:36 是 UTC 前一天 23:36；台灣 20:00 是 UTC 同一天 12:00。
    # 兩張的 UTC 日期不同，但台灣日期相同，要算同一天。
    photos = load(tmp_path, [photo("2023:07:24 07:36:40"), photo("2023:07:24 20:00:00")])
    summary = daily_summary(photos)
    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["date"] == "2023-07-24"
    assert row["n_photos"] == 2
    assert (row["start_tw"].hour, row["end_tw"].hour) == (7, 20)
    assert row["start_utc"].day == 23 and row["end_utc"].day == 24


def test_summary_one_row_per_day(tmp_path):
    photos = load(tmp_path, [photo("2023:07:24 07:00:00"), photo("2023:07:24 07:05:00"),
                             photo("2023:07:25 06:00:00")])
    summary = daily_summary(photos)
    assert list(summary["date"]) == ["2023-07-24", "2023-07-25"]
    assert list(summary["n_photos"]) == [2, 1]


def test_summary_median_and_max_distance(tmp_path):
    photos = load(tmp_path, [photo("2023:07:24 07:00:00", km=0.2),
                             photo("2023:07:24 07:01:00", km=0.4),
                             photo("2023:07:24 07:02:00", km=3.0)])
    row = daily_summary(photos).iloc[0]
    assert row["median_dist_km"] == pytest.approx(0.4, rel=1e-3)
    assert row["max_dist_km"] == pytest.approx(3.0, rel=1e-3)


def test_n_near_uses_threshold(tmp_path):
    photos = load(tmp_path, [photo("2023:07:24 07:00:00", km=NEAR_KM * 0.5),
                             photo("2023:07:24 07:01:00", km=NEAR_KM * 1.5)])
    assert daily_summary(photos).iloc[0]["n_near"] == 1                  # 預設門檻
    assert daily_summary(photos, near_km=NEAR_KM * 2).iloc[0]["n_near"] == 2  # 放寬後


def test_n_telephoto_counts_from_70mm(tmp_path):
    photos = load(tmp_path, [photo("2023:07:24 07:00:00", focal=f) for f in (24, 28, 69, 70, 161)])
    assert daily_summary(photos).iloc[0]["n_telephoto"] == 2  # 70 與 161


def test_missing_gps_does_not_crash_and_is_not_near(tmp_path):
    no_gps = photo("2023:07:24 07:00:00")
    no_gps["lat"] = float("nan")
    photos = load(tmp_path, [no_gps, photo("2023:07:24 07:01:00", km=0.1)])
    row = daily_summary(photos).iloc[0]
    assert row["n_photos"] == 2
    assert row["n_near"] == 1
