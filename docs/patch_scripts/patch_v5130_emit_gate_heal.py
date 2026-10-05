# -*- coding: utf-8 -*-
"""
5.1.30 —— 修「网页上传进度卡在 19%，但传输没停」

## 真机证据（2026-10-03 13:34，5.1.29）
  13:34:16  上传开始
  13:34:38  [UP] blk#512 122.8MB      <- 19% x 645MB = 122.5MB，界面上报**最后停在这里**
  13:35:05  设备下线：已移除 vivi @ 192.168.10.186
  13:35:07  [UP] blk#2368 586.1MB     <- 但 while 循环**一直在跑**，日志持续打点
  13:35:39  新进程 onCreate（crash.flag）
  ⇒ 「日志在打、上报不执行」= 同一循环里两个分支，一个活着一个死了。

## 根因：`pendingEmitTimer` 标志位泄漏
  `emitThrottled()`：
    if (gap >= 100) { lastEmitAt = now; this.emit(); return; }
    if (this.pendingEmitTimer >= 0) { return; }        // <== 闸门
    this.pendingEmitTimer = setTimeout(() => {
      this.pendingEmitTimer = -1;                       // <== **唯一**清标志的地方
      this.lastEmitAt = Date.now();
      this.emit();
    }, 100 - gap);

  `pendingEmitTimer` 只在 setTimeout 回调里被清。主线程被长任务长时间占用时，
  定时器回调可能被系统性推迟/合并 ⇒ 只要有一次没跑到，标志位**永久 >= 0**，
  此后所有 `emitThrottled()` 都撞在 `return` 上被静默吞掉
  ⇒ 进度条停住、界面再也不刷新（而传输循环完全正常）。
  ★ 这正是「判据的通用纪律」里的形态：**闸门状态只能靠异步回调清除
    ⇒ 回调一旦丢失，闸门永久失效**。

## 修法：闸门必须能**时间自愈**，不能只依赖回调
  给排队加一个**时间上限**：距上次真正 emit 超过 `EMIT_PENDING_MAX_MS` 时，
  无视 `pendingEmitTimer` 直接 emit（并把旧定时器 clear 掉，防双重）。
  这样即使回调丢失，最多晚 `EMIT_PENDING_MAX_MS` 也会自愈。

  另把 `emit()` 也纳入兜底：`emit()` 开头强刷 `pendingEmitTimer`，
  保证终态（onWebUploadEnd 走立即版 emit）不会被残留闸门挡住。

## 幂等
  sentinel = `EMIT_PENDING_MAX_MS`
"""
import io
import sys
import os
import shutil

ROOT = r'E:\lanshare-harmony\LANShareV5'
SVC = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'LanService.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')
BAK = os.path.join(ROOT, 'docs', 'backups')

SENTINEL = 'EMIT_PENDING_MAX_MS'

src = io.open(SVC, encoding='utf-8').read()
if SENTINEL in src:
    print('ALREADY APPLIED')
    sys.exit(0)


def check(s, old, new, tag):
    co = s.count(old)
    cn = s.count(new)
    if co != 1:
        raise AssertionError('%s: old 出现 %d 次（应为 1）' % (tag, co))
    if cn != 0:
        raise AssertionError('%s: new 已存在 %d 次（应为 0）' % (tag, cn))


# ---------------------------------------------------------------- 1. 新增上限常量
OLD_1 = """  private lastEmitAt: number = 0;"""
NEW_1 = """  private lastEmitAt: number = 0;
  /**
   * ★★ 5.1.30：`emitThrottled` 排队闸门的**时间上限**（毫秒）。
   *
   * 【为什么需要】`pendingEmitTimer` 只在 `setTimeout` 回调里被清；
   *   主线程被长任务占满时定时器回调可能被推迟/丢弃 ⇒ 标志位永久 >= 0
   *   ⇒ 此后**所有** `emitThrottled()` 都被 `return` 静默吞掉。
   *   真机症状：网页上传进度条卡在 19%（122MB）不动，而传输完全正常
   *   （`[UP]` 日志持续打到 586MB）—— 同一个循环，上报死了、传输活着。
   *
   * 【修法】闸门不再只依赖回调清除：距上次真正 emit 超过本值就**强制放行**，
   *   最多晚这么多毫秒必然自愈。
   */
  private static readonly EMIT_PENDING_MAX_MS: number = 500;"""
check(src, OLD_1, NEW_1, 'const')

# ---------------------------------------------------------------- 2. 闸门自愈
OLD_2 = """    if (this.pendingEmitTimer >= 0) {
      return;   // 已有排队，靠它兜底
    }
    this.pendingEmitTimer = setTimeout(() => {
      this.pendingEmitTimer = -1;
      this.lastEmitAt = Date.now();
      this.emit();
    }, 100 - gap);"""
NEW_2 = """    if (this.pendingEmitTimer >= 0) {
      // ★★ 5.1.30：闸门**时间自愈**。
      //   原来这里无条件 `return`，一旦排队定时器因主线程长任务被推迟/丢弃，
      //   `pendingEmitTimer` 就永久 >= 0 ⇒ 后续刷新全被吞掉
      //   （真机：进度条卡 19% 不动，而传输正常）。
      //   现在：超过 EMIT_PENDING_MAX_MS 没真正 emit 过，就无视残留闸门强制放行。
      const sinceLast: number = now - this.lastEmitAt;
      if (sinceLast < LanService.EMIT_PENDING_MAX_MS) {
        return;   // 排队还在有效期内，靠它兜底
      }
      // 残留闸门已失效 —— 清掉旧定时器防双重，然后直接放行
      clearTimeout(this.pendingEmitTimer);
      this.pendingEmitTimer = -1;
      this.lastEmitAt = now;
      this.emit();
      return;
    }
    this.pendingEmitTimer = setTimeout(() => {
      this.pendingEmitTimer = -1;
      this.lastEmitAt = Date.now();
      this.emit();
    }, 100 - gap);"""
check(src, OLD_2, NEW_2, 'gate')

# ---------------------------------------------------------------- 3. 版本号
OLD_3 = '"versionCode": 5000129'
NEW_3 = '"versionCode": 5000130'
app_src = io.open(APP, encoding='utf-8').read()
check(app_src, OLD_3, NEW_3, 'versionCode')

OLD_4 = '"versionName": "5.1.29"'
NEW_4 = '"versionName": "5.1.30"'
check(app_src, OLD_4, NEW_4, 'versionName')

# ---------------------------------------------------------------- 备份 + 落盘
if not os.path.isdir(BAK):
    os.makedirs(BAK)
shutil.copyfile(SVC, os.path.join(BAK, 'LanService.ets.v5130pre'))
shutil.copyfile(APP, os.path.join(BAK, 'app.json5.v5130pre'))

out = src.replace(OLD_1, NEW_1).replace(OLD_2, NEW_2)
io.open(SVC, 'w', encoding='utf-8', newline='\n').write(out)
io.open(APP, 'w', encoding='utf-8', newline='\n').write(
    app_src.replace(OLD_3, NEW_3).replace(OLD_4, NEW_4))

# ---------------------------------------------------------------- 复核
chk = io.open(SVC, encoding='utf-8').read()
assert 'EMIT_PENDING_MAX_MS: number = 500' in chk, '常量未写入'
assert chk.count('EMIT_PENDING_MAX_MS') == 3, '引用数应为 3（声明 + 注释 + 使用）'
assert 'const sinceLast: number = now - this.lastEmitAt;' in chk, '自愈分支未写入'
assert io.open(APP, encoding='utf-8').read().count('5000130') == 1, 'versionCode 未更新'
print('OK 5.1.30 applied')
