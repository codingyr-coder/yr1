import os
import json
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
GIST_TOKEN = os.environ['GIST_TOKEN']
GIST_ID = os.environ['GIST_ID']

BINANCE_BASE = "https://data-api.binance.vision"

# ---------- الإعدادات الرسمية المعتمدة (نسخة الحساب الشخصي النهائية) ----------
BLOCK_PCT = 0.60          # الحد الذي لا يجوز للفتيل المقابل تجاوزه
WICK_THRESHOLD_PCT = 40.0  # الحد الأدنى لعمق الفتيل (فلتر الجودة) -- مؤكَّد الأفضل استقراراً
TARGET_SPLIT = 50.0        # نقطة تقسيم الهدف المتكيّف حسب عمق الفتيل
TARGET_PCT_LOW = 0.20      # الهدف لعمق فتيل أقل من TARGET_SPLIT (محدَّثة بعد إعادة الاختبار)
TARGET_PCT_HIGH = 0.28     # الهدف لعمق فتيل أكبر من TARGET_SPLIT (محدَّثة بعد إعادة الاختبار)

# SL كنسبة مئوية من السعر (بدل مبلغ دولار ثابت -- أصلح مشكلة عدم إمكانية التنفيذ عند أسعار عالية)
SL_PCT = 0.12              # مؤكَّدة كأفضل توازن أداء/استقرار بعد بحث معمّق
STOPLIMIT_OFFSET_PCT = SL_PCT * 0.6  # 0.072% -- مؤكَّدة الأكثر استقراراً بين البدائل المُختبرة

VOLUME_THRESHOLD = {"BTCUSDT": 0.40, "ETHUSDT": 0.30}  # مؤكَّدة الأفضل، حتى بعد تغيير الهدف
