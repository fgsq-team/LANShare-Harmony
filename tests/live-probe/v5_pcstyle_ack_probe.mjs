// 仿真 PC 端读取行为的探针（用于验证 ack 字节数是否对得上）。
//
// 背景：PC 端 `LANShare.cpp:250` 每块读 1 字节 ack、`:598` 每个文件之间再读 1 字节，
//       即每文件读 **N+1** 次；且它握手时报的是「**目标设备**」的地址
//       （`makeDataEnc(*p1,…)`），也就是**手机自己的 IP**。
//
// 本探针复刻这两点，用来回答：手机实际回了几个字节？PC 会不会从第 2 个文件起错位？
//
// 用法： node v5_pcstyle_ack_probe.mjs [phoneIp] [port] [files] [blocks]
import net from 'node:net';

const HOST = process.argv[2] || '192.168.10.146';   // 手机
const PORT = Number(process.argv[3] || 5856);
const FILES = Number(process.argv[4] || 3);
const BLOCKS = Number(process.argv[5] || 2);
const ACK_MS = 8000;

/** 仿 PC：宣告的是「目标设备」的地址 —— 对手机而言就是它自己的 IP */
const ANNOUNCE_IP = HOST;

const CHUNK = 2097140;
const MAGIC = Buffer.from([0x66, 0x67, 0x73, 0x71]);

const be32 = (v) => { const b = Buffer.alloc(4); b.writeInt32BE(v | 0, 0); return b; };
const be64 = (v) => { const b = Buffer.alloc(8); b.writeBigInt64BE(BigInt(v), 0); return b; };
const str = (s) => { const e = Buffer.from(s, 'utf8'); return Buffer.concat([be32(e.length), e]); };
const frame = (cmd, arg, payload) => Buffer.concat([be32(cmd), be32(arg), be32(payload.length), payload]);
const dataFrame = (p) => Buffer.concat([Buffer.from([1, 0xff, 0xff, 0xff]), be32(0), be32(p.length), p]);
const endFrame = () => Buffer.concat([Buffer.from([2, 0xff, 0xff, 0xff]), be32(0), be32(0)]);

function sharePayload() {
  return Buffer.concat([
    be32(5381),
    str(ANNOUNCE_IP),          // ★ 对端宣告的地址 = 手机自己的 IP（复刻 PC 的行为）
    str('PC-STYLE-PROBE'),
    be32(0),                   // devMode = 0（不是 ANDROID=1）
    str('probe-pc-style'),
    be32(5),
    be32(100),
    Buffer.from([0]),
    be32(0),
    Buffer.from([0]),
  ]);
}
const itemPayload = (size, name) => Buffer.concat([be64(size), str(name), be32(3001), str('')]);
const makeChunk = (size) => { const b = Buffer.alloc(size); b.fill(0x5a); return b; };

const perFile = CHUNK * BLOCKS;
console.log(`目标 ${HOST}:${PORT}  ${FILES} 文件 × ${BLOCKS} 块`);
console.log(`握手宣告地址 = ${ANNOUNCE_IP}（= 手机自己的 IP，复刻 PC 端 makeDataEnc 的行为）\n`);

const sock = net.connect(PORT, HOST);
sock.setNoDelay(true);
let rx = Buffer.alloc(0);
let closed = false;
const allAck = [];
sock.on('data', (d) => { rx = Buffer.concat([rx, d]); for (const b of d) allAck.push(b); });
sock.on('close', () => { closed = true; });
const write = (buf) => new Promise((res) => { sock.write(buf) ? res() : sock.once('drain', res); });

async function readN(n, timeoutMs) {
  const dl = Date.now() + timeoutMs;
  while (rx.length < n) {
    if (Date.now() > dl || closed) return null;
    await new Promise((r) => setTimeout(r, 5));
  }
  const out = rx.subarray(0, n); rx = rx.subarray(n); return out;
}

await new Promise((r) => sock.once('connect', r));
await write(MAGIC);
await write(frame(1101, FILES, sharePayload()));
for (let i = 0; i < FILES; i++) await write(frame(-1, 0, itemPayload(perFile, `pc_style_${i + 1}.bin`)));

const agree = await readN(12, 8000);
if (!agree) { console.log('!! 没等到 AGREE'); sock.destroy(); process.exit(2); }
console.log(`← AGREE（cmd=${agree.readInt32BE(0)}）\n`);

const chunk = makeChunk(CHUNK);
let desync = false;

for (let f = 0; f < FILES; f++) {
  console.log(`=== 文件 ${f + 1}/${FILES}（PC 读法：N 次块级 = ${BLOCKS} 次）===`);
  for (let b = 0; b < BLOCKS; b++) {
    await write(dataFrame(chunk));
    const a = await readN(1, ACK_MS);
    if (!a) { console.log(`    ✗ 块 ${b + 1}：${ACK_MS}ms 没收到 ack`); desync = true; break; }
    const tag = a[0] === 5 ? 'FS_NEXT' : (a[0] === 2 ? '★FS_END(不是块级 5!)' : (a[0] === 6 ? 'FS_BREAK' : `?${a[0]}`));
    console.log(`    ✓ 块 ${b + 1} ack=${a[0]} (${tag})`);
  }
  if (desync) break;
  await write(endFrame());
  // ★ PC 在文件之间**再读 1 个字节**（LANShare.cpp:598）
  const extra = await readN(1, 1500);
  if (!extra) {
    console.log('    ✗ 文件间那一字节没收到 —— PC 端在这里会永久卡住！');
    desync = true; break;
  }
  console.log(`    ✓ 文件间 ack=${extra[0]}${extra[0] === 5 ? '（= 我方多送的那个 5，PC 本不读它）' : ''}\n`);
}

await new Promise((r) => setTimeout(r, 500));
console.log('---- 汇总 ----');
console.log(`收到应答字节序列： [${allAck.join(', ')}]`);
console.log(`期望（PC 口径 N+1/文件）： ${FILES} 文件 × (${BLOCKS}+1) = ${FILES * (BLOCKS + 1)} 个，且末位应是 2`);
console.log(`实际： ${allAck.length} 个`);
if (allAck.length > FILES * (BLOCKS + 1)) {
  console.log(`\n★ 实测多出 ${allAck.length - FILES * (BLOCKS + 1)} 个字节 ⇒ PC 从第 2 个文件起会读到残留字节（确诊）。`);
}
sock.end();
setTimeout(() => process.exit(0), 300);
