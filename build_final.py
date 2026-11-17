# -*- coding: utf-8 -*-
"""生成最终交付：热播剧主表 + 分集明细 + 统计汇总 + 逆向接口清单"""
import json, os, csv
import pandas as pd
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment, PatternFill

OUT = os.path.dirname(os.path.abspath(__file__))
hot = json.load(open(os.path.join(OUT, "hot_dramas.json"), encoding="utf-8"))
det = {d["id"]: d for d in json.load(open(os.path.join(OUT, "hot_dramas_detail.json"), encoding="utf-8"))}
eps = {int(k): v for k, v in json.load(open(os.path.join(OUT, "episodes.json"), encoding="utf-8")).items()}

title_of = {h["id"]: h.get("title") for h in hot}
rank_of = {h["id"]: i for i, h in enumerate(hot, 1)}

# ---------- 分集维度聚合 ----------
agg = {}
for did, lst in eps.items():
    if not lst:
        continue
    views = sum(e.get("viewCount") or 0 for e in lst)
    likes = sum(e.get("likeCount") or 0 for e in lst)
    comments = sum(e.get("commentCount") or 0 for e in lst)
    durs = [e.get("duration") or 0 for e in lst if e.get("duration")]
    paid = sum(1 for e in lst if (e.get("price") or 0) > 0)
    agg[did] = {
        "eps_count": len(lst),
        "eps_views": views,
        "eps_likes": likes,
        "eps_comments": comments,
        "avg_duration": round(sum(durs) / len(durs), 1) if durs else None,
        "total_duration_min": round(sum(durs) / 60.0, 1),
        "paid_episodes": paid,
        "last_publish": max((e.get("createdAt") or "") for e in lst) or None,
    }

# ---------- Sheet1 主表 ----------
cols = ["rank", "id", "title", "seriesTitle", "seasonNo", "category", "tags",
        "maleRoles", "femaleRoles", "totalEpisodes", "eps_count", "freeEpisodeCount",
        "paid_episodes", "mode", "wholePrice", "batchDiscount", "avg_duration",
        "total_duration_min", "status", "isSerializing", "isNewDrama",
        "hotScore", "viewCount", "eps_views", "eps_likes", "eps_comments",
        "creatorId", "creatorName", "vodClassId", "seriesId",
        "createdAt", "last_publish", "coverUrl", "description"]
rows = []
for i, h in enumerate(hot, 1):
    d = det.get(h["id"], {})
    a = agg.get(h["id"], {})
    rows.append({
        "rank": i, "id": h["id"], "title": h.get("title"),
        "seriesTitle": d.get("seriesTitle"), "seasonNo": d.get("seasonNo"),
        "category": h.get("category"), "tags": "/".join(h.get("tags") or []),
        "maleRoles": d.get("maleRoles"), "femaleRoles": d.get("femaleRoles"),
        "totalEpisodes": h.get("totalEpisodes"), "eps_count": a.get("eps_count"),
        "freeEpisodeCount": d.get("freeEpisodeCount"), "paid_episodes": a.get("paid_episodes"),
        "mode": d.get("mode"), "wholePrice": d.get("wholePrice"),
        "batchDiscount": d.get("batchDiscount"), "avg_duration": a.get("avg_duration"),
        "total_duration_min": a.get("total_duration_min"),
        "status": h.get("status"), "isSerializing": h.get("isSerializing"),
        "isNewDrama": h.get("isNewDrama"), "hotScore": h.get("hotScore"),
        "viewCount": h.get("viewCount"), "eps_views": a.get("eps_views"),
        "eps_likes": a.get("eps_likes"), "eps_comments": a.get("eps_comments"),
        "creatorId": d.get("creatorId"), "creatorName": h.get("creatorName"),
        "vodClassId": d.get("vodClassId"), "seriesId": d.get("seriesId"),
        "createdAt": d.get("createdAt"), "last_publish": a.get("last_publish"),
        "coverUrl": h.get("coverUrl"),
        "description": (h.get("description") or "").replace("\n", " "),
    })
df_main = pd.DataFrame(rows, columns=cols)

# ---------- Sheet2 分集明细 ----------
ep_rows = []
for h in hot:
    did = h["id"]
    for e in eps.get(did, []):
        ep_rows.append({
            "drama_rank": rank_of[did], "dramaId": did, "drama_title": title_of[did],
            "episodeNumber": e.get("episodeNumber"), "episodeId": e.get("id"),
            "ep_title": e.get("title"), "type": e.get("type"),
            "duration_sec": e.get("duration"),
            "duration_min": round((e.get("duration") or 0) / 60.0, 2),
            "price": e.get("price"), "freeInWhole": e.get("freeInWhole"),
            "status": e.get("status"), "viewCount": e.get("viewCount"),
            "likeCount": e.get("likeCount"), "commentCount": e.get("commentCount"),
            "vodFileId": e.get("vodFileId"), "vodFileName": e.get("vodFileName"),
            "scheduledPublishAt": e.get("scheduledPublishAt"),
            "createdAt": e.get("createdAt"),
        })
df_eps = pd.DataFrame(ep_rows)

# ---------- 接口清单 ----------
api = [
    ["GET", "/api/dramas/hot", "热播剧列表（按 hotScore 降序，即全站剧按热度排）", "page, pageSize(<=100), category, tag", "否"],
    ["GET", "/api/dramas/latest", "最新上架列表", "page, pageSize", "否"],
    ["GET", "/api/dramas", "剧库列表（默认按创建时间倒序）", "page, pageSize, category, sort, order", "否"],
    ["GET", "/api/dramas/{id}", "剧集详情（价格/免费集数/演员角色/系列）", "路径参数 id", "否"],
    ["GET", "/api/episodes/drama/{dramaId}", "某剧全部单集（时长/价格/播放/点赞/评论/VOD文件ID）", "路径参数 dramaId", "否"],
    ["GET", "/api/categories", "分类/标签两级目录", "无", "否"],
    ["GET", "/api/banners", "轮播位", "position", "否"],
    ["GET", "/api/app/bootstrap", "首屏聚合（banner+推荐）", "无", "否"],
    ["GET", "/api/app/config", "App 全局配置（名称/域名池/公告/更新）", "无", "否"],
    ["GET", "/api/dramas/tags", "标签聚合", "-", "否（实测 404）"],
    ["GET", "/api/dramas/rankings/gift-creators", "打赏创作者榜", "limit", "否"],
    ["GET", "/api/search", "搜索", "keyword/q", "实测 404"],
    ["GET", "/api/player/context", "播放上下文", "episodeId", "是(401)"],
    ["GET", "/api/video/play-auth/{episodeId}", "播放鉴权（换播放地址）", "路径参数", "是(401)"],
    ["GET", "/api/user/profile", "用户信息", "无", "是"],
    ["POST", "/api/auth/login", "登录", "body", "是"],
    ["POST", "/api/auth/register", "注册", "body", "是"],
    ["GET", "/api/payment/packages", "充值档位", "无", "是"],
    ["GET", "/api/mall/products", "商城商品", "page, pageSize", "是"],
]
df_api = pd.DataFrame(api, columns=["方法", "路径", "说明", "主要参数", "需登录"])

# ---------- 统计汇总 ----------
tagcnt = {}
for h in hot:
    for t in (h.get("tags") or []):
        tagcnt[t] = tagcnt.get(t, 0) + 1
stat = [
    ["指标", "值"],
    ["热播剧总数", len(df_main)],
    ["分集总数", len(df_eps)],
    ["总集数（字段合计）", int(df_main["totalEpisodes"].fillna(0).sum())],
    ["列表播放量合计", int(df_main["viewCount"].fillna(0).sum())],
    ["分集播放量合计", int(df_eps["viewCount"].fillna(0).sum())],
    ["分集点赞合计", int(df_eps["likeCount"].fillna(0).sum())],
    ["分集评论合计", int(df_eps["commentCount"].fillna(0).sum())],
    ["总时长（分钟）", round(float(df_eps["duration_sec"].fillna(0).sum()) / 60, 1)],
    ["平均单集时长（秒）", round(float(df_eps["duration_sec"].mean()), 1)],
    ["连载中", int((df_main["isSerializing"] == True).sum())],
    ["已完结", int((df_main["isSerializing"] == False).sum())],
    ["新剧标记", int((df_main["isNewDrama"] == True).sum())],
    ["付费模式 WHOLE(整部)", int((df_main["mode"] == "WHOLE").sum())],
    ["付费模式 PER_EPISODE(单集)", int((df_main["mode"] == "PER_EPISODE").sum())],
    [], ["分类", "剧数"],
]
for k, v in df_main["category"].value_counts().items():
    stat.append([k, int(v)])
stat += [[], ["标签", "剧数"]]
for k, v in sorted(tagcnt.items(), key=lambda kv: -kv[1])[:40]:
    stat.append([k, v])
stat += [[], ["创作者", "上榜剧数"]]
for k, v in df_main["creatorName"].value_counts().head(40).items():
    stat.append([k, int(v)])
df_stat = pd.DataFrame(stat)

xlsx = os.path.join(OUT, "热播剧数据.xlsx")
head_fill = PatternFill("solid", fgColor="1F4E79")
with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
    df_main.to_excel(xw, index=False, sheet_name="热播剧总表")
    df_eps.to_excel(xw, index=False, sheet_name="分集明细")
    df_stat.to_excel(xw, index=False, sheet_name="统计汇总", header=False)
    df_api.to_excel(xw, index=False, sheet_name="接口清单")

    def style(ws, widths, freeze="B2", filt=True):
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF"); c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
        for idx, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(idx)].width = w
        ws.freeze_panes = freeze
        if filt:
            ws.auto_filter.ref = ws.dimensions

    style(xw.sheets["热播剧总表"], [6, 6, 30, 26, 7, 8, 26, 20, 20, 8, 8, 10, 8, 12, 9, 9, 9, 10, 8, 9, 8, 11, 10, 10, 9, 10, 9, 16, 10, 9, 20, 20, 40, 60])
    style(xw.sheets["分集明细"], [9, 8, 30, 8, 9, 24, 7, 8, 8, 7, 8, 8, 10, 8, 10, 18, 34, 18, 20])
    style(xw.sheets["接口清单"], [7, 42, 46, 34, 10])
    ws3 = xw.sheets["统计汇总"]
    ws3.column_dimensions["A"].width = 32
    ws3.column_dimensions["B"].width = 16
    for r in ws3.iter_rows():
        for c in r:
            if isinstance(c.value, str) and c.column == 1 and c.value in ("指标", "分类", "标签", "创作者"):
                c.font = Font(bold=True, color="FFFFFF"); c.fill = head_fill

# CSV 备份
df_main.to_csv(os.path.join(OUT, "热播剧总表.csv"), index=False, encoding="utf-8-sig")
df_eps.to_csv(os.path.join(OUT, "分集明细.csv"), index=False, encoding="utf-8-sig")

print(f"[=] {xlsx}")
print(f"    热播剧总表: {len(df_main)} 行 x {len(df_main.columns)} 列")
print(f"    分集明细:   {len(df_eps)} 行")
print(f"    分集播放量合计: {int(df_eps['viewCount'].fillna(0).sum()):,}")
print(f"    总时长: {round(float(df_eps['duration_sec'].fillna(0).sum())/60/60,1)} 小时")
print("\n=== TOP 20 ===")
for r in rows[:20]:
    print(f"{r['rank']:>3}. {r['title'][:24]:<26} {str(r['category'])[:4]:<5} {str(r['totalEpisodes']):>3}集 "
          f"免费{str(r['freeEpisodeCount']):>2} 热度{r['hotScore']:>12,.0f} 播放{r['viewCount'] or 0:>8,} {r['creatorName']}")
