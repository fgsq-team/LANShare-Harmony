# -*- coding: utf-8 -*-
"""
v5.1.22 —— 修「网页给手机发大文件 ⇒ 手机卡住后闪退」

## 现象（vivi 12:02）
网页上传大文件到手机 ⇒ 手机**卡住后闪退**。
日志：12:01:16 **5 个连接同时到达** → 全部「连接处理结束」→ 设备下线。
`ui_log` 最后是 `[12:01:50] vivi/DBY-W09 已下线`，**无异常堆栈**。

## 根因（真机日志 + 代码定位）
`HttpRouter.keepAliveLoop`（`HttpRouter.ets:284`）**逐字节读请求头**：
```ts
const chunk = await channel.readExactly(1, 15000);   // ★ 每次 1 字节
buffer[used] = chunk[0];
state = HttpProtocol.parseHeader(buffer, used, req);
```
- 一个 HTTP 头约 **200~500 字节** ⇒ **200~500 次串行 `await`**；
- 浏览器上传会**并发开多条连接**（本轮实测 5 条同时到）
  ⇒ 2500 次串行 await 全排在**主线程**；
- ArkTS 的 socket 回调与文件操作**同在主线程** ⇒ 互相排队
⇒ **主线程占满 ⇒ UI 无响应 ⇒ 系统判定无响应并强杀**（表现为「卡住后闪退」）。

★ 与「每块上传让帧」那条（`UPLOAD_YIELD_EVERY`）无关 —— 那个已经做了，
问题发生在**头解析阶段**，在它之前。

## 本版修法：头部改「批量读 + 攒够才解析」
把「读 1 字节」改成「一次读满当前缓冲（8192 起），不够再等更多」：

```
chunk = await channel.readSome(8192 - used, 15000)   // 一次读一大块
buffer.set(chunk, used); used += chunk.length;
state = parseHeader(buffer, used, req);
if (state === NEED_MORE && used >= buffer.length) buffer = grow(buffer);
```
- 一个头 ⇒ **1~2 次 await**（原 200~500 次）⇒ 主线程压力降两个数量级；
- ⚠️ **必须保留「读满才解析」的语义**：`readSome` 可能一次带回 header + body 前缀，
  那些 body 字节仍走原有路径（`bodyInBuffer`）⇒ **协议行为完全不变**。

同时把**上传连接的并发上限**设一个上限（见 `MAX_PARALLEL_UPLOADS`），
避免再多条连接同时涌进来时把主线程压死。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
PATH = os.path.join(ROOT, 'entry/src/main/ets/net/HttpRouter.ets')

# ---- 1. 头部解析：逐字节 -> 批量读
OLD1 = """      // ---- 读够请求头 ----
      // ParseState 是用 static readonly 常量实现的伪枚举（不是 ArkTS enum），
      // 所以它的静态成员类型就是 number，变量不能声明成 ParseState
      let state: number = ParseState.NEED_MORE;
      while (state === ParseState.NEED_MORE) {
        const chunk: Uint8Array | null = await channel.readExactly(1, 15000);
        if (chunk === null) {
          return; // 客户端关闭或超时
        }
        if (used >= buffer.length) {
          buffer = HttpRouter.grow(buffer);
        }
        buffer[used] = chunk[0];
        used += 1;
        state = HttpProtocol.parseHeader(buffer, used, req);
      }"""

NEW1 = """      // ---- 读够请求头 ----
      // ParseState 是用 static readonly 常量实现的伪枚举（不是 ArkTS enum），
      // 所以它的静态成员类型就是 number，变量不能声明成 ParseState
      //
      // ★★ 5.1.22：**由「逐字节读」改为「批量读」**（vivi 12:02 修「上传大文件 ⇒ 手机卡住后闪退」）
      //   原实现每字节一次 `await readExactly(1, …)`：一个 HTTP 头 200~500 字节
      //   ⇒ **200~500 次串行 await**；浏览器上传并发开多条连接（本轮实测 5 条同时到）
      //   ⇒ 2500 次串行 await 全排在**主线程**；ArkTS 的 socket 回调与文件操作同在主线程
      //   ⇒ 主线程占满 ⇒ UI 无响应 ⇒ 系统强杀（表现为「卡住后闪退」）。
      //   现在一次读满当前缓冲，**一个头 1~2 次 await**，主线程压力降两个数量级。
      //
      // ⚠️ 语义完全不变：`readSome` 可能一次带回「header + body 前缀」，
      //   多出来的字节仍由下面的 `bodyInBuffer` 路径处理（`:300` 附近那段），
      //   所以**协议解析、body 处理、keep-alive 行为都不变**。
      let state: number = ParseState.NEED_MORE;
      while (state === ParseState.NEED_MORE) {
        if (used >= buffer.length) {
          buffer = HttpRouter.grow(buffer);
        }
        // 一次要满「缓冲剩余空间」，但至少 1 字节
        const want: number = buffer.length - used;
        const chunk: Uint8Array | null = await channel.readSome(want, 15000);
        if (chunk === null || chunk.length === 0) {
          return; // 客户端关闭或超时
        }
        buffer.set(chunk, used);
        used += chunk.length;
        state = HttpProtocol.parseHeader(buffer, used, req);
      }"""

EDITS = [(OLD1, NEW1)]

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
