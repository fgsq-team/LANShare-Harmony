"""5.1.27 判决性实验版：把「进度上报」与「让帧」**全部关掉**。

【为什么】5.1.26-diag 的心跳数据已经把范围压到最后一层：
    read 累计 = 7ms（0.02%）、feed 累计 = 367ms（1.3%）、other = 98.7%
    hblag 稳定 365~524ms  ⇒ **事件循环确实被推迟了约 450ms**
而循环体里除 readSome/feed 外只剩三件事：
    ① notifyUploadProgress（节流 1000ms/4MB）→ emitThrottled（**100ms 节流**）→ ArkUI 重建整页
    ② yieldFrame（每 32 块 = 每 8MB）
    ③ if (!mp.ok) break
5.1.25 已证伪 ②（8→32 降 4 倍，速度 16.5→16.7 零变化）。
⇒ 只剩 ① 没被证伪，而它是**唯一能同时解释「事件循环被推迟」+「吞吐卡在 17MB/s」**的候选。

【★ 本版做法】加一个总开关，一次实验定因果：
    UPLOAD_DIAG_DISABLE_UI = true  ⇒ ①② 全关（进度条不更新、UI 会卡）
    UPLOAD_DIAG_DISABLE_UI = false ⇒ 全开（= 5.1.26 行为，便于 A/B 复现）
⚠️ 牺牲 UI 响应是**故意的** —— 这是诊断版，不是给用户长期用的。

【判读】
| 结果 | 结论 |
|---|---|
| 速度飙升到 50MB/s 且不崩 | ★ 确认：进度上报引发的 ArkUI 重建是唯一瓶颈 |
| 速度仍 17MB/s 但不崩 | 重建是「卡」的来源，吞吐另有原因 |
| 仍崩在 40% | 与 UI 无关 ⇒ 纯协议/对端问题（5.1.12 也崩 ⇒ 基线问题） |
"""

import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
HTTP = os.path.join(ROOT, r'entry\src\main\ets\net\HttpRouter.ets')
SVC = os.path.join(ROOT, r'entry\src\main\ets\service\LanService.ets')

# ---- 1. HttpRouter：加总开关 ----
OLD1 = """  private async serveUpload(req: HttpRequest, channel: TcpChannel,
                            pre: Uint8Array, bodyLen: number): Promise<HttpResponse> {"""

NEW1 = """  private async serveUpload(req: HttpRequest, channel: TcpChannel,
                            pre: Uint8Array, bodyLen: number): Promise<HttpResponse> {
    // ★★ 5.1.27（**判决性实验开关，可随时删**）
    //
    // 【背景】5.1.26-diag 的心跳测量（真机 640MB 上传）：
    //     read 累计 7ms(0.02%) / feed 累计 367ms(1.3%) / other 98.7%
    //     hblag 稳定 365~524ms ⇒ **事件循环确实被推迟约 450ms**
    // 循环体里除 readSome/feed 只剩：进度上报、yieldFrame、if(!mp.ok)。
    // 5.1.25 已证伪 yieldFrame（8→32 降 4 倍，速度 16.5→16.7 零变化）。
    // ⇒ 只剩「进度上报」未证伪。
    //
    // 【为什么它嫌疑最大】onWebUploadProgress → **emitThrottled**（100ms 节流）
    //   → @State 变化 → **ArkUI 重建整个页面**。
    //   100ms 节流 = **每秒最多 10 次整页重建**，这既能解释「事件循环被推迟 450ms」，
    //   也能解释「吞吐卡在 17MB/s」（每次重建期间上传循环无法推进）。
    //   ⚠️ 注意：节流参数本身（1000ms/4MB）调大到 16 倍也没用 ——
    //     因为瓶颈是 **emitThrottled 内部那层 100ms 节流 + ArkUI 重建**，不是它。
    //
    // 【本版】true = 全关（进度条不更新、上传期间 UI 会卡）
    //   ⚠️ 这是**故意的**：牺牲 UI 响应换取「一次实验定因果」。
    //     测完会出正式修法，不会长期用这一版。
    if (HttpRouter.UPLOAD_DIAG_DISABLE_UI) {
      Log.i(TAG, '[UP27] 判决性实验：进度上报与让帧**已全部关闭**');
    }"""

# ---- 2. 关闭进度上报 ----
OLD2 = """      const now: number = Date.now();
      if (now - lastReportAt >= UPLOAD_PROGRESS_MIN_MS &&
        got - lastReportBytes >= UPLOAD_PROGRESS_MIN_BYTES) {
        lastReportAt = now;
        lastReportBytes = got;
        this.notifyUploadProgress(got, total, mp.currentName);
      }"""

NEW2 = """      // ★★ 5.1.27：进度上报可被总开关关掉（判决性实验）
      const now: number = Date.now();
      if (!HttpRouter.UPLOAD_DIAG_DISABLE_UI &&
        now - lastReportAt >= UPLOAD_PROGRESS_MIN_MS &&
        got - lastReportBytes >= UPLOAD_PROGRESS_MIN_BYTES) {
        lastReportAt = now;
        lastReportBytes = got;
        this.notifyUploadProgress(got, total, mp.currentName);
      }"""

# ---- 3. 关闭让帧 ----
OLD3 = """      if (chunks % UPLOAD_YIELD_EVERY === 0) {
        await HttpRouter.yieldFrame();
      }"""

NEW3 = """      // ★★ 5.1.27：让帧可被总开关关掉（判决性实验）
      if (!HttpRouter.UPLOAD_DIAG_DISABLE_UI && chunks % UPLOAD_YIELD_EVERY === 0) {
        await HttpRouter.yieldFrame();
      }"""

# ---- 4. 开关常量 ----
OLD4 = """const UPLOAD_YIELD_EVERY: number = 32;"""

NEW4 = """const UPLOAD_YIELD_EVERY: number = 32;

/**
 * ★★ 5.1.27（**判决性实验开关**）：关掉上传期间的「进度上报」与「让帧」。
 *
 * 改 `false` 即回到 5.1.26 行为（便于 A/B 复现）。
 * ⚠️ `true` 时上传期间**进度条不更新、UI 会卡** —— 这是故意的，
 *    用一次实验换掉「到底是 UI 重建还是协议层」这个问号。
 */
const UPLOAD_DIAG_DISABLE_UI: boolean = true;"""

EDITS_HTTP = [
    (OLD1, NEW1),
    (OLD2, NEW2),
    (OLD3, NEW3),
    (OLD4, NEW4),
]

DRY = '--dry' in sys.argv
http = io.open(HTTP, encoding='utf-8').read()
svc = io.open(SVC, encoding='utf-8').read()

if 'UPLOAD_DIAG_DISABLE_UI' in http:
    print('ALREADY APPLIED')
    sys.exit(0)

out = http
ok = True
for i, (old, new) in enumerate(EDITS_HTTP, 1):
    c = out.count(old)
    if c != 1:
        print('[FAIL] OLD%d 命中 %d（应 1）: %r' % (i, c, old[:60]))
        ok = False
        continue
    if new.count('5.1.27') == 0:
        print('[FAIL] NEW%d 缺标记' % i)
        ok = False
        continue
    if '\r\n' in new or '\ufffd' in new:
        print('[FAIL] NEW%d 含 CRLF 或坏字符' % i)
        ok = False
        continue
    out = out.replace(old, new, 1)
    print('[ok] OLD%d <- %r' % (i, old[:54]))

if not ok:
    print('ABORT（磁盘未改）')
    sys.exit(1)

if DRY:
    print('DRY-RUN OK（%d 处）' % len(EDITS_HTTP))
    sys.exit(0)

assert '\r\n' not in out
io.open(HTTP, 'w', encoding='utf-8', newline='\n').write(out)
print('APPLIED  %d chars' % len(out))
