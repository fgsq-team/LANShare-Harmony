#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 5.0.19 实测结果追加到工作区日志（哨兵幂等，重复执行直接跳过）。"""
import io
import sys

P = r'E:\lanshare项目\.workbuddy\memory\2026-10-01.md'
SENTINEL = '## 2026-10-01 5.0.19 实测通过'

BLOCK = """
## 2026-10-01 5.0.19 实测通过（真机 PLR-AL50 / 192.168.10.146）

- 手机已装 5.0.19。`bm dump -n com.fgsqw.lansharev5` 里 **ability 层的 `versionName` 恒为 `""`**，
  要看**应用级**那两行（`versionCode 5000019 / versionName "5.0.19"`，`updateTime 16:58:52`）才准。
- **1101（图片路径）前后对照**（`tests/live-probe/v5_blockack_probe.mjs`）：
  - 5.0.18：`✗ 块 1/3 无应答`，磁盘留下 **2097140 B**（= 恰好 1 块，与「卡 48%」同数）。
  - 5.0.19：`✓ 3/3 块应答`，6291420 B / 610ms；日志 `v5 已保存 … (6291420 B, 3 片, 388ms)`。
- **1110（16 分片路径）**：新增 `tests/live-probe/v5_seg_probe.mjs`（手工当分片发送端）。
  4 片×2 块 与 **16 片×2 块（67.1 MB）** 均 100% 通过；16 片吞吐 ≈12.8 MB/s（≈102 Mbps），
  进度单调 50→62→75→100%。日志 `分片全部收齐 …(67108480 B, 16 片, 1681ms)`。
- **★ 内容完整性校验（新手段，很值钱）**：非 root 读不到应用沙箱（`Permission denied`），但
  **本工程 HTTP 与 v5 协议共用同一个 TCP 端口 5856** —— `HttpRouter` 只是 `LanService` 里的
  路由器（`LanService.ets:187`），**没有独立的 8080**（实测 8080 ECONNREFUSED）。
  于是直接 `GET http://<ip>:5856/file/<名>?path=<URL编码绝对路径>` 就能把落盘文件取回来。
  探针在每块内每 4096 字节写标记、其余为 0x00 ⇒「标记数 × 标记长 = 非零字节数」必须严格相等。
  实测 16 片×2 块 = **16384/16384**、非零 196608 = 16384×12 ⇒ 16 路随机写偏移**零错位**。
  ⚠️ 跑这类脚本必须 `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'`，否则设备绝对路径被改写成
  `C:/Users/.../PortableGit/.../data/storage/...`，请求必然失败。
- **新发现（非缺陷）**：`SegPart` 存在静态 Map、以 segId 为键，`purgeFinished()` 要 **60s** 才清。
  探针复用同一 segId 时第二轮命中陈旧条目 → `gotIdx` 去重令 `counts=false` →
  `part.received` 不再累加 → 进度冻结在上一轮 100%（日志里 fileSize 与「已收 X/X」对不上，
  实测 `fileSize=25165680` 却报 `16777120/16777120`）。
  真实环境不会触发：PC `LANShare::sendFileParallelOne` 用 `Utils::getUUID()`
  （反汇编 0x14000c273 → `QUuid::createUuid`，随机 UUID v4）**每次传输现生成**。
  ⇒ 探针已改成每轮唯一 segId。
- **沙箱里的真实痕迹（未改动）**：`鹰眼守护-910-v5-…60帧.apk` = 605029454 B，同名共 **6 份**
  （重复尝试 6 次）+ 一份 **489684992 B** 未完成残件 —— 正是 1110 大文件反复失败的现场。
- 新增工具：`v5_seg_probe.mjs` / `verify_written.mjs` / `list_recv.mjs`；
  文档 `docs/PENDING_TEST.md` 追加「实测通过」全节（幂等脚本
  `docs/patch_scripts/patch_v5019_pending_test_results.py`）。
- **待用户本人**：PC 实测发 1 张图片 + 1 个 apk 做最终端到端确认。
"""


def main():
    s = io.open(P, encoding='utf-8', newline='').read()
    if SENTINEL in s:
        print('ALREADY APPLIED — skip')
        return 0
    assert s.count(BLOCK) == 0, '块已存在'
    assert '\r\n' not in s, '源文件出现 CRLF'
    with io.open(P, 'a', encoding='utf-8', newline='') as f:
        f.write(BLOCK)
    print('OK — 追加 %d 字节' % len(BLOCK))
    return 0


if __name__ == '__main__':
    sys.exit(main())
