# HiTwo 短剧榜

从 **HiTwo（com.starry.wang）** 短剧 App 逆向出来的榜单聚合服务。

抓 `api.starry.wang` 的公开接口，聚合成 5 个分类 + 3 个榜单 + 书城，输出一个响应式网页（手机/电脑通吃），支持服务端定时刷新。

---

## 目录

```
.
├── rank-server/            ★ 部署用（PM2 服务，零第三方依赖）
│   ├── server.js               抓取 + 聚合 + HTTP
│   ├── ecosystem.config.js     PM2 配置（PORT 6066）
│   ├── public/index.html       页面（49KB，无内嵌数据）
│   └── README.md               部署 / 反代 / 接口 / 排错
│
├── rank_template.html      页面模板（唯一真源，改完跑 make-frontend.js）
├── make-frontend.js        模板 → rank-server/public/index.html
├── build_rank_page.py      Python 版构建（生成单文件 HTML + data.json）
├── serve.py                Python 版服务（备用方案）
├── Dockerfile              容器化
│
├── 逆向分析报告.md          APK 逆向过程、接口清单、字段字典
├── 部署说明.md              三种部署方式（serve.py / nginx+cron / Docker）
│
└── 辅助脚本
    ├── fetch_hot.py         抓热播榜
    ├── enrich_hot.py        抓剧集详情
    ├── patch_details.py     补抓被限流的详情
    ├── fetch_episodes.py    抓全部分集
    ├── build_final.py       生成 Excel/CSV 报表
    ├── login_play.py        登录后换取播放地址（需验证码）
    ├── selftest.js          CDP 自动化体检
    └── shoot.js             CDP 截图
```

---

## 快速部署

```bash
git clone git@github.com:liuNNW/date_manju.git
cd date_manju/rank-server
pm2 start ecosystem.config.js
```

监听 `127.0.0.1:6066`，反代指向它即可。详见 [rank-server/README.md](rank-server/README.md)。

> 仓库不含 `data/` 缓存，首次启动会全量抓一次（含 700+ 部分集，约 3 分钟），期间 `/api/data` 返回 503、页面显示"服务端还在准备数据"。抓完自动正常。

---

## 数据能力

| 分类 | 数量 | 口径 |
|---|---|---|
| 热门 | ~723 部 | 按 `hotScore` 降序 |
| 新剧 | 全部 | 按上线时间倒序 |
| 更新 | ~474 部 | 近 7 天有新集上线 |
| 完结榜 | ~261 部 | `isSerializing=false`，按热度 |
| 黑马榜 | ~96 部 | 上架 7–45 天 且 热度前 20%，按日均热度 |
| 礼物榜 | 20 部 | 官方礼物榜顺序 |
| 书城 | 59 本 | 推荐=热度 / 最新=上架时间 / 24 个标签筛选 |

每张卡片都带封面、剧名、热度；详情抽屉含集数、免费集、出品方、解锁方式、简介。

---

## 已知边界

- 接口**未开放 CORS**（带 `Origin` 头直接 500），所以浏览器不能直连，必须走服务端聚合
- 播放地址（m3u8）需登录态换 `/api/video/play-auth/{episodeId}`，本项目不涉及
- 热度分数是服务端低频重算（实测 41 分钟不变），60 秒轮询足够
