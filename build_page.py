"""把整理好的資料嵌進頁面模板，產生單一 HTML 檔（site/index.html）。

預設輸出可以直接用瀏覽器打開的完整頁面；加 --fragment 則輸出不含文件外框的版本（發佈成 Artifact 用）。
用法：python build_page.py --data data --template site/template.html --out site/index.html [--fragment]
"""
import argparse

from event import add_event_args, event_from_args
from page_data import load_data, to_json

PLACEHOLDER = "/*PAGE_DATA*/null"
WRAPPER_HEAD = '<!doctype html>\n<html lang="zh-Hant">\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'


def embed(template, data_json):
    """把 JSON 文字放進模板。「</」要跳脫，否則資料裡出現 </script> 會提早結束 script。"""
    if template.count(PLACEHOLDER) != 1:
        raise ValueError(f"模板裡必須剛好有一個 {PLACEHOLDER}")
    return template.replace(PLACEHOLDER, data_json.replace("</", "<\\/"))


def build_html(template, data_json, fragment=False):
    html = embed(template, data_json)
    return html if fragment else WRAPPER_HEAD + html + "\n</html>\n"


def main():
    ap = argparse.ArgumentParser(description="產生統一介面頁")
    ap.add_argument("--data", default="data", help="放各階段輸出的資料夾")
    ap.add_argument("--template", default="site/template.html")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fragment", action="store_true", help="不含文件外框（Artifact 用）")
    add_event_args(ap)
    args = ap.parse_args()
    data_json = to_json(load_data(args.data, event_from_args(ap, args)))
    with open(args.template, encoding="utf-8") as f:
        template = f.read()
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_html(template, data_json, args.fragment))
    print(f"已寫入 {args.out}（{len(data_json) / 1024:.0f} KB 資料）")


if __name__ == "__main__":
    main()
