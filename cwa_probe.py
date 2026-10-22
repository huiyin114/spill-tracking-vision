"""探測氣象署海象平台溢油個案的輸入場（zip 內的 NetCDF4），不下載整包。

背景：氣象署個案頁「天使輪」的 NetCDF 是 898.zip，約 14 GB，裡面是 2023 年 7 月整個月的海流、風、波浪等
輸入場（不是模擬結果）。zip 裡的檔案沒有壓縮（儲存方式 stored），NetCDF4 是 HDF5 格式，所以可以用 HTTP
的 Range 請求只讀需要的片段。這支程式先做最小的試探：
  1. 只讀 zip 的目錄，列出裡面的檔案與大小；
  2. 開指定的檔案（例如 UCURR.202307.nc），印出資料集、形狀、分塊、壓縮、座標、時間單位；
  3. 讀一個時間步、沉船點附近一小塊範圍，印出最近格點的值，以及實際下載了多少位元組。

這是「看一眼」，不存檔。結果要先貼給 AI 確認格式與時區，再決定怎麼抓整個範圍。

需要 h5py 與 requests（opendrift 環境已經有）。在 opendrift 環境執行：
  python cwa_probe.py --members
  python cwa_probe.py --member UCURR.202307.nc
  python cwa_probe.py --member U10M.202307.nc --time-index 0
"""
import argparse
import ssl
import struct
import time
import zipfile

import numpy as np

DEFAULT_URL = "https://ocean.cwa.gov.tw/V2/data/case/B_898/898.zip"
USER_AGENT = "Mozilla/5.0 (probe for student project; range requests)"


def data_offset(local_header, header_offset):
    """zip 的 local file header（至少 30 位元組）→ 檔案資料開始的位置。

    header 的第 26、28 位元組各是檔名長度與 extra 欄位長度（little-endian 2 位元組），
    資料接在 30 位元組固定部分、檔名、extra 之後。簽章不對就報錯。
    """
    if len(local_header) < 30 or local_header[:4] != b"PK\x03\x04":
        raise ValueError("不是 zip 的 local file header")
    name_len, extra_len = struct.unpack("<HH", local_header[26:30])
    return header_offset + 30 + name_len + extra_len


def relaxed_ssl_context():
    """憑證、主機名稱照樣驗證，只關掉 Python 3.13 起預設開啟的 X.509 嚴格檢查（VERIFY_X509_STRICT）。

    為什麼：有些政府網站的憑證缺少 Subject Key Identifier，嚴格檢查會直接拒絕
    （CERTIFICATE_VERIFY_FAILED: Missing Subject Key Identifier）。瀏覽器不檢查這一項。
    驗證憑證鏈與主機名稱沒有關掉。
    """
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except ImportError:
        pass
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def make_session(relax_x509=False):
    """requests 的 Session；relax_x509=True 時 https 使用 relaxed_ssl_context()。"""
    import requests
    from requests.adapters import HTTPAdapter

    session = requests.Session()
    if relax_x509:
        ctx = relaxed_ssl_context()

        class Adapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs["ssl_context"] = ctx
                super().init_poolmanager(*args, **kwargs)

        session.mount("https://", Adapter())
    return session


def index_window(values, center, half):
    """座標陣列（遞增或遞減）中，落在 center ± half 的索引範圍 slice。範圍內沒有格點就報錯。"""
    v = np.asarray(values, dtype=float)
    idx = np.where((v >= center - half) & (v <= center + half))[0]
    if idx.size == 0:
        raise ValueError(f"座標 {center} ± {half} 內沒有格點（範圍 {v.min()}–{v.max()}）")
    return slice(int(idx.min()), int(idx.max()) + 1)


def nearest_index(values, target):
    """離 target 最近的索引；一樣近取較小的索引。"""
    v = np.asarray(values, dtype=float)
    return int(np.argmin(np.abs(v - target)))


class HttpRangeFile:
    """用 HTTP Range 請求讀遠端檔案的唯讀檔案物件（可 seek），以區塊快取。

    offset、length 讓它只呈現遠端檔案的一段（例如 zip 裡某個沒壓縮的成員）。
    bytes_fetched 與 requests 記錄實際下載量。
    """

    def __init__(self, url, size=None, offset=0, length=None, block=1 << 20, session=None, max_blocks=256,
                 retries=5, sleep=time.sleep):
        import requests

        self.retries = retries
        self.sleep = sleep
        self.url = url
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        if size is None:
            r = self.session.head(url, allow_redirects=True, timeout=60)
            r.raise_for_status()
            size = int(r.headers["Content-Length"])
        self.total = size
        self.offset = offset
        self.length = size - offset if length is None else length
        self.block = block
        self.max_blocks = max_blocks
        self.pos = 0
        self.cache = {}
        self.bytes_fetched = 0
        self.requests = 0
        self.closed = False

    # --- 檔案物件介面 ---
    def readable(self):
        return True

    def seekable(self):
        return True

    def writable(self):
        return False

    def tell(self):
        return self.pos

    def seek(self, pos, whence=0):
        if whence == 0:
            self.pos = pos
        elif whence == 1:
            self.pos += pos
        elif whence == 2:
            self.pos = self.length + pos
        else:
            raise ValueError(f"whence 不合法：{whence}")
        if self.pos < 0:
            raise ValueError("seek 到負的位置")
        return self.pos

    def close(self):
        self.closed = True

    def flush(self):
        pass

    def _get(self, start, end):
        """GET 一段範圍；連線中斷、逾時、伺服器 5xx 會重試（每次等候時間加倍），其他錯誤直接丟出。"""
        import requests

        for attempt in range(self.retries + 1):
            try:
                r = self.session.get(self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=120)
                if r.status_code < 500:
                    return r
                error = IOError(f"伺服器回 {r.status_code}")
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError) as e:
                error = e
            if attempt == self.retries:
                raise error
            self.sleep(min(2 ** attempt, 30))

    def _block(self, i):
        if i not in self.cache:
            if len(self.cache) >= self.max_blocks:
                self.cache.pop(next(iter(self.cache)))
            start = self.offset + i * self.block
            end = min(start + self.block, self.offset + self.length) - 1
            r = self._get(start, end)
            if r.status_code != 206:
                raise IOError(f"伺服器沒有回 206（回 {r.status_code}），不支援 Range 請求")
            if len(r.content) != end - start + 1:
                raise IOError(f"Range 回傳長度不對：要 {end - start + 1}，收到 {len(r.content)}")
            self.cache[i] = r.content
            self.bytes_fetched += len(r.content)
            self.requests += 1
        return self.cache[i]

    def read(self, n=-1):
        if self.pos >= self.length:
            return b""
        if n is None or n < 0 or self.pos + n > self.length:
            n = self.length - self.pos
        out = []
        pos, remaining = self.pos, n
        while remaining > 0:
            i, within = divmod(pos, self.block)
            chunk = self._block(i)[within:within + remaining]
            if not chunk:
                break
            out.append(chunk)
            pos += len(chunk)
            remaining -= len(chunk)
        self.pos = pos
        return b"".join(out)

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def open_member(url, member, session=None):
    """開 zip 內沒壓縮的成員，回傳 (只讀這一段的 HttpRangeFile, 整個 zip 的 HttpRangeFile)。"""
    whole = HttpRangeFile(url, session=session)
    with zipfile.ZipFile(whole) as zf:
        info = zf.getinfo(member)
        if info.compress_type != zipfile.ZIP_STORED:
            raise ValueError(f"{member} 有壓縮（方法 {info.compress_type}），無法用 Range 直接讀")
        whole.seek(info.header_offset)
        start = data_offset(whole.read(30), info.header_offset)
        size = info.file_size
    sub = HttpRangeFile(url, size=whole.total, offset=start, length=size, session=whole.session)
    return sub, whole


def list_members(url, session=None):
    whole = HttpRangeFile(url, session=session)
    with zipfile.ZipFile(whole) as zf:
        rows = [(i.filename, i.file_size, i.compress_type) for i in zf.infolist()]
    return rows, whole


def describe(h5):
    """印出 HDF5 檔的資料集：名稱、形狀、型別、分塊、壓縮。"""
    import h5py

    lines = []

    def visit(name, obj):
        if isinstance(obj, h5py.Dataset):
            lines.append(f"  {name}: shape={obj.shape} dtype={obj.dtype} chunks={obj.chunks} "
                         f"compression={obj.compression} dims={[d.label or '' for d in obj.dims]}")

    h5.visititems(visit)
    return lines


def plane_index(shape, n_lat, n_lon, time_index, ys, xs):
    """變數形狀為 (時間, [其他維度...], 緯度, 經度) 時，回傳取某時間步、其他維度取第 0 層的索引；形狀不符回 None。"""
    if len(shape) < 3 or tuple(shape[-2:]) != (n_lat, n_lon):
        return None
    return (time_index,) + (0,) * (len(shape) - 3) + (ys, xs)


def coordinate_names(h5):
    """猜緯度、經度、時間的資料集名稱（找不到的回 None）。"""
    names = {k.lower(): k for k in h5.keys()}
    pick = lambda options: next((names[o] for o in options if o in names), None)
    return pick(("lat", "latitude", "y")), pick(("lon", "longitude", "x")), pick(("time", "t"))


def main():
    ap = argparse.ArgumentParser(description="探測氣象署個案 zip 內的輸入場（不下載整包）")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--members", action="store_true", help="只列出 zip 內的檔案與大小")
    ap.add_argument("--member", help="要看的成員，例如 UCURR.202307.nc")
    ap.add_argument("--var", help="變數名稱；不給就取第一個三維以上的資料集")
    ap.add_argument("--lat", type=float, default=22.609)
    ap.add_argument("--lon", type=float, default=120.207)
    ap.add_argument("--half-deg", type=float, default=0.25, help="讀取範圍：中心 ± 這個度數")
    ap.add_argument("--time-index", type=int, default=0)
    ap.add_argument("--relax-x509", action="store_true",
                    help="憑證與主機名稱照樣驗證，只關掉 X.509 嚴格檢查（遇到 Missing Subject Key Identifier 時用）")
    args = ap.parse_args()
    session = make_session(args.relax_x509)
    try:
        run(args, session)
    except Exception as e:
        import requests
        if isinstance(e, requests.exceptions.SSLError) and not args.relax_x509:
            raise SystemExit(f"SSL 憑證驗證失敗：{e}\n如果訊息是 Missing Subject Key Identifier，加上 --relax-x509 再試"
                             "（只關掉 X.509 嚴格檢查，憑證鏈與主機名稱仍會驗證）。")
        raise


def run(args, session):

    t0 = time.time()
    if args.members or not args.member:
        rows, whole = list_members(args.url, session=session)
        print(f"zip 共 {len(rows)} 個檔案（只讀了目錄，下載 {whole.bytes_fetched / 1e6:.2f} MB，{whole.requests} 次請求）")
        for name, size, ctype in rows:
            print(f"  {name}\t{size / 1e6:,.0f} MB\t壓縮方法 {ctype}（0 = 沒壓縮）")
        if not args.member:
            return
    import h5py

    sub, whole = open_member(args.url, args.member, session=session)
    print(f"\n成員 {args.member}：資料從 zip 的第 {sub.offset:,} 位元組開始，{sub.length / 1e6:,.0f} MB")
    with h5py.File(sub, "r") as h5:
        print("全域屬性：", {k: (v.decode() if isinstance(v, bytes) else v) for k, v in h5.attrs.items()})
        for line in describe(h5):
            print(line)
        lat_name, lon_name, time_name = coordinate_names(h5)
        print(f"座標資料集：lat={lat_name} lon={lon_name} time={time_name}")
        if time_name:
            t = h5[time_name]
            print("時間：", {k: (v.decode() if isinstance(v, bytes) else v) for k, v in t.attrs.items() if k in ("units", "calendar", "long_name")},
                  "筆數", t.shape, "第一筆", t[0], "最後一筆", t[-1], "第二筆", t[1] if t.shape[0] > 1 else None)
        if not (lat_name and lon_name):
            print("找不到緯度或經度資料集，停在這裡；請把上面的輸出貼給 AI。")
            return
        lats, lons = h5[lat_name][:], h5[lon_name][:]
        print(f"緯度 {lats.min():.4f}–{lats.max():.4f}（{lats.size} 個），經度 {lons.min():.4f}–{lons.max():.4f}（{lons.size} 個）")
        var = args.var or next((k for k, v in h5.items() if isinstance(v, h5py.Dataset) and v.ndim >= 3), None)
        if var is None:
            print("找不到三維以上的變數，停在這裡。")
            return
        ds = h5[var]
        print(f"變數 {var}：shape={ds.shape} 屬性={ {k: (v.decode() if isinstance(v, bytes) else v) for k, v in ds.attrs.items()} }")
        ys, xs = index_window(lats, args.lat, args.half_deg), index_window(lons, args.lon, args.half_deg)
        idx = plane_index(ds.shape, lats.size, lons.size, args.time_index, ys, xs)
        if idx is None:
            print(f"形狀 {ds.shape} 最後兩維不是（緯度, 經度）= ({lats.size}, {lons.size})，沒有自動讀取；請把輸出貼給 AI。")
            return
        if ds.ndim > 3:
            print(f"注意：變數有 {ds.ndim} 維，第 2 維以後（例如深度）都取第 0 層")
        before = sub.bytes_fetched
        block = ds[idx]
        print(f"讀取時間步 {args.time_index}，範圍緯度 {lats[ys][0]:.3f}–{lats[ys][-1]:.3f}、經度 {lons[xs][0]:.3f}–{lons[xs][-1]:.3f}，"
              f"形狀 {block.shape}，這一步下載 {(sub.bytes_fetched - before) / 1e6:.2f} MB")
        i, j = nearest_index(lats, args.lat), nearest_index(lons, args.lon)
        nearest = plane_index(ds.shape, lats.size, lons.size, args.time_index, i, j)
        print(f"最近格點 緯度 {lats[i]:.4f}、經度 {lons[j]:.4f} 的值：{ds[nearest]}")
        print(f"範圍內：最小 {np.nanmin(block):.4f}、最大 {np.nanmax(block):.4f}、缺值 {int(np.isnan(block).sum())} 個")
    total = sub.bytes_fetched + whole.bytes_fetched
    print(f"\n總共下載 {total / 1e6:.2f} MB，{sub.requests + whole.requests} 次請求，花 {time.time() - t0:.1f} 秒")


if __name__ == "__main__":
    main()
