# -*- coding: utf-8 -*-
"""5.0.18 补充：PENDING_TEST 里加上 syscap 警告的说明。"""
import io

p = r'E:\lanshare-harmony\LANShareV5\docs\PENDING_TEST.md'
s = io.open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')

old = '这是刻意取舍：为一个纯显示字段去改 `ChatMessage` 的落盘结构，代价与风险都不划算。\n'
new = (
    old
    + '\n'
    + '\u26a0\ufe0f 构建时有两条 syscap 警告：`The system capacity of this api '
    + "'media'"
    + " is not supported on all devices`"
    + '（指 `AVImageGenerator`）。手机（API 26）标准支持，**不影响**；\n'
    + '万一某台设备真不支持，表现是「缩略图一直停在灰色占位」，**播放与存相册不受影响**'
    + '（功能降级，不是崩溃）。\n'
)

assert s.count(new) == 0, 'already'
assert s.count(old) == 1, s.count(old)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new, 1))
print('已补 syscap 说明')
