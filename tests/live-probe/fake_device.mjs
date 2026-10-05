/**
 * PC 伪装成 LANShare 设备 —— 让真机上的鸿蒙端能"发现"本机，
 * 从而把「鸿蒙 -> 其他设备」这条发送链路也测穿，不需要第二台手机。
 *
 * 干两件事：
 *   1. 每 3s 向子网广播地址 :4573 广播 UDP_SET_DEVICES 心跳
 *      → 鸿蒙的设备列表里会出现一个叫 "PC-Probe(Windows)" 的设备
 *   2. TCP 5856 当 v4 接收端
 *      → 在鸿蒙 App 上点「发送文件」→ 选 PC-Probe，这里把字节流完整收下来并打印
 *
 * 报文构造**直接复用交付的 .ets 源码**（DeviceCodec / DataPacket），
 * 不另写一份镜像，避免模拟端与真实端悄悄漂移。
 *
 * 用法:
 *   node --experimental-strip-types fake_device.mjs [bindIp] [broadcastIp]
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import dgram from 'node:dgram';
import net from 'node:net';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../../');
const ETS = path.join(ROOT, 'entry/src/main/ets');
const BUILD = path.join(__dirname, '_probe_build');

const BIND_IP = process.argv[2] || '192.168.10.186';
const BCAST_IP = process.argv[3] || '192.168.10.255';
const UDP_PORT = 4573;
const TCP_PORT = 5856;

const t0 = Date.now();
function log(msg) {
  console.log(`[+${String(Date.now() - t0).padStart(6)}ms] ${msg}`);
}

// ------------------------------------------------------------------ ets 加载
const ARK_UTIL_SHIM = `
const ArkUtil = {
  TextEncoder: class { encodeInto(s) { return new TextEncoder().encode(s); } },
  TextDecoder: { create(_e) { return { decodeToString: (u) => new TextDecoder('utf-8').decode(u) }; } }
};
`;
const HILOG_SHIM = `
const hilog = { debug(){}, info(){}, warn(){}, error(){} };
`;

function convert(rel, outName) {
  let s = fs.readFileSync(path.join(ETS, rel), 'utf8');
  s = s.replace(/^\s*import\s*\{\s*util\s*\}\s*from\s*'@kit\.ArkTS';\s*$/gm, ARK_UTIL_SHIM);
  s = s.replace(/\butil\.TextEncoder\b/g, 'ArkUtil.TextEncoder');
  s = s.replace(/\butil\.TextDecoder\b/g, 'ArkUtil.TextDecoder');
  s = s.replace(/^\s*import\s*\{\s*hilog\s*\}\s*from\s*'@kit\.PerformanceAnalysisKit';\s*$/gm, HILOG_SHIM);
  s = s.replace(/from\s*'(\.{1,2}\/[\w/]+)'/g, "from '$1.ts'");
  const out = path.join(BUILD, `${outName}.ts`);
  fs.writeFileSync(out, s, 'utf8');
  return pathToFileURL(out).href;
}

fs.mkdirSync(BUILD, { recursive: true });
for (const [rel, name] of [
  ['core/LanConfig.ets', 'LanConfig'],
  ['core/LCmd.ets', 'LCmd'],
  ['core/ByteCodec.ets', 'ByteCodec'],
  ['core/MiniJson.ets', 'MiniJson'],
  ['core/Logger.ets', 'Logger'],
  ['core/DataPacket.ets', 'DataPacket'],
  ['core/DeviceCodec.ets', 'DeviceCodec']
]) {
  convert(rel, name);
}

const { DeviceCodec, LanDevice, DeviceMode } = await import(
  pathToFileURL(path.join(BUILD, 'DeviceCodec.ts')).href
);
const { LCmd } = await import(pathToFileURL(path.join(BUILD, 'LCmd.ts')).href);
const { LanConfig } = await import(pathToFileURL(path.join(BUILD, 'LanConfig.ts')).href);
const { DataDec } = await import(pathToFileURL(path.join(BUILD, 'DataPacket.ts')).href);

// ------------------------------------------------------------------ 本机身份
const self = new LanDevice('PC-Probe(Windows)', BIND_IP, TCP_PORT);
self.devNetMask = '255.255.255.0';
self.devBroadcastIp = BCAST_IP;
self.uniqueUuid = 'PC-PROBE-WINDOWS-0001';
self.devMode = DeviceMode.WINDOWS;
self.dataVersion = LanConfig.DATA_VERSION;
self.batteryLevel = 100;
self.chargeStatus = -1;

// ------------------------------------------------------------------ UDP 心跳
let udpSent = 0;
const dg = dgram.createSocket({ type: 'udp4', reuseAddr: true });
dg.on('error', (e) => log(`UDP error: ${e.code} ${e.message}`));
dg.on('message', (msg, rinfo) => {
  // 顺带看看鸿蒙的探测包长什么样（不参与判定，纯观测）
  try {
    const d = DataDec.fromUdp(new Uint8Array(msg));
    if (d !== null) {
      log(`<- 收到对端 UDP cmd=${d.getCmd()} 来自 ${rinfo.address}:${rinfo.port}`);
    }
  } catch (_e) { /* 忽略 */ }
});
dg.bind(0, () => {
  dg.setBroadcast(true);
  const pkt = Buffer.from(DeviceCodec.buildHeartbeat(self, LCmd.UDP_SET_DEVICES));
  const probe = Buffer.from(DeviceCodec.buildHeartbeat(self, LCmd.UDP_GET_DEVICES));
  const send = () => {
    dg.send(pkt, UDP_PORT, BCAST_IP, (e) => {
      if (e) { log(`广播失败: ${e.message}`); return; }
      udpSent++;
      if (udpSent === 1 || udpSent % 10 === 0) {
        log(`-> 已广播心跳 #${udpSent} (${pkt.length}B) → ${BCAST_IP}:${UDP_PORT}`);
      }
    });
  };
  send();
  setInterval(send, 3000);
  log(`UDP 心跳已启动：本机 ${BIND_IP}，子网广播 ${BCAST_IP}:${UDP_PORT}`);
});

// ------------------------------------------------------------------ TCP 接收端
class FrameReader {
  constructor(sock) {
    this.buf = Buffer.alloc(0);
    this.closed = false;
    this.waiters = [];
    sock.on('data', (d) => { this.buf = Buffer.concat([this.buf, d]); this.pump(); });
    sock.on('close', () => { this.closed = true; this.pump(); });
    sock.on('error', () => { this.closed = true; this.pump(); });
  }
  pump() {
    while (this.waiters.length > 0) {
      const w = this.waiters[0];
      if (this.buf.length >= w.n) {
        this.waiters.shift();
        w.resolve(this.buf.subarray(0, w.n));
        this.buf = this.buf.subarray(w.n);
      } else if (this.closed) {
        this.waiters.shift();
        w.resolve(null);
      } else {
        break;
      }
    }
  }
  read(n, timeoutMs = 20000) {
    return new Promise((resolve) => {
      let done = false;
      const w = { n, resolve: (v) => { if (!done) { done = true; resolve(v); } } };
      this.waiters.push(w);
      this.pump();
      setTimeout(() => { if (!done) {
        const i = this.waiters.indexOf(w);
        if (i >= 0) { this.waiters.splice(i, 1); }
        done = true; resolve(null);
      } }, timeoutMs);
    });
  }
  async readInt() { const b = await this.read(4); return b ? b.readInt32BE(0) : null; }
  async readBool() { const b = await this.read(1); return b ? b[0] === 1 : null; }
  async readString() {
    const len = await this.readInt();
    if (len === null) { return null; }
    if (len < 0) { return ''; }
    const b = await this.read(len);
    return b ? b.toString('utf8') : null;
  }
}

function i32(n) { const b = Buffer.alloc(4); b.writeInt32BE(n | 0, 0); return b; }

let fileCount = 0;
const server = net.createServer(async (sock) => {
  const peer = `${sock.remoteAddress}:${sock.remotePort}`;
  log(`═══ TCP 连接来自 ${peer}`);
  sock.setNoDelay(true);
  const rd = new FrameReader(sock);
  try {
    const magic = await rd.read(4);
    if (magic === null) { log('  未收到魔数，断开'); sock.end(); return; }
    log(`  魔数 = 0x${magic.toString('hex')} (期望 0x${(LanConfig.MAGIC_NUM >>> 0).toString(16)})`);

    const ver = await rd.readInt();
    log(`  协议代次 = ${ver} (NEW_VERSION_4 = ${LCmd.NEW_VERSION_4})`);
    if (ver !== LCmd.NEW_VERSION_4) { log('  非 v4，断开'); sock.end(); return; }

    const devJson = await rd.readString();
    log(`  对端设备 JSON (${devJson === null ? 0 : devJson.length}B): ${devJson}`);

    const cmd = await rd.readInt();
    log(`  cmd = ${cmd} (FS_SHARE_FILE = ${LCmd.FS_SHARE_FILE})`);
    if (cmd !== LCmd.FS_SHARE_FILE) { log('  非文件共享命令，断开'); sock.end(); return; }

    const encData = await rd.readBool();
    log(`  encData = ${encData}`);

    const transferJson = await rd.readString();
    log(`  传输清单 (${transferJson === null ? 0 : transferJson.length}B): ${transferJson}`);

    let items = [];
    try { items = JSON.parse(transferJson).files || []; } catch (_e) { /* ignore */ }
    log(`  → 回 FS_AGREE，准备接收 ${items.length} 项`);
    sock.write(i32(LCmd.FS_AGREE));

    for (const it of items) {
      const expect = Number(it.length) || 0;
      log(`  接收 ${it.name} (声明 ${expect}B, fileType=${it.fileType})`);
      let got = 0;
      let bad = false;
      const chunks = [];
      while (got < expect) {
        const len = await rd.readInt();
        if (len === null) { log('    连接中断'); bad = true; break; }
        if (len <= 0) { log(`    收到 length=${len}，中止`); bad = true; break; }
        const body = await rd.read(len);
        if (body === null) { log('    数据未读满'); bad = true; break; }
        chunks.push(body);
        got += body.length;
        if (chunks.length === 1) {
          const head = body.subarray(0, Math.min(48, body.length)).toString('utf8').replace(/\n/g, '\\n');
          log(`    首片内容: "${head}"`);
        }
      }
      const whole = Buffer.concat(chunks);
      const outDir = path.join(__dirname, 'recv');
      fs.mkdirSync(outDir, { recursive: true });
      const outFile = path.join(outDir, String(it.name));
      fs.writeFileSync(outFile, whole);
      fileCount++;
      log(`  ${bad ? '✗' : '✓'} ${it.name}: 收到 ${got}/${expect} B，已写入 ${outFile}`);
    }
  } catch (e) {
    log(`  处理异常: ${e.message}`);
  } finally {
    setTimeout(() => sock.end(), 500);
  }
});
server.on('error', (e) => log(`TCP server error: ${e.code} ${e.message}`));
server.listen(TCP_PORT, '0.0.0.0', () => {
  log(`TCP v4 接收端已监听 0.0.0.0:${TCP_PORT}`);
  log('准备就绪。请在鸿蒙 App 的设备列表里找到 "PC-Probe(Windows)" 并发送文件。');
});

setInterval(() => {
  log(`… 心跳 ${udpSent} 次，已接收 ${fileCount} 个文件`);
}, 30000);
