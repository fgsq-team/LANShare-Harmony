#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.66 C1b：补上漏掉的「探测循环内让帧」（幂等）

`PROBE_YIELD_EVERY` 常量已落盘，但 `probeAlbumOnEnterChat` 循环体
里的 `sinceYield` 判断没落盘（同文件多处替换的老问题，本轮第 3 次）。
⇒ **常量在、逻辑不在 = 完全无效**（编译器不报错，因为常量被当未用变量）。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = 'let sinceYield: number = 0;'
REL = 'entry/src/main/ets/pages/Index.ets'

OLD = """      let checked: number = 0;
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

NEW = """      let checked: number = 0;
      const dead: string[] = [];
      // ★★ 5.1.66 C1b：**循环内**周期性让帧。
      //   `albumAssetAlive` 是纯同步 IO（statSync / openSync / readSync），
      //   400+ 张逐个探会把主线程占死 ⇒ 切消息页卡住（vivi 2026-10-05 实测）。
      //   ⚠️ 原实现只在**循环之前**调了一次 `yieldOnce()`，那等于没让 ——
      //   几百张的 IO 全挤在第一次让帧之后的整段里。
      //   ⇒ 每 PROBE_YIELD_EVERY 张让一帧，把单次连续占用压到 20 张的量。
      let sinceYield: number = 0;
      for (const key of this.albumIndex.keys()) {
        // key 形如 `消息id#序号`；只看 part 0（相册 uri）
        const uri: string = this.albumPart(key, 0);
        if (uri.length === 0 || this.albumClearedIds.has(key)) {
          continue;
        }
        checked += 1;
        sinceYield += 1;
        if (sinceYield >= Index.PROBE_YIELD_EVERY) {
          sinceYield = 0;
          await Index.yieldOnce();
        }
        if (!this.albumAssetAlive(uri)) {
          dead.push(key);
        }
      }
      // 收尾再让一帧：最后不足一批的也别把尾段留到下一帧
      if (sinceYield > 0) {
        await Index.yieldOnce();
      }"""


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
