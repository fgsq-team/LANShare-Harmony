// 5.1.59 离线验证：鸿蒙端推送路径 autoDownloadFiles() / downloadOnePushed()
// 断言「单文件 => 不调 /compressFiles、改为 location.href=/file/...」
const fs = require('fs');
const vm = require('vm');

const SRC = fs.readFileSync(
  __dirname + '/../../entry/src/main/resources/rawfile/web/js/lanshareChat.min.js', 'utf8');

function extract(name) {
  const start = SRC.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('找不到函数 ' + name);
  let i = SRC.indexOf('{', start), depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === '{') depth++;
    else if (SRC[i] === '}') { depth--; if (depth === 0) return SRC.slice(start, i + 1); }
  }
  throw new Error(name + ' 花括号不配对');
}
const code = extract('downloadOnePushed') + '\n' + extract('autoDownloadFiles');

function run(list, names) {
  const calls = { post: [], href: null, notify: [], loading: [] };
  const ctx = {
    window: { location: { set href(v) { calls.href = v; }, get href() { return calls.href; } } },
    localStorage: { getItem: () => 'TOK999' },
    lightyear: {
      notify: (m, t) => calls.notify.push(m + '|' + t),
      loading: (m) => calls.loading.push(m),
    },
    post: (o) => { calls.post.push(o.url); if (o.error) o.error({ message: 'x' }); },
    encodeURIComponent,
    console,
  };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  ctx.autoDownloadFiles(list, names);
  return calls;
}

let fail = 0;
function check(label, cond, extra) {
  console.log((cond ? 'OK   ' : 'FAIL ') + label + (extra ? '   ' + extra : ''));
  if (!cond) fail++;
}

// 用例1：推送 1 个文件（鸿蒙端已推 names）=> 直推
const one = run(['/data/storage/el2/base/haps/entry/files/Docs/abc_1.jpg'], ['abc_1.jpg']);
check('推送单文件：不调 /compressFiles', one.post.length === 0, JSON.stringify(one.post));
check('推送单文件：走 location.href=/file/', !!one.href && one.href.startsWith('/file/'), one.href);
check('推送单文件：URL 用的是 names 里的文件名', !!one.href && one.href.startsWith('/file/abc_1.jpg'), '');
check('推送单文件：带 path 与 token', !!one.href && one.href.includes('path=%2Fdata') && one.href.includes('token=TOK999'), '');
check('推送单文件：无打包 loading 遮罩', one.loading.length === 0, JSON.stringify(one.loading));
check('推送单文件：不提示"正在打包"', !one.notify.some(n => n.indexOf('正在打包') >= 0), JSON.stringify(one.notify));

// 用例2：推送 3 个文件 => 仍打包
const three = run(['/d/a.jpg', '/d/b.png', '/d/c.mp4'], ['a.jpg', 'b.png', 'c.mp4']);
check('推送多文件：调 /compressFiles', three.post.length === 1 && three.post[0] === '/compressFiles', JSON.stringify(three.post));
check('推送多文件：不走 /file/', three.href === null, String(three.href));
check('推送多文件：有 loading 遮罩', three.loading.includes('show'), JSON.stringify(three.loading));

// 用例3：老版本鸿蒙端只推 list 不推 names ⇒ 必须回退打包，不能请求 /file/undefined
const legacy = run(['/d/old.jpg'], undefined);
check('无 names（老对端）：回退到打包', legacy.post.length === 1 && legacy.post[0] === '/compressFiles', JSON.stringify(legacy.post));
check('无 names（老对端）：绝不请求 /file/undefined', !!legacy.href === false, String(legacy.href));

// 用例4：空 list => 什么都不做
const empty = run([], []);
check('空列表：无请求无跳转', empty.post.length === 0 && empty.href === null, '');
check('空列表：无提示', empty.notify.length === 0, JSON.stringify(empty.notify));

// 用例5：单文件但 names 为空数组 => 回退打包
const badNames = run(['/d/x.jpg'], []);
check('names 空数组：回退打包', badNames.post.length === 1 && badNames.post[0] === '/compressFiles', JSON.stringify(badNames.post));

console.log('-'.repeat(78));
if (fail) { console.log('FAILED: ' + fail + ' 项不符'); process.exit(1); }
console.log('ALL PASS: 推送单文件直推 / 多文件打包 / 老对端回退 / 空列表 均符合预期');