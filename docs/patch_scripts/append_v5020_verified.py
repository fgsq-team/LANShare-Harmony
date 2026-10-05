# -*- coding: utf-8 -*-
"""5.0.20 实测结果追加（哨兵幂等）。"""

import io
import os
import sys

DOC = r'E:\lanshare-harmony\LANShareV5\docs\PENDING_TEST.md'
LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-01.md'
S_DOC = '### ✅ 5.0.20 实测通过（2026-10-01 17:20'
S_LOG = '### 5.0.20 实测验证（2026-10-01 17:20）'


def read(p):
    with io.open(p, 'r', encoding='utf-8', newline='') as f:
        s = f.read()
    crlf = '\r\n' in s
    return s.replace('\r\n', '\n'), crlf


def write(p, s, crlf):
    if crlf:
        s = s.replace('\n', '\r\n')
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


D = '''### ✅ 5.0.20 实测通过（2026-10-01 17:20，设备已装 `com.fgsqw.lanshare` / versionCode 5000020）

> 设备上 `com.fgsqw.lansharev5` 已不存在，只剩新包名 —— 旧包与新包不会并存，无需额外卸载。

**A. 多文件（本轮的修复目标）**

| 用例 | 修复前 5.0.19 | 修复后 5.0.20 |
|---|---|---|
| 1 文件 × 3 块 | ✅（本来就正常） | ✅ `[AGREE][5,5,5,5]` |
| 2 文件 × 2 块 | ✗ 文件 2 `v5 接收字节数不符: 0 != 4194280`；应答 `[5,5,5,6]` | ✅ `[AGREE][5,5,5,5,5,5]` |
| 3 文件 × 3 块 | —（必失败） | ✅ `[AGREE][5×12]`，3 条 `v5 已保存` 各 6291420 B |

→ 应答序列里的 `5` 全部来自对端：**9 个块级 ack + 3 个文件级 ack ＝ 12 个**，与 3×3 块完全对上。

**B. 回归（确认没修出新问题）**

| 用例 | 结果 |
|---|---|
| 单文件 × 3 块 | ✅ 通过（用户原始场景：PC 发图片） |
| 块级应答（5.0.19 修复项） | ✅ 3/3 块，6291420 B / 370ms |
| 1110 分片 16 片并发 | ✅ 16/16 片，67108480 B / 4959ms ≈ 102 Mbps |

**C. 内容级校验**（走应用自带的 `GET /file/<名>?path=<绝对路径>` 把落盘文件取回）

| 文件 | 大小 | 标记数 | 非零字节 | 判定 |
|---|---|---|---|---|
| `v5_multi_f1(1).bin` | 6291420 | **1536/1536** | 26112 | ✓ |
| `v5_multi_f2(1).bin` | 6291420 | **1536/1536** | 26112 | ✓ |
| `v5_multi_f3.bin` | 6291420 | **1536/1536** | 26112 | ✓ |

每块内每 4096 字节埋一个标记、其余填 `0x00` ⇒ `1536 × 17 = 26112` 精确相等。
**关键判据：每个文件只匹配到自己的标记串**（`LANSHARE-MULTI-f1` / `-f2` / `-f3` 互不串扰）
⇒ 那 12 字节 FS_END 帧既没被写成数据、也没串到下一条记录里，**文件之间零错位**。

**D. 设备日志**（全程无 `不符` / `失败` / `超时` / `错位` / `FS_CLOSE`）

```
I A0F5F0/com.fgsqw.lanshare/V5Transfer: v5 已保存 .../v5_multi_f1(1).bin (6291420 B, 3 片, 358ms)
I A0F5F0/com.fgsqw.lanshare/V5Transfer: v5 已保存 .../v5_multi_f2(1).bin (6291420 B, 3 片, 224ms)
I A0F5F0/com.fgsqw.lanshare/V5Transfer: v5 已保存 .../v5_multi_f3.bin    (6291420 B, 3 片, 210ms)
```
（注意 TAG 前缀已变成 `com.fgsqw.lanshare/` —— 新包名生效）

**唯一剩余的手工确认**：用 PC 真实操作界面，一次选 2~3 张图片 / 多个文件一起发。
探针能复刻时序但驱不动 PC GUI，这一步仍建议你随手验一下。

'''

L = '''### 5.0.20 实测验证（2026-10-01 17:20）

- 设备已装 `com.fgsqw.lanshare` / versionCode 5000020；`com.fgsqw.lansharev5` 已不存在
  （新旧包名不并存，无需再手动卸载旧包）。
- **修复目标验证通过**：`v5_multifile_probe.mjs`
  - 2 文件 × 2 块：修复前 `[AGREE][5,5,5,6]` + `0 != 4194280`；修复后 `[AGREE][5,5,5,5,5,5]` ✓
  - 3 文件 × 3 块：`[AGREE][5×12]`，3 条 `v5 已保存` 各 6291420 B ✓
- **回归全绿**：单文件 × 3 块 ✓ / 块级应答 3/3（370ms）✓ / 1110 分片 16 片 16/16（4959ms）✓
- **内容级校验**（HTTP 取回沙箱文件）：3 个文件各 1536/1536 标记、非零 26112 = 1536×17，
  且**每个文件只匹配自己的标记串**（f1/f2/f3 不串扰）⇒ FS_END 帧零污染、文件间零错位。
- 设备日志全程无 `不符/失败/超时/错位/FS_CLOSE`。

'''


def append(p, block, sent, what):
    s, crlf = read(p)
    if sent in s:
        print('SKIP %s（已存在）' % what)
        return
    if not s.endswith('\n'):
        s += '\n'
    s += block
    write(p, s, crlf)
    print('OK   %s 已追加（%d 字符）' % (what, len(block)))


append(DOC, D, S_DOC, 'PENDING_TEST.md 实测结果')
append(LOG, L, S_LOG, '工作区日志 实测结果')

s, _ = read(DOC)
assert s.count(S_DOC) == 1
s, _ = read(LOG)
assert s.count(S_LOG) == 1
print('自检：哨兵各 1 次 ✓')
