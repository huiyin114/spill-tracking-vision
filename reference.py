"""外部參考觀測（文獻裡研究者估計的油膜面積、距離等），以及它們對應到哪一次衛星過境。

這些是別人的估計值，不是地面真值；檔案裡每一列都要寫出處。
長格式，一個數字一列：ref_id, sensor, date, variable, value, unit, source, note
文獻只給日期、沒給時間，也沒說是哪個時區的日期，所以對應過境時：
  同感測器、且過境的 UTC 日期或台灣日期任一等於該日期，才算候選；
  候選剛好一個才配對，沒有或有多個就不猜（match = no_pass / ambiguous）。

用法：python reference.py --reference data/reference_observations.csv --passes data/passes.csv [--out data/reference_matched.csv]
"""
import argparse

import numpy as np
import pandas as pd

from event import TAIWAN

# 變數登記表：變數名 → 單位。新增變數時先在這裡登記。
VARIABLES = {
    "oil_area": "km2",
    "oil_max_distance": "km",
}
SENSORS = {"S1", "S2"}
COLUMNS = ["ref_id", "sensor", "date", "variable", "value", "unit", "source", "note"]


def load_reference(path):
    """讀參考觀測檔並檢查；有問題就報錯，不默默修正。"""
    ref = pd.read_csv(path, encoding="utf-8-sig", dtype={"ref_id": str, "sensor": str, "date": str,
                                                          "variable": str, "unit": str, "source": str, "note": str})
    missing = [c for c in COLUMNS if c not in ref.columns]
    if missing:
        raise ValueError(f"{path} 缺少欄位：{missing}")
    ref = ref[COLUMNS].copy()
    for col in ("ref_id", "source"):
        if ref[col].isna().any() or (ref[col].str.strip() == "").any():
            raise ValueError(f"{path} 的 {col} 不能是空的（每筆都要有編號與出處）")
    if ref["ref_id"].duplicated().any():
        raise ValueError(f"{path} 有重複的 ref_id：{sorted(ref['ref_id'][ref['ref_id'].duplicated()])}")
    bad = sorted(set(ref["sensor"].dropna()) - SENSORS)
    if bad or ref["sensor"].isna().any():
        raise ValueError(f"{path} 的 sensor 只能是 {sorted(SENSORS)}，但有：{bad or '空值'}")
    unknown = sorted(set(ref["variable"].dropna()) - set(VARIABLES))
    if unknown or ref["variable"].isna().any():
        raise ValueError(f"{path} 有未登記的變數：{unknown or '空值'}（請先加到 reference.VARIABLES）")
    for v, unit in VARIABLES.items():
        wrong = ref[(ref["variable"] == v) & (ref["unit"] != unit)]
        if not wrong.empty:
            raise ValueError(f"{path} 的 {v} 單位應為 {unit}，但 {list(wrong['ref_id'])} 不是")
    dates = pd.to_datetime(ref["date"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ValueError(f"{path} 的 date 必須是 YYYY-MM-DD：{list(ref['date'][dates.isna()])}")
    ref["value"] = pd.to_numeric(ref["value"], errors="coerce")
    if (~np.isfinite(ref["value"])).any() or (ref["value"] < 0).any():
        raise ValueError(f"{path} 的 value 必須是不小於 0 的數字")
    return ref.reset_index(drop=True)


def match_passes(reference, passes):
    """每筆參考觀測對到一次過境；回傳參考表加上 pass_id、pass_time_tw、match。

    match：matched（候選剛好一個）、no_pass（沒有候選）、ambiguous（多個候選，不猜）。
    後兩者的 pass_id 為空。
    """
    utc = pd.to_datetime(passes["time_utc"], utc=True)
    d_utc = utc.dt.strftime("%Y-%m-%d")
    d_tw = utc.dt.tz_convert(TAIWAN).dt.strftime("%Y-%m-%d")
    rows = []
    for _, r in reference.iterrows():
        hit = passes[(passes["sensor"] == r["sensor"]) & ((d_utc == r["date"]) | (d_tw == r["date"]))]
        if len(hit) == 1:
            rows.append((hit["pass_id"].iloc[0], hit["time_tw"].iloc[0], "matched"))
        else:
            rows.append((None, None, "no_pass" if hit.empty else "ambiguous"))
    out = reference.copy()
    out["pass_id"], out["pass_time_tw"], out["match"] = zip(*rows) if rows else ([], [], [])
    return out


def main():
    ap = argparse.ArgumentParser(description="外部參考觀測與衛星過境的對應")
    ap.add_argument("--reference", required=True, help="參考觀測 CSV（data/reference_observations.csv）")
    ap.add_argument("--passes", required=True, help="過境表 CSV（data/passes.csv）")
    ap.add_argument("--out", help="輸出對應結果 CSV 路徑")
    args = ap.parse_args()

    ref = load_reference(args.reference)
    passes = pd.read_csv(args.passes, encoding="utf-8-sig")
    matched = match_passes(ref, passes)
    print(matched.drop(columns=["source", "note"]).to_string(index=False))
    print(matched["match"].value_counts().to_string())
    if args.out:
        matched.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"已寫入 {args.out}")


if __name__ == "__main__":
    main()
