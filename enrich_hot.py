# -*- coding: utf-8 -*-
"""对热播剧列表逐条抓 /api/dramas/{id} 详情并合并成完整表"""
import json, os, time, csv, urllib.request, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://api.starry.wang/api"
HEADERS = {"User-Agent": "okhttp/4.12.0", "Accept": "application/json", "X-App-Version-Code": "46"}
OUT = os.path.dirname(os.path.abspath(__file__))

def get(url, tries=4):
    req = urllib.request.Request(url, headers=HEADERS)
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(0.6 * (i + 1))
    raise last

def main():
    with open(os.path.join(OUT, "hot_dramas.json"), encoding="utf-8") as f:
        hot = json.load(f)

    lock = threading.Lock()
    done = [0]
    details = {}

    def work(d):
        did = d["id"]
        try:
            r = get(f"{BASE}/dramas/{did}")
            with lock:
                done[0] += 1
                if done[0] % 50 == 0:
                    print(f"[+] {done[0]}/{len(hot)}")
            return did, r.get("data")
        except Exception as e:
            with lock:
                done[0] += 1
            print(f"[!] {did} failed: {e}")
            return did, None

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(work, d) for d in hot]
        for fu in as_completed(futs):
            did, data = fu.result()
            if data:
                details[did] = data
    print(f"[=] details fetched: {len(details)}/{len(hot)} in {time.time()-t0:.1f}s")

    with open(os.path.join(OUT, "hot_dramas_detail.json"), "w", encoding="utf-8") as f:
        json.dump(list(details.values()), f, ensure_ascii=False, indent=2)

    cols = ["rank", "id", "title", "seriesTitle", "seasonNo", "category", "tags",
            "maleRoles", "femaleRoles", "totalEpisodes", "freeEpisodeCount", "mode",
            "wholePrice", "batchDiscount", "status", "isSerializing", "isNewDrama",
            "hotScore", "viewCount", "creatorId", "creatorName", "vodClassId",
            "seriesId", "createdAt", "updatedAt", "coverUrl", "description"]
    rows = []
    for i, h in enumerate(hot, 1):
        d = details.get(h["id"], {})
        badge = h.get("cornerBadge") or {}
        rows.append({
            "rank": i,
            "id": h["id"],
            "title": h.get("title"),
            "seriesTitle": d.get("seriesTitle"),
            "seasonNo": d.get("seasonNo"),
            "category": h.get("category"),
            "tags": "/".join(h.get("tags") or []),
            "maleRoles": d.get("maleRoles"),
            "femaleRoles": d.get("femaleRoles"),
            "totalEpisodes": h.get("totalEpisodes"),
            "freeEpisodeCount": d.get("freeEpisodeCount"),
            "mode": d.get("mode"),
            "wholePrice": d.get("wholePrice"),
            "batchDiscount": d.get("batchDiscount"),
            "status": h.get("status"),
            "isSerializing": h.get("isSerializing"),
            "isNewDrama": h.get("isNewDrama"),
            "hotScore": h.get("hotScore"),
            "viewCount": h.get("viewCount"),
            "creatorId": d.get("creatorId"),
            "creatorName": h.get("creatorName"),
            "vodClassId": d.get("vodClassId"),
            "seriesId": d.get("seriesId"),
            "createdAt": d.get("createdAt"),
            "updatedAt": d.get("updatedAt"),
            "coverUrl": h.get("coverUrl"),
            "description": (h.get("description") or "").replace("\n", " "),
        })

    csv_path = os.path.join(OUT, "hot_dramas_full.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"[=] {csv_path}")

    import pandas as pd
    df = pd.DataFrame(rows, columns=cols)
    xlsx = os.path.join(OUT, "热播剧数据.xlsx")
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="热播剧TOP708")
        from openpyxl.utils import get_column_letter
        from openpyxl.styles import Font, Alignment, PatternFill
        ws = xw.sheets["热播剧TOP708"]
        head_fill = PatternFill("solid", fgColor="1F4E79")
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
        for idx, col in enumerate(cols, 1):
            width = 12
            if col == "title":
                width = 34
            elif col == "description":
                width = 60
            elif col in ("coverUrl", "tags", "creatorName", "seriesTitle"):
                width = 28
            ws.column_dimensions[get_column_letter(idx)].width = width
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = ws.dimensions

        # 统计页
        stat = []
        stat.append(["指标", "值"])
        stat.append(["热播剧总数", len(rows)])
        stat.append(["总集数合计", int(df["totalEpisodes"].fillna(0).sum())])
        stat.append(["总播放量合计", int(df["viewCount"].fillna(0).sum())])
        stat.append(["连载中数量", int((df["isSerializing"] == True).sum())])
        stat.append(["已完结数量", int((df["isSerializing"] == False).sum())])
        stat.append(["新剧数量", int((df["isNewDrama"] == True).sum())])
        stat.append([])
        stat.append(["分类", "数量"])
        for k, v in df["category"].value_counts().items():
            stat.append([k, int(v)])
        stat.append([])
        stat.append(["标签", "数量"])
        tagcnt = {}
        for t in (h.get("tags") or [] for h in hot):
            for x in t:
                tagcnt[x] = tagcnt.get(x, 0) + 1
        for k, v in sorted(tagcnt.items(), key=lambda kv: -kv[1])[:30]:
            stat.append([k, v])
        stat.append([])
        stat.append(["创作者", "上榜剧数"])
        for k, v in df["creatorName"].value_counts().head(30).items():
            stat.append([k, int(v)])

        sdf = pd.DataFrame(stat)
        sdf.to_excel(xw, index=False, sheet_name="统计汇总", header=False)
        ws2 = xw.sheets["统计汇总"]
        ws2.column_dimensions["A"].width = 30
        ws2.column_dimensions["B"].width = 14
        for r in ws2.iter_rows():
            for c in r:
                if isinstance(c.value, str) and c.column == 1 and c.value in ("指标", "分类", "标签", "创作者"):
                    c.font = Font(bold=True, color="FFFFFF")
                    c.fill = head_fill
    print(f"[=] {xlsx}")

if __name__ == "__main__":
    main()
