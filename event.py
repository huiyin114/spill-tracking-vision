"""天使輪事件的固定參數，以官方公告為準。
其他模組需要這些值時，從這裡匯入：from event import WRECK_LAT, WRECK_LON, SINKING_TIME
"""
from datetime import datetime
from zoneinfo import ZoneInfo

TAIWAN = ZoneInfo("Asia/Taipei")

# 沉沒時間：運安會調查頁面「7月21日0530時」。原文未註明時區，視為台灣時間。
SINKING_TIME = datetime(2023, 7, 21, 5, 30, tzinfo=TAIWAN)

# 沉船位置：航港局 2023-08-01 礙航公告「沉船位置更新」，22°36.54′N、120°12.41′E。
# 公告用「度＋分」，這裡換成十進位度（分 ÷ 60）。公告未註明座標系。
WRECK_LAT = 22 + 36.54 / 60
WRECK_LON = 120 + 12.41 / 60
