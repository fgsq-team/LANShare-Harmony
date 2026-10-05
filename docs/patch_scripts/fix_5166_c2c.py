#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.66 C2c：补上漏掉的 setThumbOnlyBatch 方法体 + scheduleAlbumPersist（幂等）

## 为什么单独一个脚本
前一个脚本（fix_5166_thumb.py）里 C2 与 C2b 是**同一个文件的两条 edit**，
而它每条 edit 都自己重读文件 ⇒ 第二条读到的已是改过的内容
⇒ 「先全部校验再统一落盘」没做到 ⇒ C2 那条被后续 abort 连带丢掉。
（就是 MEMORY 里第 37 条那个教训，本轮又犯了一次。）

本脚本只做一件事：在 `setThumbOnly` 的 doc 注释前插入
`setThumbOnlyBatch` + `scheduleAlbumPersist` 两个方法。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = 'setThumbOnlyBatch(items: string[]): void {'
REL = 'entry/src/main/ets/service/LanService.ets'

OLD = """  /**
   * ★ 5.0.61：**只**补一条「缩略图缓存路径」，**绝不碰已有的相册 URI**。
   *
   * 用途：接收 / 渲染缩略图时**预生成**缓存小图，好让气泡的显示源从一开始就恒定
   * 指向 `album_thumbs/<key>.jpg` —— 之后存相册、删沙箱副本时源不变、ForEach key
   * 不变，缩略图**不会再整屏重刷一遍**。
   *
   * ⚠️ 与 `setAlbumIndex` 的区别只有一条，但极其关键：这条路径上**用户还没点
   *    相册确认框**，uri 必须是空的。如果直接把已有行覆盖成 `|thumb`，就把
   *    「点图跳相册」的能力冲掉了（`clearAlbumUri` 那种失效场景重演）。
   */
  async setThumbOnly(id: string, thumb: string, rot: number = 0): Promise<void> {"""

NEW = """  /**
   * ★★ 5.1.66 C2：批量补缩略图索引 —— **只进内存，落盘交给防抖**。
   *
   * ## 为什么（vivi 2026-10-05 真机：400+ 张缩略图生成时卡顿）
   *   原来每预生成一张缩略图就 `await setThumbOnly(...)`
   *   ⇒ 内部 `persistAlbumIndex` + `persistAlbumRot` 各**全量遍历** + flush
   *   ⇒ **400 张 = 800 次全量写**，而表只多了 400 条。
   *   （与 5.1.65 修掉的 `setAlbumIndex` 是同一个病，那次只修了存相册那条路径。）
   *
   * ## 改法
   *   **只写 Map，不落盘**。落盘由 `scheduleAlbumPersist()` **防抖合并**
   *   （1.5s 静默期，且**不重置**定时器）⇒ 连续 400 张最多落盘 1~2 次。
   *   ⚠️ 崩溃风险：防抖窗口内挂掉 ⇒ 丢这一批缩略图索引。可接受 ——
   *   `prefetchThumbInner` 失败会 `thumbPrepare.delete(key)`，
   *   下次渲染还会再试（见 maybePrefetchThumb 的注释）。
   *
   * @param items 每项格式 `${key}|${thumb}|${rot}`
   */
  setThumbOnlyBatch(items: string[]): void {
    if (items.length === 0) {
      return;
    }
    this.albumLoaded = true;
    for (let i: number = 0; i < items.length; i++) {
      const parts: string[] = items[i].split('|');
      if (parts.length >= 3) {
        const cur: string | undefined = this.albumMap.get(parts[0]);
        const segs: string[] = cur === undefined ? [] : cur.split('|');
        const curUri: string = segs.length > 0 ? segs[0] : '';
        // ⚠️ 绝不碰已有相册 URI（这是 setThumbOnly 的核心不变量）
        this.albumMap.set(parts[0], `${curUri}|${parts[1]}`);
        this.albumRotMap.set(parts[1], Number(parts[2]));
      }
    }
    this.scheduleAlbumPersist();
  }

  /**
   * 5.1.66 C2：相册索引落盘的**防抖合并**。
   * 已有定时器在等就直接搭车（**不重置**）⇒ 连续 N 次调用只落盘 1 次。
   * ⚠️ 与 `scheduleChatSave`（5.x）同款写法，参照它。
   */
  private scheduleAlbumPersist(): void {
    if (this.albumPersistTimer !== -1) {
      return;
    }
    this.albumPersistTimer = setTimeout(() => {
      this.albumPersistTimer = -1;
      this.persistAlbumIndex();
      this.persistAlbumRot();
    }, 1500);
  }

  /**
   * ★ 5.0.61：**只**补一条「缩略图缓存路径」，**绝不碰已有的相册 URI**。
   *
   * 用途：接收 / 渲染缩略图时**预生成**缓存小图，好让气泡的显示源从一开始就恒定
   * 指向 `album_thumbs/<key>.jpg` —— 之后存相册、删沙箱副本时源不变、ForEach key
   * 不变，缩略图**不会再整屏重刷一遍**。
   *
   * ⚠️ 与 `setAlbumIndex` 的区别只有一条，但极其关键：这条路径上**用户还没点
   *    相册确认框**，uri 必须是空的。如果直接把已有行覆盖成 `|thumb`，就把
   *    「点图跳相册」的能力冲掉了（`clearAlbumUri` 那种失效场景重演）。
   *
   * ⚠️ 5.1.66 C2：**单条**版保留「立即落盘」原语义；
   *   大批量场景（预生成缩略图）请用 `setThumbOnlyBatch`。
   */
  async setThumbOnly(id: string, thumb: string, rot: number = 0): Promise<void> {"""


def main():
    path = os.path.join(ROOT, REL)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()

    if PROBE in src:
        print('SKIP 已应用')
        return

    if src.count(OLD) != 1:
        print('ABORT count=%d' % src.count(OLD))
        sys.exit(1)
    src = src.replace(OLD, NEW, 1)
    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('OK %s' % REL)


if __name__ == '__main__':
    main()
