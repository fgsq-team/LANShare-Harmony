#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5.1.56 补丁②：发版体检项同步
  - `Index.ets` 的 ABOUT_FALLBACK_VER：5.1.55 -> 5.1.56
    （取不到 bundleManager 时回落到它；这条**确实会被遗忘**，已进 MEMORY 铁律）
  - `AppScope/app.json5` 的 versionCode：5000155 -> 5000156
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
BK = os.path.join(ROOT, 'docs', 'backups')
IDX = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets')
AP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = "const ABOUT_FALLBACK_VER: string = '5.1.56';"
OLD_IDX = "const ABOUT_FALLBACK_VER: string = '5.1.55';"
NEW_IDX = "const ABOUT_FALLBACK_VER: string = '5.1.56';"
OLD_CODE = '"versionCode": 5000155,'
NEW_CODE = '"versionCode": 5000156,'


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
    idx = read(IDX)
    ap = read(AP)
    if SENTINEL in idx and NEW_CODE in ap:
        print('ALREADY APPLIED')
        return 0
    assert idx.count(OLD_IDX) == 1, 'ABOUT_FALLBACK_VER anchor count=%d' % idx.count(OLD_IDX)
    assert idx.count(SENTINEL) == 0
    assert ap.count(OLD_CODE) == 1, 'versionCode anchor count=%d' % ap.count(OLD_CODE)
    assert ap.count(NEW_CODE) == 0

    idx2 = idx.replace(OLD_IDX, NEW_IDX)
    ap2 = ap.replace(OLD_CODE, NEW_CODE)
    assert SENTINEL in idx2 and NEW_CODE in ap2

    backup(IDX, 'v5156b')
    backup(AP, 'v5156b')
    write(IDX, idx2)
    write(AP, ap2)
    print('OK 5.1.56b: ABOUT_FALLBACK_VER + versionCode')
    return 0


if __name__ == '__main__':
    sys.exit(main())