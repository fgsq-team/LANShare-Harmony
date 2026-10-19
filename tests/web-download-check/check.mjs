/**
 * 网页端「下载文件」（打包下载）离线对拍验证
 *
 * ## 为什么需要它
 * 网页端的「下载文件」按钮一直在（js/lanshare.min.js 的 downloadFiles），
 * 但服务端只有 `/file/` 单文件下载，`/compressFiles` 与 `/downloadZipFile`
 * 从来没实现 —— 点下去必然「文件打包失败」。这一轮把两个接口补齐，
 * 顺带修了「list[0] 被当成返回上一级」的旧错位。
 *
 * 这些都是**服务端行为**，装到手机之前没法点，所以这里直接执行交付的
 * `net/HttpRouter.ets`（类型擦除 + 平台 shim），用真实目录/文件喂进去断言结果。
 *
 * ## 被测契约（从 js/lanshare.min.js 提取，不是猜的）
 * | 前端调用 | 契约 |
 * |---|---|
 * | `post("/compressFiles", {list:[绝对路径]})` | 成功必须返回 `{"tempFile":"<名字>"}` |
 * | 紧接着 `location.href = "/downloadZipFile?tempFile=" + a.tempFile` | GET，必须真的吐出 zip 字节 |
 * | `post("/files", {path, isBack})` 渲染列表 | `list[0]` 无勾选框、点击按 isBack=true 走 —— 服务端必须补一条「返回上一级」 |
 *
 * 用法：node tests/web-download-check/check.mjs
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
//    若这里用 path.join（Windows 下是反斜杠），resolveSafePath 的前缀判断会全部失配，
//    于是一批用例假 FAIL —— 失败原因是测试环境，不是代码。Node 的 fs 认正斜杠，可以直接用。
const SANDBOX = path.join(OUT, 'files').split(path.sep).join('/');
const CACHE = path.join(OUT, 'cache').split(path.sep).join('/');
fs.mkdirSync(path.join(SANDBOX, 'LANShare', '文档'), { recursive: true });
fs.mkdirSync(CACHE, { recursive: true });

const router = new HttpRouter();
router.setContext({ filesDir: SANDBOX, cacheDir: CACHE });

/** 造一个只带 body / query / header 的请求壳（类型擦除后不校验真实类型） */
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

function respText(r) {
  return new TextDecoder().decode(r.body);
}

// ---------------------------------------------------------------- 用例 1：路径清单解析

const A = `${SANDBOX}/LANShare/a.txt`;
const B = `${SANDBOX}/LANShare/文档/b.pdf`;
fs.writeFileSync(A, 'hello a');
fs.writeFileSync(B, 'hello b');

check('1.1 解析 {"list":[...]} 得到两条路径',
  HttpRouter.parsePathList(new TextEncoder().encode(JSON.stringify({ list: [A, B] }))).length === 2,
  JSON.stringify(HttpRouter.parsePathList(new TextEncoder().encode(JSON.stringify({ list: [A, B] })))));

check('1.2 空 body -> 空清单',
  HttpRouter.parsePathList(new Uint8Array(0)).length === 0);

check('1.3 list 不是数组 -> 空清单',
  HttpRouter.parsePathList(new TextEncoder().encode('{"list":"x"}')).length === 0);

check('1.4 非字符串元素被转成字符串（数字 -> "1"，后面由安全校验拦掉）',
  JSON.stringify(HttpRouter.parsePathList(new TextEncoder().encode('{"list":[1,2,3]}'))) === '["1","2","3"]',
  JSON.stringify(HttpRouter.parsePathList(new TextEncoder().encode('{"list":[1,2,3]}'))));

// ---------------------------------------------------------------- 用例 2：打包（/compressFiles）

globalThis.__ZLIB_CALLS = [];
const mixed = await router.compressFiles(req({
  body: JSON.stringify({ list: [A, B, '/system/bin/sh', `${SANDBOX}/../secret.txt`, '/nope/missing.txt'] })
}));

check('2.1 打包成功返回 200', mixed.status === 200, `status=${mixed.status} ${respText(mixed)}`);

let tempFile = '';
try {
  tempFile = JSON.parse(respText(mixed)).tempFile;
} catch (e) {
  tempFile = '';
}
check('2.2 响应里必须有 tempFile（网页端靠这个字段发起第二步）', tempFile.length > 0, respText(mixed));

const calls = globalThis.__ZLIB_CALLS;
check('2.3 只把沙箱内的 2 个真实文件交给 zlib',
  calls.length === 1 && calls[0].inFiles.length === 2,
  JSON.stringify(calls.map((c) => c.inFiles)));

check('2.4 越界路径（/system/bin/sh、".."、不存在）全部被过滤掉',
  calls.length === 1 && calls[0].inFiles.every((p) => p === A || p === B),
  JSON.stringify(calls.map((c) => c.inFiles)));

check('2.5 输出文件落在 cacheDir 下的临时目录',
  calls.length === 1 && calls[0].outFile.startsWith(`${CACHE}/webzip`),
  calls.length ? calls[0].outFile : '(未调用)');

check('2.6 tempFile 是纯文件名（不含目录分隔符）',
  tempFile.length > 0 && !tempFile.includes('/') && !tempFile.includes('\\'),
  tempFile);

// 全部非法 -> 400，不能返回一个空 zip
const allBad = await router.compressFiles(req({ body: JSON.stringify({ list: ['/etc/passwd'] }) }));
check('2.7 全部路径越界 -> 400 且不调用 zlib',
  allBad.status === 400 && globalThis.__ZLIB_CALLS.length === 1,
  `status=${allBad.status} ${respText(allBad)}`);

const noPick = await router.compressFiles(req({ body: JSON.stringify({ list: [] }) }));
check('2.8 空清单 -> 400（提示勾选）', noPick.status === 400, respText(noPick));

// ---------------------------------------------------------------- 用例 3：取 zip（/downloadZipFile）

const zipName = tempFile;
const good = router.serveZip(req({ method: 'GET', query: { tempFile: zipName } }));
check('3.1 合法 tempFile -> 200', good.status === 200, `status=${good.status} ${respText(good)}`);
check('3.2 Content-Type 是 zip', good.headers.get('Content-Type') === 'application/zip');
check('3.3 带 Content-Disposition 附件头', (good.headers.get('Content-Disposition') || '').startsWith('attachment'));
check('3.4 设置了流式体（大文件不进内存）', good.streamFile !== null && good.streamFile !== undefined);

for (const bad of ['../../../etc/passwd', 'a/b.zip', '..', '']) {
  const r = router.serveZip(req({ method: 'GET', query: { tempFile: bad } }));
  const ok = bad === '' ? r.status === 400 : r.status === 400;
  check(`3.5 tempFile="${bad}" 被拒绝（防目录穿越）`, ok, `status=${r.status}`);
}

const missing = router.serveZip(req({ method: 'GET', query: { tempFile: 'no-such-file.zip' } }));
check('3.6 不存在的 tempFile -> 404', missing.status === 404, `status=${missing.status}`);

// ---------------------------------------------------------------- 用例 4：文件列表的「返回上一级」

const rootList = await router.listFiles(req({ body: JSON.stringify({ path: '' }) }));
const rootJson = JSON.parse(respText(rootList));
check('4.1 list[0] 是「返回上一级」', rootJson.list[0].name === '返回上一级',
  JSON.stringify(rootJson.list[0]));
// ⚠️ 交付代码一律用 `/` 拼路径，而 path.join 在 Windows 上给的是 `\`。
//    这里统一成正斜杠再比，否则 Windows 上会出现一批假的 FAIL。
const ROOT_DIR = `${SANDBOX}/LANShare`;

check('4.2 list[0].path 指向当前目录（点了才回得去上一级）',
  rootJson.list[0].path === ROOT_DIR,
  rootJson.list[0].path);
check('4.3 list[0] 之后才是真实条目（真实条目才带勾选框，才能下载）',
  rootJson.list.length >= 2 && rootJson.list[1].isDirectory === true,
  JSON.stringify(rootJson.list.slice(1)));

const backAtRoot = await router.listFiles(req({ body: JSON.stringify({ path: ROOT_DIR, isBack: 'true' }) }));
const backJson = JSON.parse(respText(backAtRoot));
check('4.4 在根目录再点「返回上一级」不会退到沙箱外',
  backJson.path === ROOT_DIR,
  backJson.path);

// ---------------------------------------------------------------- 汇总

const pass = results.filter((r) => r.ok).length;
console.log(`\n网页端打包下载 离线对拍：${pass}/${results.length}\n`);
for (const r of results) {
  console.log(`${r.ok ? '  PASS' : '  FAIL'}  ${r.name}${r.ok ? '' : `   -- ${r.detail}`}`);
}
console.log('');
process.exit(pass === results.length ? 0 : 1);
