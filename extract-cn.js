// 从 Dart AOT 快照里提取中文字符串（含上下文），定位付费/解锁相关提示
const fs = require('fs');

const buf = fs.readFileSync('unpacked/lib/arm64-v8a/libapp.so');
const text = buf.toString('utf8');

const re = /[\u4e00-\u9fa5][\u4e00-\u9fa5A-Za-z0-9，。！？、：；""''（）《》%·\s\-]{1,30}/g;
const hits = text.match(re) || [];
const uniq = [...new Set(hits.map(s => s.trim()).filter(s => s.length >= 2))];

console.log('中文片段总数:', hits.length, '| 去重:', uniq.length);

const kw = ['解锁', '购买', '金币', '会员', '充值', '试看', '免费', '付费', '余额', '支付',
            '权限', '不足', '开通', '订阅', '订单', '需', '请先', '已购', '已解锁', '看不了'];
const sel = uniq.filter(u => kw.some(k => u.includes(k)));

console.log('\n=== 付费/解锁相关 (%d) ===', sel.length);
sel.slice(0, 80).forEach(u => console.log('  ' + u));

console.log('\n=== 播放/错误提示 ===');
const kw2 = ['播放', '视频', '加载', '失败', '错误', '稍后', '重试', '登录', '账号'];
uniq.filter(u => kw2.some(k => u.includes(k))).slice(0, 40).forEach(u => console.log('  ' + u));

// 存全量便于后续检索
fs.writeFileSync('cn_strings.txt', uniq.join('\n'), 'utf8');
console.log('\n[=] 全量已存 cn_strings.txt (%d 条)', uniq.length);
