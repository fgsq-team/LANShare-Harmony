# -*- coding: utf-8 -*-
"""
MEMORY.md（长期项目约定）5.0.20 更新 —— 幂等，可重复执行。

改动：
  ① V5 工程条目：bundleName 已改为 com.fgsqw.lanshare、应用名 LANShare
  ② 推送文件名 LANShare-<ver>.hap
  ③ 探针清单补 v5_multifile_probe.mjs
  ④ 「已知未修」条目 → 换成「V5 文件结束帧（5.0.20 定案）」整节
  ⑤ 补丁纪律：把「最后统一落盘」的翻车实测写进去
"""

import io
import os
import sys

P = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
SENT = '### V5 文件结束帧（5.0.20 定案）'


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


def sub_once(s, old, new, what):
    n = s.count(old)
    assert n == 1, '[%s] 命中 %d 次（期望 1）:\n---\n%s\n---' % (what, n, old[:200])
    return s.replace(old, new, 1)


s, crlf = read(P)

if SENT in s:
    print('ALREADY APPLIED -> skip')
    sys.exit(0)

# ---------------------------------------------------------------- ① + ②
s = sub_once(
    s,
    '- **V5 工程（2026-10-01 新增）**：`E:\\lanshare-harmony\\LANShareV5\\`，兼容局域网互传 1.35 修改版\n'
    '  （v5 协议，与 v4 并行共存、按首 4 字节分流）。bundleName `com.fgsqw.lansharev5`，\n'
    '  应用名 LANShareV5，推送名 `LANShareV5.hap`（与原版 HAP 并存，不互相覆盖）。\n',
    '- **V5 工程（2026-10-01 新增）**：`E:\\lanshare-harmony\\LANShareV5\\`，兼容局域网互传 1.35 修改版\n'
    '  （v5 协议，与 v4 并行共存、按首 4 字节分流）。\n'
    '  ⚠️ **5.0.20 起已改名**（vivi 要求去掉 V5）：bundleName `com.fgsqw.lansharev5` →\n'
    '  **`com.fgsqw.lanshare`**；应用名 → **`LANShare`**；推送名 → **`LANShare-<版本>.hap`**。\n'
    '  查版本 / 卸载都用**新** bundleName；旧的 `com.fgsqw.lansharev5` 是**另一个应用**，\n'
    '  两者都监听 5856 → **必须卸载旧的**，不能同时跑。\n'
    '  换包名 = 应用数据不迁移（聊天记录清空），属预期。\n',
    '① V5 工程条目（bundleName / 应用名）',
)

# ---------------------------------------------------------------- ⑤ 补丁纪律
s = sub_once(
    s,
    '- **幂等**：脚本开头按哨兵串判断「是否已打过」，打过就**逐文件** SKIP；\n'
    '  先全部校验 + 在内存里构造结果，最后统一落盘（任一失败则一个字都不写）。\n',
    '- **幂等**：脚本开头按哨兵串判断「是否已打过」，打过就**逐文件** SKIP；\n'
    '  先全部校验 + 在内存里构造结果，最后统一落盘（任一失败则一个字都不写）。\n'
    '- ⚠️ **「最后统一落盘」必须真的做到**（5.0.20 实测翻车）：第一版 `patch_v5020_*.py`\n'
    '  写成 `read → edit → write` **逐文件落盘**，第 6 步 push.cmd 的注释锚点少了一个空格\n'
    '  → `AssertionError` 时**前 5 个文件已经写进磁盘了**，只能从 `.backup_v5020/` 全量回滚重做。\n'
    '  正确形态：`_doc` / `_orig` 两张内存表 → 所有 `edit()` 只改内存 → 末尾一次性 `write()`。\n'
    '  落盘前还要 `assert _doc[p][0] != _orig[p]` 才算「改了」，空改动不写。\n'
    '- **锚点按原文件逐字抄**（含空格数）：`REM  apart` 与 `REM apart` 差一个空格就断言失败。\n'
    '  先 `grep -n "关键字" 文件 | cat -A` 看不可见字符再写锚点，别凭记忆。\n',
    '⑤ 补丁纪律（延迟落盘 + 锚点逐字）',
)

# ---------------------------------------------------------------- ③ 探针清单
s = sub_once(
    s,
    '- 回归探针：`tests/live-probe/v5_blockack_probe.mjs`（复刻 PC 时序）/\n'
    '  `v5_push_probe.mjs`（零应答，测接收管线上限）。\n',
    '- 回归探针：`tests/live-probe/v5_blockack_probe.mjs`（复刻 PC 时序）/\n'
    '  `v5_push_probe.mjs`（零应答，测接收管线上限）/\n'
    '  `v5_multifile_probe.mjs`（**多文件**，专门暴露「每文件结束帧」这类只在 N≥2 时现形的边界缺陷）。\n',
    '③ 探针清单',
)

# ---------------------------------------------------------------- ④ 新节
s = sub_once(
    s,
    '- **已知未修**：`recvBody` 收满即跳出，不吃对端补发的 `FS_END` 帧 → PC 一次发 ≥2 个文件时第 2 个失败。\n',
    '- ~~已知未修~~（**5.0.20 已修**，见下节）。\n'
    '\n'
    '### V5 文件结束帧（5.0.20 定案）—— 每个文件收满后必须再消费一帧 FS_END\n'
    '\n'
    '- **发送端在「每个文件」的数据块之后补发一帧 12 字节结束帧**：`head[0]=2 (FS_END)`、\n'
    '  `head[4..7]=arg=0`、`head[8..11]=len=0`（未发满则 `3` = FS_CLOSE）。\n'
    '  - PC `baseSend`：`1400223ad: cmpq 80(%rax),%r14 ; je 1400224c0`（已发满）→\n'
    '    `movl $2,%edx ; callq DataEnc::setByteCmd` → `send(data,len,0)`。\n'
    '  - 1.35 `LANService.D`（`docs/forensics/dump_D.txt` 320-343）：`setInt(v0,-1,0)` →\n'
    '    `setInt(v0,0,4)` → `v0[0]=(发满?2:3)` → `setInt(v0,0,8)` → `write(v0,0,12)`。\n'
    '  - 本机 `sendPlain` 本来就发（`endFrame.setStreamCmd(LCmd.FS_END)`）。\n'
    '- **PC 收端 `baseRecv` 就是靠它判文件结束**：`140022f48: cmpb $2,%al ; je 140022f10`\n'
    '  → 退出循环，且**不回 ack**。\n'
    '- 旧 `recvBody` 用 `while (subTotal < item.length)` **收满即跳出**，从不读它 →\n'
    '  被下一个文件的 recvBody 当帧头读走 → `0 != item.length` → 回 `FS_BREAK(6)` →\n'
    '  **PC 一次发 ≥2 个文件时第 2 个起必失败**（单文件正常，所以长期没暴露）。\n'
    '  真机复现（5.0.19）：`v5 接收字节数不符: 0 != 4194280（v5_multi_f2.bin）`。\n'
    '- 5.0.20 修法：while **之外**补读一帧（`END_FRAME_WAIT_MS = 5000`），\n'
    '  `FS_END` / `FS_CLOSE` 都吃掉、其它命令判「帧流错位」并返回 false；\n'
    '  顺序**必须**在最后一块的块级 ack 之后 —— 反了就是双方对等死锁。\n'
    '  超时（对端不发结束帧的旧实现）→ 回退到按字节数判结束，功能仍正确。\n'
    '- ★ **方法论：单条记录通过 ≠ 多条记录通过。** 协议里「每记录结束帧 / 每记录分隔符」\n'
    '  这类边界只在 **N ≥ 2** 时现形；验收必须跑 N≥2 的用例，别只用单文件回归。\n',
    '④ 已知未修 → 文件结束帧整节',
)

write(P, s, crlf)

# 自检
t, _ = read(P)
assert SENT in t, '新节未写入'
assert 'com.fgsqw.lanshare`' in t, 'bundleName 未更新'
assert 'LANShare-<版本>.hap' in t, '推送名未更新'
assert 'v5_multifile_probe.mjs' in t, '探针清单未更新'
assert '_doc` / `_orig' in t or '_doc' in t, '补丁纪律未更新'
assert '已知未修**：`recvBody`' not in t, '旧的「已知未修」仍在'
print('OK - MEMORY.md 已更新（5 处），自检全过')
