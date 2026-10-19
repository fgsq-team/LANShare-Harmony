/**
 * 文本消息（v4 FS_MESSAGE）字节级对拍 —— 离线自校验，不需要真机。
 *
 * 验证三件事：
 *   1. 「密钥的密钥」到真正消息密钥的派生。Android 的 Config.initPrefs() 会把
 *      DEFAULT_MESSAGE_KEY 再解一层，得到 32 字符的 MESSAGE_KEY。这一步错了，
 *      两端就是「A 加密 B 解密」，消息永远显示不出来。
 *   2. 发送帧的字节序列，与 Java FileSend.sendMessage 逐字段一致：
 *        int NEW_VERSION_4(-2) | string devJson | int FS_MESSAGE(1105) | bool isClip | string hex(密文)
 *   3. 用「接收端逻辑」把帧解回来（模拟 Android FileServer.handleMessage）：
 *        读 bool -> 读 string -> hexToBytes -> AES-ECB-PKCS5 解密 -> 明文
 *
 * 运行： node tests/text-message-check/check.mjs
 */
import crypto from 'node:crypto';

// ---- 常量：必须与 core/LanConfig.ets、core/LCmd.ets 完全一致 ----
const KEY = '6c9b%8ErII@Rc&f';
const DEFAULT_MESSAGE_KEY =
  'e4be1373272c69e0932651d97187b746c6725b17bbe84ad0b0fe2d4e81fc1d6c0c633d8ebd7f0fea65a57a9d5529d214';
const EXPECTED_MESSAGE_KEY = 'Ndsi3dklHn4ErC95z3u2QnxeAMQwkNJp';
const NEW_VERSION_4 = -2;
const FS_MESSAGE = 1105;

let pass = 0;
let fail = 0;
function ok(name, cond, extra = '') {
  if (cond) {
    pass++;
    console.log(`  \u2713 ${name}`);
  } else {
    fail++;
    console.log(`  \u2717 ${name} ${extra}`);
  }
}

/** Java AESUtils.padKey：不足 32 字节补 '\0'（恰好 32 字节不补） */
function padKey(key) {
  const raw = Buffer.from(key, 'utf8');
  if (raw.length > 32) {
    throw new Error(`AES 密钥长度 ${raw.length} 超过 32 字节`);
  }
  const out = Buffer.alloc(32);
  raw.copy(out);
  return out;
}

function aesDecryptHex(hex, key) {
  const d = crypto.createDecipheriv('aes-256-ecb', padKey(key), null);
  // ⚠️ 必须先把 Buffer 拼完再 decode：`update().toString() + final()` 会在
  // 分块边界把一个多字节 UTF-8 字符劈成两半，中文/emoji 会解出替换字符。
  // 这是脚本自身的坑，不是协议问题（曾用它误报过一次）。
  const out = Buffer.concat([d.update(Buffer.from(hex, 'hex')), d.final()]);
  return out.toString('utf8');
}

function aesEncryptHex(plain, key) {
  const c = crypto.createCipheriv('aes-256-ecb', padKey(key), null);
  return Buffer.concat([c.update(Buffer.from(plain, 'utf8')), c.final()]).toString('hex');
}

// ---------------- 写端（对照 ProtoIO） ----------------
function intBytes(v) {
  const b = Buffer.alloc(4);
  b.writeInt32BE(v | 0);
  return b;
}
function boolBytes(v) {
  return Buffer.from([v ? 1 : 0]);
}
function stringBytes(s) {
  const body = Buffer.from(s, 'utf8');
  const head = Buffer.alloc(4);
  head.writeUInt32BE(body.length);
  return Buffer.concat([head, body]);
}

// ---------------- 读端（对照 Android CustomDataInputStream） ----------------
class Reader {
  constructor(buf) {
    this.b = buf;
    this.i = 0;
  }
  int() {
    const v = this.b.readInt32BE(this.i);
    this.i += 4;
    return v;
  }
  bool() {
    return this.b[this.i++] === 1;
  }
  str() {
    const len = this.b.readUInt32BE(this.i);
    this.i += 4;
    const s = this.b.subarray(this.i, this.i + len).toString('utf8');
    this.i += len;
    return s;
  }
}

console.log('== 1. 消息密钥派生（Config.initPrefs 的第二层解密） ==');
const derived = aesDecryptHex(DEFAULT_MESSAGE_KEY, KEY);
ok(`派生结果 == 内置常量 (${derived})`, derived === EXPECTED_MESSAGE_KEY, `got=${derived}`);
ok('派生结果恰好 32 字节（AES-256，无需补齐）', Buffer.byteLength(derived, 'utf8') === 32);

console.log('== 2. 发送帧字节序列 ==');
const self = { devName: 'PLR-AL50', devIp: '192.168.10.20', devPort: 5856 };
const devJson = JSON.stringify(self);
for (const text of ['hello', '你好，这是一条中文消息 🎉', 'a'.repeat(700), '单']) {
  const cipher = aesEncryptHex(text, derived);
  const frame = Buffer.concat([
    intBytes(NEW_VERSION_4),
    stringBytes(devJson),
    intBytes(FS_MESSAGE),
    boolBytes(false),
    stringBytes(cipher)
  ]);

  const r = new Reader(frame);
  const ver = r.int();
  const dj = r.str();
  const cmd = r.int();
  const isClip = r.bool();
  const payload = r.str();
  // 模拟 Android FileServer.handleMessage
  let decoded = null;
  try {
    decoded = aesDecryptHex(payload, derived);
  } catch (e) {
    decoded = `<decrypt error: ${e.message}>`;
  }
  ok(
    `往返一致 (len=${Buffer.byteLength(text, 'utf8')}B)`,
    ver === NEW_VERSION_4 && cmd === FS_MESSAGE && dj === devJson && isClip === false && decoded === text,
    `ver=${ver} cmd=${cmd} decoded=${String(decoded).slice(0, 40)}`
  );
}

console.log('== 3. 密文形态（必须是纯 hex，否则对端 hexToBytes 直接抛） ==');
const c1 = aesEncryptHex('test', derived);
ok('密文为偶数长度十六进制', /^[0-9a-f]+$/.test(c1) && c1.length % 2 === 0, c1);
ok('密文长度是 16 字节块整数倍', c1.length % 32 === 0, `len=${c1.length}`);

console.log('== 4. 明文直接发会被对端判为解密失败（负向用例） ==');
let plainAsHexThrew = false;
try {
  aesDecryptHex('hello', derived);
} catch (e) {
  plainAsHexThrew = true;
}
ok('明文 "hello" 无法当密文解（证明必须加密）', plainAsHexThrew);

console.log(`\n结果: ${pass}/${pass + fail} 通过`);
process.exit(fail === 0 ? 0 : 1);
