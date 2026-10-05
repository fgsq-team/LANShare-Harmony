#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 5.0.19 的「实测通过」结果写进 docs/PENDING_TEST.md。

幂等：哨兵串 '## 实测通过（2026-10-01 17:00' 已存在则直接跳过（exit 0），
      不写、不报错（避免 Bash 工具重复执行造成二次插入）。
两道断言一起上：
  assert s.count(NEW) == 0   # 新文本此前不存在（挡住「NEW 含 OLD」的嵌套重复）
  assert s.count(OLD) == 1   # 旧文本恰好一处
"""
import io
import sys

P = r'E:\lanshare-harmony\LANShareV5\docs\PENDING_TEST.md'
SENTINEL = '## 实测通过（2026-10-01 17:00'

OLD = "- **待验证**：安装 5.0.19 后同一探针应输出 `✓ 3/3 块全部收到应答`；再用 PC 实测图片与 apk。\n"

NEW = """- **实测通过（已完成，见下节）**。

## 实测通过（2026-10-01 17:00–17:06，真机 PLR-AL50 / 192.168.10.146）

### 0. 版本确认
`bm dump -n com.fgsqw.lansharev5` → 应用级 `versionCode 5000019 / versionName "5.0.19"`，
`updateTime = 2026-10-01 16:58:52`（HAP 推送于 16:58）⇒ 已装且为最新。

### 1. 1101（图片路径）——`v5_blockack_probe.mjs`，完全复刻 PC 时序

| 版本 | 探针输出 | 落盘文件 | 磁盘大小 | 内容标记 |
|---|---|---|---|---|
| **5.0.18（修复前）** | `✗ 块 1/3：发送后 6005ms 内没收到任何应答字节` | `v5_blockack_probe.bin` | **2097140** | 512/512 ✓ |
| **5.0.19（修复后）** | `✓ 通过：3/3 块全部收到应答，6291420 字节推送完成，用时 610ms` | `v5_blockack_probe(1).bin` | 6291420 | 1536/1536 ✓ |

> **磁盘实证**：修复前那份文件恰好停在 **2097140 B** —— 与用户报告的
> `2097140 / 4336019 = 48.36%` 是同一个数，即「卡在 48%」在磁盘上的直接体现。
> 标记数 512 = 恰好 1 块 ⇒ 对端确实只发了一块就停了。

设备日志（5.0.19）：
`v5 已保存 …/v5_blockack_probe(1).bin (6291420 B, 3 片, 388ms)` —— 无超时、无告警。

### 2. 1110（16 分片文件路径）——新增 `v5_seg_probe.mjs`

手工当分片发送端（每片一条 TCP，元数据帧 `long fileSize/str name/str segId/int idx/int total/long start/long len`），
每片发一块就阻塞读 1 字节。

| 规模 | 结果 | 设备日志 | 内容标记 |
|---|---|---|---|
| 4 片 × 2 块（16.8 MB） | `✓ 4/4 片全部收到逐块应答`，12/12 块 = 5，4/4 片尾 = [5, 2] | `分片全部收齐 …(16777120 B, 4 片, 637ms)` | 4096/4096 ✓ |
| **16 片 × 2 块（67.1 MB，生产规模）** | `✓ 16/16 片全部收到逐块应答，67108480 字节推送完成，用时 5008ms` | `分片全部收齐 …(67108480 B, 16 片, 1681ms)` | **16384/16384 ✓** |

吞吐 ≈ 12.8 MB/s（≈102 Mbps），16 片并发下进度单调 **50%→62%→75%→100%**，无回跳。

### 3. 内容完整性校验（新增 `verify_written.mjs`）

⚠️ **非 root 设备读不到应用沙箱**（`/data/storage/el2/base/...` → `Permission denied`）。
但本工程 **HTTP 与 v5 协议共用同一个 TCP 服务器（5856）** —— `HttpRouter` 只是
`LanService` 里的路由器（`LanService.ets:187`），不是独立监听端口，8080 根本没起。

所以直接走应用自己的下载接口把落盘文件取回来：

```
GET http://192.168.10.146:5856/file/<文件名>?path=<URL 编码的绝对路径>
```

校验方式：探针造的负载在**每块内每 4096 字节**开头写一个可识别标记
（push/seg 用 `LANSHARE-PROBE`/`LANSHARE-SEG`，blockack 用 `LANSHARE-BLOCKACK`），
其余字节为 0x00。于是「标记数」与「非零字节数」必须精确相等：

| 文件 | 大小 | 标记数 | 非零字节 | 判定 |
|---|---|---|---|---|
| `v5_seg_probe(1).bin`（4 片×2 块） | 16777120 | 4096/4096 | 49152 = 4096×12 | ✓ 零错位 |
| `v5_seg_probe(2).bin`（**16 片×2 块**） | 67108480 | **16384/16384** | 196608 = 16384×12 | ✓ 零错位 |
| `v5_blockack_probe(1).bin`（修复后 1101） | 6291420 | 1536/1536 | 26112 = 1536×17 | ✓ |
| `v5_blockack_probe.bin`（修复前 1101） | 2097140 | 512/512 | 8704 = 512×17 | ✓ |

⇒ **16 路随机写（`start + got` 偏移）零错位**，下载回来的字节与推送的逐字节一致。

### 4. ⚠️ 澄清：`SegPart` 静态 Map 的 60s 陈旧条目（**不是产品缺陷**）

如果两轮探针**用同一个 segId**，第二轮会命中第一轮遗留的 `SegPart`：
`gotIdx[]` 去重令 `counts=false` → `part.received` 不再累加 → 进度冻结在上一轮的 100%，
日志表现为 `fileSize` 与「已收 X/X」对不上（实测踩过：`fileSize=25165680` 却报 `16777120/16777120`）。
`purgeFinished()` 要 **60 秒**后才清条目。

**真实环境不会触发**：PC 端 `LANShare::sendFileParallelOne` 用
`Utils::getUUID()`（反汇编 `0x14000c273` → `QUuid::createUuid`，**随机 UUID v4**）
**每次传输现生成**一个 segId 给整个文件用，不可能重复。
⇒ 探针已改为默认带时间戳的唯一 segId（`v5_seg_probe.mjs` 第 3 节注释）。

### 5. 顺带发现（沙箱内真实文件，**未改动**）

`LANShare/其他/` 里有用户真实传输留下的痕迹：
`鹰眼守护-910-v5-无车道级-适配17控制器-60帧.apk` = **605029454 B**，
同名不同后缀共 **6 份**（= 重复尝试 6 次），另有一份 **489684992 B**（467 MB，**未完成**残件）。
这与「大文件走 1110 分片、反复失败」的现象一致 —— 本次修复正是针对它。

### 6. 本轮新增的探针/工具（`tests/live-probe/`）
- `v5_blockack_probe.mjs` —— 1101 块级应答回归探针（复刻 PC 时序）。
- `v5_seg_probe.mjs` —— 1110 分片块级应答探针（并发 N 片，每轮唯一 segId）。
- `verify_written.mjs` —— 通过 HTTP 取回落盘文件做内容标记校验。
- `list_recv.mjs` —— 列 `LANShare/其他/` 目录（拿探针文件准确名）。
- 均需 `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'`，否则设备绝对路径被 MSYS 改写。

### 7. 仍需用户本人做的一步
用 PC（`E:\\LANShare\\LANShare-PC(新)\\LANShare\\LANShare.exe`）真实发一张图片 + 一个 apk，
确认进度不再停在 48%、落盘大小与原始一致（这是唯一无法由探针替代的端到端确认）。
"""


def main():
    s = io.open(P, encoding='utf-8', newline='').read()
    if SENTINEL in s:
        print('ALREADY APPLIED — skip')
        return 0

    assert s.count(NEW) == 0, '新文本已存在，拒绝重复插入'
    assert s.count(OLD) == 1, f'旧锚点命中 {s.count(OLD)} 次（应为 1）'

    s2 = s.replace(OLD, NEW, 1)

    # 复核：新文本恰好 1 份，旧文本 0 份
    assert s2.count(NEW) == 1, '插入后新文本份数异常'
    assert s2.count(OLD) == 0, '插入后旧锚点仍存在'

    # 行尾规范化：工程 .md 目前为 LF
    assert '\r\n' not in s, '源文件出现 CRLF，需先确认行尾'

    io.open(P, 'w', encoding='utf-8', newline='').write(s2)
    print(f'OK — 写入 {len(s2) - len(s)} 字节，文件现 {len(s2)} 字节')
    return 0


if __name__ == '__main__':
    sys.exit(main())
