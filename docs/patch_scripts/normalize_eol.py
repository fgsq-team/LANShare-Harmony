# -*- coding: utf-8 -*-
"""
把 ets/json5 源码的行尾统一规范化。**改代码前先跑一次**。

背景（2026-10-02 踩到）：
  用 `open(p, 'w', encoding='utf-8').write(s)` 写文件时，Windows 下 Python 默认
  newline=None 会把 `\\n` 转成 `\\r\\n`。而工程源文件约定是 **LF**。
  一旦某个文件被写成 CRLF，后续所有「按 LF 写的锚点」都匹配不上 ——
  表现是补丁脚本静默不匹配 / 报 assert count=0，非常浪费时间。

所以：
  - 读用 `io.open(..., newline='')` 保留原样；
  - 写回统一用 `newline='\\n'` 强制 LF（不要依赖默认转换）。

用法：
  python docs/patch_scripts/normalize_eol.py          # 规范化所有 ets/json5
  python docs/patch_scripts/normalize_eol.py --check  # 只检查不改写
"""
import os
import sys
import io

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXTS = ('.ets', '.json5', '.json', '.ts')

CHECK = '--check' in sys.argv

changed = []
bad = []

for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, 'entry', 'src')):
    for fn in filenames:
        if not fn.endswith(EXTS):
            continue
        p = os.path.join(dirpath, fn)
        raw = io.open(p, 'rb').read()
        crlf = raw.count(b'\r\n')
        if crlf == 0:
            continue
        rel = os.path.relpath(p, ROOT)
        if CHECK:
            bad.append((rel, crlf))
            continue
        s = raw.decode('utf-8').replace('\r\n', '\n')
        io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
        changed.append((rel, crlf))

# 顺带 AppScope/app.json5 与 module.json5
for rel in ('AppScope/app.json5', 'entry/src/main/module.json5'):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    raw = io.open(p, 'rb').read()
    crlf = raw.count(b'\r\n')
    if crlf:
        if CHECK:
            bad.append((rel, crlf))
        else:
            io.open(p, 'w', encoding='utf-8', newline='\n').write(
                raw.decode('utf-8').replace('\r\n', '\n'))
            changed.append((rel, crlf))

if CHECK:
    if not bad:
        print('OK: 所有源码均为 LF')
    else:
        print('以下文件含 CRLF:')
        for rel, n in bad:
            print('  %s  (%d 行)' % (rel, n))
else:
    if not changed:
        print('OK: 无需规范化（全是 LF）')
    else:
        print('已规范化为 LF:')
        for rel, n in changed:
            print('  %s  (%d 行 CRLF -> LF)' % (rel, n))
