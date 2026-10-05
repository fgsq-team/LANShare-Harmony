# -*- coding: utf-8 -*-
"""
v5.1.20 —— ★ 探针版：1101 路径开始**消费对端块级 ack**

## 现象（vivi 11:30）
| 对端 | 5.1.12 | 5.1.17/5.1.19 |
|---|---|---|
| 官方 1.2.8（电脑）| ✅ | ✅ |
| **1.35（平板）** | ✅ | ❌ **大文件失败，小文件成功** |

而**鸿蒙侧 4 次全部报「已发送成功」**（`ui_log` 零错误）
⇒ **失败发生在对端，我方完全没察觉**。

## 根因假设（★ 这是一路推理下来的结论，本版就是为验证它）
**1.35 与官方的唯一关键差异 = 块级应答（背靠背流控）**：
- 1.35 收端：**每收一块立刻回 1 字节**（`5`=继续 / `6`=中止），见
  `docs/forensics/dump_y.txt` 238-249 的 `isNextStep() ? write(5) : write(6)`。
- 官方 1.2.8：不需要块级 ack ⇒ **完全不受影响**（与实测一致）。

**我方 1101 路径从头到尾不读 ack**（`sendBody` 内零 `readExactly`）：
- 5.1.12 时 `SO_SNDBUF=262144`（256KB）**天然限流** ——
  内核缓冲吃不下就阻塞，等对端读走 ⇒ 对端回的 ack 有机会被读走，不积压。
- 去掉缓冲后一路狂飙 ⇒ 1.35 回了成百上千个 ack **全堆在接收缓冲**，
  而 1.35 发完最后一块就在**等我方回应** ⇒ 双方错位 ⇒ 对端判定失败。
- **小文件只有几块，ack 少，缓冲装得下 ⇒ 成功**；大文件必然溢出 ⇒ 失败。

## 本版改动（纯观测 + 保守排空，不改协议）
在 1101 的数据循环里，**每发完一块就读掉对端的块级 ack**（短超时，不阻塞）：
- 读到 `6`（FS_BREAK）⇒ 立刻判失败并打出**是第几块**断的
- 统计收到的 ack 字节数与块数，打进汇总日志
- 这样能直接回答：「1.35 是在第几块停止回应的」/「它到底回了多少 ack」

⚠️ 官方 1.2.8 不回块级 ack ⇒ 这些读会短超时返回 null，**不影响它的正确性**。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
PATH = os.path.join(ROOT, 'entry/src/main/ets/service/V5Transfer.ets')

# ---- 1. sendBody 签名：加 ack 统计
OLD1 = """  private static async sendBody(
    chan: TcpChannel,
    item: OutgoingFile,
    encData: boolean,
    onChunk: (sent: number, size: number) => void
  ): Promise<boolean> {"""

NEW1 = """  private static async sendBody(
    chan: TcpChannel,
    item: OutgoingFile,
    encData: boolean,
    onChunk: (sent: number, size: number) => void
  ): Promise<boolean> {
    // ★★ 5.1.20（探针）：本版统计对端回了多少块级 ack、在第几块停止回应。
    //   1.35 是背靠背流控（每收一块回 1 字节），官方 1.2.8 不回 —— 两者行为不同，
    //   而旧实现**从不读 ack**，所以 1.35 一旦因 ack 堆积而错位，我方毫无察觉。
    let ackCount: number = 0;
    let ackBreakAt: number = -1;
    const startedAt2: number = Date.now();"""

# ---- 2. 循环内：每块读 ack
OLD2 = """        if (SEND_INFLIGHT_BLOCKS > 0 && chunkCount % SEND_INFLIGHT_BLOCKS === 0) {
          await sendYieldFrame();
        }"""

NEW2 = """        if (SEND_INFLIGHT_BLOCKS > 0 && chunkCount % SEND_INFLIGHT_BLOCKS === 0) {
          await sendYieldFrame();
        }
        // ★★ 5.1.20（探针）：**读掉对端的块级 ack**。
        //   1.35 每收一块回 1 字节；官方 1.2.8 不回（这里会短超时返回 null，无害）。
        //   ⚠️ 用**极短超时**（默认 0 = 立刻返回，绝不等）——
        //     不用 `readExactly(1, 0)`：它每次超时都打一条 W 日志（647 块 = 647 条噪音）。
        //   读到 6（FS_BREAK）⇒ 立刻判失败，并记下断在第几块。
        let gotAck: boolean = false;
        try {
          const a1: Uint8Array | null = await chan.readSome(1, 0);
          if (a1 !== null) {
            gotAck = true;
            ackCount += 1;
            if (a1[0] === LCmd.FS_BREAK) {
              ackBreakAt = chunkCount;
            }
          }
        } catch (e) {
          // 读不到就当没回，不影响流程
        }
        if (ackBreakAt >= 0) {
          Log.w(TAG, `v5 [ACK] 对端在第 ${ackBreakAt} 块回 FS_BREAK(6)`
            + `（已发 ${subTotal}/${size} B，共 ${chunkCount} 块，收到 ${ackCount} 个 ack）`);
          return false;
        }
        if (gotAck && chunkCount % 64 === 0) {
          Log.i(TAG, `v5 [ACK] blk#${chunkCount} 累计收到 ${ackCount} 个块级 ack`
            + `（${subTotal} / ${size} B）`);
        }"""

# ---- 3. 汇总日志
OLD3 = """    const ms: number = Date.now() - startedAt;
    Log.i(TAG, `v5 已发送 ${item.name} (${subTotal} B, ${chunkCount} \u7247, ${ms}ms)`);
    return true;
  }"""

NEW3 = """    const ms: number = Date.now() - startedAt;
    // ★★ 5.1.20（探针）：汇总里带上 ack 统计 ——
    //   ackCount / chunkCount 就是「对端实际回了几次块级 ack」，
    //   与块数一致 ⇒ 流控正常；为 0 ⇒ 对端完全没回（官方 1.2.8 属正常）。
    Log.i(TAG, `v5 已发送 ${item.name} (${subTotal} B, ${chunkCount} \u7247, ${ms}ms,`
      + ` ack=${ackCount}, 耗时 ${Date.now() - startedAt2}ms)`);
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
