import http.server
import struct
import threading
import zipfile

import numpy as np
import pytest

import cwa_probe as c


def test_data_offset_adds_header_name_and_extra_lengths():
    header = b"PK\x03\x04" + b"\x00" * 22 + struct.pack("<HH", 12, 20)
    assert c.data_offset(header, 1000) == 1000 + 30 + 12 + 20


def test_data_offset_rejects_bad_signature_and_short_header():
    with pytest.raises(ValueError):
        c.data_offset(b"XXXX" + b"\x00" * 26, 0)
    with pytest.raises(ValueError):
        c.data_offset(b"PK\x03\x04", 0)


def test_index_window_ascending_and_descending():
    asc = np.array([21.0, 21.5, 22.0, 22.5, 23.0])
    assert c.index_window(asc, 22.0, 0.5) == slice(1, 4)
    assert c.index_window(asc[::-1], 22.0, 0.5) == slice(1, 4)


def test_index_window_includes_edges_and_rejects_empty():
    asc = np.array([21.0, 21.5, 22.0])
    assert c.index_window(asc, 21.5, 0.5) == slice(0, 3)
    with pytest.raises(ValueError, match="沒有格點"):
        c.index_window(asc, 30.0, 0.5)


def test_nearest_index_ties_pick_smaller_index():
    assert c.nearest_index([1.0, 2.0, 3.0], 2.4) == 1
    assert c.nearest_index([1.0, 2.0, 3.0], 1.5) == 0


class RangeHandler(http.server.BaseHTTPRequestHandler):
    data = b""
    ignore_range = False
    truncate = False

    def log_message(self, *a):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.data)))
        self.end_headers()

    def do_GET(self):
        rng = self.headers.get("Range")
        if rng and not self.ignore_range:
            a, b = rng.replace("bytes=", "").split("-")
            a, b = int(a), min(int(b), len(self.data) - 1)
            if a > b:                       # 真的伺服器對無效範圍回 416
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = self.data[a:b + 1]
            if self.truncate:
                body = body[:-1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(self.data)}")
        else:
            body = self.data
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    servers = []

    def start(data, ignore_range=False, truncate=False):
        handler = type("H", (RangeHandler,), {"data": data, "ignore_range": ignore_range, "truncate": truncate})
        s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        servers.append(s)
        return f"http://127.0.0.1:{s.server_address[1]}/f.zip"

    yield start
    for s in servers:
        s.shutdown()


def test_range_file_reads_exact_bytes_across_blocks_and_seeks(server):
    pytest.importorskip("requests")
    data = bytes(range(256)) * 40
    f = c.HttpRangeFile(server(data), block=100)
    assert f.read(5) == data[:5]
    f.seek(95)
    assert f.read(20) == data[95:115]
    f.seek(-10, 2)
    assert f.read() == data[-10:]
    assert f.read(5) == b""
    f.seek(3)
    f.seek(4, 1)
    assert f.tell() == 7 and f.read(2) == data[7:9]


def test_range_file_offset_and_length_present_a_slice(server):
    pytest.importorskip("requests")
    data = bytes(range(200))
    f = c.HttpRangeFile(server(data), offset=50, length=30, block=16)
    assert f.read() == data[50:80]
    f.seek(-5, 2)
    assert f.read() == data[75:80]


def test_range_file_downloads_only_needed_blocks(server):
    pytest.importorskip("requests")
    data = b"x" * 10_000
    f = c.HttpRangeFile(server(data), block=1000)
    f.seek(5500)
    f.read(100)
    assert f.bytes_fetched == 1000 and f.requests == 1
    f.seek(5600)
    f.read(100)
    assert f.requests == 1          # 同一區塊用快取


def test_range_file_rejects_server_without_range_support(server):
    pytest.importorskip("requests")
    f = c.HttpRangeFile(server(b"y" * 1000, ignore_range=True), block=100)
    with pytest.raises(IOError, match="206"):
        f.read(10)


def build_zip(tmp_path, compress=zipfile.ZIP_STORED):
    h5py = pytest.importorskip("h5py")
    nc = tmp_path / "VAR.nc"
    lats = np.linspace(21.0, 24.0, 31)
    lons = np.linspace(119.0, 122.0, 31)
    with h5py.File(nc, "w") as f:
        f["lat"] = lats
        f["lon"] = lons
        f["time"] = np.array([0.0, 1.0, 2.0])
        f["time"].attrs["units"] = "hours since 2023-07-01 00:00:00"
        data = np.arange(3 * 31 * 31, dtype="float32").reshape(3, 31, 31)
        f.create_dataset("U", data=data, chunks=(1, 31, 31))
    zp = tmp_path / "a.zip"
    with zipfile.ZipFile(zp, "w", compression=compress) as zf:
        zf.writestr("first.txt", "hello world" * 100)
        zf.write(nc, "VAR.nc")
    return zp, data, lats, lons


def test_open_member_reads_hdf5_inside_stored_zip(server, tmp_path):
    h5py = pytest.importorskip("h5py")
    pytest.importorskip("requests")
    zp, data, lats, lons = build_zip(tmp_path)
    url = server(zp.read_bytes())
    sub, whole = c.open_member(url, "VAR.nc")
    with h5py.File(sub, "r") as h5:
        assert h5["U"].shape == (3, 31, 31)
        assert np.array_equal(h5["U"][1, 2:5, 3:6], data[1, 2:5, 3:6])
        assert c.coordinate_names(h5) == ("lat", "lon", "time")
        assert any("U: shape=(3, 31, 31)" in line for line in c.describe(h5))


def test_open_member_rejects_compressed_member(server, tmp_path):
    pytest.importorskip("requests")
    zp, *_ = build_zip(tmp_path, compress=zipfile.ZIP_DEFLATED)
    with pytest.raises(ValueError, match="壓縮"):
        c.open_member(server(zp.read_bytes()), "VAR.nc")


def test_list_members_reads_only_directory(server, tmp_path):
    pytest.importorskip("requests")
    zp, *_ = build_zip(tmp_path)
    rows, whole = c.list_members(server(zp.read_bytes()))
    assert [r[0] for r in rows] == ["first.txt", "VAR.nc"]
    assert rows[0][2] == zipfile.ZIP_STORED
    assert whole.bytes_fetched <= zp.stat().st_size


def test_plane_index_three_and_four_dims():
    ys, xs = slice(1, 3), slice(4, 6)
    assert c.plane_index((5, 10, 20), 10, 20, 2, ys, xs) == (2, ys, xs)
    assert c.plane_index((5, 3, 10, 20), 10, 20, 2, ys, xs) == (2, 0, ys, xs)
    assert c.plane_index((5, 3, 2, 10, 20), 10, 20, 1, ys, xs) == (1, 0, 0, ys, xs)


def test_plane_index_rejects_wrong_shape():
    assert c.plane_index((5, 10, 20), 20, 10, 0, 0, 0) is None
    assert c.plane_index((10, 20), 10, 20, 0, 0, 0) is None


def test_main_cli_reads_four_dimensional_variable(server, tmp_path, capsys, monkeypatch):
    h5py = pytest.importorskip("h5py")
    pytest.importorskip("requests")
    nc = tmp_path / "V4.nc"
    lats, lons = np.linspace(21.0, 24.0, 31), np.linspace(119.0, 122.0, 31)
    with h5py.File(nc, "w") as f:
        f["lat"], f["lon"], f["time"] = lats, lons, np.array([0.0, 1.0])
        data = np.arange(2 * 2 * 31 * 31, dtype="float32").reshape(2, 2, 31, 31)
        f.create_dataset("U", data=data, chunks=(1, 1, 31, 31))
    zp = tmp_path / "b.zip"
    with zipfile.ZipFile(zp, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.write(nc, "V4.nc")
    url = server(zp.read_bytes())
    monkeypatch.setattr("sys.argv", ["cwa_probe.py", "--url", url, "--member", "V4.nc", "--lat", "22.5", "--lon", "120.5",
                                     "--half-deg", "0.1", "--time-index", "1"])
    c.main()
    out = capsys.readouterr().out
    assert "第 0 層" in out
    assert f"的值：{data[1, 0, 15, 15]}" in out


def test_range_file_rejects_truncated_response(server):
    pytest.importorskip("requests")
    f = c.HttpRangeFile(server(b"z" * 1000, truncate=True), block=100)
    with pytest.raises(IOError, match="長度"):
        f.read(10)


def test_range_file_read_past_end_returns_remaining_bytes_only(server):
    pytest.importorskip("requests")
    data = bytes(range(200))
    f = c.HttpRangeFile(server(data), block=100)
    f.seek(150)
    assert f.read(51) == data[150:]
    assert f.read(1) == b""


def test_relaxed_ssl_context_keeps_verification_but_drops_strict_flag():
    import ssl
    ctx = c.relaxed_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert not (ctx.verify_flags & ssl.VERIFY_X509_STRICT)


def test_make_session_uses_relaxed_context_only_when_asked():
    pytest.importorskip("requests")
    default = c.make_session()
    relaxed = c.make_session(relax_x509=True)
    assert type(default.get_adapter("https://example.com")).__name__ == "HTTPAdapter"
    adapter = relaxed.get_adapter("https://example.com")
    assert type(adapter).__name__ == "Adapter"
    import ssl
    assert not (adapter.poolmanager.connection_pool_kw["ssl_context"].verify_flags & ssl.VERIFY_X509_STRICT)
    assert relaxed.get_adapter("http://example.com").__class__.__name__ == "HTTPAdapter"


def test_main_explains_ssl_error_and_suggests_flag(monkeypatch):
    requests = pytest.importorskip("requests")

    def boom(*a, **k):
        raise requests.exceptions.SSLError("Missing Subject Key Identifier")

    monkeypatch.setattr(c, "run", boom)
    monkeypatch.setattr("sys.argv", ["cwa_probe.py", "--members"])
    with pytest.raises(SystemExit) as e:
        c.main()
    assert "--relax-x509" in str(e.value)
    monkeypatch.setattr("sys.argv", ["cwa_probe.py", "--members", "--relax-x509"])
    with pytest.raises(requests.exceptions.SSLError):
        c.main()


class FlakySession:
    """前 fails 次 get 丟出指定例外（或回傳 5xx），之後回 206。"""

    def __init__(self, fails, kind="conn"):
        self.fails, self.kind, self.calls = fails, kind, 0
        self.headers = {}

    def get(self, url, headers=None, timeout=None):
        import requests

        self.calls += 1
        if self.calls <= self.fails:
            if self.kind == "conn":
                raise requests.exceptions.ConnectionError("Remote end closed connection without response")
            r = requests.Response()
            r.status_code = 503
            return r
        r = requests.Response()
        r.status_code = 206
        r._content = b"x"
        return r


@pytest.mark.parametrize("kind", ["conn", "5xx"])
def test_get_retries_then_succeeds_with_doubling_waits(kind):
    pytest.importorskip("requests")
    waits = []
    f = c.HttpRangeFile("http://x/", size=10, session=FlakySession(3, kind), sleep=waits.append)
    assert f._get(0, 0).status_code == 206
    assert waits == [1, 2, 4]


def test_get_gives_up_after_retries():
    pytest.importorskip("requests")
    import requests

    s = FlakySession(99)
    f = c.HttpRangeFile("http://x/", size=10, session=s, retries=2, sleep=lambda t: None)
    with pytest.raises(requests.exceptions.ConnectionError):
        f._get(0, 0)
    assert s.calls == 3


def test_get_does_not_retry_client_errors():
    pytest.importorskip("requests")
    import requests

    class S404:
        calls = 0
        headers = {}

        def get(self, *a, **k):
            S404.calls += 1
            r = requests.Response()
            r.status_code = 404
            return r

    f = c.HttpRangeFile("http://x/", size=10, session=S404(), sleep=lambda t: None)
    assert f._get(0, 0).status_code == 404 and S404.calls == 1
