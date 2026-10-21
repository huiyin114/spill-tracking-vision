"""把各張表整理成介面頁要用的一份資料（JSON）。頁面本身只負責畫，資料處理都在這裡。

輸入（都是前幾個階段的輸出）：過境表、長格式特徵表、對應好的參考觀測、逐時風、測站清單、
無人機每日摘要（選填），再加上事件參數。
輸出的規則：
  - 時間一律是 UTC 的毫秒時間戳（頁面再依 event.tz 顯示），避免這裡先格式化成字串。
  - 空值（NaN）一律變成 null，輸出的 JSON 不含 NaN。
  - 風：每次過境、每個測站保留所有筆（Sentinel-2 夾在兩個整點之間就是兩筆），各自附 gap_min，不替使用者挑。
  - 逐時風只留分析期間內的，頁面才不會載入不相關的資料。

用法：python page_data.py --data data --out site/page_data.json
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

from drone import daily_summary, haversine_km, load_photos
from event import ANGEL, add_event_args, event_from_args


def _clean(v):
    """pandas／numpy 的值轉成 JSON 能放的 Python 值；空值是 None。"""
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _ms(t):
    """時間（要帶時區）轉成 UTC 毫秒時間戳；空值回傳 None。"""
    if t is None or pd.isna(t):
        return None
    t = pd.Timestamp(t)
    if t.tzinfo is None:
        raise ValueError("時間必須帶時區")
    return int(t.tz_convert("UTC").value // 10**6)


def _event_dict(event):
    a, b = event.period_utc()
    return {"name": event.name, "period": [_ms(a), _ms(b)], "lat": event.lat, "lon": event.lon, "tz": event.tz,
            "time": None if event.time is None else _ms(event.time),
            "start": event.start.isoformat(), "end": event.end.isoformat()}


def _single(features, variable, source=None):
    """某變數每次過境一個值的 Series（index = pass_id）。同一過境有多筆時報錯，不默默挑一筆。"""
    f = features[features["variable"] == variable]
    if source is not None:
        f = f[f["source"] == source]
    if f["pass_id"].duplicated().any():
        raise ValueError(f"{variable} 在同一次過境有多筆，這裡只接受一筆")
    return f.set_index("pass_id")["value"]


def _wind_by_pass(features):
    """{pass_id: [{station, gap_min, ws, wd}, ...]}，速度與風向用 (過境, 測站, 時間差) 對起來。"""
    ws = features[features["variable"] == "wind_speed"][["pass_id", "source", "gap_min", "value"]]
    wd = features[features["variable"] == "wind_direction"][["pass_id", "source", "gap_min", "value"]]
    key = ["pass_id", "source", "gap_min"]
    for name, t in (("風速", ws), ("風向", wd)):
        if t.duplicated(key).any():
            raise ValueError(f"{name}有重複的 (過境, 測站, 時間差)")
    # gap_min 可能是空值（NaN 不會自己對上），先換成不可能出現的數字再合併
    ws, wd = ws.assign(_g=ws["gap_min"].fillna(1e9)), wd.assign(_g=wd["gap_min"].fillna(1e9))
    m = ws.merge(wd[["pass_id", "source", "_g", "value"]], on=["pass_id", "source", "_g"],
                 how="outer", suffixes=("_ws", "_wd"))
    m["gap_min"] = m["_g"].where(m["_g"] != 1e9)
    out = {}
    for _, r in m.sort_values(["pass_id", "source", "_g"]).iterrows():
        out.setdefault(r["pass_id"], []).append({
            "station": r["source"], "gap_min": _clean(r["gap_min"]),
            "ws": _clean(r["value_ws"]), "wd": _clean(r["value_wd"])})
    return out


def build_page_data(event, passes, features, reference, wind_hourly, stations, drone_days=None):
    """整理成可直接 json.dumps 的 dict。"""
    ev = _single(features, "hours_since_event", "event")
    cloud = _single(features, "cloud_cover_min", "stac")
    drone_gap = _single(features, "drone_gap_hours", "drone")
    drone_n = _single(features, "drone_n_near", "drone")
    wind = _wind_by_pass(features)

    known = set(passes["pass_id"])
    stray = set(features["pass_id"]) - known
    if stray:
        raise ValueError(f"特徵表裡有不在過境表的過境：{sorted(stray)[:3]}")

    plist = []
    for _, p in passes.sort_values("time_utc").iterrows():
        pid = p["pass_id"]
        plist.append({
            "pass_id": pid, "sensor": p["sensor"], "time": _ms(pd.to_datetime(p["time_utc"], utc=True)),
            "covers": bool(p["covers_wreck"]), "orbit": _clean(p["orbit_state"]), "mode": _clean(p["mode"]),
            "hours_since_event": _clean(ev.get(pid)), "cloud": _clean(cloud.get(pid)),
            "drone_date": _clean(p["drone_date"]), "drone_gap_hours": _clean(drone_gap.get(pid)),
            "drone_n_near": _clean(drone_n.get(pid)), "wind": wind.get(pid, []),
        })

    st = []
    for _, s in stations.iterrows():
        st.append({"code": s["code"], "name": s["name"], "lat": float(s["lat"]), "lon": float(s["lon"]),
                   "dist_km": round(float(haversine_km(s["lat"], s["lon"], event.lat, event.lon)), 1)})

    hourly = {}
    for code, g in wind_hourly.groupby("station"):
        t = pd.to_datetime(g["time_utc"], utc=True)
        keep = [event.in_period(x.to_pydatetime()) for x in t]
        g, t = g[keep], t[keep]
        hourly[code] = [[_ms(a), _clean(b), _clean(c)] for a, b, c in zip(t, g["ws_ms"], g["wd_deg"])]

    refs = []
    for _, r in reference.iterrows():
        refs.append({"ref_id": r["ref_id"], "sensor": r["sensor"], "date": r["date"], "variable": r["variable"],
                     "value": _clean(r["value"]), "unit": r["unit"], "source": r["source"], "note": _clean(r["note"]),
                     "pass_id": _clean(r["pass_id"]), "match": r["match"]})

    days = []
    if drone_days is not None:
        for _, d in drone_days.iterrows():
            days.append({"date": d["date"], "start": _ms(d["start_utc"]), "end": _ms(d["end_utc"]),
                         "n_photos": int(d["n_photos"]), "n_near": int(d["n_near"])})

    return {"event": _event_dict(event), "passes": plist, "stations": st, "wind_hourly": hourly,
            "reference": refs, "drone_days": days}


def to_json(data):
    """轉成 JSON 文字；含 NaN 會直接報錯（頁面的 JSON.parse 讀不了 NaN）。"""
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def load_data(data_dir, event=ANGEL):
    """從 data/ 讀齊所有輸入並整理。沒有無人機檔就不放無人機資料。"""
    def read(name):
        return pd.read_csv(os.path.join(data_dir, name), encoding="utf-8-sig")
    drone_path = os.path.join(data_dir, "drone", "angel_drone_exif.csv")
    days = daily_summary(load_photos(drone_path, event)) if os.path.exists(drone_path) else None
    return build_page_data(event, read("passes.csv"), read("features_long.csv"), read("reference_matched.csv"),
                           read("wind_hourly.csv"), read("stations.csv"), days)


def main():
    ap = argparse.ArgumentParser(description="整理介面頁要用的資料")
    ap.add_argument("--data", default="data", help="放各階段輸出的資料夾")
    ap.add_argument("--out", required=True, help="輸出 JSON 路徑")
    add_event_args(ap)
    args = ap.parse_args()
    data = load_data(args.data, event_from_args(ap, args))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(to_json(data))
    print(f"{len(data['passes'])} 次過境、{len(data['stations'])} 個測站、"
          f"{sum(len(v) for v in data['wind_hourly'].values())} 筆逐時風、{len(data['reference'])} 筆參考觀測 → {args.out}")


if __name__ == "__main__":
    main()
