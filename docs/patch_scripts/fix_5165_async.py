#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.65 A3 修正：copyTo 改异步（按 SDK 真实签名）（幂等）

上一版写错了两处，本版修：
  1. `copyTo` 声明是 `static copyTo(...): string`（**非 async**）⇒ 里面用 await 直接编译失败
     （`Cannot use keyword 'await' outside an async function`）。
     ⇒ 改成 `static async copyTo(...): Promise<string>`，**两个调用点都要加 await**。
  2. 异步 `fileIo.read` **不是**「返回 ArrayBuffer」，真实签名是
     `read(fd, buffer, options?): Promise<ReadOut>`，**要自己传入 buffer**，
     返回的 `ReadOut.bytesRead` 才是读到的字节数。
     （我上一版误以为能像 `readSync(fd, len)` 那样返回 buffer —— 那是 Node 的 API。）

SDK 出处（command-line-tools/sdk/default/openharmony/ets/api/@ohos.fileio.d.ts）：
  1197: declare function read(fd, buffer: ArrayBuffer, options?): Promise<ReadOut>
  1511: declare function write(fd, buffer: ArrayBuffer|string, options?): Promise<number>
  2230: interface ReadOut { bytesRead: number }
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

EDITS = []


def edit(rel, old, new, probe):
    EDITS.append((rel, old, new, probe))


# ---- 1) copyTo 声明改 async ----
edit('entry/src/main/ets/service/ExportService.ets',
     "  static copyTo(srcPath: string, dstUri: string, name: string): string {",
     """  /**
   * ★★ 5.1.65：改成 **async** —— 原来同步 `readSync`/`writeSync` 逐块拷贝，
   *   40 张图把主线程占满 2~4 秒（vivi 2026-10-05 真机实测）。
   *   ⚠️ **两个调用点都要加 `await`**（见 Index.ets 的两处调用）。
   */
  static async copyTo(srcPath: string, dstUri: string, name: string): Promise<string> {""",
     '5.1.65：改成 **async**')

# ---- 2) 拷贝循环按 SDK 真实签名重写 ----
_LOOP_OLD = """      // ★★ 5.1.65：同步 64KB 拷贝改**异步**。
      //   原来 `readSync/writeSync` 逐块同步，40 张图把主线程占满 2~4 秒
      //   （vivi 2026-10-05 真机实测），存相册期间界面全冻。
      //   ⚠️ 与「5.1.34 落盘改异步掉速 1/6」**不是同一场景**：那次是
      //   **网页上传流控**（1.35 每块 256KiB × 6 并发连接、边收边落盘、
      //   microtask 抢占宏任务导致流控饿死）；这里是**串行、用户已点确认、
      //   无流控交织**，异步让出的只是「拷贝」这一段，不参与流控调度。
      //   ⚠️ `fileIo.read(fd, len)` 返回**新读的 ArrayBuffer**（长度 ≤ len），
      //   直接整段 write 即可，不需要像同步版那样 `slice(0, n)`。
      const bufLen: number = COPY_CHUNK;
      while (true) {
        const chunk: ArrayBuffer = await fileIo.read(src.fd, bufLen);
        if (chunk.byteLength <= 0) {
          break;
        }
        await fileIo.write(dst.fd, chunk);
        written += chunk.byteLength;
      }"""

_LOOP_NEW = """      // ★★ 5.1.65：同步 64KB 拷贝改**异步**（40 张图曾把主线程占满 2~4 秒）。
      //
      // ## 为什么这里异步是安全的（与「5.1.34 掉速 1/6」不冲突）
      //   那次是**网页上传流控**：1.35 每块 256KiB × 6 并发连接、边收边落盘，
      //   microtask 抢占宏任务导致**流控饿死**（要按时 ack / 看流控窗口）。
      //   这里是 `copyTo`：**串行、用户已点确认框、无协议交织** ——
      //   异步让出的主线程时间没有任何状态机要抢，只会让 UI 呼吸。
      //
      // ## SDK 真实签名（别照抄 Node 的写法）
      //   `read(fd, buffer, options?): Promise<ReadOut>` —— **要自己传入 buffer**，
      //   返回 `ReadOut.bytesRead`；它**不是**「返回读到的 buffer」。
      //   `write(fd, buffer, options?): Promise<number>` —— 传要写的 buffer。
      //   出处：@ohos.fileio.d.ts 第 1197 / 1511 / 2230 行。
      const buf: ArrayBuffer = new ArrayBuffer(COPY_CHUNK);
      while (true) {
        const out: fileIo.ReadOut = await fileIo.read(src.fd, buf);
        const n: number = out.bytesRead;
        if (n <= 0) {
          break;
        }
        // 只写实际读到的部分（`fileIo` 没有导出 WriteOptions 类型，
        // 与其硬凑 options 对象，不如裁一段 ArrayBuffer 来得稳）。
        const piece: ArrayBuffer = buf.slice(0, n);
        await fileIo.write(dst.fd, piece);
        written += n;
      }"""

edit('entry/src/main/ets/service/ExportService.ets', _LOOP_OLD, _LOOP_NEW,
     'SDK 真实签名（别照抄 Node 的写法）')

# ---- 3) 调用点 1：单张手动存图 ----
edit('entry/src/main/ets/pages/Index.ets',
     "      const msg: string = ExportService.copyTo(path, uris[0], name);",
     "      const msg: string = await ExportService.copyTo(path, uris[0], name);",
     'const msg: string = await ExportService.copyTo(path, uris[0], name);')

# ---- 4) 调用点 2：批量存相册主循环 ----
edit('entry/src/main/ets/pages/Index.ets',
     "          const msg: string = ExportService.copyTo(batchPaths[i], gotUris[j], Index.baseName(batchPaths[i]));",
     "          const msg: string = await ExportService.copyTo(batchPaths[i], gotUris[j], Index.baseName(batchPaths[i]));",
     'await ExportService.copyTo(batchPaths[i]')


def main():
    plans = []
    for rel, old, new, probe in EDITS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print('MISSING %s' % rel)
            sys.exit(1)
        with io.open(path, 'r', encoding='utf-8', newline='') as f:
            src = f.read()
        if probe in src:
            print('ABORT %s: 探针已存在（已应用过）' % rel)
            sys.exit(0)
        n = src.count(old)
        if n != 1:
            print('ABORT %s: count(old)=%d 期望 1' % (rel, n))
            print(repr(old[:200]))
            sys.exit(1)
        cur = src.replace(old, new, 1)
        if probe not in cur:
            print('ABORT %s: 探针未命中' % rel)
            sys.exit(1)
        plans.append((path, rel, src, cur))

    for path, rel, src, cur in plans:
        if src == cur:
            continue
        with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(cur)
        print('OK %s' % rel)
    print('DONE')


if __name__ == '__main__':
    main()
