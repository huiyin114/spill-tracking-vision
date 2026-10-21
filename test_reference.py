"""reference.py 的測試：自己造資料，不讀 data/。"""
import pandas as pd
import pytest

from reference import COLUMNS, VARIABLES, load_reference, match_passes

GOOD = {"ref_id": "r1", "sensor": "S2", "date": "2023-07-24", "variable": "oil_area", "value": "20.3",
        "unit": "km2", "source": "某文獻", "note": "估計值"}


def write(tmp_path, *rows, columns=COLUMNS):
    p = tmp_path / "ref.csv"
    pd.DataFrame(list(rows), columns=columns).to_csv(p, index=False, encoding="utf-8-sig")
    return str(p)


def row(**kw):
    return {**GOOD, **kw}


# ---------- load_reference ----------

def test_load_good_file(tmp_path):
    ref = load_reference(write(tmp_path, row(), row(ref_id="r2", variable="oil_max_distance", unit="km", value="26.5")))
    assert list(ref.columns) == COLUMNS
    assert list(ref["value"]) == [20.3, 26.5]
    assert ref["value"].dtype == "float64"


def test_load_keeps_chinese_note(tmp_path):
    assert load_reference(write(tmp_path, row(note="油膜往東南")))["note"].iloc[0] == "油膜往東南"


def test_zero_value_is_allowed(tmp_path):
    assert load_reference(write(tmp_path, row(value="0")))["value"].iloc[0] == 0


@pytest.mark.parametrize("kw, text", [
    ({"ref_id": "r1"}, "重複"),                       # 配合下面加第二列
])
def test_duplicate_ref_id_rejected(tmp_path, kw, text):
    with pytest.raises(ValueError, match=text):
        load_reference(write(tmp_path, row(), row(**kw)))


@pytest.mark.parametrize("kw, text", [
    ({"sensor": "S3"}, "sensor"),
    ({"sensor": None}, "sensor"),
    ({"variable": "oil_volume"}, "未登記"),
    ({"variable": None}, "未登記"),
    ({"unit": "m2"}, "單位"),
    ({"date": "2023/07/24"}, "date"),
    ({"date": "2023-13-01"}, "date"),
    ({"value": "abc"}, "value"),
    ({"value": "-1"}, "value"),
    ({"value": None}, "value"),
    ({"value": "inf"}, "value"),
    ({"source": None}, "出處"),
    ({"source": "  "}, "出處"),
    ({"ref_id": None}, "編號"),
])
def test_invalid_rows_rejected(tmp_path, kw, text):
    with pytest.raises(ValueError, match=text):
        load_reference(write(tmp_path, row(**kw)))


def test_missing_column_rejected(tmp_path):
    cols = [c for c in COLUMNS if c != "unit"]
    with pytest.raises(ValueError, match="缺少欄位"):
        load_reference(write(tmp_path, {k: GOOD[k] for k in cols}, columns=cols))


def test_unit_checked_per_variable(tmp_path):
    with pytest.raises(ValueError, match="單位"):
        load_reference(write(tmp_path, row(variable="oil_max_distance", unit="km2")))


def test_registry_has_both_variables():
    assert VARIABLES == {"oil_area": "km2", "oil_max_distance": "km"}


# ---------- match_passes ----------

def passes_df(*items):
    """items: (pass_id, sensor, UTC 時間字串)"""
    rows = [{"pass_id": i, "sensor": s, "time_utc": t,
             "time_tw": str(pd.Timestamp(t, tz="UTC").tz_convert("Asia/Taipei"))} for i, s, t in items]
    return pd.DataFrame(rows)


def ref_df(**kw):
    return pd.DataFrame([{**GOOD, "value": 20.3, **kw}])


def test_match_single_candidate_same_utc_date():
    out = match_passes(ref_df(date="2023-07-24"), passes_df(("p1", "S2", "2023-07-24 02:25:41+00:00")))
    assert out["match"].iloc[0] == "matched" and out["pass_id"].iloc[0] == "p1"
    assert out["pass_time_tw"].iloc[0].startswith("2023-07-24 10:25")


def test_match_by_taiwan_date_when_utc_date_differs():
    # UTC 7/26 22:01 = 台灣 7/27 06:01：文獻寫 7/27 時只有台灣日期對得上
    out = match_passes(ref_df(sensor="S1", date="2023-07-27"), passes_df(("p1", "S1", "2023-07-26 22:01:24+00:00")))
    assert out["match"].iloc[0] == "matched" and out["pass_id"].iloc[0] == "p1"


def test_match_by_utc_date_when_taiwan_date_differs():
    # UTC 7/24 20:00 = 台灣 7/25 04:00；文獻寫 7/24 只有 UTC 日期對得上
    out = match_passes(ref_df(date="2023-07-24"), passes_df(("p1", "S2", "2023-07-24 20:00:00+00:00")))
    assert out["match"].iloc[0] == "matched"


def test_match_ignores_other_sensor():
    out = match_passes(ref_df(sensor="S2", date="2023-07-24"), passes_df(("p1", "S1", "2023-07-24 02:00:00+00:00")))
    assert out["match"].iloc[0] == "no_pass" and pd.isna(out["pass_id"].iloc[0])


def test_no_pass_on_that_date():
    out = match_passes(ref_df(date="2023-07-24"), passes_df(("p1", "S2", "2023-07-30 02:00:00+00:00")))
    assert out["match"].iloc[0] == "no_pass"


def test_two_candidates_is_ambiguous_and_not_guessed():
    out = match_passes(ref_df(date="2023-07-24"), passes_df(
        ("p1", "S2", "2023-07-24 02:25:41+00:00"), ("p2", "S2", "2023-07-24 20:00:00+00:00")))
    assert out["match"].iloc[0] == "ambiguous" and pd.isna(out["pass_id"].iloc[0])


def test_same_pass_matching_both_dates_counts_once():
    # 台灣 7/24 10:25 = UTC 7/24 02:25：兩種日期都對上，仍只是一個候選
    out = match_passes(ref_df(date="2023-07-24"), passes_df(("p1", "S2", "2023-07-24 02:25:41+00:00")))
    assert out["match"].iloc[0] == "matched"


def test_two_references_can_share_one_pass():
    ref = pd.DataFrame([{**GOOD, "value": 1.0}, {**GOOD, "ref_id": "r2", "variable": "oil_max_distance", "unit": "km"}])
    out = match_passes(ref, passes_df(("p1", "S2", "2023-07-24 02:25:41+00:00")))
    assert list(out["pass_id"]) == ["p1", "p1"]


def test_match_keeps_reference_values_and_order():
    ref = pd.DataFrame([{**GOOD, "ref_id": "a", "value": 1.0}, {**GOOD, "ref_id": "b", "value": 2.0, "date": "2023-08-01"}])
    out = match_passes(ref, passes_df(("p1", "S2", "2023-07-24 02:25:41+00:00")))
    assert list(out["ref_id"]) == ["a", "b"] and list(out["value"]) == [1.0, 2.0]
    assert list(out["match"]) == ["matched", "no_pass"]


def test_match_empty_reference():
    out = match_passes(ref_df().iloc[0:0], passes_df(("p1", "S2", "2023-07-24 02:25:41+00:00")))
    assert out.empty and {"pass_id", "pass_time_tw", "match"} <= set(out.columns)
