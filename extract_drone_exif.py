#!/usr/bin/env python3
"""
抽出無人機影像的 EXIF / XMP 中繼資料，輸出成 CSV（不複製、不修改任何影像）。

用法：
    python extract_drone_exif.py <影像資料夾> [輸出.csv]

例：
    python extract_drone_exif.py "Z:\\天使輪\\drone" angel_drone_exif.csv
    python extract_drone_exif.py /Volumes/NAS/天使輪/drone

需要：Python 3.8+、Pillow（pip install pillow）
會遞迴掃描子資料夾；只讀每個檔案的檔頭，不會整張載入，適合在 NAS 上跑。
"""
import csv
import os
import re
import sys
from collections import Counter

try:
    from PIL import Image
except ImportError:
    sys.exit("找不到 Pillow，請先執行：pip install pillow")

IMAGE_EXT = {".jpg", ".jpeg", ".tif", ".tiff", ".dng"}
GPS_IFD, EXIF_IFD = 0x8825, 0x8769

# DJI 等無人機寫在 XMP 的欄位（drone-dji:xxx="..."）
XMP_FIELDS = [
    "RelativeAltitude", "AbsoluteAltitude",
    "GimbalPitchDegree", "GimbalYawDegree", "GimbalRollDegree",
    "FlightYawDegree", "FlightPitchDegree", "FlightRollDegree",
]

COLUMNS = [
    "file", "subfolder", "datetime_original", "subsec", "offset_time",
    "lat", "lon", "gps_alt_m",
    "rel_alt_m", "abs_alt_m",
    "gimbal_pitch", "gimbal_yaw", "gimbal_roll",
    "flight_yaw", "flight_pitch", "flight_roll",
    "make", "model", "focal_mm", "focal_35mm",
    "width", "height", "file_size_mb", "error",
]


def _ratio(x):
    try:
        return float(x)
    except (TypeError, ValueError, ZeroDivisionError):
        try:
            return x[0] / x[1]
        except Exception:
            return None


def _dms_to_deg(dms, ref):
    if not dms or len(dms) != 3:
        return None
    d, m, s = (_ratio(v) for v in dms)
    if None in (d, m, s):
        return None
    deg = d + m / 60 + s / 3600
    if ref in ("S", "W", b"S", b"W"):
        deg = -deg
    return round(deg, 7)


def _read_xmp(path, limit=512 * 1024):
    """在檔頭範圍內找 XMP 封包，抓 drone-dji 欄位。"""
    out = {}
    try:
        with open(path, "rb") as fh:
            head = fh.read(limit)
    except OSError:
        return out
    start = head.find(b"<x:xmpmeta")
    if start < 0:
        return out
    end = head.find(b"</x:xmpmeta>", start)
    xmp = head[start:end if end > 0 else None].decode("utf-8", "ignore")
    for key in XMP_FIELDS:
        m = re.search(r'[\w-]+:%s\s*=\s*"([^"]+)"' % key, xmp) or \
            re.search(r"<[\w-]+:%s>([^<]+)<" % key, xmp)
        if m:
            try:
                out[key] = float(m.group(1))
            except ValueError:
                pass
    return out


def read_one(path, root):
    row = dict.fromkeys(COLUMNS, "")
    row["file"] = os.path.basename(path)
    row["subfolder"] = os.path.relpath(os.path.dirname(path), root)
    row["file_size_mb"] = round(os.path.getsize(path) / 1e6, 2)
    try:
        with Image.open(path) as im:
            row["width"], row["height"] = im.size
            exif = im.getexif()
            row["make"] = str(exif.get(0x010F, "")).strip("\x00 ")
            row["model"] = str(exif.get(0x0110, "")).strip("\x00 ")
            ex = exif.get_ifd(EXIF_IFD)
            row["datetime_original"] = ex.get(0x9003) or exif.get(0x0132, "")
            row["subsec"] = ex.get(0x9291, "")
            row["offset_time"] = ex.get(0x9011, "")
            f = _ratio(ex.get(0x920A))
            row["focal_mm"] = round(f, 2) if f else ""
            row["focal_35mm"] = ex.get(0xA405, "")
            gps = exif.get_ifd(GPS_IFD)
            if gps:
                row["lat"] = _dms_to_deg(gps.get(2), gps.get(1)) or ""
                row["lon"] = _dms_to_deg(gps.get(4), gps.get(3)) or ""
                alt = _ratio(gps.get(6))
                if alt is not None:
                    row["gps_alt_m"] = round(-alt if gps.get(5) in (1, b"\x01") else alt, 2)
    except Exception as e:  # 壞檔或不支援的格式，記錄後繼續
        row["error"] = f"{type(e).__name__}: {e}"[:200]

    xmp = _read_xmp(path)
    mapping = {
        "RelativeAltitude": "rel_alt_m", "AbsoluteAltitude": "abs_alt_m",
        "GimbalPitchDegree": "gimbal_pitch", "GimbalYawDegree": "gimbal_yaw",
        "GimbalRollDegree": "gimbal_roll", "FlightYawDegree": "flight_yaw",
        "FlightPitchDegree": "flight_pitch", "FlightRollDegree": "flight_roll",
    }
    for k, col in mapping.items():
        if k in xmp:
            row[col] = xmp[k]
    return row


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root = sys.argv[1]
    out_csv = sys.argv[2] if len(sys.argv) > 2 else "angel_drone_exif.csv"
    if not os.path.isdir(root):
        sys.exit(f"找不到資料夾：{root}")

    paths, skipped = [], Counter()
    for dirpath, _, files in os.walk(root):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in IMAGE_EXT:
                paths.append(os.path.join(dirpath, name))
            elif not name.startswith("."):
                skipped[ext or "(無副檔名)"] += 1
    paths.sort()
    print(f"找到 {len(paths)} 張影像，開始讀取…")

    rows = []
    for i, p in enumerate(paths, 1):
        rows.append(read_one(p, root))
        if i % 50 == 0 or i == len(paths):
            print(f"  {i}/{len(paths)}")

    # utf-8-sig：用 Excel 開啟中文不會亂碼
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    n_gps = sum(1 for r in rows if r["lat"] != "")
    n_time = sum(1 for r in rows if r["datetime_original"])
    n_err = sum(1 for r in rows if r["error"])
    dates = Counter(str(r["datetime_original"])[:10] for r in rows if r["datetime_original"])
    print(f"\n完成：{out_csv}")
    print(f"  有時間 {n_time} 張｜有 GPS {n_gps} 張｜讀取錯誤 {n_err} 張")
    if dates:
        print("  各日期張數：" + "、".join(f"{d.replace(':', '/')}({c})" for d, c in sorted(dates.items())))
    if skipped:
        print("  略過的其他檔案：" + "、".join(f"{k}×{v}" for k, v in skipped.most_common()))


if __name__ == "__main__":
    main()
