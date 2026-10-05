# -*- coding: utf-8 -*-
"""
v5.1.19 —— 兼容 1.35 的「在途量闸门」（保留提速，不再无条件关掉自动调优）

## 现象（vivi 11:19 反馈 + 实测）
- 5.1.12：给 1.35 发**大文件也成功**（35.7MB/s）
- 5.1.17/5.1.18：给 1.35 **小文件成功、大文件失败**（52.9MB/s）
- 对**官方 1.2.8** 两种版本都成功
- 5.1.18 只保留了一处改动（`TUNE_SOCKET_BUFFERS=false`，即不设 SO_SNDBUF）仍失败
  ⇒ **病因就是「发送缓冲变大」这一件事本身**，与 readChunkInto / 加密查表 / 双连接无关。

## 机理推断（与「小文件成功、大文件失败」完全吻合）
- 5.1.12 显式 `SO_SNDBUF=262144`（256KB）：一块 1MiB 写进去，内核只能吃下 256KB，
  **必须等对端读走**才能继续 ⇒ **在途字节量被硬压到 ~1.25MB**。
- 5.1.17/5.1.18 **不设** SO_SNDBUF ⇒ 内核自动调优，缓冲可达数 MB
  ⇒ **在途量可能到 4MB+**（3 倍以上）。
- 1.35（修改版）在块级流控上有一处**按「在途量」做的假设**
  （`recvBuf=2097152` = 2MB 单缓冲 + `isNextStep()` 判定），
  在途量超过它的预期后就会判错 ⇒ **大文件必然踩到，小文件（几块）在途量小、撑得住**。

## 本版做法：把「在途量上限」做成显式开关
不靠 SO_SNDBUF（那会一并关掉自动调优），而是在**发送循环里加一个可调的批次闸门**：

    每发 `SEND_INFLIGHT_BLOCKS` 块 ⇒ 让一帧（setTimeout 0）⇒ 继续

- 闸门只**让出事件循环**，不阻塞、不等 ack（1101 路径本来就没有块级 ack）；
- 效果：把「一次连续 push 进内核的字节数」压到 `N × 1MiB`，
  从而间接约束在途量，**同时保留内核自动调优带来的提速**。

### 三档开关（`SEND_INFLIGHT_BLOCKS`）
| 值 | 含义 | 预期 |
|---|---|---|
| `0` | **不设闸门**（= 5.1.17/5.1.18 行为）| 52.9MB/s，1.35 大文件失败 |
| `4` | 每 4 块让一帧（在途 ≈ 4MB）| 速度略降，1.35 可能仍失败 |
| `1` | **每块让一帧**（在途 ≈ 1MB，最接近 5.1.12）| 1.35 大文件应恢复，速度介于两者之间 |

⚠️ 这是一版**探测性质**的版本：请按 4 → 1 的顺序各测一次 1.35 大文件，
即可反推 1.35 的真实在途量阈值，然后我把值定死、去掉多余分支。
若 `1` 仍失败 ⇒ 阈值不是「在途量」而是别的（届时我会去掉 SO_SNDBUF 方向另查）。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
PATH = os.path.join(ROOT, 'entry/src/main/ets/service/V5Transfer.ets')

OLD1 = """/** 单帧 payload 的硬上限，超过一定是流错位了 */
const MAX_FRAME: number = 8 * 1024 * 1024;"""

NEW1 = """const SEG_TOTAL: number = 16;

/**
 * ★★ 5.1.19：**在途量闸门**（每发 N 块让一帧）。
 *
 * ## 为什么要它
 * 5.1.17/5.1.18 把 `SO_SNDBUF` 改成「不设」，让内核自动调优 ⇒ 吞吐 35.7 → 52.9MB/s，
 * **但对端 1.35 的**大文件**传输开始失败**（小文件仍成功）。
 * 5.1.18 只保留这一处改动仍失败 ⇒ 病因就是「发送缓冲变大」本身。
 *
 * ## 机理
 * 5.1.12 显式 `SO_SNDBUF=262144`（256KB）：一块 1MiB 写进去，内核只吃下 256KB，
 * 必须等对端读走才能继续 ⇒ **在途字节量被硬压到 ~1.25MB**。
 * 改成不设之后缓冲可达数 MB ⇒ 在途量 4MB+（3 倍以上）。
 * 1.35 的块级流控有一处**按在途量做的假设**（`recvBuf=2097152` 单缓冲 +
 * `isNextStep()`），超过阈值就判错 ⇒ **大文件必踩、小文件撑得住**。
 *
 * ## 本开关的作用
 * 不再用 SO_SNDBUF 去压（在途量的同时会一并关掉内核自动调优、丢掉 48% 提速），
 * 改在**应用层**加批次闸门：每发 N 块 `await` 一帧（`setTimeout(0)`），
 * 把「一次连续 push 进内核的字节数」压到 `N × 1MiB`，
 * **间接约束在途量，同时保住内核自动调优**。
 *
 * | 值 | 含义 | 预期 |
 * |---|---|---|
 * | `0` | 不设闸门（= 5.1.17 行为）| 52.9MB/s，1.35 大文件失败 |
 * | `4` | 每 4 块让一帧（在途 ≈4MB）| 略降，可能仍失败 |
 * | `1` | 每块让一帧（在途 ≈1MB，**最接近 5.1.12**）| 1.35 应恢复 |
 *
 * ⚠️ 探测性质的版本：按 4 → 1 各测一次 1.35 大文件，反推它的真实阈值。
 */
const SEND_INFLIGHT_BLOCKS: number = 1;

/** 让出一帧（ArkTS 单线程，见 memory：让 UI 插进来画一帧） */
function yieldFrame(): Promise<void> {
  return new Promise<void>((resolve: () => void) => {
    setTimeout(resolve, 0);
  });
}"""

# ---------------------------------------------------------------- 发送循环加闸门
OLD2 = """        await chan.send(frame.bytes());
        subTotal += n;
        chunkCount += 1;
        const percent: number = Math.floor(subTotal * 100 / size);
        if (percent !== lastPercent || subTotal >= size) {
          lastPercent = percent;
          onChunk(subTotal, size);
        }
      }"""

NEW2 = """        await chan.send(frame.bytes());
        subTotal += n;
        chunkCount += 1;
        // ★★ 5.1.19：在途量闸门 —— 每发 SEND_INFLIGHT_BLOCKS 块让一帧，
        //   把「一次连续 push 进内核的字节数」压到 N × CHUNK，
        //   间接约束在途量（1.35 大文件失败的直接对策），**不碰 SO_SNDBUF**
        //   ⇒ 内核自动调优带来的提速得以保留。
        //   ⚠️ 0 = 关闭（等于 5.1.17 行为）；1 = 每块让一帧（最接近 5.1.12）。
        if (SEND_INFLIGHT_BLOCKS > 0 && chunkCount % SEND_INFLIGHT_BLOCKS === 0) {
          await yieldFrame();
        }
        const percent: number = Math.floor(subTotal * 100 / size);
        if (percent !== lastPercent || subTotal >= size) {
          lastPercent = percent;
          onChunk(subTotal, size);
        }
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
