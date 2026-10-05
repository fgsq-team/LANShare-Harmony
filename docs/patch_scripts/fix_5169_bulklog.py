#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.69 B：v5 接收逐项日志节流（幂等，一处改动）

## 实测依据（vivi 2026-10-05 14:52~14:53 真机，426 张）
接收阶段打出 **1708 条** v5 日志（426 项 × 4 类 + 4）：
| 日志点 | 条数 |
|---|---|
| `v5 清单[i/426] ...` | 426 |
| `v5 开始收第 i/426 项 ...` | 426 |
| `v5 "..." 已收满 N B，等待结束帧…` | 426 |
| `v5 "..." 收尾已回 2（…）` | 426 |
| 其他（收到发送请求 / 收到清单 / 收齐等） | 4 |
| **合计** | **1708** |

## 为什么这是「批量接收时卡」的真凶
`V5Transfer.receive` 的 `onLog` 在 `LanService.ets:3423` 绑的是 **`this.pushLog`**，
而 `pushLog` ⇒ `emit` ⇒ `onSnapshot` ⇒ **`refreshReceived`**
（**全量扫盘** + `rebuildRecvIndex` + `syncChatMediaPaths` + `buildChatGroups`
 三个全量重算）
⇒ **1708 次 O(n) 重建**，而此时文件列表正从 0 长到 426（每次重建的成本都在涨）。
★ 与「收尾那 1 秒」是**两件事**：收尾已优化到位，但整个接收过程被这 1708 次拖累。

## 修法：在 `onLog` 绑定处做**一条**节流包装
`v5 清单[i/n]` / `开始收第 i/n 项` / `收尾已回` 三类带**进度下标**的日志，
在 `n > V5_BULK_LOG_PLAIN(20)` 时只放行「首项 / 每 25 项 / 末项」，
其余**丢给 `Log.d`（hilog，不进 UI、不 emit）**。
- UI 日志条数：426/25×3 ≈ **51 条** + 4 ⇒ 降一个数量级
- **排障信息不丢**：hilog 里全都有；`已收满` 不带下标、无法按进度过滤 ⇒ 保留
  （但它只在真正收满时打一次，条数 = 项数，这一类不打）

⚠️ 只节流**日志落地**，不碰协议 / 流控 / 让帧任何时序
  （与 5.1.29~5.1.32 证伪的那类「帧判据」无关）。
★ **一处改动**：只包 `onLog` 这一个回调，不动 V5Transfer 的 4 个日志点
  ⇒ 零编译风险（上一版想改 4 个调用点、要补 4 个 `}`，风险高，已放弃）。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = '5.1.69 B'
REL = 'entry/src/main/ets/service/LanService.ets'

OLD = """    await V5Transfer.receive(channel, peer, count, encData !== 0, this.storage,
      (r: TransferReport) => this.onTransferReport(r),
      // 5.0.47：接收链关键事件接到 UI 日志 —— hilog 抓不到时（无线调试 Unauthorized）
      // 也能靠这行定位「多项发送卡死」卡在哪一步
      (s: string) => this.pushLog(s), pcStyleAck);"""

NEW = """    // ★★ 5.1.69 B：接收逐项日志**节流**（一处包装，V5Transfer 侧零改动）。
    //
    // 【为什么】vivi 2026-10-05 真机 426 张：接收阶段打出 **1708 条** v5 日志
    //   （426 项 × 4 类：清单/开始收/已收满/收尾 + 4 条其他）。
    //   `onLog` 原本直接接 `this.pushLog`，而 `pushLog` ⇒ **emit**
    //   ⇒ `onSnapshot` ⇒ `refreshReceived`
    //   （**全量扫盘** + rebuildRecvIndex + syncChatMediaPaths + buildChatGroups）
    //   ⇒ **1708 次 O(n) 重建**，且文件列表正从 0 长到 426（每次成本都在涨）
    //   ⇒ 这才是「批量接收时界面卡」的真凶。
    //   ★ 与「收尾那 1 秒」是两件事：收尾已优化到位，但整个接收过程被拖累。
    //
    // 【怎么节流】带进度下标的三类（`清单[i/n]` / `开始收第 i/n 项` / `收尾已回`）
    //   在 `n > V5_BULK_LOG_PLAIN(20)` 时只放行 **首项 / 每 V5_BULK_LOG_STEP(25) 项 / 末项**，
    //   其余**转发到 hilog（Log.d）**，不进 UI、不 emit ⇒ 信息不丢，只是不刷屏。
    //   `已收满 N B` 不带下标、无法按进度过滤 ⇒ 保留（它本就每项只打一次）。
    //
    // ⚠️ 只节流**日志落地**，不碰协议 / 流控 / 让帧任何时序
    //   （与 5.1.29~5.1.32 证伪的那类「帧判据」无关）。
    const bulkN: number = count;
    const bulkPlain: number = 20;
    const bulkStep: number = 25;
    await V5Transfer.receive(channel, peer, count, encData !== 0, this.storage,
      (r: TransferReport) => this.onTransferReport(r),
      // 5.0.47：接收链关键事件接到 UI 日志 —— hilog 抓不到时（无线调试 Unauthorized）
      // 也能靠这行定位「多项发送卡死」卡在哪一步
      (s: string) => {
        if (bulkN > bulkPlain && LanService.isPerItemV5Log(s)) {
          // 从日志文本里取出进度下标 i（形如 `[i/n]` 或 `第 i/n 项`）
          const i: number = LanService.progressIndexOf(s);
          if (i > 0 && i !== 1 && i !== bulkN && (i % bulkStep) !== 0) {
            Log.d(TAG, s);      // 只进 hilog
            return;
          }
        }
        this.pushLog(s);
      }, pcStyleAck);"""

# 附带的两个静态辅助
HELPER = """
  /**
   * ★ 5.1.69 B：这条 v5 日志是不是「逐项」日志（带进度下标，可按进度节流）。
   * 判据：含 `清单[i/`、`开始收第 i/`、`收尾已回` 三种形态之一。
   */
  private static isPerItemV5Log(s: string): boolean {
    return s.indexOf('清单[') >= 0
      || s.indexOf('开始收第') >= 0
      || s.indexOf('收尾已回') >= 0;
  }

  /**
   * ★ 5.1.69 B：从逐项日志文本里取进度下标 i。
   * 形态：`v5 清单[37/426] ...` / `v5 开始收第 37/426 项 ...`
   * ⚠️ **不通用正则**（ArkTS 与性能）—— 逐段扫数字，遇 `/` 停。
   *   找不到返回 -1（调用方按「不过滤」处理）。
   */
  private static progressIndexOf(s: string): number {
    const open: number = s.indexOf('第');
    let from: number = -1;
    if (open >= 0) {
      from = open + 1;
    } else {
      const lb: number = s.indexOf('[');
      if (lb < 0) {
        return -1;
      }
      from = lb + 1;
    }
    let n: number = 0;
    let digits: number = 0;
    for (let i: number = from; i < s.length; i++) {
      const c: number = s.charCodeAt(i);
      if (c >= 0x30 && c <= 0x39) {
        n = n * 10 + (c - 0x30);
        digits += 1;
        if (digits > 6) {
          return -1;
        }
      } else {
        break;
      }
    }
    return digits > 0 ? n : -1;
  }
"""


def main():
    path = os.path.join(ROOT, REL)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()

    if PROBE in src:
        print('SKIP 已应用')
        return

    if src.count(OLD) != 1:
        print('ABORT onLog 绑定点 count=%d' % src.count(OLD))
        sys.exit(1)

    # 插到 isPerItemV5Log 之前：找一个稳定的锚点
    ANCHOR = "  private async persistAlbumIndex(): Promise<void> {"
    if src.count(ANCHOR) != 1:
        print('ABORT 锚点 count=%d' % src.count(ANCHOR))
        sys.exit(1)

    src = src.replace(OLD, NEW, 1)
    src = src.replace(ANCHOR, HELPER.lstrip('\n') + '\n' + ANCHOR, 1)

    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)
    # 语义自检
    for s in ['private static isPerItemV5Log', 'private static progressIndexOf',
              'Log.d(TAG, s);', 'this.pushLog(s);']:
        if s not in src:
            print('ABORT 自检失败: %s' % s)
            sys.exit(1)
    # 括号平衡粗检
    if src.count('{') != src.count('}'):
        print('WARN 花括号不平衡: { %d vs } %d' % (src.count('{'), src.count('}')))

    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('OK %s' % REL)
    print('自检: isPerItemV5Log ✓  progressIndexOf ✓  Log.d 转发 ✓  pushLog 保留 ✓')


if __name__ == '__main__':
    main()
