#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5.1.57 规则验证（先跑真实输入，通过后才允许写进 ArkTS）

vivi 2026-10-03 要求：
  「把错误后缀文件原本的 `.` 都改为 `_`，只保留新添加后缀的那一个」
  参照现象：相册把 `abc.1` 存成 `abc_1.jpg` / `abc_1_1.jpg` / `abc_1_2.jpg`。

复刻 `MagicType.fixExtByMagic` 的**改名决策**（不含IO），跑真实用例表。
"""
import re
import sys

MEDIA_EXTS = {
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'heic', 'heif', 'avif',
    'ico', 'tif', 'tiff',
    'mp4', 'mov', 'm4v', 'mkv', 'webm', 'avi', '3gp', 'ts', 'flv',
    'wmv', 'rmvb', 'mpg', 'mpeg', 'ogv',
    'mp3', 'aac', 'm4a', 'wav', 'flac', 'ogg', 'ape',
}

EQUIV_EXTS = [
    ['jpg', 'jpg', 'jpeg', 'jpe', 'jfif'],
    ['png', 'png'],
    ['gif', 'gif'],
    ['bmp', 'bmp'],
    ['webp', 'webp'],
    ['heic', 'heic', 'heif', 'heics'],
    ['avif', 'avif'],
    ['tiff', 'tif', 'tiff'],
    ['mp4', 'mp4', 'm4v', 'mpeg4'],
    ['mov', 'mov', 'qt'],
    ['3gp', '3gp', '3g2', '3gpp'],
    ['mkv', 'mkv', 'webm'],
    ['avi', 'avi'],
    ['flv', 'flv'],
    ['mp3', 'mp3'],
    ['m4a', 'm4a', 'aac', 'mp4a'],
    ['wav', 'wav', 'wave'],
    ['ogg', 'ogg', 'opus'],
    ['flac', 'flac'],
]


def rtrim(s):
    return s.rstrip(' \t\n\r')


def rstrip_copy(name):
    """剥掉尾部 ` (n)`（最多 8 层），每层都 rtrim"""
    n = name
    for _ in range(8):
        n = rtrim(n)
        if not n.endswith(')'):
            return n
        lp = n.rfind('(')
        if lp < 0:
            return n
        inner = n[lp + 1:len(n) - 1]
        if len(inner) == 0 or len(inner) > 6:
            return n
        if not inner.isdigit():
            return n
        n = n[:lp]
    return n


def tail_ext(base):
    dot = base.rfind('.')
    if dot <= 0 or dot == len(base) - 1:
        return ''
    return rtrim(base[dot + 1:]).lower()


def same_kind(tail, det):
    t = rtrim(tail).lower()
    d = rtrim(det).lower()
    if len(t) == 0:
        return False
    for row in EQUIV_EXTS:
        if row[0] == d:
            return t in row[1:]
    return t == d


def dots_to_underscores(s):
    """★★ 5.1.57 新增：stem 里的所有 `.` 一律换成 `_`"""
    return s.replace('.', '_')


def decide(filename, detected, taken=()):
    """返回目标文件名；不改则返回 None

    @param taken 已存在的文件名集合（模拟沙箱里已有的文件）
    """
    if len(detected) == 0 or detected not in MEDIA_EXTS:
        return None# 探测不出/ 非媒体 => 不动
    base = rstrip_copy(rtrim(filename))
    if same_kind(tail_ext(base), detected):
        return None                                        # 后缀已正确
    stem = dots_to_underscores(base)                       # ★ 新规则
    name = '%s.%s' % (stem, detected)
    if name in taken:
        for k in range(2, 50):
            cand = '%s (%d).%s' % (stem, k, detected)
            if cand not in taken:
                name = cand
                break
        else:
            return None
    return name


# ======================================================================
# 用例表（全部用 vivi 给的真实文件名）
# ======================================================================
CASES = [
    # (原名,魔数结果, 沙箱已占用, 期望目标名, 说明)
    ('abc.1',                'jpg', (),                   'abc_1.jpg',      'vivi 的核心用例'),
    ('abc.jpg.1',            'jpg', (),                   'abc_jpg_1.jpg',  '双扩展名'),
    ('IMG_20260929_201632.jpg.1', 'jpg', (),             'IMG_20260929_201632_jpg_1.jpg', '真实相机名'),
    ('IMG_20260929_201632.jpg.1', 'jpg', ('IMG_20260929_201632_jpg_1.jpg',),
     'IMG_20260929_201632_jpg_1 (2).jpg', '第二次接收（递增去重）'),
    ('abc.1',                'jpg', ('abc_1.jpg', 'abc_1 (2).jpg', 'abc_1 (3).jpg'),
     'abc_1 (4).jpg',        '第三次接收'),
    ('.1',                   'jpg', (),                   '_1.jpg',         '退化：stem 只有一个点'),
    # ---- 不应改动的 ----
    ('a.jpg',                'jpg', (),                   None, '后缀已正确'),
    ('a.jpeg',               'jpg', (),                   None, '同类型（等价组）⇒ 不动，不能变 a_jpeg.jpg'),
    ('a.JPEG',               'jpg', (),                   None, '大小写归一'),
    ('扫描全能王 2026-10-01 09.47.jpg (1)', 'jpg', (),    None, '剥 (1) 后后缀已正确 ⇒ 不动'),
    ('报告 v1.2.pdf',        'pdf', (),                   None, 'pdf 非媒体 ⇒ 不动'),
    ('abc.1',                '',    (),                   None, '探测不出⇒ 不动'),
    ('abc.1',                'zip', (),                   None, '非媒体后缀不动'),
]


def main():
    fail = 0
    for i, (src, det, taken, want, why) in enumerate(CASES):
        got = decide(src, det, taken)
        ok = (got == want)
        if not ok:
            fail += 1
        print('%-4s #%-2d %-36s det=%-5s => %-38s (want %-38s) %s'
              % ('OK' if ok else 'FAIL', i, src, det or '<none>',
                 got or '<不改>', want or '<不改>', why))
    print('-' * 100)
    if fail:
        print('FAILED: %d/%d 用例不符 ⇒ 不允许写进 ArkTS' % (fail, len(CASES)))
        return 1
    print('ALL PASS: %d/%d ⇒ 规则正确，可以写进 ArkTS' % (len(CASES), len(CASES)))
    return 0


if __name__ == '__main__':
    sys.exit(main())