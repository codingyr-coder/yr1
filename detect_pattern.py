import os
import json
import requests
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
GIST_TOKEN = os.environ['GIST_TOKEN']
GIST_ID = os.environ['GIST_ID']

BINANCE_BASE = "https://data-api.binance.vision"

# ---------- الإعدادات الرسمية المعتمدة (Option 2 + الهدف المتكيّف) ----------
BLOCK_PCT = 0.60          # الحد الذي لا يجوز للفتيل المقابل تجاوزه (بدل 50% الأصلية)
WICK_THRESHOLD_PCT = 40.0  # الحد الأدنى لعمق الفتيل (فلتر الجودة)
TARGET_SPLIT = 50.0        # نقطة تقسيم الهدف المتكيّف حسب عمق الفتيل
TARGET_PCT_LOW = 0.15      # الهدف لعمق فتيل أقل من TARGET_SPLIT
TARGET_PCT_HIGH = 0.25     # الهدف لعمق فتيل أكبر من TARGET_SPLIT

SL_BUFFER = {"BTCUSDT": 5.0, "ETHUSDT": 0.5}
STOPLIMIT_OFFSET = {"BTCUSDT": 3.0, "ETHUSDT": 0.3}
VOLUME_THRESHOLD = {"BTCUSDT": 0.40, "ETHUSDT": 0.30}  # الحد الأدنى لمئوية الحجم (بدل نافذة التوقيت)

RISK_BASE_PEAK = 0.0175     # المخاطرة الأساسية عند قمة رأس المال (محدّثة بعد فحص التراجع اليومي)
RISK_BASE_DRAWDOWN = 0.00875  # المخاطرة الأساسية في حالة التراجع

FOMC_DATES_UTC = [
    "2026-09-16 18:00", "2026-10-28 18:00", "2026-12-09 19:00",
]

# ---------- Telegram ----------
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})

# ---------- Gist (الذاكرة) ----------
def load_state():
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {"Authorization": f"token {GIST_TOKEN}", "Accept": "application/vnd.github+json"}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    data = r.json()
    content = data["files"]["state.json"]["content"]
    return json.loads(content)

def save_state(state):
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {"Authorization": f"token {GIST_TOKEN}", "Accept": "application/vnd.github+json"}
    payload = {"files": {"state.json": {"content": json.dumps(state)}}}
    r = requests.patch(url, headers=headers, json=payload)
    r.raise_for_status()

# ---------- Binance (بيانات السوق الحقيقي) ----------
def get_klines(symbol, interval, limit=100, start_time=None, end_time=None):
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_time is not None:
        params["startTime"] = int(start_time)
    if end_time is not None:
        params["endTime"] = int(end_time)
    r = requests.get(url, params=params)
    data = r.json()
    candles = []
    for c in data:
        candles.append({
            "open_time": c[0], "open": float(c[1]), "high": float(c[2]),
            "low": float(c[3]), "close": float(c[4]), "volume": float(c[5]),
        })
    return candles

# ---------- تسجيل السبريد (صامت) ----------
def get_spread_pct(symbol):
    url = f"{BINANCE_BASE}/api/v3/ticker/bookTicker"
    r = requests.get(url, params={"symbol": symbol})
    data = r.json()
    bid = float(data["bidPrice"]); ask = float(data["askPrice"])
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid * 100 if mid > 0 else None

def log_spread(state, symbol, spread_pct, now_dt, vol_pct=None, volume_pct=None):
    stats = state.setdefault("spread_stats", {})
    sym_stats = stats.setdefault(symbol, {"by_hour": {}, "by_weekday": {}, "by_volatility": {}, "by_volume": {}})
    hour_key = str(now_dt.hour)
    he = sym_stats["by_hour"].setdefault(hour_key, {"count": 0, "sum_pct": 0.0})
    he["count"] += 1; he["sum_pct"] += spread_pct
    wd_key = str(now_dt.weekday())
    we = sym_stats["by_weekday"].setdefault(wd_key, {"count": 0, "sum_pct": 0.0})
    we["count"] += 1; we["sum_pct"] += spread_pct
    if vol_pct is not None:
        vol_bucket = "low" if vol_pct<0.25 else "medium" if vol_pct<0.5 else "high" if vol_pct<0.75 else "very_high"
        ve = sym_stats["by_volatility"].setdefault(vol_bucket, {"count": 0, "sum_pct": 0.0})
        ve["count"] += 1; ve["sum_pct"] += spread_pct
    if volume_pct is not None:
        volume_bucket = "low" if volume_pct<0.25 else "medium" if volume_pct<0.5 else "high" if volume_pct<0.75 else "very_high"
        vle = sym_stats["by_volume"].setdefault(volume_bucket, {"count": 0, "sum_pct": 0.0})
        vle["count"] += 1; vle["sum_pct"] += spread_pct

# ---------- حظر الأخبار (لم تعد هناك نافذة توقيت عامة) ----------
def is_news_blackout(open_time_ms):
    dt = datetime.fromtimestamp(open_time_ms/1000, tz=timezone.utc)
    for date_str in FOMC_DATES_UTC:
        event_dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        diff_minutes = (dt - event_dt).total_seconds() / 60
        if -5 <= diff_minutes <= 15:
            return True
    return False

def is_execution_allowed(open_time_ms):
    # لم يعد هناك قيد يوم/ساعة -- استُبدل بفلتر الحجم عند اكتشاف النموذج
    # يبقى فقط حظر الأخبار (FOMC/CPI)، مستقلاً تماماً
    return not is_news_blackout(open_time_ms)

def trim_incomplete(candles, interval_ms, now_ms):
    if not candles:
        return candles
    last = candles[-1]
    if last["open_time"] + interval_ms > now_ms:
        return candles[:-1]
    return candles

def fmt(ts):
    return datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')

# ---------- منطق كشف النموذج على فريم الساعة (Option 2: block=60%) ----------
def find_pattern(candles):
    n = len(candles)
    idx = 1
    last_found = None

    while idx < n - 1:
        prev = candles[idx-1]
        c1 = candles[idx]

        if not (c1["high"] > prev["high"] or c1["low"] < prev["low"]):
            idx += 1
            continue

        high1, low1 = c1["high"], c1["low"]
        range1 = high1 - low1
        block_bull = low1 + BLOCK_PCT * range1
        block_bear = high1 - BLOCK_PCT * range1

        j = idx + 1
        found = False
        direction = None
        c2 = None

        while j < n:
            cj = candles[j]
            breaks_top = cj["high"] > high1
            breaks_bottom = cj["low"] < low1

            if not breaks_top and not breaks_bottom:
                j += 1
                continue
            if breaks_top and breaks_bottom:
                break

            open_in_range = low1 <= cj["open"] <= high1
            close_in_range = low1 <= cj["close"] <= high1

            if breaks_bottom and not breaks_top:
                if cj["high"] < block_bull and open_in_range and close_in_range:
                    found = True
                    direction = "bullish"
                    c2 = cj
                break
            elif breaks_top and not breaks_bottom:
                if cj["low"] > block_bear and open_in_range and close_in_range:
                    found = True
                    direction = "bearish"
                    c2 = cj
                break
            j += 1

        if not found:
            if j >= n:
                break
            idx = j
            continue

        if direction == "bullish":
            wick = min(c2["open"], c2["close"]) - c2["low"]
        else:
            wick = c2["high"] - max(c2["open"], c2["close"])
        wick_pct = (wick / range1 * 100) if range1 > 0 else 0

        if wick_pct >= WICK_THRESHOLD_PCT:
            target_pct = TARGET_PCT_LOW if wick_pct < TARGET_SPLIT else TARGET_PCT_HIGH
            if direction == "bullish":
                TP1 = low1 + target_pct * range1
            else:
                TP1 = high1 - target_pct * range1

            last_found = {
                "direction": direction,
                "candle1_time": c1["open_time"],
                "candle1_high": high1,
                "candle1_low": low1,
                "TP1": TP1,
                "target_pct": target_pct,
                "candle2_high": c2["high"],
                "candle2_low": c2["low"],
                "candle2_close": c2["close"],
                "candle2_volume": c2["volume"],
                "wick_pct": wick_pct,
                "candle2_time": c2["open_time"],
            }

        idx = j + 1

    return last_found

# ---------- منطق تحديد شمعة الدخول ----------
def find_entry_candle(m5_candles_window, direction):
    if direction == "bullish":
        bearish = [c for c in m5_candles_window if c["close"] < c["open"]]
        if not bearish:
            return None
        return min(bearish, key=lambda c: c["low"])
    else:
        bullish = [c for c in m5_candles_window if c["close"] > c["open"]]
        if not bullish:
            return None
        return max(bullish, key=lambda c: c["high"])

# ---------- منطق البحث عن التأكيد (يشمل فحص الهدف البعيد قبل التأكيد) ----------
def check_confirmation(candles_after, entry_open, direction, sl_level, far_target):
    for c in candles_after:
        if direction == "bullish":
            if c["low"] < sl_level:
                return "CANCELLED", c["open_time"]
            if c["high"] >= far_target:
                return "CANCELLED", c["open_time"]
            if c["close"] > entry_open:
                return "CONFIRMED", c["open_time"]
        else:
            if c["high"] > sl_level:
                return "CANCELLED", c["open_time"]
            if c["low"] <= far_target:
                return "CANCELLED", c["open_time"]
            if c["close"] < entry_open:
                return "CONFIRMED", c["open_time"]
    return None, None

# ---------- منطق انتظار التنفيذ (يجد أول لمسة طبيعية، ثم يفحص النافذة) ----------
def check_fill(candles_after, entry_open, direction, far_target):
    for c in candles_after:
        if direction == "bullish":
            if c["high"] >= far_target:
                return "CANCELLED_NO_FILL", c["open_time"]
            if c["low"] <= entry_open:
                if is_execution_allowed(c["open_time"]):
                    return "FILLED", c["open_time"]
                else:
                    return "CANCELLED_OUTSIDE_WINDOW", c["open_time"]
        else:
            if c["low"] <= far_target:
                return "CANCELLED_NO_FILL", c["open_time"]
            if c["high"] >= entry_open:
                if is_execution_allowed(c["open_time"]):
                    return "FILLED", c["open_time"]
                else:
                    return "CANCELLED_OUTSIDE_WINDOW", c["open_time"]
    return None, None

# ---------- منطق إدارة الصفقة المفتوحة (يبدأ من شمعة التنفيذ نفسها) ----------
def check_position(candles_after, direction, sl_trigger, sl_limit, tp1):
    for c in candles_after:
        if direction == "bullish":
            hit_sl = c["low"] <= sl_trigger
            hit_tp = c["high"] >= tp1
        else:
            hit_sl = c["high"] >= sl_trigger
            hit_tp = c["low"] <= tp1
        if hit_sl:
            return "SL", c["open_time"]
        if hit_tp:
            return "TP1", c["open_time"]
    return None, None

# ---------- حساب مئوية التقلب السببية (بلا نظر للمستقبل، تُحدَّث مرة واحدة فقط لكل شمعة ساعة جديدة) ----------
def update_atr_history_if_new_hour(state, symbol, current_atr_pct, current_hour_time):
    last_key = f"atr_last_hour_{symbol}"
    hist_key = f"atr_history_{symbol}"
    last_recorded_hour = state.get(last_key)
    if last_recorded_hour == current_hour_time:
        return  # نفس الشمعة التي سُجّلت بالفعل، لا تكرار
    hist = state.get(hist_key, [])
    hist.append(current_atr_pct)
    if len(hist) > 2000:
        hist = hist[-2000:]
    state[hist_key] = hist
    state[last_key] = current_hour_time

def compute_vol_percentile(state, symbol, current_atr_pct):
    hist_key = f"atr_history_{symbol}"
    hist = state.get(hist_key, [])
    if len(hist) >= 20:
        pct = sum(1 for v in hist if v < current_atr_pct) / len(hist)
    else:
        pct = 0.5
    return pct

def vol_multiplier(pct):
    if pct < 0.25: return 0.7
    elif pct < 0.5: return 0.85
    elif pct < 0.75: return 1.15
    else: return 1.3

# ---------- حساب مئوية الحجم (فلتر السيولة، بدل نافذة التوقيت) ----------
def update_volume_history_if_new_hour(state, symbol, current_volume, current_hour_time):
    last_key = f"vol_last_hour_{symbol}"
    hist_key = f"volume_history_{symbol}"
    last_recorded_hour = state.get(last_key)
    if last_recorded_hour == current_hour_time:
        return
    hist = state.get(hist_key, [])
    hist.append(current_volume)
    if len(hist) > 2000:
        hist = hist[-2000:]
    state[hist_key] = hist
    state[last_key] = current_hour_time

def compute_volume_percentile(state, symbol, current_volume):
    hist_key = f"volume_history_{symbol}"
    hist = state.get(hist_key, [])
    if len(hist) >= 20:
        pct = sum(1 for v in hist if v < current_volume) / len(hist)
    else:
        pct = 0.5
    return pct

def main():
    state = load_state()
    last_seen = state.get("last_candle2_time", {})
    pending = state.get("pending_confirmation", {})
    state_changed = False

    for symbol in ["BTCUSDT", "ETHUSDT"]:
        h1_candles = get_klines(symbol, "1h", limit=100)
        current_price = h1_candles[-1]["close"]
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        closed_h1 = trim_incomplete(h1_candles, 60*60*1000, now_ms)
        result = find_pattern(closed_h1)

        # حساب ATR14 ومئوية التقلب (لحظياً من آخر 20 شمعة)
        if len(closed_h1) >= 15:
            trs = [closed_h1[i]["high"]-closed_h1[i]["low"] for i in range(len(closed_h1)-14, len(closed_h1))]
            atr14 = sum(trs)/14
            atr_pct = atr14/current_price*100
            # تسجيل مستمر وغير متحيّز: مرة واحدة فقط لكل شمعة ساعة جديدة، بغض النظر عن حدوث صفقة
            current_hour_time = closed_h1[-1]["open_time"]
            before = state.get(f"atr_last_hour_{symbol}")
            update_atr_history_if_new_hour(state, symbol, atr_pct, current_hour_time)
            if state.get(f"atr_last_hour_{symbol}") != before:
                state_changed = True
        else:
            atr_pct = None

        # تسجيل مستمر لتاريخ الحجم (لفلتر السيولة، بدل نافذة التوقيت)
        if len(closed_h1) >= 1:
            current_volume = closed_h1[-1]["volume"]
            current_hour_time_vol = closed_h1[-1]["open_time"]
            before_vol = state.get(f"vol_last_hour_{symbol}")
            update_volume_history_if_new_hour(state, symbol, current_volume, current_hour_time_vol)
            if state.get(f"vol_last_hour_{symbol}") != before_vol:
                state_changed = True

        # تسجيل السبريد بصمت (الآن مع سياق مستوى التقلب في نفس اللحظة)
        try:
            spread_pct = get_spread_pct(symbol)
            if spread_pct is not None:
                current_vol_pct = compute_vol_percentile(state, symbol, atr_pct) if atr_pct is not None else None
                current_volume_pct = compute_volume_percentile(state, symbol, current_volume) if len(closed_h1) >= 1 else None
                log_spread(state, symbol, spread_pct, datetime.now(timezone.utc), vol_pct=current_vol_pct, volume_pct=current_volume_pct)
                state_changed = True
        except Exception:
            pass

        if result:
            candle2_time_str = str(result["candle2_time"])
            if candle2_time_str != last_seen.get(symbol) and symbol not in pending:
                current_vol_pct_for_pattern = compute_volume_percentile(state, symbol, result["candle2_volume"])
                if current_vol_pct_for_pattern < VOLUME_THRESHOLD[symbol]:
                    # حجم ضعيف جداً -> تجاهل هذا النموذج تماماً (بديل نافذة التوقيت)
                    last_seen[symbol] = candle2_time_str
                    state_changed = True
                    continue
                emoji = "🟢" if result["direction"] == "bullish" else "🔴"
                direction_ar = "صاعد" if result["direction"] == "bullish" else "هابط"
                send_telegram(
                    f"🆕 نموذج جديد! (بانتظار تأكيد فريم 5 دقائق)\n\n"
                    f"{emoji} {symbol}: نموذج {direction_ar}\n"
                    f"   عمق الفتيل: {result['wick_pct']:.1f}%\n"
                    f"   نسبة الهدف المُختارة: {result['target_pct']*100:.0f}%\n"
                    f"   مئوية الحجم: {current_vol_pct_for_pattern*100:.0f}%\n"
                    f"   وقت شمعة النطاق: {fmt(result['candle1_time'])}\n"
                    f"   وقت شمعة السحب: {fmt(result['candle2_time'])}\n"
                    f"   السعر الحالي: {current_price}"
                )
                last_seen[symbol] = candle2_time_str
                pending[symbol] = {
                    "status": "waiting_confirmation",
                    "direction": result["direction"],
                    "candle1_high": result["candle1_high"],
                    "candle1_low": result["candle1_low"],
                    "TP1": result["TP1"],
                    "candle2_time": result["candle2_time"],
                    "candle2_low": result["candle2_low"],
                    "candle2_high": result["candle2_high"],
                }
                state_changed = True
                continue

        if symbol not in pending:
            continue

        p = pending[symbol]
        if "status" not in p:
            del pending[symbol]
            state_changed = True
            continue

        MAX_PENDING_AGE_MS = 7 * 24 * 60 * 60 * 1000
        if p["status"] != "position_open" and now_ms - p["candle2_time"] > MAX_PENDING_AGE_MS:
            send_telegram(f"⏱️ {symbol}: تم إلغاء نموذج قديم جداً (تجاوز المهلة القصوى بلا تقدم)")
            del pending[symbol]
            state_changed = True
            continue

        direction = p["direction"]

        if result and str(p["candle2_time"]) != str(result["candle2_time"]) and p["status"] in ("waiting_confirmation",):
            del pending[symbol]
            state_changed = True
            continue

        candle2_start = p["candle2_time"]
        candle2_end = candle2_start + (60*60*1000)
        m5_candles = get_klines(symbol, "5m", limit=1500, start_time=candle2_start)
        closed_m5 = trim_incomplete(m5_candles, 5*60*1000, now_ms)

        if p["status"] == "waiting_confirmation":
            window_12 = [c for c in closed_m5 if candle2_start <= c["open_time"] < candle2_end]
            if "entry_open" not in p:
                if len(window_12) < 12:
                    continue
                entry_candle = find_entry_candle(window_12, direction)
                if entry_candle is None:
                    send_telegram(f"❌ {symbol}: لم توجد شمعة دخول صالحة، تم إلغاء النموذج")
                    del pending[symbol]
                    state_changed = True
                    continue
                p["entry_open"] = entry_candle["open"]
                p["entry_time"] = entry_candle["open_time"]
                state_changed = True

            sl_level = p["candle2_low"] if direction == "bullish" else p["candle2_high"]
            far_target = p["candle1_high"] if direction == "bullish" else p["candle1_low"]
            candles_to_check = [c for c in closed_m5 if c["open_time"] > p["entry_time"]]
            status, confirm_time = check_confirmation(candles_to_check, p["entry_open"], direction, sl_level, far_target)

            if status == "CANCELLED":
                send_telegram(f"❌ {symbol}: تم إلغاء النموذج (كسر SL أو وصل السعر للهدف قبل تحقق التأكيد)\n   وقت الإلغاء (UTC): {fmt(confirm_time)}")
                del pending[symbol]
                state_changed = True
            elif status == "CONFIRMED":
                emoji = "🟢" if direction == "bullish" else "🔴"
                send_telegram(
                    f"✅ تأكيد! بانتظار تنفيذ السعر الأرخص\n\n"
                    f"{emoji} {symbol}\n"
                    f"   سعر الدخول المستهدف: {p['entry_open']}\n"
                    f"   وقت التأكيد (UTC): {fmt(confirm_time)}"
                )
                p["status"] = "waiting_fill"
                p["confirm_time"] = confirm_time
                state_changed = True
            continue

        if p["status"] == "waiting_fill":
            far_target = p["candle1_high"] if direction == "bullish" else p["candle1_low"]
            effective_start = max(p["confirm_time"], candle2_end - 1)
            candles_to_check = [c for c in closed_m5 if c["open_time"] > effective_start]
            status, fill_time = check_fill(candles_to_check, p["entry_open"], direction, far_target)

            if status == "CANCELLED_NO_FILL":
                send_telegram(f"❌ {symbol}: وصل السعر للهدف البعيد دون تنفيذ الأمر — إلغاء تام")
                del pending[symbol]
                state_changed = True
            elif status == "CANCELLED_OUTSIDE_WINDOW":
                send_telegram(f"❌ {symbol}: تحقق التنفيذ لكن أثناء حظر الأخبار (FOMC/CPI) — إلغاء تام\n   وقت اللمسة (UTC): {fmt(fill_time)}")
                del pending[symbol]
                state_changed = True
            elif status == "FILLED":
                sl_buf = SL_BUFFER[symbol]
                sl_off = STOPLIMIT_OFFSET[symbol]
                if direction == "bullish":
                    sl_trigger = p["candle2_low"] - sl_buf
                    sl_limit = sl_trigger - sl_off
                else:
                    sl_trigger = p["candle2_high"] + sl_buf
                    sl_limit = sl_trigger + sl_off
                tp1 = p["TP1"]

                # حساب حجم المخاطرة (نظام القمة + التقلب المُحدَّث) -- لأغراض العرض في Shadow Mode
                account_peak = state.get("account_equity_peak", 1.0)
                account_current = state.get("account_equity_current", 1.0)
                base_risk = RISK_BASE_PEAK if account_current >= account_peak else RISK_BASE_DRAWDOWN
                vp = compute_vol_percentile(state, symbol, atr_pct) if atr_pct is not None else 0.5
                vm = vol_multiplier(vp)
                final_risk_pct = base_risk * vm

                emoji = "🟢" if direction == "bullish" else "🔴"
                send_telegram(
                    f"🎯 صفقة افتراضية مفتوحة! (Shadow Mode)\n\n"
                    f"{emoji} {symbol}\n"
                    f"   الدخول: {p['entry_open']}\n"
                    f"   وقف الخسارة: {sl_trigger:.4f}\n"
                    f"   الهدف (TP1): {tp1:.4f}\n"
                    f"   المخاطرة المقترحة من رأس المال: {final_risk_pct*100:.2f}%\n"
                    f"   وقت التنفيذ (UTC): {fmt(fill_time)}"
                )
                p["status"] = "position_open"
                p["fill_time"] = fill_time
                p["sl_trigger"] = sl_trigger
                p["sl_limit"] = sl_limit
                p["tp1"] = tp1
                p["risk_pct_used"] = final_risk_pct
                state_changed = True
            continue

        if p["status"] == "position_open":
            candles_to_check = [c for c in closed_m5 if c["open_time"] >= p["fill_time"]]
            outcome, exit_time = check_position(candles_to_check, direction, p["sl_trigger"], p["sl_limit"], p["tp1"])

            if outcome:
                emoji = "✅" if outcome == "TP1" else "❌"
                result_ar = "ربح (وصل الهدف)" if outcome == "TP1" else "خسارة (ضرب وقف الخسارة)"

                # تحديث رصيد الحساب الافتراضي (Shadow Mode) لتتبع القمة لاحقاً
                if direction == "bullish":
                    pnl_pct = ((p["tp1"]-p["entry_open"])/p["entry_open"]) if outcome=="TP1" else ((p["sl_limit"]-p["entry_open"])/p["entry_open"])
                    price_risk_pct = (p["entry_open"]-p["sl_trigger"])/p["entry_open"]
                else:
                    pnl_pct = ((p["entry_open"]-p["tp1"])/p["entry_open"]) if outcome=="TP1" else ((p["entry_open"]-p["sl_limit"])/p["entry_open"])
                    price_risk_pct = (p["sl_trigger"]-p["entry_open"])/p["entry_open"]

                r_multiple = pnl_pct / price_risk_pct if price_risk_pct > 0 else 0
                account_current = state.get("account_equity_current", 1.0)
                account_current *= (1 + p["risk_pct_used"] * r_multiple)
                account_peak = max(state.get("account_equity_peak", 1.0), account_current)
                state["account_equity_current"] = account_current
                state["account_equity_peak"] = account_peak

                send_telegram(
                    f"{emoji} إغلاق الصفقة الافتراضية\n\n"
                    f"{symbol}: {result_ar}\n"
                    f"   وقت الإغلاق (UTC): {fmt(exit_time)}\n"
                    f"   رأس المال الافتراضي التراكمي: {account_current:.4f}×"
                )
                del pending[symbol]
                state_changed = True

    if state_changed:
        state["last_candle2_time"] = last_seen
        state["pending_confirmation"] = pending
        save_state(state)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            send_telegram(f"🚨 خطأ غير متوقع أوقف البوت هذه التشغيلة:\n\n{type(e).__name__}: {str(e)}")
        except Exception:
            pass  # حتى لو فشل إرسال التنبيه نفسه، لا نُريد أن يُخفي هذا الخطأ الأصلي
        raise  # نُعيد رفع الخطأ حتى يظهر بوضوح في سجل GitHub Actions أيضاً
