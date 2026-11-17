/**
 * 把 rank_template.html（双模式模板）转成 PM2 服务端的纯前端页面
 * --------------------------------------------------------------
 *   模板 = 内嵌快照 + 可选的同源 data.json 轮询（本地单文件用）
 *   产物 = 无内嵌数据，启动时 GET /api/data，轮询 /api/version（PM2 服务用）
 *
 * 用法：node make-frontend.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const SRC = path.join(ROOT, 'rank_template.html');
const OUT = path.join(ROOT, 'rank-server', 'public', 'index.html');

let t = fs.readFileSync(SRC, 'utf8');
const before = t.length;

/* 1) 去掉内嵌数据块 */
t = t.replace(/<script type="application\/json" id="data">[\s\S]*?<\/script>\s*\n/, '');

/* 2) PAYLOAD 不再从 DOM 读 */
t = t.replace(
  "  var PAYLOAD = JSON.parse(document.getElementById('data').textContent);",
  "  var PAYLOAD = null;"
);
t = t.replace(/\n\s*bindData\(PAYLOAD\);\n/, '\n');

/* 3) 记录运行模式 */
t = t.replace(
  "  var MODE = 'file';            // 'file' = 内嵌快照模式；'server' = 服务端 API 模式",
  "  var MODE = 'server';          // 服务端 API 模式（PM2）"
);

/* 4) 替换末尾初始化块为「拉 /api/data + 轮询 /api/version」 */
const START = '  paintMeta();\n\n  /* ====== 首屏';
const startIdx = t.indexOf(START);
if (startIdx < 0) throw new Error('未找到初始化块标记，模板结构可能变了');
const endIdx = t.lastIndexOf('})();');
if (endIdx < startIdx) throw new Error('未找到收尾标记');

const NEW_BOOT = `  /* ================= 骨架屏 ================= */
  function skeleton(){
    var s = '';
    for(var i=0;i<21;i++) s += '<div class="sk"><div class="sk-p"></div></div>';
    return s;
  }

  /* ================= 数据装载 ================= */
  function flashTip(text){
    var el = document.getElementById('liveTip');
    if(!el) return;
    el.textContent = text;
    el.classList.add('on');
    clearTimeout(el._t);
    el._t = setTimeout(function(){ el.classList.remove('on') }, 3200);
  }
  function fetchJSON(url){
    return fetch(url, {cache:'no-store', headers:{'Accept':'application/json'}})
      .then(function(r){
        if(!r.ok) throw new Error('HTTP ' + r.status + (r.status===503 ? '（服务端还在准备数据）' : ''));
        return r.json();
      });
  }
  function applyPayload(p, first){
    if(!bindData(p)) throw new Error('数据格式异常');
    LIVE = true;
    if(first){
      paintMeta();
      applyHash();
      syncTopH();
      setTimeout(syncTopH, 260);
    }else{
      sync();
      paintMeta();
      syncTopH();
      warmCached();
    }
  }
  function bootError(msg){
    $more.hidden = true;
    $grid.innerHTML = '<div class="empty"><p>数据加载失败：' + esc(msg) + '</p>' +
      '<button id="retryBtn">重新加载</button></div>';
    var b = document.getElementById('retryBtn');
    if(b) b.addEventListener('click', function(){ boot(); });
    document.getElementById('count').textContent = '连接失败';
  }

  var booted = false, polling = false;
  function startPolling(){
    if(polling) return;
    polling = true;
    setInterval(function(){
      fetchJSON('api/version?ts=' + Date.now())
        .then(function(v){
          if(v && v.generatedAt && v.generatedAt !== META.generatedAt){
            return fetchJSON('api/data?ts=' + Date.now()).then(function(p){
              applyPayload(p, false);
              flashTip('数据已更新');
            });
          }
          paintMeta();   // 只刷新"几分钟前"这类相对时间
        })
        .catch(function(){
          if(LIVE){ LIVE = false; paintMeta(); }
        });
    }, POLL_MS);
  }

  function boot(){
    if(!booted) $grid.innerHTML = skeleton();
    fetchJSON('api/data?ts=' + Date.now())
      .then(function(p){
        applyPayload(p, !booted);
        booted = true;
        startPolling();
      })
      .catch(function(e){ bootError(e.message); });
  }

  paintMeta();
  boot();
`;

t = t.slice(0, startIdx) + NEW_BOOT + t.slice(endIdx);

/* 5) 加骨架屏样式 */
const SK_CSS = `
/* ================= 骨架屏（服务端模式） ================= */
.sk .sk-p{
  aspect-ratio:7/10;border-radius:var(--r-m);
  background:linear-gradient(100deg,#14141c 20%,#1e1e29 40%,#14141c 60%);
  background-size:220% 100%;
  animation:skwave 1.3s ease-in-out infinite;
}
@keyframes skwave{to{background-position:-220% 0}}
@media(prefers-reduced-motion:reduce){.sk .sk-p{animation:none}}
</style>`;
t = t.replace(/\n<\/style>/, SK_CSS);

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, t, 'utf8');

console.log(`[ok] ${OUT}`);
console.log(`     模板 ${(before/1024).toFixed(0)}KB → 产物 ${(t.length/1024).toFixed(0)}KB（无内嵌数据）`);
if (t.includes('__DATA_JSON__') || t.includes('id="data"')) {
  console.warn('[!] 仍残留内嵌数据标记，请检查');
}
