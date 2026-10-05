# -*- coding: utf-8 -*-
import io
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if '## 12:14 5.1.23 诊断版' in s:
    print('ALREADY')
    raise SystemExit(0)

ADD = r'''

## 12:14 5.1.23 诊断版：网页上传卡死（**连错两轮后改用观测**）

HAP `LANShare-5.1.23-DIAG.hap`（2,523,164 B），已推手机 Download/（12:14）。

### 现象
vivi 12:08：**5.1.22 修完后仍卡住闪退**。hilog 确认 `THREAD_BLOCK_6S` → `signal:9` 强杀。
`ui_log` 尾部：12:07:26 **5 个连接同时到达** → 12:07:46 **5 个「连接处理结束」挤在同一秒** → 设备下线。

### ★ 已排除的三个假设（记录在案，别重复劳动）
| 假设 | 状态 |
|---|---|
| HTTP 头逐字节读 = 2500 次 await | ✅ 5.1.22 已修，**仍闪退** ⇒ 不是它 |
| `MultipartStream.feed` 的 concat 是 O(n²)、815GB 复制 | ❌ **我算错了** |
| 我的批量读导致 hold 无限 grow | ❌ `parseHeader` 找到 `\r\n\r\n` 即 DONE，最多 1~2 轮 |

★ **第二个假设错在哪**：`pump()` 的 `S_BODY` 分支**本来就有** else 分支
（`MultipartStream.ets:236`：留 `marker.length+1` 尾巴、其余**立即落盘**），
所以 `hold` 在同一个 `feed` 内就被排空 ⇒ concat 规模 ≈ 256KB，
**复制量 ≈0.63GB（线性）**，不是 O(n²)。
⇒ 教训：**看到一个 `concat` 就断言 O(n²) 是错的，必须先确认「消费方是否在同一次调用里排空」。**

### 唯一未验证的热点
`MultipartStream.write`（`:257`）每块调 `sink.append`，
而 `append`（`FileStorage.ets:246`）是 **`fileIo.writeSync` 同步系统调用**。
646MB / 256KB = **2585 次同步写**，全在**主线程**（ArkTS 单线程）⇒ 最可能卡 6 秒的点。

### 本版只做观测
上传循环插分段计时（**每 64 块 = 16MiB 打一行**，低频）：
```
[UP] blk#256 64.0MB tot=3200ms read=1800 feed=900 other=0 | avg=20.0MB/s
```
判读：
- `feed` 占绝大多数 ⇒ **落盘（writeSync）是瓶颈** ⇒ 换异步写 / 加大块 / Worker
- `read` 占绝大多数 ⇒ 是网络侧，方向要换

### 关于「5.1.12 为什么没事」
★ **5.1.12 用的是同一份 `MultipartStream`（git 显示该文件自 v5.0.47 基线只被改过一次）**
⇒ 它**也会卡**。而且**所有历史日志里「网页上传」一次成功记录都没有**
⇒ **5.1.12 从没成功上传过网页大文件**，不是「没事」，是**没测过**。
'''
s = s.rstrip('\n') + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count(chr(0xFFFD))))
