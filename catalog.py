"""讀取 Copernicus STAC 搜尋結果，整理成「一個影像一列」的表格。

用法：python catalog.py data/raw/stac_s1.json
"""
import json
import sys

import pandas as pd


def load_items(path):
    """讀 STAC JSON，回傳 DataFrame（一個 item 一列，依時間排序）。"""
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
        })

    df = pd.DataFrame(rows)
    return df.sort_values("time_utc").reset_index(drop=True)


def group_passes(items, gap_minutes=10):
    """把同一次過境被切成的多筆影像合併，回傳「一次過境一列」。"""
    items = items.sort_values("time_utc").reset_index(drop=True)

    # 與前一筆相隔超過 gap_minutes，就算新的一次過境
    new_pass = items["time_utc"].diff() > pd.Timedelta(minutes=gap_minutes)
    items["pass_id"] = new_pass.cumsum()

    passes = items.groupby("pass_id").agg(
        platform=("platform", "first"),
        time_utc=("time_utc", "min"),
        orbit_state=("orbit_state", "first"),
        mode=("mode", "first"),
        n_items=("id", "count"),
        tiles=("tile", lambda s: ";".join(sorted(s.dropna()))),
    ).reset_index()
    passes["time_tw"] = passes["time_utc"].dt.tz_convert("Asia/Taipei")
    return passes


if __name__ == "__main__":
    items = load_items(sys.argv[1])
    passes = group_passes(items)
    print(f"{len(items)} 筆影像 → {len(passes)} 次過境")
    print(passes.drop(columns=["time_utc"]).to_string())

'''
逐段說明
json.load：把檔案裡的 JSON 文字變成 Python 能操作的資料，就是我們在小段 A 看到的那個結構。
next 連結檢查：依據我們核對過的 STAC 規範，有 next 就是還有下一頁。我們兩份檔案都沒有，但之後如果換成範圍更大的查詢，這個檢查可以避免你誤把不完整的結果當成全部。
for item in data["features"]：每個 feature 就是一景影像，迴圈對每一景挑出需要的欄位，存成一列。
p["platform"] 和 p.get("sar:instrument_mode") 的差別：用方括號，欄位不存在就會報錯；用 .get()，不存在就回傳 None。S1 沒有圖幅和雲量，S2 沒有成像模式，所以這三個欄位要用 .get()，而兩邊都有的欄位用方括號，這樣資料缺了才會馬上被發現。
pd.Timestamp(...)：把 2023-07-19T02:25:39Z 這樣的文字轉成真正的時間物件。結尾的 Z 代表 UTC，所以之後換算成台灣時間、計算兩景相隔幾小時都能直接做。
sort_values 和 reset_index：依時間排序，並重新編號。'''