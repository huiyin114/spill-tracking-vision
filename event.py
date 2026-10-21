"""事件參數：要分析哪一個事件（地點、期間、發生時間）。

必填：參考位置（lat, lon）與分析期間（start, end，含頭尾兩天）。
選填：發生時間 time（沒有就不算「距事件幾小時」）、名稱 name、時區 tz（用來解讀 start、end
與 CLI 給的沒有時區的時間，預設台灣）。

沒有指定事件時，各模組預設用天使輪（ANGEL）。
其他模組需要這些值時，從這裡匯入：from event import Event, ANGEL
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TAIWAN = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True)
class Event:
    lat: float
    lon: float
    start: date
    end: date
    time: datetime = None
    name: str = ""
    tz: str = "Asia/Taipei"

    def __post_init__(self):
        if not -90 <= self.lat <= 90:
            raise ValueError(f"緯度要在 -90 到 90 之間：{self.lat}")
        if not -180 <= self.lon <= 180:
            raise ValueError(f"經度要在 -180 到 180 之間：{self.lon}")
        try:
            ZoneInfo(self.tz)
        except (KeyError, ValueError):
            raise ValueError(f"找不到時區：{self.tz!r}") from None
        if type(self.start) is not date or type(self.end) is not date:
            raise ValueError("start、end 必須是日期（datetime.date）")
        if self.start > self.end:
            raise ValueError(f"分析期間的開始日 {self.start} 晚於結束日 {self.end}")
        if self.time is not None and self.time.tzinfo is None:
            raise ValueError("事件時間必須帶時區")

    def period_utc(self):
        """分析期間的 UTC 範圍 (開始, 結束)：開始日 00:00 起，到結束日隔天 00:00 前（不含）。"""
        tz = ZoneInfo(self.tz)
        a = datetime(self.start.year, self.start.month, self.start.day, tzinfo=tz)
        b = datetime(self.end.year, self.end.month, self.end.day, tzinfo=tz) + timedelta(days=1)
        return a.astimezone(ZoneInfo("UTC")), b.astimezone(ZoneInfo("UTC"))

    def in_period(self, t):
        """時間 t（要帶時區）是否在分析期間內。"""
        a, b = self.period_utc()
        return a <= t < b


# 天使輪（2023-07-21 高雄外海沉沒）。
# 沉沒時間：運安會調查頁面「7月21日0530時」。原文未註明時區，視為台灣時間。
SINKING_TIME = datetime(2023, 7, 21, 5, 30, tzinfo=TAIWAN)

# 沉船位置：航港局 2023-08-01 礙航公告「沉船位置更新」，22°36.54′N、120°12.41′E。
# 公告用「度＋分」，這裡換成十進位度（分 ÷ 60）。公告未註明座標系。
WRECK_LAT = 22 + 36.54 / 60
WRECK_LON = 120 + 12.41 / 60

# 分析期間 2023-07-19 到 2023-08-31：本專案查衛星目錄的範圍。
ANGEL = Event(lat=WRECK_LAT, lon=WRECK_LON, start=date(2023, 7, 19), end=date(2023, 8, 31),
              time=SINKING_TIME, name="天使輪")


# ---- 命令列 ----
EVENT_ARGS = ("lat", "lon", "start", "end", "event_time")


def add_event_args(ap):
    """替命令列加上事件參數。全部不給就用天使輪；要換事件，lat、lon、start、end 四個都要給。"""
    g = ap.add_argument_group("事件（全部不給＝天使輪；換事件時 lat、lon、start、end 必填）")
    g.add_argument("--lat", type=float, help="參考位置緯度（十進位度）")
    g.add_argument("--lon", type=float, help="參考位置經度（十進位度）")
    g.add_argument("--start", help="分析期間開始日 YYYY-MM-DD")
    g.add_argument("--end", help="分析期間結束日 YYYY-MM-DD（含當天）")
    g.add_argument("--event-time", help="事件發生時間 YYYY-MM-DD HH:MM（選填，沒給就不算距事件幾小時）")
    g.add_argument("--event-name", default="", help="事件名稱（選填）")
    g.add_argument("--tz", default="Asia/Taipei", help="start、end、event-time 的時區（預設 Asia/Taipei）")


def event_from_args(ap, args):
    """由命令列參數得到 Event。參數不完整或不合理時用 ap.error 結束並說明。"""
    given = [k for k in EVENT_ARGS if getattr(args, k) is not None]
    if not given:
        return ANGEL
    missing = [k for k in ("lat", "lon", "start", "end") if getattr(args, k) is None]
    if missing:
        ap.error("換事件時 --lat --lon --start --end 都要給，缺：" + "、".join("--" + m for m in missing))
    try:
        try:
            tz = ZoneInfo(args.tz)
        except (KeyError, ValueError):
            raise ValueError(f"找不到時區：{args.tz!r}") from None
        t = None
        if args.event_time is not None:
            t = datetime.strptime(args.event_time, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        return Event(lat=args.lat, lon=args.lon,
                     start=datetime.strptime(args.start, "%Y-%m-%d").date(),
                     end=datetime.strptime(args.end, "%Y-%m-%d").date(),
                     time=t, name=args.event_name, tz=args.tz)
    except ValueError as e:
        ap.error(f"事件參數有誤：{e}")
