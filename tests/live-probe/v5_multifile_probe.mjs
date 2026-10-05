/**
 * v5 / 1101 **多文件**探针 —— 复现并回归「PC 一次发多个文件，第 2 个起失败」。
 *
 * ## 它回答什么问题
 * 单文件已经修好（5.0.19 块级应答）。但 1101 路径还有一个**文件边界**缺陷：
 *
 *   - 发送端（PC `baseSend` / 1.35 `LANService.D` / 我方 `sendPlain`）在**每个文件**
 *     的数据块发完之后，一定会补发一帧 **12 字节结束帧**：
 *         head[0] = 2 (FS_END)，head[4..7] = arg = 0，head[8..11] = len = 0
 *     （PC 取证：`0x1400224c0: movl $2,%edx; callq DataEnc::setByteCmd` → `send(data,len,0)`；
 *       1.35 取证：`dump_D.txt` 320-343，`v0[0] = (thatSend==declared) ? 2 : 3`，`write(v0,0,12)`）
 *
 *   - 接收端（PC `baseRecv`）就是**靠这一帧判文件结束**的：
 *         `0x140022f48: cmpb $2,%al ; je 0x140022f10`  → 读到 FS_END 就退出，且**不回 ack**
 *
 *   - 而我方 `V5Transfer.recvBody()` 的循环条件是 `while (subTotal < item.length)`，
 *     **字节数一收满就跳出**，根本不去读那一帧 FS_END。于是它留在 TCP 缓冲区里，
 *     被**下一个文件的 recvBody** 当成帧头读走 → `head[0] == FS_END` → `break`
 *     → `subTotal(0) != item.length` → 返回 false → `receive()` 回 FS_BREAK(6) → 整体失败。
 *
 *   单文件不受影响（收完就结束，没有「下一个文件」去踩那帧）。
 *
 * ## 本脚本的时序 = 逐字对齐 PC `baseSend`
 *   发一块 → 等 1 字节 ack（阻塞） → 再发下一块 …
 *   最后一块的 ack 收到后 → 发 12 字节 FS_END 帧 → **不读**（PC 也不读）
 *   然后立刻开始下一个文件的第一块。
 *
 * ## 判据
 *   - **修复前（≤5.0.19）**：文件 1 落盘成功，文件 2 失败 —— 探针会看到
 *     文件 2 之后的 ack 序列里出现 `6`(FS_BREAK)，或连接被对端关掉。
 *   - **修复后（≥5.0.20）**：两个文件都落盘，ack 序列全是 `5`。
 *     以手机 hilog `v5 已保存 …` 出现 **2 条**为准。
 *
 * 用法：node v5_multifile_probe.mjs [ip] [port] [fileCount] [blocksPerFile] [ackTimeoutMs]
 */

import net from 'node:net';

const HOST = process.argv[2] || '192.168.10.146';
const PORT = Number(process.argv[3] || 5856);
const FILES = Number(process.argv[4] || 2);
const BLOCKS = Number(process.argv[5] || 2);
const ACK_MS = Number(process.argv[6] || 8000);

/** 1.35 / PC 共用的块尺寸（2MB 缓冲 - 12 字节头） */
const CHUNK = 2097140;
const MARK = 'LANSHARE-MULTI';           // 15 字节
const MAGIC = Buffer.from([0x66, 0x67, 0x73, 0x71]); // 'fgsq'

const be32 = (v) => { const b = Buffer.alloc(4); b.writeInt32BE(v | 0, 0); return b; };
const be64 = (v) => { const b = Buffer.alloc(8); b.writeBigInt64BE(BigInt(v), 0); return b; };
const str = (s) => { const e = Buffer.from(s, 'utf8'); return Buffer.concat([be32(e.length), e]); };

/** v5 帧 = 12 字节大端头 + payload */
function frame(cmd, arg, payload) {
  return Buffer.concat([be32(cmd), be32(arg), be32(payload.length), payload]);
}

/** 数据帧：头[0]=1 (FS_DATA)，其余 3 字节 0xFF（1.35 的 g() 行为） */
function dataFrame(payload) {
  return Buffer.concat([Buffer.from([1, 0xff, 0xff, 0xff]), be32(0), be32(payload.length), payload]);
}

/** ★ 结束帧：头[0]=2 (FS_END)，arg=0，len=0 —— PC/1.35 在每个文件末尾都发这一帧 */
function endFrame() {
  return Buffer.concat([Buffer.from([2, 0xff, 0xff, 0xff]), be32(0), be32(0)]);
}

/** 1101 首帧 payload = 设备头 + byte(encData=0) */
function sharePayload() {
  return Buffer.concat([
    be32(5381),
    str('192.168.10.186'),
    str('PC-MULTIFILE-PROBE'),
    be32(0),
    str('probe-multi-5'),
    be32(5),
    be32(100),
    Buffer.from([0]),
    be32(0),
    Buffer.from([0]),
  ]);
}

/** 清单帧 payload = long 长度 / str 名 / int 类型 / str 附加 */
function itemPayload(size, name) {
  return Buffer.concat([be64(size), str(name), be32(3001), str('')]);
}

/** 每 4096 字节开头埋一个标记，其余填 0 —— 便于事后做内容校验 */
function makeChunk(size, tag) {
  const b = Buffer.alloc(size);
  for (let i = 0; i < size; i += 4096) {
    b.write(`${MARK}-${tag}`, i, Math.min(MARK.length + 3, size - i), 'utf8');
  }
  return b;
}

const perFile = CHUNK * BLOCKS;
const names = [];
for (let i = 0; i < FILES; i++) names.push(`v5_multi_f${i + 1}.bin`);

const t0 = Date.now();
console.log(`目标 ${HOST}:${PORT}  ${FILES} 个文件 × ${BLOCKS} 块 × ${CHUNK} = 每文件 ${perFile} B`);
console.log('时序：完全复刻 PC baseSend（每块后阻塞读 1 字节 ack；文件末尾补发 FS_END 帧）\n');

const sock = net.connect(PORT, HOST);
sock.setNoDelay(true);
let rx = Buffer.alloc(0);
const ackSeq = [];          // 所有收到的应答字节（诊断用）
let peerClosed = false;

sock.on('data', (d) => {
  rx = Buffer.concat([rx, d]);
  for (const b of d) ackSeq.push(b);
});
sock.on('error', (e) => console.log(`  !! socket 错误: ${e.message}`));
sock.on('close', () => { peerClosed = true; console.log(`  -- 连接被关闭（+${Date.now() - t0}ms）`); });

function write(buf) {
  return new Promise((resolve) => {
    if (sock.write(buf)) resolve();
    else sock.once('drain', resolve);
  });
}

async function readN(n, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (rx.length < n) {
    if (Date.now() > deadline || peerClosed) return null;
    await new Promise((r) => setTimeout(r, 10));
  }
  const out = rx.subarray(0, n);
  rx = rx.subarray(n);
  return out;
}

await new Promise((r) => sock.once('connect', r));
console.log(`  ++ 已连接（+${Date.now() - t0}ms）`);

// ---- 1. MAGIC + 1101 首帧 + 全部清单帧（清单必须紧跟首帧，接收端读完 count 帧才回 AGREE）----
await write(MAGIC);
await write(frame(1101, FILES, sharePayload()));
for (let i = 0; i < FILES; i++) {
  await write(frame(-1, 0, itemPayload(perFile, names[i])));
}
console.log(`  → 已发 MAGIC + 1101(arg=${FILES}) + ${FILES} 个清单帧，等 AGREE…`);

const agree = await readN(12, 8000);
if (agree === null) {
  console.log(`  !! 8s 内没等到 AGREE —— 收端未进 receive()，中止`);
  sock.destroy();
  process.exit(2);
}
console.log(`  ← AGREE cmd=${agree.readInt32BE(0)}（+${Date.now() - t0}ms）\n`);

// ---- 2. 逐文件发送：块 → 等 ack → … → FS_END 帧 ----
let failedAt = -1;
for (let f = 0; f < FILES; f++) {
  const tag = `f${f + 1}`;
  const chunk = makeChunk(CHUNK, tag);
  console.log(`  === 文件 ${f + 1}/${FILES}  ${names[f]}  (${perFile} B) ===`);

  for (let b = 0; b < BLOCKS; b++) {
    await write(dataFrame(chunk));
    const ack = await readN(1, ACK_MS);
    if (ack === null) {
      console.log(`    ✗ 块 ${b + 1}/${BLOCKS}：${ACK_MS}ms 内没收到 ack（peerClosed=${peerClosed}）`);
      failedAt = f;
      break;
    }
    const v = ack[0];
    const tagTxt = v === 5 ? 'FS_NEXT ✓' : (v === 6 ? '★ FS_BREAK（对端中止）' : `未知 ${v}`);
    console.log(`    ✓ 块 ${b + 1}/${BLOCKS} ack = ${v} (${tagTxt})  +${Date.now() - t0}ms`);
    if (v === 6) { failedAt = f; break; }
  }
  if (failedAt >= 0) break;

  // ★ 文件末尾补发 FS_END 帧 —— 这正是当前实现「不吃」的那一帧
  await write(endFrame());
  console.log(`    → 已补发 FS_END 帧（PC/1.35 每个文件末尾都发）`);
}

// ---- 3. 收尾：把残留应答读干净（PC 此时其实不读，这里读只是为了拿到诊断序列）----
await new Promise((r) => setTimeout(r, 700));
while (rx.length > 0) {
  const a = await readN(1, 200);
  if (a === null) break;
}

console.log(`\n---- 汇总 ----`);
console.log(`收到应答字节序列： [${ackSeq.join(', ')}]`);
console.log(`（期望：${FILES} 个文件 × ${BLOCKS} 块 = ${FILES * BLOCKS} 个 5，可能夹杂 receive() 的文件级 5）`);
if (failedAt >= 0) {
  console.log(`\n✗ 失败：在第 ${failedAt + 1} 个文件处中断。`);
  console.log(`  若这是 ≤5.0.19：正是「recvBody 吃掉对端 FS_END 帧导致多文件错位」的复现。`);
} else {
  console.log(`\n✓ 通过：${FILES} 个文件全部按 PC 时序发完并逐块收到应答。`);
}
console.log(`\n请核对手机 hilog：应出现 ${FILES} 条 \`v5 已保存\`，落盘大小各为 ${perFile} B。`);
console.log(`   hdc shell "hilog -x -T V5Transfer" | grep "v5 已保存"`);

await new Promise((r) => setTimeout(r, 300));
sock.end();
setTimeout(() => process.exit(failedAt >= 0 ? 1 : 0), 400);
