# -*- coding: utf-8 -*-
import io
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if '## 10:20 ★ 诊断结论：`send` 独占 97.2%' in s:
    print('ALREADY')
    raise SystemExit(0)

ADD = r'''

## 10:20 ★★ 诊断结论（真机实测）：**`send` 独占 97.2%**，本机 CPU 只占 2.8%

平板 192.168.10.146 装诊断版，发 646.1MB 给 DBY-W09(192.168.10.100)，18 秒。
从 hilog 抓到 **40 条 `[DIAG]` 样本**（639MB），每 1MiB 块平均：

| 段 | 耗时 | 占比 |
|---|---|---|
| **send** | **25.95 ms** | **97.2%** |
| read | 0.68 ms | 2.5% |
| copy | 0.07 ms | 0.3% |
| **enc** | **0.00 ms** | **0.0%** |
| other | 0.00 ms | 0.0% |
| 合计 | 26.70 ms | 100% |

⇒ **本机 CPU 合计 0.75ms / 26.70ms = 2.8%**。
⇒ **我 5.1.13 优化的「缓冲复用 + 加密查表」正好落在这 2.8% 里** —— 难怪零效果。
（`enc=0` 是查表优化的直接证明：查表后加密耗时低于 Date.now() 的 1ms 分辨率。）

### 算一下如果 send 能减半
块均 26.70 → 13.72 ms ⇒ **35.7 → 69.5 MB/s**（超过网页的 55）。
⇒ **唯一值得动的就是 `send`**，其余全是噪音。

### ★ `send` 里到底有什么（逐项已排除到 API 层）
`await chan.send(frame.bytes())` 一个 await 里串了三件事：
1. `bytes()` → `subarray(0, pos)`（byteOffset=12，零拷贝视图）
2. `TcpChannel.toArrayBuffer`（`NativeSocket.ets:547`）→ 因 byteOffset≠0
   ⇒ **走 `slice()` 分支，再拷 1MB**
3. `await this.sock.write(ab)` —— ArkTS socket 写，**背压时 Promise 挂起**
   ⇒ socket 缓冲满时，**要等对端把数据读走（TCP 窗口）** 才继续
⇒ **第 3 步才是 26ms 的主体**：本机写得再快，对端没读就只能等。
⇒ 差距的真正性质：**单条 TCP 流的窗口/对端消费速度**，不是本机算力。

### 为什么网页能到 55
浏览器 HTTP 上传**开多条连接**（HTTP/1.1 6 连接 / HTTP/2 多流），
每条连接独立有自己的 TCP 窗口 ⇒ **聚合带宽远大于单流**。
⇒ 这就是「30/35 vs 55」的全部差距来源，**与本机性能无关**。

### ⇒ 下一步唯一方向：**多连接并发**
- 不能改 1110（1.35 有 5% 提前 FIN 的 bug）
- 不能改 CHUNK（1.35 只给 1MB 缓冲）
- ⇒ 只剩「**同一条 1101 协议、开 N 条 TCP 连接并发发**」，
  但要过 1.35 收端能否接受「同文件多连接」这一关（**必须小流量实测**）。

### ★★★ 两个工具坑（本轮踩死）
1. **`Log.i` 只进 hilog，不进 `ui_log.txt`**
   —— `Logger.ets` 的 `i/w/e` 全部走 `hilog.info/warn/error`；
   `ui_log.txt` 是 `logRing` 机制，只收 `pushLog` 的业务消息。
   ⇒ **诊断打点用 `Log.i` 时，`ui_log.txt` 里永远看不到**，必须 `hilog -x` 捞。
2. **`hdc file recv` 的沙箱路径不是 `.../files/`，而是 `.../haps/entry/files/`**
   —— 正确：`/data/app/el2/100/base/<bundle>/haps/entry/files/ui_log.txt`。
   我按 `.../base/<bundle>/files/` 找，两次都 `no such file`。
'''

s = s.rstrip('\n') + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count(chr(0xFFFD))))
