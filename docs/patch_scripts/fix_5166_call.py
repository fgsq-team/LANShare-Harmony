#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.66 C2b：缩略图预生成改走批量落盘（幂等，两处）

C2a（前一个脚本）只加了 `LanService.setThumbOnlyBatch`，
**调用点还在用单条 `setThumbOnly`** ⇒ 每张仍全量落盘 ⇒ 等于没修。

本脚本两处：
  ① `prefetchThumbInner`：`await setThumbOnly(...)` → 塞进 `thumbIndexBatch` 数组
  ② `flushThumbBatch`：在**已有的**批量换 `albumIndex` 引用时，
     顺带 `setThumbOnlyBatch(this.thumbIndexBatch)` 一次落盘
     ⇒ **零新增定时器**（`scheduleThumbFlush` 的防抖节奏直接复用）
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = '5.1.66 C2b'
REL = 'entry/src/main/ets/pages/Index.ets'


def main():
    path = os.path.join(ROOT, REL)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()

    if PROBE in src:
        print('SKIP 已应用')
        return

    edits = []

    # ---- ① 调用点 ----
    old1 = """      const rot: number = this.service.rotOf(thumb) ?? 0;
      // ⚠️ 只补缩略图，**绝不碰相册 URI** —— 用户还没点确认框（见 setThumbOnly）
      await this.service.setThumbOnly(key, thumb, rot);"""
    new1 = """      const rot: number = this.service.rotOf(thumb) ?? 0;
      // ⚠️ 只补缩略图，**绝不碰相册 URI** —— 用户还没点确认框（见 setThumbOnlyBatch）
      // ★★ 5.1.66 C2b：原来这里是 `await setThumbOnly(...)` —— 每张都
      //   persistAlbumIndex + persistAlbumRot 各全量遍历 + flush
      //   ⇒ **400 张 = 800 次全量写** ⇒ 缩略图生成时卡顿（vivi 2026-10-05 实测）。
      //   ⇒ 改成**只进数组**（纯内存），落盘交给 `flushThumbBatch()` 一起做。
      this.thumbIndexBatch.push(`${key}|${thumb}|${rot}`);"""
    if src.count(old1) != 1:
        print('ABORT ① count=%d' % src.count(old1))
        sys.exit(1)
    edits.append((old1, new1))

    # ---- ② flushThumbBatch 里顺带落盘 ----
    old2 = """    const n: number = this.thumbBatch.size;
    this.thumbBatch.clear();
    this.albumIndex = this.service.albumSnapshot();
    Log.i(TAG, `缩略图批量提交：${n} 张，显示源一次性恒定（避免逐张重渲染）`);"""
    new2 = """    const n: number = this.thumbBatch.size;
    this.thumbBatch.clear();
    // ★★ 5.1.66 C2b：把这一批缩略图索引**一次**落盘。
    //   放在这里是因为 `flushThumbBatch` 本身已经是「批量 + 防抖」节奏
    //   （`scheduleThumbFlush` 合并），**零新增定时器**。
    this.service.setThumbOnlyBatch(this.thumbIndexBatch);
    this.thumbIndexBatch = [];
    this.albumIndex = this.service.albumSnapshot();
    Log.i(TAG, `缩略图批量提交：${n} 张，显示源一次性恒定（避免逐张重渲染）`);"""
    if src.count(old2) != 1:
        print('ABORT ② count=%d' % src.count(old2))
        sys.exit(1)
    edits.append((old2, new2))

    # ---- ③ 加字段 ----
    old3 = "  private thumbBatchTimer: number = -1;"
    new3 = """  private thumbBatchTimer: number = -1;
  /**
   * ★★ 5.1.66 C2b：待落盘的缩略图索引，格式 `${key}|${thumb}|${rot}`。
   * 只进数组，由 `flushThumbBatch()` 一次 `setThumbOnlyBatch` 落盘
   * ⇒ 400 张从 800 次全量写降到 1 次。
   */
  private thumbIndexBatch: string[] = [];"""
    if src.count(old3) != 1:
        print('ABORT ③ count=%d' % src.count(old3))
        sys.exit(1)
    edits.append((old3, new3))

    for old, new in edits:
        src = src.replace(old, new, 1)

    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)

    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('OK %s (C2b 三处)' % REL)


if __name__ == '__main__':
    main()
