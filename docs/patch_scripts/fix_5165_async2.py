#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.65 A3 收尾：把剩下的两处同步 copyTo 改成 async（幂等）

为什么单独一个脚本：上一个脚本对**同一文件**的两条替换，
第二条读到的文件已被第一条改过 ⇒ 校验基于旧内容 ⇒ 漏改。
★ 教训：补丁脚本处理同文件多处替换时，**必须先全部 apply 再统一落盘**
  （本项目的标准做法就是「先全部校验、内存构造、末尾统一落盘」，
  但我那个脚本每条 edit 都自己读文件 ⇒ 等于逐条落盘前读 ⇒ 这个坑）。

本脚本两处：
  1. ExportService.copyTo 声明 → async
  2. Index.ets:4058 调用点 → 加 await
（第 3 处 4516 上个脚本已改好）
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


def main():
    plans = []

    # ---- 1) copyTo 声明 ----
    rel1 = 'entry/src/main/ets/service/ExportService.ets'
    p1 = os.path.join(ROOT, rel1)
    s1 = io.open(p1, 'r', encoding='utf-8', newline='').read()
    old1 = "  static copyTo(srcPath: string, dstUri: string, name: string): string {"
    new1 = ("""  /**
   * ★★ 5.1.65：改成 **async** —— 原来同步 `readSync`/`writeSync` 逐块拷贝，
   *   40 张图把主线程占满 2~4 秒（vivi 2026-10-05 真机实测，存相册期间界面全冻）。
   *   ⚠️ **两个调用点都要加 `await`**（Index.ets 的 saveImageToAlbum 与批量主循环）。
   *   ⚠️ 与「5.1.34 落盘改异步掉速 1/6」不冲突：那次是**网页上传流控**
   *   （6 并发连接 + 边收边落盘，microtask 饿死流控）；这里是**串行、
   *   用户已点确认、无协议交织**，让出的主线程时间没有状态机要抢。
   */
  static async copyTo(srcPath: string, dstUri: string, name: string): Promise<string> {""")
    probe1 = '5.1.65：改成 **async**'
    if probe1 in s1:
        print('SKIP %s 声明已改' % rel1)
    else:
        if s1.count(old1) != 1:
            print('ABORT 声明: count=%d' % s1.count(old1))
            sys.exit(1)
        s1 = s1.replace(old1, new1, 1)
        assert probe1 in s1, '探针未命中'
        plans.append((p1, rel1, s1))

    # ---- 2) 调用点 4058 ----
    rel2 = 'entry/src/main/ets/pages/Index.ets'
    p2 = os.path.join(ROOT, rel2)
    s2 = io.open(p2, 'r', encoding='utf-8', newline='').read()
    old2 = "      const msg: string = ExportService.copyTo(path, uris[0], name);"
    new2 = "      const msg: string = await ExportService.copyTo(path, uris[0], name);"
    probe2 = 'await ExportService.copyTo(path, uris[0], name)'
    if probe2 in s2:
        print('SKIP %s 调用点已改' % rel2)
    else:
        if s2.count(old2) != 1:
            print('ABORT 调用点: count=%d' % s2.count(old2))
            sys.exit(1)
        s2 = s2.replace(old2, new2, 1)
        assert probe2 in s2, '探针未命中'
        plans.append((p2, rel2, s2))

    for path, rel, content in plans:
        with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
        print('OK %s' % rel)

    if not plans:
        print('DONE (无改动)')
    else:
        print('DONE')


if __name__ == '__main__':
    main()
