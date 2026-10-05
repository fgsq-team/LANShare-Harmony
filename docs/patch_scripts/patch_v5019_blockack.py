# -*- coding: utf-8 -*-
"""
V5 块级应答补丁 —— 5.0.18 -> 5.0.19
=====================================

## 症状
PC（LANShare-PC(新)\\LANShare\\LANShare.exe）向手机发大文件：
进度**恰好卡在 48%**（= 2097140 / 4336019），约 20s 后 PC 报失败；
而沙箱里确实留下一个 **恰好 2097140 字节**的半截文件。

## 根因（字节级取证，非推断）
**2097140 = 2097152 - 12**，是两端写死的块尺寸。PC 端 exe 带完整 C++ 符号表，
反汇编 `baseSend`（1101）与 `LANShare::sendOneSeg`（1110）的循环体完全同构：

    movl  $2097152,%ebp ; subl headerSize,%ebp     -> 2097140
    callq IOUtils::read(buf, 2097140)
    callq DataEnc::setByteCmd(1)                  -> FS_DATA
    callq TCPClient::send(块)
    movb  $0,55(%rsp)                             -> b = 0
    callq TCPClient::recvo(&b, 1, 0)              -> ★ 阻塞 recv(fd,&b,1,0)
    cmpb  $6,55(%rsp) ; je 中止
    -> 才发下一块

而 `TCPClient::recvo(void*,ull,int)` 就是裸 `::recv` 循环（无超时）。
Android 1.35 同构证明在 `docs/forensics/dump_y.txt` 238-249 行：
`isNextStep() ? write(5) : write(6)` 写在**每块写盘之后**、循环体内。
PC 收端 `baseRecv` 亦对称（`movl $6,%eax ; subl isNextStep` → 每帧回 1 字节）。

**所以契约是「块级」而不是「文件级 / 片级」：每收一块必须立刻回 1 字节。**

本项目旧实现只在**整份文件 / 整片收满**之后回一个字节，于是：
  对端发完第 1 块 → 阻塞在 recv → 本端在等第 2 块 → 双向死锁；
  本端 60s 后 `readExactly(12) 超时: 需要 12，现有 0`，对端进度停在 48%。

## 判据实验（已做，证明接收管线本身没问题）
`tests/live-probe/v5_push_probe.mjs` 按 1.35 原生语义一次推 3 块、
**全程不回任何应答** → 手机 `v5 已保存 … (6291420 B, 3 片, 293ms)`。
=> 手机接收侧没有 ceilings，纯粹是缺块级应答。

## 本补丁做什么
1. `recvBody()`（1101）：每落地一块后回 1 字节 5(FS_NEXT)。
2. `receiveSegment()`（1110）：每落地一块后回 1 字节 5(FS_NEXT)。
   插入点必须在 `part.received += flen` **之前** —— 「累加 → 节流判断」那对语句
   之间不能有 await，否则 16 片并发的进度上报会交错（见该处原注释）。
3. 文件头补一节「块级应答」把取证钉死，避免以后又被"优化"掉。

保留原有的「整片/整份收满后回 5(+2)」收尾不变 —— 那是 1.35 `z()`/`B()` 的片级收尾，
多余字节对端不读即丢弃，无害；删掉反而可能破坏与 Android 端的互通。

## 幂等
哨兵 = SENTINEL，重跑直接 exit 0。
"""

import io
import os
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
V5 = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'V5Transfer.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '## ★ 块级应答（5.0.19 定案）'


def read_text(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        return f.read().replace('\r\n', '\n')


def write_text(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


src = read_text(V5)
app = read_text(APP)

if SENTINEL in src:
    print('ALREADY APPLIED')
    sys.exit(0)

# ---------------------------------------------------------------- 文件头：新增一节
HDR_OLD = """ * 取 1MB-12 是两边都能收的保守值，不会踩到 1.35 的数组越界。
 */
"""

HDR_NEW = """ * 取 1MB-12 是两边都能收的保守值，不会踩到 1.35 的数组越界。
 *
 * ## ★ 块级应答（5.0.19 定案）—— 每收一块必须**立刻**回 1 字节
 *
 * 这是 V5 互通的**硬性时序**，不是可选优化。不遵守 = 大文件必然卡死：
 *
 *   · PC 端 `LANShare.exe`（MinGW/Qt，带完整 C++ 符号表）反汇编证据：
 *     `baseSend`（1101 路径）与 `LANShare::sendOneSeg`（1110 路径）循环体同构 ——
 *     `IOUtils::read(buf, 2097152 - headerSize)` → `setByteCmd(1)` →
 *     `TCPClient::send(块)` → `b=0` → **`TCPClient::recvo(&b, 1, 0)`** →
 *     `if (b == 6) 中止` → 才发下一块。
 *     `TCPClient::recvo(void*, unsigned long long, int)` 的真身就是裸 `::recv`
 *     循环（第 3 个参数被当 flags 传给 recv），**阻塞且无超时**。
 *     块尺寸：`movl $2097152,%ebp ; subl headerSize,%ebp` → **2097140**。
 *   · Android 1.35 同构：`docs/forensics/dump_y.txt` 238-249 行，
 *     `isNextStep() ? write(5) : write(6)` 位于**每块写盘之后**的循环体内；
 *     同文件 91 行的日志串 `" recvBuf=2097152 chunk=2097140 target="` 即块尺寸出处。
 *   · PC 收端 `baseRecv` 亦对称：`6 - isNextStep()` 写回 1 字节 / 帧。
 *
 * 旧实现只在**整份文件 / 整片收满**之后回一个字节，于是：
 *   对端发完第 1 块 → 阻塞在 `recv` 等应答 → 本端在等第 2 块 → **双向死锁**；
 *   本端 60s 后 `readExactly(12)` 超时，对端进度条停在此处：
 *   **2097140 / 文件大小 = 48%** —— 正是用户看到的现象。
 *
 * 判据实验：`tests/live-probe/v5_push_probe.mjs`（手工按 1.35 语义推 3 块、
 * 全程零应答）→ 真机 `v5 已保存 … (6291420 B, 3 片, 293ms)`，
 * 证明本端接收管线本身没有上限，缺的就是这个字节。
 *
 * ⚠️ 保留「整片/整份收满后回 5(+2)」的片级收尾不变：那是 1.35 `z()`/`B()` 的结尾语义，
 *    多余字节对端不读即丢弃；删掉反而可能破坏与 Android 端的互通。
 */
"""

# ---------------------------------------------------------------- recvBody：块级应答
BODY_OLD = """        chunkCount += 1;
        subTotal += len;
        const percent: number = Math.floor(subTotal * 100 / item.length);
"""

BODY_NEW = """        chunkCount += 1;
        subTotal += len;
        // ★ 块级应答（5.0.19）：对端每发一块都阻塞 recv 1 字节才发下一块。
        //   放在 append 成功之后 —— 数据已落地才确认。整份文件只回一次 =
        //   对端发完第一块就永久卡在 recv（实测进度停在 2097140/4xx 万 = 48%）。
        await V5Transfer.sendByte(chan, LCmd.FS_NEXT);
        const percent: number = Math.floor(subTotal * 100 / item.length);
"""

# ---------------------------------------------------------------- receiveSegment：块级应答
SEG_OLD = """        got += flen;
        // ---- 全局进度：每落地一块就累加到**跨片共享**的计数器 ----
"""

SEG_NEW = """        got += flen;
        // ★ 块级应答（5.0.19）：16 片并发时每条连接各自回各自的，
        //   与下面「累加 + 节流」的共享状态互不相干。
        //   ⚠️ 必须在 `part.received += flen` **之前**：那之后到节流判断之间
        //     不能出现 await（见下方原注释），否则进度上报会交错乱跳。
        await V5Transfer.sendByte(chan, LCmd.FS_NEXT);
        // ---- 全局进度：每落地一块就累加到**跨片共享**的计数器 ----
"""

# ---------------------------------------------------------------- 旧注释的补充说明
NOTE_OLD = """    // 收完一片回**两个**字节，与 1.35 自己的接收端 (`z()` + `B()`) 完全一致：
"""
NOTE_NEW = """    // 收完一片回**两个**字节（这是**片级收尾**；块级应答已在每块回过了，见文件头）。
    // 与 1.35 自己的接收端 (`z()` + `B()`) 完全一致：
"""

EDITS = [
    (V5, HDR_OLD, HDR_NEW, '文件头新增「块级应答」章节'),
    (V5, BODY_OLD, BODY_NEW, 'recvBody 每块回 FS_NEXT'),
    (V5, SEG_OLD, SEG_NEW, 'receiveSegment 每块回 FS_NEXT'),
    (V5, NOTE_OLD, NOTE_NEW, '片级收尾注释补充'),
    (APP, '    "versionCode": 5000018,', '    "versionCode": 5000019,', 'versionCode -> 5000019'),
    (APP, '    "versionName": "5.0.18",', '    "versionName": "5.0.19",', 'versionName -> 5.0.19'),
]

# ---------------------------------------------------------------- 1) 全量校验
buffers = {V5: src, APP: app}
brace_before = src.count('{') - src.count('}')
for path, old, new, label in EDITS:
    cur = buffers[path]
    n = cur.count(old)
    assert n == 1, '[%s] 锚点命中 %d 次（应为 1）: %r' % (label, n, old[:80])
    assert cur.count(new) == 0, '[%s] 新文本已存在，疑似半途落盘: %r' % (label, new[:80])
    buffers[path] = cur.replace(old, new, 1)
    print('  [校验通过] %s' % label)

# 括号增量必须为 0（本补丁只加「注释 + 一行 await」，不含花括号）
brace_after = buffers[V5].count('{') - buffers[V5].count('}')
assert brace_before == brace_after, '花括号增量 %d != 0' % (brace_after - brace_before)
print('  [校验通过] 花括号增量 = 0（%d）' % brace_after)

# 关键符号引用数核对：新增 2 处 sendByte 调用（原 6 处 -> 8 处）
n_send = buffers[V5].count('V5Transfer.sendByte(')
print('  [核对] V5Transfer.sendByte( 调用点 = %d（期望 8 = 原 6 + 新 2）' % n_send)
assert n_send == 8, 'sendByte 调用点数异常'

# ---------------------------------------------------------------- 2) 统一落盘
write_text(V5, buffers[V5])
write_text(APP, buffers[APP])
print('DONE: V5Transfer.ets + app.json5 已更新（5.0.19）')
