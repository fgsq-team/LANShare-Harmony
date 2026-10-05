/**
 * 端到端断言：伪装官方 Android（或 v5）发一条 UDP 文本消息，看鸿蒙**是否真的收到**。
 *
 * 为什么要连 WebSocket：`LanService.pushLog()` 只写内存环形缓冲，**不进 hilog**，
 * 所以从 hilog 看不到消息内容。而收到消息后 `broadcastChatToWeb()` 会向所有
 * WebSocket 会话推一条 `{"cmd":1,"isLeft":true,"devName":...,"message":...}`
 * —— 那就是最可靠的"收到"凭据。
 *
 * 用法：node udp_msg_e2e.mjs <host> [udpPort] [ver] ["消息"] [selfIp]
 *   例：node udp_msg_e2e.mjs 192.168.10.146 4573 4 "v4-消息"
 *       node udp_msg_e2e.mjs 192.168.10.146 4573 5 "v5-消息"
 */
import dgram from 'node:dgram';
import crypto from 'node:crypto';

const HOST = process.argv[2] || '192.168.10.146';
const UDP_PORT = Number(process.argv[3] || 4573);
const VER = Number(process.argv[4] || 4);
const TEXT = process.argv[5] || `e2e-v${VER}-消息`;
const SELF_IP = process.argv[6] || '192.168.10.186';

const MAGIC = Buffer.from([0x66, 0x67, 0x73, 0x71]);
const TCP_PORT = 5856;
const UUID = 'e2e-udp-probe';
const MESSAGE_KEY = 'Ndsi3dklHn4ErC95z3u2QnxeAMQwkNJp';

function encryptHex(plain) {
  const keyBuf = Buffer.alloc(32);
  Buffer.from(MESSAGE_KEY, 'utf8').copy(keyBuf);
  const c = crypto.createCipheriv('aes-256-ecb', keyBuf, null);
  // 这台 Node 的 Cipheriv 没有 digest()，只有 final()
  const head = c.update(Buffer.from(plain, 'utf8'));
  const tail = typeof c.final === 'function' ? c.final() : c.digest();
  return Buffer.concat([head, tail]).toString('hex');
}

const beInt = (v) => { const b = Buffer.alloc(4); b.writeInt32BE(v | 0, 0); return b; };
const str = (s) => { const body = Buffer.from(s, 'utf8'); return Buffer.concat([beInt(body.length), body]); };

function build(cmd, extras, withKnown) {
  const parts = [
    beInt(TCP_PORT), str(SELF_IP), str('E2E-PROBE'), beInt(1),
    str(`${UUID}-${VER}`), beInt(VER >= 5 ? 5 : 3), beInt(66), Buffer.from([2])
  ];
  if (withKnown) parts.push(beInt(0));
  for (const e of extras) parts.push(str(e));
  const payload = Buffer.concat(parts);
  const frame = Buffer.concat([beInt(cmd), beInt(0), beInt(payload.length), payload]);
  const ob = Buffer.alloc(frame.length);
  for (let i = 0; i < frame.length; i++) ob[i] = ((((frame[i] & 0xFF) - 1) & 0xFF) ^ 0x45) & 0xFF;
  return Buffer.concat([MAGIC, ob]);
}

const WITH_KNOWN = VER >= 5;
const hex = encryptHex(TEXT);
const sock = dgram.createSocket('udp4');

console.log(`目标      : ${HOST}:${UDP_PORT}`);
console.log(`协议形态  : v${VER}${WITH_KNOWN ? '（带已知设备表 → v5/1.35 形态）' : '（无已知设备表 → 官方 v4 形态）'}`);
console.log(`期望消息  : ${TEXT}`);

let hit = false;
let sentAt = 0;

const ws = new WebSocket(`ws://${HOST}:${TCP_PORT}/wss`);
ws.addEventListener('open', () => {
  console.log('WebSocket 已连接，0.8s 后发包 …');
  setTimeout(() => {
    sentAt = Date.now();
    sock.send(build(1004, [hex, 'com.fgsqw.lanshare'], WITH_KNOWN), UDP_PORT, HOST, (err) => {
      if (err) { console.log(`✗ UDP 发送失败: ${err.message}`); }
      else { console.log('✓ UDP 探针已发出'); }
    });
  }, 800);
});
ws.addEventListener('message', (ev) => {
  const raw = typeof ev.data === 'string' ? ev.data : Buffer.from(ev.data).toString('utf8');
  let o = null;
  try { o = JSON.parse(raw); } catch (e) { return; }
  if (o && o.cmd === 1) {
    const mark = o.message === TEXT ? '  ★ 就是它' : '';
    console.log(`<< WS 聊天推送: devName=${o.devName} isLeft=${o.isLeft} message=${JSON.stringify(o.message)}${mark}`);
    if (o.message === TEXT) hit = true;
  }
});
ws.addEventListener('error', (e) => console.log(`WS 错误: ${e.message || e}`));

setTimeout(() => {
  console.log('');
  if (hit) {
    console.log(`✓ PASS —— 对端已收到（${Date.now() - sentAt} ms 内）并推给了网页会话`);
  } else {
    console.log('✗ FAIL —— 8s 内没有收到该消息（WebSocket 未收到对应 cmd=1 推送）');
  }
  // 清理探针条目
  sock.send(build(1003, [], WITH_KNOWN), UDP_PORT, HOST, () => {
    try { ws.close(); } catch (e) { /* ignore */ }
    sock.close();
    setTimeout(() => process.exit(hit ? 0 : 2), 300);
  });
}, 9000);
