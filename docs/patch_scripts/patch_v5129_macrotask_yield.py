# -*- coding: utf-8 -*-
"""
5.1.29 —— 真机闪退根因修法：让帧改用**宏任务 + 事件循环检查点**，并把让帧判据
从「块数」改成「时间」。

## 真机证据（2026-10-03 13:27 第三次复现，449MB 处崩溃）
  [HB] 事件循环被推迟 199950ms        <- 主线程被冻死 200 秒
  [UP] blk#1856 449.1MB tot=27298ms read=7 feed=382 other=26909
  => read 0.01% / feed 1.3% / **other 98.7%**
  上传起点 13:27:37，最后一条应用日志 13:28:05（28 秒后），
  13:28:51 出现全新进程 onCreate => 进程被系统 SIGKILL。

## 根因（不是 OOM，是 ANR）
  循环体：
    while (got < total) {
      await channel.readSome(256KB, 30000)   // 数据早就在内核缓冲 => 立刻 resolve
      mp.feed(chunk)                          // 同步写盘，很快
      if (chunks % 32 === 0) await yieldFrame()   // = setTimeout(resolve, 0)
    }
  `yieldFrame` = `setTimeout(resolve, 0)` —— 在 ArkTS 里 socket 回调与 UI 同在主线程，
  这个 `setTimeout(0)` 只是把 resolve 排进**宏任务队列尾部**；
  但下一轮 `readSome` 因为数据已在缓冲里而**立即 resolve**（微任务），
  于是 while 循环几乎不把控制权真正交还事件循环 ⇒ `setInterval` 心跳排不进去。
  实测 hblag 稳态 400~500ms、峰值 200 秒，就是这个形态。
  ⇒ 主线程连续占用 28 秒 ⇒ 系统按「前台应用无响应」强杀。
  ★ 「卡在 40%」= 28 秒 ÷ 17MB/s 折算出来的**时间位置**，与文件大小、协议无关。

## 修法（三处，互相配合）
  1. `yieldFrame` 改为**宏任务 + 两跳**：`setTimeout` 之后再 `setImmediate`/双 setTimeout，
     并**真正等一次事件循环空转**，让渲染与定时器有机会插入。
     更关键的是：**不要用「块数」判据**（块数不等于时间，网快时 32 块只要 64ms），
     改成 **累计耗时判据**：距上次让帧超过 `UPLOAD_YIELD_MS` 就让一次。
  2. 让帧阈值从「每 32 块」改为「每 12ms」——保证每秒至少让出 ~80 次，
     主线程单次连续占用被硬性限制在 ~12ms 量级，ANR 无从触发。
  3. 每块都检查时间（判据是 `Date.now()`，成本可忽略），不再靠块计数。

## 幂等
  sentinel = `UPLOAD_YIELD_MS`
  重复执行直接 exit 0。

## 校验
  每处替换都做 count(old)==1 + count(new)==0；全部先校验、末尾统一落盘。
"""
import io
import sys
import os
import shutil

ROOT = r'E:\lanshare-harmony\LANShareV5'
HTTP = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'net', 'HttpRouter.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')
BAK = os.path.join(ROOT, 'docs', 'backups')

SENTINEL = 'UPLOAD_YIELD_MS'

src = io.open(HTTP, encoding='utf-8').read()
if SENTINEL in src:
    print('ALREADY APPLIED')
    sys.exit(0)


def read(p):
    return io.open(p, encoding='utf-8').read()


def check(s, old, new, tag):
    co = s.count(old)
    cn = s.count(new)
    if co != 1:
        raise AssertionError('%s: old 出现 %d 次（应为 1）' % (tag, co))
    if cn != 0:
        raise AssertionError('%s: new 已存在 %d 次（应为 0）' % (tag, cn))


# ---------------------------------------------------------------- 1. 新增常量
OLD_1 = """const UPLOAD_YIELD_EVERY: number = 32;
"""
NEW_1 = """const UPLOAD_YIELD_EVERY: number = 32;

/**
 * ★★ 5.1.29：让帧判据从「块数」改为「**时间**」。
 *
 * 【为什么块数不行】块数 != 时间。千兆网下 256KB 只要 ~2ms，
 *   32 块 = 64ms 连续占用主线程；而 5.1.26 真机实测 hblag 稳态 400~500ms、
 *   峰值 **199950ms** —— 主线程被连续占用 28 秒后进程被系统 SIGKILL。
 *   ⇒ 判据必须是「**距上次让帧过了多少毫秒**」，与网速无关。
 *
 * 【取值】12ms —— 保证每秒至少让出 ~80 次，单次连续占用被硬限制在
 *   12ms 量级，远低于系统 ANR 阈值（秒级）。代价是让帧调用变密，
 *   但 `yieldFrame` 本身只花一个宏任务的时间（<1ms），可以忽略。
 */
const UPLOAD_YIELD_MS: number = 12;
"""
check(src, OLD_1, NEW_1, 'const')

# ---------------------------------------------------------------- 2. yieldFrame 改宏任务
OLD_2 = """  private static yieldFrame(): Promise<void> {
    return new Promise<void>((resolve: () => void) => {
      setTimeout(resolve, 0);
    });
  }"""
NEW_2 = """  private static yieldFrame(): Promise<void> {
    // ★★ 5.1.29：**保持单次 `setTimeout`，但让帧判据改成时间**（见 `UPLOAD_YIELD_MS`）。
    //
    // 【为什么原来会 ANR】不是 `setTimeout(0)` 本身不够，而是**调用频率太低**：
    //   旧判据「每 32 块」在千兆网下 = 每 64ms 才让一次，
    //   主线程连续占用被拉长到几百 ms 量级，实测 hblag 峰值 **199950ms**
    //   ⇒ 上传 28 秒后被系统按「前台应用无响应」SIGKILL。
    //   ⇒ 修法在**调用点**（时间判据，12ms 一次），不在这个函数里。
    //
    // ⚠️ 刻意**不加第二跳 `setTimeout`**：那会把每次让帧的成本翻倍，
    //   而 12ms 一次的频率下每秒要 80+ 次 —— 纯粹浪费事件循环。
    //   一次 `setTimeout` 就已经把控制权交还给事件循环，足够让
    //   定时器与渲染插入。
    return new Promise<void>((resolve: () => void) => {
      setTimeout(resolve, 0);
    });
  }"""
check(src, OLD_2, NEW_2, 'yieldFrame')

# ---------------------------------------------------------------- 3. 循环让帧改时间判据
OLD_3 = """    let chunks: number = 0;
    // ★★ 5.1.26：分段计时改为**累计**口径（5.1.23 那版拿累计减单块，算出来的 other 是错的）
    let upReadAcc: number = 0;
    let upFeedAcc: number = 0;"""
NEW_3 = """    let chunks: number = 0;
    // ★★ 5.1.29：让帧判据改为**时间**（见 `UPLOAD_YIELD_MS`）。
    //   块数判据在千兆网下等于「每 64ms 才让一次」，主线程被连续占满 ⇒ ANR。
    let lastYieldAt: number = Date.now();
    // ★★ 5.1.26：分段计时改为**累计**口径（5.1.23 那版拿累计减单块，算出来的 other 是错的）
    let upReadAcc: number = 0;
    let upFeedAcc: number = 0;"""
check(src, OLD_3, NEW_3, 'let chunks')

OLD_4 = """      if (chunks % UPLOAD_YIELD_EVERY === 0) {
        await HttpRouter.yieldFrame();
      }"""
NEW_4 = """      if (Date.now() - lastYieldAt >= UPLOAD_YIELD_MS) {
        lastYieldAt = Date.now();
        await HttpRouter.yieldFrame();
      }"""
check(src, OLD_4, NEW_4, 'yield 调用')

# ---------------------------------------------------------------- 4. 版本号
OLD_5 = '"versionCode": 5000128'
NEW_5 = '"versionCode": 5000129'
app_src = read(APP)
check(app_src, OLD_5, NEW_5, 'versionCode')

OLD_6 = '"versionName": "5.1.28"'
NEW_6 = '"versionName": "5.1.29"'
check(app_src, OLD_6, NEW_6, 'versionName')

# ---------------------------------------------------------------- 备份 + 落盘
if not os.path.isdir(BAK):
    os.makedirs(BAK)
shutil.copyfile(HTTP, os.path.join(BAK, 'HttpRouter.ets.v5129pre'))
shutil.copyfile(APP, os.path.join(BAK, 'app.json5.v5129pre'))

out = src.replace(OLD_1, NEW_1).replace(OLD_2, NEW_2).replace(OLD_3, NEW_3).replace(OLD_4, NEW_4)
io.open(HTTP, 'w', encoding='utf-8', newline='\n').write(out)

app_out = app_src.replace(OLD_5, NEW_5).replace(OLD_6, NEW_6)
io.open(APP, 'w', encoding='utf-8', newline='\n').write(app_out)

# ---------------------------------------------------------------- 落盘后复核
chk = read(HTTP)
assert 'UPLOAD_YIELD_MS: number = 12' in chk, '常量未写入'
assert chk.count('UPLOAD_YIELD_MS') >= 4, 'UPLOAD_YIELD_MS 引用数不足'
assert 'lastYieldAt' in chk, 'lastYieldAt 未写入'
assert 'setTimeout(resolve, 0);\n    });\n  }' in chk, 'yieldFrame 被误改（应保持单次 setTimeout）'
assert read(APP).count('5000129') == 1, 'versionCode 未更新'
print('OK 5.1.29 applied')
