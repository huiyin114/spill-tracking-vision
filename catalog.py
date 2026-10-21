"""讀取 Copernicus STAC 搜尋結果，整理成「一個影像一列」的表格。

用法：python catalog.py data/raw/stac_s1.json [--lat ... --lon ... --start ... --end ...]
"""
import argparse
import json

import pandas as pd
from shapely.geometry import Point, shape

from event import ANGEL, add_event_args, event_from_args


def load_items(path, event=ANGEL):
    """讀 STAC JSON，回傳 DataFrame（一個 item 一列，依時間排序）。

    covers_wreck 指影像涵蓋 event 的位置（欄名沿用「沉船」，換事件時指事件位置）。
    """
    # shapely 的座標順序是 (x, y) = (經度, 緯度)，和平常說「緯度、經度」相反
    here = Point(event.lon, event.lat)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # STAC 規範：有 next 連結代表還有下一頁，結果不完整
    for link in data.get("links", []):
        if link.get("rel") == "next":
            raise ValueError(f"{path} 只有第一頁，結果不完整")

    rows = []
    for item in data["features"]:
        p = item["properties"]
        rows.append({
            "id": item["id"],
            "platform": p["platform"],
            "time_utc": pd.Timestamp(p["datetime"]),
            "orbit_state": p["sat:orbit_state"],
            "mode": p.get("sar:instrument_mode"),    # 只有 Sentinel-1 有
            "tile": p.get("grid:code"),              # 只有 Sentinel-2 有
            "cloud_cover": p.get("eo:cloud_cover"),  # 只有 Sentinel-2 有
            "bbox": item["bbox"],
            # 影像實際涵蓋範圍（多邊形）是否包含沉船；bbox 只是外框，不能拿來判斷
            "covers_wreck": shape(item["geometry"]).contains(here),
        })

    df = pd.DataFrame(rows)
    return df.sort_values("time_utc").reset_index(drop=True)


def group_passes(items, gap_minutes=10):
    """把同一次過境被切成的多筆影像合併，回傳「一次過境一列」。"""
    items = items.sort_values("time_utc").reset_index(drop=True)

    # 與前一筆相隔超過 gap_minutes，就算新的一次過境
    new_pass = items["time_utc"].diff() > pd.Timedelta(minutes=gap_minutes)
    items["pass_id"] = new_pass.cumsum()

    # 只看涵蓋沉船的影像的雲量（Sentinel-2 為整個圖幅的平均，不是沉船處）
    items["cloud_at_wreck"] = items["cloud_cover"].where(items["covers_wreck"])

    passes = items.groupby("pass_id").agg(
        platform=("platform", "first"),
        time_utc=("time_utc", "min"),
        orbit_state=("orbit_state", "first"),
        mode=("mode", "first"),
        n_items=("id", "count"),
        covers_wreck=("covers_wreck", "any"),
        cloud_cover_min=("cloud_at_wreck", "min"),
        tiles=("tile", lambda s: ";".join(sorted(s.dropna()))),
    ).reset_index()
    passes["time_tw"] = passes["time_utc"].dt.tz_convert("Asia/Taipei")
    return passes


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="STAC 搜尋結果整理成每次過境一列")
    ap.add_argument("stac_json", help="STAC 搜尋結果 JSON")
    add_event_args(ap)
    args = ap.parse_args()
    items = load_items(args.stac_json, event_from_args(ap, args))
    passes = group_passes(items)
    print(f"{len(items)} 筆影像 → {len(passes)} 次過境")
    print(passes.drop(columns=["time_utc"]).to_string())
