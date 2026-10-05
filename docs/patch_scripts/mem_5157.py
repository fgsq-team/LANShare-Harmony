#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 5.1.57 的规则追加到当日日志 + MEMORY.md（幂等sentinel + LF）"""
import io
import sys

LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'

S1 = '## 5.1.57 —— 改名时把 stem 里的 `.` 换成 `_`'
S2 = '14. ★★ **「统一命名」要以「系统最终产物」为准，而不是自己另发明一套**（5.1.57）'

NOTE = """

---

## 5.1.57 —— 改名时把 stem 里的 `.` 换成 `_`

### 一、需求（vivi 2026-10-03）

「将 `abc.1` 发送三次后，相册自动给重命名为 `abc_1.jpg` / `abc_1_1.jpg` / `abc_1_2.jpg`
你也这样改名吧，把错误后缀文件原本的 `.` 都改为 `_`，只保留新添加后缀的一个。」

### 二、规则（已用 `verify_ext_rule_5157.py` 跑真实输入验证，13/13 PASS）

1. 判「末尾后缀对不对」**仍用原始名**（含点）—— `tailExt` + `sameKind` 不变；
2. **决定改名之后**，才把 stem 里所有 `.` 换成 `_`；
3. 目标名 = `<点已换下划线的 stem>.<规范后缀>`；
4. 目标已存在 ⇒ 递增 ` (2)` / ` (3)`（沿用 5.1.56）。

⚠️★ **顺序不能颠倒**：若先换下划线再判后缀，`a.b.jpg` 会被算成「后缀 `_jpg`」
⇒ 误判需要改名 ⇒ 每次都改。

### 三、关键判据（写代码前想到的）

**「相册已经这么命名了」是「我们该怎么命名」的权威依据** ——
用户看到的是相册里的结果，所以沙箱名与之对齐，
既消除多扩展名歧义，也让「相册里叫什么/沙箱里叫什么」两个答案一致。
⇒ ★ **可迁移判据：命名/去重策略要照抄「用户最终会看到的那一层的实际行为」，
不要自造一套「更干净但与实际产物不一致」的规则。**

### 四、验证用例（13 条，全部 PASS）

| 原名 |魔数 | 目标 |
|---|---|---|
| `abc.1` | jpg | `abc_1.jpg` |
| `abc.jpg.1` | jpg | `abc_jpg_1.jpg` |
| `IMG_20260929_201632.jpg.1` | jpg | `IMG_20260929_201632_jpg_1.jpg` |
| 同上（第二次） | jpg | `IMG_20260929_201632_jpg_1 (2).jpg` |
| `abc.1`（已占1~3） | jpg | `abc_1 (4).jpg` |
| `a.jpeg` | jpg | **不动**（等价组，防`a_jpeg.jpg`） |
| `扫描全能王 2026-10-01 09.47.jpg (1)` | jpg | **不动**（剥 `(1)` 后已正确） |
| `报告 v1.2.pdf` | pdf | **不动**（非媒体） |
"""

MEM_ADD = """
14. ★★ **「统一命名」要以「系统最终产物」为准，不要自己另发明一套**（5.1.57）：
    vivi 观察到相册把 `abc.1` 存成 `abc_1.jpg` / `abc_1_1.jpg` ⇒ 要求沙箱也这么改
    （stem 里所有 `.` → `_`，只留新增的那一个后缀点）。
    ⇒ **判「这个功能该怎么表现」时，去看用户最终会看到的那一层的实际行为**，
    与之对齐；自造一套「更干净但与实际产物不一致」的规则反而制造认知割裂。
    ⚠️ **顺序**：判「末尾后缀对不对」必须用**原始名**，换下划线只发生在决定改名**之后**
    ——否则 `a.b.jpg` 被算成「后缀 `_jpg`」⇒ 每次都误判要改。
    验证脚本 `docs/patch_scripts/verify_ext_rule_5157.py`（13 用例）。
"""


def append_once(path, sentinel, text):
    s = io.open(path, 'r', encoding='utf-8').read()
    if sentinel in s:
        print('ALREADY: %s' % path)
        return False
    s2 = s.rstrip('\n') + '\n' + text
    assert s2.count(sentinel) == 1
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK 追加 -> %s' % path)
    return True


def main():
    append_once(LOG, S1, NOTE)
    append_once(MEM, S2, MEM_ADD)
    return 0


if __name__ == '__main__':
    sys.exit(main())