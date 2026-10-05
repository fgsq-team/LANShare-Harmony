# -*- coding: utf-8 -*-
import io
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if '## 12:28 v5.1.24' in s:
    print('ALREADY')
    raise SystemExit(0)

ADD = r'''

## 12:28 v5.1.24：修「网页上传只有 17MB/s + 进度条卡」—— **进度上报每次 emit**

commit `a90100e` + tag `v5.1.24`，HAP `LANShare-5.1.24.hap`（2,523,360 B），
**已推手机 Download/（12:28）**。

### ★ vivi 提供的决定性对照（这才是一步到位的关键输入）
| 路径 | 速度 |
|---|---|
| **安卓 1.35 → 鸿蒙**（V5 协议接收）| **50 MB/s** ✅ |
| **网页 → 鸿蒙**（HTTP multipart 接收）| **17 MB/s** ❌ |
| 安卓接收（不论鸿蒙发还是网页发）| 50 MB/s |

⇒ **同一台设备，V5 接收 50M、HTTP 接收 17M** ⇒ CPU/IO/网络**都没问题**，
差的是**接收链路的处理方式**。

### 根因（就差一个词）
`onWebUploadProgress`（`LanService.ets:3547`）**每次都 `this.emit()`，无节流**：
```ts
this.snapshot.transferText = ...;
this.snapshot.transferPercent = pct;
this.emit();          // ★ 每次都触发 @State 变化 ⇒ ArkUI 重建整个页面
```
HTTP 上传循环里 `yieldFrame()` **每 2MB 一次** ——
让出的那一帧里 ArkUI 要**重建整页**（消息列表/文件网格/气泡），耗时可观
⇒ 主线程反复占满 ⇒ 17MB/s 且进度条超级卡。

★ **对照 V5 接收为什么快**：`onTransferReport`（`LanService.ets:3422`）用的是
**`this.emitThrottled()`**（5.0.69 起加的节流版）⇒ 同一台设备 V5 接收 50MB/s。
**同一个 App，V5 接收用节流、网页接收不用 —— 就差这一个词。**

### 本版两处改动
1. `onWebUploadProgress`：`emit()` → **`emitThrottled()`**
2. 节流参数：`200ms/256KB` → **`1000ms/4MB`**（646MB 从约 2500 次上报降到约 160 次）

⚠️ **`onWebUploadEnd`（终态）仍用立即 `emit()`** ——
否则进度条停在 99%、浮层不消失（5.0.69 踩过这个坑，本版**不动**）。

### ★★★ 方法论（本轮最值钱的两条）
★★ **「同设备、不同协议路径」的速度差 ⇒ 一定在协议处理层，不在硬件/网络。**
  本例 V5 接收 50M vs HTTP 接收 17M，一眼看穿「不是设备慢」。
  ★ 这个对照是 **vivi 提供的**（他做了「安卓收网页也 50M」的交叉验证）——
  **没有这组交叉对照，我会一直在「鸿蒙为什么慢」里打转。**
⇒ 以后遇到「某功能慢」，**先做交叉对照**（同设备换个入口试试），
  再看代码，能省掉几轮猜测。

★★ **ArkUI 里「进度上报」必须节流**：每次 `emit()` = 整页重建。
  凡高频路径（每块/每帧）上报进度，**一律用 `emitThrottled()`**，
  只在终态用立即 `emit()`。
  ⇒ 该写成一条**通用纪律**：*同 App 内不同上报路径要用同一种节流策略*，
  否则最慢的那条会主导整体体验。

### 顺带修一个补丁脚本自身的 bug
`patch_v5124` 里 `for path, s in cache.items()` 循环内又去索引 `EDITS` 取 `new`
做坏字符校验 ⇒ 变量 `s` 被覆盖 + 索引错位 ⇒ 抛异常、**补丁没落盘但版本号已改**。
⇒ 已改为先单独循环校验 `new` 再落盘。
★ 教训：**落盘校验的循环不要复用循环变量**，否则「校验」本身会污染状态。
'''
s = s.rstrip('\n') + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count(chr(0xFFFD))))
