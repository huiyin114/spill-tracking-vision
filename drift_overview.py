"""總覽圖：把多個漂移模擬的粒子重心軌跡畫在同一張地圖上，並在「同一個時刻」與氣象署官方模擬比較。

用途：直接看「同一事件、不同海流與起點，方向與距離差很多」。每個模擬一條軌跡（顏色與線型都不同，線寬一樣），
軌跡上用同樣的記號標出兩個時刻的重心位置（圓點 = 台灣時間 7/24 02:30，方塊 = 7/25 19:30）；
氣象署官方模擬在同樣兩個時刻的油膜中心用黑色的同形記號標出，可以一對一比較。
另外畫沉船位置、25／50／100 km 距離圈、文獻的方向（東南）與最遠距離圈，並印出各時刻的方位與距離。

氣象署官方模擬的位置只是目測：作者看過動畫，截了兩張標有時間的畫面，用畫面上的緯度與經度格線
把油膜中心的位置粗估成兩個點（誤差約 ±0.05°），沒有拿到官方的資料；圖上標示為「eyeballed」。

在 opendrift 環境執行（matplotlib 與 roaring_landmask 都已經裝了）。圖上的文字用英文。

用法：
  python drift_overview.py --particles CMEMS=data/drift_particles_base.csv SMOC=data/drift_particles_smoc003.csv \
      HYCOM_0722=data/drift_particles_hycom_official03.csv HYCOM_sinking=data/drift_particles_hycom_sinking03.csv \
      --out figures/drift_overview.png [--table-out data/drift_overview_points.csv]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from drift_compare import COMPASS_CENTER, REFERENCE_DIRECTION, bearing_deg, load_particles, nearest_output_time
from drift_plot import RINGS_KM, centroid_track, circle_points, destination, land_grid, map_extent, squarish_extent
from drone import haversine_km
from event import ANGEL

LITERATURE_DIRECTION = "SE"         # 與 drift_compare.REFERENCE_DIRECTION 一致（測試檢查）
LITERATURE_MAX_KM = 26.5            # JpGU 2025 摘要：2023-07-27 Sentinel-1 距沉船最遠 26.5 km
# 氣象署官方模擬（OILmap，國立高雄科技大學）的油膜中心，從 MP4 截圖目測：
# 畫面左上角標示的時間（台灣時間），緯度、經度由畫面格線（22°48′N、22°12′N、21°36′N 與 120°E、121°E、122°E）估。
COMPARE = (
    {"label": "Jul 24 02:30 TW", "tw": "2023-07-24 02:30", "marker": "o", "official": (22.19, 120.36)},
    {"label": "Jul 25 19:30 TW", "tw": "2023-07-25 19:30", "marker": "s", "official": (21.59, 121.07)},
)
# 每個模擬的顏色與線型（顏色對比、線型不同；線寬全部一樣）
RUN_STYLES = (("#0072B2", "-"), ("#CC79A7", "--"), ("#009E73", "-."), ("#E69F00", ":"), ("#56B4E9", (0, (5, 1, 1, 1))))
LINE_WIDTH = 2.0
TABLE_COLUMNS = ["run", "time_tw", "lon", "lat", "bearing_deg", "distance_km"]


def parse_run_args(items):
    """['名稱=路徑', ...] → {名稱: 路徑}。格式不對或名稱重複就報錯。"""
    runs = {}
    for item in items:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            raise ValueError(f"--particles 要寫成 名稱=路徑，收到 {item!r}")
        if name in runs:
            raise ValueError(f"模擬名稱重複：{name}")
        runs[name] = path
    return runs


def compare_time_utc(item):
    """COMPARE 項目的比較時刻（台灣時間）換成 UTC。"""
    return pd.Timestamp(item["tw"], tz="Asia/Taipei").tz_convert("UTC")


def centroid_at(particles, t, max_gap_min=30):
    """離 t 最近的輸出時間的粒子重心 (lon, lat)；沒有輸出（差距超過上限）或該時刻沒有粒子有位置時回傳 None。"""
    found = nearest_output_time(particles, t, max_gap_min)
    if found is None:
        return None
    rows = particles[particles["time_utc"] == found[0]]
    pos = rows[np.isfinite(rows["lon"]) & np.isfinite(rows["lat"])]
    if pos.empty:
        return None
    return float(pos["lon"].mean()), float(pos["lat"].mean())


def points_table(runs, wreck, compare=COMPARE, official_name="CWA (eyeballed)"):
    """各模擬與官方在比較時刻的重心位置、相對沉船點的方位與距離。沒有位置的列，經緯度、方位、距離為空值。"""
    rows = []

    def add(name, item, c):
        if c is None:
            rows.append([name, item["label"], np.nan, np.nan, np.nan, np.nan])
        else:
            rows.append([name, item["label"], c[0], c[1], float(bearing_deg(wreck[0], wreck[1], c[1], c[0])),
                         float(haversine_km(wreck[0], wreck[1], c[1], c[0]))])

    for item in compare:
        for name, particles in runs.items():
            add(name, item, centroid_at(particles, compare_time_utc(item)))
        add(official_name, item, (item["official"][1], item["official"][0]))
    return pd.DataFrame(rows, columns=TABLE_COLUMNS)


def plot_overview(runs, wreck, until, out_path):
    """畫總覽圖並存成 PNG。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    tracks = {name: centroid_track(p, until) for name, p in runs.items()}
    off_lons = [c["official"][1] for c in COMPARE]
    off_lats = [c["official"][0] for c in COMPARE]
    lons = np.concatenate([t["lon"].to_numpy() for t in tracks.values()] + [[wreck[1] - 0.5, wreck[1] + 0.5], off_lons])
    lats = np.concatenate([t["lat"].to_numpy() for t in tracks.values()] + [[wreck[0] - 0.5, wreck[0] + 0.5], off_lats])
    extent = squarish_extent(map_extent(lons, lats, pad_deg=0.15), wreck[0])
    mlons, mlats, mask = land_grid(extent)

    fig, ax = plt.subplots(figsize=(8.2, 8.8))
    ax.contourf(mlons, mlats, mask.astype(float), levels=[0.5, 1.5], colors=["#d9d4c7"], zorder=0)
    ax.contour(mlons, mlats, mask.astype(float), levels=[0.5], colors=["#8a8473"], linewidths=0.6, zorder=1)
    for r in RINGS_KM:
        la, lo = circle_points(wreck[0], wreck[1], r)
        ax.plot(lo, la, color="#9aa3ad", lw=0.8, ls=":", zorder=1)
        ax.text(lo[0], la[0], f"{r} km", fontsize=7, color="#6b7480", ha="center", va="bottom", clip_on=True)
    la, lo = circle_points(wreck[0], wreck[1], LITERATURE_MAX_KM)
    ax.plot(lo, la, color="#D55E00", lw=LINE_WIDTH, ls="--", zorder=3)
    la2, lo2 = destination(wreck[0], wreck[1], COMPASS_CENTER[LITERATURE_DIRECTION], 45.0)
    ax.annotate("", xy=(lo2, la2), xytext=(wreck[1], wreck[0]), zorder=3,
                arrowprops=dict(arrowstyle="-|>", color="#D55E00", lw=LINE_WIDTH))
    # 官方：黑色記號，以直線連到沉船點（只是連線，不是路徑）
    ax.plot([wreck[1]] + off_lons, [wreck[0]] + off_lats, color="#111111", lw=LINE_WIDTH, ls=(0, (1, 1.5)), zorder=4)

    handles = [Line2D([], [], color="#D55E00", lw=LINE_WIDTH, ls="--", label=f"Literature max distance {LITERATURE_MAX_KM:g} km (Jul 27)"),
               Line2D([], [], color="#D55E00", lw=LINE_WIDTH, label="Literature direction: SE (arrow length not scaled)"),
               Line2D([], [], color="#111111", lw=LINE_WIDTH, ls=(0, (1, 1.5)), label="CWA simulation, slick centre (eyeballed)")]
    for (name, track), (color, style) in zip(tracks.items(), RUN_STYLES):
        ax.plot(track["lon"], track["lat"], color=color, lw=LINE_WIDTH, ls=style, zorder=5)
        handles.append(Line2D([], [], color=color, lw=LINE_WIDTH, ls=style, label=f"{name} (centroid track)"))
        for item in COMPARE:
            c = centroid_at(runs[name], compare_time_utc(item))
            if c is not None:
                ax.plot(c[0], c[1], marker=item["marker"], color=color, mec="white", mew=1.2, ms=10, ls="none", zorder=6)
    for item in COMPARE:
        la, lo = item["official"]
        ax.plot(lo, la, marker=item["marker"], color="#111111", mec="white", mew=1.2, ms=12, ls="none", zorder=7)
        handles.append(Line2D([], [], marker=item["marker"], color="#555555", mec="white", ls="none", ms=9,
                              label=f"Position at {item['label']} (model and CWA, same time)"))
    ax.plot(wreck[1], wreck[0], marker="*", color="#facc15", mec="#111827", ms=16, ls="none", zorder=8)
    handles.append(Line2D([], [], marker="*", color="#facc15", mec="#111827", ls="none", ms=12, label="Wreck"))

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect(1.0 / np.cos(np.radians(wreck[0])))
    ax.set_title("Particle-simulation centroid tracks vs CWA simulation at the same times\n"
                 "colour and line style identify the run; marker shape identifies the time", fontsize=10)
    ax.set_xlabel("Longitude (°E)", fontsize=9)
    ax.set_ylabel("Latitude (°N)", fontsize=9)
    ax.tick_params(labelsize=8)
    fig.legend(handles=handles, loc="lower center", ncol=2, fontsize=7.5, frameon=False)
    fig.tight_layout(rect=(0, 0.17, 1, 1))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="漂移模擬的重心軌跡總覽圖（在 opendrift 環境執行）")
    ap.add_argument("--particles", nargs="+", required=True, metavar="RUN=PATH")
    ap.add_argument("--out", required=True, help="輸出 PNG 路徑")
    ap.add_argument("--table-out", help="另外輸出各時刻位置、方位、距離的 CSV")
    ap.add_argument("--until", default="2023-07-25 12:00", help="軌跡畫到這個 UTC 時間（預設包含最後一個比較時刻）")
    args = ap.parse_args()
    try:
        paths = parse_run_args(args.particles)
    except ValueError as e:
        ap.error(str(e))
    if len(paths) > len(RUN_STYLES):
        ap.error(f"最多 {len(RUN_STYLES)} 個模擬（顏色與線型只定義了這麼多）")
    runs = {name: load_particles(path) for name, path in paths.items()}
    wreck = (ANGEL.lat, ANGEL.lon)
    plot_overview(runs, wreck, pd.Timestamp(args.until, tz="UTC"), args.out)
    table = points_table(runs, wreck)
    print(table.round(2).to_string(index=False))
    if args.table_out:
        table.to_csv(args.table_out, index=False, encoding="utf-8-sig")
        print(f"已寫入 {args.table_out}")
    print(f"已寫入 {args.out}")


if __name__ == "__main__":
    main()
