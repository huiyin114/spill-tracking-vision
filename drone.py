"""讀取無人機照片的 EXIF 清單，整理成「每天一列」的摘要。

清單由 extract_drone_exif.py 在 NAS 的影像上產生（data/drone/angel_drone_exif.csv）。
用法：python drone.py data/drone/angel_drone_exif.csv
"""
import sys

import numpy as np
import pandas as pd

from event import TAIWAN, WRECK_LAT, WRECK_LON

EARTH_RADIUS_KM = 6371.0088

# 離沉船多近算「拍在沉船附近」（公里）。依本批資料訂定：7/20–7/26 每天的中位距離都在
# 0.5 km 內，而 7/30 最近的一張也要 1.5 km，所以 1 km 剛好能把 7/30 分出來。
NEAR_KM = 1.0

# 等效焦距（35 mm 換算）達此值以上視為長焦。24、28 mm 是廣角；本批的長焦多為 161 mm。
TELEPHOTO_35MM = 70


def haversine_km(lat1, lon1, lat2, lon2):
    """兩點的大圓距離（公里）。可傳入數字或 pandas Series；有缺值的結果是 NaN。"""
    lat1, lon1, lat2, lon2 = (np.radians(v) for v in (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def load_photos(path):
    """讀 EXIF 清單，一張照片一列，依拍攝時間排序。

    EXIF 時間沒有時區標記，經資料提供者確認為台灣當地時間，所以先標成台灣時間，
    再換算成 UTC（衛星時間是 UTC）。並加上離沉船的距離 dist_km。
    """
    photos = pd.read_csv(path, encoding="utf-8-sig")

    taken = pd.to_datetime(photos["datetime_original"], format="%Y:%m:%d %H:%M:%S", errors="coerce")
    if taken.isna().any():
        raise ValueError(f"{path} 有 {int(taken.isna().sum())} 張照片的拍攝時間無法解讀")

    photos["time_tw"] = taken.dt.tz_localize(TAIWAN)
    photos["time_utc"] = photos["time_tw"].dt.tz_convert("UTC")
    photos["date_tw"] = photos["time_tw"].dt.strftime("%Y-%m-%d")
    photos["dist_km"] = haversine_km(photos["lat"], photos["lon"], WRECK_LAT, WRECK_LON)
    return photos.sort_values("time_tw").reset_index(drop=True)


def daily_summary(photos, near_km=NEAR_KM):
    """每天一列：張數、拍攝時段（台灣時間與 UTC）、離沉船的距離、近距離與長焦張數。"""
    days = photos.groupby("date_tw").agg(
        n_photos=("file", "count"),
        start_tw=("time_tw", "min"),
        end_tw=("time_tw", "max"),
        start_utc=("time_utc", "min"),
        end_utc=("time_utc", "max"),
        median_dist_km=("dist_km", "median"),
        max_dist_km=("dist_km", "max"),
        n_near=("dist_km", lambda s: int((s <= near_km).sum())),
        n_telephoto=("focal_35mm", lambda s: int((s >= TELEPHOTO_35MM).sum())),
    ).reset_index()
    return days.rename(columns={"date_tw": "date"})


if __name__ == "__main__":
    summary = daily_summary(load_photos(sys.argv[1]))
    print(f"{summary['n_photos'].sum()} 張照片，{len(summary)} 天")
    print(summary.drop(columns=["start_utc", "end_utc"]).round(2).to_string(index=False))
