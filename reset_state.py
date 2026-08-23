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

def main():
    state = load_state()

    preserved_spread_stats = state.get("spread_stats", {})

    new_state = {
        "last_candle2_time": {},
        "pending_confirmation": {},
        "spread_stats": preserved_spread_stats,
    }

    save_state(new_state)
    print("تم تصفير last_candle2_time و pending_confirmation بنجاح.")
    print(f"تم الحفاظ على spread_stats كما هو (عدد العملات المُسجَّلة: {len(preserved_spread_stats)}).")

if __name__ == "__main__":
    main()
