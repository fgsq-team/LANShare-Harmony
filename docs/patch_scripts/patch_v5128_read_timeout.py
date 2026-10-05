"""5.1.28 正式修法：① 完成提示 ② 读超时改短值。

【A. 「传输完 App 没提示」—— vivi 13:04 反馈】
现象：**网页端有 toast 提示，App 端没有**（不是网页没提示）。
根因：App 端的传输提示是**浮层**（`transferFloat`，靠 `snapshot.transferText` 驱动），
      而 `onWebUploadEnd` 第一行就是 `this.snapshot.transferText = ''`
      ⇒ 浮层在传输结束那一瞬**直接消失**，从来没有「完成」这个视觉节点。
      消息页里那条 `appendFileChat(..., '网页端', ...)` 记录是**另一回事**
      （要切到消息页才看见），浮层本身不显示完成态。
      ⚠️ 这不是 5.1.27 引入的回归 —— 5.1.12 及以前就是这样。

修法：`onWebUploadEnd` **先置一段「✓ 完成」文案并 emit**，1.5 秒后再清空。
     ⚠️ 顺序契约（5.0.51 踩过的坑）：
        `transferText` 由非空变空 是「传输结束、刷新文件页」的触发信号，
        所以**清空动作必须仍然发生**，只是推迟 1.5 秒 ——
        否则文件页不会自动刷新。

【B. 读超时改短值 —— 治「越传越卡 + 40% 闪退」】
5.1.27-ablate 判决性实验（真机 646MB）：
    5.1.26（有 UI）: 16.6 MB/s，心跳报警 9 条，崩在 480MB
    5.1.27（关 UI）: 17.7 MB/s，心跳报警 1 条，646MB **全部完成**
  ⇒ ArkUI 重建**不是**吞吐瓶颈（我 5.1.27 的猜测被自己的实验否掉了）。
  ★ 真正的信号是 `hblag` **单调递增**：
      blk#2752  502.4MB  hblag=33
      blk#2816  515.3MB  hblag=83
      blk#2944  541.6MB  hblag=1347
      blk#3456  638.7MB  hblag=7338   ← 7.3 秒
    ⇒ 事件循环的定时器被系统性推迟、且越积越慢。

  根因：`readSome(256KB, remain)` 的 `remain` 是**整次上传的剩余超时（最大 10 分钟）**，
        而 `waitForData(timeoutMs)` 的实现是 `setTimeout(..., timeoutMs)`
        ⇒ **每一轮循环都挂一个超长定时器**，只因「数据先到、fire() 提前 clear」才没出事。
        640MB / 256KB = 2560 轮，6 个并发连接 ⇒ **约 1.5 万次长定时器反复挂/清**。
  修法：单次 `readSome` 传**固定 30s**（单块 256KB 超 30s 即视为链路异常），
        外层 10 分钟总超时不变 ⇒ 不误杀慢速连接。
"""

import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
HTTP = os.path.join(ROOT, r'entry\src\main\ets\net\HttpRouter.ets')
SVC = os.path.join(ROOT, r'entry\src\main\ets\service\LanService.ets')

DRY = '--dry' in sys.argv
http = io.open(HTTP, encoding='utf-8').read()
svc = io.open(SVC, encoding='utf-8').read()

if 'UPLOAD_READ_TIMEOUT_MS' in http and '5.1.28' in svc:
    print('ALREADY APPLIED')
    sys.exit(0)

# ============ A1. LanService：完成提示先显示 1.5s 再清空 ============
OLD_A1 = """  private onWebUploadEnd(ok: boolean, names: string[], totalBytes: number, error: string): void {
    this.snapshot.transferText = '';
    this.snapshot.transferPercent = 0;
    if (ok) {"""

NEW_A1 = """  /**
   * ★★ 5.1.28：**先显示完成态，1.5 秒后再清空**。
   *
   * 【为什么要改】vivi 13:04 反馈「传输完 App 没提示，网页端有」。
   *   App 端的传输提示是**浮层**（`transferFloat`），而原来这里第一行就
   *   `transferText = ''` ⇒ 浮层在结束那一瞬直接消失，**从来没有完成态**。
   *   （消息页那条 `appendFileChat(..., 'web')` 记录是另一回事，要切页才看见。）
   *   ⚠️ 这**不是** 5.1.27 引入的回归 —— 5.1.12 及以前同样没有完成提示。
   *
   * 【⚠️ 顺序契约 —— 5.0.51 踩过的坑】
   *   `transferText` 由「非空 → 空」是**传输结束、刷新文件页**的触发信号
   *   （`Index.ets` 的 `onSnapshot` 靠这个跳变调 `refreshReceived()`）。
   *   所以**清空动作必须仍然发生**，只是推迟 1.5 秒；
   *   否则文件页不会自动刷新（这正是 5.0.69「终态必须用立即版 emit」的同源问题）。
   */
  private onWebUploadEnd(ok: boolean, names: string[], totalBytes: number, error: string): void {
    if (ok) {
      const label: string = names.length === 1 ? names[0] : `${names.length} 个文件`;
      this.snapshot.transferText = `✓ 网页上传完成：${label}`
        + `（${LanService.fmtSize(totalBytes)}）`;
      this.snapshot.transferPercent = 100;
      this.emit();
      // ★ 定时器句柄存起来：连着传多个文件时，旧的定时器要作废，
      //   否则前一次的「清空」会提前把后一次的完成提示抹掉。
      if (this.uploadDoneTimer >= 0) {
        clearTimeout(this.uploadDoneTimer);
      }
      this.uploadDoneTimer = setTimeout(() => {
        this.uploadDoneTimer = -1;
        this.snapshot.transferText = '';
        this.snapshot.transferPercent = 0;
        this.emit();
      }, 1500);
    } else {
      this.snapshot.transferText = '';
      this.snapshot.transferPercent = 0;
    }
    if (ok) {"""

# ============ A2. LanService：定时器字段 ============
OLD_A2 = """  /** 已写入字节数，用于超限轮转 */
  private logBytes: number = 0;"""

NEW_A2 = """  /** 已写入字节数，用于超限轮转 */
  private logBytes: number = 0;
  /**
   * ★ 5.1.28：「上传完成」浮层的清除定时器句柄，-1 = 没挂。
   *   必须存句柄：连着传多个文件时，前一次的定时器要作废，
   *   否则会提前抹掉后一次的完成提示。
   */
  private uploadDoneTimer: number = -1;"""

# ============ B. HttpRouter：readSome 短超时（若 5.1.28 未落） ============
OLD_B1 = """      const tR0: number = Date.now();
      const chunk: Uint8Array | null = await channel.readSome(UPLOAD_CHUNK, remain);"""

NEW_B1 = """      const tR0: number = Date.now();
      // ★★ 5.1.28：读超时用**固定短值**而不是 `remain`（分钟级）。
      //   `waitForData` 的实现是 `setTimeout(..., timeoutMs)` ——
      //   传分钟级就等于**每一轮循环都挂一个超长定时器**，
      //   只因「数据通常先到、`fire()` 提前 clear」才没出事。
      //   640MB / 256KB = 2560 轮 × 6 个并发连接 ≈ **1.5 万次长定时器挂/清**，
      //   定时器队列调度把事件循环拖慢且**越积越慢**
      //   （实测 `hblag` 从 33ms 单调涨到 **7338ms**）。
      //   单块 256KB 超 30s 即视为链路异常；总超时仍由外层
      //   `UPLOAD_TIMEOUT_MS`（10 分钟）负责，不会误杀慢速连接。
      const chunk: Uint8Array | null = await channel.readSome(UPLOAD_CHUNK, UPLOAD_READ_TIMEOUT_MS);"""

OLD_B2 = """const UPLOAD_YIELD_EVERY: number = 32;"""

NEW_B2 = """const UPLOAD_YIELD_EVERY: number = 32;

/**
 * ★★ 5.1.28：单次 `readSome` 的超时（毫秒）。
 *
 * 【为什么不能用 `remain`（= `UPLOAD_TIMEOUT_MS` - 已用时间，最大 10 分钟）】
 *   `TcpChannel.waitForData(timeoutMs)` 内部是
 *   `setTimeout(() => {...}, timeoutMs)` ——
 *   传分钟级就等于**每轮循环都挂一个超长定时器**，
 *   只因为「数据通常先到、`fire()` 提前 clear」才没出事。
 *   代价是定时器队列被反复撑大：
 *     640MB / 256KB = 2560 轮 × 6 个并发连接 ≈ **1.5 万次长定时器挂/清**。
 *   实测（5.1.27-ablate 真机 646MB）：
 *     `hblag` 从 blk#2752 的 33ms **单调递增**到 blk#3456 的 **7338ms**
 *   ⇒ 事件循环定时器被系统性推迟、越到后面越慢，
 *      这就是「约 40% 处卡住 ⇒ 6s 无响应 ⇒ SIGKILL」的机制。
 *
 * 【30s 是否安全】单块 256KB 在局域网内 30s 读不到 ⇒ 链路已断；
 *   慢速但正常的连接由外层 10 分钟总超时兜底，不会被误杀。
 */
const UPLOAD_READ_TIMEOUT_MS: number = 30 * 1000;"""

EDITS_SVC = [(OLD_A1, NEW_A1), (OLD_A2, NEW_A2)]
# HTTP 部分：幂等（若已落则跳过）
EDITS_HTTP = []
if 'UPLOAD_READ_TIMEOUT_MS' not in http:
    EDITS_HTTP = [(OLD_B1, NEW_B1), (OLD_B2, NEW_B2)]
else:
    print('[skip] HTTP 的 B 部分已落（5.1.28 上一轮已应用）')

ok = True
out_svc = svc
for i, (old, new) in enumerate(EDITS_SVC, 1):
    c = out_svc.count(old)
    if c != 1:
        print('[FAIL] SVC OLD_A%d 命中 %d（应 1）: %r' % (i, c, old[:60]))
        ok = False
        continue
    if new.count('5.1.28') == 0:
        print('[FAIL] SVC NEW_A%d 缺标记' % i)
        ok = False
        continue
    if '\r\n' in new or '\ufffd' in new:
        print('[FAIL] SVC NEW_A%d 含 CRLF 或坏字符' % i)
        ok = False
        continue
    out_svc = out_svc.replace(old, new, 1)
    print('[ok] SVC OLD_A%d <- %r' % (i, old[:52].replace('\n', '\\n')))

out_http = http
for i, (old, new) in enumerate(EDITS_HTTP, 1):
    c = out_http.count(old)
    if c != 1:
        print('[FAIL] HTTP OLD_B%d 命中 %d（应 1）' % (i, c))
        ok = False
        continue
    out_http = out_http.replace(old, new, 1)
    print('[ok] HTTP OLD_B%d' % i)

if not ok:
    print('ABORT（磁盘未改）')
    sys.exit(1)

if DRY:
    print('DRY-RUN OK（SVC %d 处 + HTTP %d 处）' % (len(EDITS_SVC), len(EDITS_HTTP)))
    sys.exit(0)

assert '\r\n' not in out_svc and '\r\n' not in out_http
io.open(SVC, 'w', encoding='utf-8', newline='\n').write(out_svc)
io.open(HTTP, 'w', encoding='utf-8', newline='\n').write(out_http)
print('APPLIED  SVC=%d chars  HTTP=%d chars' % (len(out_svc), len(out_http)))
