# -*- coding: utf-8 -*-
"""
v5.1.14 —— **双连接并发发送**（真机诊断驱动）

## 诊断依据（5.1.13-diag 真机 40 样本，639MB）
每 1MiB 块平均耗时：
    send 25.95ms (97.2%) | read 0.68ms (2.5%) | copy 0.07ms (0.3%) | enc 0.00ms (0%)
⇒ **本机 CPU 仅占 2.8%**，5.1.13 的优化全落在这 2.8% 里，故零效果。
⇒ `send` 里 97% 是 `await sock.write()` 的**背压等待**
   （socket 缓冲满 ⇒ 等对端读走 ⇒ 等 TCP 窗口）。
⇒ **差距性质 = 单条 TCP 流的窗口/对端消费速度**。
   网页能到 55MB/s 是因为**开多条连接**，每条有独立 TCP 窗口。

## 本版做法：同一批文件开 2 条 1101 连接并发
**按序轮转分配**（不是把同一文件发两遍）—— 对端零特殊处理：
  连接 A：第 0,2,4… 项；连接 B：第 1,3,5… 项
每个连接走的仍是**完全标准的 1101 序列**：
  请求帧(1101+N) → N 个文件清单帧 → 等 FS_AGREE → 数据 → FS_END

## 为什么这个方案安全（逐条核对过）
1. **两条连接各自等自己的 FS_AGREE**（`sendPlain` 步骤 3，:428）—— 互不干扰；
2. **清单帧各自独立**，对端认成两个任务，不需要理解「同文件多连接」；
3. **不使用 1110 分片**（避开 1.35 那 5% 提前 FIN 的 bug）；
4. **不改 CHUNK**（仍 1MB-12，1.35 信令路径只 `new byte[1048576]`）；
5. **不改任何协议字段**，1.35 / PC / 本机 都能收。

## 开关
`SEND_CONCURRENCY = 2`（设为 1 即回退成原来的单连接，行为与 5.1.13 完全一致）。
⚠️ 只在「**文件数 ≥ 2**」时启用 —— 单文件时轮转无意义，仍走单连接。

## 进度上报
两条连接并发时进度会交错，`onReport` 仍按各自文件的真实字节数上报，
UI 侧按 `percent` 取最大值显示（沿用既有逻辑，不新增状态）。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
PATH = os.path.join(ROOT, 'entry/src/main/ets/service/V5Transfer.ets')

# ---------------------------------------------------------------- 1. 并发开关
OLD1 = """const DIAG_SAMPLE_EVERY: number = 16;"""

NEW1 = """const DIAG_SAMPLE_EVERY: number = 16;

/**
 * ★ 5.1.14：1101 发送**并发连接数**（1 = 关闭，行为与 5.1.13 完全一致）。
 *
 * ## 依据（5.1.13-diag 真机 40 样本 / 639MB）
 * 每 1MiB 块：`send 25.95ms (97.2%)`、其余四项合计仅 **2.8%**。
 * ⇒ 本机算力不是瓶颈，`send` 里 97% 是 `await sock.write()` 的**背压等待**
 *   （本机 socket 缓冲满 ⇒ 等对端读走 ⇒ 等 TCP 窗口开）。
 * ⇒ 差距 = **单条 TCP 流的窗口 / 对端消费速度**。
 *   网页能到 55MB/s 正因为它**开多条连接**，每条有独立窗口，聚合带宽远大于单流。
 *
 * ## 为什么不能用 1110 分片
 * 车机 1.35 收完某片全部块 ack 后**偶发提前关连接**（片级失败率 ≈5%，
 * 16 片并发 ⇒ 约 60% 概率至少 1 片中招 ⇒ 整个文件回退 1101 重传）。
 * `SEG_SEND_ENABLED` 因此自 5.0.27 起关闭至今。
 *
 * ## 本版做法
 * 同一批文件开 N 条**标准 1101** 连接并发，文件**按序轮转**分配
 * （连接 A：0,2,4…；连接 B：1,3,5…）。
 * 每条连接走的仍是完全标准的 1101 序列（请求帧 → 清单帧 → 等 FS_AGREE → 数据 → FS_END），
 * **对端零特殊处理**：清单帧各自独立，对端认成两个并行的普通任务。
 */
const SEND_CONCURRENCY: number = 2;"""

# ---------------------------------------------------------------- 2. 调度入口
OLD2 = """    const retryFiles: OutgoingFile[] = plainFiles.concat(segFailed);
    if (retryFiles.length > 0) {
      if (segFailed.length > 0) {
        Log.w(TAG, `v5 分片失败 ${segFailed.length} 个，自动回退到 1101 单连接重传`);
      }
      const okPlain: boolean = await V5Transfer.sendPlain(self, target, retryFiles, encData, onReport);
      if (!okPlain) {
        okAll = false;
      }
    }
    return okAll;
  }"""

NEW2 = """    const retryFiles: OutgoingFile[] = plainFiles.concat(segFailed);
    if (retryFiles.length > 0) {
      if (segFailed.length > 0) {
        Log.w(TAG, `v5 分片失败 ${segFailed.length} 个，自动回退到 1101 单连接重传`);
      }
      // ★ 5.1.14：文件数 ≥ 2 且开关打开时，**按序轮转分给多条连接并发发**。
      //   单文件（轮转无意义）或开关为 1 ⇒ 走原来的单连接，行为不变。
      if (SEND_CONCURRENCY > 1 && retryFiles.length >= 2) {
        const okPar: boolean = await V5Transfer.sendParallel(self, target, retryFiles, encData, onReport);
        if (!okPar) {
          okAll = false;
        }
      } else {
        const okPlain: boolean = await V5Transfer.sendPlain(self, target, retryFiles, encData, onReport);
        if (!okPlain) {
          okAll = false;
        }
      }
    }
    return okAll;
  }

  /**
   * ★ 5.1.14：把 files **按序轮转**分给 `SEND_CONCURRENCY` 条独立 1101 连接并发发送。
   *
   *  - 连接 k 拿第 `k, k+N, k+2N…` 项（**不是**把同一文件发 N 遍）
   *    ⇒ 对端看到的仍是一批普通文件，不需要理解「同文件多连接」。
   *  - 每条连接内部调 `sendPlain`，走**完全标准**的 1101 序列。
   *  - **全部连接都成功**才算成功；任一条失败即整体失败（不重试，
   *    与原 `sendPlain` 失败语义一致）。
   */
  private static async sendParallel(
    self: LanDevice,
    target: LanDevice,
    files: OutgoingFile[],
    encData: boolean,
    onReport: TransferCallback
  ): Promise<boolean> {
    const n: number = Math.min(SEND_CONCURRENCY, files.length);
    const lanes: OutgoingFile[][] = [];
    for (let i: number = 0; i < n; i++) {
      lanes.push([]);
    }
    for (let i: number = 0; i < files.length; i++) {
      lanes[i % n].push(files[i]);
    }
    Log.i(TAG, `v5 并发发送：${files.length} 项分给 ${n} 条连接（每条 ${
      lanes.map((l: OutgoingFile[]) => l.length).join('/')} 项）`);
    const tasks: Promise<boolean>[] = [];
    for (let i: number = 0; i < n; i++) {
      if (lanes[i].length === 0) {
        continue;
      }
      tasks.push(V5Transfer.sendPlain(self, target, lanes[i], encData, onReport));
    }
    const results: boolean[] = await Promise.all(tasks);
    let okAll: boolean = true;
    for (let i: number = 0; i < results.length; i++) {
      if (!results[i]) {
        okAll = false;
      }
    }
    Log.i(TAG, `v5 并发发送${okAll ? '完成' : '**有车道失败**'}（${results.length} 条连接）`);
    return okAll;
  }"""

EDITS = [(OLD1, NEW1), (OLD2, NEW2)]

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
