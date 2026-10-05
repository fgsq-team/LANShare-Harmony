#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""5.1.68 版本号（幂等）"""
import io
import os

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


def patch(rel, old, new, probe):
    p = os.path.join(ROOT, rel)
    s = io.open(p, 'r', encoding='utf-8', newline='').read()
    if probe in s:
        print('SKIP %s' % rel)
        return
    assert s.count(old) == 1, (rel, s.count(old))
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new, 1))
    print('OK %s' % rel)


patch('AppScope/app.json5',
      '\n    "versionCode": 5000167,\n    "versionName": "5.1.67",',
      '\n    "versionCode": 5000168,\n    "versionName": "5.1.68",',
      '5000168')

patch('entry/src/main/ets/pages/Index.ets',
      "const ABOUT_FALLBACK_VER: string = '5.1.67';",
      "const ABOUT_FALLBACK_VER: string = '5.1.68';",
      "ABOUT_FALLBACK_VER: string = '5.1.68'")
