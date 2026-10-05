/**
 * v5 / 1101 「块级应答」探针 —— 完全复刻 PC 端 baseSend 的时序。
 *
 * ## 为什么要这个脚本
 * 真机故障：PC → 手机发文件，进度恰好卡在 2097140 字节（= PC 的块尺寸）后不动。
 * PC 端 exe（带 C++ 符号表）反汇编 `baseSend` / `LANShare::sendOneSeg` 的循环体：
 *
 *     IOUtils::read(buf, 2097152 - headerSize)   // 2097140
 *     DataEnc::setByteCmd(1)                     // FS_DATA
 *     TCPClient::send(块)
 *     b = 0 ; TCPClient::recvo(&b, 1, 0)         // ★ 阻塞 recv 1 字节，无超时
 *     if (b == 6) 中止 ; else 发下一块
 *
 * 所以：**每发一块必须收到 1 字节，否则对端永久阻塞**。
 *
 * 本脚本用同一时序发包：
 *   · 对着 5.0.18（无块级应答）→ 必然卡在第 1 块之后（复现故障）
 *   · 对着 5.0.19（已修）      → 每块都收到 1 字节，整份发完
 *
 * 用法：node v5_blockack_probe.mjs [ip] [port] [chunks] [ackTimeoutMs]
 */

import net from 'node:net';

const HOST = process.argv[2] || '192.168.10.146';
const PORT = Number(process.argv[3] || 5856);
const CHUNKS = Number(process.argv[4] || 3);
const ACK_MS = Number(process.argv[5] || 6000);

/** PC 的块尺寸：2MB 缓冲 - 12 字节头 */
const CHUNK = 2097140;
const NAME = 'v5_blockack_probe.bin';
const TOTAL = CHUNK * CHUNKS;

const MAGIC = Buffer.from([0x66, 0x67, 0x73, 0x71]); // 'fgsq'

const be32 = (v) => { const b = Buffer.alloc(4); b.writeInt32BE(v | 0, 0); return b; };
const be64 = (v) => { const b = Buffer.alloc(8); b.writeBigInt64BE(BigInt(v), 0); return b; };
const str = (s) => { const e = Buffer.from(s, 'utf8'); return Buffer.concat([be32(e.length), e]); };
const frame = (cmd, arg, payload) => Buffer.concat([be32(cmd), be32(arg), be32(payload.length), payload]);
const dataFrame = (p) => Buffer.concat([Buffer.from([1, 0xff, 0xff, 0xff]), be32(0), be32(p.length), p]);
const endFrame = () => Buffer.concat([Buffer.from([2, 0xff, 0xff, 0xff]), be32(0), be32(0)]);

function sharePayload() {
  return Buffer.concat([
    be32(5381), str('192.168.10.186'), str('V5-BLOCKACK-PROBE'), be32(0),
    str('probe-blockack-5'), be32(5), be32(100), Buffer.from([0]), be32(0),
    Buffer.from([0]), // encData = false
  ]);
}
function itemPayload(size) {
  return Buffer.concat([be64(size), str(NAME), be32(3001), str('')]);
}
function makeChunk(size) {
  const b = Buffer.alloc(size);
  for (let i = 0; i < size; i += 4096) b.write('LANSHARE-BLOCKACK', i, Math.min(17, size - i), 'utf8');
  return b;
}

const t0 = Date.now();
const at = () => `+${Date.now() - t0}ms`;
console.log(`目标 ${HOST}:${PORT}  推 ${CHUNKS} 块 × ${CHUNK} = ${TOTAL} 字节`);
console.log(`时序：完全复刻 PC —— 发一块 → 阻塞 recv 1 字节（超时 ${ACK_MS}ms）→ 才发下一块\n`);

const sock = net.connect(PORT, HOST);
sock.setNoDelay(true);
let rx = Buffer.alloc(0);
let extra = 0;
sock.on('data', (d) => { rx = Buffer.concat([rx, d]); });
sock.on('error', (e) => console.log(`  !! socket 错误: ${e.message}`));
sock.on('close', () => console.log(`  -- 连接关闭（${at()}）`));

function write(buf) {
  return new Promise((resolve) => {
    if (sock.write(buf)) resolve();
    else sock.once('drain', resolve);
  });
}
async function readN(n, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (rx.length < n) {
    if (Date.now() > deadline) return null;
    await new Promise((r) => setTimeout(r, 10));
  }
  const out = rx.subarray(0, n);
  rx = rx.subarray(n);
  return out;
}

await new Promise((r) => sock.once('connect', r));
console.log(`  ++ 已连接（${at()}）`);

await write(MAGIC);
await write(frame(1101, 1, sharePayload()));
await write(frame(-1, 0, itemPayload(TOTAL)));
console.log(`  → MAGIC + 1101 首帧 + 清单帧 已发，等 AGREE…`);

const agree = await readN(12, 8000);
if (agree === null) { console.log(`  !! 8s 无 AGREE，中止`); sock.destroy(); process.exit(2); }
console.log(`  ← AGREE cmd=${agree.readInt32BE(0)}（${at()}）`);

const data = makeChunk(CHUNK);
let okBlocks = 0;
let badByte = null;
let stalled = false;
for (let i = 0; i < CHUNKS; i++) {
  await write(dataFrame(data));
  const t = Date.now();
  const ack = await readN(1, ACK_MS);
  if (ack === null) {
    stalled = true;
    console.log(`  ✗ 块 ${i + 1}/${CHUNKS}：发送后 ${Date.now() - t}ms 内**没收到任何应答字节** —— 对端缺块级应答`);
    break;
  }
  const b = ack[0];
  console.log(`  ✓ 块 ${i + 1}/${CHUNKS} 应答 = ${b}${b === 6 ? ' (FS_BREAK 中止)' : ''}，往返 ${Date.now() - t}ms（${at()}）`);
  if (b === 6) { badByte = b; break; }
  okBlocks++;
}

if (!stalled && badByte === null) {
  await write(endFrame());
  console.log(`  → FS_END 已发（${at()}）`);
  const tail = await readN(1, 3000);
  console.log(tail ? `  ← 收尾应答 = ${tail[0]}` : `  ← 收尾 3s 内无字节（可有可无）`);
}
extra = rx.length;

console.log('\n================ 结论 ================');
if (stalled) {
  console.log(`✗ 失败：收到 ${okBlocks}/${CHUNKS} 块级应答，卡在第 ${okBlocks + 1} 块。`);
  console.log('  ⇒ 对端（此 HAP）未实现「每收一块回 1 字节」，与 PC 端 baseSend 的阻塞 recv 死锁。');
  console.log(`  这正是用户看到的「进度卡在 ${(CHUNK / TOTAL * 100).toFixed(0)}% 后失败」。`);
} else if (badByte !== null) {
  console.log(`✗ 对端回 6（FS_BREAK）主动中止。`);
} else {
  console.log(`✓ 通过：${okBlocks}/${CHUNKS} 块全部收到应答，${TOTAL} 字节推送完成，用时 ${Date.now() - t0}ms。`);
  console.log('  ⇒ 块级应答已实现，PC 端不会再卡在第一块。');
}
await new Promise((r) => setTimeout(r, 500));
sock.end();
