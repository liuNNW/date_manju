# -*- coding: utf-8 -*-
"""
HiTwo 短剧榜 · 服务器模式（单命令启动）
======================================
一条命令搞定「定时抓数据 + 静态托管 + 同源 data.json」：

    python serve.py                 # 默认 8080 端口，每 10 分钟刷新一次数据
    python serve.py --port 80       # 换端口
    python serve.py --interval 300  # 5 分钟刷新一次
    python serve.py --no-refresh    # 只做静态托管，不自动刷新

页面会自动 fetch 同源的 data.json：
  - 数据一变就重渲染（保留当前分类 / 筛选 / 滚动位置）
  - 顶部小圆点变呼吸灯，表示"在线同步中"
  - 相对时间（"3 分钟前"）每分钟自动刷新

零第三方依赖，Python 3.9+ 标准库即可。生产环境想用 nginx 托管静态文件也可以，
只要把 data.json 设成 no-store，再配个 cron 跑 build_rank_page.py。
"""
import argparse
import os
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))


def refresh_loop(interval, no_episodes):
    """后台线程：定时重建数据"""
    import build_rank_page as B
    while True:
        t0 = time.time()
        try:
            B.build(argparse.Namespace(no_episodes=no_episodes, refresh=False))
            print(f"[refresh] ok  {time.strftime('%H:%M:%S')}  ({time.time()-t0:.1f}s)", flush=True)
        except Exception as e:
            print(f"[refresh] FAILED: {type(e).__name__}: {e}", flush=True)
        time.sleep(max(30, interval))


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        path = self.path.split('?')[0]
        if path.endswith('data.json'):
            self.send_header('Cache-Control', 'no-store, must-revalidate')
            self.send_header('Access-Control-Allow-Origin', '*')
        elif path.endswith('.html'):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 静音访问日志，避免刷屏


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--interval', type=int, default=600, help='数据刷新间隔（秒），默认 600')
    ap.add_argument('--no-refresh', action='store_true', help='不自动刷新，只做静态托管')
    ap.add_argument('--full', action='store_true', help='刷新时连分集数据一起重抓（慢，约 3 分钟）')
    a = ap.parse_args()

    os.chdir(HERE)

    # 首次启动：没有产物就先构建一次
    if not os.path.exists(os.path.join(HERE, 'data.json')):
        print('[init] 首次启动，正在抓取数据…', flush=True)
        import build_rank_page as B
        B.build(argparse.Namespace(no_episodes=not a.full, refresh=False))

    if not a.no_refresh:
        threading.Thread(target=refresh_loop, args=(a.interval, not a.full), daemon=True).start()

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print('=' * 52)
    print(f'  HiTwo 短剧榜已启动  http://{a.host}:{a.port}/')
    print(f'  数据刷新：' + ('关闭' if a.no_refresh else f'每 {a.interval} 秒（{"含分集" if a.full else "仅榜单"}）'))
    print(f'  页面：/短剧榜单.html   数据：/data.json')
    print('=' * 52, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n[exit] 已停止')


if __name__ == '__main__':
    main()
