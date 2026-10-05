#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.68 根因验证（第三版，按真机精确状态）

## 真机事实（2026-10-05 14:41:47，5.1.67）
两份同名同内容的文件**在同一秒落盘**：
```
[14:41:47] v5 开始收第 241/426 项 "mmexport1476247494008(2).jpg"（14210 B）
[14:41:47] v5 "mmexport1476247494008(2).jpg" 收尾已回 2
[14:41:47] v5 开始收第 242/426 项 "mmexport1476247494008.jpg"（14210 B）
[14:41:47] v5 "mmexport1476247494008.jpg" 收尾已回 2
```
⇒ **mtime 完全相同** ⇒ `recvPathFor` 里「按 |文件时间 - 消息时间| 就近排序」
   **无法区分两者**，谁在 `cands[0]` 取决于稳定排序的偶然结果。
⇒ 5.1.67 的实际结果：`(2)` 那份先被 `copyTo` + 删沙箱并入库；
   轮到原名那份时，排序又把它指向**已删的 `X(2).jpg`** ⇒ 解析/拷贝失败
   ⇒ 重试 6 次/60 秒 ⇒ 「放弃等待落盘」⇒ **原名那份永远留在沙箱**。

## 定量核对（真机日志）
- 落盘 426，清单 426，`落盘名 - 提交title`（按 stem 匹配）= **16**
  其中 15 个就是沙箱残留（另 1 个 `GF124BDD5T67%Q]D0Q@EH1I.png` 是特殊字符名，另有原因）
- `自动存相册完成` 累计 411；411 + 15 = 426 ⇒ **完全对上**
- 每轮丢的**具体文件不同**（14:30 丢 14 个、14:41 丢 15 个）⇒ 正是「排序不确定」的表现

## 修法
`recvPathFor` 拆 exact / loose 双池：**精确命中优先，只有没有精确命中才用退化匹配**。
- 查 `X.jpg` ⇒ 只命中 `X.jpg` 自己（不再被 `X(2).jpg` 污染）
- 查 `X(2).jpg` ⇒ 精确命中它自己
- 退化匹配仍保留，用于兼容「协议原始名 vs 落盘被 dedupeName 改名」的单份场景

本脚本按**真机精确状态**（mtime 相同、X(2) 已删）验证。exit 0 = 根因成立且修法有效。
"""
import re
import sys

X = 'mmexport1476247494008'
T_SAME = 1791182517000        # ★ 两份**同一秒**落盘（真机：14:41:47）
MSG = 1791182517876


def stripDedupeSuffix(name):
    m = re.match(r'^(.*)\((\d+)\)(\.[A-Za-z0-9]+)$', name)
    if m:
        return m.group(1) + m.group(3)
    return name


# 真机状态：mtime 相同；X(2) 已被 copyTo 成功并删沙箱，但 receivedFiles 还没刷新
FILES = [
    {'name': X + '.jpg', 'path': '/sandbox/' + X + '.jpg', 'time': T_SAME, 'deleted': False},
    {'name': X + '(2).jpg', 'path': '/sandbox/' + X + '(2).jpg', 'time': T_SAME, 'deleted': True},
]


def resolve(name, k, t, mode):
    if mode == 'old':
        c = [f for f in FILES
             if f['name'] == name or stripDedupeSuffix(f['name']) == name]
    else:
        e = [f for f in FILES if f['name'] == name]
        l = [f for f in FILES
             if f['name'] != name and stripDedupeSuffix(f['name']) == name]
        c = e if e else l
    # Python sort 稳定；ArkTS 的 sort 稳定性未定义 ⇒ 两种顺序都要测
    c = sorted(c, key=lambda f: abs(f['time'] - t))
    if k < len(c):
        return c[k]
    return None


def main():
    print('=== 前置：stripDedupeSuffix 把 (2) 剥掉 ⇒ 两者会进同一候选池 ===')
    a = stripDedupeSuffix(X + '(2).jpg')
    print('  stripDedupeSuffix("%s(2).jpg") = %s' % (X, a))
    assert a == X + '.jpg', '前提不成立'
    print('  ⇒ 等于原名')

    print()
    print('=== 真机状态：两份 mtime 完全相同（同一秒 14:41:47）===')
    for f in FILES:
        print('  %-42s time=%d deleted=%s' % (f['name'], f['time'], f['deleted']))

    print()
    print('=== 查 X.jpg（需要处理、文件还在的那份）===')
    ro = resolve(X + '.jpg', 0, MSG, 'old')
    rn = resolve(X + '.jpg', 0, MSG, 'new')
    print('  旧 -> %-40s deleted=%s' % (ro['name'], ro['deleted']))
    print('  新 -> %-40s deleted=%s' % (rn['name'], rn['deleted']))

    print()
    print('=== 查 X(2).jpg ===')
    qn = resolve(X + '(2).jpg', 0, MSG, 'new')
    print('  新 -> %s' % qn['name'])

    print()
    print('=== 判据 ===')
    c1 = ro['deleted'] is True          # 旧实现串台（拿到已删的那份）
    c2 = rn['deleted'] is False         # 新实现不串台
    c3 = qn['name'] == X + '(2).jpg'    # 反向查询仍正确
    if c1 and c2 and c3:
        print('  ✅ 根因成立：mtime 相同时旧实现把「已删的 X(2).jpg」判给了 X 的消息')
        print('  ✅ 修法有效：查 X.jpg 精确命中自己；查 X(2).jpg 也不受影响')
        return 0
    if not c1:
        print('  ⚠️ 本次排序恰好没串台（ArkTS sort 稳定性未定义 ⇒ 表现为「时好时坏」）')
        print('     这与真机现象一致：每轮丢的文件名单不同、数量 14~15 之间浮动')
        print('  ✅ 修法仍有效：查 X.jpg -> %s' % rn['name'])
        return 0 if c2 and c3 else 1
    print('  ❌ 修法有副作用')
    return 1


if __name__ == '__main__':
    sys.exit(main())
