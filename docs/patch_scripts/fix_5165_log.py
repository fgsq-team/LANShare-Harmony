#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.65 A4：入队日志聚合（幂等）

问题（vivi 2026-10-05 真机 426 张）：
  `[12:56:54] 已接收 426 项` 之后**同一秒**打出 426 条
  `入队待存相册：「...」(id=...)`。
  `logAuto` 会 emit ⇒ onSnapshot ⇒ refreshReceived
  ⇒ **每条日志都触发一次全量扫盘 + 三个全量重算**。
  ⇒ 收尾瞬间 426 次 O(n) 重建，这就是「接收到最后一张很卡」的直接原因。

改法：先把本轮入队的名字收进数组，循环结束后按数量决定怎么打：
    ≤ 8 张  逐条打（调试时看得见每张，与原来一致）
    > 8 张  只打一条汇总（含首尾样本）
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = '5.1.65 A4'
REL = 'entry/src/main/ets/pages/Index.ets'

DECL_OLD = """    const now: number = Date.now();
    for (let i: number = oldCount; i < this.chat.length; i++) {"""

DECL_NEW = """    const now: number = Date.now();
    // ★★ 5.1.65 A4：本轮入队的名字先收集，循环结束后按数量决定打日志的粒度。
    //   `logAuto` 会 emit ⇒ onSnapshot ⇒ refreshReceived ⇒ 全量扫盘 + 三个全量重算
    //   ⇒ 426 张逐条打 = 同一秒 426 次 O(n) 重建（vivi 2026-10-05 实测卡顿真凶）。
    const enqueued: string[] = [];
    for (let i: number = oldCount; i < this.chat.length; i++) {"""

PUSH_OLD = """      this.autoSavePending.push(m.id);
      this.service.logAuto(`入队待存相册：「${m.content}」(id=${m.id})`);
    }
    this.service.logAuto(`待存队列共 ${this.autoSavePending.length} 项`);"""

PUSH_NEW = """      this.autoSavePending.push(m.id);
      enqueued.push(`${m.content}|${m.id}`);
    }
    // ★★ 5.1.65 A4：按数量选粒度（>8 张只打一条汇总）。
    if (enqueued.length > 8) {
      this.service.logAuto(`[相册] 本次入队 ${enqueued.length} 项`
        + `（示例：「${enqueued[0]}」…「${enqueued[enqueued.length - 1]}」），`
        + `待存队列共 ${this.autoSavePending.length} 项`);
    } else {
      for (let i: number = 0; i < enqueued.length; i++) {
        this.service.logAuto(`入队待存相册：${enqueued[i]}`);
      }
      this.service.logAuto(`待存队列共 ${this.autoSavePending.length} 项`);
    }"""


def main():
    path = os.path.join(ROOT, REL)
    with io.open(path, 'r', encoding='utf-8', newline='') as f:
        src = f.read()

    if PROBE in src:
        print('SKIP 已应用')
        return

    for old, new, tag in ((DECL_OLD, DECL_NEW, '声明'), (PUSH_OLD, PUSH_NEW, '聚合')):
        n = src.count(old)
        if n != 1:
            print('ABORT %s: count(old)=%d 期望 1' % (tag, n))
            print(repr(old[:200]))
            sys.exit(1)
        src = src.replace(old, new, 1)

    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)

    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(src)
    print('OK %s (A4 入队日志聚合)' % REL)


if __name__ == '__main__':
    main()
