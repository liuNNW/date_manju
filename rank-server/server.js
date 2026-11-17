/**
 * 短剧热播榜 · 服务端（PM2 管理，零第三方依赖）
 * ================================================
 * 职责：
 *   1. 定时抓取 api.starry.wang 的榜单 / 剧集 / 分集 / 小说 / 礼物榜数据
 *   2. 内存聚合（热门 / 新剧 / 更新 / 完结榜 / 黑马榜 / 礼物榜 / 书城）
 *   3. 对外提供：页面、/api/data、/api/version、/api/health
 *
 * 刷新策略（两档，避免把对方接口打挂）：
 *   - 轻量：每 5 分钟（8 页榜单 + 详情增量 + 20 条礼物榜 + 59 本小说，约 2-3 秒）
 *   - 重量：每 6 小时（额外抓 700+ 部的分集，约 2-3 分钟），"更新"榜靠它保准
 *
 * 启动即可用：有 data/payload.json 就秒开，没有就先抓一次。
 *
 * 环境变量：
 *   PORT            监听端口，默认 6066
 *   HOST            监听地址，默认 127.0.0.1（反代场景建议保持本机回环）
 *   REFRESH_LIGHT   轻量刷新间隔秒，默认 300
 *   REFRESH_HEAVY   重量刷新间隔秒，默认 21600
 *   ADMIN_TOKEN     设置后 /api/refresh 需要请求头 x-admin-token
 */
'use strict';

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { URL } = require('url');

const ROOT = __dirname;
const DATA_DIR = path.join(ROOT, 'data');
const PUBLIC_DIR = path.join(ROOT, 'public');

const PORT = parseInt(process.env.PORT || '6066', 10);
const HOST = process.env.HOST || '127.0.0.1';
const REFRESH_LIGHT = parseInt(process.env.REFRESH_LIGHT || '300', 10) * 1000;
const REFRESH_HEAVY = parseInt(process.env.REFRESH_HEAVY || '21600', 10) * 1000;
const ADMIN_TOKEN = process.env.ADMIN_TOKEN || '';

const API_BASE = 'https://api.starry.wang/api';
const COVER_BASE = 'https://vod.starry.wang/covers/';
const UA = 'okhttp/4.12.0';

// 黑马榜口径
const DARK_MIN_AGE = 7;
const DARK_MAX_AGE = 45;
const DARK_TOP_PCT = 0.20;
// 更新榜窗口
const UPD_WINDOW = 7;

const F = {
  payload: path.join(DATA_DIR, 'payload.json'),
  detail: path.join(DATA_DIR, 'detail-cache.json'),
  eps: path.join(DATA_DIR, 'eps-cache.json'),
};

const log = (...a) => console.log(`[${new Date().toISOString().slice(11, 19)}]`, ...a);
const warn = (...a) => console.warn(`[${new Date().toISOString().slice(11, 19)}]`, ...a);

/* ------------------------------------------------------------------ */
/* 运行期状态                                                          */
/* ------------------------------------------------------------------ */
const S = {
  payload: null,          // 对外 payload
  payloadRaw: null,       // JSON 字符串
  payloadGzip: null,      // gzip 后的 Buffer
  etag: '',
  detailCache: {},        // id -> 详情
  epsCache: {},           // id -> 分集数组
  lastLight: 0,
  lastHeavy: 0,
  lastError: null,
  refreshing: false,
  startedAt: Date.now(),
};

/* ------------------------------------------------------------------ */
/* 基础工具                                                            */
/* ------------------------------------------------------------------ */
function readJSON(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    return fallback;
  }
}

function writeJSON(file, obj) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = file + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(obj), 'utf8');
    fs.renameSync(tmp, file);
  } catch (e) {
    warn('写缓存失败', file, e.message);
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 单次 JSON GET（用 https 而非 fetch，兼容 Node 14+） */
function getJSON(pathOrUrl, timeout = 30000) {
  const url = pathOrUrl.startsWith('http') ? pathOrUrl : API_BASE + pathOrUrl;
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { 'User-Agent': UA, Accept: 'application/json' } }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const body = Buffer.concat(chunks).toString('utf8');
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(body));
          } catch (e) {
            reject(new Error('JSON 解析失败: ' + body.slice(0, 120)));
          }
        } else {
          const err = new Error(`HTTP ${res.statusCode}`);
          err.status = res.statusCode;
          reject(err);
        }
      });
    });
    req.setTimeout(timeout, () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

/** 带 429 退避的重试 */
async function getJSONRetry(p, tries = 5) {
  for (let i = 0; i < tries; i++) {
    try {
      return await getJSON(p);
    } catch (e) {
      if (e.status === 429) {
        await sleep(2000 * (i + 1));
        continue;
      }
      if (i === tries - 1) throw e;
      await sleep(800 * (i + 1));
    }
  }
  return null;
}

/** 固定并发池 */
async function pool(items, limit, worker) {
  const out = new Array(items.length);
  let idx = 0;
  const runners = new Array(Math.min(limit, items.length || 1)).fill(0).map(async () => {
    while (true) {
      const i = idx++;
      if (i >= items.length) return;
      out[i] = await worker(items[i], i);
    }
  });
  await Promise.all(runners);
  return out;
}

const dayDiff = (isoDate, today) => {
  if (!isoDate) return null;
  const t = Date.parse(isoDate + 'T00:00:00Z');
  if (isNaN(t)) return null;
  return Math.max(0, Math.floor((today - t) / 86400000));
};

const todayUTC = () => {
  const d = new Date();
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
};

const DATE_ONLY = (iso) => (iso ? String(iso).slice(0, 10) : '');

/* ------------------------------------------------------------------ */
/* 抓取                                                                */
/* ------------------------------------------------------------------ */
async function fetchHotDramas() {
  const first = await getJSONRetry('/dramas/hot?page=1&pageSize=100');
  if (!first || !first.data) throw new Error('榜单首页失败');
  const items = [...first.data.list];
  const pages = first.data.totalPages;
  for (let p = 2; p <= pages; p++) {
    const r = await getJSONRetry(`/dramas/hot?page=${p}&pageSize=100`);
    if (r && r.data && r.data.list) items.push(...r.data.list);
    await sleep(200);
  }
  const seen = new Set();
  const uniq = [];
  for (const it of items) {
    if (seen.has(it.id)) continue;
    seen.add(it.id);
    uniq.push(it);
  }
  log(`榜单: total=${first.data.total} 去重后=${uniq.length}`);
  return uniq;
}

async function fetchDetails(ids) {
  const missing = ids.filter((id) => !S.detailCache[id]);
  if (!missing.length) return S.detailCache;
  log(`详情: 缓存 ${Object.keys(S.detailCache).length} 条，补抓 ${missing.length} 条`);
  await pool(missing, 4, async (id) => {
    try {
      const r = await getJSONRetry('/dramas/' + id);
      if (r && r.data) S.detailCache[id] = r.data;
    } catch (e) {
      warn('详情失败', id, e.message);
    }
    await sleep(150);
  });
  writeJSON(F.detail, S.detailCache);
  return S.detailCache;
}

async function fetchEpisodeStats(ids) {
  const need = ids.filter((id) => !S.epsCache[id]);
  if (need.length) log(`分集: 缓存 ${ids.length - need.length} 部，补抓 ${need.length} 部（约 1-3 分钟）`);
  await pool(need, 4, async (id) => {
    try {
      const r = await getJSONRetry('/episodes/drama/' + id);
      if (r && Array.isArray(r.data)) S.epsCache[id] = r.data;
    } catch (e) {
      warn('分集失败', id, e.message);
    }
    await sleep(120);
  });
  if (need.length) writeJSON(F.eps, S.epsCache);

  const today = todayUTC();
  const stats = {};
  for (const id of ids) {
    const list = S.epsCache[id] || [];
    let last = 0;
    let recent = 0;
    for (const e of list) {
      const t = Date.parse(e.createdAt || '');
      if (isNaN(t)) continue;
      if (t > last) last = t;
      if ((Date.now() - t) / 86400000 <= UPD_WINDOW) recent++;
    }
    stats[id] = {
      le: last ? new Date(last).toISOString().slice(0, 10) : '',
      r7: recent,
      pc: list.length,
    };
  }
  return stats;
}

async function fetchNovels() {
  const first = await getJSONRetry('/novels?page=1&pageSize=50');
  if (!first || !first.data) throw new Error('书城首页失败');
  const items = [...first.data.list];
  for (let p = 2; p <= first.data.totalPages; p++) {
    const r = await getJSONRetry(`/novels?page=${p}&pageSize=50`);
    if (r && r.data && r.data.list) items.push(...r.data.list);
    await sleep(200);
  }
  log(`书城: ${items.length} 本`);
  return items;
}

async function fetchGifts() {
  const r = await getJSONRetry('/dramas/rankings/gifts?page=1&pageSize=100');
  const list = (r && r.data && r.data.list) || [];
  return { order: list.map((d) => d.id), qty: Object.fromEntries(list.map((d) => [d.id, d.giftQuantity || 0])) };
}

/* ------------------------------------------------------------------ */
/* 聚合                                                                */
/* ------------------------------------------------------------------ */
function buildPayload(hot, novelsRaw, gifts, epStats) {
  const today = todayUTC();
  const dramas = hot.map((h) => {
    const d = S.detailCache[h.id] || {};
    const cov = h.coverUrl || '';
    const st = epStats[h.id] || { le: '', r7: 0, pc: 0 };
    const desc = String(d.description || h.description || '').replace(/\s+/g, ' ').trim();
    const ct = DATE_ONLY(d.createdAt);
    return {
      i: h.id,
      t: h.title,
      c: cov.startsWith(COVER_BASE) ? cov.slice(COVER_BASE.length) : '',
      k: h.category,
      g: (h.tags || []).slice(0, 8),
      h: Math.round(h.hotScore || 0),
      v: h.viewCount || 0,
      e: h.totalEpisodes || 0,
      a: h.creatorName || '',
      b: (h.cornerBadge && h.cornerBadge.name) || '',
      s: h.isSerializing ? 1 : 0,
      ct,
      ad: dayDiff(ct, today),
      le: st.le,
      ld: dayDiff(st.le, today),
      r7: st.r7,
      pc: st.pc,
      fp: d.freeEpisodeCount == null ? null : d.freeEpisodeCount,
      mo: d.mode || '',
      wp: d.wholePrice == null ? null : d.wholePrice,
      gq: gifts.qty[h.id] == null ? null : gifts.qty[h.id],
      sd: desc.slice(0, 120),
    };
  });

  // 分类统计（命中 category 或 tags 的数量，与前端筛选口径一致）
  const catCount = {};
  const hitCount = {};
  for (const x of dramas) {
    const k = x.k || '其他';
    catCount[k] = (catCount[k] || 0) + 1;
    const keys = new Set([x.k, ...(x.g || [])].filter(Boolean));
    for (const kk of keys) hitCount[kk] = (hitCount[kk] || 0) + 1;
  }
  const categories = Object.entries(catCount)
    .sort((a, b) => b[1] - a[1])
    .map(([name, n]) => ({ name, n: hitCount[name] || n }));

  // 书城
  const novels = [];
  const novelTagCount = {};
  for (const n of novelsRaw) {
    const cov = n.coverUrl || '';
    const desc = String(n.description || '').replace(/\s+/g, ' ').trim();
    const ct = DATE_ONLY(n.createdAt);
    const tags = n.tags || [];
    for (const t of tags) if (t) novelTagCount[t] = (novelTagCount[t] || 0) + 1;
    novels.push({
      i: n.id,
      t: n.title,
      c: cov.startsWith(COVER_BASE) ? cov.slice(COVER_BASE.length) : '',
      a: n.creatorName || '',
      g: tags.slice(0, 8),
      h: Math.round(n.hotScore || 0),
      v: n.viewCount || 0,
      u: n.unlockCount || 0,
      ch: n.totalChapters || 0,
      s: n.isSerializing ? 1 : 0,
      ct,
      ad: dayDiff(ct, today),
      lu: DATE_ONLY(n.lastContentUpdatedAt),
      mo: n.pricingMode || '',
      wp: n.wholePrice == null ? null : n.wholePrice,
      fc: n.freeChapterCount || 0,
      sd: desc.slice(0, 120),
    });
  }
  novels.sort((a, b) => b.h - a.h);
  const novelTags = Object.entries(novelTagCount)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name, n]) => ({ name, n }));

  // 各榜计数与黑马阈值
  const hs = dramas.map((x) => x.h).sort((a, b) => b - a);
  const darkThr = hs.length ? hs[Math.floor(hs.length * DARK_TOP_PCT)] : 0;
  const counts = {
    all: dramas.length,
    new7: dramas.filter((x) => x.ad != null && x.ad <= 7).length,
    upd: dramas.filter((x) => x.r7 > 0).length,
    finish: dramas.filter((x) => x.s === 0).length,
    dark: dramas.filter((x) => x.ad != null && x.ad >= DARK_MIN_AGE && x.ad <= DARK_MAX_AGE && x.h >= darkThr).length,
    gift: gifts.order.length,
    novel: novels.length,
  };

  const now = new Date();
  const p2 = (x) => String(x).padStart(2, '0');
  const generatedAt =
    now.getFullYear() + '-' + p2(now.getMonth() + 1) + '-' + p2(now.getDate()) +
    'T' + p2(now.getHours()) + ':' + p2(now.getMinutes()) + ':' + p2(now.getSeconds());

  return {
    meta: {
      generatedAt,
      episodesAsOf: epStats.__asOf || '',
      coverBase: COVER_BASE,
      source: 'api.starry.wang',
      counts,
      dark: { minAge: DARK_MIN_AGE, maxAge: DARK_MAX_AGE, topPct: Math.round(DARK_TOP_PCT * 100), threshold: darkThr },
      updWindow: UPD_WINDOW,
      giftOrder: gifts.order,
    },
    dramas,
    categories,
    novels,
    novelTags,
  };
}

/* ------------------------------------------------------------------ */
/* 刷新调度                                                            */
/* ------------------------------------------------------------------ */
async function doRefresh(withEpisodes) {
  if (S.refreshing) {
    log('已有刷新在进行，跳过');
    return S.payload;
  }
  S.refreshing = true;
  const t0 = Date.now();
  try {
    const hot = await fetchHotDramas();
    const ids = hot.map((h) => h.id);
    await fetchDetails(ids);

    let epStats;
    if (withEpisodes || !S.payload) {
      epStats = await fetchEpisodeStats(ids);
      const d = new Date();
      epStats.__asOf = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
      S.lastHeavy = Date.now();
    } else {
      // 复用上次分集统计，只重算年龄天数
      epStats = {};
      for (const x of (S.payload ? S.payload.dramas : [])) {
        epStats[x.i] = { le: x.le, r7: x.r7, pc: x.pc };
      }
      epStats.__asOf = (S.payload && S.payload.meta && S.payload.meta.episodesAsOf) || '';
      for (const id of ids) if (!epStats[id]) epStats[id] = { le: '', r7: 0, pc: 0 };
    }

    const [novelsRaw, gifts] = await Promise.all([fetchNovels(), fetchGifts()]);
    const payload = buildPayload(hot, novelsRaw, gifts, epStats);

    S.payload = payload;
    S.payloadRaw = JSON.stringify(payload);
    S.payloadGzip = zlib.gzipSync(Buffer.from(S.payloadRaw, 'utf8'), { level: 6 });
    S.etag = '"' + Buffer.from(payload.meta.generatedAt).toString('base64') + '"';
    S.lastLight = Date.now();
    S.lastError = null;
    writeJSON(F.payload, payload);

    log(`刷新完成 ${withEpisodes ? '(含分集)' : '(轻量)'} · ${payload.dramas.length} 部 / ${payload.novels.length} 本 · ${Date.now() - t0}ms · gzip ${(S.payloadGzip.length / 1024).toFixed(0)}KB`);
    return payload;
  } catch (e) {
    S.lastError = e.message;
    warn('刷新失败:', e.message);
    return S.payload;
  } finally {
    S.refreshing = false;
  }
}

function schedule() {
  setInterval(() => {
    if (Date.now() - S.lastHeavy >= REFRESH_HEAVY) doRefresh(true);
    else doRefresh(false);
  }, REFRESH_LIGHT);
}

/* ------------------------------------------------------------------ */
/* HTTP                                                                */
/* ------------------------------------------------------------------ */
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
};

function sendJSON(req, res, code, obj, extraHeaders) {
  const body = Buffer.from(JSON.stringify(obj), 'utf8');
  const headers = Object.assign({
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Access-Control-Allow-Origin': '*',
    'Content-Length': body.length,
  }, extraHeaders || {});
  res.writeHead(code, headers);
  res.end(req.method === 'HEAD' ? undefined : body);
}

function serveStatic(req, res, relPath) {
  const safe = path.normalize(relPath).replace(/^(\.\.[/\\])+/, '');
  const file = path.join(PUBLIC_DIR, safe);
  if (!file.startsWith(PUBLIC_DIR)) {
    res.writeHead(403); res.end('forbidden'); return;
  }
  fs.readFile(file, (err, buf) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('not found');
      return;
    }
    const ext = path.extname(file).toLowerCase();
    res.writeHead(200, {
      'Content-Type': MIME[ext] || 'application/octet-stream',
      'Cache-Control': ext === '.html' ? 'no-cache' : 'public, max-age=3600',
      'Content-Length': buf.length,
    });
    res.end(req.method === 'HEAD' ? undefined : buf);
  });
}

const server = http.createServer(async (req, res) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'no-referrer-when-downgrade');
  const u = new URL(req.url, 'http://' + (req.headers.host || 'localhost'));
  const p = u.pathname;

  // 健康检查
  if (p === '/api/health') {
    return sendJSON(req, res, 200, {
      ok: !!S.payload,
      uptime: Math.round((Date.now() - S.startedAt) / 1000),
      dramas: S.payload ? S.payload.dramas.length : 0,
      novels: S.payload ? S.payload.novels.length : 0,
      generatedAt: S.payload ? S.payload.meta.generatedAt : null,
      episodesAsOf: S.payload ? S.payload.meta.episodesAsOf : null,
      lastLightAgo: S.lastLight ? Math.round((Date.now() - S.lastLight) / 1000) : null,
      lastHeavyAgo: S.lastHeavy ? Math.round((Date.now() - S.lastHeavy) / 1000) : null,
      refreshing: S.refreshing,
      lastError: S.lastError,
      memoryMB: Math.round(process.memoryUsage().rss / 1048576),
    });
  }

  // 版本探测（前端轮询用，几十字节）
  if (p === '/api/version') {
    if (!S.payload) return sendJSON(req, res, 503, { ready: false });
    return sendJSON(req, res, 200, {
      ready: true,
      generatedAt: S.payload.meta.generatedAt,
      counts: S.payload.meta.counts,
    });
  }

  // 全量数据（gzip + ETag，304 省流量）
  if (p === '/api/data' || p === '/data.json') {
    if (!S.payload) return sendJSON(req, res, 503, { code: 503, message: '数据准备中，请稍后重试' });
    const inm = req.headers['if-none-match'];
    if (inm && inm === S.etag) {
      res.writeHead(304, { ETag: S.etag, 'Cache-Control': 'no-store' });
      return res.end();
    }
    const ae = String(req.headers['accept-encoding'] || '');
    if (ae.includes('gzip')) {
      res.writeHead(200, {
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Encoding': 'gzip',
        'Cache-Control': 'no-store',
        'Access-Control-Allow-Origin': '*',
        ETag: S.etag,
        'Content-Length': S.payloadGzip.length,
      });
      return res.end(req.method === 'HEAD' ? undefined : S.payloadGzip);
    }
    const buf = Buffer.from(S.payloadRaw, 'utf8');
    res.writeHead(200, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'Access-Control-Allow-Origin': '*',
      ETag: S.etag,
      'Content-Length': buf.length,
    });
    return res.end(req.method === 'HEAD' ? undefined : buf);
  }

  // 手动刷新
  if (p === '/api/refresh') {
    if (req.method !== 'POST') return sendJSON(req, res, 405, { message: 'POST only' });
    if (ADMIN_TOKEN && req.headers['x-admin-token'] !== ADMIN_TOKEN) {
      return sendJSON(req, res, 401, { message: 'unauthorized' });
    }
    const heavy = u.searchParams.get('heavy') === '1';
    doRefresh(heavy);
    return sendJSON(req, res, 202, { ok: true, mode: heavy ? 'heavy' : 'light' });
  }

  // 页面与静态资源
  if (p === '/' || p === '/index.html') return serveStatic(req, res, 'index.html');
  return serveStatic(req, res, p.replace(/^\/+/, ''));
});

/* ------------------------------------------------------------------ */
/* 启动                                                                */
/* ------------------------------------------------------------------ */
async function boot() {
  fs.mkdirSync(DATA_DIR, { recursive: true });

  // 1) 先吃缓存，做到秒开
  const cachedPayload = readJSON(F.payload, null);
  if (cachedPayload && cachedPayload.meta) {
    S.payload = cachedPayload;
    S.payloadRaw = JSON.stringify(cachedPayload);
    S.payloadGzip = zlib.gzipSync(Buffer.from(S.payloadRaw, 'utf8'), { level: 6 });
    S.etag = '"' + Buffer.from(cachedPayload.meta.generatedAt).toString('base64') + '"';
    log(`载入缓存: ${cachedPayload.dramas.length} 部 / ${cachedPayload.novels.length} 本 · ${cachedPayload.meta.generatedAt}`);
  }
  S.detailCache = readJSON(F.detail, {});
  S.epsCache = readJSON(F.eps, {});

  // 2) 监听
  server.listen(PORT, HOST, () => {
    log(`监听 http://${HOST}:${PORT}  （反代请指向这里）`);
    log(`页面 http://${HOST}:${PORT}/   数据 /api/data   健康 /api/health`);
  });

  // 3) 首次刷新：没有缓存就含分集，有缓存则轻量补差
  const firstHeavy = !S.payload;
  doRefresh(firstHeavy).catch((e) => warn('首次刷新异常', e.message));
  schedule();
}

process.on('uncaughtException', (e) => warn('未捕获异常:', e.message));
process.on('unhandledRejection', (e) => warn('未处理 Promise:', e && e.message));
process.on('SIGTERM', () => { log('收到 SIGTERM，退出'); server.close(() => process.exit(0)); });
process.on('SIGINT', () => { log('收到 SIGINT，退出'); server.close(() => process.exit(0)); });

boot();
