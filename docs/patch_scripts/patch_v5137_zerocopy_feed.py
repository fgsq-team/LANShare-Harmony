# -*- coding: utf-8 -*-
"""
5.1.37 —— 治本：网页上传的 multipart 数据路径改**零拷贝**

【根因（5.1.36-diag2 实测定案）】
  崩溃时日志最后一行是 `[B540`（进入第 541 块的**前置标记**），没有对应的 `[B] #540`
  ⇒ 主线程卡在 `mp.feed()` 内（`readSome` 是 await，等数据时主线程空闲，不可能被判无响应）。
  且 `[SLOW-IO]` 告警 **0 条** ⇒ 单次 writeSync 从不慢 ⇒ 卡的不是落盘，是**内存操作**。

  原 feed() 每块（1 MiB）的代价：
    concat(hold, chunk)            分配 + 拷贝 ~1 MiB
    indexOfSeq 扫描整个 hold       扫描       ~1 MiB
    hold.slice(0, n)               分配 + 拷贝 ~1 MiB
    sink.append 内 buffer.slice()  又拷贝     ~1 MiB
  ⇒ 645 MB 文件 ≈ GB 级堆分配 ⇒ GC 把主线程卡住数秒 ⇒ THREAD_BLOCK_6S。

【改法：两处零拷贝】
  1. `MultipartStream.feed()` 加**零拷贝快速路径**：
     S_BODY 且「chunk 内」与「hold+chunk 头接缝内」都找不到 marker 时，
     除尾部 keep 字节（可能成为下块 marker 的前缀）外全部**零拷贝直写**。
     每块拷贝量从 ~3 MiB 降到几十字节。
  2. `FileSink.append()` 不再 `buffer.slice()` 拷贝，改用
     `writeSync(fd, buf, {offset, length})` 直写 data 的可见区间，
     配合上游 `subarray()`（视图）⇒ 整条链路零拷贝。

【正确性论证（快速路径）】
  设 keep = marker.length + 1。
  · 已搜 chunk 内部 ⇒ chunk 内无 marker；
  · 已搜 seam = hold + chunk.subarray(0, marker.length) ⇒ 跨界 marker 也不存在
    （marker 若在 hold 内位置 p 起始，则 p+marker.length <= hold.length+marker.length
     必然落在 seam 内，故 seam 无 marker ⇒ hold 内无 marker 起始）；
  ⇒ 因此 hold 全部 + chunk 的 [0, len-keep) 都是纯文件内容，可安全写盘；
     只保留 chunk 尾部 keep 字节作为下一个 marker 的前缀候选。
  任一条件不满足（找到 marker / 非 S_BODY / hold 异常大）⇒ 退回原 concat+pump 慢路径。
"""
import io
import os
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
MS = os.path.join(ET, 'service', 'MultipartStream.ets')
FS = os.path.join(ET, 'service', 'FileStorage.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

ms = io.open(MS, encoding='utf-8', newline='').read()
fs = io.open(FS, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

SENTINEL = '零拷贝快速路径'
if SENTINEL in ms:
    print('ALREADY APPLIED'); sys.exit(0)

# ============================================================
# ① feed()：零拷贝快速路径
# ============================================================
a1 = ('    this.fed += chunk.length;\n'
      '    this.hold = MultipartStream.concat(this.hold, chunk);\n'
      '    this.pump();')
assert ms.count(a1) == 1, 'A1 count = %d' % ms.count(a1)

new1 = (
    '    this.fed += chunk.length;\n'
    '\n'
    '    // ★★★★ 5.1.37 零拷贝快速路径（治本，依据 5.1.36-diag2 实测）\n'
    '    // 原实现每块（1 MiB）要：concat 拷 1 MiB、indexOfSeq 扫 1 MiB、\n'
    '    // hold.slice(0,n) 拷 1 MiB、sink.append 里 buffer.slice() 再拷 1 MiB。\n'
    '    // 645 MB 文件 ⇒ GB 级堆分配 ⇒ GC 把主线程卡住数秒 ⇒ THREAD_BLOCK_6S\n'
    '    // （实测：崩溃时最后一行是进入标记 `[B540`，没有对应汇总行 ⇒ 卡在 feed 内；\n'
    '    //   且 `[SLOW-IO]` 0 条 ⇒ 不是落盘慢）。\n'
    '    //\n'
    '    // 快速路径前提（任一不满足就退回原 concat+pump 慢路径）：\n'
    '    //   · state === S_BODY（正在收文件内容）\n'
    '    //   · chunk 内部**无** marker\n'
    '    //   · 接缝（hold + chunk 头 marker.length 字节）**无** marker ⇒ 无跨界\n'
    '    //   · hold 长度正常（<= marker.length + 8），异常则走慢路径更安全\n'
    '    // 满足 ⇒ hold 全部 + chunk 的 [0, len-keep) 都是纯文件内容，零拷贝直写，\n'
    '    //        只把 chunk 尾部 keep 字节拷进 hold，作为下块 marker 的前缀候选。\n'
    '    // 每块拷贝量：~3 MiB → 几十字节。\n'
    '    if (this.state === MultipartStream.S_BODY && this.sink !== null &&\n'
    '      this.hold.length <= this.marker.length + 8) {\n'
    '      const keep: number = this.marker.length + 1;\n'
    '      let hit: boolean = MultipartStream.indexOfSeq(chunk, this.marker, 0) >= 0;\n'
    '      if (!hit && this.hold.length > 0) {\n'
    '        // 接缝：hold 尾部 + chunk 头部，覆盖 marker 全长即可判定是否跨界\n'
    '        const headLen: number = Math.min(this.marker.length, chunk.length);\n'
    '        const seam: Uint8Array =\n'
    '          MultipartStream.concat(this.hold, chunk.subarray(0, headLen));\n'
    '        hit = MultipartStream.indexOfSeq(seam, this.marker, 0) >= 0;\n'
    '      }\n'
    '      if (!hit) {\n'
    '        // hold 内已确认无 marker 起始（接缝搜索已覆盖）⇒ 全部写掉\n'
    '        this.write(this.hold);\n'
    '        const cut: number = Math.max(0, chunk.length - keep);\n'
    '        if (cut > 0) {\n'
    '          this.write(chunk.subarray(0, cut)); // ★ subarray = 视图，零拷贝\n'
    '        }\n'
    '        this.hold = chunk.slice(cut); // 只拷尾部 keep 字节（几十字节）\n'
    '        return;\n'
    '      }\n'
    '    }\n'
    '\n'
    '    this.hold = MultipartStream.concat(this.hold, chunk);\n'
    '    this.pump();')

ms = ms.replace(a1, new1, 1)

# ============================================================
# ② pump() 慢路径：slice(0, ...) → subarray（视图，零拷贝）
#    注意：hold 的重切片必须保持 slice（要真的拷出 keep 字节，
#    否则视图会钉住整个 1 MiB buffer，反而更糟）。
# ============================================================
a2 = '          this.write(this.hold.slice(0, i));'
assert ms.count(a2) == 1, 'A2 count = %d' % ms.count(a2)
ms = ms.replace(a2, '          this.write(this.hold.subarray(0, i)); // ★ 5.1.37 视图，零拷贝', 1)

a3 = '            this.write(this.hold.slice(0, n));'
assert ms.count(a3) == 1, 'A3 count = %d' % ms.count(a3)
ms = ms.replace(a3, '            this.write(this.hold.subarray(0, n)); // ★ 5.1.37 视图，零拷贝', 1)

# ============================================================
# ③ FileSink.append：writeSync 用 offset/length 直写，去掉 buffer.slice 拷贝
# ============================================================
a4a = ('      const exact: boolean = data.byteOffset === 0 && data.byteLength === data.buffer.byteLength;\n'
       '      const buf: ArrayBuffer = exact\n'
       '        ? data.buffer as ArrayBuffer\n'
       '        : data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;\n')
assert fs.count(a4a) == 1, 'A4a count = %d' % fs.count(a4a)
fs = fs.replace(
    a4a,
    '      // ★★ 5.1.37 零拷贝：不再 `buffer.slice()` 复制一份。\n'
    '      //   直接用 writeSync 的 offset/length 写出 data 的**可见区间**，\n'
    '      //   配合上游传 subarray（视图）⇒ 整条链路零拷贝。\n'
    '      //   （5.1.36 实测每块 1 MiB 要拷 3 次 ⇒ GB 级堆分配 ⇒ GC 卡主线程。）\n', 1)

a4b = '      const n: number = fileIo.writeSync(this.fd, buf);'
assert fs.count(a4b) == 1, 'A4b count = %d' % fs.count(a4b)
fs = fs.replace(
    a4b,
    '      const n: number = fileIo.writeSync(this.fd, data.buffer as ArrayBuffer, {\n'
    '        offset: data.byteOffset,\n'
    '        length: data.byteLength\n'
    '      });', 1)

# ============================================================
# ④ 版本号
# ============================================================
assert '"versionCode": 5000136' in app, 'versionCode anchor'
assert '"versionName": "5.1.36-diag"' in app, 'versionName anchor'
app = app.replace('"versionCode": 5000136', '"versionCode": 5000137', 1)
app = app.replace('"versionName": "5.1.36-diag"', '"versionName": "5.1.37"', 1)

# ============================================================
# 统一落盘
# ============================================================
for p, s in ((MS, ms), (FS, fs), (APP, app)):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

ms2 = io.open(MS, encoding='utf-8', newline='').read()
fs2 = io.open(FS, encoding='utf-8', newline='').read()
print('零拷贝快速路径 :', ms2.count('零拷贝快速路径'))
print('subarray 写入  :', ms2.count('.subarray(0, i)') + ms2.count('.subarray(0, cut)') + ms2.count('.subarray(0, n)'))
print('hold 保留 slice:', ms2.count('this.hold = chunk.slice(cut)'))
print('append offset  :', fs2.count('offset: data.byteOffset'))
print('旧 exact 分支  :', fs2.count('const exact: boolean'))
print('[B] 诊断保留   :', ms2.count('feed(chunk') )
print('CRLF           :', ms2.count('\r\n') + fs2.count('\r\n'))
print('OK 5.1.37 applied')
