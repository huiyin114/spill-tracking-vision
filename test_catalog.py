"""catalog.py 的單元測試。用法：pytest

測試資料全部在這裡自己造，不讀 data/raw/（那個資料夾沒有納入版控）。
"""
import json

import pandas as pd
import pytest

from catalog import group_passes, load_items
from event import WRECK_LAT, WRECK_LON


# ---------- 造測試資料的小工具 ----------

def square(half=0.1):
    """以沉船為中心的正方形多邊形：沉船一定在裡面。"""
    x0, x1 = WRECK_LON - half, WRECK_LON + half
    y0, y1 = WRECK_LAT - half, WRECK_LAT + half
    return [[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]


def triangle_missing_wreck():
    """外框（bbox）包含沉船，但三角形本身不包含沉船。

    三角形的斜邊在沉船上方 0.1 度處，沉船落在三角形外。
    """
    x, y = WRECK_LON, WRECK_LAT
    return [[(x - 0.2, y - 0.1), (x + 0.2, y + 0.3), (x - 0.2, y + 0.3), (x - 0.2, y - 0.1)]]


def far_square():
    """離沉船很遠的正方形（外框也不含沉船）。"""
    x, y = WRECK_LON + 2, WRECK_LAT + 2
    return [[(x - 0.1, y - 0.1), (x + 0.1, y - 0.1), (x + 0.1, y + 0.1), (x - 0.1, y + 0.1), (x - 0.1, y - 0.1)]]


def feature(id_, time, rings, **props):
    """造一筆 STAC feature；bbox 由多邊形頂點算出（與真實資料的關係相同）。"""
    xs = [p[0] for p in rings[0]]
    ys = [p[1] for p in rings[0]]
    properties = {"datetime": time, "platform": "sentinel-test", "sat:orbit_state": "descending"}
    properties.update(props)
    return {
        "id": id_,
        "properties": properties,
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
        "geometry": {"type": "Polygon", "coordinates": rings},
    }


def write_stac(tmp_path, features, links=None):
    path = tmp_path / "stac.json"
    path.write_text(json.dumps({"features": features, "links": links or []}), encoding="utf-8")
    return str(path)


# ---------- load_items ----------

def test_load_items_sorts_by_time(tmp_path):
    path = write_stac(tmp_path, [
        feature("later", "2023-07-24T02:25:41Z", square()),
        feature("earlier", "2023-07-19T02:25:39Z", square()),
    ])
    items = load_items(path)
    assert list(items["id"]) == ["earlier", "later"]


def test_load_items_missing_optional_fields_become_none(tmp_path):
    # Sentinel-1 沒有圖幅與雲量；Sentinel-2 沒有成像模式
    path = write_stac(tmp_path, [feature("s1", "2023-07-22T21:53:00Z", square(), **{"sar:instrument_mode": "IW"})])
    row = load_items(path).iloc[0]
    assert row["mode"] == "IW"
    assert row["tile"] is None
    assert pd.isna(row["cloud_cover"])


def test_load_items_rejects_incomplete_first_page(tmp_path):
    path = write_stac(tmp_path, [feature("a", "2023-07-19T02:25:39Z", square())],
                      links=[{"rel": "next", "href": "https://example.invalid/page2"}])
    with pytest.raises(ValueError, match="只有第一頁"):
        load_items(path)


def test_covers_wreck_true_when_polygon_contains_wreck(tmp_path):
    path = write_stac(tmp_path, [feature("a", "2023-07-19T02:25:39Z", square())])
    assert bool(load_items(path).iloc[0]["covers_wreck"]) is True


def test_covers_wreck_false_when_only_bbox_contains_wreck(tmp_path):
    # 外框含沉船、多邊形不含：只看外框會誤判，這正是改用多邊形的原因
    rings = triangle_missing_wreck()
    xs, ys = [p[0] for p in rings[0]], [p[1] for p in rings[0]]
    assert min(xs) <= WRECK_LON <= max(xs) and min(ys) <= WRECK_LAT <= max(ys)  # 前提：外框確實含沉船

    path = write_stac(tmp_path, [feature("a", "2023-07-19T02:25:39Z", rings)])
    assert bool(load_items(path).iloc[0]["covers_wreck"]) is False


def test_covers_wreck_false_when_far_away(tmp_path):
    path = write_stac(tmp_path, [feature("a", "2023-07-19T02:25:39Z", far_square())])
    assert bool(load_items(path).iloc[0]["covers_wreck"]) is False


# ---------- group_passes ----------

def make_items(tmp_path, specs):
    """specs: [(id, 時間, 多邊形, 額外屬性), ...]"""
    return load_items(write_stac(tmp_path, [feature(i, t, r, **p) for i, t, r, p in specs]))


def test_frames_seconds_apart_are_one_pass(tmp_path):
    items = make_items(tmp_path, [
        ("f1", "2023-07-22T21:53:01Z", square(), {}),
        ("f2", "2023-07-22T21:53:26Z", square(), {}),  # 相隔 25 秒
    ])
    passes = group_passes(items)
    assert len(passes) == 1
    assert passes.iloc[0]["n_items"] == 2


def test_gap_longer_than_threshold_starts_new_pass(tmp_path):
    items = make_items(tmp_path, [
        ("a", "2023-07-22T21:53:00Z", square(), {}),
        ("b", "2023-07-22T22:03:01Z", square(), {}),  # 相隔 10 分 1 秒
    ])
    assert len(group_passes(items)) == 2


def test_gap_exactly_threshold_stays_same_pass(tmp_path):
    items = make_items(tmp_path, [
        ("a", "2023-07-22T21:53:00Z", square(), {}),
        ("b", "2023-07-22T22:03:00Z", square(), {}),  # 剛好 10 分鐘
    ])
    assert len(group_passes(items)) == 1


def test_pass_covers_wreck_if_any_item_covers(tmp_path):
    items = make_items(tmp_path, [
        ("hit", "2023-07-22T21:53:00Z", square(), {}),
        ("miss", "2023-07-22T21:53:25Z", far_square(), {}),
    ])
    assert bool(group_passes(items).iloc[0]["covers_wreck"]) is True


def test_pass_not_covering_wreck(tmp_path):
    items = make_items(tmp_path, [("miss", "2023-07-22T21:53:00Z", far_square(), {})])
    assert bool(group_passes(items).iloc[0]["covers_wreck"]) is False


def test_cloud_cover_min_ignores_tiles_not_covering_wreck(tmp_path):
    # 涵蓋沉船的圖幅雲量 48 與 59；不涵蓋的圖幅雲量只有 5，不應被當成最小值
    items = make_items(tmp_path, [
        ("tile_a", "2023-07-24T02:25:41Z", square(), {"eo:cloud_cover": 59.0}),
        ("tile_b", "2023-07-24T02:25:41Z", square(), {"eo:cloud_cover": 48.0}),
        ("tile_c", "2023-07-24T02:25:41Z", far_square(), {"eo:cloud_cover": 5.0}),
    ])
    assert group_passes(items).iloc[0]["cloud_cover_min"] == 48.0


def test_cloud_cover_min_is_nan_without_cloud_data(tmp_path):
    items = make_items(tmp_path, [("s1", "2023-07-22T21:53:00Z", square(), {})])
    assert pd.isna(group_passes(items).iloc[0]["cloud_cover_min"])


def test_time_tw_is_utc_plus_8(tmp_path):
    items = make_items(tmp_path, [("a", "2023-07-19T02:25:39Z", square(), {})])
    tw = group_passes(items).iloc[0]["time_tw"]
    assert (tw.hour, tw.minute) == (10, 25)
    assert tw.utcoffset() == pd.Timedelta(hours=8)
