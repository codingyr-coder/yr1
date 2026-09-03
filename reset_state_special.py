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

# تصفير خاص لمرة واحدة بعد تحديث جوهري للإستراتيجية:
# - نُصفّر حالة الصفقات (كالمعتاد)
# - نُصفّر رأس المال الافتراضي أيضاً (لأنه نتاج قواعد قديمة لم تعد سارية)
# - نحتفظ ببيانات السوق الخام (سبريد، تاريخ تقلب، تاريخ حجم) لأنها لا تزال صحيحة ومفيدة

def main():
    state = load_state()

    new_state = dict(state)
    new_state["last_candle2_time"] = {}
    new_state["pending_confirmation"] = {}
    new_state["account_equity_current"] = 1.0
    new_state["account_equity_peak"] = 1.0

    save_state(new_state)
    print("تم تصفير حالة الصفقات ورأس المال الافتراضي بنجاح.")
    print("تم الحفاظ على بيانات السوق (سبريد، تقلب، حجم) كما هي.")

if __name__ == "__main__":
    main()
