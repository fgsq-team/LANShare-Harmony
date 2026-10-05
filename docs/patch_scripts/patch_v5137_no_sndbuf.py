# -*- coding: utf-8 -*-
"""
v5.1.17 —— ★ 发送端真正的根因：**别显式设 SO_SNDBUF**

## vivi 的两句反驳合起来，把方向彻底纠正了
1. 「官方安卓**不支持分片**，网页也能 60MB/s」
   ⇒ **TCP 单流本身就能跑 60** ⇒ 我 5.1.14/5.1.15 的「必须多连接」结论**错了**。
2. 「两次测试鸿蒙 APP 都是**发送端**，和接收端无关」
   ⇒ `LanTcpServer` 的缓冲改动**对本次测速毫无作用**（接收端是官方安卓，不是我们）。

## 真根因：显式 setsockopt(SO_SNDBUF) 会**关闭 Linux 内核的 TCP 自动调优**
| | 做法 | 后果 |
|---|---|---|
| 浏览器 / 官方安卓 | **不设** SO_SNDBUF | 内核自动扩缩容（16KB → tcp_wmem 上限，常见数 MB）⇒ **60MB/s** |
| 鸿蒙 `LanClient` | 显式设 **262144** | **自动调优被关**，缓冲钉死 256KB ⇒ 1MB 块分 4 段等窗口 ⇒ **35.7MB/s** |

而 SDK 上限恰好是 262144（`@ohos.net.socket.d.ts:260`：范围 0~262144，
超范围静默回落默认 8192）⇒ **顶格反而是最坏选择**。

## 本版三处改动
1. **`LanClient.applyTuning` 不再设 `sendBufferSize` / `receiveBufferSize`**
   —— 只保留 `TCPNoDelay`（那个是必要的，见 LanClient 注释里 Nagle 40ms 的分析）。
   ⚠️ 服务端 `setExtraOptions` 不接受「只传一个字段」以外的形式，
   但**可以只传 TCPNoDelay**（其余字段留空 = 不下发该选项）。
2. `LanTcpServer.TUNE_BUFFER_SIZE`：4MB → 262144（**5.0.58 遗留的静默失效**，
   与本次测速无关，但顺手修正 —— 它一直以为自己在 4MB）。
3. 修 5.1.15 引入的编译错误：`{...r}` 对象展开 ArkTS 不允许（arkts-no-spread），
   改为**逐字段显式构造** `TransferReport`。

## 开关
`TUNE_SOCKET_BUFFERS = false` ⇒ 想恢复旧行为改成 true 即可。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'

# ================================================================ 1. LanClient：不设缓冲
OLD1 = """  private static async applyTuning(s: socket.TCPSocket): Promise<void> {
    try {
      await s.setExtraOptions({
        TCPNoDelay: true,
        sendBufferSize: TUNE_BUFFER_SIZE,
        receiveBufferSize: TUNE_BUFFER_SIZE
      } as socket.TCPExtraOptions);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `套接字调优未生效（沿用系统默认）: ${err.code}`);
    }
  }"""

NEW1 = """  private static async applyTuning(s: socket.TCPSocket): Promise<void> {
    try {
      if (TUNE_SOCKET_BUFFERS) {
        await s.setExtraOptions({
          TCPNoDelay: true,
          sendBufferSize: TUNE_BUFFER_SIZE,
          receiveBufferSize: TUNE_BUFFER_SIZE
        } as socket.TCPExtraOptions);
      } else {
        // ★★ 5.1.17：**只设 TCPNoDelay，绝不设 sendBufferSize / receiveBufferSize。**
        //
        // 【为什么这是发送慢的真根因】
        // 显式 `setsockopt(SO_SNDBUF)` 会**关闭 Linux 内核的 TCP 自动调优**：
        //   · 不设  ⇒ 内核按需自动扩缩容（16KB 起，逐步涨到 tcp_wmem 上限，
        //              常见数 MB）⇒ 浏览器/官方安卓网页能到 60MB/s；
        //   · 设为 262144 ⇒ **自动调优被关**，缓冲被钉死在 256KB。
        // 而我们的数据块是 **1MB**（`CHUNK = 1024*1024-12`）
        // ⇒ 每发 4 个缓冲就装满一块，必须等对端读走才能继续
        // ⇒ 背压等待落在 `await sock.write()` 里，正是诊断看到的
        //   `send` 占 97.6%（26~28ms/块）。
        //
        // 【为什么 262144 是最坏值】
        // SDK 上限恰好就是 262144（`@ohos.net.socket.d.ts:260`：范围 0~262144，
        // 超范围**静默回落**默认 8192）⇒ 「顶格」等于「钉死 256KB」，
        // 比内核自动扩容差一个数量级。
        await s.setExtraOptions({
          TCPNoDelay: true
        } as socket.TCPExtraOptions);
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `套接字调优未生效（沿用系统默认）: ${err.code}`);
    }
  }"""

# ================================================================ 2. LanClient：新增开关
OLD2 = """const TUNE_BUFFER_SIZE: number = 262144;"""

NEW2 = """const TUNE_BUFFER_SIZE: number = 262144;

/**
 * ★★ 5.1.17：是否显式设置收发缓冲。
 *
 * **默认 false = 不设**，让 Linux 内核自己做 TCP 自动调优。
 * 见 `applyTuning` 里的完整论证：显式设 SO_SNDBUF 会关闭自动调优，
 * 把缓冲钉死在 256KB，而数据块是 1MB ⇒ 背压等待全落在 `await write()` 里
 * （真机诊断：`send` 占 97.6%）。浏览器/官方安卓不设，所以能到 60MB/s。
 *
 * 改回 true 可恢复 5.1.16 及更早的显式设值行为（仅供对比回退）。
 */
const TUNE_SOCKET_BUFFERS: boolean = false;"""

# ================================================================ 3. V5Transfer：修对象展开
OLD3 = """      const wrapped: TransferCallback = (r: TransferReport): void => {
        const j: number = Math.max(0, r.fileIndex - 1);         // 本车道内 0-based
        const globalIdx: number = j * laneCount + laneIdx + 1;  // 全局项序（1-based）
        const cur: number = laneStartBytes + r.bytes;
        onReport({
          ...r,
          fileIndex: globalIdx,
          fileCount: files.length,
          bytes: r.done ? grandBytes : cur,
          percent: grandBytes > 0 ? Math.floor(cur * 100 / grandBytes) : r.percent
        });
      };"""

NEW3 = """      const wrapped: TransferCallback = (r: TransferReport): void => {
        const j: number = Math.max(0, r.fileIndex - 1);         // 本车道内 0-based
        const globalIdx: number = j * laneCount + laneIdx + 1;  // 全局项序（1-based）
        const cur: number = laneStartBytes + r.bytes;
        // ⚠️ ArkTS **禁止对象展开**（`arkts-no-spread`），
        //   且 `TransferReport` 是 class（不是字面量）⇒ 必须逐字段重建。
        const g: TransferReport = new TransferReport();
        g.direction = r.direction;
        g.peer = r.peer;
        g.fileName = r.fileName;
        g.fileNames = r.fileNames;
        g.fileIndex = globalIdx;
        g.fileCount = files.length;
        g.bytes = r.done ? grandBytes : cur;
        g.fileSize = r.fileSize;
        g.percent = grandBytes > 0 ? Math.floor(cur * 100 / grandBytes) : r.percent;
        g.done = r.done;
        g.ok = r.ok;
        g.message = r.message;
        onReport(g);
      };"""

EDITS = [
    ('entry/src/main/ets/net/LanClient.ets', OLD1, NEW1),
    ('entry/src/main/ets/net/LanClient.ets', OLD2, NEW2),
    ('entry/src/main/ets/service/V5Transfer.ets', OLD3, NEW3),
]

cache = {}

def load(p):
    return io.open(os.path.join(ROOT, p), encoding='utf-8').read()

for path, old, new in EDITS:
    if path not in cache:
        cache[path] = load(path)
    c = cache[path].count(old)
    assert c == 1, 'OLD 命中 %d（应 1）: %s' % (c, path)
    cache[path] = cache[path].replace(old, new, 1)

if '--dry' in sys.argv:
    print('DRY-RUN OK（%d 处）' % len(EDITS))
    for p, s in cache.items():
        print('  %-22s %6d chars' % (os.path.basename(p), len(s)))
    raise SystemExit(0)

for path, s in cache.items():
    assert '\r\n' not in s, 'CRLF: ' + path
    io.open(os.path.join(ROOT, path), 'w', encoding='utf-8', newline='\n').write(s)
    print('  已写 %s' % path)
print('APPLIED')
