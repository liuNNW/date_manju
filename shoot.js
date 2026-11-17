// CDP 截图工具：node shoot.js <url> <out.png> <width> <height> [evalJs]
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const [url, out, w, h, evalJs] = process.argv.slice(2);
const W = parseInt(w || '1440', 10), H = parseInt(h || '1000', 10);
const PORT = 9333 + Math.floor(Math.random() * 300);
const profile = path.join(process.env.TEMP, 'cdp_' + PORT);

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const child = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
    '--no-default-browser-check', '--disable-extensions', '--mute-audio',
    '--allow-file-access-from-files', '--force-device-scale-factor=1',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + profile,
    '--window-size=' + W + ',' + H, 'about:blank'
  ], { stdio: 'ignore', detached: false });

  let info = null;
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch('http://127.0.0.1:' + PORT + '/json/version');
      info = await r.json();
      break;
    } catch (e) { await sleep(250); }
  }
  if (!info) { console.error('chrome not up'); child.kill(); process.exit(1); }

  const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
  const page = list.find(t => t.type === 'page');
  if (!page) { console.error('no page target'); child.kill(); process.exit(1); }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pending = new Map();
  const send = (method, params) => new Promise((res, rej) => {
    const mid = ++id;
    pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params: params || {} }));
  });
  await new Promise(r => ws.addEventListener('open', r));
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id); pending.delete(m.id);
      m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
    }
  });

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {
    width: W, height: H, deviceScaleFactor: 1, mobile: W < 600
  });
  await send('Page.navigate', { url });
  await sleep(1200);
  // 等图片与脚本就绪
  for (let i = 0; i < 20; i++) {
    const r = await send('Runtime.evaluate', {
      expression: 'document.readyState + "|" + (document.querySelectorAll(".card").length)',
      returnByValue: true
    });
    const v = String(r.result.value || '');
    if (v.startsWith('complete|') && parseInt(v.split('|')[1] || '0', 10) > 0) break;
    await sleep(300);
  }
  if (evalJs) {
    try { await send('Runtime.evaluate', { expression: evalJs, awaitPromise: true }); }
    catch (e) { console.error('eval err', e.message); }
    await sleep(900);
  }
  await sleep(1200);

  const shot = await send('Page.captureScreenshot', {
    format: 'png', fromSurface: true, captureBeyondViewport: false
  });
  fs.writeFileSync(out, Buffer.from(shot.data, 'base64'));
  console.log('saved', out, fs.statSync(out).size, 'bytes');

  // 顺带把控制台错误与布局体检数据带回来
  const diag = await send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const g = document.getElementById('grid');
      const cards = document.querySelectorAll('.card').length;
      const cols = g ? getComputedStyle(g).gridTemplateColumns.split(' ').length : 0;
      const imgs = [...document.querySelectorAll('.poster img')];
      const loaded = imgs.filter(i => i.complete && i.naturalWidth > 0).length;
      const failed = document.querySelectorAll('.poster.fail').length;
      return JSON.stringify({
        cards, cols, imgs: imgs.length, loaded, failed,
        docW: document.documentElement.scrollWidth,
        winW: window.innerWidth,
        overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
        count: document.getElementById('count').textContent,
        firstTitles: [...document.querySelectorAll('.cap h3')].slice(0,4).map(e=>e.textContent)
      });
    })()`
  });
  console.log('DIAG', diag.result.value);
  ws.close();
  child.kill();
  await sleep(300);
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) {}
}

main().catch(e => { console.error('ERR', e.message); process.exit(1); });
