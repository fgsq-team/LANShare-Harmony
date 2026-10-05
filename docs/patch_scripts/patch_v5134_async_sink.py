#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.34 —— 治本：把「网页上传落盘」从**同步**改**异步**。

【为什么是这一步（数据依据）】
  5.1.33-diag 实测（2026-10-03 14:21 崩，hilog 落盘 h244 取证）：
    第1秒 fps=11.9 / 第2秒 fps=1.7 / 第3秒 fps=1.2（最长帧间隔 1019ms）
    而 hblag 全程健康（248~256ms）与 yield 只占 6.7% 时间。
  ⇒ 主线程 93.3% 时间花在循环的**同步**部分：
     `await readSome`（数据已在缓冲，几乎不等）+ `mp.feed`（解析+落盘）。
  ⇒ 数学上：让帧 993 次 / 累计 2021ms（2.03ms/次），每 24ms 让一次
     ⇒ 每 24ms 里约 22ms 是同步占用 ⇒ vsync（16.7ms）撞上占用的概率 ~92%
     ⇒ 渲染帧持续被推后 ⇒ 3 秒无帧 ⇒ THREAD_BLOCK_6S。

【改什么】
  `FileSink.append`（同步 `fileIo.writeSync`）不动（它还有 3 处调用者），
  **新增** `FileSink.appendAsync`（`await fileIo.write`），只给热路径用；
  `MultipartStream` 的 `feed`/`pump`/`write`/`finish` 改 async，
  `write` 内部改调 `appendAsync`。

【为什么这样能治本】
  `await fileIo.write` 期间**主线程是空闲的** ⇒ 渲染帧得以插入。
  这等价于一次「与 IO 绑定的天然让帧」，**而且不需要再往队列里塞 setTimeout 任务**
  （5.1.32 的教训：让帧任务本身会加剧队列拥堵）。

【单变量纪律】
  本轮**只改落盘同步性**。不动：让帧阈值（仍 24ms）、块大小（仍 256KiB）、
  `hold` 的 slice/滑窗（零拷贝留待下一轮，避免一次引入两个变量）。
  同时**保留 5.1.33-diag 的 `[FPS]` 诊断**，便于逐项对比。

幂等：哨兵 = appendAsync 方法名。
"""

import io
import os
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
SVC = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service')
NET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'net')
FS = os.path.join(SVC, 'FileStorage.ets')
MS = os.path.join(SVC, 'MultipartStream.ets')
HR = os.path.join(NET, 'HttpRouter.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = 'async appendAsync(data: Uint8Array): Promise<boolean>'


def read(p):
    return io.open(p, 'r', encoding='utf-8', newline='').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def main():
    fs = read(FS)
    ms = read(MS)
    hr = read(HR)
    app = read(APP)

    if SENTINEL in fs:
        print('ALREADY APPLIED')
        sys.exit(0)

    # ============================================================
    # ① FileStorage：新增 FileSink.appendAsync（在 append 之后、close 之前）
    # ============================================================
    fs_old = """    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `写文件失败: ${err.code} ${err.message}`);
      return false;
    }
  }

  close(): void {"""
    fs_new = """    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `写文件失败: ${err.code} ${err.message}`);
      return false;
    }
  }

  /**
   * ★★ 5.1.34：**异步**版 append —— 只给「热路径」用（网页上传的 multipart 落盘）。
   *
   * 【为什么新增而不是改 append】`append` 另有 3 处调用者
   *   （`FileTransfer` / `LanService` / `V5Transfer`），改签名会波及它们。
   *   本方法语义与 `append` **完全一致**（同 fd、同 `written` 记账），
   *   但两者**不得对同一个 fd 混用**（filePointer 与 written 必须同步推进）。
   *
   * 【为什么必须异步（这是 5.1.34 的核心）】
   *   ArkTS 是单线程：`fileIo.writeSync` 会把真正的写系统调用**压在主线程上**，
   *   写盘期间 ArkUI 拿不到帧时间。5.1.33-diag 实测证明主线程 93% 时间
   *   耗在这种同步工作上，渲染帧率被压到 1.2fps 后触发 THREAD_BLOCK_6S。
   *   改成 `await fileIo.write` 后，**写期间主线程是空的** ⇒ 渲染帧得以插入。
   *
   *   ★ 关键收益：这是一次「**与 IO 绑定的天然让帧**」——
   *     不需要额外 `setTimeout(0)` 往主线程队列里塞任务
   *     （5.1.32 的教训：让帧任务本身会加剧队列拥堵）。
   *
   * @returns true = 写成功（`written` 已推进）；false = 失败（调用方应判坏包）
   */
  async appendAsync(data: Uint8Array): Promise<boolean> {
    if (this.fd < 0) {
      return false;
    }
    if (data.length === 0) {
      return true;
    }
    try {
      // 快速路径与 append 相同：精确切片时直接复用其 buffer，省一次整块复制。
      const exact: boolean = data.byteOffset === 0 && data.byteLength === data.buffer.byteLength;
      const buf: ArrayBuffer = exact
        ? data.buffer as ArrayBuffer
        : data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;
      // ⚠️ 不传 WriteOptions.offset：SDK 里它的语义是「filePointer + offset」，
      //    复用 fd 时会双重偏移（见 V5Transfer.writeAtFd 的注释）。
      //    本 sink 全程顺序写、无并发，靠 filePointer 自然推进即可。
      const n: number = await fileIo.write(this.fd, buf);
      this.written += n;
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `写文件失败(async): ${err.code} ${err.message}`);
      return false;
    }
  }

  close(): void {"""
    assert fs.count(fs_old) == 1, 'FileStorage anchor not unique: %d' % fs.count(fs_old)
    assert fs.count('appendAsync') == 0, 'appendAsync already present in FileStorage'
    fs = fs.replace(fs_old, fs_new, 1)

    # ============================================================
    # ② MultipartStream：feed / finish / pump / write 全部改 async
    # ============================================================
    ms_old1 = """  /** 喂一片数据。可多次调用，内部状态机自行推进 */
  feed(chunk: Uint8Array): void {
    if (chunk.length === 0) {
      return;
    }
    this.fed += chunk.length;
    this.hold = MultipartStream.concat(this.hold, chunk);
    this.pump();
  }"""
    ms_new1 = """  /**
   * 喂一片数据。可多次调用，内部状态机自行推进。
   *
   * ★★ 5.1.34：改 **async**。调用点是 `await mp.feed(chunk)` 的**顺序**关系
   *   （上一次返回后才调下一次），因此**不存在重入**，状态机安全。
   *   异步化本身不是为了让它等什么，而是为了让内部的 `write`
   *   能 `await` 异步落盘 —— 见 `write` 的注释。
   */
  async feed(chunk: Uint8Array): Promise<void> {
    if (chunk.length === 0) {
      return;
    }
    this.fed += chunk.length;
    this.hold = MultipartStream.concat(this.hold, chunk);
    await this.pump();
  }"""
    assert ms.count(ms_old1) == 1, 'feed anchor not unique: %d' % ms.count(ms_old1)
    ms = ms.replace(ms_old1, ms_new1, 1)

    ms_old2 = """  /** 数据喂完后调用：收尾并返回结果 */
  finish(): MultipartFile[] {
    // 收尾时把剩下的 hold 交给状态机做最后一次判断
    this.pump();"""
    ms_new2 = """  /** 数据喂完后调用：收尾并返回结果（★ 5.1.34：改 async，理由同 `feed`） */
  async finish(): Promise<MultipartFile[]> {
    // 收尾时把剩下的 hold 交给状态机做最后一次判断
    await this.pump();"""
    assert ms.count(ms_old2) == 1, 'finish anchor not unique: %d' % ms.count(ms_old2)
    ms = ms.replace(ms_old2, ms_new2, 1)

    ms_old3 = "  private pump(): void {"
    ms_new3 = "  private async pump(): Promise<void> {"
    assert ms.count(ms_old3) == 1, 'pump anchor not unique: %d' % ms.count(ms_old3)
    ms = ms.replace(ms_old3, ms_new3, 1)

    ms_old4 = "          this.write(this.hold.slice(0, i));"
    ms_new4 = "          await this.write(this.hold.slice(0, i));"
    assert ms.count(ms_old4) == 1, 'write#1 anchor not unique: %d' % ms.count(ms_old4)
    ms = ms.replace(ms_old4, ms_new4, 1)

    ms_old5 = "            this.write(this.hold.slice(0, n));"
    ms_new5 = "            await this.write(this.hold.slice(0, n));"
    assert ms.count(ms_old5) == 1, 'write#2 anchor not unique: %d' % ms.count(ms_old5)
    ms = ms.replace(ms_old5, ms_new5, 1)

    ms_old6 = """  private write(data: Uint8Array): void {
    if (data.length === 0 || this.sink === null) {
      return;
    }
    if (this.sink.append(data)) {
      this.curSize += data.length;
    } else {
      this.fail('写文件失败（存储空间不足或路径不可写）');
    }
  }"""
    ms_new6 = """  /**
   * ★★ 5.1.34：改 **async** 并改用 `appendAsync`（异步落盘）。
   *
   * 【为什么这是本次的**核心改动**】
   *   旧实现 `this.sink.append(data)` 内部是 `fileIo.writeSync` —— **同步**。
   *   上传循环每块（256KiB）都要在这里同步等写盘完成，
   *   主线程被连续占住 ⇒ vsync 撞不上空隙 ⇒ 渲染帧率掉到 1.2fps
   *   ⇒ 3 秒无帧 ⇒ 系统判 THREAD_BLOCK_6S 并 SIGKILL（5.1.33-diag 实测）。
   *
   *   换成 `await appendAsync` 后：写系统调用交给运行时工作线程，
   *   **await 期间主线程空闲**，ArkUI 得以插入渲染帧。
   *   ⇒ 这是一次「与 IO 绑定的天然让帧」，且**不额外制造队列任务**。
   */
  private async write(data: Uint8Array): Promise<void> {
    if (data.length === 0 || this.sink === null) {
      return;
    }
    if (await this.sink.appendAsync(data)) {
      this.curSize += data.length;
    } else {
      this.fail('写文件失败（存储空间不足或路径不可写）');
    }
  }"""
    assert ms.count(ms_old6) == 1, 'write impl anchor not unique: %d' % ms.count(ms_old6)
    ms = ms.replace(ms_old6, ms_new6, 1)

    # ============================================================
    # ③ HttpRouter：4 个调用点加 await
    # ============================================================
    hr_map = [
        ("      mp.feed(pre);",     "      await mp.feed(pre);"),
        ("      mp.feed(chunk);",   "      await mp.feed(chunk);"),
        ("        mp.finish();",    "        await mp.finish();"),
        ("    const saved: MultipartFile[] = mp.finish();",
         "    const saved: MultipartFile[] = await mp.finish();"),
    ]
    for old, new in hr_map:
        assert hr.count(old) == 1, 'HttpRouter anchor %r count=%d' % (old, hr.count(old))
        assert hr.count(new) == 0, 'HttpRouter new %r already present' % new
        hr = hr.replace(old, new, 1)

    # ============================================================
    # ④ 版本号
    # ============================================================
    assert app.count('"versionCode": 5000133') == 1, 'versionCode anchor'
    assert app.count('"versionName": "5.1.33-diag"') == 1, 'versionName anchor'
    app = app.replace('"versionCode": 5000133', '"versionCode": 5000134', 1)
    app = app.replace('"versionName": "5.1.33-diag"', '"versionName": "5.1.34"', 1)

    # ---------- 统一落盘 ----------
    write(FS, fs)
    write(MS, ms)
    write(HR, hr)
    write(APP, app)

    print('--- 复核 ---')
    f2 = read(FS)
    m2 = read(MS)
    h2 = read(HR)
    print('appendAsync (FS)      :', f2.count('appendAsync'))
    print('async feed (MS)       :', m2.count('async feed('))
    print('async finish (MS)     :', m2.count('async finish('))
    print('async pump (MS)       :', m2.count('async pump('))
    print('async write (MS)      :', m2.count('async write('))
    print('await this.write (MS) :', m2.count('await this.write('))
    print('await mp.feed (HR)    :', h2.count('await mp.feed('))
    print('await mp.finish (HR)  :', h2.count('await mp.finish('))
    print('CRLF FS/MS/HR         :', f2.count('\r\n'), m2.count('\r\n'), h2.count('\r\n'))
    print('OK 5.1.34 applied')


if __name__ == '__main__':
    main()
