// 5.1.58 离线行为验证：用最小 DOM 桩跑真实的 downloadFile()，
// 断言「单选 => 不调 /compressFiles、改为 location.href=/file/...」
// 不依赖 jQuery 真实实现，只桩出用到的几个方法。
const fs = require('fs');
const vm = require('vm');

const SRC = fs.readFileSync(__dirname + '/../../entry/src/main/resources/rawfile/web/js/lanshare.min.js', 'utf8');

// ---- 抽出被测函数（downloadOneDirect / downloadFile）----
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
const code = extract('downloadOneDirect') + '\n' + extract('downloadFile');

// ---- 最小 DOM 桩 ----
function makeEl(opts) {
  const el = {
    _checked: opts.checked || false,
    _filePath: opts.filePath,
    _name: opts.name,
    _children: opts.children || [],
    attr(k) { return k === 'file-path' ? this._filePath : undefined; },
    find(sel) {
      if (sel === '.file-img-select') return { is: (t) => t === ':checked' && el._checked };
      if (sel === '.file-item-name') return { text: () => el._name };
      return { text: () => '' };
    },
  };
  return el;
}

function run(items) {
  const calls = { post: [], href: null, notify: [], loading: [] };
  const $ = (sel) => {
    // jQuery 的 .each 回调签名是 function(index, element) —— element 是**第二个**参数。
    // 代码里对每个元素还会再 `$(element)` 包一次，所以 $() 必须认得出「这就是那个元素」。
    for (const it of items) {
      if (sel === it) return it;
    }
    if (sel === '.file-item') return { each: (fn) => items.forEach((it, i) => fn(i, it)) };
    return { text: () => '', trim: (s) => (s || '').trim() };
  };
  $.trim = (s) => (s === undefined || s === null ? '' : String(s).trim());
  const ctx = {
    $,
    window: {
      location: {
        set href(v) { calls.href = v; },
        get href() { return calls.href; },
        origin: 'http://192.168.1.2:5856',
      },
      open: (u) => { calls.open = u; },
    },
    localStorage: { getItem: () => 'TOK123' },
    lightyear: {
      notify: (m, t) => calls.notify.push(m + '|' + t),
      loading: (m) => calls.loading.push(m),
    },
    post: (o) => { calls.post.push(o.url); if (o.error) o.error({ message: 'x' }); },
    encodeURIComponent: encodeURIComponent,
    console,
  };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  ctx.downloadFile();
  return calls;
}

// ---- 断言 ----
let fail = 0;
function check(label, cond, extra) {
  console.log((cond ? 'OK   ' : 'FAIL ') + label + (extra ? '   ' + extra : ''));
  if (!cond) fail++;
}

// 用例1：单选 => 走 /file/，绝不调 /compressFiles
const one = run([makeEl({ checked: true, filePath: '/data/storage/el2/base/haps/entry/files/Docs/abc_1.jpg', name: 'abc_1.jpg' })]);
check('单选：不调 /compressFiles', one.post.length === 0, JSON.stringify(one.post));
check('单选：走 location.href=/file/', !!one.href && one.href.startsWith('/file/'), one.href);
check('单选：URL 带 path 参数', !!one.href && one.href.includes('path=%2Fdata%2Fstorage'), '');
check('单选：URL 带 token', !!one.href && one.href.includes('token=TOK123'), '');
check('单选：URL 带文件名', !!one.href && one.href.startsWith('/file/abc_1.jpg'), '');
check('单选：没有 loading 遮罩（不需要打包）', one.loading.length === 0, JSON.stringify(one.loading));

// 用例2：多选 => 仍走 /compressFiles
const two = run([
  makeEl({ checked: true, filePath: '/d/a.jpg', name: 'a.jpg' }),
  makeEl({ checked: true, filePath: '/d/b.png', name: 'b.png' }),
]);
check('多选：调 /compressFiles', two.post.length === 1 && two.post[0] === '/compressFiles', JSON.stringify(two.post));
check('多选：不走 /file/', two.href === null, String(two.href));
check('多选：有 loading 遮罩', two.loading.includes('show'), JSON.stringify(two.loading));

// 用例3：一个都没勾 => 提示，不发请求
const none = run([makeEl({ checked: false, filePath: '/d/a.jpg', name: 'a.jpg' })]);
check('未勾选：不发请求', none.post.length === 0 && none.href === null, '');
check('未勾选：给提示', none.notify.some(n => n.indexOf('请先勾选') >= 0), JSON.stringify(none.notify));

// 用例4：畸形项（有勾选框但无文件名）=> 必须挡住，不能请求 /file/undefined
const bad = run([makeEl({ checked: true, filePath: '/d/x.jpg', name: '' })]);
check('无文件名：被挡下不发请求', bad.post.length === 0 && bad.href === null, JSON.stringify([bad.post, bad.href]));

console.log('-'.repeat(78));
if (fail) { console.log('FAILED: ' + fail + ' 项不符'); process.exit(1); }
console.log('ALL PASS: 单选直推 / 多选打包 / 空选与畸形项 均符合预期');