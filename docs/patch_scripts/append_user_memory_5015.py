# -*- coding: utf-8 -*-
"""在用户级 MEMORY.md 的「中文锚点 Edit 工具」那条下面补一行 python 补丁脚本的硬规则。"""
import sys

P = r"C:\Users\vivi\.workbuddy\MEMORY.md"
ANCHOR = "- 中文锚点 Edit 工具在本环境反复失败"
SENT = "完整包住整个语法块"
ADD = [
    "  - ⚠️ python 补丁脚本按**行号区间**替换时, 区间必须**完整包住整个语法块**",
    "    (少覆盖一行 = 静默删掉代码, 到编译期才报). 配三道保险: 区间内 `expect` 关键字校验、",
    "    括号增量一致、哨兵幂等; 且**先全部校验再统一落盘**。改完 grep 被删/新增符号确认引用数。",
]


def main():
    s = open(P, "r", encoding="utf-8", newline="").read()
    if SENT in s:
        print("[SKIP] 该规则已存在")
        return 0
    lines = s.split("\n")
    idx = None
    for i, ln in enumerate(lines):
        if ln.startswith(ANCHOR):
            idx = i
            break
    if idx is None:
        raise AssertionError("未找到锚点行: %s" % ANCHOR)
    # 若下一行已经是我们的子项则跳过
    out = lines[:idx + 1] + ADD + lines[idx + 1:]
    open(P, "w", encoding="utf-8", newline="").write("\n".join(out))
    print("[OK] 已在第 %d 行后插入 %d 行" % (idx + 1, len(ADD)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
