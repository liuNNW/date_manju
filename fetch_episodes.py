# -*- coding: utf-8 -*-
"""抓取全部 708 部热播剧的分集数据 GET /api/episodes/drama/{dramaId}
   支持断点续抓（复用已存 episodes.json），温和限速避免 429。
"""
import json, os, time, urllib.request, urllib.error, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

OUT = os.path.dirname(os.path.abspath(__file__))
BASE = "https://api.starry.wang/api"
HEADERS = {"User-Agent": "okhttp/4.12.0", "Accept": "application/json", "X-App-Version-Code": "46"}
STORE = os.path.join(OUT, "episodes.json")

def get(url, tries=8):
    req = urllib.request.Request(url, headers=HEADERS)
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3.0 * (i + 1))
                continue
            raise
        except Exception:
            time.sleep(2.0 * (i + 1))
    return None

def main():
    hot = json.load(open(os.path.join(OUT, "hot_dramas.json"), encoding="utf-8"))
    store = {}
    if os.path.exists(STORE):
        try:
            store = json.load(open(STORE, encoding="utf-8"))
            store = {int(k): v for k, v in store.items()}
        except Exception:
            store = {}
    todo = [h["id"] for h in hot if h["id"] not in store]
    print(f"[i] cached {len(store)} dramas, todo {len(todo)}", flush=True)

    lock = threading.Lock()
    n = [0]

    def work(did):
        r = get(f"{BASE}/episodes/drama/{did}")
        with lock:
            n[0] += 1
            if n[0] % 20 == 0:
                print(f"[+] {n[0]}/{len(todo)}", flush=True)
                # 增量落盘
                json.dump({str(k): v for k, v in store.items()}, open(STORE, "w", encoding="utf-8"), ensure_ascii=False)
        if r and isinstance(r.get("data"), list):
            return did, r["data"]
        return did, None

    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(work, d): d for d in todo}
        for fu in as_completed(futs):
            did, eps = fu.result()
            if eps is not None:
                store[did] = eps
            else:
                print(f"[!] {did} empty/failed", flush=True)

    json.dump({str(k): v for k, v in store.items()}, open(STORE, "w", encoding="utf-8"), ensure_ascii=False)
    total_eps = sum(len(v) for v in store.values())
    print(f"[=] dramas with episodes: {len(store)}/{len(hot)}, episodes: {total_eps}", flush=True)

if __name__ == "__main__":
    main()
