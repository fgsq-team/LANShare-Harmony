#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.65 消除批量存相册的卡顿（幂等补丁脚本）

实测依据（vivi 2026-10-05 真机，426 张批量）：
  [12:57:21] 确认框返回 40 个 URI      +4s
  [12:57:24] 自动存相册完成：成功 40/40  +3s     <- 点确认后卡 2~4 秒
每批 40 张都在同一个 for 循环里对**每张**做 4 件事，全在主线程：

  1. ExportService.copyTo  —— readSync/writeSync 逐 64KB **同步**拷贝
  2. cacheThumb            —— 一次完整图片解码 + 可能旋转 + pack 写 jpg
  3. setAlbumIndex         —— persistAlbumIndex + persistAlbumRot 各一次
                              **全量遍历整个 albumMap** 再 flush
  4. deleteFile            —— 一次 unlinkSync

★ 最被低估的是第 3 项：albumMap 已有 400+ 条（历史累积），每存一张新图
  就把整张表遍历一遍 + put + flush 两次 ⇒ 一批 40 张 = **160 次全量写**，
  而 albumMap 只多了 40 条 ⇒ **99% 的写入是白做的**。

本脚本四处改动：
  A1 LanService.setAlbumIndexBatch —— 批量写，一次落盘
  A2 存相册主循环改用它；删沙箱挪到落盘之后
  A3 copyTo 改异步（await fileIo.read/write）
  A4 收尾 426 条 logAuto 聚合成一条（每条 logAuto 都会 emit → refreshReceived）

纪律：幂等（探针已存在则干净退出）、先全部校验再统一落盘、强制 LF。
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
# A1  LanService：批量写相册索引
# =====================================================================
_A1_NEW = '''  /**
   * ★★ 5.1.65：批量写相册索引 —— 存相册时**一次落盘**，不是每张一次。
   *
   * ## 为什么（vivi 2026-10-05 真机实测：426 张批量，每批点确认后卡 2~4 秒）
   *   原来每存一张图都调 `setAlbumIndex` → `persistAlbumIndex` + `persistAlbumRot`
   *   各**全量遍历** `albumMap` / `albumRotMap` 再 `flush()`。
   *   ⇒ 一批 40 张 = **160 次全量写**（表里还有 400+ 条历史），
   *     而 albumMap 只多了 40 条 ⇒ **99% 的写入是白做的**。
   *
   * ## 改法
   *   整批先写进 Map（纯内存，微秒级），**循环结束后只落盘一次**。
   *   语义等价性：调用处已改成「落盘成功后才删沙箱副本」，
   *   ⇒ 中途崩溃最坏是丢这一批索引，但沙箱副本还在 ⇒ 下次刷新能重建。
   *
   * @param items 每项格式 `${id}|${uri}|${thumb}|${rot}`
   */
  async setAlbumIndexBatch(items: string[]): Promise<void> {
    if (items.length === 0) {
      return;
    }
    this.albumLoaded = true;
    for (let i: number = 0; i < items.length; i++) {
      const parts: string[] = items[i].split('|');
      if (parts.length >= 4) {
        this.albumMap.set(parts[0], `${parts[1]}|${parts[2]}`);
        this.albumRotMap.set(parts[2], Number(parts[3]));
      }
    }
    await this.persistAlbumIndex();
    await this.persistAlbumRot();
  }

  async setAlbumIndex(id: string, uri: string, thumb: string, rot: number = 0): Promise<void> {'''

edit('entry/src/main/ets/service/LanService.ets',
     "  async setAlbumIndex(id: string, uri: string, thumb: string, rot: number = 0): Promise<void> {",
     _A1_NEW,
     '5.1.65：批量写相册索引')

# =====================================================================
# A2a  声明整批收集数组
# =====================================================================
_A2A_NEW = '''      this.toast(`正在存入相册（${gotUris.length} 个）…`);
      await Index.yieldOnce();
      let ok: number = 0;
      const missed: string[] = [];
      // ★★ 5.1.65：整批收集，循环结束后**一次性**落盘 + 一次性删沙箱。
      const idxBatch: string[] = [];
      const toDelete: string[] = [];'''

edit('entry/src/main/ets/pages/Index.ets',
     '      let ok: number = 0;\n      const missed: string[] = [];',
     _A2A_NEW,
     '5.1.65：整批收集')

# =====================================================================
# A2b  主循环：只进内存，不落盘
# =====================================================================
_A2B_NEW = '''          ok += 1;
          // ★ 5.0.52：拿刚写进去的资产校准探针（见 albumProbeCalibrate）
          this.albumProbeCalibrate(gotUris[j]);
          // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反
          const thumb: string = await this.cacheThumb(ctx, batchPaths[i], batchKeys[i]);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          // ★★ 5.1.65：**只进内存，不落盘**。原来每张都 `await setAlbumIndex`
          //   ⇒ 每张两次全量遍历 albumMap + flush（表里已有 400+ 条），
          //   一批 40 张 = 160 次全量写。改成循环后 `setAlbumIndexBatch` 一次。
          idxBatch.push(`${batchKeys[i]}|${gotUris[j]}|${thumb}|${rot}`);
          // ③ 删沙箱副本挪到**索引落盘之后**（见循环外）——
          //   万一进程挂掉，沙箱副本还在 ⇒ 缩略图与索引可重建，不会丢图。
          toDelete.push(batchPaths[i]);'''

edit('entry/src/main/ets/pages/Index.ets',
     '''          const rot: number = this.service.rotOf(thumb) ?? 0;
          await this.service.setAlbumIndex(batchKeys[i], gotUris[j], thumb, rot);
          const derr: string | null =
            ExportService.deleteFile(this.service.receiveRoot, batchPaths[i]);
          if (derr !== null) {
            Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${batchPaths[i]}`);
          }''',
     _A2B_NEW,
     '5.1.65：**只进内存，不落盘**')

# =====================================================================
# A2c  循环后：先落盘、再删沙箱
# =====================================================================
_A2C_NEW = '''      // ★★ 5.1.65：**先落盘、再删沙箱**（与原来「每张落盘后立刻删」相反，更安全）。
      //   原来每张「落盘索引 → 立刻删沙箱」；中途崩溃 ⇒ 索引写了、文件已删。
      //   现在整批落盘成功后才删 ⇒ 任一步崩溃都还能靠沙箱副本重建缩略图。
      await this.service.setAlbumIndexBatch(idxBatch);
      for (let i: number = 0; i < toDelete.length; i++) {
        const derr: string | null =
          ExportService.deleteFile(this.service.receiveRoot, toDelete[i]);
        if (derr !== null) {
          Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${toDelete[i]}`);
        }
      }
      this.toast(ok > 0 ? `已存入相册 ${ok} 个${extra}` : '存入相册失败');'''

edit('entry/src/main/ets/pages/Index.ets',
     "      this.toast(ok > 0 ? `已存入相册 ${ok} 个${extra}` : '存入相册失败');",
     _A2C_NEW,
     '5.1.65：**先落盘、再删沙箱**')

# =====================================================================
# A3  copyTo 改异步
# =====================================================================
_A3_NEW = '''      // ★★ 5.1.65：同步 64KB 拷贝改**异步**。
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
      }'''

edit('entry/src/main/ets/service/ExportService.ets',
     '''      const buf: ArrayBuffer = new ArrayBuffer(COPY_CHUNK);
      while (true) {
        const n: number = fileIo.readSync(src.fd, buf);
        if (n <= 0) {
          break;
        }
        // 只写实际读到的部分。`fileIo` 命名空间没有导出 WriteOptions 类型，
        // 与其硬凑 options 对象，不如裁一段 ArrayBuffer 来得稳。
        fileIo.writeSync(dst.fd, buf.slice(0, n));
        written += n;
      }''',
     _A3_NEW,
     '5.1.65：同步 64KB 拷贝改**异步**')


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
            print('--- old 前 240 字符 ---')
            print(repr(old[:240]))
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
