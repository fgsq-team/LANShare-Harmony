/**
 * 流式上传 + 响应头 离线对拍验证
 *
 * ## 为什么需要它
 * 这一轮改了两处关键路径，都只能在真机上才能试：
 *   1. `HttpProtocol.encodeHead()` 自动补 Content-Length
 *      —— 网页端「打开要等 15 秒」的根因修复；
 *   2. `service/MultipartStream.ets` 流式 multipart 解析
 *      —— 网页上传的落地实现，直接决定文件字节对不对。
 * 「看起来对」不算数。这里**直接执行交付的 .ets 源文件**，
 * 用真实字节喂进去，把落盘结果读回来逐字节比对。
 *
 * ## 分片是最重要的维度
 * 流式解析器最容易错的地方不是格式，而是**分隔符被切片切开**：
 * 网络分片边界与 `\r\n--boundary` 的边界毫无关系，
 * 所以每个用例都用多种分片宽度各跑一遍（含最恶劣的 1 字节）。
 *
 * 用法：node tests/upload-check/check.mjs
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

/** fileIo：用 Node fs 实现交付代码真正用到的那几个 API */
const FILEKIT_SHIM = `
import * as __fs from 'node:fs';
const fileIo = {
  OpenMode: { READ_ONLY: 0, READ_WRITE: 2, CREATE: 64, TRUNC: 512 },
  openSync(p, mode) {
    const readOnly = (mode === 0);
    return { fd: __fs.openSync(p, readOnly ? 'r' : 'w') };
  },
  writeSync(fd, buf) { return __fs.writeSync(fd, Buffer.from(buf)); },
  readSync(fd, buf) { return __fs.readSync(fd, Buffer.from(buf), 0, buf.byteLength, null); },
  closeSync(fd) { try { __fs.closeSync(fd); } catch (e) {} },
  mkdirSync(p, recursive) { try { __fs.mkdirSync(p, { recursive: !!recursive }); } catch (e) {} },
  accessSync(p) { __fs.accessSync(p); return true; },
  statSync(fd) { const s = __fs.fstatSync(fd); return { size: s.size, isDirectory: () => s.isDirectory() }; },
  listFileSync(p) { return __fs.readdirSync(p); }
};
const Environment = { getUserDownloadDir: () => '' };
`;

/** PermissionGate 只被 FileStorage.init() 用到，测试里不需要，全部桩掉 */
const PERMGATE_SHIM = `
class PermissionGate {
  static supportsUserDownloadDir() { return false; }
  static async ensureDownloadDirDetailed() { return { granted: false, detail: '' }; }
}
`;

const SUBS = [
  [/^\s*import\s*\{\s*hilog\s*\}\s*from\s*'@kit\.PerformanceAnalysisKit';\s*$/gm, HILOG_SHIM],
  [/^\s*import\s*\{\s*util\s*\}\s*from\s*'@kit\.ArkTS';\s*$/gm, ARK_UTIL_SHIM],
  [/^\s*import\s*\{\s*BusinessError\s*\}\s*from\s*'@kit\.BasicServicesKit';\s*$/gm, BIZ_SHIM],
  [/^\s*import\s*\{\s*fileIo,\s*Environment\s*\}\s*from\s*'@kit\.CoreFileKit';\s*$/gm, FILEKIT_SHIM],
  [/^\s*import\s*\{\s*PermissionGate\s*\}\s*from\s*'\.\/PermissionGate';\s*$/gm, PERMGATE_SHIM],
];

const FILES = [
  ['core/Logger.ets', 'core/Logger.ts'],
  ['core/FileTypes.ets', 'core/FileTypes.ts'],
  ['service/FileStorage.ets', 'service/FileStorage.ts'],
  ['service/MultipartStream.ets', 'service/MultipartStream.ts'],
  ['net/HttpProtocol.ets', 'net/HttpProtocol.ts'],
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

// ---------------------------------------------------------------- 被测对象

const { MultipartStream } = await import(pathToFileURL(path.join(BUILD, 'service/MultipartStream.ts')).href);
const { HttpResponse, HttpProtocol } = await import(pathToFileURL(path.join(BUILD, 'net/HttpProtocol.ts')).href);

// ---------------------------------------------------------------- 工具

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail });
}

/** 造一个标准的 multipart body */
function buildMultipart(boundary, files) {
  const parts = [];
  for (const f of files) {
    parts.push(Buffer.from(`--${boundary}\r\n`, 'utf8'));
    parts.push(Buffer.from(
      `Content-Disposition: form-data; name="file"; filename="${f.name}"\r\n`, 'utf8'));
    parts.push(Buffer.from('Content-Type: application/octet-stream\r\n\r\n', 'utf8'));
    parts.push(Buffer.isBuffer(f.data) ? f.data : Buffer.from(f.data, 'utf8'));
    parts.push(Buffer.from('\r\n', 'utf8'));
  }
  parts.push(Buffer.from(`--${boundary}--\r\n`, 'utf8'));
  return Buffer.concat(parts);
}

/** 可辨识的二进制内容（含 CRLF、单个 -、boundary 前缀片段等易错字节） */
function makeData(size, seed = 0) {
  const b = Buffer.alloc(size);
  for (let i = 0; i < size; i++) b[i] = (i * 31 + seed * 17) & 0xff;
  return b;
}

/** 按固定宽度切片，模拟网络分片 */
function sliceFixed(buf, width) {
  const out = [];
  for (let i = 0; i < buf.length; i += width) out.push(buf.subarray(i, Math.min(i + width, buf.length)));
  return out;
}

/**
 * 跑一个解析用例：按 width 切片喂入，返回落盘结果。
 * @returns {{files:Array, err:string, ms:number}}
 */
function runParse(boundary, body, width) {
  const mp = new MultipartStream(boundary, () => OUT);
  const t0 = Date.now();
  for (const c of sliceFixed(body, width)) {
    mp.feed(new Uint8Array(c));
  }
  const files = mp.finish();
  return { files, err: mp.error, ms: Date.now() - t0, bytesIn: mp.bytesIn };
}

/** 落盘文件读回，与期望字节比对 */
function sameAsDisk(file, expect) {
  try {
    const got = fs.readFileSync(file.path);
    if (got.length !== expect.length) return `长度不符 ${got.length} != ${expect.length}`;
    for (let i = 0; i < got.length; i++) {
      if (got[i] !== expect[i]) return `第 ${i} 字节不符: ${got[i]} != ${expect[i]}`;
    }
    return '';
  } catch (e) {
    return `读取失败: ${e.message}`;
  }
}

/** 清空输出目录，避免上一轮的 uniquePathIn 去重干扰 */
function cleanOut() {
  for (const f of fs.readdirSync(OUT)) fs.rmSync(path.join(OUT, f), { recursive: true, force: true });
}

// ---------------------------------------------------------------- A. Content-Length

function testContentLength() {
  {
    const r = HttpResponse.text(200, 'hello');
    const head = new TextDecoder().decode(r.encodeHead());
    check('A1 text 响应自动补 Content-Length',
      /Content-Length: 5\r\n/.test(head), head.replace(/\r\n/g, '\\n'));
  }
  {
    const r = HttpResponse.json(200, '{"a":1}');
    const head = new TextDecoder().decode(r.encodeHead());
    check('A2 json 响应自动补 Content-Length',
      /Content-Length: 7\r\n/.test(head), head.replace(/\r\n/g, '\\n'));
  }
  {
    const r = HttpResponse.of(204);
    const head = new TextDecoder().decode(r.encodeHead());
    check('A3 204 不带 Content-Length',
      !/Content-Length/.test(head), head.replace(/\r\n/g, '\\n'));
  }
  {
    // serveRawFile / downloadFile 自己设了长度，不能被覆盖
    const r = HttpResponse.of(200);
    r.body = new Uint8Array(10);
    r.set('Content-Length', '999');
    const head = new TextDecoder().decode(r.encodeHead());
    check('A4 已显式设置的 Content-Length 不被覆盖',
      /Content-Length: 999\r\n/.test(head), head.replace(/\r\n/g, '\\n'));
  }
  {
    // 空 body 的 200 也必须带长度，否则浏览器同样会卡住
    const r = HttpResponse.text(200, '');
    const head = new TextDecoder().decode(r.encodeHead());
    check('A5 空 body 也补 Content-Length: 0',
      /Content-Length: 0\r\n/.test(head), head.replace(/\r\n/g, '\\n'));
  }
}

// ---------------------------------------------------------------- B. boundary 提取

function testBoundary() {
  const cases = [
    ['multipart/form-data; boundary=----WebKitFormBoundaryABC123', '----WebKitFormBoundaryABC123'],
    ['multipart/form-data; boundary="quoted-bound-42"', 'quoted-bound-42'],
    ['multipart/form-data;boundary=nospace', 'nospace'],
    ['multipart/form-data', ''],
    ['application/json', ''],
  ];
  for (const [ct, want] of cases) {
    const got = MultipartStream.boundaryOf(ct);
    check(`B boundary 提取: ${ct.slice(0, 40)}`, got === want, `got=${JSON.stringify(got)} want=${JSON.stringify(want)}`);
  }
}

// ---------------------------------------------------------------- C. 分片鲁棒性

const BOUND = '----WebKitFormBoundaryProbe123456';

function testSlicing() {
  const data = makeData(300 * 1024); // 300 KiB：远大于任何分片
  const body = buildMultipart(BOUND, [{ name: 'a.bin', data }]);

  // 1 字节是最恶劣的情况：分隔符一定被切开
  const widths = [body.length, 1, 2, 3, 7, 13, 64, 255, 1024, 4096, 65536, 300 * 1024];

  for (const w of widths) {
    cleanOut();
    const r = runParse(BOUND, body, w);
    if (!r.files[0]) {
      check(`C 分片=${w} 能解析出文件`, false, `err=${r.err || '(空)'} files=${r.files.length}`);
      continue;
    }
    const diff = sameAsDisk(r.files[0], data);
    check(`C 分片=${w} 落盘字节与原始一致`, diff === '' && r.files[0].size === data.length,
      diff || `size=${r.files[0].size}/${data.length} name=${r.files[0].name}`);
  }
}

// ---------------------------------------------------------------- D. 多文件 / 文件名 / 边界

function testContents() {
  // 文件名
  cleanOut();
  {
    const data = Buffer.from('hello lanshare', 'utf8');
    const body = buildMultipart(BOUND, [{ name: 'note.txt', data }]);
    const r = runParse(BOUND, body, 5);
    const f = r.files[0];
    check('D1 英文文件名', !!f && f.name === 'note.txt', f ? f.name : r.err);
    check('D1b 内容一致', !!f && sameAsDisk(f, data) === '', f ? sameAsDisk(f, data) : '');
  }

  // 中文文件名（multipart 里是原始 UTF-8 字节）
  cleanOut();
  {
    const data = Buffer.from('中文内容', 'utf8');
    const body = buildMultipart(BOUND, [{ name: '测试文档.txt', data }]);
    const r = runParse(BOUND, body, 9);
    const f = r.files[0];
    check('D2 中文文件名按 UTF-8 解出', !!f && f.name === '测试文档.txt', f ? f.name : r.err);
    check('D2b 中文文件内容一致', !!f && sameAsDisk(f, data) === '');
  }

  // 两个文件
  cleanOut();
  {
    const d1 = makeData(60 * 1024, 1);
    const d2 = makeData(40 * 1024, 2);
    const body = buildMultipart(BOUND, [{ name: 'one.bin', data: d1 }, { name: 'two.bin', data: d2 }]);
    const r = runParse(BOUND, body, 333);
    check('D3 多文件都解析出来', r.files.length === 2, `files=${r.files.length} err=${r.err}`);
    if (r.files.length === 2) {
      check('D3b 第一个文件字节一致', sameAsDisk(r.files[0], d1) === '', sameAsDisk(r.files[0], d1));
      check('D3c 第二个文件字节一致', sameAsDisk(r.files[1], d2) === '', sameAsDisk(r.files[1], d2));
      check('D3d 两个文件互不串包', r.files[0].size === d1.length && r.files[1].size === d2.length,
        `${r.files[0].size}/${r.files[1].size}`);
    }
  }

  // 内容里含易与分隔符混淆的字节序列
  cleanOut();
  {
    const tricky = Buffer.concat([
      Buffer.from('\r\n--not-the-boundary\r\n', 'utf8'),
      Buffer.from('dash-boundary-prefix\r\n--', 'utf8'),
      makeData(8192, 7),
      Buffer.from('\r\n\r\n--WebKit\r\n', 'utf8'),
    ]);
    const body = buildMultipart(BOUND, [{ name: 'tricky.bin', data: tricky }]);
    const r = runParse(BOUND, body, 17);
    const f = r.files[0];
    check('D4 内容含类分隔符字节不被误判', !!f && sameAsDisk(f, tricky) === '',
      f ? sameAsDisk(f, tricky) : r.err);
  }

  // 二进制全 0xFF（含 \r 的邻接字节）
  cleanOut();
  {
    const data = Buffer.alloc(20000, 0xff);
    const body = buildMultipart(BOUND, [{ name: 'ff.bin', data }]);
    const r = runParse(BOUND, body, 64);
    const f = r.files[0];
    check('D5 全 0xFF 二进制内容一致', !!f && sameAsDisk(f, data) === '', f ? sameAsDisk(f, data) : r.err);
  }

  // 0 字节文件
  cleanOut();
  {
    const body = buildMultipart(BOUND, [{ name: 'empty.bin', data: Buffer.alloc(0) }]);
    const r = runParse(BOUND, body, 11);
    const f = r.files[0];
    check('D6 0 字节文件落盘且大小为 0', !!f && f.size === 0, f ? `size=${f.size}` : r.err);
  }

  // 坏包：没有结束 boundary
  cleanOut();
  {
    const full = buildMultipart(BOUND, [{ name: 'x.bin', data: makeData(4096, 3) }]);
    const truncated = full.subarray(0, full.length - 40); // 砍掉结尾
    const r = runParse(BOUND, truncated, 128);
    check('D7 截断的 multipart 被判定为坏包', r.err.length > 0, `err=${JSON.stringify(r.err)}`);
  }

  // 非 multipart（boundary 对不上）
  cleanOut();
  {
    const body = buildMultipart(BOUND, [{ name: 'y.bin', data: makeData(1024, 4) }]);
    const r = runParse('----AnotherBoundary999', body, 256);
    check('D8 boundary 不匹配时不产出文件', r.files.length === 0, `files=${r.files.length} err=${r.err}`);
  }
}

// ---------------------------------------------------------------- E. 吞吐（回归 O(n²)）

function testThroughput() {
  cleanOut();
  const MB = 32;
  const data = makeData(MB * 1024 * 1024);
  const body = buildMultipart(BOUND, [{ name: 'big.bin', data }]);
  // 贴近真机：服务端按 256 KiB 一块读（见 HttpRouter.UPLOAD_CHUNK）
  const r = runParse(BOUND, body, 256 * 1024);
  const f = r.files[0];
  const mbps = (MB / (r.ms / 1000)).toFixed(1);
  console.log(`\n[吞吐] 纯解析 ${MB} MiB / ${r.ms}ms = ${mbps} MiB/s（分片 256 KiB）\n`);
  check(`E ${MB} MiB 流式解析吞吐 ≥ 20 MiB/s（旧实现 0.6 MiB/s）`,
    Number(mbps) >= 20, `${mbps} MiB/s, ${r.ms}ms`);
  check('E2 大文件落盘字节一致', !!f && sameAsDisk(f, data) === '', f ? sameAsDisk(f, data) : r.err);
}

// ---------------------------------------------------------------- run

testContentLength();
testBoundary();
testSlicing();
testContents();
testThroughput();

const pass = results.filter((r) => r.ok).length;
for (const r of results) {
  console.log(`${r.ok ? '[通过]' : '[失败]'} ${r.name}${r.ok ? '' : '   -> ' + r.detail}`);
}
console.log(`\n结果: ${pass}/${results.length}`);
process.exit(pass === results.length ? 0 : 1);
