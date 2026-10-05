# -*- coding: utf-8 -*-
"""
5.1.38 —— 治本：`indexOfSeq` 换成原生 indexOf + 二字节先验；并回退 5.1.37 写盘 bug

【★ 先修 bug：5.1.37 引入数据不落盘】
  SDK `@ohos.file.fs.d.ts` 的 WriteOptions 明确写：
      offset?: Start position of the file to write (current filePointer plus **offset**)
  ⇒ `offset` 是**文件内偏移**，不是 buffer 内偏移。
  我在 5.1.37 传了 `data.byteOffset` ⇒ 写入位置错 ⇒ **处理 586 MB，文件只有 1.0 MB**。
  且 `writeSync` **没有**「只写 buffer 子区间」的参数 ⇒ 传 subarray 视图必须先拷贝。
  ⇒ 回退到 5.1.36 的 `buffer.slice()` 写法（已验证能正确落盘）。

【★ 真正的病根：indexOfSeq 的 1 MiB 全量扫描 ≈ 53ms/块】
  证据链：
  · 5.1.36（有 slice 拷贝）与 5.1.37（零拷贝）**`fd` 都是 53~55ms** ——
    拷贝量差 99% 而耗时不变 ⇒ 53ms **不是**拷贝。
  · 5.1.37 的 writeSync 实际没写成数据（bug）⇒ 53ms 也**不是**真落盘。
  · feed 内部只剩一个重活：`indexOfSeq(chunk, marker, 0)` —— 对 1 MiB 逐字节扫描。
    现有实现虽有首字节跳跃，但仍是 **100 万次 ArkTS 循环迭代**。
  · 浏览器对 645MB 文件开 **6 条并发连接** ⇒ 6 × 53ms 争抢同一主线程 ⇒ 饱和
    ⇒ vsync 插不进来 + 某次超长 ⇒ THREAD_BLOCK_6S。
  · 对照组为何不崩：V5Transfer 收私有协议是**定长帧**（长度字段直接定位），
    **根本不需要逐字节搜分隔符** ⇒ 这才是「同一场景两种结果」的真正差异，
    不是块大小、也不是同步/异步落盘（前七轮据此推断均被实测推翻）。

【改法】
  1. `FileSink.append` 回退 offset/length，恢复 `buffer.slice()`（修数据不落盘）。
  2. `indexOfSeq` 改用**原生 `Uint8Array.indexOf`** 跳首字节（native C++ 实现，
     比 ArkTS 循环快一个量级）+ **第二字节先验**（marker 形如 `\r\n--boundary`，
     c1 = 10；文件内容里 \r\n 极罕见 ⇒ 完整比对的候选从 ~4096 降到 ~16）。
  3. 保留 5.1.37 的 feed 零拷贝快速路径（仍省掉 `concat(hold, chunk)` 那次 1 MiB 拷贝，
     每块拷贝 3 MiB → 1 MiB）。保留全部诊断。
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

SENTINEL = '5.1.38 扫描提速'
if SENTINEL in ms:
    print('ALREADY APPLIED'); sys.exit(0)

# ============================================================
# ① 回退 FileSink.append：恢复 buffer.slice() 拷贝
# ============================================================
a1 = ('      // ★★ 5.1.37 零拷贝：不再 `buffer.slice()` 复制一份。\n'
      '      //   直接用 writeSync 的 offset/length 写出 data 的**可见区间**，\n'
      '      //   配合上游传 subarray（视图）⇒ 整条链路零拷贝。\n'
      '      //   （5.1.36 实测每块 1 MiB 要拷 3 次 ⇒ GB 级堆分配 ⇒ GC 卡主线程。）\n'
      '      // ⚠️ 传入的 data 可以是 subarray（共享大 buffer 的视图），\n'
      '      //    因此**必须**带 offset/length，只传 buffer 会写出整个底层 buffer（数据错乱）。\n'
      '      // ★★ 5.1.36-diag2：单次 writeSync 计时。\n'
      '      //   目的：把「mp.feed 慢」进一步拆成「解析慢」还是「落盘慢」。\n'
      '      const tW0: number = Date.now();\n'
      '      const n: number = fileIo.writeSync(this.fd, data.buffer as ArrayBuffer, {\n'
      '        offset: data.byteOffset,\n'
      '        length: data.byteLength\n'
      '      });\n'
      '      const dtW: number = Date.now() - tW0;')
assert fs.count(a1) == 1, 'A1 count = %d' % fs.count(a1)

new1 = ('      // ⚠️⚠️ 5.1.38 回退说明（**踩过的坑，勿再改**）：\n'
        '      //   5.1.37 曾改成 `writeSync(fd, data.buffer, {offset, length})` 想省掉这次拷贝，\n'
        '      //   **是错的** —— SDK WriteOptions 的 offset 语义是\n'
        '      //   「Start position of the file to write (current filePointer + offset)」，\n'
        '      //   即**文件内偏移**，不是 buffer 内偏移。\n'
        '      //   真机后果：处理 586 MB，落地文件只有 1.0 MB（写到了错误位置）。\n'
        '      //   而 `writeSync` 并没有「只写 buffer 子区间」的参数 ⇒ 传 subarray 视图\n'
        '      //   必须先拷贝出精确大小的 buffer。\n'
        '      const exact: boolean = data.byteOffset === 0 && data.byteLength === data.buffer.byteLength;\n'
        '      const buf: ArrayBuffer = exact\n'
        '        ? data.buffer as ArrayBuffer\n'
        '        : data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;\n'
        '      // ★★ 5.1.36-diag2：单次 writeSync 计时（把「feed 慢」拆成「解析」vs「落盘」）。\n'
        '      const tW0: number = Date.now();\n'
        '      const n: number = fileIo.writeSync(this.fd, buf);\n'
        '      const dtW: number = Date.now() - tW0;')

fs = fs.replace(a1, new1, 1)

# ============================================================
# ② indexOfSeq 提速：原生 indexOf + 第二字节先验
# ============================================================
a2 = ('    const limit: number = hay.length - n;\n'
      '    const first: number = needle[0];\n'
      '    for (let i = from; i <= limit; i++) {\n'
      '      if (hay[i] !== first) {\n'
      '        continue;\n'
      '      }\n'
      '      let j: number = 1;\n'
      '      while (j < n && hay[i + j] === needle[j]) {\n'
      '        j++;\n'
      '      }\n'
      '      if (j === n) {\n'
      '        return i;\n'
      '      }\n'
      '    }\n'
      '    return -1;')
assert ms.count(a2) == 1, 'A2 count = %d' % ms.count(a2)

new2 = ('    const limit: number = hay.length - n;\n'
        '    if (from > limit) {\n'
        '      return -1;\n'
        '    }\n'
        '    const c0: number = needle[0];\n'
        '    // ★ 5.1.38：第二字节先验。marker 形如 `\\r\\n--<boundary>`，c1 = 10。\n'
        '    //   文件内容里 `\\r\\n` 极罕见（1 MiB 中约 16 处），\n'
        '    //   先验掉 c1 可把「需要完整比对」的候选从 ~4096 降到 ~16。\n'
        '    const c1: number = n > 1 ? needle[1] : -1;\n'
        '    let i: number = from;\n'
        '    while (i <= limit) {\n'
        '      // ★★ 5.1.38 扫描提速：用**原生** Uint8Array.indexOf 跳首字节。\n'
        '      //   原实现是 ArkTS 逐字节 for 循环，扫 1 MiB 要 100 万次迭代 ≈ 53ms/块；\n'
        '      //   实测（5.1.36/5.1.37 的 `[B] fd=53~55ms`，且拷贝量差 99% 而耗时不变）\n'
        '      //   证明这 53ms 就是本函数的扫描成本，是整个崩溃的病根。\n'
        '      //   浏览器对大文件开 6 条并发连接 ⇒ 6 × 53ms 争抢同一主线程 ⇒ 饱和\n'
        '      //   ⇒ vsync 插不进来 ⇒ THREAD_BLOCK_6S。\n'
        '      //   native indexOf 走 C++ 实现，比 ArkTS 循环快一个量级。\n'
        '      const j: number = hay.indexOf(c0, i);\n'
        '      if (j < 0 || j > limit) {\n'
        '        return -1;\n'
        '      }\n'
        '      if (c1 >= 0 && hay[j + 1] !== c1) {\n'
        '        i = j + 1; // 首字节命中但次字节不符 ⇒ 极可能是普通数据，跳过\n'
        '        continue;\n'
        '      }\n'
        '      let k: number = c1 >= 0 ? 2 : 1;\n'
        '      while (k < n && hay[j + k] === needle[k]) {\n'
        '        k++;\n'
        '      }\n'
        '      if (k === n) {\n'
        '        return j;\n'
        '      }\n'
        '      i = j + 1;\n'
        '    }\n'
        '    return -1;')

ms = ms.replace(a2, new2, 1)

# ============================================================
# ③ 版本号
# ============================================================
assert '"versionCode": 5000137' in app, 'versionCode anchor'
assert '"versionName": "5.1.37"' in app, 'versionName anchor'
app = app.replace('"versionCode": 5000137', '"versionCode": 5000138', 1)
app = app.replace('"versionName": "5.1.37"', '"versionName": "5.1.38"', 1)

# ============================================================
# 统一落盘
# ============================================================
for p, s in ((MS, ms), (FS, fs), (APP, app)):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

ms2 = io.open(MS, encoding='utf-8', newline='').read()
fs2 = io.open(FS, encoding='utf-8', newline='').read()
print('5.1.38 扫描提速 :', ms2.count('5.1.38 扫描提速'))
print('原生 indexOf    :', ms2.count('hay.indexOf(c0, i)'))
print('二字节先验      :', ms2.count('c1 >= 0 && hay[j + 1] !== c1'))
print('回退 exact 分支 :', fs2.count('const exact: boolean'))
print('去掉 offset 写法:', 0 if 'offset: data.byteOffset' in fs2 else 1)
print('[B] 诊断保留    :', ms2.count('[B] #'))
print('CRLF            :', ms2.count('\r\n') + fs2.count('\r\n'))
print('OK 5.1.38 applied')
