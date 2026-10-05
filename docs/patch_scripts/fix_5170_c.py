#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.70 C：把相册资产探测从「切 tab」搬到「后台静默」（幂等）

vivi 2026-10-05 要求：
> 「文件页检测是否删除的逻辑改一下，之前是点击消息页才检测，现在改成后台静默检测」

## 为什么必须搬
原来挂在「切到消息 tab」（`index === 1`）⇒ **426 张时切页必卡**
（`probeAlbumOnEnterChat` 会对 414 条 uri 逐个 `statSync`/`openSync`/`readSync`）。
5.1.66 C1 只在循环内每 20 张让一帧 —— 那能缓解**帧率**，
但**切页那一帧本身的等待**还在（用户看到的是「点进去要等一下才出内容」）。

## 改法
`aboutToAppear` 里，**等 `loadAlbumIndex` 完成后**就启动探测：
```ts
this.service.loadAlbumIndex(ctx).then(() => {
  this.albumIndex = this.service.albumSnapshot();
  // ★ 5.1.70：后台静默探测 —— 不再挂在「切 tab」上
  this.scheduleBackgroundAlbumProbe();
});
```
⇒ 与 tab 切换**完全解耦**：用户什么时候切页都不再触发探测。
⚠️ 放在 `loadAlbumIndex(...).then(...)` **之内**是必须的 ——
   索引没加载完就探会全部判「已删」（这正是注释里记的历史坑）。

「已删除」的处置**完全不变**（清 uri + 更新角标 + 一条汇总日志）。

## 同时移除切页那次调用
`index === 1` 分支里的 `this.probeAlbumOnEnterChat();` 删掉，
否则「切页 + 后台」两路并发 ⇒ 探两遍（`albumProbeRunning` 闸门会挡掉，
但留着是隐患）。

★ 顺带把 `probeAlbumOnEnterChat` 的名字保留（内部方法名不改，改名要动 3 处），
  只在注释里说明它现在是「后台静默」。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = '5.1.70 C'
REL = 'entry/src/main/ets/pages/Index.ets'

EDITS = []


def edit(old, new, tag):
    EDITS.append((old, new, tag))


# ---- C1 挂在 aboutToAppear 的 loadAlbumIndex 之后 ----
edit(
    """    this.service.loadAlbumIndex(ctx).then(() => {
      this.albumIndex = this.service.albumSnapshot();
    });""",
    """    this.service.loadAlbumIndex(ctx).then(() => {
      this.albumIndex = this.service.albumSnapshot();
      // ★★ 5.1.70 C：**后台静默**探测「相册里的图还在不在」。
      //   原来挂在「切到消息 tab」（index === 1）⇒ 426 张时**切页必卡**
      //   （`probeAlbumOnEnterChat` 对 414 条 uri 逐个 statSync/openSync/readSync；
      //    5.1.66 C1 的「每 20 张让一帧」只缓解帧率，切页那一帧的等待仍在）。
      //   ⇒ 挂到页面出现时跑，与 tab 切换**完全解耦**。
      //   ⚠️ 必须在 `loadAlbumIndex` 完成**之后**：索引没加载就探会全部判「已删」
      //   （历史坑，见 probeAlbumOnEnterChat 的注释）。
      this.scheduleBackgroundAlbumProbe();
    });""",
    'C1 aboutToAppear 挂载')

# ---- C2 移除切页那次调用 ----
edit(
    """            // ★ 5.0.75（vivi 20:21 新功能）：切到消息 tab 时**主动**全量探一次
            //   「相册里的图还在不在」—— 用户可能在系统相册里删了图，
            //   而此前**只有点击气泡时**才被动探测（`onFileBubbleClick`），
            //   用户看不到任何提示，只有点它才弹 toast。
            this.probeAlbumOnEnterChat();""",
    """            // ★★ 5.1.70 C：这里**不再**做相册资产全量探测。
            //   原来 5.0.75 是「切到消息 tab 才探」⇒ 426 张时切页必卡。
            //   现已改为**后台静默**（`aboutToAppear` → `loadAlbumIndex` 完成后
            //   `scheduleBackgroundAlbumProbe()`），与 tab 切换完全解耦。
            //   ⚠️ 效果不变：用户删了相册里的图，气泡角标照样更新
            //   （处置逻辑在 `probeAlbumOnEnterChat` 里没动过）。""",
    'C2 移除切页调用')


def main():
    path = os.path.join(ROOT, REL)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()

    if PROBE in src:
        print('SKIP 已应用')
        return

    for old, new, tag in EDITS:
        if src.count(old) != 1:
            print('ABORT %s count=%d' % (tag, src.count(old)))
            print(repr(old[:160]))
            sys.exit(1)
        src = src.replace(old, new, 1)

    # 语义自检
    if 'this.scheduleBackgroundAlbumProbe();' not in src:
        print('ABORT: 后台探测调用未写入')
        sys.exit(1)
    # 切页那次必须已移除。
    # ⚠️ `scheduleBackgroundAlbumProbe()` 的**方法体内部**本来就有一处
    #   `this.probeAlbumOnEnterChat();`（那是它转调真身，**该留**），
    #   所以判据是「**恰好剩 1 处**」，不是「一处都不剩」。
    left = src.count('this.probeAlbumOnEnterChat();')
    if left != 1:
        print('ABORT: 切页那次未移除（当前 %d 处，应恰好剩 1 处=方法体转调）' % left)
        sys.exit(1)
    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)

    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('OK %s (%d 处)' % (REL, len(EDITS)))
    print('自检: 后台探测已挂 ✓  切页调用已移除 ✓')


if __name__ == '__main__':
    main()
