#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 5.1.57 的规则追加到 MEMORY.md（幂等 sentinel + LF）

⚠️ 教训：MEMORY.md 是**编号列表**，用「14.」开头的新条目会与既有第 14 条
   sentinel 计数冲突（`count(sentinel) == 1` 断言拦住了自己）。
   ⇒ **追加到末尾并给一个不会撞号的小节标题**，别复用编号。
"""
import io
import sys

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'

SENTINEL = '## ★ 命名与去重策略（5.1.57）'

ADD = """
## ★ 命名与去重策略（5.1.57）
- ★★ **「统一命名」要以「系统最终产物」为准，不要自己另发明一套**：
  vivi 观察到相册把 `abc.1` 存成 `abc_1.jpg` / `abc_1_1.jpg` / `abc_1_2.jpg` ⇒ 要求沙箱也这么改
  （**stem 里所有 `.` → `_`，只留新增的那一个后缀点**）。
  ⇒ ★ **判「这个功能该怎么表现」时去看用户最终会看到的那一层的实际行为**，
  与之对齐；自造一套「更干净但与实际产物不一致」的规则反而制造认知割裂。
- ⚠️★ **顺序不可颠倒**：判「末尾后缀对不对」必须用**原始名**（仍带点），
  换下划线只发生在**决定改名之后** —— 否则 `a.b.jpg` 被算成「后缀 `_jpg`」⇒ 每次都误判要改。
- ⚠️ **别复用 MEMORY.md 里的编号**（它是编号列表，sentinel 计数会撞号 ⇒ 自己的断言拦自己）。
  追加条目用独立小节标题。
- 验证脚本 `docs/patch_scripts/verify_ext_rule_5157.py`（13 用例，含等价组/复制后缀/非媒体/退化stem）。
"""


def main():
    s = io.open(MEM, 'r', encoding='utf-8').read()
    if SENTINEL in s:
        print('ALREADY APPLIED')
        return 0
    s2 = s.rstrip('\n') + '\n' + ADD
    assert s2.count(SENTINEL) == 1
    io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK MEMORY.md 已追加 5.1.57')
    return 0


if __name__ == '__main__':
    sys.exit(main())