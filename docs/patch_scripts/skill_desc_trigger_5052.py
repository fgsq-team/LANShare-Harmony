# -*- coding: utf-8 -*-
"""给 skill 的 description 补 5.0.52 相关触发词（幂等：含哨兵即 SKIP）。"""
import io, sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'
SENTINEL = '删一张全部提示已删除'
OLD = '「ArkUI 沉浸式适配」「鸿蒙界面排版/界面整理」时使用。'
NEW = ('「ArkUI 沉浸式适配」「鸿蒙界面排版/界面整理」'
       '「鸿蒙缩略图显示成以前的图片」「删一张全部提示已删除」「相册跳转打开的不是刚收到的那张」'
       '「一批文件共用一条记录导致串台」时使用。')

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.count(OLD) == 1, 'description 锚点未命中：%d' % s.count(OLD)
s2 = s.replace(OLD, NEW)
io.open(P, 'w', encoding='utf-8', newline='').write(s2)
print('OK: description 已补触发词，%d -> %d' % (len(s), len(s2)))
