/**
 * WebSocket 会话层离线验证
 *
 * ## 为什么需要它
 * 新写的 `service/WebSocketSession.ets` 是网页端能不能用的关键路径，
 * 而它要到真机上装了 HAP 才能试。「看起来对」不算数 —— 这里直接
 * **执行交付的 .ets 源文件**，用假的通道喂真实字节，看会话层能不能正确解出来。
 *
 * 做法沿用 tests/protocol-bytecheck 的思路：
 *   1. 读真实的 entry/src/main/ets/**\/*.ets
 *   2. 只替换平台模块导入（换成等价 shim）+ 相对导入补 .ts
 *   3. 交给 Node 22 原生类型擦除执行 —— 擦除后即 ArkTS 的真实运行语义
 *
 * 用法：node tests/ws-session-check/check.mjs
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../../');
const ETS = path.join(ROOT, 'entry/src/main/ets');
const BUILD = path.join(__dirname, '_wsbuild');

// ---------------------------------------------------------------- shims

const HILOG_SHIM = `
const hilog = {
  debug() {}, info() {}, warn() {}, error() {}
};
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
  },
  Base64Helper: class {
    encodeToStringSync(u8) { return Buffer.from(u8).toString('base64'); }
  }
};
`;

const NET_SHIM = `
const socket = {};
`;

const BIZ_SHIM = `
class BusinessError extends Error {
  constructor(code, message) { super(message || ''); this.code = code || 0; }
}
`;

const CRYPTO_SHIM = `
const cryptoFramework = {};
`;

const SUBS = [
  [/^\s*import\s*\{\s*hilog\s*\}\s*from\s*'@kit\.PerformanceAnalysisKit';\s*$/gm, HILOG_SHIM],
  [/^\s*import\s*\{\s*util\s*\}\s*from\s*'@kit\.ArkTS';\s*$/gm, ARK_UTIL_SHIM],
  [/^\s*import\s*\{\s*socket\s*\}\s*from\s*'@kit\.NetworkKit';\s*$/gm, NET_SHIM],
  [/^\s*import\s*\{\s*BusinessError\s*\}\s*from\s*'@kit\.BasicServicesKit';\s*$/gm, BIZ_SHIM],
  [/^\s*import\s*\{\s*cryptoFramework\s*\}\s*from\s*'@kit\.CryptoArchitectureKit';\s*$/gm, CRYPTO_SHIM],
];

const FILES = [
  ['core/Logger.ets', 'core/Logger.ts'],
  ['net/WsProtocol.ets', 'net/WsProtocol.ts'],
  ['net/NativeSocket.ets', 'net/NativeSocket.ts'],
  ['service/WebSocketSession.ets', 'service/WebSocketSession.ts'],
];

fs.rmSync(BUILD, { recursive: true, force: true });
for (const [src, dst] of FILES) {
  let s = fs.readFileSync(path.join(ETS, src), 'utf8');
  for (const [re, rep] of SUBS) s = s.replace(re, rep);
  // 相对导入补扩展名（Node ESM 要求显式）
  s = s.replace(/from\s*'(\.\.?\/[^']+)'/g, (_m, p1) => `from '${p1}.ts'`);
  const out = path.join(BUILD, dst);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, s);
}

// ---------------------------------------------------------------- 被测对象

const mod = await import(pathToFileURL(path.join(BUILD, 'service/WebSocketSession.ts')).href);
const { WebSocketSession } = mod;

// ---------------------------------------------------------------- 工具

const OP = { CONT: 0x0, TEXT: 0x1, BIN: 0x2, CLOSE: 0x8, PING: 0x9, PONG: 0xa };

/** 造一个客户端 -> 服务端的帧（必须带掩码，这是 RFC 6455 的要求） */
function clientFrame(opcode, payload, fin = true) {
  const body = Buffer.isBuffer(payload) ? payload : Buffer.from(payload, 'utf8');
  const mask = Buffer.from([0x11, 0x22, 0x33, 0x44]);
  let head;
  if (body.length < 126) {
    head = Buffer.from([(fin ? 0x80 : 0) | opcode, 0x80 | body.length]);
  } else if (body.length <= 0xffff) {
    head = Buffer.alloc(4);
    head[0] = (fin ? 0x80 : 0) | opcode;
    head[1] = 0x80 | 126;
    head.writeUInt16BE(body.length, 2);
  } else {
    head = Buffer.alloc(10);
    head[0] = (fin ? 0x80 : 0) | opcode;
    head[1] = 0x80 | 127;
    head.writeUInt32BE(0, 2);
    head.writeUInt32BE(body.length, 6);
  }
  const masked = Buffer.alloc(body.length);
  for (let i = 0; i < body.length; i++) masked[i] = body[i] ^ mask[i & 3];
  return Buffer.concat([head, mask, masked]);
}

/** 不带掩码的帧（非法，用来验证拒绝路径） */
function unmaskedFrame(opcode, payload) {
  const body = Buffer.from(payload, 'utf8');
  return Buffer.concat([Buffer.from([0x80 | opcode, body.length]), body]);
}

/**
 * 假通道：把预设字节按 readExactly 的语义吐出来。
 * 数据耗尽即置 closed，避免会话循环空转（真实场景对应对端关闭）。
 */
class FakeChannel {
  constructor(chunks) {
    this.buf = Buffer.concat(chunks);
    this.pos = 0;
    this.sent = [];
    this.closed = false;
  }
  get isClosed() { return this.closed; }
  get remoteIp() { return '192.168.10.99'; }
  get remotePort() { return 45678; }
  async readExactly(need) {
    if (this.pos + need > this.buf.length) {
      this.closed = true;      // 模拟对端关闭
      return null;
    }
    const out = new Uint8Array(this.buf.subarray(this.pos, this.pos + need));
    this.pos += need;
    return out;
  }
  send(u8) { this.sent.push(Buffer.from(u8)); return Promise.resolve(); }
  close() { this.closed = true; }
}

/** 解析服务端发出的帧（服务端帧一律不带掩码） */
function serverFrame(buf) {
  const len7 = buf[1] & 0x7f;
  let off = 2;
  let len = len7;
  if (len7 === 126) { len = buf.readUInt16BE(2); off = 4; }
  else if (len7 === 127) { len = Number(buf.readBigUInt64BE(2)); off = 10; }
  return { opcode: buf[0] & 0x0f, masked: (buf[1] & 0x80) !== 0, payload: buf.subarray(off, off + len) };
}

const settle = () => new Promise((r) => setTimeout(r, 80));

// ---------------------------------------------------------------- 用例

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail });
}

async function run() {
  // 1. 单帧文本
  {
    const patch = JSON.stringify({ cmd: 1, devName: 'PC', message: '你好' });
    const ch = new FakeChannel([clientFrame(OP.TEXT, patch)]);
    const got = [];
    new WebSocketSession(ch, () => '{"cmd":2,"data":[]}', (j) => got.push(j), () => {}).start();
    await settle();
    check('单帧文本消息', got.length === 1 && got[0] === patch, `got=${JSON.stringify(got)}`);
  }

  // 2. 会话建立时先推设备列表
  {
    const ch = new FakeChannel([clientFrame(OP.TEXT, '{"cmd":1}')]);
    new WebSocketSession(ch, () => '{"cmd":2,"data":[{"address":"1.1.1.1"}]}', () => {}, () => {}).start();
    await settle();
    const first = ch.sent.length > 0 ? serverFrame(ch.sent[0]) : null;
    const txt = first ? first.payload.toString('utf8') : '';
    check('建立即推送设备列表',
      first !== null && first.opcode === OP.TEXT && txt.includes('"cmd":2'),
      `first=${txt}`);
  }

  // 3. 分片消息（TEXT fin=0 + CONTINUATION fin=1）
  {
    const a = '{"cmd":1,"mess';
    const b = 'age":"split"}';
    const ch = new FakeChannel([clientFrame(OP.TEXT, a, false), clientFrame(OP.CONT, b, true)]);
    const got = [];
    new WebSocketSession(ch, () => '{}', (j) => got.push(j), () => {}).start();
    await settle();
    check('分片消息正确重组', got.length === 1 && got[0] === a + b, `got=${JSON.stringify(got)}`);
  }

  // 4. ping -> pong
  {
    const ch = new FakeChannel([clientFrame(OP.PING, 'hb')]);
    new WebSocketSession(ch, () => '{}', () => {}, () => {}).start();
    await settle();
    const pongs = ch.sent.filter((b) => serverFrame(b).opcode === OP.PONG);
    const pl = pongs.length > 0 ? serverFrame(pongs[0]).payload.toString('utf8') : '';
    check('ping 回 pong 且回显载荷', pongs.length === 1 && pl === 'hb', `pongs=${pongs.length} pl=${pl}`);
  }

  // 5. 长度 126 档（载荷 > 125）
  {
    const long = JSON.stringify({ cmd: 1, message: 'x'.repeat(400) });
    const ch = new FakeChannel([clientFrame(OP.TEXT, long)]);
    const got = [];
    new WebSocketSession(ch, () => '{}', (j) => got.push(j), () => {}).start();
    await settle();
    check('126 档长度解析（>125B）', got.length === 1 && got[0] === long, `len=${got[0] ? got[0].length : -1}`);
  }

  // 6. 长度 127 档（载荷 > 65535）
  {
    const huge = JSON.stringify({ cmd: 1, message: 'y'.repeat(70000) });
    const ch = new FakeChannel([clientFrame(OP.TEXT, huge)]);
    const got = [];
    new WebSocketSession(ch, () => '{}', (j) => got.push(j), () => {}).start();
    await settle();
    check('127 档长度解析（>65535B）', got.length === 1 && got[0] === huge, `len=${got[0] ? got[0].length : -1}`);
  }

  // 7. close 帧：回 close 并结束会话
  {
    const ch = new FakeChannel([clientFrame(OP.CLOSE, Buffer.from([0x03, 0xe8]))]);
    let closedCb = false;
    new WebSocketSession(ch, () => '{}', () => {}, () => { closedCb = true; }).start();
    await settle();
    const closes = ch.sent.filter((b) => serverFrame(b).opcode === OP.CLOSE);
    check('close 帧回送并结束会话', closes.length === 1 && closedCb, `closes=${closes.length} cb=${closedCb}`);
  }

  // 8. 未带掩码的客户端帧必须被拒绝（RFC 6455）
  {
    const ch = new FakeChannel([unmaskedFrame(OP.TEXT, '{"cmd":1}')]);
    const got = [];
    new WebSocketSession(ch, () => '{}', (j) => got.push(j), () => {}).start();
    await settle();
    check('拒绝未带掩码的客户端帧', got.length === 0, `got=${JSON.stringify(got)}`);
  }

  // 9. 连续多帧
  {
    const ch = new FakeChannel([
      clientFrame(OP.TEXT, '{"n":1}'),
      clientFrame(OP.TEXT, '{"n":2}'),
      clientFrame(OP.TEXT, '{"n":3}'),
    ]);
    const got = [];
    new WebSocketSession(ch, () => '{}', (j) => got.push(j), () => {}).start();
    await settle();
    check('连续多帧不串包', got.join('|') === '{"n":1}|{"n":2}|{"n":3}', JSON.stringify(got));
  }
}

await run();

const pass = results.filter((r) => r.ok).length;
for (const r of results) {
  console.log(`${r.ok ? '[通过]' : '[失败]'} ${r.name}${r.ok ? '' : '   -> ' + r.detail}`);
}
console.log(`\n结果: ${pass}/${results.length}`);
process.exit(pass === results.length ? 0 : 1);
