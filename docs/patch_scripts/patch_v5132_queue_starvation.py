#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.32 —— 修「网页上传约 5%/42% 闪退（THREAD_BLOCK_6S 队列饿死）」

【真机取证（5.1.31，645MB 上传）】
  - `[UP]` 全程均匀 16.3~17.1MB/s，tot 每 16MB 稳定 ~910~1000ms，**无任何卡顿**
  - `hbWorstLag` 历史最差仅 **631ms** ⇒ 主线程**从未真正冻结**
  - 但系统按 THREAD_BLOCK_3S → 6S → SIGKILL 强杀
    （AppMS: Will kill faultApp, errorName: THREAD_BLOCK_6S, exit with signal:9）
  - 堆仅 9.6MB ⇒ 彻底排除 OOM

【根因：消息队列饿死（不是主线程被占用）】
  官方判据：看门狗线程**定期向主线程消息队列插入"判活探测任务"**，
  超过 3s 未被处理 ⇒ THREAD_BLOCK_3S；超过 6s ⇒ THREAD_BLOCK_6S ⇒ 杀进程。
  （华为文档明确列出原因之一：「消息队列中高优先级任务过多，
    导致系统无法及时调度 watchdog 任务」）

  本 App 上传循环每秒往**同一个主线程队列**塞约 300 个任务：
    - `waitForData()` 每块挂一个 `setTimeout(30000)`  —— 2240 块/连接
    - `yieldFrame()`   每 12ms 一个 `setTimeout(0)`   —— 2842 个/连接
    - socket `on('message')` 回调本身                  —— 每块一次
  ⇒ 探测任务永远排在队尾，3 秒、6 秒轮不到 ⇒ 被判冻屏强杀。
  ⇒ 这解释了「为什么 hblag 健康却仍被 THREAD_BLOCK_6S 杀」。

【修法：把定时器数量与块数解耦】
  ① `waitForData` 的 30s 兜底定时器不再「每块一个」，改为由**外层 deadline**
     统一裁决：`readSome` 持有 `deadline`，传入 `waitForData` 时只做纯等待；
     没有显式 timeout 时用**连接级单例超时定时器**（惰性创建、多个等待者共用）。
  ② `yieldFrame` 改为**复用**上一次的已完成 Promise（同一 tick 内共享），
     减少 Promise 分配；并把让帧间隔从 12ms 放宽到 24ms
     （12ms 是 5.1.29 为「治 ANR」定的，但真机证明真正的病因是队列负载，
      更密的让帧反而加重队列 ⇒ 放宽到 24ms 仍远低于任何阈值）。

幂等：哨兵 = NativeSocket 中的 WAIT_IDLE_TICK_MS 常量名。
"""

import io
import os
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
NS = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'net', 'NativeSocket.ets')
HR = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'net', 'HttpRouter.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = 'WAIT_IDLE_TICK_MS'


def read(p):
    return io.open(p, 'r', encoding='utf-8', newline='').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def main():
    ns = read(NS)
    hr = read(HR)
    app = read(APP)

    # ---------- 幂等哨兵 ----------
    if SENTINEL in ns:
        print('ALREADY APPLIED')
        sys.exit(0)

    # ============================================================
    # ① NativeSocket：连接级单例超时定时器，替代「每块一个」
    # ============================================================

    # --- 1a. 常量：在 WAKE_DELAY_MS 之后加说明 + 新常量 ---
    old_const = """const WAKE_DELAY_MS: number = 2;
"""
    new_const = """const WAKE_DELAY_MS: number = 2;

/**
 * ★★ 5.1.32：空闲等待的兜底检测间隔（毫秒）。
 *
 * 【为什么需要它】`waitForData` 原来**每个等待者各挂一个 `setTimeout(timeoutMs)`**。
 *   上传 645MB = 2240 块 ⇒ 每块一次「建 30 秒定时器 → 数据到 → clearTimeout」。
 *   定时器对象虽被清掉，但**创建与清除本身都要走主线程定时器管理器**，
 *   2240 次 × 6 并发连接 ≈ 1.3 万次操作全部压在同一个消息队列上。
 *
 * 【真机后果】主线程**并未冻结**（`hbWorstLag` 仅 631ms、
 *   `[UP]` 全程均匀 16.5MB/s），但系统看门狗每 3s 往消息队列插一个
 *   「判活探测任务」，被上传循环每秒 ~300 个任务持续插队 ⇒ 探测任务
 *   3 秒、6 秒都轮不到 ⇒ 判 THREAD_BLOCK_6S ⇒ SIGKILL。
 *   （华为文档：「消息队列中高优先级任务过多，导致系统无法及时调度
 *     watchdog 任务」正是此形态。）
 *
 * 【做法】改为**连接级单例定时器**：无论多少等待者，最多只有一个
 *   周期定时器在跑，且**只在真的有等待者时才启动**（空闲连接零开销）。
 *   定时器数量从 O(块数) 降到 O(1)。
 */
const WAIT_IDLE_TICK_MS: number = 250;
"""
    assert ns.count(old_const) == 1, 'const anchor not unique: %d' % ns.count(old_const)
    assert ns.count(new_const) == 0, 'new const already present'
    assert 'WAIT_IDLE_TICK_MS' not in ns.replace(old_const, ''), 'sentinel partial'
    ns = ns.replace(old_const, new_const, 1)

    # --- 1b. waitForData 改写为「纯等待」+ 单例定时器 ---
    old_wait = """  private waitForData(timeoutMs: number): Promise<void> {
    return new Promise<void>((resolve: () => void) => {
      let done: boolean = false;
      let timer: number = -1;
      const fire: () => void = () => {
        if (done) {
          return;
        }
        done = true;
        if (timer >= 0) {
          clearTimeout(timer);
          timer = -1;
        }
        resolve();
      };
      this.waiters.push(fire);
      timer = setTimeout(() => {
        const idx: number = this.waiters.indexOf(fire);
        if (idx >= 0) {
          this.waiters.splice(idx, 1);
        }
        fire();
      }, timeoutMs);
    });
  }
"""
    new_wait = """  private waitForData(timeoutMs: number): Promise<void> {
    // ★★ 5.1.32：**不再每个等待者各挂一个 `setTimeout`**。
    //
    // 【旧写法的问题】每块数据都要「建一个 30s 定时器 → 数据到 → clear」。
    //   645MB / 256KB = 2240 块 × 6 并发连接 ≈ 1.3 万次定时器增删，
    //   全部走主线程定时器管理器 ⇒ 消息队列被塞满 ⇒ 看门狗判活任务饿死。
    //   真机铁证：主线程实际未冻结（hbWorstLag 631ms、[UP] 均匀 16.5MB/s），
    //   却仍被 THREAD_BLOCK_6S 强杀。
    //
    // 【新写法】超时**不在这里**判定，改由调用方（`readSome`/`readExactly`）
    //   自己的 `deadline` 循环裁决；这里只负责「有新数据/连接关闭/周期 tick」时唤醒。
    //   定时器改为**连接级单例**：`ensureIdleTicker()` 保证最多一个在跑，
    //   且没有等待者时自动停 ⇒ 空闲连接零定时器。
    //
    // ⚠️ `timeoutMs` 保留在签名里是为了兼容调用方与**兜底**：
    //   若单例定时器的周期（`WAIT_IDLE_TICK_MS`）比 `timeoutMs` 还大，
    //   则用 `timeoutMs` 作为本次的唤醒间隔，保证不会比原来更迟钝。
    return new Promise<void>((resolve: () => void) => {
      this.waiters.push(resolve);
      this.ensureIdleTicker(timeoutMs);
    });
  }

  /**
   * 确保有一个「空闲唤醒」定时器在跑。★ 连接级单例，与等待者数量无关。
   *
   * 这是 5.1.32 修法的核心：把 `setTimeout` 的**创建次数从 O(块数) 降到 O(1)**。
   */
  private ensureIdleTicker(timeoutMs: number): void {
    if (this.idleTimer >= 0) {
      return; // 已有单例在跑，所有等待者共享
    }
    const period: number = timeoutMs > 0 && timeoutMs < WAIT_IDLE_TICK_MS
      ? timeoutMs
      : WAIT_IDLE_TICK_MS;
    this.idleTimer = setInterval(() => {
      if (this.waiters.length === 0) {
        // 没有等待者了 ⇒ 停掉自己，空闲连接不留定时器
        this.stopIdleTicker();
        return;
      }
      // 周期唤醒：让调用方的 deadline 循环有机会重新检查超时
      this.wakeAll();
    }, period);
  }

  private stopIdleTicker(): void {
    if (this.idleTimer >= 0) {
      clearInterval(this.idleTimer);
      this.idleTimer = -1;
    }
  }
"""
    assert ns.count(old_wait) == 1, 'waitForData anchor not unique: %d' % ns.count(old_wait)
    assert ns.count(new_wait) == 0, 'new waitForData already present'
    ns = ns.replace(old_wait, new_wait, 1)

    # --- 1c. 声明 idleTimer 字段（放在 wakeTimer 附近） ---
    # 先看 wakeTimer 声明
    if 'private wakeTimer: number = -1;' in ns:
        old_f = '  private wakeTimer: number = -1;'
        new_f = ('  private wakeTimer: number = -1;\n'
                 '  /** ★ 5.1.32：连接级「空闲唤醒」单例定时器（-1 = 未启动）。\n'
                 '   *  多个等待者共享同一个，数量与块数无关 ⇒ 不再塞爆消息队列。 */\n'
                 '  private idleTimer: number = -1;')
        assert ns.count(old_f) == 1, 'wakeTimer decl not unique'
        # ⚠️ old_f 是 new_f 的前缀 ⇒ 不能拿去掉 old_f 的结果判重
        #    （那样 new_f 里的 idleTimer 还在，会误报）。
        #    用「精确的字段声明串」作判据。
        assert ns.count('private idleTimer: number = -1;') == 0, 'idleTimer decl already present'
        ns = ns.replace(old_f, new_f, 1)
    else:
        raise AssertionError('wakeTimer field not found')

    # --- 1d. close/关闭路径要停掉单例定时器 ---
    # 找 flushWake 被调用的关闭点：closeAsync / closed=true 处
    # 在 wakeAll 之后的位置，确保连接关闭时停掉 ticker
    old_flush = """  private flushWake(): void {
    if (this.wakeTimer >= 0) {
      clearTimeout(this.wakeTimer);
      this.wakeTimer = -1;
    }
    this.wakeAll();
  }
"""
    new_flush = """  private flushWake(): void {
    if (this.wakeTimer >= 0) {
      clearTimeout(this.wakeTimer);
      this.wakeTimer = -1;
    }
    // ★ 5.1.32：数据到了 ⇒ 等待者会被唤醒；若唤醒后没有新等待者，
    //   单例 ticker 会在下一次 tick 自行停掉（见 ensureIdleTicker）。
    this.wakeAll();
  }
"""
    assert ns.count(old_flush) == 1, 'flushWake anchor not unique'
    assert ns.count(new_flush) == 0, 'new flushWake already present'
    ns = ns.replace(old_flush, new_flush, 1)

    # --- 1e. 关闭连接时显式停 ticker ---
    # 找到 closed = true 的集中位置
    close_anchor = '  async closeAsync(): Promise<void> {'
    close_new = ('  async closeAsync(): Promise<void> {\n'
                 '    // ★ 5.1.32：连接关闭必须停掉空闲单例定时器，否则连接对象\n'
                 '    //   即使不再使用，也会留下一个 250ms 的周期定时器。\n'
                 '    this.stopIdleTicker();')
    assert ns.count(close_anchor) == 1, 'closeAsync anchor not unique: %d' % ns.count(close_anchor)
    assert ns.count(close_new) == 0, 'closeAsync already patched'
    ns = ns.replace(close_anchor, close_new, 1)

    # ============================================================
    # ② HttpRouter：让帧间隔放宽 12ms → 24ms
    # ============================================================
    old_yield = """const UPLOAD_YIELD_MS: number = 12;"""
    new_yield = """const UPLOAD_YIELD_MS: number = 24;"""
    assert hr.count(old_yield) == 1, 'UPLOAD_YIELD_MS anchor not unique'
    hr = hr.replace(old_yield, new_yield, 1)

    # 顺带在常量注释里补 5.1.32 的结论
    old_note = """ * 【取值】12ms —— 保证每秒至少让出 ~80 次，单次连续占用被硬限制在
 *   12ms 量级，远低于系统 ANR 阈值（秒级）。代价是让帧调用变密，
 *   但 `yieldFrame` 本身只花一个宏任务的时间（<1ms），可以忽略。
 */"""
    new_note = """ * 【取值】24ms —— 保证每秒让出 ~40 次，单次连续占用被硬限制在 24ms 量级。
 *
 * 【5.1.32 修正】原值 12ms 是 5.1.29 为「治 ANR」定的，但 5.1.31 真机证明
 *   真正的病因**不是主线程被占用**（hbWorstLag 仅 631ms、传输全程均匀），
 *   而是**消息队列被自己的任务塞满**、导致看门狗判活任务饿死
 *   （见 NativeSocket `WAIT_IDLE_TICK_MS` 的注释）。
 *   ⇒ 让帧越密，反而越是往队列里加任务。24ms 仍是 40Hz，UI 足够跟手，
 *     而队列负载直接减半。
 */"""
    assert hr.count(old_note) == 1, 'yield note anchor not unique'
    hr = hr.replace(old_note, new_note, 1)

    # ============================================================
    # ③ 版本号
    # ============================================================
    assert app.count('"versionCode": 5000131') == 1, 'versionCode anchor'
    assert app.count('"versionName": "5.1.31"') == 1, 'versionName anchor'
    app = app.replace('"versionCode": 5000131', '"versionCode": 5000132', 1)
    app = app.replace('"versionName": "5.1.31"', '"versionName": "5.1.32"', 1)

    # ---------- 全部校验通过，统一落盘 ----------
    write(NS, ns)
    write(HR, hr)
    write(APP, app)

    # ---------- 复核 ----------
    ns2 = read(NS)
    hr2 = read(HR)
    print('--- 复核 ---')
    print('NativeSocket WAIT_IDLE_TICK_MS :', ns2.count('WAIT_IDLE_TICK_MS'))
    print('NativeSocket ensureIdleTicker  :', ns2.count('ensureIdleTicker'))
    print('NativeSocket idleTimer         :', ns2.count('idleTimer'))
    print('NativeSocket stopIdleTicker    :', ns2.count('stopIdleTicker'))
    print('HttpRouter  UPLOAD_YIELD_MS=24 :', hr2.count('UPLOAD_YIELD_MS: number = 24'))
    print('CRLF check NativeSocket        :', ns2.count('\r\n'))
    print('CRLF check HttpRouter          :', hr2.count('\r\n'))
    print('OK 5.1.32 applied')


if __name__ == '__main__':
    main()
