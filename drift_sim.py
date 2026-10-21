"""用 OpenDrift 的 OpenOil 模擬沉船處釋放的油漂移，輸出粒子位置表。

要在 opendrift 環境執行（這個程式是專案裡唯一 import opendrift 的地方，核心測試不依賴它）。

設定（都是假設，不是觀測；原因見 README「漂移模擬」）：
  - 在沉船位置、沉沒時間一次釋放全部粒子（油實際何時、漏多久都不知道）。
  - 海流：CMEMS 逐時表層海流（uo、vo）；風：CMEMS 逐時風（eastward_wind、northward_wind，
    是 stress-equivalent wind，不是一般 10 m 風）。兩個檔案的時間都視為 UTC。
  - 風漂移係數 seed:wind_drift_factor：OpenDrift 1.14.12 預設 0.03（風向量的這個比例，另加海流與
    Stokes drift）。沒有海浪資料，Stokes drift 用內建備用值 0，所以實際風漂移只有這個係數。
  - 油種：AMSA Average Very Low Sulfur Fuel Oil (VLSFO)，對應船上 393.4 t 的低硫燃油（約 80%）。
    另外 98.1 t 輕柴油沒有模擬。「低硫燃油 = VLSFO」是對應，不是文章寫的。
  - 其他設定都用 OpenDrift 預設：隨機擾動（海流 0.05 m/s、風 0.5 m/s）、岸邊擱淺（stranding）、
    風化過程全開。隨機種子固定，結果可重現。
  - 外洩量不知道：粒子數只決定統計平滑度，不代表油量。

輸出（長格式）：time_utc, particle, lon, lat, status。被停用的粒子沒有位置；擱淺的粒子保留位置。

用法（在 opendrift 環境）：
  python drift_sim.py --current-nc data/raw/cmems/<海流>.nc --wind-nc data/raw/cmems/<風>.nc \
      --wind-drift-factor 0.03 --out data/drift_particles_base.csv
"""
import argparse
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from drift_compare import PARTICLE_COLUMNS, STATUS_STRANDED
from event import ANGEL, SINKING_TIME

OIL_TYPE = "AMSA Average Very Low Sulfur Fuel Oil (VLSFO)"
DEFAULT_WIND_DRIFT_FACTOR = 0.03      # OpenDrift 1.14.12 的預設值
DEFAULT_PARTICLES = 1000
DEFAULT_SEED = 0
CALC_STEP_S = 900                     # 計算步長 15 分鐘
OUTPUT_STEP_S = 3600                  # 輸出步長 1 小時


def result_to_table(ds, status_categories):
    """OpenDrift 的結果（xarray Dataset，維度 trajectory × time）轉成長格式表。

    狀態編號用 status_categories 換成名稱。OpenDrift 的結果在粒子被停用後，位置與狀態都是空的：
      - 擱淺（stranded）的油還在岸上，所以保留擱淺位置，之後每個時間都標為 stranded；
      - 其他停用（例如 missing_data：飄出資料範圍）的粒子，位置維持空，狀態沿用最後一個已知的狀態；
      - 一開始就沒有狀態的列標為 unknown。
    """
    lon = np.array(ds["lon"].values, dtype=float)
    lat = np.array(ds["lat"].values, dtype=float)
    code = np.array(ds["status"].values, dtype=float)
    n, m = lon.shape
    names = np.full((n, m), "unknown", dtype=object)
    for i in range(n):
        last_name = "unknown"
        last_pos = None
        for j in range(m):
            if np.isfinite(code[i, j]):
                last_name = status_categories[int(code[i, j])]
                last_pos = (lon[i, j], lat[i, j])
            elif last_name == STATUS_STRANDED and last_pos is not None:
                lon[i, j], lat[i, j] = last_pos
            names[i, j] = last_name
    times = pd.to_datetime(ds["time"].values, utc=True)
    out = pd.DataFrame({
        "time_utc": np.tile(times, n),
        "particle": np.repeat(np.arange(n), m),
        "lon": lon.ravel(), "lat": lat.ravel(), "status": names.ravel(),
    })
    return out[PARTICLE_COLUMNS]


def run_simulation(current_nc, wind_nc, lat=ANGEL.lat, lon=ANGEL.lon, release_time=SINKING_TIME,
                   end_time=None, particles=DEFAULT_PARTICLES, wind_drift_factor=DEFAULT_WIND_DRIFT_FACTOR,
                   oil_type=OIL_TYPE, seed=DEFAULT_SEED, calc_step_s=CALC_STEP_S, output_step_s=OUTPUT_STEP_S):
    """跑一次模擬，回傳粒子表。release_time 與 end_time 是帶時區的時間，內部換成 UTC。"""
    from opendrift.models.openoil import OpenOil
    from opendrift.readers import reader_netCDF_CF_generic

    def utc_naive(t):
        return pd.Timestamp(t).tz_convert("UTC").tz_localize(None).to_pydatetime()

    start = utc_naive(release_time)
    end = utc_naive(end_time) if end_time is not None else None

    o = OpenOil(loglevel=30, seed=seed)
    o.add_reader([reader_netCDF_CF_generic.Reader(str(current_nc)),
                  reader_netCDF_CF_generic.Reader(str(wind_nc))])
    o.set_config("seed:wind_drift_factor", float(wind_drift_factor))
    o.set_config("seed:oil_type", oil_type)
    o.seed_elements(lon=lon, lat=lat, time=start, number=int(particles), radius=0)
    o.run(end_time=end, time_step=calc_step_s, time_step_output=output_step_s)
    return result_to_table(o.result, o.status_categories)


def main():
    ap = argparse.ArgumentParser(description="OpenOil 漂移模擬（在 opendrift 環境執行）")
    ap.add_argument("--current-nc", required=True, help="海流 NetCDF（uo、vo）")
    ap.add_argument("--wind-nc", required=True, help="風 NetCDF（eastward_wind、northward_wind）")
    ap.add_argument("--out", required=True, help="輸出粒子表 CSV")
    ap.add_argument("--wind-drift-factor", type=float, default=DEFAULT_WIND_DRIFT_FACTOR)
    ap.add_argument("--particles", type=int, default=DEFAULT_PARTICLES)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--end", default="2023-07-28 23:00",
                    help="模擬結束時間（UTC，YYYY-MM-DD HH:MM）；預設是海流與風資料結束前一小時")
    args = ap.parse_args()

    end = pd.Timestamp(args.end, tz="UTC")
    table = run_simulation(args.current_nc, args.wind_nc, end_time=end, particles=args.particles,
                           wind_drift_factor=args.wind_drift_factor, seed=args.seed)
    table.to_csv(args.out, index=False, encoding="utf-8-sig")
    last = table[table["time_utc"] == table["time_utc"].max()]
    print(f"{table['particle'].nunique()} 顆粒子，{table['time_utc'].min()} → {table['time_utc'].max()}")
    print("最後一個輸出時間的狀態：", last["status"].value_counts().to_dict())
    print(f"已寫入 {args.out}")


if __name__ == "__main__":
    main()
