/**
 * 网页 → 手机 上传链路离线对拍验证（进度上报 + 主线程让出 + 结束回调）
 *
 * ## 为什么需要它
 * 用户反馈两条（vivi 2026-09-30）：
 *   1. 网页发文件给手机，**手机上没有进度条**；
 *   2. 上传期间**鸿蒙端按钮点了没反应**。
 *
 * 根因是服务端 `serveUpload` 一直在「闷头收」：
 *   - 完全没有进度出口 → UI 无从显示；
 *   - ArkTS 是单线程，socket 回调里的 read → 扫描 → 同步写盘循环不主动让出，
 *     ArkUI 拿不到帧时间 → 看起来就是"卡死"。
 * 修法是加**节流进度回调** + **每 8 块 await setTimeout(0)**。
 *
 * 这些是纯服务端行为且跨线程/跨帧，装到手机之前没法点，所以这里直接执行交付的
 * `net/HttpRouter.ets`（类型擦除 + 平台 shim），用真实的 multipart 字节流喂进去，
 * 断言「回调被怎么调用」，而不是断言压缩或网络。
 *
 * ## 被测契约（不是猜的）
 * | 契约 | 为什么 |
 * |---|---|
 * | 进度回调次数 << 块数 | 每块都回调 = UI 每帧重建 = 按钮点不动 |
 * | 结束回调**成功和失败都要来** | 只回调成功的话，断线时浮层永远停在某个百分比 |
 * | 最后一次进度必须到 100% | 节流会吞掉最后一截，不补一次就永远停在 9x% |
 * | 上传期间要 await 让出 | 不让出 UI 就没有帧时间（本测试只验证不破坏正确性） |
 *
 * 用法：node tests/web-upload-check/check.mjs
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
// ⚠️ common 只能声明一次：HttpRouter 里 `{ BusinessError, common }` 与 `{ common }`
// 两种 import 都存在，若两条替换规则都输出 `const common = {}` 会直接 SyntaxError。
const BIZ_COMMON_SHIM = BIZ_SHIM + '\nconst common = {};';

const ZLIB_SHIM = `
globalThis.__ZLIB_CALLS = [];
const zlib = {
  async compressFiles(inFiles, outFile, options) {
    globalThis.__ZLIB_CALLS.push({ inFiles: inFiles.slice(), outFile, options });
    globalThis.__NODE_FS.writeFileSync(outFile, Buffer.from('PK\\x03\\x04-shim'));
  }
};
`;

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

/**
 * TcpChannel：这次要真的「读数据」，所以 readSome 是从预设块里往外吐。
 * 每吐一块 sleep 一小会儿 —— 真实网络不会瞬间给完所有字节，
 * 不 sleep 的话进度节流测出来的次数会是 1，看不出"节流"这件事。
 */
const NATIVESOCKET_SHIM = `
const __sleep = (ms) => new Promise((r) => setTimeout(r, ms));
class TcpChannel {
  constructor() {
    this.remoteIp = '127.0.0.1';
    this.isClosed = false;
    this.chunks = (globalThis.__UP_CHUNKS || []).slice();
    this.i = 0;
    globalThis.__UP_CHANNEL = this;
  }
  async send() { return true; }
  async readExactly() { return null; }
  async readSome(n, ms) {
    if (this.i >= this.chunks.length) { return null; }
    const c = this.chunks[this.i++];
    await __sleep(globalThis.__UP_CHUNK_DELAY || 0);
    return c;
  }
  close() { this.isClosed = true; }
}
// HttpRouter 模块作用域里的 TcpChannel 没导出，用它给测试造实例
globalThis.__NEW_CHANNEL = () => new TcpChannel();
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
  [/^\s*import\s*\{\s*BusinessError,\s*common\s*\}\s*from\s*'@kit\.AbilityKit';\s*$/gm, BIZ_COMMON_SHIM],
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

globalThis.__NODE_FS = fs;

const { HttpRouter } = await import(pathToFileURL(path.join(BUILD, 'net/HttpRouter.ts')).href);
const { FileStorage } = await import(pathToFileURL(path.join(BUILD, 'service/FileStorage.ts')).href);

// ---------------------------------------------------------------- 脚手架

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail });
}

// 正斜杠：真机 filesDir 是 /data/...，交付代码也是用 / 拼路径的（Windows 反斜杠会全部失配）
const SANDBOX = path.join(OUT, 'files').split(path.sep).join('/');
const CACHE = path.join(OUT, 'cache').split(path.sep).join('/');
fs.mkdirSync(SANDBOX, { recursive: true });
fs.mkdirSync(CACHE, { recursive: true });

const storage = new FileStorage();
storage.init(`${SANDBOX}/LANShare`);

const router = new HttpRouter();
router.setContext({ filesDir: SANDBOX, cacheDir: CACHE });
router.setStorage(storage);

/** 造 multipart/form-data 请求体（单文件） */
function multipart(boundary, fileName, content) {
  const head =
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="file"; filename="${fileName}"\r\n` +
    `Content-Type: application/octet-stream\r\n\r\n`;
  const tail = `\r\n--${boundary}--\r\n`;
  const body = Buffer.concat([Buffer.from(head, 'utf8'), Buffer.from(content), Buffer.from(tail, 'utf8')]);
  return body;
}

/** 把 body 切成 n 块 */
function chunkize(buf, n) {
  const per = Math.ceil(buf.length / n);
  const out = [];
  for (let i = 0; i < buf.length; i += per) {
    out.push(new Uint8Array(buf.subarray(i, Math.min(i + per, buf.length))));
  }
  return out;
}

function req(opts) {
  const query = opts.query || {};
  return {
    method: opts.method || 'POST',
    path: opts.path || '/uploadFile',
    body: new TextEncoder().encode(opts.body || ''),
    queryParam: (k) => (query[k] === undefined ? '' : String(query[k])),
    header: (k) => ((opts.headers || {})[k.toLowerCase()] || ''),
  };
}

// ---------------------------------------------------------------- 用例 1：正常上传

const BOUND = '----LsUploadBoundary9x';
const CONTENT = Buffer.alloc(200 * 1024, 0x41);   // 200 KiB 的 'A'
const BODY = multipart(BOUND, '上传测试.txt', CONTENT);
const NCHUNK = 40;

globalThis.__UP_CHUNKS = chunkize(BODY, NCHUNK);
globalThis.__UP_CHUNK_DELAY = 12;                  // 40 × 12ms ≈ 480ms，够触发 2~3 次节流上报

const progress = [];
const ends = [];
router.setOnUploadProgress((received, total, name) => {
  progress.push({ received, total, name });
});
router.setOnUploadEnd((ok, names, totalBytes, error) => {
  ends.push({ ok, names, totalBytes, error });
});

const resp1 = await router.serveUpload(
  req({
    path: '/uploadFile',
    headers: { 'content-type': `multipart/form-data; boundary=${BOUND}` },
  }),
  globalThis.__NEW_CHANNEL(),
  new Uint8Array(0),
  BODY.length
);

const respText = new TextDecoder().decode(resp1.body);
check('1.1 上传返回 200', resp1.status === 200, `status=${resp1.status} body=${respText}`);

check('1.2 结束回调只来一次且是成功',
  ends.length === 1 && ends[0].ok === true,
  JSON.stringify(ends));

check('1.3 结束回调带回文件名与字节数',
  ends.length === 1 && ends[0].names.length === 1 && ends[0].names[0] === '上传测试.txt' &&
  ends[0].totalBytes === CONTENT.length,
  JSON.stringify(ends[0] || {}));

// 节流的核心断言：块数是 40，回调次数必须远小于它。
// 不节流的话这里会是 40（= UI 每帧重建一次，用户点什么都没反馈）。
check('1.4 进度回调被节流（次数远小于块数 40）',
  progress.length >= 1 && progress.length <= 8,
  `回调 ${progress.length} 次 / 共 ${NCHUNK} 块`);

check('1.5 第一次上报是 0%（起点要有反馈，不能等半天才有第一条）',
  progress.length > 0 && progress[0].received === 0,
  JSON.stringify(progress[0] || {}));

const last = progress[progress.length - 1];
check('1.6 最后一次上报收尾到 100%（节流不能吞掉最后一截）',
  progress.length > 0 && last.received === last.total && last.total === BODY.length,
  JSON.stringify(last || {}));

check('1.7 进度里带上了当前文件名（浮层要显示"传的是什么"）',
  progress.length > 0 && last.name === '上传测试.txt',
  JSON.stringify(last || {}));

// 落盘校验：文件必须在 saveRoot 下，且内容与原始字节一致
const savedPath = findSaved();
function findSaved() {
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) {
        const r = walk(p);
        if (r) return r;
      } else if (e.name.includes('上传测试')) {
        return p;
      }
    }
    return null;
  };
  return walk(`${SANDBOX}/LANShare`);
}
check('1.8 文件真的落盘到沙箱的接收根目录',
  !!savedPath && savedPath.split(path.sep).join('/').startsWith(`${SANDBOX}/LANShare`),
  savedPath || '(未找到)');
check('1.9 落盘内容与上传字节完全一致',
  !!savedPath && fs.readFileSync(savedPath).equals(CONTENT),
  savedPath ? `size=${fs.statSync(savedPath).size} expect=${CONTENT.length}` : '(未找到)');

// ---------------------------------------------------------------- 用例 2：中途断开

progress.length = 0;
ends.length = 0;
const HALF = chunkize(BODY, 40).slice(0, 6);       // 只给前 6 块就"断线"
globalThis.__UP_CHUNKS = HALF;
globalThis.__UP_CHUNK_DELAY = 0;

const resp2 = await router.serveUpload(
  req({
    path: '/uploadFile',
    headers: { 'content-type': `multipart/form-data; boundary=${BOUND}` },
  }),
  globalThis.__NEW_CHANNEL(),
  new Uint8Array(0),
  BODY.length
);

check('2.1 中途断开时返回非 200', resp2.status >= 400, `status=${resp2.status}`);
check('2.2 失败也会回调结束接口（否则浮层永远停在某个百分比）',
  ends.length === 1 && ends[0].ok === false && ends[0].error.length > 0,
  JSON.stringify(ends));

// ---------------------------------------------------------------- 用例 3：不是 multipart

progress.length = 0;
ends.length = 0;
globalThis.__UP_CHUNKS = [];
const resp3 = await router.serveUpload(
  req({ path: '/uploadFile', headers: { 'content-type': 'application/json' } }),
  globalThis.__NEW_CHANNEL(),
  new Uint8Array(0),
  0
);
check('3.1 缺少 boundary -> 400', resp3.status === 400, `status=${resp3.status}`);
check('3.2 缺少 boundary 也要回调结束（UI 那边才能收掉浮层）',
  ends.length === 1 && ends[0].ok === false,
  JSON.stringify(ends));

// ---------------------------------------------------------------- 汇总

let pass = 0;
for (const r of results) {
  if (r.ok) {
    pass += 1;
  }
  console.log(`${r.ok ? '  ok  ' : ' FAIL '} ${r.name}${r.detail ? '  → ' + r.detail : ''}`);
}
console.log(`\n${pass}/${results.length} passed`);
process.exit(pass === results.length ? 0 : 1);
