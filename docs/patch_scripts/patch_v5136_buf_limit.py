# -*- coding: utf-8 -*-
"""
v5.1.16 —— 修正 5.0.58 遗留的**缓冲超限**问题（真机取证 + SDK 文档双重确认）

## ★ vivi 的反驳推翻了「必须多连接」的结论
「官方安卓原版**不支持分片**，网页端也能到 60MB/s」⇒
**TCP 单流本身就能跑 60MB/s** ⇒ 「单流窗口不够、必须多连接」的前提**不成立**。
我 5.1.14/5.1.15 那条并发路线方向错了。

## 真正的差异：收发缓冲**不对称**，且接收端那个值**超 SDK 上限**
| | sendBufferSize | receiveBufferSize | 位置 |
|---|---|---|---|
| 发送端 LanClient | 262144（顶格） | 262144 | `LanClient.ets:28` |
| 接收端 LanTcpServer | **4194304** | **4194304** | `LanTcpServer.ets:76` |

### SDK 原文（`@ohos.net.socket.d.ts:260`，`TCPExtraOptions.sendBufferSize`）
> Size of the TX buffer, in bytes. **The value ranges from 0 to 262144.**
> If this parameter is left unspecified or the unspecified value **exceeds the value range,
> the default value 8192 is used.**

⇒ **4MB 超出上限 ⇒ 该项回落到默认 8192**（不是报错，是静默回落！）
⇒ 5.0.58 那次「256KB → 4MB」的改动，**很可能从未真正生效**，
   而当时的注释却写「拉到上限是纯赚」—— 这是**基于错误前提的改动**。

### 为什么这能解释 27ms
发送端 262144 = 256KB，而**数据块是 1MB**（`CHUNK = 1024*1024-12`）
⇒ 每发 4 个缓冲就装满一块，必须等对端读走才能继续写。
实测反推：本机 28.0ms/块 vs 对端网页 17.8ms/块，**差 10.2ms**，
与「1MB 分 4 段、每段一次窗口等待」的量级相符。

## 本版改动
1. `LanTcpServer.TUNE_BUFFER_SIZE`：**4194304 → 262144**（合法顶格）
   —— 宁可顶格合法，也不要超限回落 8192。
2. `LanClient.TUNE_BUFFER_SIZE` 保持 262144（已是顶格），
   但**把注释里「这是 SDK 上限」这句写实**（原文是 0~262144，确为上限）。
3. 注释里**明确标注 5.0.58 那次的教训**，避免日后又有人想「调到 4MB」。

⚠️ 本版**不动**并发（`SEND_CONCURRENCY` 保持 2，但**文件数 < 2 时不启用**，
   与 5.1.14/5.1.15 行为一致）—— 等本版实测出缓冲效果后再决定并发要不要保留。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'

# ---------------------------------------------------------------- 1. 服务端缓冲
OLD1 = """/**
 * 监听套接字的 SO_RCVBUF / SO_SNDBUF（accept 出来的连接会继承这两个值）。
 *
 * ★ 5.0.58：**256KB → 4MB**。原来只有 256KB，**比一个数据块（2MB）还小**。
 *   对端（尤其 PC 端 `TCPClient::send()` = 裸 `::send()`，**不是**循环发满）
 *   在窗口关闭时会拿到「部分发送」，而它把部分发送当硬错误 → 中止该文件并改发
 *   FS_CLOSE，我方把它当数据体吞掉 → 干等 60 秒（真机取证见补丁头）。
 *   把接收窗口放大到一个块以上，`send()` 就能一次交完，从源头消除这个触发条件。
 *   ⚠️ 纯本机内核参数，**线上字节流一个都不变**，对原版 Android / 1.35 / PC 全部照旧互通。
 *   ⚠️ 调不上去只会打一条告警（系统 rmem_max 限制），不影响功能。
 */
const TUNE_BUFFER_SIZE: number = 4 * 1024 * 1024;"""

NEW1 = """/**
 * 监听套接字的 SO_RCVBUF / SO_SNDBUF（accept 出来的连接会继承这两个值）。
 *
 * ★★ 5.1.16：**4194304 → 262144，5.0.58 那个「4MB」是超限的，从未真正生效。**
 *
 * 【SDK 原文】`@ohos.net.socket.d.ts:260`（`TCPExtraOptions.sendBufferSize`）：
 *   > Size of the TX buffer, in bytes. **The value ranges from 0 to 262144.**
 *   > If this parameter is left unspecified or the unspecified value
 *   > **exceeds the value range, the default value 8192 is used.**
 *
 * ⇒ 4MB **超出上限** ⇒ 该项被**静默回落**到默认 8192（不是报错，所以毫无征兆）。
 * ⇒ 5.0.58 那次「256KB → 4MB」是**基于错误前提的改动**：
 *   当时的注释写着「把接收窗口放大到一个块以上，纯赚」——
 *   实际上压根没生效，而「256KB 比一个数据块小」这个担忧也一直悬着。
 *
 * 【本版取值理由】宁可**顶格合法**（262144），也不要超限回落（8192）。
 *   两者相差 32 倍：合法顶格 = 256KB，超限回落 = 8KB。
 *   5.0.58 想解决的那个问题（PC 端裸 `::send()` 遇到窗口关闭拿到「部分发送」）
 *   在 256KB 下依然比 8KB 宽裕得多。
 *
 * ⚠️ 纯本机内核参数，**线上字节流一个都不变** ⇒ 对原版 Android / 1.35 / PC 全部照旧互通。
 * ⚠️ 调不上去只会打一条告警（系统 wmem_max 限制），不影响功能。
 */
const TUNE_BUFFER_SIZE: number = 262144;"""

# ---------------------------------------------------------------- 2. 发送端注释写实
OLD2 = """ * 收发缓冲目标值 = 262144，这是 SDK 允许的**上限**
 * （`ExtraOptionsBase.sendBufferSize` 文档：范围 0~262144，默认 8192）。
 * 想再大也设不进去，所以直接顶格。
 */
const TUNE_BUFFER_SIZE: number = 262144;"""

NEW2 = """ * 收发缓冲目标值 = 262144，这是 SDK 允许的**上限**
 * （`ExtraOptionsBase.sendBufferSize` 文档：范围 0~262144，默认 8192）。
 * 想再大也设不进去，所以直接顶格。
 *
 * ★★ 5.1.16：**别再想调到 4MB** —— 服务端曾经填过 4194304，
 *   而 SDK 原文是「**超出范围则回落默认 8192**」，即**静默失效**。
 *   发送端这个 262144 至少是**真生效**的（合法顶格）。
 *
 * ⚠️ 仍未解的疑点（待实测确认）：262144 = 256KB 而数据块是 1MB，
 *   理论上每发 4 个缓冲就装满一块、需等对端读走。
 *   若缓冲确为瓶颈，可考虑的方向是**减小 CHUNK**（对端缓冲也吃紧，暂不动）
 *   或**多条连接**（每条带自己的窗口）。
 */
const TUNE_BUFFER_SIZE: number = 262144;"""

EDITS = [
    ('entry/src/main/ets/net/LanTcpServer.ets', OLD1, NEW1),
    ('entry/src/main/ets/net/LanClient.ets', OLD2, NEW2),
]

cache = {}

def load(p):
    return io.open(os.path.join(ROOT, p), encoding='utf-8').read()

def save(p, s):
    assert '\r\n' not in s, 'CRLF 混入: ' + p
    for _, _, new in EDITS:
        assert '\ufffd' not in new
    io.open(os.path.join(ROOT, p), 'w', encoding='utf-8', newline='\n').write(s)

for path, old, new in EDITS:
    if path not in cache:
        cache[path] = load(path)
    c = cache[path].count(old)
    assert c == 1, 'OLD 命中 %d（应 1）: %s' % (c, path)
    cache[path] = cache[path].replace(old, new, 1)

if '--dry' in sys.argv:
    print('DRY-RUN OK（%d 处）' % len(EDITS))
    raise SystemExit(0)

for path, s in cache.items():
    save(path, s)
    print('  已写 %s' % path)
print('APPLIED')
