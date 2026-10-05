/**
 * 本机 -> 网页端（手机发给浏览器）的发送进度，离线对拍验证
 *
 * ## 为什么需要它
 * 上一轮补了「网页 -> 手机」的上传进度，反方向**手机 -> 网页**没有：
 * 手机上推文件给浏览器时浮层一片空白，用户只能看浏览器的下载条。
 * 这一轮补的是**下载方向**的一对回调（`setOnDownloadProgress` / `setOnDownloadEnd`）。
 *
 * 真机验证要靠「手机推文件 + 浏览器开着」两步人工操作，装包前没法点，
 * 所以这里直接执行交付的 `net/HttpRouter.ets`（类型擦除 + 平台 shim），
 * 断言上报的时机与数值。
 *
 * ## 被测契约
 * | 场景 | 期望 |
 * |---|---|
 * | `POST /compressFiles` 打包中 | 上报一次 `total = -1`（不可计量）+ 整句文案，UI 原样显示、不算百分比 |
 * | 打包失败 | 也要回调 `end(ok=false)`，否则浮层永远停在"正在打包…" |
 * | 流式发送开始 | 上报 `sent = 0` |
 * | 流式发送收尾 | 上报 `sent === total`（最后一次节流之后那截不能丢） |
 * | 正常结束 | `end(ok=true, totalBytes=total)` |
 * | 浏览器中途断开 | `end(ok=false)` |
 *
 * 用法：node tests/web-push-progress-check/check.mjs
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../../');
const ETS = path.join(ROOT, 'entry/src/main/ets');
const BUILD = path.join(__dirname, '_build');
const OUT = path.join(__dirname, '_out');

// ---------------------------------------------------------------- shims

const HILOG_SHIM = `
const hilog = { debug() {}, info() {}, warn() {}, error() {} };
`;

const ARK_UTIL_SHIM = `
const util = {
  TextEncoder: class {
    constructor(_e) {}
    encodeInto(s) { return new TextEncoder().encode(s); }
  },
  TextDecoder: class {
    constructor(_e) {}
    decodeToString(u) { return new TextDecoder('utf-8').decode(u); }
  }
};
`;

const BIZ_SHIM = `
class BusinessError extends Error {
  constructor(code, message) { super(message || ''); this.code = code || 0; }
}
`;

/** zlib：记录调用参数并落一个占位 zip —— 我们验证的是「传给它什么、返回什么」，不是压缩算法本身 */
const ZLIB_SHIM = `
globalThis.__ZLIB_CALLS = [];
const zlib = {
  async compressFiles(inFiles, outFile, options) {
    globalThis.__ZLIB_CALLS.push({ inFiles: inFiles.slice(), outFile, options });
    // 用例 1.5/1.6 要验证「打包失败也要回调结束」，用这个开关让 shim 抛错
    if (globalThis.__ZLIB_FAIL) { throw new Error('shim: compress failed'); }
    globalThis.__NODE_FS.writeFileSync(outFile, Buffer.from('PK\\x03\\x04-shim'));
  }
};
`;

/** fileIo：statSync 要同时吃路径和 fd（两侧调用方式不同） */
const FILEKIT_SHIM = `
import * as __fs from 'node:fs';
const fileIo = {
  OpenMode: { READ_ONLY: 0, WRITE_ONLY: 1, READ_WRITE: 2, CREATE: 64, TRUNC: 512, APPEND: 1024 },
  openSync(p, mode) {
    const m = (mode === 0) ? 'r' : ((mode & 512) ? 'w' : 'a');
    return { fd: __fs.openSync(p, m) };
  },
  writeSync(fd, buf) { return __fs.writeSync(fd, Buffer.from(buf)); },
  readSync(fd, buf) { return __fs.readSync(fd, Buffer.from(buf), 0, buf.byteLength, null); },
  closeSync(f) { try { __fs.closeSync(typeof f === 'number' ? f : f.fd); } catch (e) {} },
  mkdirSync(p, recursive) { try { __fs.mkdirSync(p, { recursive: !!recursive }); } catch (e) {} },
  // ⚠️ 真机 fileIo.accessSync 返回 boolean；Node 的 accessSync 是不存在就抛。
  //    不接住的话交付代码里 "if (!fileIo.accessSync(dir))" 会直接抛到 catch，
  //    表现成"临时目录不可用"，与真实行为完全相反。
  accessSync(p) { try { __fs.accessSync(p); return true; } catch (e) { return false; } },
  unlinkSync(p) { __fs.unlinkSync(p); },
  listFileSync(p) { return __fs.readdirSync(p); },
  statSync(p) {
    const s = (typeof p === 'number') ? __fs.fstatSync(p) : __fs.statSync(p);
    return {
      size: s.size,
      mtime: Math.floor(s.mtimeMs / 1000),
      isDirectory: () => s.isDirectory(),
      isFile: () => s.isFile()
    };
  }
};
const Environment = { getUserDownloadDir: () => '' };
`;

/** preferences：白名单存储，测试里只需要能读能写 */
const PREFS_SHIM = `
const __mem = new Map();
const preferences = {
  async getPreferences(_ctx, name) {
    if (!__mem.has(name)) { __mem.set(name, new Map()); }
    const m = __mem.get(name);
    return {
      async get(k, d) { return m.has(k) ? m.get(k) : d; },
      async put(k, v) { m.set(k, v); },
      async flush() {}
    };
  }
};
`;

const PERMGATE_SHIM = `
class PermissionGate {
  static supportsUserDownloadDir() { return false; }
  static async ensureDownloadDirDetailed() { return { granted: false, detail: '' }; }
}
`;

/** NativeSocket 只被 HttpRouter 当类型用，这里给个空壳避免拖进整张网络栈 */
const NATIVESOCKET_SHIM = `
class TcpChannel {
  remoteIp = '';
  isClosed = false;
  async send() { return true; }
  async readExactly() { return null; }
  close() {}
}
`;

const CRYPTO_SHIM = `
const cryptoFramework = {
  createMd() {
    return { update() {}, digestSync() { return { data: new Uint8Array(20) }; } };
  }
};
`;

const SUBS = [
  [/^\s*import\s*\{\s*hilog\s*\}\s*from\s*'@kit\.PerformanceAnalysisKit';\s*$/gm, HILOG_SHIM],
  [/^\s*import\s*\{\s*util\s*\}\s*from\s*'@kit\.ArkTS';\s*$/gm, ARK_UTIL_SHIM],
  [/^\s*import\s*\{\s*BusinessError,\s*common\s*\}\s*from\s*'@kit\.AbilityKit';\s*$/gm, BIZ_SHIM],
  [/^\s*import\s*\{\s*BusinessError\s*\}\s*from\s*'@kit\.BasicServicesKit';\s*$/gm, BIZ_SHIM],
  [/^\s*import\s*\{\s*BusinessError,\s*zlib\s*\}\s*from\s*'@kit\.BasicServicesKit';\s*$/gm, BIZ_SHIM + ZLIB_SHIM],
  [/^\s*import\s*\{\s*fileIo\s*\}\s*from\s*'@kit\.CoreFileKit';\s*$/gm, FILEKIT_SHIM],
  [/^\s*import\s*\{\s*fileIo,\s*Environment\s*\}\s*from\s*'@kit\.CoreFileKit';\s*$/gm, FILEKIT_SHIM],
  [/^\s*import\s*\{\s*preferences\s*\}\s*from\s*'@kit\.ArkData';\s*$/gm, PREFS_SHIM],
  [/^\s*import\s*\{\s*common\s*\}\s*from\s*'@kit\.AbilityKit';\s*$/gm, 'const common = {};'],
  [/^\s*import\s*\{\s*abilityAccessCtrl,\s*common,\s*Permissions,\s*PermissionRequestResult\s*\}\s*from\s*'@kit\.AbilityKit';\s*$/gm, 'const abilityAccessCtrl = {}; const common = {};'],
  [/^\s*import\s*\{\s*PermissionGate\s*\}\s*from\s*'\.\/PermissionGate';\s*$/gm, PERMGATE_SHIM],
  [/^\s*import\s*\{\s*TcpChannel\s*\}\s*from\s*'\.\/NativeSocket';\s*$/gm, NATIVESOCKET_SHIM],
  [/^\s*import\s*\{\s*cryptoFramework\s*\}\s*from\s*'@kit\.CryptoArchitectureKit';\s*$/gm, CRYPTO_SHIM],
];

const FILES = [
  ['core/Logger.ets', 'core/Logger.ts'],
  ['core/MiniJson.ets', 'core/MiniJson.ts'],
  ['core/LanConfig.ets', 'core/LanConfig.ts'],
  ['core/FileTypes.ets', 'core/FileTypes.ts'],
  ['service/FileStorage.ets', 'service/FileStorage.ts'],
  ['service/WebClientStore.ets', 'service/WebClientStore.ts'],
  ['service/MultipartStream.ets', 'service/MultipartStream.ts'],
  ['net/HttpProtocol.ets', 'net/HttpProtocol.ts'],
  ['net/WsProtocol.ets', 'net/WsProtocol.ts'],
  ['net/HttpRouter.ets', 'net/HttpRouter.ts'],
];

fs.rmSync(BUILD, { recursive: true, force: true });
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

for (const [src, dst] of FILES) {
  let s = fs.readFileSync(path.join(ETS, src), 'utf8');
  for (const [re, rep] of SUBS) s = s.replace(re, rep);
  s = s.replace(/from\s*'(\.\.?\/[^']+)'/g, (_m, p1) => `from '${p1}.ts'`);
  const out = path.join(BUILD, dst);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, s);
}

// zlib shim 通过 globalThis 拿 fs（ESM 里没有 require）
globalThis.__NODE_FS = fs;

const { HttpRouter } = await import(pathToFileURL(path.join(BUILD, 'net/HttpRouter.ts')).href);
// ---------------------------------------------------------------- 脚手架

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail });
}

// ⚠️ 用正斜杠：真机 filesDir/cacheDir 是 `/data/...`，交付代码也是用 `/` 拼路径的。
const SANDBOX = path.join(OUT, 'files').split(path.sep).join('/');
const CACHE = path.join(OUT, 'cache').split(path.sep).join('/');
fs.mkdirSync(path.join(SANDBOX, 'LANShare'), { recursive: true });
fs.mkdirSync(CACHE, { recursive: true });

const router = new HttpRouter();
router.setContext({ filesDir: SANDBOX, cacheDir: CACHE });

/** 只带 body / query / header 的请求壳 */
function req(opts) {
  const query = opts.query || {};
  return {
    method: opts.method || 'POST',
    path: opts.path || '/',
    body: new TextEncoder().encode(opts.body || ''),
    queryParam: (k) => (query[k] === undefined ? '' : String(query[k])),
    header: (k) => ((opts.headers || {})[k.toLowerCase()] || ''),
  };
}

/** 假的 TCP 通道：只统计发过多少字节，可模拟中途断开 */
function fakeChannel(breakAfter) {
  return {
    remoteIp: '192.168.10.9',
    isClosed: false,
    sent: 0,
    async send(chunk) {
      this.sent += chunk.length;
      if (breakAfter !== undefined && this.sent >= breakAfter) {
        this.isClosed = true;
      }
      return true;
    },
    async readExactly() { return null; },
    close() {}
  };
}

// ---------------------------------------------------------------- 用例 1：打包阶段

const A = SANDBOX + '/LANShare/a.txt';
fs.writeFileSync(A, 'x'.repeat(4096));

let progress = [];
let ends = [];
router.setOnDownloadProgress((sent, total, name) => {
  progress.push({ sent, total, name });
});
router.setOnDownloadEnd((ok, name, bytes, error) => {
  ends.push({ ok, name, bytes, error });
});

const packed = await router.compressFiles(req({ body: JSON.stringify({ list: [A] }) }));
const tempFile = JSON.parse(new TextDecoder().decode(packed.body)).tempFile;

check('1.1 打包阶段会上报进度', progress.length > 0, JSON.stringify(progress));
check('1.2 打包阶段 total = -1（没有可计量的总量）',
  progress.length > 0 && progress[0].total === -1, JSON.stringify(progress[0]));
check('1.3 打包阶段的 name 是整句文案（含"打包"）',
  progress.length > 0 && progress[0].name.indexOf('打包') >= 0,
  JSON.stringify(progress[0]).slice(0, 120));
check('1.4 打包完上报"等待网页下载"，仍不是百分比',
  progress.length >= 2 && progress[progress.length - 1].total === -1
  && progress[progress.length - 1].name.indexOf('等待') >= 0,
  JSON.stringify(progress[progress.length - 1]));

// 打包失败：必须回调 end(ok=false)，否则浮层永远停在"正在打包…"
progress = [];
ends = [];
globalThis.__ZLIB_FAIL = true;
const bad = await router.compressFiles(req({ body: JSON.stringify({ list: [A] }) }));
check('1.5 打包失败返回 500', bad.status === 500, 'status=' + bad.status);
check('1.6 打包失败也要回调结束（否则浮层停在"正在打包…"）',
  ends.length === 1 && ends[0].ok === false, JSON.stringify(ends));
globalThis.__ZLIB_FAIL = false;

// ---------------------------------------------------------------- 用例 2：流式发送

const zipResp = router.serveZip(req({ method: 'GET', query: { tempFile } }));
const total = zipResp.streamFile.chunkSize;
check('2.0 取到 zip 的流式体', total > 0, 'total=' + total);

progress = [];
ends = [];
let ch = fakeChannel();
const okSend = await router.sendFileRange(ch, zipResp.streamFile);

check('2.1 发送成功', okSend === true);
check('2.2 起始上报 sent = 0', progress.length > 0 && progress[0].sent === 0,
  JSON.stringify(progress[0]));
check('2.3 收尾上报 sent === total（最后一次节流之后那截不能丢）',
  progress[progress.length - 1].sent === total,
  JSON.stringify(progress[progress.length - 1]));
check('2.4 进度里的 total 一致（UI 才算得出百分比）',
  progress.every((p) => p.total === -1 || p.total === total), JSON.stringify(progress));
check('2.5 通道真的收到了全部字节', ch.sent === total,
  'sent=' + ch.sent + ' total=' + total);
check('2.6 结束回调 ok=true 且带上总字节',
  ends.length === 1 && ends[0].ok === true && ends[0].bytes === total, JSON.stringify(ends));

// 浏览器中途取消：必须回调 end(ok=false)，否则浮层永远停在某个百分比
progress = [];
ends = [];
ch = fakeChannel(1); // 收到第一块就"断开"
const cutSpec = router.serveZip(req({ method: 'GET', query: { tempFile } })).streamFile;
const cutSend = await router.sendFileRange(ch, cutSpec);
check('2.7 中途断开时 sendFileRange 返回 false', cutSend === false, 'ret=' + cutSend);
check('2.8 中途断开也要回调结束（浮层才会被收掉）',
  ends.length === 1 && ends[0].ok === false, JSON.stringify(ends));

// ---------------------------------------------------------------- 汇总

const pass = results.filter((r) => r.ok).length;
console.log('\n本机 -> 网页端发送进度 离线对拍：' + pass + '/' + results.length + '\n');
for (const r of results) {
  const line = (r.ok ? '  PASS  ' : '  FAIL  ') + r.name + (r.ok ? '' : '   -- ' + r.detail);
  console.log(line);
}
console.log('');
process.exit(pass === results.length ? 0 : 1);
