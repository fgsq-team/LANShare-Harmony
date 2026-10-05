# -*- coding: utf-8 -*-
"""
v5.1.23 —— ★ 纯诊断版：网页上传卡死/闪退（vivi 12:07 报 5.1.22 仍闪退）

## 已排除的假设（避免重复劳动，记录在案）
| 假设 | 状态 |
|---|---|
| HTTP 头逐字节读导致 2500 次 await | ✅ 已修（5.1.22），**但仍闪退** ⇒ 不是它 |
| `MultipartStream.feed` 的 concat 是 O(n²)、815GB 复制 | ❌ **我算错了** —— `pump()` 在同一个 `feed` 内就把 hold 排空到只剩 `marker.length+1`（74 字节），复制量≈0.63GB（线性） |
| 我的「批量读」导致 hold 无限 grow | ❌ `parseHeader` 找到 `\r\n\r\n` 即 DONE，最多 1~2 轮 |

## 唯一还没验证的热点：`FileSink.append` 里的 **`fileIo.writeSync`**
`MultipartStream.write`（`:257`）每块调一次 `sink.append`，
而 `append`（`FileStorage.ets:246`）是 **`fileIo.writeSync` 同步系统调用**。
646MB / 256KB = **2585 次同步写**，全部在**主线程**（ArkTS 单线程）。
⇒ 这是目前最可能卡死 6 秒的点。

## 本版只做观测（不改任何行为）
在 `serveUpload` 的上传循环里插**分段计时**（低频采样，每 64 块打一行）：
```
[UP] blk#256 64.0MB tot=3200ms read=1800 feed=900 write=500 other=0 | avg=20.0MB/s
```
从而把「上传一次」的总耗时拆成：
- `read`  = `channel.readSome`（等对端数据）
- `feed`  = `mp.feed`（解析 + 落盘，含 writeSync）
- `write` = 单独测 `mp` 内部写盘（下面用「feed 减去解析」不好拆，故直接测 append 累计）
- `other` = 其余

★ 若 `feed` 占绝大多数 ⇒ 落盘（writeSync）是瓶颈，
  修法是**换异步写 / 加大块 / 换 Worker**，而不是继续调缓冲。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
PATH = os.path.join(ROOT, 'entry/src/main/ets/net/HttpRouter.ets')

OLD1 = """      const chunk: Uint8Array | null = await channel.readSome(UPLOAD_CHUNK, remain);
      if (chunk === null) {
        break; // 对端关闭或等待超时
      }
      got += chunk.length;
      chunks += 1;
      mp.feed(chunk);"""

NEW1 = """      // ★★ 5.1.23（纯诊断）：分段计时，把上传总耗时拆成 read / feed(解析+落盘) / other。
      //   动机：5.1.22 修完「头逐字节读」后**仍闪退** ⇒ 前一个假设被证伪。
      //   剩下的唯一未验证热点 = `mp.feed` 里的 **同步 `fileIo.writeSync`**（2585 次）。
      const tR0: number = Date.now();
      const chunk: Uint8Array | null = await channel.readSome(UPLOAD_CHUNK, remain);
      if (chunk === null) {
        break; // 对端关闭或等待超时
      }
      const tR1: number = Date.now();
      got += chunk.length;
      chunks += 1;
      mp.feed(chunk);
      const tR2: number = Date.now();
      // 低频采样：每 64 块（16 MiB）打一行，避免日志本身成瓶颈。
      if (chunks % 64 === 0) {
        const dtRead: number = tR1 - tR0;
        const dtFeed: number = tR2 - tR1;
        const el: number = Date.now() - tUp;
        const mbps: number = el > 0 ? (got / 1024 / 1024) * 1000 / el : 0;
        Log.i(TAG, `[UP] blk#${chunks} ${(got / 1024 / 1024).toFixed(1)}MB `
          + `tot=${el}ms read=${dtRead} feed=${dtFeed} other=${el - dtRead - dtFeed} `
          + `| avg=${mbps.toFixed(1)}MB/s`);
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
