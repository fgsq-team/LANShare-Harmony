#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.63 批量 425 张暴露的三个 bug 修复（幂等补丁脚本）

B1  FileStorage.ets  sameKind off-by-one  => `row.indexOf(t) >= 1` 改 `>= 0`
    根因：EQUIV_EXTS 的 row[0] 就是规范名本身，`indexOf('jpg')` 返回 0，
          `0 >= 1` 为 false ⇒ jpg/jpeg 互认失败 ⇒ 误判「后缀错」⇒ 改名。
    现象：SelfieCity_xxx_save.jpg → SelfieCity_xxx_save_jpg.jpg
    （5.1.57 的 dotsToUnderscores 再把点换成 _，于是变成 _jpg.jpg）

B2  LanService.ets   MAX_CHAT 200 → 1000
    根因：425 项涌入时 chatRing 被 shift() 挤掉前 225 条 ⇒ 「只收到 200 张」。
    注意：文件全部落盘了（清单 [425/425] 全到），丢的是聊天消息。

B3  ExportService.ets  MAX_LIST 40 → 1000
    现象：文件页只显示 40 个文件，其余 385 个看不到。
    同步扫盘条数上限 MAX_LIST*3 跟着放大。

纪律（见 MEMORY.md）：
  - 幂等：sentinel 判重，重跑直接 exit 0
  - 先全部校验、内存构造、末尾统一落盘
  - io.open(..., newline='\\n') 强制 LF
  - 探针避开 markdown 强调标记与缩进敏感串
"""
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PATCHES = []


def patch(rel, subs):
    PATCHES.append((rel, subs))


# ---------------------------------------------------------------- B1
# ⚠️ 缩进串必须带前导 \n（"        return" 是 "          return" 的子串）
patch('entry/src/main/ets/service/FileStorage.ets', [(
    "\n  static sameKind(tail: string, det: string): boolean {",
    "\n  /// ★★ 5.1.63 B1 BUG FIX：原为 `row.indexOf(t) >= 1`。\n"
    "  ///   `EQUIV_EXTS` 的 **row[0] 就是规范名本身**，所以 `indexOf('jpg')` 返回 **0**，\n"
    "  ///   `0 >= 1` 为 false ⇒ **jpg 与 jpg 被判成不同类** ⇒ 触发改名。\n"
    "  ///   现象（vivi 2026-10-05 真机 425 张批量）：\n"
    "  ///     `SelfieCity_xxx_save.jpg` → `SelfieCity_xxx_save_jpg.jpg`\n"
    "  ///   （再经 5.1.57 的 dotsToUnderscores 把点换成 _ ⇒ 成了 `_jpg.jpg`）\n"
    "  ///   ★ 只有**非规范名**（jpeg/jpe/jfif）碰巧正确 ⇒ 表现为「**有些** jpg 被加后缀」。\n"
    "  ///   正解：`>= 0`（0 位是规范名本身，也算等价）。\n"
    "  static sameKind(tail: string, det: string): boolean {",
    "5.1.63 B1 BUG FIX",
), (
    "\n        return row.indexOf(t) >= 1;   // 0 位是规范名本身，也算等价",
    "\n        return row.indexOf(t) >= 0;   // ★ 5.1.63 B1：0 位是规范名本身，必须算等价",
    "row.indexOf(t) >= 0",
)])

# ---------------------------------------------------------------- B2
patch('entry/src/main/ets/service/LanService.ets', [(
    "\nconst MAX_CHAT: number = 200;",
    "\n/// ★★ 5.1.63 B2：200 → 1000。\n"
    "///   vivi 2026-10-05 真机：批量发 429 个文件，清单 [425/425] 全部收到并落盘，\n"
    "///   但聊天记录只留下 200 条 ⇒ 前 225 条被 chatRing.shift() 挤掉\n"
    "///   ⇒ 日志「[相册] 新消息 0 -> 200」⇒ 用户以为「只收到 200 张」。\n"
    "///   ★ 这是**内存态环形缓冲**条数，与「文件是否落盘」无关，两者不要混。\n"
    "const MAX_CHAT: number = 1000;",
    "5.1.63 B2",
)])

# ---------------------------------------------------------------- B3
patch('entry/src/main/ets/service/ExportService.ets', [(
    "\nconst MAX_LIST: number = 40;",
    "\n/// ★★ 5.1.63 B3：40 → 1000。\n"
    "///   vivi 2026-10-05 真机：存了 200 张进相册，但**文件页只显示 40 个**\n"
    "///   ⇒ 剩下 360 个「看不到」（其实都在沙箱里）。\n"
    "///   ⚠️ UI 上那句「列表最多显示最近 40 个」的提示文案也要一起改（见 Index.ets）。\n"
    "const MAX_LIST: number = 1000;",
    "5.1.63 B3",
)])

# ---------------------------------------------------------------- B3-UI 文案
patch('entry/src/main/ets/pages/Index.ets', [(
    "Text('列表最多显示最近 40 个；长按文件可多选，批量保存 / 删除')",
    "Text('列表最多显示最近 1000 个；长按文件可多选，批量保存 / 删除')",
    "最近 1000 个",
)])

# ---------------------------------------------------------------- 版本号 5.1.63
patch('AppScope/app.json5', [(
    "\n    \"versionCode\": 5000162,\n    \"versionName\": \"5.1.62\",",
    "\n    \"versionCode\": 5000163,\n    \"versionName\": \"5.1.63\",",
    "5000163",
)])

patch('entry/src/main/ets/pages/Index.ets', [(
    "const ABOUT_FALLBACK_VER: string = '5.1.62';",
    "const ABOUT_FALLBACK_VER: string = '5.1.63';",
    "5.1.63",
)])


# ---------------------------------------------------------------- 引擎
def main():
    plans = []
    for rel, subs in PATCHES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print('MISSING: %s' % rel)
            sys.exit(1)
        with io.open(path, 'r', encoding='utf-8', newline='') as f:
            src = f.read()
        # 按文件聚合多组替换；每组自带探针（new 的首行注释）
        cur = src
        for old, new, probe in subs:
            n = cur.count(old)
            if n != 1:
                print('ABORT %s: count(old)=%d (期望 1)\n--- old ---\n%s' % (rel, n, old))
                sys.exit(1)
            if probe in cur:
                print('ABORT %s: 探针已存在(可能已应用): %s' % (rel, probe))
                sys.exit(1)
            cur = cur.replace(old, new, 1)
            if probe not in cur:
                print('ABORT %s: 探针未命中 %s' % (rel, probe))
                sys.exit(1)
        plans.append((path, rel, src, cur))

    written = []
    for path, rel, src, cur in plans:
        if src == cur:
            print('SKIP %s (已是新内容)' % rel)
            continue
        with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(cur)
        written.append(rel)
        print('OK   %s' % rel)

    # 幂等复检：探针必须全部在位（比「旧串消失」可靠 —— 有些 old 是
    # 方法签名/文案骨架，改动只发生在它的**下一行**，old 本身合法保留）。
    print('--- 复检 ---')
    for rel, subs in PATCHES:
        path = os.path.join(ROOT, rel)
        with io.open(path, 'r', encoding='utf-8', newline='') as f:
            t = f.read()
        for old, new, probe in subs:
            assert t.count(probe) == 1, '探针异常: %s / %s' % (rel, probe)
    print('ALL OK, written=%d' % len(written))


if __name__ == '__main__':
    main()
