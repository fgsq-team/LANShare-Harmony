# -*- coding: utf-8 -*-
"""给工作区长期记忆补一节「源码批量补丁的固定做法」。追加型写入，幂等。"""
import sys

P = r"E:\lanshare项目\.workbuddy\memory\MEMORY.md"
SENT = "## 源码批量补丁（AI 改代码的固定做法"

TEXT = '''## 源码批量补丁（AI 改代码的固定做法，2026-10-01 订立）

本工程源码含大量中文长注释，**中文锚点的 Edit 工具在本机反复失败**，
统一改成「写 python 补丁脚本 → 运行」：

- 脚本先放在工程根临时位置，跑完归档到 `docs/patch_scripts/`。
- 读文件：`open(p, encoding='utf-8', newline='')`，把 `\\r\\n` 规范化成 `\\n`；
  写回时按原行尾还原（工程源文件目前都是 LF）。
- **幂等**：脚本开头按哨兵串判断「是否已打过」，打过就**逐文件** SKIP；
  先全部校验 + 在内存里构造结果，最后统一落盘（任一失败则一个字都不写）。

### ⚠️ 头号教训：行号区间必须**完整包住整个语法块**

5.0.15 那次构建直接失败（20 个 `10505001`），根因是补丁把 `import` 区写成 `(25, 27)`，
而真实区段是 **25~28 四行** → 删掉了 `common` / `fileIo`、又留下重复的 `deviceInfo`。
同一脚本里 `dropDevice` 也犯过一次（区间包住整个方法，替换块却只写了前半段）。

两道保险只能挡住一部分：

| 保险 | 挡住什么 | 挡不住什么 |
|---|---|---|
| `expect` 关键字（区间内必须出现指定串） | 行号整体偏移 | 区间**本身划小了**（行号没错） |
| 括号增量一致（`{` − `}`） | 少写收尾大括号 | `import { X } from` 这类**括号成对**的整行丢失 |

**规则**：区间边界从**语法块的起止**推 —— 「import 区」= 第一个 import 到最后一个 import，
不是「到第 N 个 import 为止」。改完立刻 `grep` 被删/新增的符号，确认引用数为 0 / 等于预期。
（.md 这类无花括号的文本更好办：直接按**内容锚点**定位，别用行号。）

### 构建与验证

- **用 PowerShell 工具跑 `build.cmd`** —— Bash 里调 `cmd.exe` 会被安全策略拦。
  `build.cmd` 成功会自动 `push.cmd` 推手机（USB + WiFi 双通道）。
- **每次都要解包 HAP 验「改动真的编进去了」**：读 `ets/modules.abc`，
  搜本轮新增的中文字符串或方法名。`UP-TO-DATE` **不能**用来判断"未重编"。
- 版本号在 `AppScope/app.json5`，约定 `versionCode = 5000000 + 小版本`（5.0.15 → 5000015）；
  push.cmd 按 `versionName` 自动命名手机端文件（`LANShareV5-<ver>.hap`）。
'''

def main():
    s = open(P, "r", encoding="utf-8", newline="").read()
    if SENT in s:
        print("[SKIP] 该节已存在")
        return 0
    out = s.rstrip("\n") + "\n\n" + TEXT
    open(P, "w", encoding="utf-8", newline="").write(out)
    print("[OK] 已追加，MEMORY.md 现 %d 字符" % len(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
