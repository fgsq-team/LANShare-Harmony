/**
 * v5 / 1110（FS_SEG_FILE）判据探针 —— 16 分片并行路径的**块级应答**实测。
 *
 * ## 背景
 * 5.0.19 修的是「每收一块必须立刻回 1 字节 FS_NEXT」。1101（图片）路径已由
 * `v5_blockack_probe.mjs` 验证；1110（文件/apk，16 片并发）走的是**另一条**函数
 * `receiveSegment()`，同样被补了块级应答 —— 但「代码同构」不等于「实测通过」，
 * 所以这里手工当 16 分片发送端，逐条连接核对每一块的应答。
 *
 * ## PC 端真实时序（llvm-objdump 反汇编 `LANShare::sendOneSeg` @0x14002ee50）
 *   loop:
 *     n = io->read(buf + headerSize, 2097152 - headerSize);   // -> 2097140
 *     enc.setByteCmd(1);                                       // FS_DATA
 *     tcp->send(enc.getData(), enc.getDataLen(), 0);
 *     char b = 0;
 *     tcp->recvo(&b, 1, 0);        // ★ 阻塞 recv 1 字节，无超时
 *     if (b == 6) return -3;                                    // FS_BREAK
 *   与 1101 的 baseSend 循环体逐指令同构 —— 所以缺陷与修复也该一致。
 *
 * ## 1110 帧序（一条连接 = 一片）
 *   1) MAGIC(4) + frame(1110, 片数, 设备头 + byte encData)
 *   2) 元数据帧 frame(?, 0, long fileSize / string name / string segId
 *                       / int idx / int total / long start / long len)
 *      — 接收端 `readFrameBody` 只取 len(off 8)，不校验 cmd/arg
 *   3) 本片的数据帧序列（每块 12B 头 + payload），每块后收 1 字节应答
 *   4) 片尾接收端回 2 字节：5(FS_NEXT) 再 2(FS_END)
 *
 * 用法：node v5_seg_probe.mjs [ip] [port] [片数] [每片块数] [应答超时ms]
 */

import net from 'node:net';

const HOST = process.argv[2] || '192.168.10.146';
const PORT = Number(process.argv[3] || 5856);
const SEGS = Number(process.argv[4] || 4);   // 并发几片
const BLOCKS = Number(process.argv[5] || 1); // 每片几块
const ACK_MS = Number(process.argv[6] || 6000);

/** 1.35 写死的块尺寸 = 2MB 缓冲 - 12 字节头 */
const CHUNK = 2097140;
const NAME = 'v5_seg_probe.bin';
/**
 * ★ 16 片共用一个 segId —— 接收端就是靠它把 16 条连接认领到同一个目标文件。
 *
 * ⚠️ **每轮必须换一个 segId**（默认带时间戳，也可用第 7 个参数指定）。
 *   接收端把 SegPart 存在静态 Map 里、以 segId 为键，收齐后只打 `finishedAt`，
 *   由 `purgeFinished()` 在 **60 秒后** 才删除。若两轮用同一个 segId：
 *     · 第二轮 `segs.get(segId)` 命中陈旧条目（fileSize 还是上一轮的）；
 *     · `gotIdx[]` 去重令 `counts=false` → `part.received` **不再累加**；
 *     · 结果：字节照样写盘，但进度冻结在上一轮的 100%（日志里 fileSize 与
 *       「已收 X/X」对不上）。实测踩过。
 *   真实环境不会有这个问题：PC 端 `LANShare::sendFileParallelOne` 用
 *   `Utils::getUUID()`（= QUuid::createUuid 随机 UUID v4）**每次传输现生成**
 *   一个 segId 给整个文件用，不可能重复（llvm-objdump 反汇编 0x1400254c9 取证）。
 */
const SEG_ID = 'seg-probe-' + (process.argv[7] || Date.now().toString(36));

const MAGIC = Buffer.from([0x66, 0x67, 0x73, 0x71]); // 'fgsq'

const be32 = (v) => { const b = Buffer.alloc(4); b.writeInt32BE(v | 0, 0); return b; };
const be64 = (v) => { const b = Buffer.alloc(8); b.writeBigInt64BE(BigInt(v), 0); return b; };
const str = (s) => { const e = Buffer.from(s, 'utf8'); return Buffer.concat([be32(e.length), e]); };

/** v5 帧 = 12 字节大端头(cmd/arg/len) + payload */
function frame(cmd, arg, payload) {
  return Buffer.concat([be32(cmd), be32(arg), be32(payload.length), payload]);
}

/** 数据帧：头[0] 写单字节流命令 1=FS_DATA，其余 3 字节补 0xFF（1.35 `g()` 行为） */
function dataFrame(payload) {
  return Buffer.concat([Buffer.from([1, 0xff, 0xff, 0xff]), be32(0), be32(payload.length), payload]);
}

/** 结束帧：头[0] = 2 (FS_END)，无 payload */
function endFrame() {
  return Buffer.concat([Buffer.from([2, 0xff, 0xff, 0xff]), be32(0), be32(0)]);
}

/** 1110 首帧 payload = 设备头 + byte(encData=0)（与 1101 同构，见 handleV5Segment 注释） */
function sharePayload() {
  return Buffer.concat([
    be32(5381),                 // devPort
    str('192.168.10.186'),      // devIp
    str('V5-SEG-PROBE'),        // devName
    be32(0),                    // devMode
    str('probe-0000-5'),        // uniqueUuid-版本
    be32(5),                    // dataVersion
    be32(100),                  // batteryLevel
    Buffer.from([0]),           // chargeStatus
    be32(0),                    // 已知设备数 = 0
    Buffer.from([0]),           // encData = false
  ]);
}

/** 分片元数据帧 payload —— 字段顺序与 receiveSegment 的解析**逐字对应** */
function metaPayload(fileSize, idx, total, start, len) {
  return Buffer.concat([
    be64(fileSize),  // long fileSize
    str(NAME),       // string name
    str(SEG_ID),     // string segId  ★ 16 片共用
    be32(idx),       // int idx
    be32(total),     // int total
    be64(start),     // long start
    be64(len),       // long len
  ]);
}

/** 造一块可校验负载：每 4096 字节开头写 'LANSHARE-SEG' */
function makeChunk(size) {
  const b = Buffer.alloc(size);
  for (let i = 0; i < size; i += 4096) {
    b.write('LANSHARE-SEG', i, Math.min(12, size - i), 'utf8');
  }
  return b;
}

const perSeg = CHUNK * BLOCKS;
const fileSize = perSeg * SEGS;
const t0 = Date.now();

console.log(`目标 ${HOST}:${PORT}`);
console.log(`并发 ${SEGS} 片 × ${BLOCKS} 块 × ${CHUNK} = 每片 ${perSeg} B，整文件 ${fileSize} B`);
console.log(`segId = ${SEG_ID}（每轮唯一，避免命中上一轮的陈旧 SegPart）`);
console.log(`时序：完全复刻 PC sendOneSeg —— 每发一块，阻塞读 1 字节应答（超时 ${ACK_MS}ms）\n`);

/** 跑一片（= 一条 TCP 连接）。返回 true=全部块都收到应答 */
async function runSeg(i) {
  const start = i * perSeg;
  const tag = `[片 ${i + 1}/${SEGS}]`;
  const sock = net.connect(PORT, HOST);
  sock.setNoDelay(true);
  let rx = Buffer.alloc(0);
  sock.on('data', (d) => { rx = Buffer.concat([rx, d]); });
  sock.on('error', (e) => console.log(`${tag} !! socket 错误: ${e.message}`));

  // ⚠️ 等 drain 必须带兜底：对端收完本片会直接关连接，
  //    此时 write 返回 false 且 **drain 永不触发**（socket 已销毁），
  //    而整个 runSeg 又没有别的活跃定时器 → Node 判定 top-level await
  //    永不 settle，直接以 exit 13 退出（实测踩过）。所以三路合流 + 超时。
  const write = (buf) => new Promise((resolve) => {
    let done = false;
    const fin = () => { if (!done) { done = true; resolve(); } };
    if (sock.write(buf)) return fin();
    sock.once('drain', fin);
    sock.once('close', fin);
    sock.once('error', fin);
    setTimeout(fin, 3000);
  });
  const readN = async (n, timeoutMs) => {
    const deadline = Date.now() + timeoutMs;
    while (rx.length < n) {
      if (Date.now() > deadline) return null;
      await new Promise((r) => setTimeout(r, 5));
    }
    const out = rx.subarray(0, n);
    rx = rx.subarray(n);
    return out;
  };

  try {
    await new Promise((res, rej) => {
      sock.once('connect', res);
      sock.once('error', rej);
    });

    // 1) MAGIC + 1110 首帧 + 元数据帧（**连续发**，不等应答）
    await write(MAGIC);
    await write(frame(1110, SEGS, sharePayload()));
    await write(frame(-1, 0, metaPayload(fileSize, i, SEGS, start, perSeg)));

    // 2) 灌本片数据，每块后等 1 字节应答
    const data = makeChunk(CHUNK);
    for (let b = 0; b < BLOCKS; b++) {
      const bt = Date.now();
      await write(dataFrame(data));
      const ack = await readN(1, ACK_MS);
      if (ack === null) {
        console.log(`${tag} ✗ 块 ${b + 1}/${BLOCKS}：发送后 ${ACK_MS}ms 内没收到应答字节 —— 缺块级应答`);
        sock.destroy();
        return false;
      }
      if (ack[0] !== 5) {
        console.log(`${tag} ✗ 块 ${b + 1}/${BLOCKS}：应答 = ${ack[0]}（期望 5=FS_NEXT）`);
        sock.destroy();
        return false;
      }
      console.log(`${tag} ✓ 块 ${b + 1}/${BLOCKS} 应答 = 5，往返 ${Date.now() - bt}ms`);
    }

    // 3) 片尾：接收端应回 2 字节 —— 5(FS_NEXT) + 2(FS_END)
    await write(endFrame());
    const tail = await readN(2, ACK_MS);
    if (tail === null) {
      console.log(`${tag} ⚠ 片尾只收到 ${rx.length} 字节（期望 2 字节：5 然后 2）`);
    } else {
      console.log(`${tag} ✓ 片尾应答 = [${[...tail].join(', ')}]（期望 [5, 2]）`);
    }
    await new Promise((r) => setTimeout(r, 200));
    sock.end();
    return true;
  } catch (e) {
    console.log(`${tag} !! 异常: ${e.message}`);
    try { sock.destroy(); } catch (_) { /* ignore */ }
    return false;
  }
}

const results = await Promise.all(Array.from({ length: SEGS }, (_, i) => runSeg(i)));
const pass = results.filter(Boolean).length;

console.log(`\n================ 结论 ================`);
if (pass === SEGS) {
  console.log(`✓ 通过：${pass}/${SEGS} 片全部收到逐块应答，${fileSize} 字节推送完成，用时 ${Date.now() - t0}ms。`);
  console.log(`  ⇒ 1110 分片路径的块级应答已实现，PC 发 apk/大文件不会再卡在第 1 块。`);
} else {
  console.log(`✗ 失败：只有 ${pass}/${SEGS} 片通过（${Date.now() - t0}ms）。`);
}
process.exit(pass === SEGS ? 0 : 1);
