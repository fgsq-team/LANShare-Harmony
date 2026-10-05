#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5.0.27 —— 关闭 1110 分片**发送**（保留接收）。

诉求（vivi 2026-10-01 19:52）：
    「放弃分片发送，失败率太高，只在接收时用分片」

实证依据（见 docs/PENDING_TEST.md 与工作日志 2026-10-01）：
  · 片级收尾竞态约 5%/片 —— 失败片日志恒为
    「已跳过 N 个流控字节，本片共 N 块，连接已断」：块 ack 全部收齐（数据 100% 送达），
    但读片级终态 2 时读到对端 FIN（已排除超时误判：NativeSocket.readExactly 超时只
    return null，不会置 closed=true）。
  · 16 片并发 ⇒ 约 60% 概率至少 1 片中招 ⇒ 整批判失败 ⇒ 1101 把大文件再传一遍
    （677MB 传两遍 = 1.35GB），正是 vivi 看到的「一直连续发送 2 次」。
  · 5.0.25 补发片级 FS_END 后，绝大多数片已能拿到 resp=2，但对端**偶发提前关连接**
    这一条改不了（对端行为）。

方案：加一个总开关 SEG_SEND_ENABLED=false —— 发送侧一律走 1101 单连接；
      接收侧（1110 分片接收）完全保留，对端发来分片照样能收。
      ⚠️ 发送侧代码（sendSegBatch / sendSegFile / sendOneSegment）**不删**，
         仍被引用链串着，将来想恢复只需把开关改回 true。

改动点：
  1. V5Transfer.ets  —— 新增 SEG_SEND_ENABLED 常量（默认 false）
  2. V5Transfer.ets  —— segEligible() 开头按开关短路返回 false
  3. V5Transfer.ets  —— send() 开头打一条日志说明走哪条通道
  4. AppScope/app.json5 —— 版本 5.0.26 -> 5.0.27（versionCode 5000027）

铁律：哨兵幂等 + 全量校验 + 末尾统一落盘。
"""

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V5 = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'V5Transfer.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = 'static readonly SEG_SEND_ENABLED: boolean = false;'

# ---------------- 锚点（按原文件逐字抄） ----------------

# 1) 常量：插在 SEG_MIN_SIZE 之后
OLD_CONST = """  /** 走 1110 的最小文件大小 = 128MB（1.35 的 `0x8000000`，见 `send()` 注释） */
  static readonly SEG_MIN_SIZE: number = 134217728;
"""

NEW_CONST = """  /** 走 1110 的最小文件大小 = 128MB（1.35 的 `0x8000000`，见 `send()` 注释） */
  static readonly SEG_MIN_SIZE: number = 134217728;
  /**
   * ★ 是否启用 1110 分片**发送**（5.0.27 起默认 **false**；**接收侧恒保留**）。
   *
   * 关闭原因（真机实证，非推测）：车机版安卓 1.35 在收完某一片的全部数据块、
   * 回完所有块级 ack（5）后，会**偶发直接关掉这条连接、不再发片级终态 2**。
   *   · 判据：失败片日志恒为「已跳过 N 个流控字节，本片共 N 块，连接已断」——
   *     hopCount == blocks（数据 100% 送达）+ `chan.isClosed === true`。
   *   · 已排除「本端超时误判」：`NativeSocket.readExactly` 超时只 `return null`，
   *     **不会**把 `closed` 置 true，所以这是真的对端 FIN。
   *   · 量化：片级失败率 ≈ 5%；16 片并发 ⇒ **约 60% 概率至少 1 片中招**。
   *
   * 后果：批次只要有 1 片判失败，`send()` 就把**整个文件**并入 1101 重传
   * （677MB 传两遍 = 1.35GB）—— 即 vivi 反馈的「一直连续发送 2 次」。
   * 而 1101 单连接对 1.35 是**已实机验证成功**的通道，代价只是没有并行加速。
   *
   * ⚠️ 发送侧代码（`sendSegBatch` / `sendSegFile` / `sendOneSegment`）**不删**，
   *    仍被引用链串着；将来若换到不会提前关连接的对端，把这里改回 true 即可恢复。
   */
  static readonly SEG_SEND_ENABLED: boolean = false;
"""

# 2) segEligible 开头短路
OLD_ELIG = """  private static segEligible(f: OutgoingFile): boolean {
    const t: number = V5Transfer.typeOf(f.name);
"""

NEW_ELIG = """  private static segEligible(f: OutgoingFile): boolean {
    if (!V5Transfer.SEG_SEND_ENABLED) {
      return false;   // 全局关闭 1110 发送（理由见 SEG_SEND_ENABLED 注释）；接收侧不受影响
    }
    const t: number = V5Transfer.typeOf(f.name);
"""

# 3) send() 开头日志
OLD_SEND = """    let okAll: boolean = true;
    // 大文件先发（走 1110，自己开 16 条连接，与 1101 的连接互不影响）
"""

NEW_SEND = """    if (!V5Transfer.SEG_SEND_ENABLED) {
      Log.i(TAG, 'v5 发送走 1101 单连接（1110 分片发送已关闭，接收侧仍支持分片）');
    }
    let okAll: boolean = true;
    // 大文件先发（走 1110，自己开 16 条连接，与 1101 的连接互不影响）
"""

# 4) 版本
OLD_VER = """    "versionCode": 5000026,
    "versionName": "5.0.26","""
NEW_VER = """    "versionCode": 5000027,
    "versionName": "5.0.27","""


def read(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        s = f.read()
    crlf = '\r\n' in s
    return s.replace('\r\n', '\n'), crlf


def write(p, s, crlf):
    out = s.replace('\n', '\r\n') if crlf else s
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(out)


def main():
    for p in (V5, APP):
        if not os.path.isfile(p):
            print('MISSING: %s' % p)
            return 1

    doc = {}
    orig = {}
    crlf = {}
    for p in (V5, APP):
        doc[p], crlf[p] = read(p)
        orig[p] = doc[p]

    # ---- 幂等 ----
    if SENTINEL in doc[V5] and '5000027' in doc[APP]:
        print('ALREADY APPLIED (5.0.27 sentinel present) — nothing to do')
        return 0

    def edit(p, old, new, expect_absent=None):
        cur = doc[p]
        assert cur.count(old) == 1, 'anchor not unique/found in %s:\n%r' % (p, old[:80])
        if expect_absent:
            assert expect_absent not in cur, 'sentinel already present: %r' % expect_absent
        doc[p] = cur.replace(old, new, 1)

    # ---- 全量校验 + 内存构造 ----
    edit(V5, OLD_CONST, NEW_CONST, expect_absent=SENTINEL)
    edit(V5, OLD_ELIG, NEW_ELIG)
    edit(V5, OLD_SEND, NEW_SEND)
    edit(APP, OLD_VER, NEW_VER)

    # ---- 落盘前最终断言 ----
    v5_new = doc[V5]
    app_new = doc[APP]
    assert SENTINEL in v5_new, '常量未写入'
    assert v5_new.count('static readonly SEG_SEND_ENABLED') == 1, '常量重复'
    assert v5_new.count('if (!V5Transfer.SEG_SEND_ENABLED) {') == 2, '开关判断处数不对（应为 2：segEligible + send）'
    assert v5_new.count("private static segEligible(f: OutgoingFile): boolean {") == 1, 'segEligible 定义异常'
    assert 'static readonly SEG_TOTAL: number = 16;' in v5_new, 'SEG_TOTAL 丢失'
    assert 'static readonly SEG_MIN_SIZE: number = 134217728;' in v5_new, 'SEG_MIN_SIZE 丢失'
    # 接收侧必须完整保留
    assert 'static async receiveSegment(' in v5_new, '接收侧 receiveSegment 丢失！'
    assert 'sendSegBatch' in v5_new, 'sendSegBatch 引用丢失（会导致未使用告警）'
    assert '"versionCode": 5000027' in app_new, 'versionCode 未改'
    assert '"versionName": "5.0.27"' in app_new, 'versionName 未改'

    # ---- 统一落盘 ----
    touched = 0
    for p in (V5, APP):
        if doc[p] != orig[p]:
            write(p, doc[p], crlf[p])
            touched += 1
            print('WROTE  %s' % os.path.relpath(p, ROOT))
        else:
            print('SKIP   %s (no change)' % os.path.relpath(p, ROOT))

    assert touched == 2, 'expected 2 files touched, got %d' % touched
    print('OK: 5.0.27 patch applied (1110 发送关闭 / 接收保留)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
