"""wind.py 的單元測試。用法：pytest

測試資料全部在這裡自己造，不讀 data/ 裡的真實檔案。
"""
import calendar
import csv
import math
from pathlib import Path

import pandas as pd
import pytest

from event import WRECK_LAT, WRECK_LON
from wind import build_wind_at_passes, load_month, load_wind, parse_cell, winds_at_pass

TW = "Asia/Taipei"


# ---------- 造測試資料的小工具 ----------

def tw(s):
    return pd.Timestamp(s, tz=TW)


def write_month(folder, station, year, month, cell=lambda d, h: "1.0 / 90", name=None, days=None, bom=False):
    """造一份和 CODiS 月報表同樣形狀的檔：日 × 時，最後有「平均」列與「平均」欄。"""
    n = calendar.monthrange(year, month)[1]
    days = range(1, n + 1) if days is None else days
    name = name or f"{station}-{year}-{month:02d}-WindSpeed,WindDirection-hour.csv"
    path = Path(folder) / name
    with open(path, "w", newline="", encoding="utf-8-sig" if bom else "utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL)
        w.writerow(["日/時"] + [str(h) for h in range(1, 25)] + ["平均"])
        for d in days:
            w.writerow([f"{d:02d}"] + [cell(d, h) for h in range(1, 25)] + ["1.0"])
        w.writerow(["平均"] + ["1.0"] * 24 + ["平均"])
    return path


def make_wind(station="A", start="2023-07-20 01:00", hours=72, ws=2.0, wd=90.0):
    """台灣時間每個整點一筆（各代表整點前 10 分鐘），連續 hours 小時。"""
    times = pd.date_range(start, periods=hours, freq="h", tz=TW)
    return pd.DataFrame({"station": station, "time_tw": times, "time_utc": times.tz_convert("UTC"),
                         "ws_ms": ws, "wd_deg": wd})


# ---------- parse_cell ----------

def test_parse_cell_normal():
    assert parse_cell("3.4 / 250") == (3.4, 250.0)


def test_parse_cell_no_observation_is_nan():
    ws, wd = parse_cell("-- / --")
    assert math.isnan(ws) and math.isnan(wd)


@pytest.mark.parametrize("text", ["0.0 / 0", "0.1 / 0", "0.2 / 0"])
def test_parse_cell_calm_has_no_direction(text):
    ws, wd = parse_cell(text)
    assert ws <= 0.2 and math.isnan(wd)


def test_parse_cell_just_above_calm_keeps_direction():
    assert parse_cell("0.3 / 20") == (0.3, 20.0)


def test_parse_cell_north_is_360_and_kept():
    assert parse_cell("2.0 / 360") == (2.0, 360.0)


def test_parse_cell_variable_direction_keeps_speed():
    ws, wd = parse_cell("5.1 / V")
    assert ws == 5.1 and math.isnan(wd)


def test_parse_cell_malfunction_symbol():
    ws, wd = parse_cell("x / x")
    assert math.isnan(ws) and math.isnan(wd)


@pytest.mark.parametrize("text", ["3.4", "abc / 12", "3.4 / 250 / 1", ""])
def test_parse_cell_unreadable_raises(text):
    with pytest.raises(ValueError):
        parse_cell(text)


# ---------- load_month ----------

def test_load_month_row_count_and_station(tmp_path):
    path = write_month(tmp_path, "C0V690", 2023, 7)
    out = load_month(path)
    assert len(out) == 31 * 24            # 「平均」列與欄沒有混進來
    assert set(out["station"]) == {"C0V690"}


def test_load_month_uses_real_download_filename(tmp_path):
    """瀏覽器下載的實際檔名含逗號。"""
    path = write_month(tmp_path, "C0V850", 2023, 8, name="C0V850-2023-08-WindSpeed,WindDirection-hour.csv")
    assert set(load_month(path)["station"]) == {"C0V850"}


def test_load_month_time_mapping(tmp_path):
    out = load_month(write_month(tmp_path, "C0V690", 2023, 7)).set_index("time_tw")
    first = out.index[0]
    assert first == tw("2023-07-01 01:00")
    assert out.loc[first, "time_utc"] == pd.Timestamp("2023-06-30 17:00", tz="UTC")


def test_hour_24_is_next_day_midnight(tmp_path):
    cells = lambda d, h: "9.9 / 45" if (d, h) == (1, 24) else "1.0 / 90"
    out = load_month(write_month(tmp_path, "C0V690", 2023, 7, cell=cells))
    row = out[out["ws_ms"] == 9.9].iloc[0]
    assert row["time_tw"] == tw("2023-07-02 00:00")


def test_hour_24_on_last_day_crosses_month(tmp_path):
    cells = lambda d, h: "9.9 / 45" if (d, h) == (31, 24) else "1.0 / 90"
    out = load_month(write_month(tmp_path, "C0V690", 2023, 7, cell=cells))
    assert out[out["ws_ms"] == 9.9].iloc[0]["time_tw"] == tw("2023-08-01 00:00")


def test_load_month_missing_cell_keeps_the_row(tmp_path):
    cells = lambda d, h: "-- / --" if (d, h) == (1, 15) else "1.0 / 90"
    out = load_month(write_month(tmp_path, "C0V690", 2023, 7, cell=cells))
    assert len(out) == 31 * 24
    missing = out[out["ws_ms"].isna()]
    assert len(missing) == 1 and missing.iloc[0]["time_tw"] == tw("2023-07-01 15:00")


def test_load_month_calm_direction_is_nan(tmp_path):
    cells = lambda d, h: "0.0 / 0" if (d, h) == (3, 5) else "1.0 / 90"
    out = load_month(write_month(tmp_path, "C0V690", 2023, 7, cell=cells))
    calm = out[out["time_tw"] == tw("2023-07-03 05:00")].iloc[0]
    assert calm["ws_ms"] == 0.0 and math.isnan(calm["wd_deg"])


def test_load_month_accepts_bom(tmp_path):
    out = load_month(write_month(tmp_path, "C0V690", 2023, 7, bom=True))
    assert len(out) == 31 * 24


def test_load_month_follows_the_calendar(tmp_path):
    assert len(load_month(write_month(tmp_path, "C0V690", 2023, 2))) == 28 * 24
    assert len(load_month(write_month(tmp_path, "C0V690", 2024, 2))) == 29 * 24


def test_load_month_incomplete_month_raises(tmp_path):
    path = write_month(tmp_path, "C0V690", 2023, 7, days=range(1, 31))   # 少一天
    with pytest.raises(ValueError):
        load_month(path)


def test_load_month_unrecognised_filename_raises(tmp_path):
    path = write_month(tmp_path, "C0V690", 2023, 7, name="wind-july.csv")
    with pytest.raises(ValueError):
        load_month(path)


# ---------- load_wind ----------

def test_load_wind_merges_months_and_stations_sorted(tmp_path):
    write_month(tmp_path, "C0V850", 2023, 8)
    write_month(tmp_path, "C0V690", 2023, 8)
    write_month(tmp_path, "C0V690", 2023, 7)
    wind = load_wind(tmp_path)
    assert len(wind) == (31 + 31 + 31) * 24
    assert wind["station"].tolist() == sorted(wind["station"].tolist())
    one = wind[wind["station"] == "C0V690"]
    assert one["time_utc"].is_monotonic_increasing
    assert len(one) == 62 * 24


def test_load_wind_ignores_other_files(tmp_path):
    write_month(tmp_path, "C0V690", 2023, 7)
    (tmp_path / "stac_s1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "angel_drone_exif.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert len(load_wind(tmp_path)) == 31 * 24


def test_load_wind_duplicate_month_raises(tmp_path):
    write_month(tmp_path, "C0V690", 2023, 7)
    write_month(tmp_path, "C0V690", 2023, 7, name="C0V690-2023-07-WindSpeed,WindDirection (1)-hour.csv")
    with pytest.raises(ValueError):
        load_wind(tmp_path)


def test_load_wind_empty_folder_raises(tmp_path):
    with pytest.raises(ValueError):
        load_wind(tmp_path)


# ---------- winds_at_pass ----------

def test_pass_inside_the_window_has_zero_gap():
    # 05:53 落在 06:00 觀測的窗口 [05:50, 06:00] 內
    near = winds_at_pass(make_wind(), tw("2023-07-21 05:53"))
    assert len(near) == 1
    assert near.iloc[0]["time_tw"] == tw("2023-07-21 06:00")
    assert near.iloc[0]["gap_min"] == 0.0


def test_pass_just_after_the_window_is_negative():
    near = winds_at_pass(make_wind(), tw("2023-07-21 06:01"))
    assert len(near) == 1
    assert near.iloc[0]["time_tw"] == tw("2023-07-21 06:00")
    assert near.iloc[0]["gap_min"] == -1.0       # 觀測在衛星之前


def test_pass_midway_between_windows_returns_both():
    # 10:25：10 時窗口結束後 25 分鐘，11 時窗口 [10:50, 11:00] 開始前 25 分鐘，完全平手
    near = winds_at_pass(make_wind(), tw("2023-07-21 10:25"))
    assert near["time_tw"].tolist() == [tw("2023-07-21 10:00"), tw("2023-07-21 11:00")]
    assert near["gap_min"].tolist() == [-25.0, 25.0]


def test_max_gap_is_inclusive():
    # 06:30:00 離 06:00 窗口剛好 30 分鐘；晚 1 秒就超過
    on_edge = winds_at_pass(make_wind(), tw("2023-07-21 06:30:00"))
    assert on_edge["time_tw"].tolist() == [tw("2023-07-21 06:00"), tw("2023-07-21 07:00")]
    past_edge = winds_at_pass(make_wind(), tw("2023-07-21 06:30:01"))
    assert past_edge["time_tw"].tolist() == [tw("2023-07-21 07:00")]


def test_smaller_max_gap_can_return_nothing():
    assert winds_at_pass(make_wind(), tw("2023-07-21 10:25"), max_gap_min=10).empty


def test_every_minute_of_the_day_gets_one_or_two_observations():
    wind = make_wind()
    for minutes in range(2 * 60, 22 * 60):
        t = tw("2023-07-21 00:00") + pd.Timedelta(minutes=minutes)
        assert len(winds_at_pass(wind, t)) in (1, 2), t


def test_pass_time_without_timezone_raises():
    with pytest.raises(ValueError):
        winds_at_pass(make_wind(), pd.Timestamp("2023-07-21 06:00"))


# ---------- build_wind_at_passes ----------

def stations_df(*rows):
    return pd.DataFrame(list(rows), columns=["code", "name", "lat", "lon"])


def timeline_df(time_tw="2023-07-21 05:53:00+08:00", time_utc="2023-07-20 21:53:00+00:00",
                sensor="S1", covers=True):
    return pd.DataFrame([{"sensor": sensor, "time_tw": time_tw, "time_utc": time_utc, "covers_wreck": covers}])


def test_build_one_row_per_station_with_own_values():
    wind = pd.concat([make_wind("A", ws=2.0, wd=90.0), make_wind("B", ws=5.0, wd=270.0)])
    stations = stations_df(("A", "甲", WRECK_LAT, WRECK_LON), ("B", "乙", WRECK_LAT, WRECK_LON + 0.1))
    out = build_wind_at_passes(timeline_df(), wind, stations)
    assert out["station"].tolist() == ["A", "B"]
    assert out["ws_ms"].tolist() == [2.0, 5.0]
    assert out["wd_deg"].tolist() == [90.0, 270.0]
    assert out["gap_min"].tolist() == [0.0, 0.0]


def test_build_distance_to_wreck():
    stations = stations_df(("A", "甲", WRECK_LAT, WRECK_LON), ("B", "乙", WRECK_LAT, WRECK_LON + 0.1))
    out = build_wind_at_passes(timeline_df(), make_wind("A"), stations)
    assert out.loc[out["station"] == "A", "dist_km"].iloc[0] == 0.0
    assert out.loc[out["station"] == "B", "dist_km"].iloc[0] == pytest.approx(10.3, abs=0.1)


def test_build_carries_pass_columns():
    out = build_wind_at_passes(timeline_df(sensor="S2", covers=False), make_wind("A"),
                               stations_df(("A", "甲", WRECK_LAT, WRECK_LON)))
    assert out.iloc[0]["sensor"] == "S2"
    assert not out.iloc[0]["covers_wreck"]
    assert out.iloc[0]["time_tw"] == "2023-07-21 05:53:00+08:00"


def test_build_station_without_data_keeps_an_empty_row():
    out = build_wind_at_passes(timeline_df(), make_wind("A"),
                               stations_df(("A", "甲", WRECK_LAT, WRECK_LON), ("C", "丙", WRECK_LAT, WRECK_LON)))
    c = out[out["station"] == "C"]
    assert len(c) == 1 and pd.isna(c.iloc[0]["obs_time_tw"]) and math.isnan(c.iloc[0]["ws_ms"])
    assert len(out[out["station"] == "A"]) == 1


def test_build_tie_gives_two_rows_for_that_station():
    # 10:25 台灣時間 = 02:25 UTC
    out = build_wind_at_passes(timeline_df("2023-07-21 10:25:00+08:00", "2023-07-21 02:25:00+00:00"),
                               make_wind("A"), stations_df(("A", "甲", WRECK_LAT, WRECK_LON)))
    assert out["gap_min"].tolist() == [-25.0, 25.0]


def test_build_missing_observation_value_is_kept_as_nan():
    wind = make_wind("A")
    wind.loc[wind["time_tw"] == tw("2023-07-21 06:00"), "ws_ms"] = float("nan")
    out = build_wind_at_passes(timeline_df(), wind, stations_df(("A", "甲", WRECK_LAT, WRECK_LON)))
    assert len(out) == 1 and math.isnan(out.iloc[0]["ws_ms"])
    assert out.iloc[0]["obs_time_tw"] == tw("2023-07-21 06:00")
