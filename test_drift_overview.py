import numpy as np
import pandas as pd
import pytest

import drift_overview as o


def particles(rows):
    df = pd.DataFrame(rows, columns=["time_utc", "particle", "lon", "lat", "status"])
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    return df


def test_parse_run_args_ok():
    assert o.parse_run_args(["A=a.csv", "B=dir/b.csv"]) == {"A": "a.csv", "B": "dir/b.csv"}


@pytest.mark.parametrize("bad", ["noequals", "=path", "name="])
def test_parse_run_args_rejects_bad_format(bad):
    with pytest.raises(ValueError, match="名稱=路徑"):
        o.parse_run_args([bad])


def test_parse_run_args_rejects_duplicate_name():
    with pytest.raises(ValueError, match="重複"):
        o.parse_run_args(["A=a.csv", "A=b.csv"])


def test_parse_run_args_keeps_equals_in_path():
    assert o.parse_run_args(["A=x=y.csv"]) == {"A": "x=y.csv"}


def test_centroid_at_is_mean_of_positioned_particles():
    p = particles([("2023-07-24 02:00", 0, 120.0, 22.0, "active"), ("2023-07-24 02:00", 1, 121.0, 24.0, "active"),
                   ("2023-07-24 02:00", 2, np.nan, np.nan, "missing_data")])
    assert o.centroid_at(p, pd.Timestamp("2023-07-24 02:25", tz="UTC")) == (120.5, 23.0)


def test_centroid_at_picks_nearest_output_time():
    p = particles([("2023-07-24 02:00", 0, 120.0, 22.0, "active"), ("2023-07-24 03:00", 0, 121.0, 23.0, "active")])
    assert o.centroid_at(p, pd.Timestamp("2023-07-24 02:40", tz="UTC")) == (121.0, 23.0)


def test_centroid_at_none_when_too_far():
    p = particles([("2023-07-24 02:00", 0, 120.0, 22.0, "active")])
    assert o.centroid_at(p, pd.Timestamp("2023-07-24 04:00", tz="UTC")) is None
    assert o.centroid_at(p, pd.Timestamp("2023-07-24 02:30", tz="UTC"), max_gap_min=30) == (120.0, 22.0)
    assert o.centroid_at(p, pd.Timestamp("2023-07-24 02:31", tz="UTC"), max_gap_min=30) is None


def test_centroid_at_none_when_no_positions():
    p = particles([("2023-07-24 02:00", 0, np.nan, np.nan, "missing_data")])
    assert o.centroid_at(p, pd.Timestamp("2023-07-24 02:00", tz="UTC")) is None


def test_official_points_are_southeast_of_wreck_and_move_away():
    from drift_compare import bearing_deg
    from drone import haversine_km
    from event import ANGEL
    pts = [c["official"] for c in o.COMPARE]
    b = [bearing_deg(ANGEL.lat, ANGEL.lon, la, lo) for la, lo in pts]
    d = [haversine_km(ANGEL.lat, ANGEL.lon, la, lo) for la, lo in pts]
    assert all(135 < x < 180 for x in b)
    assert d[0] < d[1]
    assert 40 < d[0] < 60 and 120 < d[1] < 160


def test_literature_direction_matches_drift_compare():
    assert set(o.REFERENCE_DIRECTION.values()) == {o.LITERATURE_DIRECTION}


def test_centroid_at_uses_mean_not_median():
    p = particles([("2023-07-24 02:00", 0, 120.0, 22.0, "active"), ("2023-07-24 02:00", 1, 120.0, 22.0, "active"),
                   ("2023-07-24 02:00", 2, 123.0, 25.0, "active")])
    assert o.centroid_at(p, pd.Timestamp("2023-07-24 02:00", tz="UTC")) == pytest.approx((121.0, 23.0))


def test_centroid_at_ignores_particle_with_only_one_coordinate():
    p = particles([("2023-07-24 02:00", 0, 120.0, 22.0, "active"), ("2023-07-24 02:00", 1, 130.0, np.nan, "active")])
    assert o.centroid_at(p, pd.Timestamp("2023-07-24 02:00", tz="UTC")) == (120.0, 22.0)


def test_compare_time_utc_is_taiwan_minus_eight_hours():
    assert o.compare_time_utc(o.COMPARE[0]) == pd.Timestamp("2023-07-23 18:30", tz="UTC")
    assert o.compare_time_utc(o.COMPARE[1]) == pd.Timestamp("2023-07-25 11:30", tz="UTC")


def test_compare_markers_and_labels_are_distinct():
    assert len({c["marker"] for c in o.COMPARE}) == len(o.COMPARE)
    assert len({c["label"] for c in o.COMPARE}) == len(o.COMPARE)


def test_run_styles_differ_in_colour_and_line_style():
    colours = [c for c, _ in o.RUN_STYLES]
    styles = [str(s) for _, s in o.RUN_STYLES]
    assert len(set(colours)) == len(colours) and len(set(styles)) == len(styles)


def test_points_table_has_model_and_official_rows_per_time():
    p = particles([("2023-07-23 18:30", 0, 120.2, 22.0, "active"), ("2023-07-23 18:30", 1, 120.2, 22.2, "active"),
                   ("2023-07-25 11:30", 0, 120.2, 21.0, "active"), ("2023-07-25 11:30", 1, 120.2, 21.2, "active")])
    t = o.points_table({"RUN": p}, (22.6, 120.2))
    assert t["run"].tolist() == ["RUN", "CWA (eyeballed)", "RUN", "CWA (eyeballed)"]
    assert t["time_tw"].tolist() == ["Jul 24 02:30 TW", "Jul 24 02:30 TW", "Jul 25 19:30 TW", "Jul 25 19:30 TW"]
    first = t.iloc[0]
    assert first["lat"] == pytest.approx(22.1) and first["bearing_deg"] == pytest.approx(180.0, abs=0.5)
    assert first["distance_km"] == pytest.approx(55.6, abs=0.5)
    assert t.iloc[3]["lat"] == 21.59 and t.iloc[3]["lon"] == 121.07


def test_points_table_missing_model_output_gives_nan_but_keeps_official():
    p = particles([("2023-07-23 18:30", 0, 120.2, 22.0, "active")])   # 7/25 沒有輸出
    t = o.points_table({"RUN": p}, (22.6, 120.2))
    row = t[(t["run"] == "RUN") & (t["time_tw"] == "Jul 25 19:30 TW")].iloc[0]
    assert np.isnan(row["lat"]) and np.isnan(row["distance_km"])
    assert t[(t["run"] == "CWA (eyeballed)")]["distance_km"].notna().all()


def test_points_table_columns_match_constant():
    t = o.points_table({}, (22.6, 120.2))
    assert t.columns.tolist() == o.TABLE_COLUMNS
