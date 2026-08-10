import os
import requests
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

BINANCE_BASE = "https://testnet.binancefuture.com"
WICK_THRESHOLD_PCT = 40.0

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})

def get_klines(symbol, interval, limit=100):
    url = f"{BINANCE_BASE}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
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
                "wick_pct": wick_pct,
                "candle2_time": c2["open_time"],
            }

        idx = j + 1

    return last_found

def main():
    report_lines = []
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    for symbol in ["BTCUSDT", "ETHUSDT"]:
        candles = get_klines(symbol, "1h", limit=100)
        result = find_pattern(candles)
        current_price = candles[-1]["close"]
        if result:
            emoji = "🟢" if result["direction"] == "bullish" else "🔴"
            direction_ar = "صاعد" if result["direction"] == "bullish" else "هابط"
            candle1_dt = datetime.fromtimestamp(result["candle1_time"]/1000, tz=timezone.utc)
            candle2_dt = datetime.fromtimestamp(result["candle2_time"]/1000, tz=timezone.utc)
            hours_ago = (now_ms - result["candle2_time"]) / (1000*3600)
            staleness = "🟢 حديث (خلال آخر ساعتين)" if hours_ago <= 2 else f"⚠️ قديم ({hours_ago:.1f} ساعة مضت)"
            report_lines.append(
                f"{emoji} {symbol}: نموذج {direction_ar} صالح\n"
                f"   عمق الفتيل: {result['wick_pct']:.1f}%\n"
                f"   --- شمعة النطاق (Candle 1) ---\n"
                f"   وقتها (UTC): {candle1_dt.strftime('%Y-%m-%d %H:%M')}\n"
                f"   قمة النطاق: {result['candle1_high']}\n"
                f"   قاع النطاق: {result['candle1_low']}\n"
                f"   مستوى 50%: {result['mid1']:.2f}\n"
                f"   --- شمعة السحب (Candle 2) ---\n"
                f"   وقتها (UTC): {candle2_dt.strftime('%Y-%m-%d %H:%M')}\n"
                f"   قمتها: {result['candle2_high']}\n"
                f"   قاعها: {result['candle2_low']}\n"
                f"   إغلاقها: {result['candle2_close']}\n"
                f"   الحالة: {staleness}\n"
                f"   السعر الحالي: {current_price}"
            )
        else:
            report_lines.append(f"⚪ {symbol}: لا يوجد نموذج صالح حالياً\n   السعر الحالي: {current_price}")

    message = "📊 تقرير كشف النموذج\n\n" + "\n\n".join(report_lines)
    send_telegram(message)

if __name__ == "__main__":
    main()
