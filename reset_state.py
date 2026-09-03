import os
import json
import requests

GIST_TOKEN = os.environ['GIST_TOKEN']
GIST_ID = os.environ['GIST_ID']

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

# فقط هذان المفتاحان يخصّان "حالة الصفقات الجارية" ويجب تصفيرهما دائماً
# كل شيء آخر (سبريد، تاريخ تقلب، تاريخ حجم، رأس مال افتراضي) بيانات تراكمية تُحفظ دائماً
TRADE_STATE_KEYS_TO_RESET = ["last_candle2_time", "pending_confirmation"]

def main():
    state = load_state()

    new_state = dict(state)  # نسخ كل شيء كما هو أولاً
    new_state["last_candle2_time"] = {}
    new_state["pending_confirmation"] = {}

    save_state(new_state)
    preserved_keys = [k for k in state.keys() if k not in TRADE_STATE_KEYS_TO_RESET]
    print("تم تصفير last_candle2_time و pending_confirmation بنجاح.")
    print(f"تم الحفاظ على كل البيانات التراكمية الأخرى: {preserved_keys}")

if __name__ == "__main__":
    main()
