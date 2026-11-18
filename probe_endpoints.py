# -*- coding: utf-8 -*-
"""
接口穷举：把 AOT 里提取到的全部 API 路径，无 token 挨个打一遍
目的：找出「不需要登录就能拿到内容」的端点，尤其是播放地址相关
"""
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.starry.wang/api"
UA = "okhttp/4.12.0"


def load_paths():
    out = []
    for line in open("libapp_strings.txt", encoding="utf-8", errors="ignore"):
        p = line.strip()
        if not re.match(r"^/[a-zA-Z][a-zA-Z0-9\-/_{}]*$", p):
            continue
        if "{" in p or p.endswith("/"):
            continue          # 需要参数或尾斜杠的跳过
        out.append(p)
    # 补几个常见变体
    out += ["/app/bootstrap", "/app/config", "/banners", "/novel-banners", "/novel-tags", "/categories"]
    return sorted(set(out))


def probe(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(1200).decode("utf-8", "replace")
            return (r.status, path, round(time.time() - t0, 2), body[:200])
    except urllib.error.HTTPError as e:
        body = e.read(300).decode("utf-8", "replace")
        return (e.code, path, round(time.time() - t0, 2), body[:160])
    except Exception as e:
        return (-1, path, round(time.time() - t0, 2), f"{type(e).__name__}")


def main():
    paths = load_paths()
    print(f"待测路径: {len(paths)}\n")

    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, r in enumerate(ex.map(probe, paths), 1):
            results.append(r)
            time.sleep(0.05)
            if i % 40 == 0:
                print(f"  ... {i}/{len(paths)}")

    ok = [r for r in results if r[0] == 200]
    other = [r for r in results if r[0] != 200]

    print("\n" + "=" * 60)
    print(f"[OK] 免登录可访问 (200)：{len(ok)} 个")
    print("=" * 60)
    for st, path, dt, body in ok:
        print(f"  {path:<38} {dt}s")
        print(f"     {body[:150]}")

    print("\n" + "=" * 60)
    print("状态分布：")
    from collections import Counter
    for code, n in Counter(r[0] for r in results).most_common():
        print(f"  {code}: {n}")

    print("\n=== 播放相关路径的详细结果 ===")
    for st, path, dt, body in results:
        if re.search(r"(?i)(video|play|player|stream)", path):
            print(f"  {path:<32} -> {st}  {body[:110]}")

    json.dump([{"status": s, "path": p, "sec": d, "body": b} for s, p, d, b in results],
              open("endpoint_scan.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n[=] 明细 endpoint_scan.json")


if __name__ == "__main__":
    main()
