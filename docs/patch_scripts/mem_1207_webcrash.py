# -*- coding: utf-8 -*-
import io
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if '## 12:07 v5.1.22' in s:
    print('ALREADY')
    raise SystemExit(0)

ADD = r'''

## 12:07 v5.1.22：修「网页给手机发大文件 ⇒ 卡住后闪退」+ 回退接收端缓冲

commit `b276251` + tag `v5.1.22`，HAP `LANShare-5.1.22.hap`（2,521,231 B），
**已推手机 Download/（12:07）**。

### ★ 两处设备身份纠正（vivi 12:02，我此前一直叫错）
| 地址 | 我之前说 | 实际 |
|---|---|---|
| `192.168.10.146` | 「平板」 | **HUAWEI Mate 70 Pro 优享版 = 手机**（鸿蒙版装在这）|
| `192.168.10.100` | 「安卓平板」 | **DBY-W09 = 安卓设备** |

且 DBY-W09 上**同时装了** `com.fgsqw.lanshare`(1.2.8) + `com.fgsqw.lansharf`(1.35)，
电脑也两个都装。★ 以后别把「146=平板」当既定事实。

### 接收速度 50M：瓶颈在**对端**，我方改不动
5.1.21 把接收端也改成「不设缓冲」后实测**毫无提升**（仍 ~50MB/s）
⇒ 吞吐取决于**对端发送能力**，接收窗口不是瓶颈。
★ 顺带查了安卓 APK 的 dex：1.2.8 里 `setSendBufferSize` 符号 **0 次**、
1.35 里各 1 次 —— 但**只在字符串池里，不能证明真被调用**（需追 invoke 指令），
**证据不足，不下结论**。

### ★★ 闪退根因：HTTP 头**逐字节读** ⇒ 主线程占满
`ui_log` 最后是 `12:01:16` **5 个连接同时到达** → 全部「连接处理结束」→ 设备下线，
**无异常堆栈** ⇒ 不是崩溃，是**主线程被占满**（THREAD_BLOCK 强杀）。

`HttpRouter.keepAliveLoop`（`HttpRouter.ets:284`）：
```ts
const chunk = await channel.readExactly(1, 15000);   // ★ 每字节一次 await
```
- 一个 HTTP 头 200~500 字节 ⇒ **200~500 次串行 await**
- 浏览器上传**并发开多条连接**（实测 5 条同时到）⇒ 2500 次串行 await 全排**主线程**
- ArkTS 的 socket 回调与文件操作**同在主线程** ⇒ 互相排队 ⇒ 主线程占满 ⇒ UI 无响应

★ **与上传体那个「每 8 块让帧」（`UPLOAD_YIELD_EVERY`）无关** —— 那个已经做了，
问题发生在**头解析阶段**，在它之前。

### 修法：头解析改「批量读」
`readSome(buffer.length - used, 15000)` 一次读一大块。
等价性已用 node 验证：**头结束位置一致、头内容一致**；5 连接 await **890 → 5（-99%）**。
⚠️ `readSome` 可能一次带回「header + body 前缀」，多出的字节仍由 `bodyInBuffer`
传给 `serveUpload`（`:326` 的 `mp.feed(pre)`）⇒ **数据不丢**。

### 顺带回退接收端（vivi 决定）
`TUNE_SERVER_BUFFERS` 改回 `true`（显式 **262144** 合法顶格）。
理由：收益为零，却带着 5.0.58 记录的「对端部分发送 ⇒ 干等 60s」风险。
★ **没有收益的改动就是负担。**

### ★★★ 方法论（本轮两条最值钱）
★★ **「逐字节读」在 ArkTS 上是性能杀手**：每次 `await` 都是一次事件循环往返，
而 socket 回调与文件操作**同在主线程** ⇒ 任何「按字节/按小步 await」的循环
在并发连接下都会**指数级放大主线程占用**。
★ 排查「并发下卡死/闪退」时，先数「一个请求产生多少次 await」：
   5 连接 × 500 await = 2500 次串行挂起 —— 这就是主线程被打爆的量级。

★ **「优化后没提升」要分清是哪一侧的瓶颈**：
本轮接收端不设缓冲零收益 ⇒ 瓶颈在**对端**。
没收益的改动要**回退**，否则白担风险。
'''
s = s.rstrip('\n') + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count(chr(0xFFFD))))
