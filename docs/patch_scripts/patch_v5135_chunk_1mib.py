#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.35 —— 回退 5.1.34 的异步落盘（数据证伪），改用**块大小对齐对照组**。

【5.1.34 为什么被证伪（实测数据）】
  同一台机、同一个应用，两版的 `[HB]`（事件循环被推迟）告警：
    5.1.33-diag（同步写）：最差  999ms
    5.1.34    （异步写）：最差 6325ms  ← 更糟 6 倍！
                          且单调递增：603→620→701→1605→2477→2996→5213→6325
  吞吐也从 16.5 MB/s 掉到 2.6 MB/s（慢 6 倍）。
  ⇒ 异步 IO 换来的不是"让出主线程"，而是把同步占用换成了**更长的连续占用**
    （每块多一次 `await`，continuation 是 microtask，**microtask 优先于宏任务**，
     vsync/定时器更难插入；且 IO 完成回调会批量回到主线程）。

  ⚠️ 同时修正一条此前记录错误的判据：**不能只看 `[UP]` 里的 `hblag=` 瞬时值**
     （它只在打点那一刻取值，会漏掉最差时刻）。**`[HB]` 告警才是主线程被占的可靠证据。**

【本版改什么（相对 5.1.33-diag 基线，单变量）】
  只改 `UPLOAD_CHUNK`：256 KiB → **1 MiB − 12**（对齐 `V5Transfer.CHUNK`）。

【依据：对照实验】
  同一个「收 1.5GB 大文件」的场景，两条路径结果相反：
    `V5Transfer`（私有协议，16 并发分片）：块 **1 MiB − 12** ⇒ 成功，32 MB/s，0 条 vsync 超时
    `HttpRouter`（网页上传，单连接）      ：块 **256 KiB**    ⇒ 崩，THREAD_BLOCK_6S
  ⇒ 块大小是本项目里唯一被实证过的显著差异。
  ⇒ 让帧预算反而不重要（V5Transfer 用 12ms、HttpRouter 用 24ms，前者更密却更稳）。

【预期收益】
  每 16 MiB 的循环轮数：64 → 16
  ⇒ `readSome` 的 await 次数、`hold` 的 concat/slice 次数、临时数组分配次数
    全部降到 1/4 ⇒ 缓解「任务与分配按块累积」导致的队列积压/主线程长占用。

【刻意未改】
  `UPLOAD_YIELD_MS` 仍 24ms；让帧仍 `setTimeout(resolve, 0)`；
  `hold` 仍用 slice（零拷贝留待本轮结果出来后再决定）。**保持单变量。**

幂等：哨兵 = 版本号 5.1.35。
"""

import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
SVC = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service')
NET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'net')
BK = os.path.join(ROOT, 'docs', 'backups')
HR = os.path.join(NET, 'HttpRouter.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '"versionName": "5.1.35"'


def read(p):
    return io.open(p, 'r', encoding='utf-8', newline='').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def main():
    app = read(APP)
    if SENTINEL in app:
        print('ALREADY APPLIED')
        sys.exit(0)

    # ---------- ① 回退 5.1.34 的异步化（从 v5134pre 备份恢复） ----------
    pairs = [
        (os.path.join(BK, 'MultipartStream.ets.v5134pre'), os.path.join(SVC, 'MultipartStream.ets')),
        (os.path.join(BK, 'FileStorage.ets.v5134pre'), os.path.join(SVC, 'FileStorage.ets')),
        (os.path.join(BK, 'HttpRouter.ets.v5134pre'), HR),
    ]
    for src, dst in pairs:
        assert os.path.isfile(src), 'backup missing: %s' % src
        body = read(src)
        assert 'appendAsync' not in body, 'backup %s unexpectedly contains appendAsync' % src
        assert 'async feed(' not in body, 'backup %s unexpectedly contains async feed' % src
        write(dst, body)
        print('  reverted:', os.path.basename(dst))

    # 复核：异步化痕迹必须清零
    for _, dst in pairs:
        b = read(dst)
        assert 'appendAsync' not in b, 'appendAsync still in %s' % dst
        assert 'async pump(' not in b, 'async pump still in %s' % dst
        assert 'await mp.feed(' not in b, 'await mp.feed still in %s' % dst
    print('  revert verified: 0 remaining async traces')

    # ---------- ② 改块大小（本版唯一的实质改动） ----------
    hr = read(HR)
    old = 'const UPLOAD_CHUNK: number = 256 * 1024;'
    new = '''/**
 * ★★ 5.1.35：块大小 256 KiB → **1 MiB − 12**（对齐 `V5Transfer.CHUNK`）。
 *
 * 【依据：对照实验（同一个「收大文件」场景，结果相反）】
 *    `V5Transfer`（私有协议，16 并发分片）：块 **1 MiB − 12** ⇒ 成功（32 MB/s，0 条 vsync 超时）
 *    `HttpRouter`（网页上传，单连接）      ：块 **256 KiB**    ⇒ 崩（THREAD_BLOCK_6S）
 *  唯一的显著差异就是块大小 —— 让帧预算反而不重要
 *  （V5Transfer 用 12ms、本文件用 24ms，前者更密却更稳）。
 *
 * 【为什么块大小会决定生死】
 *  对端发得比我们处理得快时，`readSome` 会**立刻**返回 ⇒ `await` 立即 resolve
 *  ⇒ 这是 **microtask**，**优先于宏任务（vsync / 定时器）**
 *  ⇒ 单连接 + 数据充足时，主线程会被这条 microtask 链几乎独占，
 *    渲染帧与让帧的定时器都排不进去（实测 `[HB]` 事件循环被推迟到 999ms~6325ms）。
 *  块变大 ⇒ **每单位数据的 await / 分配 / 循环轮数按比例减少**：
 *    每 16 MiB 的轮数 64 → 16，`hold` 的 concat/slice 与临时数组分配同步降到 1/4。
 *
 * ⚠️ 副作用：单块的同步工作量涨到 4 倍（`indexOfSeq` 扫描 + slice 拷贝），
 *    单次主线程占用会变长。总占用不变、次数减 4 倍 —— 孰优待本轮实测裁决。
 */
const UPLOAD_CHUNK: number = 1024 * 1024 - 12;'''
    assert hr.count(old) == 1, 'UPLOAD_CHUNK anchor %d' % hr.count(old)
    assert hr.count(new) == 0, 'new UPLOAD_CHUNK already present'
    hr = hr.replace(old, new, 1)
    write(HR, hr)

    # ---------- ③ 版本号 ----------
    assert app.count('"versionCode": 5000134') == 1, 'versionCode anchor'
    assert app.count('"versionName": "5.1.34"') == 1, 'versionName anchor'
    app = app.replace('"versionCode": 5000134', '"versionCode": 5000135', 1)
    app = app.replace('"versionName": "5.1.34"', '"versionName": "5.1.35"', 1)
    write(APP, app)

    # ---------- 复核 ----------
    h2 = read(HR)
    m2 = read(os.path.join(SVC, 'MultipartStream.ets'))
    f2 = read(os.path.join(SVC, 'FileStorage.ets'))
    print('--- 复核 ---')
    print('UPLOAD_CHUNK 1MiB   :', h2.count('const UPLOAD_CHUNK: number = 1024 * 1024 - 12;'))
    print('UPLOAD_CHUNK 256KiB :', h2.count('const UPLOAD_CHUNK: number = 256 * 1024;'))
    print('[FPS] diag kept     :', h2.count('startFrameDiag'))
    print('async leftover MS/FS:', m2.count('async '), f2.count('appendAsync'))
    print('CRLF HR/MS/FS       :', h2.count('\r\n'), m2.count('\r\n'), f2.count('\r\n'))
    print('OK 5.1.35 applied')


if __name__ == '__main__':
    main()
