// 榜单页自动化体检（同时支持 file:// 单文件模式 与 http:// PM2 服务模式）
//   node selftest.js <url>
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const url = process.argv[2];
const PORT = 9700 + Math.floor(Math.random() * 200);
const profile = path.join(process.env.TEMP, 'cdpst_' + PORT);
const sleep = ms => new Promise(r => setTimeout(r, ms));

const VIEWPORTS = [
  { name: 'desktop-1440', w: 1440, h: 1000 },
  { name: 'laptop-1024', w: 1024, h: 900 },
  { name: 'tablet-768', w: 768, h: 900 },
  { name: 'mobile-390', w: 390, h: 844 },
  { name: 'mobile-375', w: 375, h: 812 },
];

const PROBE = `(() => {
  const out={};
  const g=document.getElementById('grid');
  const cs=getComputedStyle(g);
  out.cols=cs.gridTemplateColumns.split(' ').filter(Boolean).length;
  out.docW=document.documentElement.scrollWidth;
  out.winW=window.innerWidth;
  out.overflowX=document.documentElement.scrollWidth>window.innerWidth+1;
  const card=document.querySelector('.card');
  if(card){ const r=card.getBoundingClientRect(); out.cardW=Math.round(r.width); out.cardRatio=+(r.width/r.height).toFixed(3) }
  const top=document.querySelector('.top');
  out.topH=top?Math.round(top.getBoundingClientRect().height):null;
  out.tabsFit=[...document.querySelectorAll('.tabs-main .tab')].every(t=>t.scrollWidth<=t.clientWidth+1);
  const first=document.querySelector('.card');
  if(first&&top){ out.contentCleared = first.getBoundingClientRect().top >= top.getBoundingClientRect().bottom - 1 }
  const rgb=s=>{const m=(s||'').match(/\\d+/g); return m?m.map(Number).slice(0,3):null};
  const lum=a=>{const f=c=>{c/=255;return c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4)};return .2126*f(a[0])+.7152*f(a[1])+.0722*f(a[2])};
  const cr=(x,y)=>{if(!x||!y)return null;const l1=lum(x),l2=lum(y);const hi=Math.max(l1,l2),lo=Math.min(l1,l2);return +((hi+.05)/(lo+.05)).toFixed(2)};
  const root=getComputedStyle(document.documentElement);
  const norm=v=>{v=(v||'').trim();return v.startsWith('#')?'rgb('+[1,3,5].map(i=>parseInt(v.substr(i,2),16)).join(',')+')':v};
  out.cText=cr(norm(root.getPropertyValue('--text')),norm(root.getPropertyValue('--bg')));
  out.cMuted=cr(norm(root.getPropertyValue('--muted')),norm(root.getPropertyValue('--bg')));
  out.cAccent=cr(norm(root.getPropertyValue('--accent')),norm(root.getPropertyValue('--bg')));
  return JSON.stringify(out);
})()`;

const FUNCS = `(async () => {
  const R={errs:[]};
  let data;
  const emb=document.getElementById('data');
  if(emb){ data=JSON.parse(emb.textContent); }
  else { const r=await fetch('api/data'); data=await r.json(); }
  const byId=new Map(data.dramas.map(d=>[String(d.i),d]));
  const nById=new Map((data.novels||[]).map(d=>[String(d.i),d]));
  const cards=()=>[...document.querySelectorAll('.card')];
  const rowsInDom=()=>cards().map(c=>byId.get(c.dataset.id)).filter(Boolean);
  const novelsInDom=()=>cards().map(c=>nById.get(c.dataset.id)).filter(Boolean);
  const cnt=()=>{const m=document.getElementById('count').textContent.match(/共\\s*(\\d+)\\s*[部本]/);return m?parseInt(m[1],10):0};
  const activeTab=()=>document.querySelector('.tabs-main .tab[aria-selected=true]').dataset.tab;
  const go=async(t)=>{ [...document.querySelectorAll('.tabs-main .tab')].find(x=>x.dataset.tab===t).click(); await new Promise(r=>setTimeout(r,400)) };
  const sub=async(s)=>{ [...document.querySelectorAll('.subtab')].find(x=>x.dataset.sub===s).click(); await new Promise(r=>setTimeout(r,400)) };
  const desc=(arr,f)=>{for(let i=0;i<arr.length-1;i++){if(f(arr[i])<f(arr[i+1]))return false}return true};

  // 热门
  await go('hot');
  R.hot={tab:activeTab(),count:cnt(),sorted:desc(rowsInDom(),d=>d.h),
         metaText:[...document.querySelectorAll('.mf')][0].textContent,
         allHaveHeat:[...document.querySelectorAll('.mf')].every(el=>el.textContent.indexOf('热度')>-1)};

  // 新剧
  await go('new');
  R.new={count:cnt(),sortedByDate:desc(rowsInDom(),d=>d.ct||''),metaText:[...document.querySelectorAll('.mf')][0].textContent};

  // 更新
  await go('upd');
  const ud=rowsInDom();
  R.upd={count:cnt(),allRecent:ud.every(d=>d.r7>0),sortedByLast:desc(ud,d=>d.le||''),metaText:[...document.querySelectorAll('.mf')][0].textContent};

  // 榜单 - 完结
  await go('rank');
  R.rankTab={subbarVisible:!document.getElementById('subbar').hidden,rule:document.querySelector('.subbar .rule').textContent.trim()};
  await sub('finish');
  const fd=rowsInDom();
  R.finish={count:cnt(),allFinished:fd.every(d=>d.s===0),sorted:desc(fd,d=>d.h),metaText:[...document.querySelectorAll('.mf')][0].textContent};

  // 榜单 - 黑马
  await sub('dark');
  const dd=rowsInDom(); const DK=data.meta.dark;
  R.dark={count:cnt(),allInAgeRange:dd.every(d=>d.ad>=DK.minAge&&d.ad<=DK.maxAge),
          allAboveThr:dd.every(d=>d.h>=DK.threshold),
          sortedByMomentum:desc(dd,d=>d.h/Math.max(d.ad,1)),
          metaText:[...document.querySelectorAll('.mf')][0].textContent};

  // 榜单 - 礼物
  await sub('gift');
  const gd=rowsInDom(); const gi=data.meta.giftOrder;
  R.gift={count:cnt(),orderMatches:gd.every((d,i)=>String(d.i)===String(gi[i])),
          allHaveGq:gd.every(d=>typeof d.gq==='number'),metaText:[...document.querySelectorAll('.mf')][0].textContent};

  // 书城 - 推荐
  await go('store');
  const nd=novelsInDom();
  R.store={count:cnt(),subActive:document.querySelector('.subtab[aria-pressed=true]').dataset.sub,
           chipCount:document.querySelectorAll('.chip').length,
           recSorted:desc(nd,d=>d.h),
           allHaveHeat:[...document.querySelectorAll('.mf')].every(el=>el.textContent.indexOf('热度')>-1),
           metaText:[...document.querySelectorAll('.mf')][0].textContent};

  // 书城 - 最新
  await sub('late');
  R.storeLate={subActive:document.querySelector('.subtab[aria-pressed=true]').dataset.sub,
               count:cnt(),sortedByDate:desc(novelsInDom(),d=>d.ct||''),
               metaText:[...document.querySelectorAll('.mf')][0].textContent};

  // 书城标签筛选
  const sweet=[...document.querySelectorAll('.chip')].find(c=>c.dataset.cat==='甜宠');
  R.storeTag={exists:!!sweet,label:sweet?sweet.textContent:null};
  if(sweet){
    sweet.click(); await new Promise(r=>setTimeout(r,360));
    R.storeTag.count=cnt();
    R.storeTag.match=sweet.textContent.replace(/[^0-9]/g,'')===String(cnt());
    R.storeTag.allMatch=novelsInDom().every(d=>(d.g||[]).indexOf('甜宠')>-1);
    [...document.querySelectorAll('.chip')].find(c=>c.dataset.cat==='全部').click();
    await new Promise(r=>setTimeout(r,300));
  }

  // 书城详情
  await sub('rec'); await new Promise(r=>setTimeout(r,280));
  cards()[0].click(); await new Promise(r=>setTimeout(r,560));
  R.novelDetail={open:document.getElementById('sheet').classList.contains('on'),
                 title:(document.querySelector('.d-head h2')||{}).textContent,
                 stats:[...document.querySelectorAll('.d-stat span')].map(x=>x.textContent),
                 rows:document.querySelectorAll('.d-row').length,
                 copyLabel:(document.getElementById('copyBtn')||{}).textContent};
  document.getElementById('close').click(); await new Promise(r=>setTimeout(r,420));

  // 搜索
  await go('hot');
  const q=document.getElementById('q');
  q.value='总裁'; q.dispatchEvent(new Event('input',{bubbles:true}));
  await new Promise(r=>setTimeout(r,460));
  R.search={count:cnt(),cards:cards().length};
  q.value=''; q.dispatchEvent(new Event('input',{bubbles:true}));
  await new Promise(r=>setTimeout(r,400));

  // 分类筛选
  const chip=[...document.querySelectorAll('.chip')].find(c=>c.dataset.cat==='古代');
  if(chip){
    chip.click(); await new Promise(r=>setTimeout(r,360));
    R.chip={label:chip.textContent,count:cnt(),match:chip.textContent.replace(/[^0-9]/g,'')===String(cnt())};
    [...document.querySelectorAll('.chip')].find(c=>c.dataset.cat==='全部').click();
    await new Promise(r=>setTimeout(r,300));
  }

  // 加载更多
  const more=document.getElementById('more');
  const before=cards().length;
  R.more={visible:!more.hidden,before};
  if(!more.hidden){ more.click(); await new Promise(r=>setTimeout(r,360)); R.more.after=cards().length; R.more.grew=cards().length>before }

  // 短剧详情
  cards()[0].click(); await new Promise(r=>setTimeout(r,560));
  R.detail={open:document.getElementById('sheet').classList.contains('on'),
            title:(document.querySelector('.d-head h2')||{}).textContent,
            stats:[...document.querySelectorAll('.d-stat span')].map(x=>x.textContent),
            rows:document.querySelectorAll('.d-row').length};
  document.getElementById('close').click(); await new Promise(r=>setTimeout(r,420));
  R.detail.closed=!document.getElementById('sheet').classList.contains('on');

  // 图片失败兜底
  const img=document.querySelector('.poster img');
  img.src='https://127.0.0.1:9/nope.jpg';
  await new Promise(r=>setTimeout(r,1600));
  R.fallback={shown:!!document.querySelector('.poster.fail'),
              phDisp:document.querySelector('.poster.fail .ph')?getComputedStyle(document.querySelector('.poster.fail .ph')).display:null};

  // 模式与时间显示
  R.meta={stamp:(document.getElementById('stamp')||{}).textContent,
          modeNote:((document.getElementById('modeNote')||{}).textContent||'').slice(0,40),
          stamp2:(document.getElementById('stamp2')||{}).textContent};
  R.externalDeps=[...document.querySelectorAll('link[rel=stylesheet],script[src]')].length;
  R.hash=location.hash;
  return JSON.stringify(R);
})()`;

async function main() {
  const child = spawn(CHROME, ['--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run',
    '--no-default-browser-check','--disable-extensions','--mute-audio','--allow-file-access-from-files',
    '--force-device-scale-factor=1','--remote-debugging-port='+PORT,'--user-data-dir='+profile,
    '--window-size=1440,1000','about:blank'], {stdio:'ignore'});

  let ok=false;
  for(let i=0;i<60;i++){ try{ await fetch('http://127.0.0.1:'+PORT+'/json/version'); ok=true; break }catch(e){ await sleep(250) } }
  if(!ok){ console.error('chrome 未启动'); child.kill(); process.exit(1) }

  const list = await (await fetch('http://127.0.0.1:'+PORT+'/json/list')).json();
  const page = list.find(t=>t.type==='page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id=0; const pend=new Map(); const msgs=[];
  const send=(m,p)=>new Promise((res,rej)=>{const i=++id;pend.set(i,{res,rej});ws.send(JSON.stringify({id:i,method:m,params:p||{}}))});
  await new Promise(r=>ws.addEventListener('open',r));
  ws.addEventListener('message',ev=>{
    const m=JSON.parse(ev.data);
    if(m.id&&pend.has(m.id)){const{res,rej}=pend.get(m.id);pend.delete(m.id);m.error?rej(new Error(JSON.stringify(m.error))):res(m.result)}
    if(m.method==='Runtime.consoleAPICalled'&&['error','warning'].includes(m.params.type)) msgs.push(m.params.type+': '+(m.params.args[0]&&m.params.args[0].value));
    if(m.method==='Runtime.exceptionThrown') msgs.push('exception: '+JSON.stringify(m.params.exceptionDetails.text));
  });
  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.navigate',{url});
  await sleep(2200);
  for(let i=0;i<40;i++){
    const r=await send('Runtime.evaluate',{expression:'document.querySelectorAll(".card").length',returnByValue:true});
    if(Number(r.result.value)>0) break;
    await sleep(300);
  }

  const vps={};
  for(const vp of VIEWPORTS){
    await send('Emulation.setDeviceMetricsOverride',{width:vp.w,height:vp.h,deviceScaleFactor:1,mobile:false});
    await sleep(430);
    const r=await send('Runtime.evaluate',{expression:PROBE,returnByValue:true});
    if(r.exceptionDetails){ console.error('PROBE 异常 @'+vp.name+':', (r.exceptionDetails.exception||{}).description); ws.close(); child.kill(); process.exit(1) }
    vps[vp.name]=JSON.parse(r.result.value);
  }

  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await sleep(400);
  const f=await send('Runtime.evaluate',{expression:FUNCS,returnByValue:true,awaitPromise:true});
  if(f.exceptionDetails){
    console.error('FUNCS 异常:', (f.exceptionDetails.exception||{}).description);
    ws.close(); child.kill(); process.exit(1);
  }
  const funcs=JSON.parse(f.result.value);

  console.log('=== 视口 ===');
  for(const k of Object.keys(vps)) console.log(k.padEnd(13), JSON.stringify(vps[k]));
  console.log('\n=== 功能断言 ===');
  console.log(JSON.stringify(funcs,null,1));
  console.log('\n=== 控制台 ('+msgs.length+') ===');
  msgs.slice(0,10).forEach(m=>console.log(' ',m));

  ws.close(); child.kill(); await sleep(300);
  try{ fs.rmSync(profile,{recursive:true,force:true}) }catch(e){}
}
main().catch(e=>{ console.error('ERR',e.stack); process.exit(1) });
