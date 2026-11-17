# -*- coding: utf-8 -*-
"""抓取 com.starry.wang 短剧 App 的热播剧数据 (GET /api/dramas/hot)"""
import json, time, urllib.request, urllib.error, os, csv

BASE = "https://api.starry.wang/api"
HEADERS = {
    "User-Agent": "okhttp/4.12.0",
    "Accept": "application/json",
    "X-App-Version-Code": "46",
}
OUT = os.path.dirname(os.path.abspath(__file__))

def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(1.5)

def fetch_hot():
    first = get(f"{BASE}/dramas/hot?page=1&pageSize=100")
    total = first["data"]["total"]
    total_pages = first["data"]["totalPages"]
    items = list(first["data"]["list"])
    print(f"[+] total={total} totalPages={total_pages} page1={len(items)}")
    for p in range(2, total_pages + 1):
        d = get(f"{BASE}/dramas/hot?page={p}&pageSize=100")
        batch = d["data"]["list"]
        items.extend(batch)
        print(f"[+] page {p}/{total_pages} +{len(batch)} (acc={len(items)})")
        time.sleep(0.25)
    # 去重保序
    seen, uniq = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)
    print(f"[=] unique dramas: {len(uniq)}")
    return uniq

def main():
    data = fetch_hot()
    with open(os.path.join(OUT, "hot_dramas.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    cols = ["rank", "id", "title", "category", "tags", "totalEpisodes", "status",
            "isSerializing", "isNewDrama", "hotScore", "viewCount", "creatorName",
            "badge", "coverUrl", "description"]
    rows = []
    for i, d in enumerate(data, 1):
        badge = d.get("cornerBadge") or {}
        rows.append({
            "rank": i,
            "id": d.get("id"),
            "title": (d.get("title") or "").replace("\n", " "),
            "category": d.get("category"),
            "tags": "/".join(d.get("tags") or []),
            "totalEpisodes": d.get("totalEpisodes"),
            "status": d.get("status"),
            "isSerializing": d.get("isSerializing"),
            "isNewDrama": d.get("isNewDrama"),
            "hotScore": d.get("hotScore"),
            "viewCount": d.get("viewCount"),
            "creatorName": d.get("creatorName"),
            "badge": badge.get("name"),
            "coverUrl": d.get("coverUrl"),
            "description": (d.get("description") or "").replace("\n", " "),
        })

    csv_path = os.path.join(OUT, "hot_dramas.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"[=] saved {csv_path} ({len(rows)} rows)")

    try:
        import pandas as pd
        df = pd.DataFrame(rows, columns=cols)
        xlsx = os.path.join(OUT, "hot_dramas.xlsx")
        with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
            df.to_excel(xw, index=False, sheet_name="hot_dramas")
            from openpyxl.utils import get_column_letter
            ws = xw.sheets["hot_dramas"]
            for idx, col in enumerate(cols, 1):
                width = 12
                if col in ("title", "description"):
                    width = 50
                elif col in ("coverUrl", "tags", "creatorName"):
                    width = 30
                ws.column_dimensions[get_column_letter(idx)].width = width
            ws.freeze_panes = "A2"
        print(f"[=] saved {xlsx}")
    except Exception as e:
        print("[!] xlsx skipped:", e)

    # 统计摘要
    print("\n=== TOP 15 热播 ===")
    for r in rows[:15]:
        print(f"{r['rank']:>3}. {r['title']}  | {r['category']} | {r['totalEpisodes']}集 | hot={r['hotScore']} | 播放={r['viewCount']} | {r['creatorName']}")

if __name__ == "__main__":
    main()
