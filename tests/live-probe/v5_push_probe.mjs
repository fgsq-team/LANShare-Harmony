/**
 * v5 / 1101 判据探针 —— 「手工当发送端」，把收发两侧解耦。
 *
 * ## 它回答什么问题
 * 真机现象：PC → 手机发大文件，进度恰好卡在 **2097140 字节**（= 1.35 的 chunk = 2MB - 12），
 * 20 秒后 PC 报失败；手机侧 hilog 打 `TcpChannel: readExactly 超时: 需要 12，现有 0`。
 * 2097140 正好是 `dump_y.txt` 里 1.35 的块尺寸常量 —— 即「发完第一个块就停了」。
 *
 * 两种可能，本脚本用来二选一：
 *   (A) 手机接收管线自身有天花板（收到第一块后不再消费）→ 本脚本同样会卡住；
 *   (B) PC 端发完一块后在等某种应答 → 手机没问题，本脚本能一次性推完。
 *
 * 关键设计：本脚本**严格按 1.35 原生发送端的语义**——
 *   `dump_D.txt` 里发送端读应答是 `while (in.available() > 0) { b = read(); if (b == 6) break; }`，
 *   **非阻塞**，从不等待。所以这里推完所有块之前**一个字节都不读**。
 *
 * 用法：node v5_push_probe.mjs [ip] [port] [chunks]
 */

import net from 'node:net';

const HOST = process.argv[2] || '192.168.10.146';
const PORT = Number(process.argv[3] || 5856);
const CHUNKS = Number(process.argv[4] || 3);

/** 1.35 的块尺寸（2MB 缓冲 - 12 字节头）—— 正是真机上卡住的那个数 */
const CHUNK = 2097140;
const NAME = 'v5_push_probe.bin';

const MAGIC = Buffer.from([0x66, 0x67, 0x73, 0x71]); // 'fgsq'

const be32 = (v) => { const b = Buffer.alloc(4); b.writeInt32BE(v | 0, 0); return b; };
const be64 = (v) => { const b = Buffer.alloc(8); b.writeBigInt64BE(BigInt(v), 0); return b; };
const str = (s) => { const e = Buffer.from(s, 'utf8'); return Buffer.concat([be32(e.length), e]); };

/** v5 帧 = 12 字节大端头 + payload */
function frame(cmd, arg, payload) {
  return Buffer.concat([be32(cmd), be32(arg), be32(payload.length), payload]);
}

/** 数据帧：头[0] 写单字节流命令，其余 3 字节补 0xFF（1.35 的 g() 行为） */
function dataFrame(payload) {
  return Buffer.concat([Buffer.from([1, 0xff, 0xff, 0xff]), be32(0), be32(payload.length), payload]);
}

/** 结束帧：头[0] = 2 (FS_END)，无 payload */
function endFrame() {
  return Buffer.concat([Buffer.from([2, 0xff, 0xff, 0xff]), be32(0), be32(0)]);
}

/** 1101 首帧 payload = 设备头 + byte(encData=0) */
function sharePayload() {
  return Buffer.concat([
    be32(5381),                 // devPort
    str('192.168.10.186'),      // devIp
    str('V5-PUSH-PROBE'),       // devName
    be32(0),                    // devMode
    str('probe-0000-5'),        // uniqueUuid-版本
    be32(5),                    // dataVersion
    be32(100),                  // batteryLevel
    Buffer.from([0]),           // chargeStatus
    be32(0),                    // 已知设备数 = 0
    Buffer.from([0]),           // encData = false
  ]);
}

/** 清单帧 payload = long 长度 / str 名 / int 类型 / str 附加（不写 mediaId，故 remaining=0） */
function itemPayload(size) {
  return Buffer.concat([be64(size), str(NAME), be32(3001), str('')]);
}

/** 造一块可校验的负载：每 4096 字节开头写 'LANSHARE-PROBE' */
function makeChunk(size) {
  const b = Buffer.alloc(size);
  for (let i = 0; i < size; i += 4096) {
    b.write('LANSHARE-PROBE', i, Math.min(14, size - i), 'utf8');
  }
  return b;
}

const total = CHUNK * CHUNKS;
const t0 = Date.now();
console.log(`目标 ${HOST}:${PORT}  推 ${CHUNKS} 块 × ${CHUNK} = ${total} 字节`);
console.log('策略：推完之前**不读任何应答**（对齐 1.35 原生发送端 in.available() 非阻塞排空）');

const sock = net.connect(PORT, HOST);
sock.setNoDelay(true);
let rx = Buffer.alloc(0);
let wrote = 0;

sock.on('data', (d) => {
  rx = Buffer.concat([rx, d]);
  if (rx.length > 0) {
    console.log(`  ← 收到 ${rx.length} 字节应答: ${[...rx].join(',')}`);
  }
});
sock.on('error', (e) => console.log(`  !! socket 错误: ${e.message}`));
sock.on('close', () => console.log(`  -- 连接关闭（+${Date.now() - t0}ms）`));

/** 等 drain，保证不靠内核缓冲硬灌 */
function write(buf) {
  return new Promise((resolve) => {
    if (sock.write(buf)) { wrote += buf.length; resolve(); }
    else {
      sock.once('drain', () => { wrote += buf.length; resolve(); });
    }
  });
}

async function readN(n, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (rx.length < n) {
    if (Date.now() > deadline) return null;
    await new Promise((r) => setTimeout(r, 20));
  }
  const out = rx.subarray(0, n);
  rx = rx.subarray(n);
  return out;
}

await new Promise((r) => sock.once('connect', r));
console.log(`  ++ 已连接（+${Date.now() - t0}ms）`);

// 1) MAGIC + 1101 首帧 + 清单帧
// ⚠️ 清单帧必须**紧跟**首帧发出去，不能等 AGREE —— 接收端是
//    「先读完 count 个清单帧 → 才回 FS_AGREE」（见 V5Transfer.receive 步骤 1/2），
//    等 AGREE 再发清单会双向死锁。
await write(MAGIC);
await write(frame(1101, 1, sharePayload()));
await write(frame(-1, 0, itemPayload(total)));
console.log(`  → 已发 MAGIC + 1101 首帧 + 清单帧（+${Date.now() - t0}ms），等 AGREE(1102)…`);

// 2) 等 AGREE —— 这是**唯一**一次读，而且是协议规定必须等的
const agree = await readN(12, 8000);
if (agree === null) {
  console.log(`  !! 8s 内没等到 AGREE（收到 ${rx.length} 字节）——收端口没进 receive()，中止`);
  sock.destroy();
  process.exit(2);
}
console.log(`  ← AGREE cmd=${agree.readInt32BE(0)}（+${Date.now() - t0}ms）`);

// 3) 开始灌数据
console.log(`  → 开始灌数据…`);

// 4) 连推 CHUNKS 个块 —— ★ 中途不读任何应答 ★
const data = makeChunk(CHUNK);
for (let i = 0; i < CHUNKS; i++) {
  const t = Date.now();
  await write(dataFrame(data));
  console.log(`  → 块 ${i + 1}/${CHUNKS} 已入内核（本块 ${Date.now() - t}ms，累计写 ${wrote} 字节，+${Date.now() - t0}ms）`);
}

// 5) 结束帧
await write(endFrame());
console.log(`  → 已发 FS_END（累计写 ${wrote} 字节，+${Date.now() - t0}ms）`);

// 6) 现在才读应答：应该是裸单字节 5(FS_NEXT)
const ack = await readN(1, 20000);
if (ack === null) {
  console.log(`  !! 20s 内没收到单字节应答（rx=${rx.length}）`);
} else {
  console.log(`  ← 单字节应答 = ${ack[0]}（5=FS_NEXT 正常 / 6=FS_BREAK 表示被中止）（+${Date.now() - t0}ms）`);
}

console.log(`\n结果：内核侧确认写入 ${wrote} 字节 / 期望 ${MAGIC.length + frame(1101, 1, sharePayload()).length + frame(-1, 0, itemPayload(total)).length + CHUNKS * (12 + CHUNK) + 12}`);
console.log('若手机 hilog 出现 `v5 已保存 … 6291420 B, 3 片` ⇒ 手机接收侧完全正常，问题在 PC 端。');
await new Promise((r) => setTimeout(r, 1500));
sock.end();
