#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5.1.57 补丁：改名时把 stem 里的 `.` 全换成 `_`

vivi 2026-10-03：
  「把错误后缀文件原本的 . 都改为 _，只保留新添加后缀的一个」
  参照现象：相册把 `abc.1` 存成 `abc_1.jpg` / `abc_1_1.jpg` / `abc_1_2.jpg`。

规则已用 `docs/patch_scripts/verify_ext_rule_5157.py` 跑真实输入验证（13/13 PASS）。

只改 `MagicType` 两处：
  1. 新增 `static dotsToUnderscores(s)`；
  2. `fixExtByMagic` 的 `finalName` / 递增去重候选都基于「点已换下划线」的 stem。
⚠️ **判「后缀对不对」仍然用原始 base**（含点的原名）——
   换下划线只发生在「决定改名之后」，否则 `a.b.jpg` 会被误判成后缀缺失。

纪律：幂等（sentinel + 重跑 ALREADY）；先全部校验、末尾统一落盘；UTF-8 + LF。
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
BK = os.path.join(ROOT, 'docs', 'backups')
FS = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'FileStorage.ets')
AP = os.path.join(ROOT, 'AppScope', 'app.json5')
IDX = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets')

SENTINEL = 'static dotsToUnderscores(s: string): string'

# ---- 1) 新增工具方法（挂在 baseNameOf 之前）----
OLD_ANCHOR = """  /** ★ 5.1.55：取路径里的**文件名部分**（去掉目录） */
  static baseNameOf(path: string): string {"""

NEW_METHOD = """  /**
   * ★★ 5.1.57：把 stem 里的**所有 `.` 换成 `_`** —— 改名时用。
   *
   * ## 为什么（vivi 2026-10-03 观察到的现象）
   *   相册把 `abc.1` 存成 `abc_1.jpg` / `abc_1_1.jpg` / `abc_1_2.jpg`
   *   ⇒ 沙箱里也保持同样写法，文件名与相册一致、也不再有多扩展名歧义。
   *
   * ## 为什么不用 `replaceAll`
   *   ArkTS 的 `String.replaceAll` 在低版本 SDK 上行为不稳，
   *   项目里统一用 `split().join()`（同 `LanService` 等处的既有写法）。
   *
   * ⚠️ **只在「已经决定要改名」之后调用**：
   *   判「末尾后缀对不对」必须用**原始名**（仍带点），
   *   否则 `a.b.jpg` 会被算成「后缀 `_jpg`」⇒ 误判需要改名。
   */
  static dotsToUnderscores(s: string): string {
    if (s.indexOf('.') < 0) {
      return s;
    }
    return s.split('.').join('_');
  }

  /** ★ 5.1.55：取路径里的**文件名部分**（去掉目录） */
  static baseNameOf(path: string): string {"""

# ---- 2) finalName 用「点已换下划线」的 stem ----
OLD_FINAL = """      let finalName: string = `${base}.${real}`;"""
NEW_FINAL = """      // ★★ 5.1.57：决定改名之后，把 stem 里的点全换成下划线，
      //   只保留这里新增的**一个**后缀点（`abc.1` → `abc_1.jpg`）。
      //   ⚠️ 上面的 `sameKind` 判定用的是**原始 base**（仍带点）—— 顺序不能颠倒。
      const stem: string = MagicType.dotsToUnderscores(base);
      let finalName: string = `${stem}.${real}`;"""

OLD_LOOP = """          const cand: string = `${base} (${k}).${real}`;"""
NEW_LOOP = """          const cand: string = `${stem} (${k}).${real}`;"""

OLD_LOG = """          Log.w(TAG, `魔数纠错：${base}.${real} 的候选名都被占用，保持原名`);"""
NEW_LOG = """          Log.w(TAG, `魔数纠错：${stem}.${real} 的候选名都被占用，保持原名`);"""

OLD_VER = "const ABOUT_FALLBACK_VER: string = '5.1.56';"
NEW_VER = "const ABOUT_FALLBACK_VER: string = '5.1.57';"
OLD_CODE = '"versionCode": 5000156,'
NEW_CODE = '"versionCode": 5000157,'
OLD_NAME = '"versionName": "5.1.56",'
NEW_NAME = '"versionName": "5.1.57",'


def read(p):
    return io.open(p, 'r', encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def backup(p, tag):
    if not os.path.isdir(BK):
        os.makedirs(BK)
    dst = os.path.join(BK, os.path.basename(p) + '.' + tag)
    if not os.path.exists(dst):
        shutil.copy2(p, dst)
        print('  备份 -> %s' % dst)


def main():
    fs = read(FS)
    ap = read(AP)
    idx = read(IDX)

    if SENTINEL in fs:
        print('ALREADY APPLIED')
        return 0

    # ---- 校验（全部通过才落盘）----
    assert fs.count(OLD_ANCHOR) == 1, 'anchor baseNameOf count=%d' % fs.count(OLD_ANCHOR)
    assert fs.count(NEW_METHOD) == 0
    assert fs.count(OLD_FINAL) == 1, 'finalName count=%d' % fs.count(OLD_FINAL)
    assert fs.count(OLD_LOOP) == 1, 'loop cand count=%d' % fs.count(OLD_LOOP)
    assert fs.count(OLD_LOG) == 1, 'log count=%d' % fs.count(OLD_LOG)
    assert '"5.1.56"' in ap and ap.count(NEW_NAME) == 0
    assert ap.count(OLD_CODE) == 1 and ap.count(NEW_CODE) == 0
    assert idx.count(OLD_VER) == 1 and idx.count(NEW_VER) == 0

    # ---- 内存构造 ----
    fs2 = fs.replace(OLD_ANCHOR, NEW_METHOD)
    fs2 = fs2.replace(OLD_FINAL, NEW_FINAL)
    fs2 = fs2.replace(OLD_LOOP, NEW_LOOP)
    fs2 = fs2.replace(OLD_LOG, NEW_LOG)
    ap2 = ap.replace(OLD_CODE, NEW_CODE).replace(OLD_NAME, NEW_NAME)
    idx2 = idx.replace(OLD_VER, NEW_VER)

    # ---- 二次校验：确认每处都替换成功且没有残留 ----
    assert SENTINEL in fs2
    assert fs2.count(OLD_ANCHOR) == 1          # 原锚点仍在（方法被插在它前面）
    assert fs2.count(OLD_FINAL) == 0
    assert fs2.count(OLD_LOOP) == 0
    assert fs2.count(OLD_LOG) == 0
    assert fs2.count('${stem}.${real}') == 2   # finalName + 兜底日志
    assert fs2.count('${stem} (${k}).${real}') == 1
    # ★关键：判后缀仍用原始 base（没有被换下划线）
    assert 'if (MagicType.sameKind(MagicType.tailExt(base), real)) {' in fs2
    assert NEW_NAME in ap2 and NEW_CODE in ap2
    assert NEW_VER in idx2

    # ---- 统一落盘 ----
    backup(FS, 'v5157pre')
    backup(AP, 'v5157pre')
    backup(IDX, 'v5157pre')
    write(FS, fs2)
    write(AP, ap2)
    write(IDX, idx2)
    print('OK 5.1.57 patched: FileStorage.ets / app.json5 / Index.ets')
    return 0


if __name__ == '__main__':
    sys.exit(main())