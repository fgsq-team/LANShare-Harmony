# -*- coding: utf-8 -*-
import io
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if '## 10:41 ★★ 发送端真根因' in s:
    print('ALREADY')
    raise SystemExit(0)

ADD = r'''

## 10:41 ★★★ 发送端真根因：**别显式设 SO_SNDBUF**（5.1.17，vivi 两句反驳纠正了方向）

commit `6e89866` + tag `v5.1.17`，HAP `LANShare-5.1.17.hap`（2,535,776 B），
**已推手机 Download/（10:41）**。

### vivi 的两句反驳（都推翻了我的结论）
1. **「官方安卓不支持分片，网页也能 60MB/s」**
   ⇒ **TCP 单流本身就能跑 60** ⇒ 我 5.1.14/5.1.15「必须多连接」的结论**错了**。
2. **「两次测试鸿蒙 APP 都是发送端，和接收端无关」**
   ⇒ `LanTcpServer` 的缓冲改动**对本次测速毫无作用**（接收端是官方安卓，不是我们平板）。
   ⇒ 我 5.1.16 去改服务端缓冲，属于**改错了地方**。

### ★★ 真根因：显式 `setsockopt(SO_SNDBUF)` 会关闭 Linux 内核的 TCP 自动调优
| | 做法 | 后果 |
|---|---|---|
| 浏览器 / 官方安卓网页 | **不设** SO_SNDBUF | 内核自动扩缩容（16KB → tcp_wmem 上限，常见数 MB）⇒ **60MB/s** |
| 鸿蒙 `LanClient`（改前） | 显式设 **262144** | **自动调优被关**，缓冲钉死 256KB |

数据块是 **1MB**（`CHUNK = 1024*1024-12`）⇒ 每发 4 个缓冲就装满一块，
必须等对端读走 ⇒ 背压全落在 `await sock.write()` 里
⇒ 正是诊断看到的 **`send` 占 97.6%（26~28ms/块）**。

★★ **而 SDK 上限恰好是 262144**
（`@ohos.net.socket.d.ts:260`：范围 0~262144，超范围**静默回落**默认 8192）
⇒ **「顶格」反而是最坏选择**。我一直在「往上顶格」，方向正好相反。

### 改动
1. `LanClient.applyTuning`：**不再设 `sendBufferSize`/`receiveBufferSize`**，
   只保留 `TCPNoDelay`（Nagle 那 40ms 的分析仍成立）。
   新开关 **`TUNE_SOCKET_BUFFERS = false`**（改 true 可回退对比）。
2. `LanTcpServer.TUNE_BUFFER_SIZE`：4194304 → **262144**
   （5.0.58 遗留的**静默失效**：填了 4MB，超上限回落 8192，而注释却写「纯赚」）。
3. 修 5.1.15 引入的编译错误：`{...r}` 对象展开 ArkTS 不允许（`arkts-no-spread`），
   改为**逐字段显式构造** `TransferReport`（11 个字段全覆盖）。

`[DIAG]` 打点保留，测完直接读数确认 `send` 占比是否下降。

### ★★★ 方法论（本轮最值钱的一条）
**「显式 setsockopt 缓冲」不是优化，是禁用内核自动调优。**
在 Linux 上（鸿蒙/安卓同源）`SO_SNDBUF` 一旦被显式设置，
`tcp_wmem` 的自动扩缩容就失效 —— 很多人（包括我）却把它当「性能优化」。
★ 凡见 `setExtraOptions` / `setsockopt` 里出现 `sendBufferSize`，
  **先问「这是不是把自动调优关掉了」**，再问「上限是多少」。

### 顺带：5.1.15 的双连接闪退真因（已修但方向也错了）
hilog 时间戳 `10:30:11.136` / `10:30:11.137`（相差 1ms）⇒ 两条连接**同一瞬间**发起
`connect()`，各自 `await chan.send(magicPrefix())`；
ArkTS 的 socket 回调与文件操作**同在主线程** ⇒ 双份建连把主线程堵死
⇒ `THREAD_BLOCK_3S` → `6S forceExit:1` → `signal:9` 强杀。
修法 = **错峰启动**（`START_STAGGER_MS = 400`）+ 车道进度换算成全局坐标。
⚠️ 该版引入的 `{...r}` 当时**没编译过**（arkts-no-spread），5.1.17 才补。

### 待实测
装 5.1.17，发**单个 ≥200MB 文件**（单文件也该生效 —— 本版与文件数无关），
看日志 `v5 已发送 … MB/s` 与 `[DIAG]` 行的 `send` 占比。
预期 35.7 → 接近 60MB/s。**若 `send` 仍占 97%**，则缓冲不是根因，回到观测。
'''

s = s.rstrip('\n') + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count(chr(0xFFFD))))
