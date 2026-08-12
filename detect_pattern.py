import os
import json
import requests
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
GIST_TOKEN = os.environ['GIST_TOKEN']
GIST_ID = os.environ['GIST_ID']

BINANCE_BASE = "https://fapi.binance.com"
WICK_THRESHOLD_PCT = 40.0

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

# ---------- Binance ----------
def get_klines(symbol, interval, limit=100, start_time=None, end_time=None):
    url = f"{BINANCE_BASE}/fapi/v1/klines"
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
            "open_time": c[0],
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
        })
    return candles

# ---------- منطق كشف النموذج على فريم الساعة ----------
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
        mid1 = (high1 + low1) / 2.0
        range1 = high1 - low1

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
                if cj["high"] < mid1 and open_in_range and close_in_range:
                    found = True
                    direction = "bullish"
                    c2 = cj
                break
            elif breaks_top and not breaks_bottom:
                if cj["low"] > mid1 and open_in_range and close_in_range:
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
            last_found = {
                "direction": direction,
                "candle1_time": c1["open_time"],
                "candle1_high": high1,
                "candle1_low": low1,
                "mid1": mid1,
                "candle2_high": c2["high"],
                "candle2_low": c2["low"],
                "candle2_close": c2["close"],
                "candle2_open": c2["open"],
                "wick_pct": wick_pct,
                "candle2_time": c2["open_time"],
            }

        idx = j + 1

    return last_found

# ---------- منطق تحديد شمعة الدخول على فريم 5 دقائق ----------
def find_entry_candle(m5_candles_window, direction):
    """
    m5_candles_window: الـ12 شمعة 5 دقائق المكوّنة لشمعة السحب
    """
    if direction == "bullish":
        bearish = [c for c in m5_candles_window if c["close"] < c["open"]]
        if not bearish:
            return None
        entry_candle = min(bearish, key=lambda c: c["low"])
    else:
        bullish = [c for c in m5_candles_window if c["close"] > c["open"]]
        if not bullish:
            return None
        entry_candle = max(bullish, key=lambda c: c["high"])
    return entry_candle

# ---------- منطق البحث عن التأكيد ----------
def check_confirmation(m5_candles_after, entry_open, direction, sl_level):
    """
    يبحث بين شموع 5 دقائق التي حدثت بعد شمعة الدخول عن:
    - تأكيد (إغلاق فوق/تحت افتتاح شمعة الدخول)
    - أو إلغاء (كسر مستوى SL قبل التأكيد)
    يرجع: ("CONFIRMED", وقت التأكيد) أو ("CANCELLED", None) أو (None, None) إن لم يحدث شيء بعد
    """
    for c in m5_candles_after:
        if direction == "bullish":
            if c["low"] <= sl_level:
                return "CANCELLED", None
            if c["close"] > entry_open:
                return "CONFIRMED", c["open_time"]
        else:
            if c["high"] >= sl_level:
                return "CANCELLED", None
            if c["close"] < entry_open:
                return "CONFIRMED", c["open_time"]
    return None, None

def main():
    state = load_state()
    last_seen = state.get("last_candle2_time", {})
    pending = state.get("pending_confirmation", {})  # نماذج بانتظار التأكيد
    state_changed = False

    now_ms = datetime.now(timezone.utc).timestamp() * 1000

    for symbol in ["BTCUSDT", "ETHUSDT"]:
        h1_candles = get_klines(symbol, "1h", limit=100)
        current_price = h1_candles[-1]["close"]
        closed_h1 = h1_candles[:-1]
        result = find_pattern(closed_h1)

        if not result:
            continue

        candle2_time_str = str(result["candle2_time"])

        # حالة 1: نموذج جديد لم نره من قبل إطلاقاً -> نبدأ تتبعه
        if candle2_time_str != last_seen.get(symbol) and symbol not in pending:
            emoji = "🟢" if result["direction"] == "bullish" else "🔴"
            direction_ar = "صاعد" if result["direction"] == "bullish" else "هابط"
            candle1_dt = datetime.fromtimestamp(result["candle1_time"]/1000, tz=timezone.utc)
            candle2_dt = datetime.fromtimestamp(result["candle2_time"]/1000, tz=timezone.utc)

            send_telegram(
                f"🆕 نموذج جديد! (بانتظار تأكيد فريم 5 دقائق)\n\n"
                f"{emoji} {symbol}: نموذج {direction_ar}\n"
                f"   عمق الفتيل: {result['wick_pct']:.1f}%\n"
                f"   وقت شمعة النطاق: {candle1_dt.strftime('%Y-%m-%d %H:%M')}\n"
                f"   وقت شمعة السحب: {candle2_dt.strftime('%Y-%m-%d %H:%M')}\n"
                f"   السعر الحالي: {current_price}"
            )

            last_seen[symbol] = candle2_time_str
            pending[symbol] = {
                "direction": result["direction"],
                "candle1_high": result["candle1_high"],
                "candle1_low": result["candle1_low"],
                "mid1": result["mid1"],
                "candle2_time": result["candle2_time"],
                "candle2_low": result["candle2_low"],
                "candle2_high": result["candle2_high"],
                "entry_candle_found": False,
                "confirmed": False,
            }
            state_changed = True
            continue

        # حالة 2: هناك نموذج قيد التتبع لهذا الرمز -> نتابع مرحلة فريم 5 دقائق
        if symbol in pending:
            p = pending[symbol]
            direction = p["direction"]

            # هل تغيّر النموذج (نموذج أحدث ظهر بينما كنا ننتظر)؟ إن كان كذلك، نُلغي القديم ونبدأ الجديد
            if str(p["candle2_time"]) != candle2_time_str:
                del pending[symbol]
                state_changed = True
                continue

            candle2_start = p["candle2_time"]
            candle2_end = candle2_start + (60*60*1000)  # ساعة كاملة بعدها

            m5_candles = get_klines(symbol, "5m", limit=1500, start_time=candle2_start)
            closed_m5 = m5_candles[:-1]  # نستبعد الشمعة غير المكتملة

            window_12 = [c for c in closed_m5 if candle2_start <= c["open_time"] < candle2_end]

            if not p["entry_candle_found"]:
                if len(window_12) < 12:
                    continue  # لم تكتمل الـ12 شمعة بعد، ننتظر
                entry_candle = find_entry_candle(window_12, direction)
                if entry_candle is None:
                    send_telegram(f"❌ {symbol}: لم توجد شمعة دخول صالحة، تم إلغاء النموذج")
                    del pending[symbol]
                    state_changed = True
                    continue
                p["entry_open"] = entry_candle["open"]
                p["entry_time"] = entry_candle["open_time"]
                p["entry_candle_found"] = True
                state_changed = True

            if p["entry_candle_found"] and not p["confirmed"]:
                sl_level = p["candle2_low"] if direction == "bullish" else p["candle2_high"]
                # نفحص كل شمعة تلت شمعة الدخول مباشرة، سواء كانت لا تزال ضمن ساعة شمعة السحب أو بعدها
                candles_to_check = [c for c in closed_m5 if c["open_time"] > p["entry_time"]]
                status, confirm_time = check_confirmation(candles_to_check, p["entry_open"], direction, sl_level)

                if status == "CANCELLED":
                    send_telegram(f"❌ {symbol}: تم إلغاء النموذج (كسر السعر مستوى SL قبل التأكيد)")
                    del pending[symbol]
                    state_changed = True
                    continue
                elif status == "CONFIRMED":
                    emoji = "🟢" if direction == "bullish" else "🔴"
                    send_telegram(
                        f"✅ تأكيد! جاهز للدخول (Shadow Mode)\n\n"
                        f"{emoji} {symbol}\n"
                        f"   سعر الدخول المستهدف: {p['entry_open']}\n"
                        f"   وقت التأكيد (UTC): {datetime.fromtimestamp(confirm_time/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}"
                    )
                    p["confirmed"] = True
                    state_changed = True
                    # المرحلة التالية (انتظار التنفيذ الفعلي، SL/TP) ستُضاف لاحقاً

    if state_changed:
        state["last_candle2_time"] = last_seen
        state["pending_confirmation"] = pending
        save_state(state)

if __name__ == "__main__":
    main()
