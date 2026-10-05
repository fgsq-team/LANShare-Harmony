/**
 * 复现「同一 IP 下多条目 → 群发重复」。
 *
 * 原理（全部来自官方源码 + 本工程实现）：
 *   · 官方 UDP 心跳 = MAGIC(4) + 逐字节混淆[(12B头)(devPort/devIp/devName/devMode/uuid-N/dataVersion/battery/charge)]
 *   · 本工程 devices Map 的 key = uniqueUuid（UDP 发现与 trackPeer 两条路径都是）
 *   · 所以**同一台物理机换了 uuid（重装 / 双版本）**时，Map 里会留下多条同 IP 记录
 *   · 而 `tcpProbeStep` 的 TCP 复核**只认 IP**：复核成功会把 `d.lastSeenMs` 刷新，
 *     于是这些历史条目互相续命、永不过期 → 群发时每个条目各发一份
 *
 * 本脚本在 PC 上伪造 N 条「同 IP、不同 uuid」的官方 v4 心跳，周期重发，
 * 同时通过应用自身的 WebSocket（/wss，SYNC_DEVICE_LIST）观察设备表条目数。
 *
 * 用法：
 *   node v4_udp_dup_probe.mjs <host> [udpPort] [名字数=2] [持续秒=24] [watchOnly]
 *   例：node v4_udp_dup_probe.mjs 192.168.10.146 4573 2 24
 *       node v4_udp_dup_probe.mjs 192.168.10.146 4573 0 12 watchOnly   # 只观察
 */
import dgram from 'node:dgram';

const HOST = process.argv[2] || '192.168.10.146';
const UDP_PORT = Number(process.argv[3] || 4573);
const FAKES = Number(process.argv[4] ?? 2);
const SECONDS = Number(process.argv[5] || 24);
const WATCH_ONLY = process.argv[6] === 'watchOnly';

const MAGIC = Buffer.from([0x66, 0x67, 0x73, 0x71]); // 'fgsq'
const TCP_PORT = 5856;                                // 设备互相回连用的端口
const SELF_IP = process.argv[7] || '192.168.10.186';  // 伪造设备声明的 IP（=本机 IP 才有意义）
const CMD_SET = 1002;
const CMD_OFFLINE = 1003;

const beInt = (v) => { const b = Buffer.alloc(4); b.writeInt32BE(v | 0, 0); return b; };
const str = (s) => { const body = Buffer.from(s, 'utf8'); return Buffer.concat([beInt(body.length), body]); };

/** 官方 DataEnc：12 字节头 + 字段，最后整段做 (b-1)^0x45，前面加 MAGIC */
function buildV4(cmd, uuid, name) {
  const payload = Buffer.concat([
    beInt(TCP_PORT),        // devPort
    str(SELF_IP),           // devIp
    str(name),              // devName
    beInt(1),               // devMode = ANDROID
    str(`${uuid}-4`),       // uniqueUUid + "-" + DATA_VERSION(4)
    beInt(3),               // 官方写死 LVersion.DATA_VERSION_3
    beInt(88),              // batteryLevel
    Buffer.from([2])        // chargeStatus
  ]);
  const frame = Buffer.concat([beInt(cmd), beInt(0), beInt(payload.length), payload]);
  const ob = Buffer.alloc(frame.length);
  for (let i = 0; i < frame.length; i++) ob[i] = ((((frame[i] & 0xFF) - 1) & 0xFF) ^ 0x45) & 0xFF;
  return Buffer.concat([MAGIC, ob]);
}

// ------------------------------------------------------------------
// 设备表观察（应用自带 WebSocket）
// ------------------------------------------------------------------
const seen = [];
let lastDupReport = '';
function report(tag) {
  const byIp = new Map();
  for (const d of seen) {
    const k = d.devIP || '(空)';
    if (!byIp.has(k)) byIp.set(k, []);
    byIp.get(k).push(d);
  }
  const dup = [...byIp.entries()].filter(([, l]) => l.length > 1);
  const sig = [...byIp.entries()].map(([ip, l]) => `${ip}×${l.length}`).sort().join(' ');
  if (sig === lastDupReport && tag !== '最终') return;
  lastDupReport = sig;
  console.log(`[${tag}] 条目 ${seen.length} 条 / ${byIp.size} 个 IP  ${sig}`);
  for (const [ip, list] of dup) {
    console.log(`   ★ ${ip} 有 ${list.length} 条：${list.map((d) => d.devName).join(' , ')}`);
  }
}

const ws = new WebSocket(`ws://${HOST}:${TCP_PORT}/wss`);
ws.addEventListener('message', (ev) => {
  const raw = typeof ev.data === 'string' ? ev.data : Buffer.from(ev.data).toString('utf8');
  let o = null;
  try { o = JSON.parse(raw); } catch (e) { return; }
  if (o && o.cmd === 2 && Array.isArray(o.data)) { seen.length = 0; seen.push(...o.data); report('设备表'); }
});
ws.addEventListener('error', (e) => console.log(`WS 错误: ${e.message || e}`));

// ------------------------------------------------------------------
// 伪造心跳（每 3 秒一轮，模拟「同一 IP 上还跑着另一台设备」）
// ------------------------------------------------------------------
const sock = dgram.createSocket('udp4');
const names = [];
for (let i = 0; i < FAKES; i++) names.push({ uuid: `dup-probe-${String.fromCharCode(65 + i)}`, name: `DUP-${String.fromCharCode(65 + i)}` });

if (WATCH_ONLY) {
  console.log(`只观察模式：不发送任何包，仅用 WebSocket 读设备表 ${SECONDS}s`);
} else {
  console.log(`伪造 ${FAKES} 台设备（同 IP ${SELF_IP}、不同 uuid），每 3s 一轮，共 ${SECONDS}s`);
  for (const n of names) console.log(`   uuid=${n.uuid}-4  name=${n.name}`);
}

let rounds = 0;
const timer = setInterval(() => {
  rounds += 1;
  if (!WATCH_ONLY) {
    for (const n of names) {
      const pkt = buildV4(CMD_SET, n.uuid, n.name);
      sock.send(pkt, UDP_PORT, HOST, (err) => { if (err) console.log('UDP 发送失败', err.message); });
    }
    console.log(`-- 第 ${rounds} 轮心跳已发（${FAKES} 包，各 ${buildV4(CMD_SET, names[0].uuid, names[0].name).length}B）`);
  }
}, 3000);

setTimeout(async () => {
  clearInterval(timer);
  report('最终');
  if (!WATCH_ONLY) {
    console.log('清理：发送 UDP_DEVICES_OFF_LINE(1003) 让对端移除这些伪造条目 …');
    for (const n of names) {
      sock.send(buildV4(CMD_OFFLINE, n.uuid, n.name), UDP_PORT, HOST);
      await new Promise((r) => setTimeout(r, 150));
    }
    await new Promise((r) => setTimeout(r, 1500));
    report('清理后');
  }
  try { ws.close(); } catch (e) { /* ignore */ }
  sock.close();
  setTimeout(() => process.exit(0), 300);
}, SECONDS * 1000);
