"""漂移模擬的圖：每個文獻對應過境一張靜態圖，加上一段動畫（GIF）。

輸入是 drift_sim.py 的粒子表；文獻方向與最遠距離來自 drift_compare.compare_runs。
在 opendrift 環境執行（需要 matplotlib 與 roaring_landmask，OpenDrift 都已經裝了）。
陸地用 OpenDrift 擱淺判斷所用的同一份陸地遮罩（roaring_landmask）畫出，不需要另外下載底圖。
圖上的文字用英文，避免字型問題。

圖的內容：
  - 靜態圖：每個模擬一格，畫該過境時刻最近一次輸出的粒子位置（active 與 stranded 不同顏色）、
    重心與重心從釋放到該時刻的軌跡、沉船位置、25／50／100 km 距離圈、
    文獻方向（東南，只表示方向，箭頭長度沒有意義）、文獻最遠距離圈（有的話）。
  - 動畫：兩個（或多個）模擬並排，從釋放到結束，預設每 3 小時一格。

這只是把模擬與文獻並列，不是驗證。

用法（在 opendrift 環境）：
  python drift_plot.py --particles base=data/drift_particles_base.csv wind002=data/drift_particles_wind002.csv \
      --matched data/reference_matched.csv --passes data/passes.csv --out-dir figures --animation
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from drift_compare import (COMPASS_CENTER, STATUS_STRANDED, compare_runs, load_particles, nearest_output_time)
from drone import EARTH_RADIUS_KM
from event import ANGEL

RINGS_KM = (25, 50, 100)
LAND_RES_DEG = 0.01


# ---- 純計算（有單元測試） ----

def destination(lat, lon, bearing_deg, distance_km):
    """從 (lat, lon) 朝方位 bearing_deg（0 為北、順時針）走 distance_km 後的 (lat, lon)（大圓）。"""
    d = np.asarray(distance_km, dtype=float) / EARTH_RADIUS_KM
    b = np.radians(np.asarray(bearing_deg, dtype=float))
    p1, l1 = np.radians(lat), np.radians(lon)
    p2 = np.arcsin(np.sin(p1) * np.cos(d) + np.cos(p1) * np.sin(d) * np.cos(b))
    l2 = l1 + np.arctan2(np.sin(b) * np.sin(d) * np.cos(p1), np.cos(d) - np.sin(p1) * np.sin(p2))
    return np.degrees(p2), np.degrees(l2)


def circle_points(lat, lon, radius_km, n=181):
    """以 (lat, lon) 為圓心、半徑 radius_km 的圓上 n 個點（頭尾相接），回傳 (lats, lons)。"""
    return destination(lat, lon, np.linspace(0.0, 360.0, n), radius_km)


def map_extent(lons, lats, pad_deg=0.3):
    """包住所有有限數值的範圍 (lon_min, lon_max, lat_min, lat_max)，四邊各加 pad_deg。沒有有限值就報錯。"""
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    ok = np.isfinite(lons) & np.isfinite(lats)
    if not ok.any():
        raise ValueError("沒有任何有位置的點，無法決定地圖範圍")
    return (lons[ok].min() - pad_deg, lons[ok].max() + pad_deg, lats[ok].min() - pad_deg, lats[ok].max() + pad_deg)


def squarish_extent(extent, lat0, max_ratio=1.25):
    """把範圍的短邊（以公里計）往兩側加寬，讓寬高比不超過 max_ratio，避免圖太窄長。"""
    lon_min, lon_max, lat_min, lat_max = extent
    w = (lon_max - lon_min) * np.cos(np.radians(lat0))      # 以緯度 1 度為單位的東西向長度
    h = lat_max - lat_min
    if w < h / max_ratio:
        need = (h / max_ratio - w) / np.cos(np.radians(lat0))
        lon_min, lon_max = lon_min - need / 2, lon_max + need / 2
    elif h < w / max_ratio:
        need = w / max_ratio - h
        lat_min, lat_max = lat_min - need / 2, lat_max + need / 2
    return (lon_min, lon_max, lat_min, lat_max)


def frame_times(particles, every_hours):
    """動畫要用的輸出時間：從第一個輸出時間起，每隔約 every_hours 小時取一個（含最後一個）。"""
    times = pd.Series(particles["time_utc"].unique()).sort_values().reset_index(drop=True)
    if len(times) < 2:
        return list(times)
    step_s = float(times.diff().dt.total_seconds().median())
    k = max(1, int(round(every_hours * 3600.0 / step_s)))
    picked = list(times.iloc[::k])
    if picked[-1] != times.iloc[-1]:
        picked.append(times.iloc[-1])
    return picked


def centroid_track(particles, until):
    """每個輸出時間（不晚於 until）有位置的粒子重心，回傳 DataFrame[time_utc, lon, lat]。"""
    p = particles[(particles["time_utc"] <= pd.Timestamp(until)) & np.isfinite(particles["lon"])
                  & np.isfinite(particles["lat"])]
    g = p.groupby("time_utc")[["lon", "lat"]].mean().reset_index()
    return g.reset_index(drop=True)          # groupby 已依時間排序


# ---- 畫圖（用眼睛檢查，沒有單元測試） ----

def land_grid(extent, res_deg=LAND_RES_DEG):
    """範圍內的陸地遮罩（OpenDrift 擱淺判斷用的 roaring_landmask），回傳 (lons, lats, 二維布林，True 為陸地)。"""
    from roaring_landmask import RoaringLandmask

    lon_min, lon_max, lat_min, lat_max = extent
    lons = np.arange(lon_min, lon_max + res_deg, res_deg)
    lats = np.arange(lat_min, lat_max + res_deg, res_deg)
    gx, gy = np.meshgrid(lons, lats)
    mask = RoaringLandmask.new().contains_many_par(gx.ravel().astype(float), gy.ravel().astype(float))
    return lons, lats, np.asarray(mask, dtype=bool).reshape(gx.shape)


def draw_panel(ax, rows, wreck, extent, land, title, track=None, ref_direction=None, ref_max_km=None):
    """在 ax 上畫一個時刻的粒子（rows 是該時刻的粒子表列）與參考圖層。"""
    lons, lats, mask = land
    ax.contourf(lons, lats, mask.astype(float), levels=[0.5, 1.5], colors=["#d9d4c7"], zorder=0)
    ax.contour(lons, lats, mask.astype(float), levels=[0.5], colors=["#8a8473"], linewidths=0.6, zorder=1)
    for r in RINGS_KM:
        la, lo = circle_points(wreck[0], wreck[1], r)
        ax.plot(lo, la, color="#9aa3ad", lw=0.7, ls=":", zorder=1)
        ax.text(lo[0], la[0], f"{r} km", fontsize=6.5, color="#6b7480", ha="center", va="bottom", zorder=1)
    if ref_max_km is not None and np.isfinite(ref_max_km):
        la, lo = circle_points(wreck[0], wreck[1], ref_max_km)
        ax.plot(lo, la, color="#c2410c", lw=1.3, ls="--", zorder=3, label=f"Literature max distance {ref_max_km:g} km")
    if ref_direction in COMPASS_CENTER:
        la, lo = destination(wreck[0], wreck[1], COMPASS_CENTER[ref_direction], 45.0)
        ax.annotate("", xy=(lo, la), xytext=(wreck[1], wreck[0]), zorder=3,
                    arrowprops=dict(arrowstyle="-|>", color="#c2410c", lw=1.6))
        ax.plot([], [], color="#c2410c", lw=1.6, label=f"Literature direction: {ref_direction} (arrow length not scaled)")
    pos = rows[np.isfinite(rows["lon"]) & np.isfinite(rows["lat"])]
    active = pos[pos["status"] != STATUS_STRANDED]
    stranded = pos[pos["status"] == STATUS_STRANDED]
    ax.scatter(active["lon"], active["lat"], s=5, c="#1d4ed8", alpha=0.35, linewidths=0, zorder=4,
               label="Active")
    ax.scatter(stranded["lon"], stranded["lat"], s=6, c="#b91c1c", alpha=0.5, linewidths=0, zorder=4,
               label="Stranded")
    ax.text(0.02, 0.02, f"Active {len(active)}  |  Stranded {len(stranded)}", transform=ax.transAxes, fontsize=8,
            zorder=8, bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#9aa3ad", alpha=0.9))
    if track is not None and len(track) > 1:
        ax.plot(track["lon"], track["lat"], color="#111827", lw=1.0, zorder=5, label="Centroid track")
    if len(pos):
        ax.plot(pos["lon"].mean(), pos["lat"].mean(), marker="X", color="#111827", mec="white", ms=9, zorder=6,
                ls="none", label="Centroid")
    ax.plot(wreck[1], wreck[0], marker="*", color="#facc15", mec="#111827", ms=13, zorder=7, ls="none", label="Wreck")
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect(1.0 / np.cos(np.radians(wreck[0])))
    ax.set_title(title, fontsize=9)
    ax.set_xlabel("Longitude (°E)", fontsize=8)
    ax.set_ylabel("Latitude (°N)", fontsize=8)
    ax.tick_params(labelsize=7)


def _tw(t):
    return pd.Timestamp(t).tz_convert("Asia/Taipei").strftime("%Y-%m-%d %H:%M TW")


def plot_passes(runs, result, wreck, extent, land, out_dir):
    """每個文獻對應的過境一張圖，回傳檔案路徑清單。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths = []
    for pass_id in sorted(result["pass_id"].unique()):
        sel = result[result["pass_id"] == pass_id]
        fig, axes = plt.subplots(1, len(runs), figsize=(6.2 * len(runs), 6.6), squeeze=False)
        for ax, (run_id, particles) in zip(axes[0], runs.items()):
            row = sel[sel["run_id"] == run_id]
            if row.empty or pd.isna(row["sim_time_utc"].iloc[0]):
                ax.set_title(f"{run_id}: no model output near this pass", fontsize=9)
                ax.axis("off")
                continue
            r = row.iloc[0]
            when = r["sim_time_utc"]
            at = particles[particles["time_utc"] == when]
            title = (f"{run_id} | {pass_id}\nmodel time {_tw(when)} (model − pass = {r['gap_min']:+.1f} min)"
                     f" | centroid {r['centroid_compass']} {r['centroid_bearing_deg']:.0f}°, {r['centroid_distance_km']:.0f} km")
            ref_dir = r["ref_direction"] if isinstance(r["ref_direction"], str) else None
            draw_panel(ax, at, wreck, extent, land, title, centroid_track(particles, when), ref_dir,
                       r["ref_max_distance_km"])
        handles, labels = axes[0][0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8, frameon=False)
        fig.tight_layout(rect=(0, 0.07, 1, 1))
        path = Path(out_dir) / f"drift_{pass_id}.png"
        fig.savefig(path, dpi=130)
        plt.close(fig)
        paths.append(path)
    return paths


def animate(runs, wreck, extent, land, out_path, every_hours=3, fps=6):
    """逐格動畫（GIF）：各模擬並排，沿著時間顯示粒子與重心軌跡。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter

    times = frame_times(next(iter(runs.values())), every_hours)
    fig, axes = plt.subplots(1, len(runs), figsize=(5.4 * len(runs), 6.0), squeeze=False)

    def update(i):
        t = times[i]
        for ax, (run_id, particles) in zip(axes[0], runs.items()):
            ax.clear()
            at = particles[particles["time_utc"] == t]
            draw_panel(ax, at, wreck, extent, land, f"{run_id}\n{_tw(t)}", centroid_track(particles, t))
        return []

    update(0)
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5, fontsize=8, frameon=False)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    FuncAnimation(fig, update, frames=len(times), blit=False).save(str(out_path), writer=PillowWriter(fps=fps))
    plt.close(fig)
    return len(times)


def main():
    ap = argparse.ArgumentParser(description="漂移模擬的圖（在 opendrift 環境執行）")
    ap.add_argument("--particles", nargs="+", required=True, metavar="RUN=PATH")
    ap.add_argument("--matched", required=True)
    ap.add_argument("--passes", required=True)
    ap.add_argument("--out-dir", required=True, help="輸出資料夾（不存在會建立）")
    ap.add_argument("--animation", action="store_true", help="另外輸出動畫 drift_animation.gif")
    ap.add_argument("--every-hours", type=float, default=3.0, help="動畫每隔幾小時一格")
    ap.add_argument("--max-gap-min", type=float, default=30)
    args = ap.parse_args()

    runs = {}
    for item in args.particles:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            ap.error(f"--particles 要寫成 名稱=路徑，收到 {item!r}")
        if name in runs:
            ap.error(f"模擬名稱重複：{name}")
        runs[name] = load_particles(path)
    matched = pd.read_csv(args.matched, encoding="utf-8-sig")
    passes = pd.read_csv(args.passes, encoding="utf-8-sig")
    result = compare_runs(runs, matched, passes, max_gap_min=args.max_gap_min)

    wreck = (ANGEL.lat, ANGEL.lon)
    allp = pd.concat(runs.values())
    # 範圍包住所有粒子、沉船，以及沉船四周各約 50 公里（放得下文獻箭頭與距離圈），再調成不要太窄長
    box_lon = [wreck[1] - 0.5, wreck[1] + 0.5]
    box_lat = [wreck[0] - 0.5, wreck[0] + 0.5]
    extent = squarish_extent(map_extent(np.concatenate([allp["lon"].to_numpy(), box_lon]),
                                        np.concatenate([allp["lat"].to_numpy(), box_lat]), pad_deg=0.1), wreck[0])
    land = land_grid(extent)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for p in plot_passes(runs, result, wreck, extent, land, out):
        print(f"已寫入 {p}")
    if args.animation:
        path = out / "drift_animation.gif"
        n = animate(runs, wreck, extent, land, path, args.every_hours)
        print(f"已寫入 {path}（{n} 格）")


if __name__ == "__main__":
    main()
