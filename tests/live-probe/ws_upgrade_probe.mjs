/**
 * 真机 WebSocket 升级探测 —— 一条命令看清 /wss 到底是死是活
 *
 * 判据（按这个顺序看结论）：
 *   1. 有没有收到 101 Switching Protocols，Sec-WebSocket-Accept 对不对
 *   2. 握手后连接是否**保持**（旧版在这里 26ms 就被服务端关掉）
 *   3. 有没有收到服务端主动推的设备列表帧（{"cmd":2,...}）
 *   4. 发一个 ping，能不能收到 pong
 *
 * 用法：
 *   node tests/live-probe/ws_upgrade_probe.mjs [ip] [port]
 * 默认 192.168.10.146:5856
 */
import net from 'node:net';

const HOST = process.argv[2] || '192.168.10.146';
const PORT = Number(process.argv[3] || 5856);
const KEY = 'dGhlIHNhbXBsZSBub25jZQ==';
const HOLD_MS = 6000;

const t0 = Date.now();
let buf = Buffer.alloc(0);
let handshakeMs = -1;
let headersDone = false;
let frameBytes = Buffer.alloc(0);
const frames = [];
let closedMs = -1;
let closeReason = '';

function takeFrames() {
  while (frameBytes.length >= 2) {
    const len7 = frameBytes[1] & 0x7f;
    let off = 2;
    let len = len7;
    if (len7 === 126) {
      if (frameBytes.length < 4) return;
      len = frameBytes.readUInt16BE(2); off = 4;
    } else if (len7 === 127) {
      if (frameBytes.length < 10) return;
      len = Number(frameBytes.readBigUInt64BE(2)); off = 10;
    }
    if (frameBytes.length < off + len) return;
    const opcode = frameBytes[0] & 0x0f;
    frames.push({ opcode, payload: frameBytes.subarray(off, off + len) });
    frameBytes = frameBytes.subarray(off + len);
  }
}

const s = net.connect(PORT, HOST, () => {
  s.write(
    `GET /wss?token=probe-${Date.now()} HTTP/1.1\r\n` +
    `Host: ${HOST}:${PORT}\r\n` +
    'Upgrade: websocket\r\n' +
    'Connection: Upgrade\r\n' +
    `Sec-WebSocket-Key: ${KEY}\r\n` +
    'Sec-WebSocket-Version: 13\r\n\r\n'
  );
});

s.on('data', (d) => {
  buf = Buffer.concat([buf, d]);
  if (!headersDone) {
    const end = buf.indexOf('\r\n\r\n');
    if (end >= 0) {
      headersDone = true;
      handshakeMs = Date.now() - t0;
      const head = buf.subarray(0, end).toString('latin1');
      console.log('---- 握手响应 ----');
      console.log(head);
      console.log('');
      frameBytes = buf.subarray(end + 4);
      takeFrames();
    }
  } else {
    frameBytes = Buffer.concat([frameBytes, d]);
    takeFrames();
  }
});

s.on('close', () => {
  closedMs = Date.now() - t0;
  closeReason = '对端关闭';
});
s.on('error', (e) => {
  closedMs = Date.now() - t0;
  closeReason = '错误: ' + e.message;
});

// 握手 1 秒后发个 ping，看能不能换回 pong
setTimeout(() => {
  if (closedMs >= 0) return;
  const payload = Buffer.from('hb');
  const mask = Buffer.from([1, 2, 3, 4]);
  const masked = Buffer.alloc(payload.length);
  for (let i = 0; i < payload.length; i++) masked[i] = payload[i] ^ mask[i & 3];
  s.write(Buffer.concat([Buffer.from([0x89, 0x80 | payload.length]), mask, masked]));
  console.log('[已发送] ping');
}, 1000);

setTimeout(() => {
  if (closedMs < 0) {
    try { s.destroy(); } catch (e) {}
  }
  console.log('');
  console.log('======== 结论 ========');
  console.log(`握手         : ${handshakeMs >= 0 ? handshakeMs + ' ms（收到 101）' : '未收到响应头'}`);
  console.log(`握手后存活   : ${closedMs >= 0 ? closedMs + ' ms 后断开（' + closeReason + '）' : '≥ ' + HOLD_MS + ' ms，连接保持'}`);
  console.log(`收到帧数     : ${frames.length}`);
  frames.forEach((f, i) => {
    const name = { 1: 'TEXT', 2: 'BIN', 8: 'CLOSE', 9: 'PING', 10: 'PONG' }[f.opcode] || ('OP' + f.opcode);
    let body = f.payload.toString('utf8');
    if (body.length > 160) body = body.slice(0, 160) + '…';
    console.log(`  [${i}] ${name}  ${JSON.stringify(body)}`);
  });
  // 「保持」必须建立在「握手确实成功」之上：连 101 都没收到，
  // 只能说明服务没在跑或没响应，不能算连接保持。
  const held = handshakeMs >= 0 && (closedMs < 0 || closedMs > 2000);
  const gotPong = frames.some((f) => f.opcode === 10);
  const gotDeviceList = frames.some((f) => f.opcode === 1 && f.payload.toString('utf8').includes('"cmd":2'));
  console.log('');
  if (handshakeMs < 0) {
    console.log('❓ 没收到握手响应 —— 先确认手机上 LANShare 正在前台运行、共享已开启');
  } else if (held) {
    console.log('✅ 连接能保持 —— 会话层已接管');
  } else {
    console.log('❌ 握手后立刻断开 —— 会话层没接上（旧版就是这个表现）');
  }
  console.log(gotDeviceList ? '✅ 收到服务端推送的设备列表' : '⚠️ 没收到设备列表帧');
  console.log(gotPong ? '✅ ping 得到 pong' : '⚠️ ping 没有 pong');
  process.exit(held && gotDeviceList ? 0 : 1);
}, HOLD_MS);
