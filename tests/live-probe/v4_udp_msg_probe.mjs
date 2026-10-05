/**
 * 伪装「官方 Android 版」发一条 UDP 文本消息（cmd=1004），验证鸿蒙端能否收到。
 *
 * 官方实现取证（docs/official_src）：
 *   LANService.makeDataEncUdp()   → 8 个设备字段，**没有「已知设备表」**
 *   LANService.broadcastMessage() → dataEnc.setCmd(1004/1005) + putString(messageEnc) + putString(packageName)
 *   UDPTools.sendData()           → MAGIC(4) + DataEnc.encData()（整段 (b-1)^0x45 混淆）
 *   AESUtils                     → AES/ECB/PKCS5Padding，key = padKey(MESSAGE_KEY) → 32B（= AES-256-ECB）
 *
 * 本工程 V5Udp.parse 曾**无条件**在设备头之后读一个「已知设备数」int（那是 v5 才有的），
 * 于是把 v4 的 messageEnc 长度前缀当成计数吃掉 → extras 全空 → 消息被丢弃。
 * 症状：设备能发现，但「安卓发来的文字一条都收不到」。
 *
 * 用法：node v4_udp_msg_probe.mjs <host> [udpPort] ["消息内容"] [clip]
 */
import dgram from 'node:dgram';
import crypto from 'node:crypto';

const HOST = process.argv[2] || '192.168.10.146';
const UDP_PORT = Number(process.argv[3] || 4573);
const TEXT = process.argv[4] || 'official-v4-udp-probe 你好';
const CLIP = process.argv[5] === 'clip';
const SELF_IP = process.argv[6] || '192.168.10.186';
/** 4 = 官方（设备头之后**没有**已知设备表）；5 = v5/1.35（**有**） */
const VER = Number(process.argv[7] || 4);
const TCP_PORT = 5856;
const UUID = 'udpmsg-probe';
const MAGIC = Buffer.from([0x66, 0x67, 0x73, 0x71]);   // 'fgsq'

/** 与 core/LanConfig.ets 的 DEFAULT_MESSAGE_KEY_PLAIN 一致（= AESUtils.decrypt(DEFAULT_MESSAGE_KEY, KEY)） */
const MESSAGE_KEY = 'Ndsi3dklHn4ErC95z3u2QnxeAMQwkNJp';

/** AES/ECB/PKCS5Padding，key 不足 32 字节补 '\0'（与官方 padKey 一致），输出 hex */
function encryptHex(plain) {
  const keyBuf = Buffer.alloc(32);
  Buffer.from(MESSAGE_KEY, 'utf8').copy(keyBuf);          // 右侧自动补 0
  const c = crypto.createCipheriv('aes-256-ecb', keyBuf, null);
  // ⚠️ 两个 runtime 坑（本机 managed Node 22.22.2 实测）：
  //    ① cipher.update() 返回的是**密文 Buffer**，不是 Cipher 本身 →
  //       写成 `c.update(x).digest()` 会报 "digest is not a function"；
  //    ② 这台 Node 的 Cipheriv **没有 digest 方法**（原型上只有
  //       update/final/setAutoPadding…）→ 收尾必须用 `final()`，不能用 digest()。
  const head = c.update(Buffer.from(plain, 'utf8'));
  const tail = typeof c.final === 'function' ? c.final() : c.digest();
  return Buffer.concat([head, tail]).toString('hex');
}

const beInt = (v) => { const b = Buffer.alloc(4); b.writeInt32BE(v | 0, 0); return b; };
const str = (s) => { const body = Buffer.from(s, 'utf8'); return Buffer.concat([beInt(body.length), body]); };

/**
 * @param withKnown true = 在设备头之后插一个「已知设备数 int」（v5 才有；官方 v4 没有）
 */
function build(cmd, extras, withKnown = false) {
  const parts = [
    beInt(TCP_PORT),
    str(SELF_IP),
    str('安卓消息探针'),
    beInt(1),                       // devMode = ANDROID
    str(`${UUID}-${VER}`),          // uuid + "-" + DATA_VERSION
    beInt(VER >= 5 ? 5 : 3),        // v5 写 DATA_VERSION(5)；官方写死 DATA_VERSION_3
    beInt(77),
    Buffer.from([2])
  ];
  if (withKnown) parts.push(beInt(0));   // ★ 已知设备数 = 0（v5 的已知设备表）
  for (const e of extras) parts.push(str(e));
  const payload = Buffer.concat(parts);
  const frame = Buffer.concat([beInt(cmd), beInt(0), beInt(payload.length), payload]);
  const ob = Buffer.alloc(frame.length);
  for (let i = 0; i < frame.length; i++) ob[i] = ((((frame[i] & 0xFF) - 1) & 0xFF) ^ 0x45) & 0xFF;
  return Buffer.concat([MAGIC, ob]);
}

const hex = encryptHex(TEXT);
const cmd = CLIP ? 1005 : 1004;
const WITH_KNOWN = VER >= 5;
const pkt = build(cmd, [hex, 'com.fgsqw.lanshare'], WITH_KNOWN);

console.log(`协议版本  : ${VER}${WITH_KNOWN ? '（设备头后带「已知设备表」= v5 形态）' : '（设备头后直接跟参数 = 官方 v4 形态）'}`);
console.log(`明文      : ${TEXT}`);
console.log(`AES-256   : ${hex}`);
console.log(`命令字    : ${cmd}${CLIP ? ' (1005 写剪贴板)' : ' (1004)'}`);
console.log(`数据报长  : ${pkt.length} B`);

const sock = dgram.createSocket('udp4');
sock.send(pkt, UDP_PORT, HOST, (err) => {
  if (err) { console.log(`✗ 发送失败: ${err.message}`); process.exit(1); }
  console.log(`✓ 已发送到 ${HOST}:${UDP_PORT}`);
  setTimeout(() => {
    // 清理：把探针设备从对端设备表里摘掉
    sock.send(build(1003, [], WITH_KNOWN), UDP_PORT, HOST, () => {
      console.log('（已发送 1003 下线通知清理探针条目）');
      sock.close();
      process.exit(0);
    });
  }, 1200);
});
