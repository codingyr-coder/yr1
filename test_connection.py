import os
import time
import hmac
import hashlib
import requests

API_KEY = os.environ['BINANCE_API_KEY']
API_SECRET = os.environ['BINANCE_API_SECRET']
TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

BASE_URL = "https://testnet.binancefuture.com"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})

def get_binance_balance():
    endpoint = "/fapi/v2/balance"
    timestamp = int(time.time() * 1000)
    query_string = f"timestamp={timestamp}"
    signature = hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE_URL}{endpoint}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": API_KEY}
    response = requests.get(url, headers=headers)
    return response.json()

try:
    balance_data = get_binance_balance()
    if isinstance(balance_data, list):
        usdt_balance = next((b['balance'] for b in balance_data if b['asset']=='USDT'), 'غير موجود')
        send_telegram(f"✅ الاتصال ناجح!\nرصيد USDT التجريبي: {usdt_balance}")
    else:
        send_telegram(f"⚠️ اتصل لكن هناك خطأ من Binance:\n{balance_data}")
except Exception as e:
    send_telegram(f"❌ فشل الاتصال: {str(e)}")
