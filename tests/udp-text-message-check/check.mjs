/**
 * UDP 文本消息（1004 / 1005）字节级对拍 —— 离线自校验，不需要真机。
 *
 * 背景（真机 bug）：安卓平板能收到手机发的文字，手机收不到平板发的。
 * 根因是安卓 `broadcastMessage()` 里 **msg.length() <= 700 走 UDP**（命令 1004），
 * 而我们早期只认 1001/1002，其余命令在 parseHeartbeat 里被 return null 丢掉。
 *
 * 本脚本验证「我们对 UDP 报文的解析」与「安卓发送端的构造」逐字段对齐：
 *   1. 按 Java makeDataEncUdp() + setCmd(1004) + putString(密文) + putString(包名) 造包
 *   2. 套 DataPacket 的 12 字节头 + 0x45 混淆 + MAGIC 前缀（与 encodeUdp 一致）
 *   3. 用 DeviceCodec.parseUdpFrame 的同款逻辑解回来
 *   4. AES-256-ECB 解出明文
 * 另外顺带验证：设备下线包 1003 也必须是**完整 8 字段头**（不能只写 uuid+ip）。
 *
 * 运行： node tests/udp-text-message-check/check.mjs
 */
import crypto from 'node:crypto';

// ---- 常量：必须与 core/LanConfig.ets、core/LCmd.ets、core/DataPacket.ets 一致 ----
const MAGIC_NUM = 0x66677371;
const XOR_KEY = 0x45;
const HEADER_LEN = 12;
const MAGIC_LEN = 4;
const UDP_DEVICES_MESSAGE = 1004;
const UDP_DEVICES_MESSAGE_TO_CLIPBOARD = 1005;
const UDP_DEVICES_OFF_LINE = 1003;
const UDP_SET_DEVICES = 1002;
const KEY = '6c9b%8ErII@Rc&f';
const DEFAULT_MESSAGE_KEY =
  'e4be1373272c69e0932651d97187b746c6725b17bbe84ad0b0fe2d4e81fc1d6c0c633d8ebd7f0fea65a57a9d5529d214';
const EXPECTED_MESSAGE_KEY = 'Ndsi3dklHn4ErC95z3u2QnxeAMQwkNJp';

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

/** Java AESUtils.padKey：不足 32 字节补 '\0'，恰好 32 不补（>= 会误杀） */
function padKey(key) {
  const raw = Buffer.from(key, 'utf8');
  if (raw.length > 32) {
    throw new Error(`AES 密钥长度 ${raw.length} 超过 32 字节`);
  }
  const out = Buffer.alloc(32);
  raw.copy(out);
  return out;
}

function aesEncryptHex(plain, key) {
  const c = crypto.createCipheriv('aes-256-ecb', padKey(key), null);
  return Buffer.concat([c.update(Buffer.from(plain, 'utf8')), c.final()]).toString('hex');
}

function aesDecryptHex(hex, key) {
  const d = crypto.createDecipheriv('aes-256-ecb', padKey(key), null);
  // 必须拼完再 decode：update().toString() + final() 会在分块边界劈开多字节 UTF-8
  return Buffer.concat([d.update(Buffer.from(hex, 'hex')), d.final()]).toString('utf8');
}

// ---------------- 发送端：Java DataEnc 的等价实现 ----------------
class Enc {
  constructor(size = 512) {
    this.buf = Buffer.alloc(HEADER_LEN + size);
    this.pos = HEADER_LEN;
    this.cmd = 0;
    this.count = 0;
  }
  ensure(need) {
    if (this.pos + need <= this.buf.length) return;
    let cap = this.buf.length;
    while (cap < this.pos + need) cap *= 2;
    const next = Buffer.alloc(cap);
    this.buf.copy(next, 0, 0, this.pos);
    this.buf = next;
  }
  writeIntAt(off, v) {
    this.buf.writeInt32BE(v | 0, off);
  }
  packData(cmd) {
    this.cmd = cmd;
    this.pos = HEADER_LEN;
    this.writeIntAt(0, cmd);
    this.writeIntAt(4, 0);
    this.writeIntAt(8, 0);
  }
  putInt(v) {
    this.ensure(4);
    this.writeIntAt(this.pos, v);
    this.pos += 4;
  }
  putByte(v) {
    this.ensure(1);
    this.buf[this.pos] = v & 0xff;
    this.pos += 1;
  }
  putString(s) {
    const b = Buffer.from(s === null || s === undefined ? '' : s, 'utf8');
    this.ensure(4 + b.length);
    this.writeIntAt(this.pos, b.length);
    this.pos += 4;
    b.copy(this.buf, this.pos);
    this.pos += b.length;
  }
  encode() {
    this.writeIntAt(8, this.pos - HEADER_LEN);
    for (let i = 0; i < this.pos; i++) {
      this.buf[i] = ((this.buf[i] - 1) & 0xff) ^ XOR_KEY;
    }
    return this.buf.subarray(0, this.pos);
  }
  encodeUdp() {
    const body = this.encode();
    const out = Buffer.alloc(MAGIC_LEN + body.length);
    out.writeInt32BE(MAGIC_NUM >>> 0, 0);
    body.copy(out, MAGIC_LEN);
    return out;
  }
}

// ---------------- 接收端：DeviceCodec.parseUdpFrame 的等价实现 ----------------
function unscramble(buf, start, end) {
  const to = Math.min(end, buf.length);
  for (let i = Math.max(start, 0); i < to; i++) {
    buf[i] = ((buf[i] ^ XOR_KEY) + 1) & 0xff;
  }
}

function parseUdpFrame(datagram) {
  const buf = Buffer.from(datagram);
  if (buf.length < MAGIC_LEN + HEADER_LEN) return null;
  if (buf.readUInt32BE(0) !== (MAGIC_NUM >>> 0)) return null;
  const body = buf.subarray(MAGIC_LEN);
  unscramble(body, 0, HEADER_LEN);
  const cmd = body.readInt32BE(0);
  const bodyLen = body.readInt32BE(8);
  if (bodyLen > 0) {
    unscramble(body, HEADER_LEN, Math.min(HEADER_LEN + bodyLen, body.length));
  }
  let pos = HEADER_LEN;
  const readInt = () => {
    if (pos + 4 > body.length) { pos += 4; return 0; }
    const v = body.readInt32BE(pos);
    pos += 4;
    return v;
  };
  const readByte = () => {
    if (pos >= body.length) return 0;
    const v = body[pos];
    pos += 1;
    return v;
  };
  const readString = () => {
    const len = readInt();
    if (len === -1) return null;
    if (len === 0) return '';
    if (pos + len > body.length) return null;
    const s = body.subarray(pos, pos + len).toString('utf8');
    pos += len;
    return s;
  };

  const device = {
    devPort: readInt(),
    devIp: readString() ?? '',
    devName: readString() ?? '',
    devMode: readInt(),
    uniqueUuid: readString() ?? '',
    dataVersion: readInt(),
    batteryLevel: readInt(),
    chargeStatus: readByte()
  };
  const sep = device.uniqueUuid.lastIndexOf('-');
  if (sep > 0) {
    const v = Number.parseInt(device.uniqueUuid.substring(sep + 1), 10);
    if (!Number.isNaN(v)) {
      device.dataVersion = v;
      device.uniqueUuid = device.uniqueUuid.substring(0, sep);
    }
  }
  const extras = [];
  for (let i = 0; i < 8; i++) {
    const s = readString();
    if (s === null) break;
    extras.push(s);
  }
  return { cmd, device, extras };
}

console.log('\n[1] 密钥派生（与 Android Config.initPrefs 一致）');
const messageKey = aesDecryptHex(DEFAULT_MESSAGE_KEY, KEY);
ok(`MESSAGE_KEY = ${EXPECTED_MESSAGE_KEY}`, messageKey === EXPECTED_MESSAGE_KEY, `实际 ${messageKey}`);

console.log('\n[2] 安卓端发短消息：UDP 1004（msg.length() <= 700 分支）');
{
  // 安卓 makeDataEncUdp(fromDevice, null, 1024 + msgLen) 的 8 个字段
  const enc = new Enc(1024 + 64);
  enc.packData(UDP_DEVICES_MESSAGE);
  enc.putInt(5856);                       // devPort
  enc.putString('192.168.43.13');         // devIp（平板在热点下的地址）
  enc.putString('vivi 的平板');            // devName
  enc.putInt(1);                          // Device.ANDROID
  enc.putString('a1b2c3d4-4');            // uuid + "-" + DATA_VERSION
  enc.putInt(3);                          // DATA_VERSION_3
  enc.putInt(77);                         // batteryLevel
  enc.putByte(1);                         // chargeStatus
  const plain = '你好，这是平板发来的消息 \u{1F600}';
  enc.putString(aesEncryptHex(plain, messageKey)); // messageEnc（hex 密文）
  enc.putString('com.fgsqw.lanshare');    // packageName
  const datagram = enc.encodeUdp();

  const frame = parseUdpFrame(datagram);
  ok('报文能被解析', frame !== null);
  ok(`命令字 = ${UDP_DEVICES_MESSAGE}`, frame.cmd === UDP_DEVICES_MESSAGE, `实际 ${frame.cmd}`);
  ok('devIp = 192.168.43.13', frame.device.devIp === '192.168.43.13');
  ok('devName = vivi 的平板', frame.device.devName === 'vivi 的平板');
  ok('devPort = 5856', frame.device.devPort === 5856);
  ok('uniqueUuid 剥掉版本后缀 = a1b2c3d4', frame.device.uniqueUuid === 'a1b2c3d4');
  ok('dataVersion 取后缀 = 4', frame.device.dataVersion === 4);
  ok('batteryLevel = 77', frame.device.batteryLevel === 77);
  ok('extras 有 2 项（密文 + 包名）', frame.extras.length >= 2, `实际 ${frame.extras.length}`);
  ok('packageName = com.fgsqw.lanshare', frame.extras[1] === 'com.fgsqw.lanshare');
  let text = '';
  try {
    text = aesDecryptHex(frame.extras[0], messageKey);
  } catch (e) {
    text = `<解密失败: ${e.message}>`;
  }
  ok('解密出明文与原文一致', text === plain, `实际 ${text}`);
}

console.log('\n[3] 到剪切板变体 1005（长按发送）');
{
  const enc = new Enc(512);
  enc.packData(UDP_DEVICES_MESSAGE_TO_CLIPBOARD);
  enc.putInt(5856);
  enc.putString('192.168.43.13');
  enc.putString('平板');
  enc.putInt(1);
  enc.putString('uuid-4');
  enc.putInt(3);
  enc.putInt(-1);
  enc.putByte(-1);
  enc.putString(aesEncryptHex('clip me', messageKey));
  enc.putString('');
  const frame = parseUdpFrame(enc.encodeUdp());
  ok(`命令字 = ${UDP_DEVICES_MESSAGE_TO_CLIPBOARD}`, frame.cmd === UDP_DEVICES_MESSAGE_TO_CLIPBOARD);
  ok('空 packageName 也要能取到', frame.extras.length >= 1);
  ok('明文 = clip me', aesDecryptHex(frame.extras[0], messageKey) === 'clip me');
}

console.log('\n[4] 心跳包 1002 不应带出多余 extras 影响设备逻辑');
{
  const enc = new Enc(512);
  enc.packData(UDP_SET_DEVICES);
  enc.putInt(5856);
  enc.putString('192.168.43.1');
  enc.putString('我的手机');
  enc.putInt(6);                 // HARMONY_OS
  enc.putString('uuid-x-4');
  enc.putInt(3);
  enc.putInt(50);
  enc.putByte(0);
  const frame = parseUdpFrame(enc.encodeUdp());
  ok('devMode = 6 (HARMONY_OS)', frame.device.devMode === 6);
  ok('命令字 = 1002', frame.cmd === UDP_SET_DEVICES);
}

console.log('\n[5] 下线包 1003 必须是完整 8 字段头（不能只写 uuid + ip）');
{
  // 错误写法：只 putString(uuid) + putString(ip)
  const bad = new Enc(256);
  bad.packData(UDP_DEVICES_OFF_LINE);
  bad.putString('uuid-x');
  bad.putString('192.168.43.1');
  const badFrame = parseUdpFrame(bad.encodeUdp());
  // 按 8 字段读时，第一个 readInt 会把 uuid 的长度前缀当成 devPort
  const badPort = badFrame.device.devPort;
  ok('错误写法会被解析成乱掉的 devPort（说明对端会错位）', badPort !== 5856, `实际 ${badPort}`);

  // 正确写法：复用完整设备头（buildOffline 现在走 buildHeartbeat）
  const good = new Enc(512);
  good.packData(UDP_DEVICES_OFF_LINE);
  good.putInt(5856);
  good.putString('192.168.43.1');
  good.putString('我的手机');
  good.putInt(6);
  good.putString('uuid-x-4');
  good.putInt(3);
  good.putInt(50);
  good.putByte(0);
  const goodFrame = parseUdpFrame(good.encodeUdp());
  ok('正确写法 devPort = 5856', goodFrame.device.devPort === 5856);
  ok('正确写法 devIp = 192.168.43.1', goodFrame.device.devIp === '192.168.43.1');
  ok('正确写法命令字 = 1003', goodFrame.cmd === UDP_DEVICES_OFF_LINE);
}

console.log(`\n结果: ${pass} 通过 / ${fail} 失败\n`);
process.exit(fail === 0 ? 0 : 1);
