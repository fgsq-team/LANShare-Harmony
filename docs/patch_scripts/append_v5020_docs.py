# -*- coding: utf-8 -*-
"""
5.0.20 文档 + 工作区记忆追加（哨兵幂等，可重复执行）

只做「追加」，所以每条写入前都先判重；已存在则整段跳过。
"""

import io
import os
import sys

DOC = r'E:\lanshare-harmony\LANShareV5\docs\PENDING_TEST.md'
WS_LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-01.md'

SENT_DOC = '## 🟢 待测：LANShare-5.0.20'
SENT_LOG = '### 5.0.20 —— 多文件结束帧 + 去 V5 改名（2026-10-01 17:17）'


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


DOC_BLOCK = '''## 🟢 待测：LANShare-5.0.20 —— **多文件传输第 2 个起失败（已修）+ 包名/应用名去掉 V5**（2026-10-01 17:17 构建）

| 项 | 值 |
|---|---|
| 本地 HAP | `E:/lanshare-harmony/LANShareV5/entry/build/default/outputs/default/entry-default-unsigned.hap`（**2113072 B**） |
| 手机落地 | ✅ 已推送 17:17 → `Download/LANShare-5.0.20.hap`（2113072 B，rc=0） |
| **bundleName** | ⚠️ `com.fgsqw.lansharev5` → **`com.fgsqw.lanshare`** —— 这是**另一个应用**，先卸载旧的，别让两个同时跑（都监听 5856） |
| 应用名 | `LANShareV5` → **`LANShare`**（桌面图标名 / 任务卡名） |
| versionCode / versionName | `5000020` / `5.0.20` |
| modules.abc | 842140 B（5.0.19 = 841104 B，**+1036 B**） |
| 文件名 | HAP 落到手机叫 `LANShare-<版本>.hap`（版本号保留，V5 去掉） |

### 修的是什么

**PC 一次发 ≥2 个文件，第 2 个起必然失败。**（单文件正常，所以之前一直没暴露）

V5 协议里，**发送端在每个文件的数据块之后都会补发一帧 12 字节结束帧**
（`head[0]=2 FS_END`、`arg=0`、`len=0`）：

| 端 | 取证 |
|---|---|
| PC `baseSend` | `0x1400223ad: cmpq 80(%rax),%r14 ; je 0x1400224c0`（已发满）→ `0x1400224c0: movl $2,%edx ; callq DataEnc::setByteCmd` → `send(data,len,0)`（未发满走 `$3` = FS_CLOSE） |
| 1.35 `LANService.D` | `dump_D.txt` 320-343：`setInt(v0,-1,0)` → `setInt(v0,0,4)` → `v0[0] = (发满 ? 2 : 3)` → `setInt(v0,0,8)` → `write(v0,0,12)` |
| 本机 `sendPlain` | 本来就发：`endFrame.setStreamCmd(LCmd.FS_END)` |

**而 PC 收端 `baseRecv` 就是靠这一帧判文件结束**：
`140022dd1: cmpb $1,%al ; jne 140022f48`（非数据帧）→ `140022f48: cmpb $2,%al ; je 140022f10`（FS_END → 退出，**不回 ack**）。

本机 `recvBody` 的循环是 `while (subTotal < item.length)` —— **收满即跳出，从不读这一帧** →
它留在 TCP 缓冲区 → 被**下一个文件的 recvBody** 当帧头读走 → `break` → `0 != item.length`
→ 回 `FS_BREAK(6)` → 整体失败。

### 修复前真机复现（5.0.19）

```bash
node tests/live-probe/v5_multifile_probe.mjs 192.168.10.146 5856 2 2 8000
#   文件 1：块1 ack=5、块2 ack=5  → 发 FS_END 帧
#   文件 2：块1 ack=5（★错位吃到的文件级 ack）→ 连接被关闭 → 块2 ack=6 (FS_BREAK)
#   应答序列 = [AGREE 12B][5, 5, 5, 6]
```

设备日志：
```
v5 已保存 .../v5_multi_f1.bin (4194280 B, 2 片, 259ms)
v5 接收字节数不符: 0 != 4194280（.../v5_multi_f2.bin）      ← 0 就是「被 FS_END 帧顶掉」
```

### 改了什么

`V5Transfer.recvBody()` 在 `while` 循环**之外**补一段（收满后才执行）：

```ts
if (subTotal === item.length) {
  const tail = await chan.readExactly(12, END_FRAME_WAIT_MS);   // 5s
  if (tail !== null) {
    const tcmd = tail[0] & 0xFF;
    if (tcmd === LCmd.FS_END)      { /* 吃掉；len>0 也一并吃掉 */ }
    else if (tcmd === LCmd.FS_CLOSE) { /* 对端判失败，按已收字节落地 */ }
    else { return false; }          // 其它命令 = 帧流错位，明确报错
  }
  // tail === null（对端不发结束帧的旧实现）→ 回退到按字节数判结束
}
```

**顺序不能反**：循环内最后一块的块级 ack 已经回过，对端才会发这帧。
先等帧、后回 ack 就是双方对等死锁。

### 待你验证

1. **先卸载手机上旧的 `com.fgsqw.lansharev5`**（不卸载也行，但两个都开就会抢 5856）。
2. 装 `Download/LANShare-5.0.20.hap`，确认桌面图标名是 **LANShare**。
3. 重新跑多文件探针，预期 **2/2 个文件全落盘**：
   ```bash
   node tests/live-probe/v5_multifile_probe.mjs 192.168.10.146 5856 2 2 8000
   # 预期：✓ 通过：2 个文件全部按 PC 时序发完并逐块收到应答
   hdc shell "hilog -x -T V5Transfer" | grep "v5 已保存"   # 应有 2 条，各 4194280 B
   ```
4. 用 PC 实测：**一次选中 2~3 张图片 / 2 个文件一起发**，确认不再只成功第 1 个。
5. 单文件回归：PC 发 1 张图，确认仍正常（别修出回归）。

> ⚠️ 应用数据不会从旧包迁移（换了 bundleName 就是另一个应用），聊天记录是空的，属正常。

'''

LOG_BLOCK = '''### 5.0.20 —— 多文件结束帧 + 去 V5 改名（2026-10-01 17:17）

- 交接遗留闭环：`recvBody` 不吃对端 FS_END 结束帧 → PC 一次发 ≥2 个文件第 2 个起失败。
- 取证（三端一致，非推断）：PC `baseSend` `0x1400224c0: movl $2,%edx; setByteCmd` → `send`；
  PC `baseRecv` `0x140022f48: cmpb $2,%al; je 140022f10`（读到 FS_END 退出且不回 ack）；
  1.35 `LANService.D` `dump_D.txt` 320-343 同构 12 字节结束帧；本机 `sendPlain` 本来就发。
- 真机复现（5.0.19）：`v5_multifile_probe.mjs` 2 文件 × 2 块 → 文件 1 成功、文件 2
  `v5 接收字节数不符: 0 != 4194280`；应答序列 [AGREE][5,5,5,6]。
- 修复：`recvBody` 在 while **之外**补读一帧（`END_FRAME_WAIT_MS = 5000`），
  收满后才执行；FS_END/FS_CLOSE 都吃掉，其它命令判错位。顺序必须在块级 ack 之后。
- 改名：bundleName `com.fgsqw.lansharev5` → `com.fgsqw.lanshare`；应用名 LANShareV5 → LANShare；
  push.cmd 目标名 `LANShare-%VER%.hap`。**工程目录仍叫 LANShareV5**（push.cmd 的 PROJECT_PATH 不动）。
- 版本 5.0.20 / 5000020，全量重建 33/33，HAP 2113072 B，modules.abc +1036 B，
  已推送 `Download/LANShare-5.0.20.hap`。
- ⚠️ 教训：本轮补丁脚本 `patch_v5020_*.py` 第一版**边算边写**，在 push.cmd 锚点断言失败时
  前 4 个文件已落盘 → 只能从 `.backup_v5020/` 全量回滚重做。
  **补丁脚本必须「全部校验 + 内存构造 → 最后统一落盘」**，这不是新规则，是本工程铁律。
  第二版已改成 `_doc/_orig` 内存工作区 + 末尾一次性 write，并逐文件幂等。
- 待用户：卸载旧包 → 装 5.0.20 → 跑多文件探针（预期 2/2）+ PC 实测一次发多张图。

'''


def append(p, block, sentinel, what):
    s, crlf = read(p)
    if sentinel in s:
        print('SKIP %s（已存在）' % what)
        return False
    if not s.endswith('\n'):
        s += '\n'
    s += block
    write(p, s, crlf)
    print('OK   %s 已追加（%d 字符）' % (what, len(block)))
    return True


append(DOC, DOC_BLOCK, SENT_DOC, 'PENDING_TEST.md')
append(WS_LOG, LOG_BLOCK, SENT_LOG, '工作区日志 2026-10-01.md')

# 复跑判重自检
s, _ = read(DOC)
assert s.count(SENT_DOC) == 1, 'PENDING_TEST.md 哨兵重复'
s, _ = read(WS_LOG)
assert s.count(SENT_LOG) == 1, '工作区日志哨兵重复'
print('自检：两处哨兵各 1 次 ✓')
