# -*- coding: utf-8 -*-
"""
HiTwo（com.starry.wang）播放地址获取工具
=======================================
视频 CDN (vod.starry.wang) 带腾讯云鉴权，裸链返回 403 "need sign info"，
播放地址只能通过登录态调用 GET /api/video/play-auth/{episodeId} 换取。

用法
----
1) 发验证码（二选一）
   python login_play.py --send-sms 13800138000
   python login_play.py --send-email you@qq.com          # 仅 qq/163/outlook 等主流邮箱

2) 用验证码注册/登录，拿到 token（自动存 token.json）
   python login_play.py --phone 13800138000 --code 123456
   python login_play.py --email you@qq.com --code 123456

3) 换取播放地址
   python login_play.py --drama 260                 # 单部剧全部集
   python login_play.py --all                       # 全部 708 部 / 22176 集（耗时较长）
   python login_play.py --all --workers 3           # 控制并发，默认 3

4) 仅用已有 token
   python login_play.py --token <access_token> --drama 260

产出：play_urls.json / play_urls.csv
"""
import argparse, csv, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://api.starry.wang/api"
OUT = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(OUT, "token.json")
UA = "okhttp/4.12.0"


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
            return e.code, {"raw": raw[:400]}
    except Exception as e:
        return -1, {"error": f"{type(e).__name__}: {e}"}


def find_urls(obj, acc=None):
    """递归收集响应中所有 http(s) 资源地址"""
    if acc is None:
        acc = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            find_urls(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            find_urls(v, acc)
    elif isinstance(obj, str):
        if obj.startswith("http://") or obj.startswith("https://"):
            if obj not in acc:
                acc.append(obj)
    return acc


def save_token(tok):
    json.dump(tok, open(TOKEN_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[=] token 已保存到 {TOKEN_FILE}")


def load_token():
    if os.path.exists(TOKEN_FILE):
        try:
            return json.load(open(TOKEN_FILE, encoding="utf-8")).get("accessToken")
        except Exception:
            pass
    return None


def do_auth(args):
    if args.send_sms:
        code, r = req("POST", "/auth/sms-code", {"phone": args.send_sms})
        print(f"[sms-code] {code} {r}")
        return None
    if args.send_email:
        code, r = req("POST", "/auth/email/code", {"email": args.send_email})
        print(f"[email-code] {code} {r}")
        return None

    if args.token:
        save_token({"accessToken": args.token})
        return args.token

    if not args.code:
        return load_token()

    # 先试登录，失败再注册
    if args.phone:
        ident = {"phone": args.phone}
        login_path, reg_path = "/auth/login", "/auth/register"
    elif args.email:
        ident = {"email": args.email}
        login_path, reg_path = "/auth/login", "/auth/email/register"
    else:
        print("[!] 需要 --phone 或 --email")
        return None

    body = dict(ident, code=args.code)
    if args.password:
        body["password"] = args.password

    code_, r = req("POST", login_path, body)
    print(f"[login] {code_} {r.get('message') or r}")
    if code_ == 200 and isinstance(r.get("data"), dict) and r["data"].get("accessToken"):
        save_token(r["data"])
        return r["data"]["accessToken"]

    if not body.get("password"):
        body["password"] = "Aa123456"
    code_, r = req("POST", reg_path, body)
    print(f"[register] {code_} {r.get('message') or r}")
    if code_ in (200, 201) and isinstance(r.get("data"), dict):
        d = r["data"]
        tok = d.get("accessToken") or (d.get("tokens") or {}).get("accessToken")
        if tok:
            save_token(d)
            return tok
        # 注册成功但未返回 token，改走登录
        code_, r2 = req("POST", login_path, {"account": ident.get("phone") or ident.get("email"),
                                             "password": body["password"], **ident})
        print(f"[login2] {code_} {r2.get('message')}")
        if isinstance(r2.get("data"), dict) and r2["data"].get("accessToken"):
            save_token(r2["data"])
            return r2["data"]["accessToken"]
    return None


def episodes_of(drama_id, token):
    code, r = req("GET", f"/episodes/drama/{drama_id}", token=token)
    if code == 200 and isinstance(r.get("data"), list):
        return r["data"]
    return []


def play_auth(ep, token):
    code, r = req("GET", f"/video/play-auth/{ep['id']}", token=token)
    urls = find_urls(r) if code == 200 else []
    return {
        "episodeId": ep["id"],
        "dramaId": ep.get("dramaId"),
        "episodeNumber": ep.get("episodeNumber"),
        "price": ep.get("price"),
        "httpStatus": code,
        "code": r.get("code") if isinstance(r, dict) else None,
        "message": r.get("message") if isinstance(r, dict) else None,
        "urls": urls,
        "playUrl": next((u for u in urls if ".m3u8" in u), urls[0] if urls else None),
        "raw": r.get("data") if isinstance(r, dict) else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send-sms")
    ap.add_argument("--send-email")
    ap.add_argument("--phone")
    ap.add_argument("--email")
    ap.add_argument("--code")
    ap.add_argument("--password", default="Aa123456")
    ap.add_argument("--token")
    ap.add_argument("--drama", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    token = do_auth(args)
    if not token:
        print("\n[!] 尚未取得 token。先发码再带 --code 运行，或直接 --token 传入已有 accessToken。")
        return

    if args.drama:
        targets = episodes_of(args.drama, token)
        print(f"[i] drama {args.drama}: {len(targets)} 集")
    elif args.all:
        hot = json.load(open(os.path.join(OUT, "hot_dramas.json"), encoding="utf-8"))
        targets = []
        for h in hot:
            targets.extend(episodes_of(h["id"], token))
            time.sleep(0.2)
        print(f"[i] 全站 {len(targets)} 集")
    else:
        # 单集自检
        code, r = req("GET", "/video/play-auth/8737", token=token)
        print("[self-test]", code, json.dumps(r, ensure_ascii=False)[:600])
        return

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(play_auth, ep, token) for ep in targets]
        for i, fu in enumerate(as_completed(futs), 1):
            results.append(fu.result())
            if i % 20 == 0:
                ok = sum(1 for x in results if x["playUrl"])
                print(f"[+] {i}/{len(targets)} 命中播放地址 {ok}")

    results.sort(key=lambda x: (x["dramaId"] or 0, x["episodeNumber"] or 0))
    json.dump(results, open(os.path.join(OUT, "play_urls.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, "play_urls.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["dramaId", "episodeId", "episodeNumber", "price",
                                          "httpStatus", "code", "message", "playUrl"])
        w.writeheader()
        for x in results:
            w.writerow({k: x.get(k) for k in w.fieldnames})
    ok = sum(1 for x in results if x["playUrl"])
    print(f"[=] 完成：{len(results)} 集，命中 {ok} 条播放地址 → play_urls.json / play_urls.csv")


if __name__ == "__main__":
    main()
