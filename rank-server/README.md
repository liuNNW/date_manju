# HiTwo 短剧榜 · PM2 服务

节点服务，负责**定时抓数据 + 聚合 + 出页面**。反代你自己配，它只监听 `127.0.0.1:6066`。

零第三方依赖（不用 `npm install` 装任何包），只要 Node ≥ 16。

---

## 目录

```
rank-server/
├── server.js              # 主服务（抓取 + 聚合 + HTTP）
├── ecosystem.config.js    # PM2 配置
├── package.json
├── public/
│   └── index.html         # 页面（不含数据，启动时拉 /api/data）
├── data/                  # 运行时缓存（可删，删了首次启动会重抓）
│   ├── payload.json       # 聚合结果，重启秒开
│   ├── detail-cache.json  # 剧集详情缓存
│   └── eps-cache.json     # 分集缓存（"更新"榜用）
└── logs/                  # PM2 日志
```

---

## 部署

```bash
# 1. 上传整个 rank-server 目录到服务器
scp -r rank-server user@host:/opt/

# 2. 进目录启动
cd /opt/rank-server
pm2 start ecosystem.config.js

# 3. 看状态
pm2 status
pm2 logs hitwo-rank --lines 50

# 4. 开机自启
pm2 save
pm2 startup        # 按提示复制执行它输出的那行命令
```

启动日志长这样：

```
[12:08:39] 载入缓存: 712 部 / 59 本 · 2026-11-17T18:39:55
[12:08:39] 监听 http://127.0.0.1:6066  （反代请指向这里）
[12:08:41] 榜单: total=714 去重后=714
[12:08:42] 刷新完成 (轻量) · 714 部 / 59 本 · 2815ms · gzip 160KB
```

> 目录里带了 `data/` 缓存，所以**启动即秒开**。如果删掉 `data/`，首次启动会全量抓一次（含 700+ 部分集，约 3 分钟），期间 `/api/data` 返回 503，页面会显示"服务端还在准备数据"。

---

## 反代

服务只监听回环地址 `127.0.0.1:6066`，公网入口交给你自己的反代。两种常见写法：

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name rank.example.com;

    # 证书省略…

    location / {
        proxy_pass http://127.0.0.1:6066;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    # 数据接口别缓存，否则页面永远看到旧的
    location = /api/data {
        proxy_pass http://127.0.0.1:6066;
        proxy_set_header Host $host;
        add_header Cache-Control "no-store" always;
        proxy_buffering off;
    }

    location = /api/version {
        proxy_pass http://127.0.0.1:6066;
        proxy_set_header Host $host;
        add_header Cache-Control "no-store" always;
    }

    # 健康检查可以放开给监控
    location = /api/health {
        proxy_pass http://127.0.0.1:6066;
        proxy_set_header Host $host;
        access_log off;
    }
}
```

### Caddy

```caddy
rank.example.com {
    reverse_proxy 127.0.0.1:6066
    @nocache path /api/data /api/version
    header @nocache Cache-Control "no-store"
}
```

### 宝塔 / 1Panel

新建站点 → 反代到 `http://127.0.0.1:6066` → 在「配置文件」里给 `/api/data` 单独加 `add_header Cache-Control "no-store" always;`。

> 如果前面还套了 Cloudflare：记得对 `/api/data`、`/api/version` 设 bypass cache，或者直接用「开发模式」。

---

## 接口

| 端点 | 说明 |
|---|---|
| `GET /` | 页面 |
| `GET /api/data` | 全量数据（gzip ≈160KB，带 ETag，支持 `If-None-Match` 返回 304） |
| `GET /api/version` | 版本探测，几十字节：`{ready, generatedAt, counts}`，页面轮询用这个 |
| `GET /api/health` | 健康检查：运行时长、数据量、上次刷新时间、内存占用、最近错误 |
| `POST /api/refresh` | 手动触发刷新，`?heavy=1` 连分集一起重抓 |

设置 `ADMIN_TOKEN` 后，`/api/refresh` 需要请求头 `x-admin-token: <token>`：

```bash
curl -X POST -H "x-admin-token: your-token" "http://127.0.0.1:6066/api/refresh"
```

---

## 刷新策略（两档）

| 档位 | 默认间隔 | 抓什么 | 耗时 |
|---|---|---|---|
| 轻量 | **5 分钟**（`REFRESH_LIGHT`） | 8 页榜单 + 详情增量 + 20 条礼物榜 + 59 本小说 | 约 3 秒 |
| 重量 | **6 小时**（`REFRESH_HEAVY`） | 额外抓 700+ 部的分集（"更新"榜的命脉） | 约 2-3 分钟 |

页面每 60 秒打一次 `/api/version`（几十字节），版本变了才去拉 `/api/data` 并重渲染，**保留你当前的分类、筛选、搜索**。可以用 `?poll=15000` 改成 15 秒。

> 别把 `REFRESH_LIGHT` 调到 60 秒以下——一次轻量刷新要打十几个请求，太频繁会被对方 429 限流（服务里有退避重试，但没必要）。

---

## 环境变量

在 `ecosystem.config.js` 的 `env` 里改，或 `pm2 restart hitwo-rank --update-env` 前 export。

| 变量 | 默认 | 说明 |
|---|---|---|
| `PORT` | `6066` | 监听端口 |
| `HOST` | `127.0.0.1` | 监听地址，反代场景别改成 0.0.0.0 |
| `REFRESH_LIGHT` | `300` | 轻量刷新间隔（秒） |
| `REFRESH_HEAVY` | `21600` | 含分集的刷新间隔（秒） |
| `ADMIN_TOKEN` | 空 | 非空时 `/api/refresh` 需鉴权 |
| `TZ` | `Asia/Shanghai` | 时区（影响日志和生成时间） |

---

## 数据来源与口径

全部来自 `api.starry.wang` 公开接口，游客可读，不需要登录：

| 分类 | 数据源 | 口径 |
|---|---|---|
| 热门 | `/dramas/hot` | 按 `hotScore` 降序 |
| 新剧 | 同上 | 按 `createdAt` 降序 |
| 更新 | `/episodes/drama/{id}` 的分集 `createdAt` | 近 7 天有新集上线，按最后更新时间排 |
| 完结榜 | 本地筛 `isSerializing=false` | 按热度排（服务端的 `status` 参数是摆设，实测被忽略） |
| 黑马榜 | 本地算 | 上架 7–45 天 **且** 热度进全站前 20%，按日均热度排序 |
| 礼物榜 | `/dramas/rankings/gifts` | 服务端顺序（固定 20 条） |
| 书城 | `/novels` | 推荐=热度 / 最新=上架时间 / 筛选=24 个官方标签 |

---

## 排错

| 现象 | 原因与处理 |
|---|---|
| `/api/data` 返回 503 | 首次全量抓取还没完成。`pm2 logs` 看进度，等 3 分钟 |
| 页面一直显示"连接失败" | 反代没通，或 `/api/data` 路径被改。直接 `curl 127.0.0.1:6066/api/health` 验证服务本身 |
| 页面数据不自动更新 | 反代把 `/api/data` 缓存了，见上面 no-store 配置；或浏览器 F12 看 `/api/version` 是否 200 |
| `pm2 logs` 里大量 429 | 对方限流，把 `REFRESH_LIGHT` 调大（如 600） |
| 内存涨到 300M+ | `max_memory_restart: '400M'` 会自动重启；`eps-cache.json` 约 10MB 属正常 |
| 重启后要等 3 分钟 | 说明 `data/` 被删了。留着它，重启就是秒开 |
| 改了 `index.html` 不生效 | 页面 `Cache-Control: no-cache`，强刷即可；或在反代里加 `proxy_no_cache` |

### 从模板重新生成页面

`public/index.html` 是从根目录的 `rank_template.html` 转出来的（去掉内嵌数据，改成拉 API）。改了模板后：

```bash
node make-frontend.js          # 在项目根目录跑
pm2 restart hitwo-rank         # 静态文件，其实不用重启也能生效
```

---

## 常用命令

```bash
pm2 status                    # 状态
pm2 logs hitwo-rank           # 实时日志
pm2 logs hitwo-rank --lines 200 --nostream
pm2 restart hitwo-rank        # 重启
pm2 reload hitwo-rank         # 平滑重载
pm2 stop hitwo-rank
pm2 delete hitwo-rank
pm2 monit                     # 资源监控
pm2 describe hitwo-rank       # 详细配置
```

> **换端口 / 改环境变量后要 `delete` 再 `start`**：`pm2 restart` 默认不重读 `ecosystem.config.js` 里的 `env`（除非加 `--update-env`）。所以改端口应该是：
>
> ```bash
> pm2 delete hitwo-rank && pm2 start ecosystem.config.js
> # 或者
> pm2 restart hitwo-rank --update-env
> ```

### 确认端口是否真的生效

```bash
ss -lntp | grep 6066          # 看有没有监听
curl 127.0.0.1:6066/api/health
pm2 describe hitwo-rank | grep -A2 "PORT"
```
