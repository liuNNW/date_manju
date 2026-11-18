# -*- coding: utf-8 -*-
"""
播放地址获取 + 视频下载器
=========================
链路：play-auth 换签名地址(10 分钟过期) → 拉 m3u8 → 下载 ts 分片 → 合并 mp4

关键约束：
  - 播放地址 expireSeconds=600，必须「取一条立刻下一条」，不能提前批量导清单
  - 免费集（episodeNumber <= freeEpisodeCount 或 price=0）登录即可拿
  - 付费集服务端会拦（canWatch=false, reason=需要付费解锁），需先解锁才有地址

用法：
  python grab.py --drama 260 --list                 # 只看该剧可拿/被拦的集
  python grab.py --drama 260 --ep 1 --out dl        # 下载第 1 集
  python grab.py --drama 260 --all-free --out dl    # 下载该剧全部免费集
  python grab.py --episode-id 8737 --out dl         # 直接按集 ID 下
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.starry.wang/api"
UA = "okhttp/4.12.0"
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, "token.json")


def token():
    if not os.path.exists(TOKEN_FILE):
        sys.exit("[!] 缺 token.json，先跑 verify_paywall.py 登录")
    return json.load(open(TOKEN_FILE, encoding="utf-8"))["accessToken"]


def api(path, tok, timeout=25):
    r = urllib.request.Request(BASE + path, headers={
        "User-Agent": UA, "Authorization": "Bearer " + tok, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            return x.status, json.loads(x.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return -1, {"err": str(e)}


def http_get(url, timeout=40):
    r = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(r, timeout=timeout) as x:
        return x.read()


def play_info(tok, episode_id):
    """返回 (可播放, 地址, 原因, 各清晰度)"""
    st, r = api(f"/video/play-auth/{episode_id}", tok)
    d = (r.get("data") or {}) if isinstance(r, dict) else {}
    url = d.get("playUrl")
    if url:
        return True, url, "", d.get("qualities") or []
    reason = ((d.get("canWatchResult") or {}).get("reason")
              or d.get("reason") or r.get("message") or "未知")
    return False, None, reason, []


def pick_quality(qualities, prefer="hd"):
    """从 qualities 里挑指定清晰度，没有就用主地址"""
    for q in qualities:
        if q.get("definition") == prefer and q.get("url"):
            return q["url"]
    return None


def download_episode(tok, episode_id, out_dir, name, prefer="hd", keep_ts=False):
    ok, url, reason, quals = play_info(tok, episode_id)
    if not ok:
        print(f"  [跳过] ep{episode_id} 不可播放：{reason}")
        return None

    qurl = pick_quality(quals, prefer) or url
    print(f"  m3u8: {qurl[:96]}...")

    # 1) 拉 m3u8
    try:
        m3u8 = http_get(qurl).decode("utf-8", "replace")
    except Exception as e:
        print(f"  [失败] m3u8 拉取：{e}")
        return None
    if "#EXTM3U" not in m3u8:
        print("  [失败] 不是合法 m3u8")
        return None

    # 2) master playlist → 取子列表
    if "#EXT-X-STREAM-INF" in m3u8:
        subs = re.findall(r"#EXT-X-STREAM-INF[^\n]*\n(\S+)", m3u8)
        if subs:
            sub = subs[0]
            base = qurl.rsplit("/", 1)[0] + "/"
            qurl = sub if sub.startswith("http") else base + sub
            m3u8 = http_get(qurl).decode("utf-8", "replace")

    segs = [s for s in re.findall(r"^(?!#)(\S+)$", m3u8, re.M) if s.strip()]
    if not segs:
        print("  [失败] m3u8 里没有分片")
        return None

    base = qurl.rsplit("/", 1)[0] + "/"
    full = [s if s.startswith("http") else base + s for s in segs]
    print(f"  分片 {len(full)} 个，开始下载…")

    os.makedirs(out_dir, exist_ok=True)
    ts_path = os.path.join(out_dir, name + ".ts")
    done = 0
    t0 = time.time()
    with open(ts_path, "wb") as f:
        for i, s in enumerate(full, 1):
            for attempt in range(3):
                try:
                    f.write(http_get(s))
                    done += 1
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"  [警告] 分片 {i} 失败：{e}")
                    time.sleep(0.6)
            if i % 20 == 0 or i == len(full):
                sp = os.path.getsize(ts_path) / 1048576
                print(f"    {i}/{len(full)} 段 · {sp:.1f} MB · {time.time()-t0:.0f}s")

    # 3) 合并成 mp4
    mp4 = os.path.join(out_dir, name + ".mp4")
    ff = shutil.which("ffmpeg")
    if ff:
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", ts_path,
                            "-c", "copy", "-bsf:a", "aac_adtstoasc", mp4],
                           capture_output=True)
        if r.returncode == 0 and os.path.exists(mp4):
            print(f"  [OK] {mp4}  {os.path.getsize(mp4)/1048576:.1f} MB")
            if not keep_ts:
                os.remove(ts_path)
            return mp4
        print(f"  [警告] ffmpeg 合并失败，保留 ts：{ts_path}")
    else:
        print(f"  [提示] 没装 ffmpeg，保留 ts：{ts_path}（播放器/.ts 可直接播）")
    return ts_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drama", type=int)
    ap.add_argument("--episode-id", type=int)
    ap.add_argument("--ep", type=int, help="集号（第几集）")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all-free", action="store_true")
    ap.add_argument("--out", default="dl")
    ap.add_argument("--quality", default="hd", choices=["sd", "hd"])
    ap.add_argument("--keep-ts", action="store_true")
    a = ap.parse_args()

    tok = token()

    if a.episode_id:
        download_episode(tok, a.episode_id, a.out, f"ep{a.episode_id}", a.quality, a.keep_ts)
        return

    if not a.drama:
        sys.exit("需要 --drama 或 --episode-id")

    st, r = api(f"/episodes/drama/{a.drama}", tok)
    eps = sorted(r.get("data") or [], key=lambda e: e.get("episodeNumber") or 0)
    if not eps:
        sys.exit(f"剧 {a.drama} 没有分集")
    st, rd = api(f"/dramas/{a.drama}", tok)
    d = rd.get("data") or {}
    fn = d.get("freeEpisodeCount") or 0
    print(f"剧 {a.drama}「{d.get('title')}」 mode={d.get('mode')} "
          f"免费前 {fn} 集 / 共 {len(eps)} 集 / 整部 {d.get('wholePrice')} 豆")

    if a.list:
        print(f"\n{'集号':>4} {'price':>5} {'判定':>6}  说明")
        for e in eps:
            n = e.get("episodeNumber") or 0
            free = (e.get("price") or 0) == 0 or (fn and n <= fn)
            print(f"{n:>4} {e.get('price') or 0:>5} {'免费' if free else '付费':>6}  "
                  f"{'免费集范围内' if fn and n<=fn else ('price=0' if (e.get('price') or 0)==0 else '需解锁')}")
        return

    targets = []
    if a.ep:
        targets = [e for e in eps if (e.get("episodeNumber") or 0) == a.ep]
    elif a.all_free:
        targets = [e for e in eps if (e.get("price") or 0) == 0 or (fn and (e.get("episodeNumber") or 0) <= fn)]
    if not targets:
        sys.exit("没有匹配的集（用 --list 看哪些能下）")

    print(f"\n待下载 {len(targets)} 集")
    okc = 0
    for idx, e in enumerate(targets, 1):
        n = e.get("episodeNumber") or 0
        print(f"\n[{idx}/{len(targets)}] 第{n}集 ep{e['id']}")
        res = download_episode(tok, e["id"], a.out,
                              f"{a.drama}_ep{n:03d}", a.quality, a.keep_ts)
        if res:
            okc += 1
        time.sleep(0.5)
    print(f"\n完成：{okc}/{len(targets)} 集 -> {os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
