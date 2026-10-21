"""drift_compare.py 的測試：自己造粒子表與參考觀測，不讀 data/。"""
import numpy as np
import pandas as pd
import pytest

import drift_compare as dc

LAT0, LON0 = 22.6, 120.2
KM_PER_DEG_LAT = 111.19


def particles(rows):
    """rows: [(UTC 時間字串, 粒子編號, lon, lat, status), ...]"""
    df = pd.DataFrame(rows, columns=dc.PARTICLE_COLUMNS)
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    return df


# ---- 方位 ----

@pytest.mark.parametrize("dlat,dlon,expected", [(0.1, 0, 0), (0, 0.1, 90), (-0.1, 0, 180), (0, -0.1, 270)])
def test_bearing_cardinal_directions(dlat, dlon, expected):
    assert dc.bearing_deg(LAT0, LON0, LAT0 + dlat, LON0 + dlon) == pytest.approx(expected, abs=0.05)


def test_bearing_diagonal_is_between_the_two_axes():
    b = float(dc.bearing_deg(LAT0, LON0, LAT0 - 0.1, LON0 + 0.1))
    assert 90 < b < 180                      # 東南


def test_bearing_same_point_is_nan():
    assert np.isnan(dc.bearing_deg(LAT0, LON0, LAT0, LON0))


@pytest.mark.parametrize("a,b,d", [(350, 10, 20), (10, 350, 20), (135, 135, 0), (0, 180, 180), (90, 270, 180), (45, 135, 90)])
def test_angle_diff_wraps_around(a, b, d):
    assert dc.angle_diff_deg(a, b) == pytest.approx(d)


@pytest.mark.parametrize("deg,name", [
    (0, "N"), (22.4, "N"), (22.5, "NE"), (45, "NE"), (67.4, "NE"), (67.5, "E"), (90, "E"),
    (112.5, "SE"), (135, "SE"), (157.5, "S"), (180, "S"), (225, "SW"), (270, "W"),
    (315, "NW"), (337.4, "NW"), (337.5, "N"), (359.9, "N")])
def test_compass8_sector_boundaries(deg, name):
    assert dc.compass8(deg) == name


def test_compass8_missing_is_none():
    assert dc.compass8(np.nan) is None
    assert dc.compass8(None) is None


# ---- 讀檔 ----

def test_load_particles_sorts_and_parses_utc(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("time_utc,particle,lon,lat,status\n"
                 "2023-07-21 01:00:00+00:00,1,120.2,22.6,active\n"
                 "2023-07-21 00:00:00+00:00,1,120.2,22.6,active\n", encoding="utf-8")
    df = dc.load_particles(p)
    assert df["time_utc"].iloc[0] < df["time_utc"].iloc[1] and str(df["time_utc"].dt.tz) == "UTC"


def test_load_particles_rejects_missing_column(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("time_utc,particle,lon,lat\n2023-07-21 00:00:00+00:00,1,120.2,22.6\n", encoding="utf-8")
    with pytest.raises(ValueError, match="status"):
        dc.load_particles(p)


def test_load_particles_rejects_duplicate(tmp_path):
    p = tmp_path / "p.csv"
    row = "2023-07-21 00:00:00+00:00,1,120.2,22.6,active\n"
    p.write_text("time_utc,particle,lon,lat,status\n" + row + row, encoding="utf-8")
    with pytest.raises(ValueError, match="多次"):
        dc.load_particles(p)


# ---- 單一時間的統計 ----

T0 = "2023-07-24 02:30:00+00:00"


def east_line():
    """三顆粒子在沉船正東 0.05、0.10、0.15 度（同緯度）。"""
    return particles([(T0, i, LON0 + 0.05 * (i + 1), LAT0, "active") for i in range(3)])


def test_summary_centroid_bearing_and_distances():
    s = dc.summarize_at(east_line(), "2023-07-24 02:25:41+00:00", LAT0, LON0)
    km_per_deg_lon = KM_PER_DEG_LAT * np.cos(np.radians(LAT0))
    assert s["centroid_lon"] == pytest.approx(LON0 + 0.10) and s["centroid_lat"] == pytest.approx(LAT0)
    assert s["centroid_bearing_deg"] == pytest.approx(90, abs=0.05) and s["centroid_compass"] == "E"
    assert s["centroid_distance_km"] == pytest.approx(0.10 * km_per_deg_lon, rel=0.01)
    assert s["max_distance_km"] == pytest.approx(0.15 * km_per_deg_lon, rel=0.01)
    assert s["n_particles"] == 3 and s["n_with_position"] == 3 and s["n_stranded"] == 0
    assert s["gap_min"] == pytest.approx(4.3167, abs=0.01)


def test_p95_uses_percentile_not_max():
    rows = [(T0, i, LON0, LAT0 + 0.01 * i, "active") for i in range(21)]   # 距離 0 到 20 步，每步約 1.1119 km
    s = dc.summarize_at(particles(rows), T0, LAT0, LON0)
    assert s["max_distance_km"] == pytest.approx(0.20 * KM_PER_DEG_LAT, rel=1e-3)
    assert s["p95_distance_km"] == pytest.approx(0.19 * KM_PER_DEG_LAT, rel=1e-3)


def test_particles_without_position_are_excluded_but_counted_in_total():
    rows = [(T0, 0, LON0 + 0.1, LAT0, "active"), (T0, 1, np.nan, np.nan, "missing_data")]
    s = dc.summarize_at(particles(rows), T0, LAT0, LON0)
    assert s["n_particles"] == 2 and s["n_with_position"] == 1
    assert s["centroid_lon"] == pytest.approx(LON0 + 0.1)


def test_stranded_particles_keep_their_position_and_are_counted():
    rows = [(T0, 0, LON0 + 0.1, LAT0, "active"), (T0, 1, LON0 + 0.2, LAT0, "stranded")]
    s = dc.summarize_at(particles(rows), T0, LAT0, LON0)
    assert s["n_with_position"] == 2 and s["n_stranded"] == 1
    assert s["centroid_lon"] == pytest.approx(LON0 + 0.15)


def test_position_needs_both_lon_and_lat():
    rows = [(T0, 0, LON0 + 0.1, LAT0, "active"), (T0, 1, LON0 + 0.2, np.nan, "active")]
    s = dc.summarize_at(particles(rows), T0, LAT0, LON0)
    assert s["n_with_position"] == 1 and s["centroid_lon"] == pytest.approx(LON0 + 0.1)


def test_stranded_count_only_includes_particles_with_position():
    rows = [(T0, 0, LON0 + 0.1, LAT0, "active"), (T0, 1, np.nan, np.nan, "stranded")]
    assert dc.summarize_at(particles(rows), T0, LAT0, LON0)["n_stranded"] == 0


def test_n_particles_counts_every_particle_in_the_run_not_just_this_time():
    rows = [("2023-07-24 01:30:00+00:00", 0, LON0, LAT0, "active"), ("2023-07-24 01:30:00+00:00", 1, LON0, LAT0, "active"),
            (T0, 0, LON0 + 0.1, LAT0, "active")]
    s = dc.summarize_at(particles(rows), T0, LAT0, LON0)
    assert s["n_particles"] == 2 and s["n_with_position"] == 1


def test_centroid_is_the_mean_not_the_median():
    rows = [(T0, i, LON0 + d, LAT0, "active") for i, d in enumerate((0.05, 0.10, 0.30))]
    assert dc.summarize_at(particles(rows), T0, LAT0, LON0)["centroid_lon"] == pytest.approx(LON0 + 0.15)


def test_all_particles_without_position_gives_nan_stats():
    s = dc.summarize_at(particles([(T0, 0, np.nan, np.nan, "missing_data")]), T0, LAT0, LON0)
    assert s["n_with_position"] == 0 and np.isnan(s["centroid_lat"]) and s["centroid_compass"] is None
    assert np.isnan(s["max_distance_km"]) and np.isnan(s["p95_distance_km"])


def test_picks_nearest_output_time_and_tie_takes_earlier():
    rows = ([("2023-07-24 02:00:00+00:00", 0, LON0 + 0.1, LAT0, "active")]
            + [("2023-07-24 03:00:00+00:00", 0, LON0 + 0.2, LAT0, "active")])
    p = particles(rows)
    assert dc.summarize_at(p, "2023-07-24 02:40:00+00:00", LAT0, LON0)["centroid_lon"] == pytest.approx(LON0 + 0.2)
    tie = dc.summarize_at(p, "2023-07-24 02:30:00+00:00", LAT0, LON0)
    assert tie["gap_min"] == pytest.approx(-30.0) and tie["centroid_lon"] == pytest.approx(LON0 + 0.1)
    assert dc.summarize_at(p.iloc[::-1].reset_index(drop=True), "2023-07-24 02:30:00+00:00",
                           LAT0, LON0)["gap_min"] == pytest.approx(-30.0)


def test_no_output_time_within_max_gap_gives_none():
    assert dc.summarize_at(east_line(), "2023-07-24 03:01:00+00:00", LAT0, LON0) is None
    assert dc.summarize_at(east_line(), "2023-07-24 03:00:00+00:00", LAT0, LON0) is not None
    assert dc.summarize_at(east_line(), "2023-07-24 03:00:00+00:00", LAT0, LON0, max_gap_min=29) is None


# ---- 與文獻並列 ----

def make_passes():
    return pd.DataFrame({"pass_id": ["S2_A", "S1_B", "S1_C"],
                         "time_utc": ["2023-07-24 02:25:41+00:00", "2023-07-26 22:01:24+00:00",
                                      "2023-08-10 00:00:00+00:00"]})


def make_matched():
    base = {"sensor": "S2", "date": "x", "unit": "", "source": "s", "note": "", "pass_time_tw": ""}
    return pd.DataFrame([
        {**base, "ref_id": "jpgu2025-s2-0724-area", "variable": "oil_area", "value": 20.3, "pass_id": "S2_A", "match": "matched"},
        {**base, "ref_id": "jpgu2025-s1-0727-area", "variable": "oil_area", "value": 10.7, "pass_id": "S1_B", "match": "matched"},
        {**base, "ref_id": "jpgu2025-s1-0727-maxdist", "variable": "oil_max_distance", "value": 26.5, "pass_id": "S1_B", "match": "matched"},
        {**base, "ref_id": "other", "variable": "oil_area", "value": 1.0, "pass_id": None, "match": "no_pass"},
    ])


def southeast_run():
    """粒子在沉船東南方：兩個過境時刻各一組輸出。"""
    rows = []
    for t, k in (("2023-07-24 02:30:00+00:00", 1), ("2023-07-26 22:00:00+00:00", 2)):
        rows += [(t, i, LON0 + 0.1 * k, LAT0 - 0.1 * k, "active") for i in range(3)]
    return particles(rows)


def test_compare_runs_row_per_run_and_matched_pass():
    out = dc.compare_runs({"a": southeast_run(), "b": southeast_run()}, make_matched(), make_passes(), LAT0, LON0)
    assert list(out.columns) == dc.RESULT_COLUMNS
    assert sorted(zip(out["run_id"], out["pass_id"])) == [("a", "S1_B"), ("a", "S2_A"), ("b", "S1_B"), ("b", "S2_A")]


def test_compare_runs_attaches_reference_direction_distance_and_angle_diff():
    out = dc.compare_runs({"a": southeast_run()}, make_matched(), make_passes(), LAT0, LON0).set_index("pass_id")
    assert out.loc["S2_A", "ref_direction"] == "SE" and np.isnan(out.loc["S2_A", "ref_max_distance_km"])
    assert out.loc["S1_B", "ref_direction"] == "SE" and out.loc["S1_B", "ref_max_distance_km"] == 26.5
    b = out.loc["S2_A", "centroid_bearing_deg"]
    assert 90 < b < 180 and out.loc["S2_A", "centroid_compass"] in ("E", "SE", "S")
    assert out.loc["S2_A", "bearing_diff_to_ref_deg"] == pytest.approx(abs(b - 135.0))
    assert out.loc["S1_B", "max_distance_km"] > out.loc["S2_A", "max_distance_km"]


def test_compare_runs_opposite_direction_gives_large_angle_diff():
    nw = southeast_run().assign(lon=lambda d: 2 * LON0 - d["lon"], lat=lambda d: 2 * LAT0 - d["lat"])
    out = dc.compare_runs({"nw": nw}, make_matched(), make_passes(), LAT0, LON0).set_index("pass_id")
    assert out.loc["S2_A", "centroid_compass"] == "NW"
    assert out.loc["S2_A", "bearing_diff_to_ref_deg"] > 150


def test_compare_runs_without_output_near_pass_gives_nan_row():
    late = southeast_run()
    late["time_utc"] = late["time_utc"] + pd.Timedelta(hours=5)
    out = dc.compare_runs({"a": late}, make_matched(), make_passes(), LAT0, LON0)
    assert len(out) == 2 and out["centroid_lat"].isna().all() and out["sim_time_utc"].isna().all()
    assert set(out["ref_direction"]) == {"SE"}


def test_compare_runs_skips_unmatched_references():
    out = dc.compare_runs({"a": southeast_run()}, make_matched(), make_passes(), LAT0, LON0)
    assert "S1_C" not in set(out["pass_id"])        # 沒被任何文獻配對的過境不出現
    assert len(out) == 2


def test_compare_runs_unknown_pass_raises():
    m = make_matched()
    m.loc[0, "pass_id"] = "S2_ZZZ"
    with pytest.raises(ValueError, match="過境表"):
        dc.compare_runs({"a": southeast_run()}, m, make_passes(), LAT0, LON0)


def test_compare_runs_conflicting_reference_directions_raise(monkeypatch):
    monkeypatch.setitem(dc.REFERENCE_DIRECTION, "jpgu2025-s1-0727-maxdist", "NW")
    with pytest.raises(ValueError, match="矛盾"):
        dc.compare_runs({"a": southeast_run()}, make_matched(), make_passes(), LAT0, LON0)


def test_compare_runs_two_max_distances_for_one_pass_raise():
    m = make_matched()
    extra = m.iloc[[2]].copy()
    extra["ref_id"] = "dup"
    with pytest.raises(ValueError, match="最遠距離"):
        dc.compare_runs({"a": southeast_run()}, pd.concat([m, extra], ignore_index=True), make_passes(), LAT0, LON0)


def test_compare_runs_ignores_rows_that_are_not_matched_even_if_they_carry_a_pass_id():
    m = make_matched()
    m.loc[3, ["pass_id", "match"]] = ["S1_C", "ambiguous"]
    out = dc.compare_runs({"a": southeast_run()}, m, make_passes(), LAT0, LON0)
    assert "S1_C" not in set(out["pass_id"])
