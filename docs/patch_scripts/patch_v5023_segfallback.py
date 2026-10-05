# -*- coding: utf-8 -*-
"""
5.0.23 补丁：分片(1110)发送失败时，自动回退到 1101 单连接重传。

背景（实锤）：
  车机版安卓 1.35 在收到 >=128MB 的普通文件时，手机侧会走 1110「16 分片并行」通道，
  但车机侧的 1.35 要么不带 1110 分片接收、要么与我们的 1110 发送存在细微不兼容，
  导致 16 片全部拿不到 RECV_OK（日志：分片 0/16 —— 对端可能不支持分片传输，
  表现为进度到 ~99% 后超时失败）。
  1101 单连接通道对 1.35 已实机验证可用，因此分片失败直接回退 1101 即可保证大文件一定能发出去。

改动文件：
  entry/src/main/ets/service/V5Transfer.ets
    - send()：分片失败的文件并入 plainFiles，统一走 sendPlain 回退重传
    - sendSegBatch()：返回类型 boolean -> OutgoingFile[]（返回分片失败的文件列表）
    - sendSegFile()：不再在此下「发送失败」定论，只留 warn（调用方负责回退）
  AppScope/app.json5：versionName 5.0.22 -> 5.0.23，versionCode 5000022 -> 5000023

约定：全量校验后统一落盘；幂等（已应用则跳过）。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V5 = os.path.join(ROOT, "entry", "src", "main", "ets", "service", "V5Transfer.ets")
APP = os.path.join(ROOT, "AppScope", "app.json5")

SENT_V5 = "const retryFiles: OutgoingFile[]"
SENT_APP = '"versionName": "5.0.23"'

EDITS_V5 = [
    # ---- EDIT 1: send() 编排：分片失败回退 1101 ----
    (
        """    let okAll: boolean = true;
    // 大文件先发（走 1110，自己开 16 条连接，与 1101 的连接互不影响）
    if (segFiles.length > 0) {
      const okSeg: boolean = await V5Transfer.sendSegBatch(self, target, segFiles, onReport);
      if (!okSeg) {
        okAll = false;
      }
    }
    // 其余走原来的 1101 单连接路径（已实机验证成功，保持不动）
    if (plainFiles.length > 0) {
      const okPlain: boolean = await V5Transfer.sendPlain(self, target, plainFiles, encData, onReport);
      if (!okPlain) {
        okAll = false;
      }
    }
    return okAll;""",
        """    let okAll: boolean = true;
    // 大文件先发（走 1110，自己开 16 条连接，与 1101 的连接互不影响）
    let segFailed: OutgoingFile[] = [];
    if (segFiles.length > 0) {
      // sendSegBatch 返回**分片失败的文件**（空数组 = 全部成功）
      segFailed = await V5Transfer.sendSegBatch(self, target, segFiles, onReport);
    }
    // 其余走原来的 1101 单连接路径（已实机验证成功，保持不动）。
    // ⚠️ 分片失败的文件也并入这里**自动回退重传**：车机版 1.35 等部分对端
    //    不支持 / 无法处理 1110 分片接收，直接走 1101 能保证大文件一定能发出去。
    const retryFiles: OutgoingFile[] = plainFiles.concat(segFailed);
    if (retryFiles.length > 0) {
      if (segFailed.length > 0) {
        Log.w(TAG, `v5 分片失败 ${segFailed.length} 个，自动回退到 1101 单连接重传`);
      }
      const okPlain: boolean = await V5Transfer.sendPlain(self, target, retryFiles, encData, onReport);
      if (!okPlain) {
        okAll = false;
      }
    }
    return okAll;""",
    ),
    # ---- EDIT 2: sendSegBatch 签名 + 返回类型 + 收集失败文件 ----
    (
        """  /** 逐文件走 1110 分片并发。单个文件失败不中止其余，但整体返回 false。 */
  private static async sendSegBatch(
    self: LanDevice,
    target: LanDevice,
    files: OutgoingFile[],
    onReport: TransferCallback
  ): Promise<boolean> {""",
        """  /** 逐文件走 1110 分片并发。返回**分片失败的文件列表**（空 = 全部成功），由调用方决定是否回退 1101。 */
  private static async sendSegBatch(
    self: LanDevice,
    target: LanDevice,
    files: OutgoingFile[],
    onReport: TransferCallback
  ): Promise<OutgoingFile[]> {""",
    ),
    (
        """    let grandTotal: number = 0;
    for (let i = 0; i < files.length; i++) {
      grandTotal += files[i].size;
    }
    let okAll: boolean = true;
    let sentBefore: number = 0;
    for (let i = 0; i < files.length; i++) {
      const ok: boolean = await V5Transfer.sendSegFile(self, target, files[i], onReport,
        i + 1, files.length, grandTotal, sentBefore);
      if (!ok) {
        okAll = false;
      }
      sentBefore += files[i].size;
    }
    if (okAll) {
      V5Transfer.report(onReport, 'send', target.devName,
        files.length === 1 ? files[0].name : `${files.length} 个文件`,
        files.length, files.length, grandTotal, grandTotal, 100, true, true,
        `已发送 ${V5Transfer.human(grandTotal)} 到 ${target.devName}（分片并发）`);
    }
    return okAll;""",
        """    let grandTotal: number = 0;
    for (let i = 0; i < files.length; i++) {
      grandTotal += files[i].size;
    }
    const failed: OutgoingFile[] = [];
    let sentBefore: number = 0;
    for (let i = 0; i < files.length; i++) {
      const ok: boolean = await V5Transfer.sendSegFile(self, target, files[i], onReport,
        i + 1, files.length, grandTotal, sentBefore);
      if (!ok) {
        failed.push(files[i]);
      }
      sentBefore += files[i].size;
    }
    if (failed.length === 0) {
      V5Transfer.report(onReport, 'send', target.devName,
        files.length === 1 ? files[0].name : `${files.length} 个文件`,
        files.length, files.length, grandTotal, grandTotal, 100, true, true,
        `已发送 ${V5Transfer.human(grandTotal)} 到 ${target.devName}（分片并发）`);
    }
    return failed;""",
    ),
    # ---- EDIT 3: sendSegFile 不再下「发送失败」定论，只留 warn ----
    (
        """    if (okCount === segTotal) {
      Log.i(TAG, `v5 分片发送完成 ${item.name}（${segTotal} 片，${fileSize} B）`);
      return true;
    }
    Log.w(TAG, `v5 分片发送失败 ${item.name}：成功 ${okCount}/${segTotal} 片`);
    V5Transfer.report(onReport, 'send', target.devName, item.name, fileIndex, fileCount,
      st.sent, fileSize, st.lastPercent < 0 ? 0 : st.lastPercent, true, false,
      `发送失败：${item.name}（分片 ${okCount}/${segTotal}）—— 对端可能不支持分片传输`);
    return false;""",
        """    if (okCount === segTotal) {
      Log.i(TAG, `v5 分片发送完成 ${item.name}（${segTotal} 片，${fileSize} B）`);
      return true;
    }
    // 分片未完成：不在此处下「发送失败」定论 —— 调用方会把它并入 1101 自动回退重传。
    // 仅留一条 warn 供排查（对端可能不支持 1110 分片接收，如部分车机版 1.35）。
    Log.w(TAG, `v5 分片发送失败 ${item.name}：成功 ${okCount}/${segTotal} 片（将回退 1101）`);
    return false;""",
    ),
]

EDITS_APP = [
    (
        '    "versionCode": 5000022,\n    "versionName": "5.0.22",',
        '    "versionCode": 5000023,\n    "versionName": "5.0.23",',
    ),
]


def read_text(p):
    with io.open(p, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(p, s):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def main():
    v5 = read_text(V5)
    app = read_text(APP)

    # ---- 幂等：已应用则跳过 ----
    if SENT_V5 in v5 and SENT_APP in app:
        print("ALREADY APPLIED (5.0.23 segfallback) — 跳过")
        sys.exit(0)

    # 反向前置断言：旧串必须恰好出现一次（保证没重复/没漏）
    v5_new = v5
    for i, (old, new) in enumerate(EDITS_V5):
        assert v5_new.count(old) == 1, f"V5 EDIT {i}: old 出现次数={v5_new.count(old)}，期望 1"
        v5_new = v5_new.replace(old, new)
    app_new = app
    for i, (old, new) in enumerate(EDITS_APP):
        assert app_new.count(old) == 1, f"APP EDIT {i}: old 出现次数={app_new.count(old)}，期望 1"
        app_new = app_new.replace(old, new)

    # 后置断言：新串必须出现、旧串必须消失
    assert SENT_V5 in v5_new, "落盘前 retryFiles 缺失"
    assert SENT_APP in app_new, "落盘前 versionName 5.0.23 缺失"
    assert v5_new.count(": Promise<OutgoingFile[]>") == 1, "sendSegBatch 返回类型未改"
    # sendSegFile 仍返回 Promise<boolean>（返回 true/false），故此处只校验旧失败报告已移除
    assert "发送失败：${item.name}（分片" not in v5_new, "sendSegFile 旧失败报告未移除"

    # ---- 统一落盘（全量校验通过才写） ----
    write_text(V5, v5_new)
    write_text(APP, app_new)
    print("OK: 5.0.23 分片回退补丁已写入")
    print("  - V5Transfer.ets: send()/sendSegBatch()/sendSegFile() 改写")
    print("  - app.json5: 5.0.22 -> 5.0.23 (5000022 -> 5000023)")


if __name__ == "__main__":
    main()
