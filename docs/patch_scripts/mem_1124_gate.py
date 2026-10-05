# -*- coding: utf-8 -*-
import io
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if '## 11:24 v5.1.19 在途量闸门' in s:
    print('ALREADY')
    raise SystemExit(0)

ADD = r'''

## 11:24 v5.1.19「在途量闸门」：保留提速 + 兼容 1.35（探测版）

commit `ef98128` + tag `v5.1.19`，HAP `LANShare-5.1.19.hap`（2,518,085 B），
**已推手机 Download/（11:24）**。

### vivi 的关键补充信息（把范围锁死）
- 1.35：**小文件成功、大文件失败**（646.1MB 失败）
- 官方 1.2.8：两种版本都成功
- 5.1.12：给 1.35 **全成功**（35.7MB/s）
- 5.1.18：**只保留 SO_SNDBUF 提速**这一处，仍失败
⇒ ★ **病因就是「发送缓冲变大」本身**，与 readChunkInto / 加密查表 / 双连接**全都无关**。

### 机理（与「小文件成功、大文件失败」完全吻合）
- 5.1.12 显式 `SO_SNDBUF=262144`（256KB）：一块 1MiB 写进去，内核只吃下 256KB，
  **必须等对端读走**⇒ **在途字节量被硬压到 ~1.25MB**。
- 5.1.17/5.1.18 **不设** ⇒ 内核自动调优，缓冲可达数 MB ⇒ **在途量 4MB+（3 倍以上）**。
- 1.35 的块级流控有一处**按在途量做的假设**（`recvBuf=2097152` 单缓冲 + `isNextStep()`）
  ⇒ 在途量超预期就判错 ⇒ **大文件必踩、小文件（在途量小）撑得住**。

### 做法：不用 SO_SNDBUF 去压，改在**应用层**加批次闸门
`V5Transfer.ets` 新增 `SEND_INFLIGHT_BLOCKS`：
每发 N 块 `await sendYieldFrame()`（`setTimeout(0)` 让一帧），
把「一次连续 push 进内核的字节数」压到 `N × 1MiB`，**间接约束在途量**。
★ 关键取舍：**用 SO_SNDBUF 压会一并关掉内核自动调优 ⇒ 丢掉 48% 提速**，
所以必须在应用层做。

| 值 | 在途量 | 预期 |
|---|---|---|
| `0` | 无限制 | 52.9MB/s，1.35 大文件失败（= 5.1.17 行为）|
| `4` | ≈4MB | 略降，可能仍失败 |
| **`1`（当前）** | ≈1MB，最接近 5.1.12 | 1.35 应恢复 |

### 待 vivi 实测（按 4 → 1 各测一次 1.35 大文件）
- `1` 成功 ⇒ 阈值确认在途量，我把值定死、去多余分支
- `1` 仍失败 ⇒ **阈值不是「在途量」**，去掉 SO_SNDBUF 方向另查

### 顺带修两个编译错（本轮踩）
1. `MAX_FRAME` 被补丁的**替换**吃掉（不是追加）⇒ 报 `Cannot find name 'MAX_FRAME'`
2. 顶层 `function yieldFrame()` 与类内 `V5Transfer.yieldFrame()` **同名** ⇒ 改 `sendYieldFrame`
★ 教训：补丁里 `OLD/NEW` 成对出现时，**NEW 必须包含 OLD 全文**（我在 OLD1 只写了 `SEG_TOTAL` 一行，
   NEW 也没带上它 ⇒ 那行被替换没了）。这类「替换吃掉声明」的错误**编译期才会暴露**。
'''
s = s.rstrip('\n') + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count(chr(0xFFFD))))
