# -*- coding: utf-8 -*-
"""补抓 429 失败的热播剧详情，串行低频重试，然后重建表格"""
import json, os, time, urllib.request
import importlib.util

OUT = os.path.dirname(os.path.abspath(__file__))
BASE = "https://api.starry.wang/api"
HEADERS = {"User-Agent": "okhttp/4.12.0", "Accept": "application/json", "X-App-Version-Code": "46"}

def get(url, tries=6, base_sleep=2.0):
    req = urllib.request.Request(url, headers=HEADERS)
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(base_sleep * (i + 1))
                continue
            raise
        except Exception:
            time.sleep(base_sleep * (i + 1))
    return None

def main():
    with open(os.path.join(OUT, "hot_dramas.json"), encoding="utf-8") as f:
        hot = json.load(f)
    dpath = os.path.join(OUT, "hot_dramas_detail.json")
    details = {}
    if os.path.exists(dpath):
        with open(dpath, encoding="utf-8") as f:
            for d in json.load(f):
                details[d["id"]] = d
    missing = [h["id"] for h in hot if h["id"] not in details]
    print(f"[i] have {len(details)}, missing {len(missing)}")

    for n, did in enumerate(missing, 1):
        r = get(f"{BASE}/dramas/{did}")
        if r and r.get("data"):
            details[did] = r["data"]
            print(f"[+] {n}/{len(missing)} id={did} ok (total {len(details)})")
        else:
            print(f"[!] {n}/{len(missing)} id={did} still failed")
        time.sleep(1.0)

    with open(dpath, "w", encoding="utf-8") as f:
        json.dump([details[h["id"]] for h in hot if h["id"] in details], f, ensure_ascii=False, indent=2)
    print(f"[=] details total {len(details)}/{len(hot)}")

if __name__ == "__main__":
    main()
