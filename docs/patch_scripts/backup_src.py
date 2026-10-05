# -*- coding: utf-8 -*-
"""
源码快照备份 —— 每次改代码**之前**跑一次。

用法：
  python docs/patch_scripts/backup_src.py <版本标签>      # 例：v5045
  python docs/patch_scripts/backup_src.py --list

规则：
- 备份写 docs/backups/（**绝不能放 entry/src 下**，hvigor 会把 src 里任意文件打进 HAP）；
- 文件名 <原名>.<版本标签>；
- 自动只保留**最近 5 个版本**的快照，更老的删掉。
"""
import os
import sys
import shutil
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BAK = os.path.join(ROOT, 'docs', 'backups')

# 需要快照的文件（相对工程根）
TARGETS = [
    'entry/src/main/ets/pages/Index.ets',
    'entry/src/main/ets/service/LanService.ets',
    'entry/src/main/ets/service/V5Transfer.ets',
    'AppScope/app.json5',
]

KEEP = 5


def list_snapshots():
    tags = set()
    for p in glob.glob(os.path.join(BAK, '*.*')):
        base = os.path.basename(p)
        parts = base.split('.')
        if len(parts) >= 3:
            tags.add(parts[-1])
    return sorted(tags)


def prune(tags):
    """只保留最近 KEEP 个版本标签（按字典序，v5xxx 天然有序）"""
    if len(tags) <= KEEP:
        return []
    old = tags[:len(tags) - KEEP]
    removed = []
    for t in old:
        for p in glob.glob(os.path.join(BAK, '*.' + t)):
            os.remove(p)
            removed.append(os.path.basename(p))
    return removed


def main():
    if '--list' in sys.argv:
        for t in list_snapshots():
            print(t)
        return

    tag = sys.argv[1] if len(sys.argv) > 1 else ''
    if not tag:
        print('用法: python backup_src.py <版本标签>   # 例: v5045')
        sys.exit(1)

    os.makedirs(BAK, exist_ok=True)
    wrote = []
    for rel in TARGETS:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            continue
        name = os.path.basename(rel) + '.' + tag
        dst = os.path.join(BAK, name)
        shutil.copy2(src, dst)
        wrote.append(name)

    removed = prune(list_snapshots())
    print('备份完成 (%s):' % tag)
    for w in wrote:
        print('  +', w)
    if removed:
        print('已清理旧快照(仅保留最近 %d 版):' % KEEP)
        for r in removed:
            print('  -', r)
    print('当前保留版本:', ', '.join(list_snapshots()))


if __name__ == '__main__':
    main()
