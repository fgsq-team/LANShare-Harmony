#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.33-diag —— **纯诊断版**：量出「上传期间 ArkUI 实际出了多少帧」。

【为什么是诊断版】
  5.1.29（让帧判据 12ms）与 5.1.32（定时器单例）连续两轮基于
  「JS 消息队列负载」这一**同一假设**改动，症状只换位置、未解决：
    5.1.29 → 崩在 40%     5.1.31 → 崩在 86%
    5.1.32 → 崩在 8%/348MB
  按项目铁律「改了但没好连着两轮 ⇒ 停止猜测、改用观测」，
  本版**不改任何行为**，只加观测。

【5.1.32 复测拿到的钥匙日志】
  14:01:34.266  Vsync: recv vsync timeout  timeInterval:605761109ns  (0.61s)
  14:01:35.535  Vsync: recv vsync timeout  timeInterval:1171444171ns (1.17s)
  14:01:37.191  Vsync: recv vsync timeout  timeInterval:1624607591ns (1.62s) ← 递增
  14:01:43.864  Ace: ArkUI request vsync, but no vsync received in 3 seconds
  ⇒ THREAD_BLOCK 的判据是「**渲染帧出不来**」，不是「JS 事件循环被占」。
  ⇒ 但 hblag 全程健康（30~270ms）⇒ **两套独立心跳，我盯错了指标。**

【本版要回答的三个问题】
  Q1 上传期间 ArkUI 实际拿到多少帧？正常应 ~60fps（或至少 30fps）。
  Q2 帧间隔分布如何？是均匀变长，还是偶发大空档？
  Q3 `yieldFrame` 一次往返实际花多久？（若远超「一个宏任务」，说明
     连让帧本身都排不上队。）

【实现】
  用 @ohos.graphics.displaySync 的 frame 回调（带帧到达时间戳纳秒）
  做**独立于 JS 定时器**的帧计数 —— 它反映的是**渲染管线**的真实节奏，
  而不是 JS 事件循环的节奏。这正是前三轮缺的那个维度。

⚠️ 本版**不改任何业务行为**：让帧判据、定时器、顺序全部保持 5.1.32 原样。
   唯一的运行时副作用是一个 1 秒周期的统计汇总（低频，不是渲染路径）。

幂等：哨兵 = DIAG_FRAME_WINDOW_MS 常量名。
"""

import io
import os
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
HR = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'net', 'HttpRouter.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = 'DIAG_FRAME_WINDOW_MS'


def read(p):
    return io.open(p, 'r', encoding='utf-8', newline='').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def main():
    hr = read(HR)
    app = read(APP)

    if SENTINEL in hr:
        print('ALREADY APPLIED')
        sys.exit(0)

    # ============================================================
    # ① import：displaySync（ArkGraphics2D）
    # ============================================================
    # 找现有 import 区，在第一个 import 之后插入
    anchor_imp = "import { TcpChannel } from './NativeSocket';"
    if anchor_imp not in hr:
        # 退化：找任意一个 import 行
        lines = hr.split('\n')
        idx = -1
        for i, ln in enumerate(lines):
            if ln.startswith('import '):
                idx = i
                break
        if idx < 0:
            raise AssertionError('no import line found')
        anchor_imp = lines[idx]
    new_imp = (anchor_imp + "\n"
               "// ★★ 5.1.33-diag：**纯诊断用**导入 —— 量 ArkUI 渲染管线的真实帧率。\n"
               "//   前三轮只看了 JS 事件循环心跳（hblag），但 5.1.32 复测证明\n"
               "//   真正被饿死的是渲染帧（Ace: no vsync received in 3 seconds）。\n"
               "//   本模块从渲染管线取帧到达时间戳，与 JS 定时器**完全独立**。\n"
               "import { displaySync } from '@kit.ArkGraphics2D';")
    assert hr.count(anchor_imp) == 1, 'import anchor not unique: %d' % hr.count(anchor_imp)
    assert hr.count('displaySync') == 0, 'displaySync already imported'
    hr = hr.replace(anchor_imp, new_imp, 1)

    # ============================================================
    # ② 常量：诊断窗口
    # ============================================================
    old_c = "const UPLOAD_YIELD_MS: number = 24;"
    new_c = """const UPLOAD_YIELD_MS: number = 24;

/**
 * ★★ 5.1.33-diag：渲染帧统计的汇总窗口（毫秒）。
 *
 * 每满一个窗口打一行 `[FPS]`，记录**这一秒里 ArkUI 实际出了多少帧**、
 * 最长帧间隔是多少。这是前三轮**一直没有的观测维度**：
 *   - `hblag` 测的是 JS 事件循环（宏任务）延迟
 *   - `[FPS]` 测的是**渲染管线**的真实出帧节奏
 * 5.1.32 复测证明两者可以严重背离（hblag 全程 30~270ms 健康，
 * 而 `Ace: no vsync received in 3 seconds`）。
 *
 * ⚠️ 只在窗口满时打一行 ⇒ 1 行/秒，低频，**不在渲染路径上逐帧打日志**。
 */
const DIAG_FRAME_WINDOW_MS: number = 1000;"""
    assert hr.count(old_c) == 1, 'UPLOAD_YIELD_MS anchor not unique'
    assert hr.count(new_c) == 0, 'new const already present'
    hr = hr.replace(old_c, new_c, 1)

    # ============================================================
    # ③ 字段 + 方法：帧统计器
    # ============================================================
    # 挂在 hbTimer 附近（同为诊断设施）
    old_f = "  private hbTimer: number = -1;"
    new_f = """  // ★★ 5.1.33-diag：渲染帧统计（**纯诊断，可整段删**）。
  //   与 hbTimer 的区别：hbTimer 测 JS 事件循环，本组字段测**渲染管线**。
  private diagSync: displaySync.DisplaySync | null = null;
  private diagFrameCount: number = 0;
  private diagLastFrameTs: number = 0;
  private diagWorstGapNs: number = 0;
  private diagWindowStart: number = 0;
  private diagTotalFrames: number = 0;
  private diagTotalWindows: number = 0;

  private hbTimer: number = -1;"""
    assert hr.count(old_f) == 1, 'hbTimer decl not unique: %d' % hr.count(old_f)
    assert hr.count('diagSync') == 0, 'diag fields already present'
    hr = hr.replace(old_f, new_f, 1)

    # 方法：加在 startHeartbeat 之前
    old_m = "  private startHeartbeat(): void {"
    new_m = """  /**
   * ★★ 5.1.33-diag：启动渲染帧统计（**纯诊断**）。
   *
   * 【要回答的问题】上传期间 ArkUI **实际**出了多少帧？
   *   正常应接近屏幕刷新率（60/90/120Hz）；若掉到个位数，
   *   就坐实了「渲染帧被上传循环饿死」这个假设 ——
   *   这正是前三轮所有改动都没触及的维度。
   *
   * 【为什么用 displaySync 而不是自己数】它给的 `timestamp` 是**帧到达的
   *   真实时刻（纳秒）**，来自渲染管线；而 JS 里的 `Date.now()` 只能反映
   *   「我的回调什么时候被排到」—— 恰恰是被影响的那一方，不能自证。
   */
  private startFrameDiag(): void {
    if (this.diagSync !== null) {
      return;
    }
    try {
      const ds: displaySync.DisplaySync = displaySync.create();
      this.diagWindowStart = Date.now();
      ds.on('frame', (info: displaySync.IntervalInfo) => {
        this.diagFrameCount += 1;
        this.diagTotalFrames += 1;
        // 帧间隔：用渲染管线给的时间戳算，不用 Date.now()
        if (this.diagLastFrameTs > 0 && info.timestamp > this.diagLastFrameTs) {
          const gap: number = info.timestamp - this.diagLastFrameTs;
          if (gap > this.diagWorstGapNs) {
            this.diagWorstGapNs = gap;
          }
        }
        this.diagLastFrameTs = info.timestamp;
        const now: number = Date.now();
        if (now - this.diagWindowStart >= DIAG_FRAME_WINDOW_MS) {
          const win: number = now - this.diagWindowStart;
          // 帧率用窗口内帧数 / 实际窗口时长；最长间隔换算成 ms
          const fps: number = win > 0 ? (this.diagFrameCount * 1000 / win) : 0;
          const worstMs: number = this.diagWorstGapNs / 1000000;
          Log.i(TAG, `[FPS] 帧=${this.diagFrameCount} fps=${fps.toFixed(1)} `
            + `最长间隔=${worstMs.toFixed(0)}ms 累计帧=${this.diagTotalFrames} `
            + `窗口数=${this.diagTotalWindows}`);
          this.diagTotalWindows += 1;
          this.diagFrameCount = 0;
          this.diagWorstGapNs = 0;
          this.diagWindowStart = now;
        }
      });
      ds.setExpectedFrameRateRange({ expected: 60, min: 30, max: 120 });
      ds.start();
      this.diagSync = ds;
      Log.i(TAG, '[FPS] 渲染帧统计已启动（诊断用，不影响上传行为）');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `[FPS] 启动失败（诊断跳过）: ${err.code} ${err.message}`);
    }
  }

  /** ★ 5.1.33-diag：停止帧统计并输出总计 */
  private stopFrameDiag(): void {
    if (this.diagSync === null) {
      return;
    }
    try {
      this.diagSync.stop();
    } catch (e) {
      // ArkTS 不允许空 catch 块 ⇒ 显式忽略（诊断设施，失败无副作用）
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `[FPS] stop 异常（忽略）: ${err.code}`);
    }
    Log.i(TAG, `[FPS] 统计结束：总帧数=${this.diagTotalFrames} `
      + `总窗口=${this.diagTotalWindows}`);
    this.diagSync = null;
  }

  private startHeartbeat(): void {"""
    assert hr.count(old_m) == 1, 'startHeartbeat anchor not unique: %d' % hr.count(old_m)
    assert hr.count('startFrameDiag') == 0, 'startFrameDiag already present'
    hr = hr.replace(old_m, new_m, 1)

    # ============================================================
    # ④ 让帧耗时观测：yieldFrame 前后计时，累计到 [UP] 行
    # ============================================================
    # 4a. 字段
    old_y = "  private static yieldFrame(): Promise<void> {"
    new_y = """  // ★ 5.1.33-diag：让帧往返累计耗时（诊断）
  private diagYieldAccMs: number = 0;
  private diagYieldWorstMs: number = 0;
  private diagYieldCount: number = 0;

  private static yieldFrame(): Promise<void> {"""
    assert hr.count(old_y) == 1, 'yieldFrame anchor not unique'
    assert hr.count('diagYieldAccMs') == 0, 'diagYield fields already present'
    hr = hr.replace(old_y, new_y, 1)

    # 4b. [UP] 行附带让帧统计
    old_up = """        Log.i(TAG, `[UP] blk#${chunks} ${(got / 1024 / 1024).toFixed(1)}MB `
          + `tot=${el}ms read=${upReadAcc} feed=${upFeedAcc} `
          + `other=${el - upReadAcc - upFeedAcc} hblag=${this.hbLag()} `
          + `| avg=${mbps.toFixed(1)}MB/s`);"""
    new_up = """        Log.i(TAG, `[UP] blk#${chunks} ${(got / 1024 / 1024).toFixed(1)}MB `
          + `tot=${el}ms read=${upReadAcc} feed=${upFeedAcc} `
          + `other=${el - upReadAcc - upFeedAcc} hblag=${this.hbLag()} `
          + `yield=${this.diagYieldAccMs}ms/${this.diagYieldCount}次(最差${this.diagYieldWorstMs}ms) `
          + `| avg=${mbps.toFixed(1)}MB/s`);"""
    assert hr.count(old_up) == 1, '[UP] log anchor not unique: %d' % hr.count(old_up)
    assert hr.count(new_up) == 0, 'new [UP] log already present'
    hr = hr.replace(old_up, new_up, 1)

    # 4c. 让帧调用点计时（包住 await yieldFrame()）
    old_call = """      if (Date.now() - lastYieldAt >= UPLOAD_YIELD_MS) {
        lastYieldAt = Date.now();
        await HttpRouter.yieldFrame();
      }"""
    new_call = """      if (Date.now() - lastYieldAt >= UPLOAD_YIELD_MS) {
        lastYieldAt = Date.now();
        // ★ 5.1.33-diag：量「让帧一次往返」的真实耗时。
        //   若它远超「一个宏任务」（应 <1ms），说明连让帧本身都排不上队。
        const yT0: number = Date.now();
        await HttpRouter.yieldFrame();
        const yDt: number = Date.now() - yT0;
        this.diagYieldAccMs += yDt;
        this.diagYieldCount += 1;
        if (yDt > this.diagYieldWorstMs) {
          this.diagYieldWorstMs = yDt;
        }
      }"""
    assert hr.count(old_call) == 1, 'yield call anchor not unique: %d' % hr.count(old_call)
    assert hr.count(new_call) == 0, 'new yield call already present'
    hr = hr.replace(old_call, new_call, 1)

    # ============================================================
    # ⑤ 启停接线
    # ============================================================
    # 【为什么不用 heartbeat 的调用点】
    #   stopHeartbeat 在本文件里**根本没有调用点**（心跳是连接级生命周期，
    #   由 serve() 起、随连接销毁）。若跟它走 ⇒ 帧统计会全程刷 [FPS]，
    #   空闲期也打日志，既脏又偏离「只看上传期间」的目标。
    #
    # 【为什么用 notifyUploadEnd 收口】
    #   它是**成功与失败唯一的收口点**（函数注释原话：
    #   「成功与失败都会走，保证浮层一定会被收掉」）⇒ 只需改一处，
    #   不会漏掉超时 / 400 / serverError 等任一条 return 路径。
    #
    # 5a. 起点：上传循环入口（notifyUploadProgress(0, total, '') 之后）
    c_start = "    this.notifyUploadProgress(0, total, '');"
    if hr.count(c_start) == 1:
        hr = hr.replace(c_start,
                        c_start + "\n"
                        "    // ★★ 5.1.33-diag：**纯诊断** —— 上传期间开始量渲染帧。\n"
                        "    //   幂等：重复调用只启动一次。\n"
                        "    this.startFrameDiag();", 1)
    else:
        raise AssertionError('serveUpload 入口锚点不唯一: %d' % hr.count(c_start))

    # 5b. 终点：notifyUploadEnd 内部收口
    old_end = """  private notifyUploadEnd(ok: boolean, names: string[], totalBytes: number, error: string): void {
    if (this.uploadEndSink !== null) {"""
    new_end = """  private notifyUploadEnd(ok: boolean, names: string[], totalBytes: number, error: string): void {
    // ★★ 5.1.33-diag：这里**先停帧统计**再回调。
    //   本函数是上传成功/失败的唯一收口 ⇒ 只改这一处就不会漏。
    this.stopFrameDiag();
    if (this.uploadEndSink !== null) {"""
    assert hr.count(old_end) == 1, 'notifyUploadEnd anchor not unique: %d' % hr.count(old_end)
    assert hr.count('this.stopFrameDiag();\n    if (this.uploadEndSink') == 0, 'stopFrameDiag hook already present'
    hr = hr.replace(old_end, new_end, 1)

    # 5c. drainBody 早退路径（boundary 缺失）也走 notifyUploadEnd ⇒ 已覆盖，无需额外改

    # ============================================================
    # ⑥ 版本号
    # ============================================================
    assert app.count('"versionCode": 5000132') == 1, 'versionCode anchor'
    assert app.count('"versionName": "5.1.32"') == 1, 'versionName anchor'
    app = app.replace('"versionCode": 5000132', '"versionCode": 5000133', 1)
    app = app.replace('"versionName": "5.1.32"', '"versionName": "5.1.33-diag"', 1)

    # ---------- 统一落盘 ----------
    write(HR, hr)
    write(APP, app)

    hr2 = read(HR)
    print('--- 复核 ---')
    print('displaySync import        :', hr2.count("from '@kit.ArkGraphics2D'"))
    print('DIAG_FRAME_WINDOW_MS      :', hr2.count('DIAG_FRAME_WINDOW_MS'))
    print('startFrameDiag            :', hr2.count('startFrameDiag'))
    print('stopFrameDiag             :', hr2.count('stopFrameDiag'))
    print('diagYieldAccMs            :', hr2.count('diagYieldAccMs'))
    print('CRLF count                :', hr2.count('\r\n'))
    print('OK 5.1.33-diag applied')


if __name__ == '__main__':
    main()
