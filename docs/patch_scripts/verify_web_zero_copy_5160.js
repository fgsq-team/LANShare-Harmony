// 5.1.60 离线验证：零落盘直推路径
// 断言「带 uris => 走 /stagefile/，不调 /compressFiles、不用 paths」
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

function run(list, names, uris) {
  const calls = { post: [], href: null, notify: [], loading: [] };
  const ctx = {
    window: { location: { set href(v) { calls.href = v; }, get href() { return calls.href; } } },
    localStorage: { getItem: () => 'TOK' },
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
  ctx.autoDownloadFiles(list, names, uris);
  return calls;
}

let fail = 0;
function check(label, cond, extra) {
  console.log((cond ? 'OK   ' : 'FAIL ') + label + (extra ? '   ' + extra : ''));
  if (!cond) fail++;
}

const URI = 'datashare://media/file/1234?uid=abc';

// A. 5.1.60 新路径：uris 有值、paths 为空 => /stagefile/
const a = run([], ['abc_1.jpg'], [URI]);
check('零落盘：不调 /compressFiles', a.post.length === 0, JSON.stringify(a.post));
check('零落盘：走 /stagefile/', !!a.href && a.href.startsWith('/stagefile/abc_1.jpg'), a.href);
check('零落盘：带 uri 参数', !!a.href && a.href.includes('uri=datashare%3A%2F%2F'), '');
check('零落盘：带 token', !!a.href && a.href.includes('token=TOK'), '');
check('零落盘：无 loading 遮罩', a.loading.length === 0, JSON.stringify(a.loading));

// B. 老路径回归：只有 paths（文件页单条已在沙箱）=> 仍走 /file/
const b = run(['/data/.../Docs/x.jpg'], ['x.jpg'], undefined);
check('回归：有 paths 无 uris => /file/', !!b.href && b.href.startsWith('/file/x.jpg'), b.href);
check('回归：不调 /compressFiles', b.post.length === 0, JSON.stringify(b.post));

// C. paths + uris 都有 => 优先 /stagefile/（零落盘优先）
const c = run(['/data/x.jpg'], ['x.jpg'], [URI]);
check('两者都有：优先 /stagefile/', !!c.href && c.href.startsWith('/stagefile/'), c.href);

// D. 多文件 => 必须打包（浏览器限制），即使有 uris
const d = run(['/data/a.jpg', '/data/b.png'], ['a.jpg', 'b.png'], [URI, URI]);
check('多文件：仍打包', d.post.length === 1 && d.post[0] === '/compressFiles', JSON.stringify(d.post));
check('多文件：不走 /stagefile/', !d.href || !d.href.startsWith('/stagefile/'), String(d.href));

// E. 空 list + 空 names => 什么都不做
const e = run([], [], []);
check('全空：无动作', e.post.length === 0 && e.href === null, '');

console.log('-'.repeat(78));
if (fail) { console.log('FAILED: ' + fail + ' 项不符'); process.exit(1); }
console.log('ALL PASS: 零落盘 /stagefile/ + 老路径回归 + 多文件仍打包');