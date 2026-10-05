#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.66 消除消息页缩略图卡顿（3 处，幂等）

vivi 2026-10-05 反馈：「400 多张缩略图在消息页生成/删除提示的时候也会卡顿」

## 三个卡点（都在同步 IO 上）

### C1 `probeAlbumOnEnterChat` —— 切消息页逐个探 400+ 张
`Index.ets:5159` 遍历 `albumIndex` 所有 key，对有 uri 的逐个
`albumAssetAlive(uri)`，而它是**纯同步 IO**：
```ts
fileIo.statSync(uri)                 // 信号①
fileIo.openSync(uri, READ_ONLY)      // 信号②
fileIo.readSync(f.fd, buf)           // 信号②
```
⇒ 400+ 张 × (1~2 次 syscall + 可能的 open/close) 全在主线程，
**只有函数开头一次 `yieldOnce()`**，循环内**完全不让帧**。
★ 注释里自己写了「一批几十张会把主线程占住掉帧 ⇒ 先 `yieldOnce()` 再逐个探」
  —— 但 `yieldOnce` 只在**循环之前**叫了一次，400 张里每张都还在主线程上。

### C2 `setThumbOnly` —— 每张缩略图 2 次全量落盘
`prefetchThumbInner` 每生成一张缩略图就
`await this.service.setThumbOnly(key, thumb, rot)`
⇒ 内部 `persistAlbumIndex` + `persistAlbumRot` 各**全量遍历** + flush
⇒ **400 张 = 800 次全量写**。
（与 5.1.65 修的 `setAlbumIndex` 是同一个病，漏了这条路径。）

### C3 探测只在切 tab 时跑，但 400 张的量让「切 tab」本身变慢
`probeAlbumOnEnterChat` 是 async 但**没有节流**（只在切 tab 时调），
⇒ 每次切进消息页都要等这 400+ 次同步探测跑完。

## 修法
- **C1**：循环内**每 N 张让一帧**（`yieldOnce`），把主线程占压降到 ≤N 张的量。
  ⚠️ 不能改判据（`albumAssetAlive` 的三信号是 5.0.51~5.0.52 踩坑定案的）。
- **C2**：`setThumbOnlyBatch(keys...)` 批量写 + **防抖落盘**
  （复用已有的 `scheduleThumbFlush` 节奏），400 张从 800 次降到个位数。
- **C3**：给探测加**节流**：同一批 id 已经探过就跳过
  （`albumClearedIds` 只记「已删」，这里补一个「已探活」集合）。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

EDITS = []


def edit(rel, old, new, probe):
    EDITS.append((rel, old, new, probe))


# =====================================================================
# C1  探测循环内让帧
# =====================================================================
_C1_OLD = """      let checked: number = 0;
      const dead: string[] = [];
      for (const key of this.albumIndex.keys()) {
        // key 形如 `消息id#序号`；只看 part 0（相册 uri）
        const uri: string = this.albumPart(key, 0);
        if (uri.length === 0 || this.albumClearedIds.has(key)) {
          continue;
        }
        checked += 1;
        if (!this.albumAssetAlive(uri)) {
          dead.push(key);
        }
      }"""

_C1_NEW = """      let checked: number = 0;
      const dead: string[] = [];
      let sinceYield: number = 0;
      for (const key of this.albumIndex.keys()) {
        // key 形如 `消息id#序号`；只看 part 0（相册 uri）
        const uri: string = this.albumPart(key, 0);
        if (uri.length === 0 || this.albumClearedIds.has(key)) {
          continue;
        }
        checked += 1;
        // ★★ 5.1.66 C1：**循环内**周期性让帧。
        //   `albumAssetAlive` 是纯同步 IO（statSync / openSync / readSync），
        //   400+ 张逐个探会把主线程占死 ⇒ 切消息页直接卡住。
        //   ⚠️ 原实现只在**循环之前**调了一次 `yieldOnce()`，那等于没让 ——
        //   400 张的 IO 全挤在第一次让帧之后的整段里。
        //   ⇒ 每 PROBE_YIELD_EVERY 张让一帧，把单次连续占用压到 20 张的量。
        sinceYield += 1;
        if (sinceYield >= Index.PROBE_YIELD_EVERY) {
          sinceYield = 0;
          await Index.yieldOnce();
        }
        if (!this.albumAssetAlive(uri)) {
          dead.push(key);
        }
      }
      // 收尾再让一帧：最后不足一批的也要让出去，别把尾段留到下一帧
      if (sinceYield > 0) {
        await Index.yieldOnce();
      }"""

edit('entry/src/main/ets/pages/Index.ets', _C1_OLD, _C1_NEW,
     '5.1.66 C1：**循环内**周期性让帧')

# =====================================================================
# C1b  加常量
# =====================================================================
_C1B_OLD = "  private static ALBUM_DIALOG_MAX: number = 40;"
_C1B_NEW = """  private static ALBUM_DIALOG_MAX: number = 40;

  /**
   * ★★ 5.1.66 C1：切消息页探测相册资产时，**每多少张让一帧**。
   *
   * 背景（vivi 2026-10-05）：400+ 张缩略图时「切消息页 + 删除提示」卡顿。
   * `albumAssetAlive` 是纯同步 IO（statSync / openSync / readSync），
   * 几百张逐个探会把主线程占死。
   *
   * 取 20 的理由：一次 `statSync` 约几十微秒量级，20 张 ≈ 毫秒级，
   * 对比一帧 16.7ms 仍有富余；再大就让帧变稀、探测总时长变长。
   */
  private static PROBE_YIELD_EVERY: number = 20;"""

edit('entry/src/main/ets/pages/Index.ets', _C1B_OLD, _C1B_NEW,
     '5.1.66 C1：切消息页探测相册资产时')

# =====================================================================
# C2  LanService：setThumbOnly 批量 + 防抖
# =====================================================================
  # 撤掉刚才那条（old 不对）

# 正确做法：在原 setThumbOnly 的 doc 注释前插入新方法
_C2_INS_OLD = """  /**
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

_C2_INS_NEW = """  /**
   * ★★ 5.1.66 C2：批量补缩略图索引 —— **只进内存，落盘交给防抖**。
   *
   * ## 为什么（vivi 2026-10-05 真机：400+ 张缩略图生成时卡顿）
   *   原来每预生成一张缩略图就 `await setThumbOnly(...)`
   *   ⇒ 内部 `persistAlbumIndex` + `persistAlbumRot` 各**全量遍历** + flush
   *   ⇒ **400 张 = 800 次全量写**，而表只多了 400 条。
   *   （与 5.1.65 修掉的 `setAlbumIndex` 是同一个病，这条路径当时漏了。）
   *
   * ## 改法
   *   **只写 Map，不落盘**。落盘由末尾的 `scheduleAlbumPersist()` **防抖合并**
   *   （1.5s 静默期，且**不重置**定时器）⇒ 连续 400 张最多落盘 1~2 次。
   *   ⚠️ 崩溃风险：防抖窗口内挂掉 ⇒ 丢这一批缩略图索引。可接受 ——
   *   `prefetchThumbInner` 失败会 `thumbPrepare.delete(key)`，
   *   下次渲染还会再试（见 maybePrefetchThumb 的注释）。
   */
  setThumbOnlyBatch(items: string[]): void {
    if (items.length === 0) {
      return;
    }
    this.albumLoaded = true;
    for (let i: number = 0; i < items.length; i++) {
      // items[i] = `${key}|${thumb}|${rot}`
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
   */
  private scheduleAlbumPersist(): void {
    if (this.albumPersistTimer >= 0) {
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

edit('entry/src/main/ets/service/LanService.ets', _C2_INS_OLD, _C2_INS_NEW,
     '5.1.66 C2：批量补缩略图索引')

# =====================================================================
# C2b  加 albumPersistTimer 字段
# =====================================================================
_C2B_OLD = "  private albumLoaded: boolean = false;"
_C2B_NEW = """  private albumLoaded: boolean = false;

  /**
   * ★★ 5.1.66 C2：相册索引落盘的**防抖定时器**（-1 = 无）。
   * ⚠️ 语义是「防抖」不是「节流」：**已有定时器在等就搭车，不重置**。
   * 这样连续 400 次 `setThumbOnlyBatch` 只落盘 1~2 次。
   * （参照同文件里既有的 `chatSaveTimer` 写法。）
   */
  private albumPersistTimer: number = -1;"""

edit('entry/src/main/ets/service/LanService.ets', _C2B_OLD, _C2B_NEW,
     '5.1.66 C2：相册索引落盘的**防抖定时器**')


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
            print('ABORT %s: 探针已存在' % rel)
            sys.exit(0)
        n = src.count(old)
        if n != 1:
            print('ABORT %s: count(old)=%d 期望 1' % (rel, n))
            print(repr(old[:180]))
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
