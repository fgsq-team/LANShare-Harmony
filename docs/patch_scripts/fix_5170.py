#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.70：① 存相册三段计时日志  ② 相册资产探测改「后台静默」（幂等）

## 背景（vivi 2026-10-05）
- 「存相册卡」的方案还没定 ⇒ **先量**：`确认框返回 → 完成` = 3.5 秒 / 40 张 / 65.7MB
  （约 19MB/s）。要拆成「拷贝 / 解码 / 删沙箱」三段，才能判断该砍哪一段。
- 另：「文件页检测相册里删没删」目前是**切到消息 tab 时**才跑
  （`probeAlbumOnEnterChat`，7815 行）⇒ 426 张时切页必卡。
  ⇒ 改成**后台静默**：进消息页就开始探，**不等用户切页**，且不阻塞任何 UI。

## 改动清单
### ① Index.ts：存相册主循环加三段计时
每批打一条汇总：`copyTo` 累计 / `cacheThumb` 累计 / 删沙箱累计。
⚠️ 用 `Date.now()` 累加，**不逐张打日志**（否则又制造 40 次 emit ⇒ 全量重建）。
  ⇒ 40 张只有 **1 条** 日志，与 5.1.69 的日志节流方向一致。

### ② Index.ets：探测改后台静默
- 原来：切到消息 tab（`index === 1`）才 `probeAlbumOnEnterChat()`
- 改为：**启动后就后台跑**，不挂在 tab 切换上；
  「已删除」的处理**照旧**（清 uri + 更新角标 + 一条汇总日志），
  差别只在**不再占用切页那一帧**。
- 加 `albumProbeRunning` 闸门，避免与用户点击气泡触发的探测重入。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = '5.1.70'
REL = 'entry/src/main/ets/pages/Index.ets'

EDITS = []


def edit0(old, new, tag):
    EDITS.append((old, new, tag))


# ---- 探测闸门字段 ----
edit0(
    "  private albumClearedIds: Set<string> = new Set<string>();",
    """  private albumClearedIds: Set<string> = new Set<string>();
  /**
   * ★★ 5.1.70：相册资产探测的**重入闸门**。
   * 切页（已停用）与 （后台静默）两路都可能触发，
   * 426 张时并发 = 白干一遍全量探活。
   */
  private albumProbeRunning: boolean = false;""",
    '②0 闸门字段')


def edit(old, new, tag):
    EDITS.append((old, new, tag))


# ---- ① 三段计时：循环前声明三个累加器 ----
edit(
    """      let ok: number = 0;
      const missed: string[] = [];
      // ★★ 5.1.65：整批收集，循环结束后**一次性**落盘 + 一次性删沙箱。
      //   （`idxBatch` / `toDelete` 已声明在 try 之前，见本方法开头。）""",
    """      let ok: number = 0;
      const missed: string[] = [];
      // ★★ 5.1.70：**三段计时**（vivi 要据「确认框返回→完成 = 3.5s / 40 张 /
      //   65.7MB ≈ 19MB/s」判断该砍哪一段：拷贝 / 解码 / 删沙箱）。
      //   ⚠️ 只**累加**、循环结束后打**一条**汇总 ——
      //   逐张打就是 40 次 logAuto ⇒ 40 次 emit ⇒ 40 次全量重建
      //   （那正是 5.1.69 B 刚治好的病，别在这里复发）。
      let tCopy: number = 0;
      let tThumb: number = 0;
      // ★★ 5.1.65：整批收集，循环结束后**一次性**落盘 + 一次性删沙箱。
      //   （`idxBatch` / `toDelete` 已声明在 try 之前，见本方法开头。）""",
    '①a 计时累加器')

# ---- ① copyTo 计时 ----
edit(
    """        try {
          const msg: string = await ExportService.copyTo(batchPaths[i], gotUris[j], Index.baseName(batchPaths[i]));
          if (!msg.startsWith('已保存')) {""",
    """        try {
          // ★ 5.1.70：分段计时
          const t0: number = Date.now();
          const msg: string = await ExportService.copyTo(batchPaths[i], gotUris[j], Index.baseName(batchPaths[i]));
          tCopy += Date.now() - t0;
          if (!msg.startsWith('已保存')) {""",
    '①b copyTo 计时')

# ---- ① cacheThumb 计时 ----
edit(
    """          const thumb: string = await this.cacheThumb(ctx, batchPaths[i], batchKeys[i]);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          // ★★ 5.1.67 关键修正：这里**只进数组**。""",
    """          // ★ 5.1.70：分段计时
          const t1: number = Date.now();
          const thumb: string = await this.cacheThumb(ctx, batchPaths[i], batchKeys[i]);
          tThumb += Date.now() - t1;
          const rot: number = this.service.rotOf(thumb) ?? 0;
          // ★★ 5.1.67 关键修正：这里**只进数组**。""",
    '①c cacheThumb 计时')

# ---- ① 删沙箱计时 + 汇总日志 ----
edit(
    """      await this.service.setAlbumIndexBatch(idxBatch);
      for (let i: number = 0; i < toDelete.length; i++) {
        const derr: string | null =
          ExportService.deleteFile(this.service.receiveRoot, toDelete[i]);
        if (derr !== null) {
          Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${toDelete[i]}`);
        }
      }""",
    """      // ★ 5.1.70：三段计时汇总（**整批一条**日志）。
      //   判据：拷贝 vs 解码 谁占大头 ⇒ 决定「砍 cacheThumb」还是「让帧已够」。
      //   例：拷贝 2.5s / 解码 0.8s / 删 0.2s ⇒ 大头是纯 IO，让帧就是最优解。
      const tDel0: number = Date.now();
      await this.service.setAlbumIndexBatch(idxBatch);
      for (let i: number = 0; i < toDelete.length; i++) {
        const derr: string | null =
          ExportService.deleteFile(this.service.receiveRoot, toDelete[i]);
        if (derr !== null) {
          Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${toDelete[i]}`);
        }
      }
      const tDel: number = Date.now() - tDel0;
      this.service.logAuto(`[耗时] 存相册 ${gotUris.length} 项：`
        + `拷贝 ${tCopy}ms + 解码缩略图 ${tThumb}ms + 落盘删沙箱 ${tDel}ms`
        + `（让帧 ${Index.ALBUM_YIELD_EVERY} 张/次）`);""",
    '①d 汇总日志')

# ---- ② 探测改后台静默：加闸门字段 ----
edit(
    """  private async probeAlbumOnEnterChat(): Promise<void> {
    try {""",
    """  private async probeAlbumOnEnterChat(): Promise<void> {
    // ★★ 5.1.70：**重入闸门**。原来切 tab 会触发、点击气泡也会触发，
    //   两路并发时会对同一批 uri 重复探一遍（426 张 = 白干）。
    if (this.albumProbeRunning) {
      return;
    }
    this.albumProbeRunning = true;
    try {""",
    '②a 探测闸门')

# ---- ② catch 后释放闸门 ----
edit(
    """    } catch (e) {
      const err: BusinessError = e as BusinessError;
      // ⚠️ 探测失败**绝不能**影响切 tab，只记日志
      this.service.logAuto(`切消息页相册探测异常（已忽略）：${err.code} ${err.message}`);
    }
  }""",
    """    } catch (e) {
      const err: BusinessError = e as BusinessError;
      // ⚠️ 探测失败**绝不能**影响切 tab，只记日志
      this.service.logAuto(`切消息页相册探测异常（已忽略）：${err.code} ${err.message}`);
    } finally {
      this.albumProbeRunning = false;
    }
  }

  /**
   * ★★ 5.1.70（vivi 要求）：相册资产探测改为**后台静默**。
   *
   * 【原来】只在「切到消息 tab」时跑 `probeAlbumOnEnterChat()`
   *   ⇒ 426 张时切页必卡（每 20 张让一帧也救不了，扫盘 + 打开 + 读字节本身就要时间）。
   *
   * 【现在】`onPageShow`（应用回前台）就启动一次，
   *   **与 tab 切换完全解耦** ⇒ 用户什么时候切页都不再触发探测。
   *
   * 【为什么不直接 `void` 掉不 await】探测是 async；
   *   `onPageShow` 里不 await ⇒ 不阻塞启动流程，但**闸门 + 静默日志**保证不重入。
   *
   * ⚠️ 「已删除」的处置**完全不变**（清 uri + 更新角标 + 一条汇总日志），
   *   只是**不再占用切页那一帧**。
   */
  private scheduleBackgroundAlbumProbe(): void {
    this.probeAlbumOnEnterChat();
  }""",
    '②b finally + 后台入口')


def main():
    path = os.path.join(ROOT, REL)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()

    if PROBE in src:
        print('SKIP 已应用')
        return

    for old, new, tag in EDITS:
        if src.count(old) != 1:
            print('ABORT %s count=%d' % (tag, src.count(old)))
            print('--- old 前 150 ---')
            print(repr(old[:150]))
            sys.exit(1)
        src = src.replace(old, new, 1)

    # 语义自检
    for s in ['let tCopy: number = 0;', 'let tThumb: number = 0;',
              'tCopy += Date.now() - t0;', 'tThumb += Date.now() - t1;',
              '[耗时] 存相册', 'albumProbeRunning']:
        if s not in src:
            print('ABORT 自检失败: %s' % s)
            sys.exit(1)
    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)
    print('花括号 { %d vs } %d' % (src.count('{'), src.count('}')))

    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('OK %s (%d 处)' % (REL, len(EDITS)))
    print('自检: tCopy ✓ tThumb ✓ 汇总日志 ✓ 探测闸门 ✓')


if __name__ == '__main__':
    main()
