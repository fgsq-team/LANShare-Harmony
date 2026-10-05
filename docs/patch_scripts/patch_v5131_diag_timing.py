# -*- coding: utf-8 -*-
"""
v5.1.13-diag —— **纯诊断版**，不改任何传输行为。

## 为什么是诊断版
5.1.13 做了「缓冲复用 + 加密查表」，vivi 实测**速度与 5.1.12 无任何区别**。
按纪律：**「改了但没好」连着两轮 ⇒ 停止猜测，改用观测。**
本版只往发送循环里插入时间戳，把「每块 34ms」拆成四段，问出瓶颈在哪一段。

## ★ 顺带纠正一个此前推理错误（重要）
前一轮我写过「块级应答（一块一等）在 RTT 1ms 时上限 2000MB/s ⇒ RTT 不是瓶颈」。
**这个推理用错了路**：块级 ack 只存在于 **1110 分片路**（`readExactly(1)` 在 :472 / :826），
而**当前 `SEG_SEND_ENABLED = false`，发送一律走 1101**，
而 **1101 循环里根本没有 ack 等待**（全函数无 `readExactly`/`recvo`）
⇒ **1101 本来就是「不等 ack 连续流式发」**，滑动窗口那一层已经在了。
所以「RTT/窗口不够」这条线索**不适用于当前发送路径**，必须重新观测。

## 插桩内容（每块 4 个时间戳，只在低频路径）
按低频采样：**每 16 块打一次**（1MiB/块 ⇒ 每 16MB 一行），
避免日志本身变瓶颈（5.0.68 的教训：诊断日志绝不能放在渲染路径/高频路径）。

四段耗时：
  tRead    = readChunkInto（同步 readSync，阻塞主线程）
  tEnc     = encData（CPU 逐字节/查表）
  tCopy    = rawBuffer().set(...)（1MB 内存拷贝）
  tSend    = await chan.send(...)（含 toArrayBuffer 的 slice 拷贝 + socket 写 + 等回执）
  tWait    = 其余（onChunk 回调、progress 上报等）

输出行形如：
  [DIAG] blk#32 1.00MB tot=31.8ms read=2.1 enc=6.0 copy=0.8 send=22.5 other=0.4

## 诊断完请把这段日志发我
判读表：
  send 占绝大多数（>70%）⇒ 瓶颈在 **socket 写 / toArrayBuffer 的 slice 拷贝**
      → 优化方向是消掉第 3 次拷贝（`toArrayBuffer` 的 `slice`）或换写 API
  read+enc 占多数 ⇒ 本机 CPU/IO 瓶颈（那 5.1.13 的优化本该有效，实测无效说明另有原因）
  other 占多数 ⇒ `onChunk` 进度回调/UI 刷新在拖累
  **若四段加起来 << tot** ⇒ 说明耗时在 `await` 之间的**事件循环排队**
      ⇒ ArkTS 单线程被别的任务（UI 重建/日志落盘/服务循环）抢占
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
PATH = os.path.join(ROOT, 'entry/src/main/ets/service/V5Transfer.ets')
SENT = '5.1.13-diag'

# ---------------------------------------------------------------- 1. 常量
OLD1 = """/** 分片 payload 上限：1MB - 12 字节头。见文件头说明 */
const CHUNK: number = 1024 * 1024 - 12;"""

NEW1 = """/** 分片 payload 上限：1MB - 12 字节头。见文件头说明 */
const CHUNK: number = 1024 * 1024 - 12;

/**
 * ★★ 5.1.13-diag（**纯诊断版，可随时回退**）：
 * 5.1.13 的「缓冲复用 + 加密查表」实测**速度无变化** ⇒ 停止猜测，改用观测。
 *
 * 本常量 = 诊断采样间隔（块）。1MiB/块 ⇒ 每 16 块打一行（即每 16MB 一行）。
 * ⚠️ **必须是低频**：每块打日志本身会变成瓶颈（5.0.68 的教训）。
 * 设为 0 或 1 可关闭诊断打点。
 */
const DIAG_SAMPLE_EVERY: number = 16;"""

# ---------------------------------------------------------------- 2. 循环插桩
OLD2 = """      while (subTotal < size) {
        const want: number = Math.min(CHUNK, size - subTotal);
        if (readBuf.length !== want) {
          readBuf = new Uint8Array(want);
        }
        // 复用 readBuf，不再每块 new。
        const n: number = src.readChunkInto(readBuf, want);
        if (n <= 0) {
          break;
        }
        if (encData) {
          // ★ index 仍是「本文件已发送字节数」subTotal —— 与原实现逐位一致。
          FileCrypto.encData(readBuf, n, 0, subTotal);
        }
        frame.resetKeepHeader();
        frame.setStreamCmd(LCmd.FS_DATA);
        frame.rawBuffer().set(readBuf.subarray(0, n), 12);
        frame.advance(n);
        await chan.send(frame.bytes());
        subTotal += n;
        chunkCount += 1;
        const percent: number = Math.floor(subTotal * 100 / size);
        if (percent !== lastPercent || subTotal >= size) {
          lastPercent = percent;
          onChunk(subTotal, size);
        }
      }"""

NEW2 = """      while (subTotal < size) {
        const want: number = Math.min(CHUNK, size - subTotal);
        if (readBuf.length !== want) {
          readBuf = new Uint8Array(want);
        }
        // ── 5.1.13-diag：分段计时（只观测，不改行为）────────────────────────
        const dT0: number = Date.now();
        // 复用 readBuf，不再每块 new。
        const n: number = src.readChunkInto(readBuf, want);
        if (n <= 0) {
          break;
        }
        const dT1: number = Date.now();
        if (encData) {
          // ★ index 仍是「本文件已发送字节数」subTotal —— 与原实现逐位一致。
          FileCrypto.encData(readBuf, n, 0, subTotal);
        }
        const dT2: number = Date.now();
        frame.resetKeepHeader();
        frame.setStreamCmd(LCmd.FS_DATA);
        frame.rawBuffer().set(readBuf.subarray(0, n), 12);
        frame.advance(n);
        const dT3: number = Date.now();
        await chan.send(frame.bytes());
        const dT4: number = Date.now();
        // ── 诊断行 ────────────────────────────────────────────────────────
        chunkCount += 1;
        if (DIAG_SAMPLE_EVERY > 0 && chunkCount % DIAG_SAMPLE_EVERY === 0) {
          const tRead: number = dT1 - dT0;
          const tEnc: number = dT2 - dT1;
          const tCopy: number = dT3 - dT2;
          const tSend: number = dT4 - dT3;
          const tTotal: number = dT4 - dT0;
          const mib: number = subTotal / 1024 / 1024;
          const mbps: number = tTotal > 0 ? (subTotal / 1024 / 1024) * 1000 / tTotal : 0;
          Log.i(TAG, `[DIAG] blk#${chunkCount} ${mib.toFixed(1)}MB `
            + `tot=${tTotal}ms read=${tRead} enc=${tEnc} copy=${tCopy} send=${tSend} `
            + `other=${tTotal - tRead - tEnc - tCopy - tSend} | avg=${mbps.toFixed(1)}MB/s`);
        }
        subTotal += n;
        const percent: number = Math.floor(subTotal * 100 / size);
        if (percent !== lastPercent || subTotal >= size) {
          lastPercent = percent;
          onChunk(subTotal, size);
        }
      }"""

# ---------------------------------------------------------------- 3. 文件级汇总加「块均」
OLD3 = """    const ms: number = Date.now() - startedAt;
    Log.i(TAG, `v5 已发送 ${item.name} (${subTotal} B, ${chunkCount} 片, ${ms}ms)`);
    return true;
  }"""

NEW3 = """    const ms: number = Date.now() - startedAt;
    const mbps: number = ms > 0 ? (subTotal / 1024 / 1024) * 1000 / ms : 0;
    // ★ 5.1.13-diag：汇总行加了「块均耗时」，配合上面的 DIAG 行一起看。
    Log.i(TAG, `v5 已发送 ${item.name} (${subTotal} B, ${chunkCount} 片, ${ms}ms, `
      + `${mbps.toFixed(1)}MB/s, 块均 ${chunkCount > 0 ? (ms / chunkCount).toFixed(1) : '0'}ms)`);
    return true;
  }"""

EDITS = [(OLD1, NEW1), (OLD2, NEW2), (OLD3, NEW3)]

s = io.open(PATH, encoding='utf-8').read()

if '--dry' in sys.argv:
    for old, new in EDITS:
        c = s.count(old)
        print('  OLD 命中 %d' % c)
        assert c == 1, c
        s = s.replace(old, new, 1)
    print('DRY-RUN OK')
    raise SystemExit(0)

for old, new in EDITS:
    c = s.count(old)
    assert c == 1, 'OLD 命中 %d（应 1）' % c
    s = s.replace(old, new, 1)

assert '\r\n' not in s, 'CRLF 混入'
for old, new in EDITS:
    assert '\ufffd' not in new, '新增文本含坏字符'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(s)
print('APPLIED  %d chars' % len(s))
