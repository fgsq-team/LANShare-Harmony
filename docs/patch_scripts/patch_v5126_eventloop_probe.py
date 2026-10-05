"""5.1.26 诊断版：直接测量「主线程到底有没有被饿死」。

【为什么做这个】连错五轮，纯推理已不可信。本版只回答一个问题：
上传期间，**事件循环**是否被阻塞？

★ 核心判据（XCollie 判 THREAD_BLOCK 的依据就是「主线程 N 秒没处理事件循环」）：
  - 心跳延迟**始终 < 100ms** ⇒ 事件循环通畅、主线程没被饿死
    ⇒ THREAD_BLOCK 属**误报**，真凶在别处
    （且 vivi 实测 5.1.12 也闪退 ⇒ 极可能是基线问题，不是我的改动）。
  - 某次延迟 **> 3000ms** ⇒ 那一瞬间就是真凶所在，`[UP]` 行的 `hblag` 会带上它。

【本版只加不改】
  1. HttpRouter 里一个 250ms 的 `setInterval` 心跳，**只在延迟 > 500ms 时打一行**；
  2. `[UP]` 打点**修正统计错误**（见下）+ 附上 `hblag`。
  ⚠️ 心跳**只打异常行**：250ms 一次若每次都打，250 次/秒的日志会自己
     变成新瓶颈（5.0.68 的教训：诊断日志绝不能放在高频路径）。

【★ 修正 5.1.23 打点的统计错误】
  原式 `other = el - dtRead - dtFeed` 里：
    `el`      = 从函数开头算起的**累计**耗时
    `dtRead`  = **当前这一块**的读耗时
    `dtFeed`  = **当前这一块**的 feed 耗时
  ⇒ 拿「累计」减「单块」，得到的 other **毫无意义**。
    5.1.25 据此得出的「每次让帧 110ms」是**伪结论**（已实测证伪：
    让帧频率降 4 倍后速度 16.5 → 16.7 MB/s，零变化）。
  本版把 read/feed 改成**累计**，other 才有意义。
"""

import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
HTTP = os.path.join(ROOT, r'entry\src\main\ets\net\HttpRouter.ets')

# ---- 1. 心跳字段 + 方法（插在 uploadProgressSink 字段之后）----
OLD1 = """  private uploadProgressSink: ((received: number, total: number, name: string) => void) | null = null;"""

NEW1 = """  private uploadProgressSink: ((received: number, total: number, name: string) => void) | null = null;

  // ★★ 5.1.26（**纯诊断，可随时整段删掉**）：事件循环心跳。
  //
  // 【要回答的问题】XCollie 报 THREAD_BLOCK_6S，但它判「无响应」的依据是
  //   「主线程连续 6 秒没有处理事件循环」。而实测 `[UP]` 日志一直在打、
  //   打印在**主线程 tid** 上、直到 SIGKILL 前 0.55 秒 —— 两者矛盾。
  //   纯推理已连错五轮（await 次数 / concat O(n²) / writeSync / UI 重建 / 让帧），
  //   本版用**独立测量**裁决：心跳定时器自己被推迟多久，就是主线程被占多久。
  //
  // 【判读】
  //   hblag 始终 < 100ms  ⇒ 事件循环通畅 ⇒ THREAD_BLOCK 是**误报**，真凶另有其人
  //   hblag 偶发 > 3000ms ⇒ 那一瞬就是真凶，`[UP]` 行会把它记下来
  //
  // ⚠️ **只在延迟 > HEARTBEAT_ALERT_MS 时才打日志**。250ms 一次的心跳若每次都打，
  //   就是 250 次/秒的字符串拼接 + 写日志 —— 诊断本身会变成新瓶颈
  //   （5.0.68 的教训：诊断日志绝不能放在高频路径上）。
  private static readonly HEARTBEAT_MS: number = 250;
  private static readonly HEARTBEAT_ALERT_MS: number = 500;
  private hbTimer: number = -1;
  private hbLast: number = 0;
  private hbWorst: number = 0;
  /** 心跳被推迟的最长毫秒数（供 UI/日志查询） */
  hbWorstLag(): number {
    return this.hbWorst;
  }

  private startHeartbeat(): void {
    if (this.hbTimer >= 0) {
      return;
    }
    this.hbLast = Date.now();
    this.hbTimer = setInterval(() => {
      const lag: number = Date.now() - this.hbLast;
      this.hbLast = Date.now();
      if (lag > HttpRouter.HEARTBEAT_ALERT_MS) {
        this.hbWorst = lag > this.hbWorst ? lag : this.hbWorst;
        console.warn('[HB] 事件循环被推迟 ' + lag + 'ms，历史最差 ' + this.hbWorst + 'ms');
      }
    }, HttpRouter.HEARTBEAT_MS);
  }

  private stopHeartbeat(): void {
    if (this.hbTimer >= 0) {
      clearInterval(this.hbTimer);
      this.hbTimer = -1;
    }
  }

  /** 最近一次心跳延迟（ms）—— `[UP]` 打点会附读 */
  hbLag(): number {
    return Date.now() - this.hbLast;
  }"""

# ---- 2. 在 serve() 开头启动心跳 ----
OLD2 = """  async serve(channel: TcpChannel, head: Uint8Array): Promise<void> {
    // 把判定协议时读走的 4 字节拼回缓冲区
    channel.unshift(head);"""

NEW2 = """  async serve(channel: TcpChannel, head: Uint8Array): Promise<void> {
    // ★★ 5.1.26（纯诊断）：连接进来就开心跳。5.1.12 也复现 ⇒ 不是我的改动引入。
    this.startHeartbeat();
    // 把判定协议时读走的 4 字节拼回缓冲区
    channel.unshift(head);"""

# ---- 3. [UP] 打点：改累计 + 附 hblag ----
OLD3 = """        Log.i(TAG, `[UP] blk#${chunks} ${(got / 1024 / 1024).toFixed(1)}MB `
          + `tot=${el}ms read=${dtRead} feed=${dtFeed} other=${el - dtRead - dtFeed} `
          + `| avg=${mbps.toFixed(1)}MB/s`);"""

NEW3 = """        // ★★ 5.1.26：★ 修正 5.1.23 的统计错误 ——
        //   `el` 是**累计**时间，dtRead/dtFeed 只是**当前这一块**，
        //   拿累计减单块得到的 other 毫无意义。
        //   （5.1.25 据此得出的「让帧 110ms」是伪结论，已被实测证伪。）
        //   本版改为 read/feed 全部累计，并附上事件循环心跳延迟。
        upReadAcc = upReadAcc + dtRead;
        upFeedAcc = upFeedAcc + dtFeed;
        Log.i(TAG, `[UP] blk#${chunks} ${(got / 1024 / 1024).toFixed(1)}MB `
          + `tot=${el}ms read=${upReadAcc} feed=${upFeedAcc} `
          + `other=${el - upReadAcc - upFeedAcc} hblag=${this.hbLag()} `
          + `| avg=${mbps.toFixed(1)}MB/s`);"""

# ---- 4. 累计变量声明 ----
OLD4 = """    let chunks: number = 0;
    this.notifyUploadProgress(0, total, '');"""

NEW4 = """    let chunks: number = 0;
    // ★★ 5.1.26：分段计时改为**累计**口径（5.1.23 那版拿累计减单块，算出来的 other 是错的）
    let upReadAcc: number = 0;
    let upFeedAcc: number = 0;
    this.notifyUploadProgress(0, total, '');"""

EDITS = [(OLD1, NEW1), (OLD2, NEW2), (OLD3, NEW3), (OLD4, NEW4)]

DRY = '--dry' in sys.argv
src = io.open(HTTP, encoding='utf-8').read()
out = src

if '5.1.26' in src and 'HEARTBEAT_MS' in src:
    print('ALREADY APPLIED')
    sys.exit(0)

ok = True
for i, (old, new) in enumerate(EDITS, 1):
    c = out.count(old)
    if c != 1:
        print('[FAIL] OLD%d 命中 %d（应 1）: %r' % (i, c, old[:56]))
        ok = False
        continue
    if new.count('5.1.26') == 0:
        print('[FAIL] NEW%d 缺标记' % i)
        ok = False
        continue
    if '\r\n' in new or '\ufffd' in new:
        print('[FAIL] NEW%d 含 CRLF 或坏字符' % i)
        ok = False
        continue
    out = out.replace(old, new, 1)
    print('[ok] OLD%d <- %r' % (i, old[:52]))

if not ok:
    print('ABORT（磁盘未改）')
    sys.exit(1)

if DRY:
    print('DRY-RUN OK（%d 处）' % len(EDITS))
    sys.exit(0)

assert '\r\n' not in out
io.open(HTTP, 'w', encoding='utf-8', newline='\n').write(out)
print('APPLIED  %d chars' % len(out))
