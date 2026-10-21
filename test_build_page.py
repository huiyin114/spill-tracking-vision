"""build_page.py 的測試：自己造模板，不讀 site/ 與 data/。"""
import json

import pytest

import build_page
from build_page import PLACEHOLDER, build_html, embed

TEMPLATE = f'<title>t</title>\n<script type="application/json" id="data">{PLACEHOLDER}</script>\n'


def test_embed_puts_data_in_place_of_placeholder():
    out = embed(TEMPLATE, '{"a":1}')
    assert '{"a":1}' in out and PLACEHOLDER not in out


def test_embedded_data_cannot_close_the_script_tag():
    data = json.dumps({"note": "</script><b>x</b>"})
    out = embed(TEMPLATE, data)
    assert out.count("</script>") == 1                       # 只有模板自己的那個
    body = out.split('id="data">')[1].split("</script>")[0]
    assert json.loads(body)["note"] == "</script><b>x</b>"   # 跳脫後瀏覽器讀到的仍是原文


def test_embedded_json_round_trips_chinese_and_null():
    data = json.dumps({"name": "天使輪", "x": None}, ensure_ascii=False)
    body = embed(TEMPLATE, data).split('id="data">')[1].split("</script>")[0]
    assert json.loads(body) == {"name": "天使輪", "x": None}


@pytest.mark.parametrize("template", ["<p>no placeholder</p>", PLACEHOLDER + PLACEHOLDER])
def test_template_needs_exactly_one_placeholder(template):
    with pytest.raises(ValueError):
        embed(template, "{}")


def test_full_page_has_doctype_charset_viewport():
    html = build_html(TEMPLATE, "{}")
    assert html.startswith("<!doctype html>")
    assert 'charset="utf-8"' in html and 'name="viewport"' in html and html.rstrip().endswith("</html>")


def test_fragment_has_no_document_frame():
    html = build_html(TEMPLATE, "{}", fragment=True)
    assert "<!doctype" not in html and "<html" not in html and "<body" not in html


def test_data_with_dollar_or_backslash_is_inserted_verbatim():
    out = embed(TEMPLATE, r'{"p":"C:\\x $1 \\1"}')
    assert r'C:\\x $1 \\1' in out
