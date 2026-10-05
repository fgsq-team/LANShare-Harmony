# -*- coding: utf-8 -*-
import io
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if '## 11:17 对端 1.35 失败 → 二分定位版 5.1.18' in s:
    print('ALREADY')
    raise SystemExit(0)

ADD = r'''

## 11:17 ★ 对端 **1.35** 报「接受失败」→ 判定为 5.1.17 回归，出二分定位版 5.1.18

### vivi 给的两条关键信息（把范围收窄了）
| 组合 | 结果 |
|---|---|
| 鸿蒙 → **官方 1.2.8**（`com.fgsqw.lanshare`） | **成功**（5.1.17 提速后仍成功）|
| 鸿蒙 → **1.35**，用 5.1.12 时 | **成功** |
| 鸿蒙 → **1.35**，用 5.1.17 时 | **失败** |

⇒ **对端是 1.35；改前能成、改后失败 ⇒ 5.1.12→5.1.17 之间的某个改动只坑 1.35。**

### ★ 抓日志时踩的坑：抓错了对端
`pm list packages | grep -i lanshare` **只匹配到 `com.fgsqw.lanshare`（1.2.8 官方版）**，
因为 1.35 共存版的包名是 **`com.fgsqw.lansharf`**（`lanshare` + **`f`**）—— 结尾是 f，`grep lanshare` 匹配不到！
⇒ 我前面那轮「4 次发送全成功」的分析对象是**官方 1.2.8**，不是 1.35。**分析无效。**
★ 教训：多版本共存时，`pm list packages` 要用 `grep -iE "lan|gsqw"` 这类**宽模式**，
   或直接 `pm list packages -3` 全看，别假设包名只差后缀。

### 1.35 的日志拿不到（三条路全堵）
| 尝试 | 结果 |
|---|---|
| `adb logcat` | ❌ 1.35 没把日志接进 logcat（只有系统噪音）|
| `/data/data/com.fgsqw.lansharf/files/` | ❌ 无 root、非 debuggable（`flags` 里无 DEBUGGABLE）|
| `/sdcard/Android/data/com.fgsqw.lansharf/files/` | ❌ 空 |
⇒ **只能从发送侧反推** ⇒ 出**二分定位版**。

### 5.1.18 = 二分定位版（★ 只保留提速，其余全回退）
`git checkout v5.1.12 -- V5Transfer.ets FileStorage.ets FileCrypto.ets`
**保留**：`LanClient.TUNE_SOCKET_BUFFERS = false`（提速的真根因修复）
**回退**：`readChunkInto` / 加密查表 / `[DIAG]` 打点 / `SEND_CONCURRENCY` 双连接
HAP `LANShare-5.1.18.hap`（2,516,954 B），已推手机 Download/（11:17）。

### 判读
- **若 1.35 恢复成功** ⇒ 病因在 `readChunkInto` / 加密查表 / 双连接 之中 ⇒ 再二分
- **若仍失败** ⇒ 病因就是提速本身（缓冲变大 ⇒ 对端某些时序假设被打破）⇒ 需在发送侧加探针

★ 这一版是**故意牺牲诊断能力**换干净的对照组 —— 定位优先，观测后补。
'''
s = s.rstrip('\n') + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count(chr(0xFFFD))))
