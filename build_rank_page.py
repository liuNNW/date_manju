# -*- coding: utf-8 -*-
"""
构建「HiTwo 短剧榜 v2」单文件网页
================================
四个一级分类：热门 / 新剧 / 更新 / 榜单（完结榜·黑马榜·礼物榜）

用法：
    python build_rank_page.py                  # 分集数据重抓（推荐，保证"更新"新鲜）
    python build_rank_page.py --no-episodes    # 复用 episodes.json 缓存（快，几秒）
    python build_rank_page.py --refresh        # 详情也全部重抓

数据源（均为游客可读公开接口）：
    GET /api/dramas/hot?page=N&pageSize=100         全库按热度排序
    GET /api/dramas/{id}                            详情（价格/免费集/简介/上线时间）
    GET /api/episodes/drama/{id}                     分集（算最后更新时间与近期更新量）
    GET /api/dramas/rankings/gifts                   礼物榜（含 giftQuantity）
"""
import argparse, json, os, statistics, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

BASE = "https://api.starry.wang/api"
COVER = "https://vod.starry.wang/covers/"
HDR = {"User-Agent": "okhttp/4.12.0", "Accept": "application/json"}
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DETAIL = os.path.join(HERE, "hot_dramas_detail.json")
CACHE_EPS = os.path.join(HERE, "episodes.json")
TPL = os.path.join(HERE, "rank_template.html")
OUT = os.path.join(HERE, "短剧榜单.html")

# 黑马榜参数
DARK_MIN_AGE, DARK_MAX_AGE, DARK_TOP_PCT = 7, 45, 0.20
# 更新榜窗口（天）
UPD_WINDOW = 7


def get(path, tries=6):
    url = path if path.startswith("http") else BASE + path
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2.5 * (i + 1))
                continue
            if i == tries - 1:
                return None
            time.sleep(1.5)
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.5 * (i + 1))
    return None


def fetch_hot():
    first = get("/dramas/hot?page=1&pageSize=100")
    d = first["data"]
    items = list(d["list"])
    for p in range(2, d["totalPages"] + 1):
        r = get(f"/dramas/hot?page={p}&pageSize=100")
        items.extend(r["data"]["list"])
        print(f"[hot] page {p}/{d['totalPages']} acc={len(items)}")
        time.sleep(0.2)
    seen, uniq = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)
    print(f"[hot] total={d['total']} unique={len(uniq)}")
    return uniq


def fetch_details(ids, refresh=False):
    cache = {}
    if os.path.exists(CACHE_DETAIL) and not refresh:
        try:
            for d in json.load(open(CACHE_DETAIL, encoding="utf-8")):
                cache[d["id"]] = d
        except Exception:
            cache = {}
    missing = [i for i in ids if i not in cache]
    print(f"[detail] cached={len(cache)} missing={len(missing)}")
    for n, did in enumerate(missing, 1):
        r = get(f"/dramas/{did}")
        if r and r.get("data"):
            cache[did] = r["data"]
        if n % 40 == 0:
            print(f"[detail] {n}/{len(missing)}")
        time.sleep(0.35)
    if missing:
        json.dump([cache[k] for k in ids if k in cache],
                  open(CACHE_DETAIL, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return cache


def ep_stats_from(list_eps, now):
    """从某剧分集数组算 (最后更新日期, 近N天更新集数, 已发布集数)"""
    ds = []
    for e in list_eps:
        s = e.get("createdAt")
        if not s:
            continue
        try:
            ds.append(datetime.fromisoformat(s.replace("Z", "+00:00")))
        except Exception:
            pass
    if not ds:
        return None, 0, len(list_eps)
    last = max(ds)
    recent = sum(1 for x in ds if (now - x).days <= UPD_WINDOW)
    return last, recent, len(list_eps)


def fetch_episode_stats(ids, refresh=True):
    cache = {}
    if not refresh and os.path.exists(CACHE_EPS):
        try:
            cache = {int(k): v for k, v in json.load(open(CACHE_EPS, encoding="utf-8")).items()}
        except Exception:
            cache = {}
    if refresh or not cache:
        print(f"[eps] 抓取 {len(ids)} 部剧的分集数据（约 2-4 分钟）…")
        done = [0]
        lock = []

        def work(did):
            r = get(f"/episodes/drama/{did}")
            if r and isinstance(r.get("data"), list):
                return did, r["data"]
            return did, None

        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(work, d): d for d in ids}
            for fu in as_completed(futs):
                did, lst = fu.result()
                if lst is not None:
                    cache[did] = lst
                done[0] += 1
                if done[0] % 60 == 0:
                    print(f"[eps] {done[0]}/{len(ids)}")
        json.dump({str(k): v for k, v in cache.items()},
                  open(CACHE_EPS, "w", encoding="utf-8"), ensure_ascii=False)
    else:
        print(f"[eps] 复用缓存 {len(cache)} 部（--no-episodes）")

    now = datetime.now(timezone.utc)
    stats = {}
    for did in ids:
        stats[did] = ep_stats_from(cache.get(did) or [], now)
    return stats


def fetch_gifts():
    r = get("/dramas/rankings/gifts?page=1&pageSize=100")
    lst = ((r or {}).get("data") or {}).get("list") or []
    order, gq = [], {}
    for d in lst:
        order.append(d["id"])
        gq[d["id"]] = d.get("giftQuantity") or 0
    print(f"[gifts] {len(order)} 部")
    return order, gq


def fetch_novels():
    """书城：/api/novels 每页上限 50，按 tags 统计筛选标签。"""
    first = get("/novels?page=1&pageSize=50")
    if not first:
        print("[novels] 抓取失败")
        return [], []
    d = first["data"]
    items = list(d["list"])
    for p in range(2, d["totalPages"] + 1):
        r = get(f"/novels?page={p}&pageSize=50")
        if r:
            items.extend(r["data"]["list"])
        time.sleep(0.2)
    print(f"[novels] total={d['total']} fetched={len(items)}")

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    novels = []
    tagcnt = {}
    for n in items:
        cov = n.get("coverUrl") or ""
        desc = (n.get("description") or "").replace("\n", " ").strip()
        ct = (n.get("createdAt") or "")[:10]
        lu = (n.get("lastContentUpdatedAt") or "")[:10]
        tags = n.get("tags") or []
        for t in tags:
            if t:
                tagcnt[t] = tagcnt.get(t, 0) + 1
        novels.append({
            "i": n["id"],
            "t": n.get("title"),
            "c": cov[len(COVER):] if cov.startswith(COVER) else "",
            "a": n.get("creatorName") or "",
            "g": tags[:8],
            "h": round(n.get("hotScore") or 0),
            "v": n.get("viewCount") or 0,
            "u": n.get("unlockCount") or 0,
            "ch": n.get("totalChapters") or 0,
            "s": 1 if n.get("isSerializing") else 0,
            "ct": ct,
            "ad": day_diff(ct, today),
            "lu": lu,
            "mo": n.get("pricingMode") or "",
            "wp": n.get("wholePrice"),
            "fc": n.get("freeChapterCount") or 0,
            "sd": desc[:120],
        })
    novels.sort(key=lambda x: -(x["h"] or 0))
    tags = [{"name": k, "n": v} for k, v in sorted(tagcnt.items(), key=lambda kv: (-kv[1], kv[0]))]
    print(f"[novels] tags={len(tags)}")
    return novels, tags


def day_diff(iso_date, today):
    if not iso_date:
        return None
    try:
        d = datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc)
        return max(0, (today - d).days)
    except Exception:
        return None


def build(args):
    hot = fetch_hot()
    ids = [h["id"] for h in hot]
    det = fetch_details(ids, refresh=args.refresh)
    stats = fetch_episode_stats(ids, refresh=not args.no_episodes)
    gift_order, gift_qty = fetch_gifts()
    novels, novel_tags = fetch_novels()

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    dramas = []
    for h in hot:
        d = det.get(h["id"], {})
        cov = h.get("coverUrl") or ""
        desc = (d.get("description") or h.get("description") or "").replace("\n", " ").strip()
        ct = (d.get("createdAt") or "")[:10]
        last, recent, count = stats.get(h["id"], (None, 0, 0))
        le = last.strftime("%Y-%m-%d") if last else ""
        dramas.append({
            "i": h["id"],
            "t": h.get("title"),
            "c": cov[len(COVER):] if cov.startswith(COVER) else "",
            "k": h.get("category"),
            "g": (h.get("tags") or [])[:8],
            "h": round(h.get("hotScore") or 0),
            "v": h.get("viewCount") or 0,
            "e": h.get("totalEpisodes") or 0,
            "a": h.get("creatorName") or "",
            "b": ((h.get("cornerBadge") or {}).get("name") or ""),
            "s": 1 if h.get("isSerializing") else 0,
            "ct": ct,
            "ad": day_diff(ct, today),          # 上架天数
            "le": le,                            # 最后更新日期
            "ld": day_diff(le, today),           # 距最后更新天数
            "r7": recent,                        # 近 N 天更新集数
            "pc": count,                         # 已发布集数
            "fp": d.get("freeEpisodeCount"),
            "mo": d.get("mode") or "",
            "wp": d.get("wholePrice"),
            "gq": gift_qty.get(h["id"]),         # 仅礼物榜有
            "sd": desc[:120],
        })

    # ---- 统计与阈值 ----
    hs = sorted((x["h"] for x in dramas), reverse=True)
    dark_thr = hs[int(len(hs) * DARK_TOP_PCT)] if hs else 0
    dark_n = sum(1 for x in dramas
                 if x["ad"] is not None and DARK_MIN_AGE <= x["ad"] <= DARK_MAX_AGE and x["h"] >= dark_thr)
    upd_n = sum(1 for x in dramas if x["r7"] > 0)
    fin_n = sum(1 for x in dramas if x["s"] == 0)
    new7_n = sum(1 for x in dramas if x["ad"] is not None and x["ad"] <= 7)

    cnt = {}
    for x in dramas:
        k = x["k"] or "其他"
        cnt[k] = cnt.get(k, 0) + 1
    hit = {}
    for x in dramas:
        for k in set([x["k"]] + list(x["g"] or [])):
            if k:
                hit[k] = hit.get(k, 0) + 1
    categories = [{"name": k, "n": hit.get(k, 0)} for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])]

    meta = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "episodesAsOf": time.strftime("%Y-%m-%d"),
        "coverBase": COVER,
        "source": "api.starry.wang",
        "counts": {"all": len(dramas), "new7": new7_n, "upd": upd_n, "finish": fin_n,
                   "dark": dark_n, "gift": len(gift_order), "novel": len(novels)},
        "dark": {"minAge": DARK_MIN_AGE, "maxAge": DARK_MAX_AGE, "topPct": int(DARK_TOP_PCT * 100),
                 "threshold": dark_thr},
        "updWindow": UPD_WINDOW,
        "giftOrder": gift_order,
    }
    payload = {"meta": meta, "dramas": dramas, "categories": categories,
               "novels": novels, "novelTags": novel_tags}

    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    tpl = open(TPL, encoding="utf-8").read()
    if "__DATA_JSON__" not in tpl:
        print("[!] 模板缺少 __DATA_JSON__ 占位")
        sys.exit(1)
    open(OUT, "w", encoding="utf-8").write(tpl.replace("__DATA_JSON__", js))

    # 同时输出独立的 data.json —— 服务器部署时页面会自动拉它做实时更新
    json_out = os.path.join(os.path.dirname(OUT), "data.json")
    open(json_out, "w", encoding="utf-8").write(js)

    print(f"\n[=] 已生成 {OUT}")
    print(f"    热门 {meta['counts']['all']} · 新剧(7天) {new7_n} · 更新 {upd_n} · 完结 {fin_n} · 黑马 {dark_n} · 礼物 {len(gift_order)} · 书城 {len(novels)}")
    print(f"    黑马阈值 hotScore≥{dark_thr:,}，年龄 {DARK_MIN_AGE}-{DARK_MAX_AGE} 天；小说标签 {len(novel_tags)} 个")
    print(f"    文件 {os.path.getsize(OUT)/1024:.0f} KB（内嵌 JSON {len(js.encode())/1024:.0f} KB）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-episodes", action="store_true", help="复用 episodes.json 缓存")
    ap.add_argument("--refresh", action="store_true", help="详情也全部重抓")
    build(ap.parse_args())
