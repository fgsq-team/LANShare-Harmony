# -*- coding: utf-8 -*-
"""
v5.1.10 修「每次启动都提示『检测到上次闪退』」（vivi 21:5x）。

## ★ 根因（读代码确认，非推测）

`initLogFile` 的流程是：
1. `accessSync(run.lock)` —— 存在则 `prevCrashed = true`
2. ……
3. **最后**又 `openSync(run.lock, CREATE|TRUNC)` **重写**它（写入本次启动时间）

★ 第 3 步在**同一次启动里就把 `run.lock` 写回来了** ⇒ 下次启动第 1 步
`accessSync` **必然为 true** ⇒ **`prevCrashed` 每次启动都是 true**
⇒ `Index.autoStart`（`:859`）的 toast **每次启动都弹**。

★ 而 `markCleanExit`（正常退出时由 `EntryAbility.onDestroy` 调）会删掉它 ——
**但那次闪退恰好没有走到 `onDestroy`** ⇒ 文件留下。
  ⚠️ 于是「闪退那一次」是**唯一**该弹的场景，可它之后**每一次正常启动**
  也会弹（因为第 3 步又写回来了）⇒ **提示变得毫无意义**。

## 修法（三处一起，缺一不可）

1. **判据换成「lock 里的内容」而不是「lock 是否存在」**：
   `run.lock` 写的是启动时间戳，但它**存在本身没有意义**（第 3 步每次都写）。
   ⇒ 改为：lock 存在 **且** 本次启动的标记与 lock 里的一致 ⇒ 说明
   「**这次启动还没走到 markCleanExit**」—— 但这在本次启动内天然为真。
   ⇒ **更稳的判据**：把「上一次是否闪退」**持久化成一个独立标记**：
   启动时若 lock 存在 ⇒ 写 `crash.flag`；`markCleanExit` 时**同时删 lock 和 flag**。
   下次启动只看 `crash.flag` ⇒ **不依赖 lock 的存在性**。

2. **`Index.autoStart` 加「一次性」守卫**：
   即使判据对了，**同一进程内**也不该重复弹（`autoStart` 有 `busy` 幂等，
   但切前台恢复共享可能再触发一次）⇒ 加一个 `crashTipShown` 标记。

3. **提示语加「日志已保留」信息**并指向「复制日志」—— 保持 5.0.49 的原意不变。

## 为什么不干脆删掉这个提示
它是 **真机唯一的排障通路**（没 hdc 时崩溃现场只能靠「复制日志」带走，
见 5.0.49 的注释）。**提示本身有价值，要修的是「它该只在真闪退时出现」。**
"""
import io
import sys
import os

SVC = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\service\LanService.ets'
IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 服务端 3 处
# =====================================================================

# --- S1：新增 crashFlag 字段 ---
OLDS1 = """  /** `run.lock`：启动时写、正常退出时删。下次启动还在 => 上次是崩的 */
  private lockFile: string = '';"""
NEWS1 = """  /** `run.lock`：启动时写、正常退出时删。 */
  private lockFile: string = '';
  /**
   * ★ 5.1.10：`crash.flag` —— 「上一次是闪退」的**持久化标记**。
   *
   * ⚠️⚠️ **为什么不能只看 `run.lock` 存不存在**（这是 5.0.49 一直以来的 bug）：
   *   `initLogFile` 在**同一次启动的末尾**又 `openSync(run.lock, CREATE|TRUNC)`
   *   把它写回来 ⇒ 下次启动 `accessSync` **必然为 true**
   *   ⇒ `prevCrashed` **每次启动都是 true** ⇒ 提示**每次都弹**（vivi 21:5x 反馈）。
   *
   * ★ 正确口径 = 「**上次退出时没走到 `markCleanExit`**」——
   *   那正是闪退的定义。所以：**lock 存在 ⇒ 本次启动写 `crash.flag`**，
   *   而 `markCleanExit` **同时删掉 lock 与 flag**。
   *   下次启动**只看 flag**（不看 lock 的存在性）⇒ 提示只在真闪退后出现一次。
   */
  private crashFlag: string = '';"""

# --- S2：initLogFile 读 flag、写 flag ---
OLDS2 = """    this.logFile = `${ctx.filesDir}/ui_log.txt`;
    this.lockFile = `${ctx.filesDir}/run.lock`;
    let lockExists: boolean = false;
    try {
      lockExists = fileIo.accessSync(this.lockFile);
    } catch (e) {
      lockExists = false;
    }
    if (lockExists) {"""
NEWS2 = """    this.logFile = `${ctx.filesDir}/ui_log.txt`;
    this.lockFile = `${ctx.filesDir}/run.lock`;
    this.crashFlag = `${ctx.filesDir}/crash.flag`;
    // ★ 5.1.10：**「上次是否闪退」只看 `crash.flag`**，不再看 `run.lock` 存不存在 ——
    //   `run.lock` 会在本次启动末尾被重写，它的存在**永远**为真
    //   ⇒ 用它当判据 = 每次启动都判成闪退（5.0.49 起的 bug，vivi 21:5x 反馈）。
    //   ★ flag 的完整生命周期（**三步缺一不可**）：
    //     ① 本行读它 —— 存在 = 上次闪退（下面进 if 取现场）
    //     ② 函数末尾写它（见 S4）—— 「本次会话已起来」
    //     ③ markCleanExit 删它 —— 「本次正常退出了」
    //   ⇒ 正常退出 → 被删 → 下次不提示；中途崩 → 留下 → 下次提示一次。
    let flagExists: boolean = false;
    try {
      flagExists = fileIo.accessSync(this.crashFlag);
    } catch (e) {
      flagExists = false;
    }
    if (flagExists) {"""

# --- S3：markCleanExit 同时删 flag ---
OLDS3 = """  markCleanExit(): void {
    if (this.lockFile.length > 0) {
      try {
        fileIo.unlinkSync(this.lockFile);
      } catch (e) {
        // 已经不在了
      }"""
NEWS3 = """  markCleanExit(): void {
    // ★ 5.1.10：**必须同时删 `crash.flag`** —— 只删 `run.lock` 的话，
    //   flag 会留下 ⇒ 下次启动仍然判成「上次闪退」⇒ 提示反复弹（vivi 21:5x）。
    if (this.crashFlag.length > 0) {
      try {
        fileIo.unlinkSync(this.crashFlag);
      } catch (e) {
        // 已经不在了
      }
    }
    if (this.lockFile.length > 0) {
      try {
        fileIo.unlinkSync(this.lockFile);
      } catch (e) {
        // 已经不在了
      }"""

# --- S4：本次启动末尾写 crash.flag ---
OLDS4 = """    // 最后才写 run.lock —— 上面任何一步崩掉都不该被误判成「本次正常」
    try {
      const lf: fileIo.File = fileIo.openSync(this.lockFile,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);
      fileIo.writeSync(lf.fd, `${new Date().toString()}\\n`);
      fileIo.closeSync(lf);
    } catch (e) {
      // 忽略
    }
  }"""
NEWS4 = """    // 最后才写 run.lock —— 上面任何一步崩掉都不该被误判成「本次正常」
    try {
      const lf: fileIo.File = fileIo.openSync(this.lockFile,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);
      fileIo.writeSync(lf.fd, `${new Date().toString()}\\n`);
      fileIo.closeSync(lf);
    } catch (e) {
      // 忽略
    }
    // ★ 5.1.10：把「本次启动已完成初始化」记到 `crash.flag` —— 它**存在即表示
    //   「上一次会话没有走到 markCleanExit」**（也就是闪退）。
    //   `markCleanExit` 正常退出时会把它删掉 ⇒ 语义闭合。
    try {
      const cf: fileIo.File = fileIo.openSync(this.crashFlag,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);
      fileIo.writeSync(cf.fd, `${new Date().toString()}\\n`);
      fileIo.closeSync(cf);
    } catch (e) {
      // 忽略
    }
  }"""

SVC_REPL = [
    (OLDS1, NEWS1, 'S1 crashFlag 字段'),
    (OLDS2, NEWS2, 'S2 读 flag 而非 lock'),
    (OLDS3, NEWS3, 'S3 markCleanExit 删 flag'),
    (OLDS4, NEWS4, 'S4 末尾写 flag'),
]

# =====================================================================
# 页面 1 处：toast 一次性守卫
# =====================================================================
OLDP1 = """      } else if (this.service.prevCrashed) {
        // 5.0.49：上次是闪退 —— 崩溃前的日志已经挂进日志列表最前面，
        //         明确引导用户去「复制日志」把它带出来（真机没有 hdc，这是唯一通路）
        this.toast('检测到上次闪退，请点「复制日志」把崩溃现场发出来');
      }"""
NEWP1 = """      } else if (this.service.prevCrashed && !this.crashTipShown) {
        // 5.0.49：上次是闪退 —— 崩溃前的日志已经挂进日志列表最前面，
        //         明确引导用户去「复制日志」把它带出来（真机没有 hdc，这是唯一通路）
        // ★ 5.1.10：加一次性守卫 —— 切前台恢复共享会**再跑一次** `autoStart`，
        //   同一个闪退提示**不该弹第二次**。
        this.crashTipShown = true;
        this.toast('检测到上次闪退，点「复制日志」可把崩溃现场带出来');
      }"""

# 字段声明（放在 busy 附近）
OLDP2 = """  /** 「关于」弹窗开关 */"""
NEWP2 = """  /** ★ 5.1.10：闪退提示**只弹一次**（切前台恢复共享会再跑 `autoStart`） */
  private crashTipShown: boolean = false;
  /** 「关于」弹窗开关 */"""

# =====================================================================
# 版本号
# =====================================================================
OLDV = '"versionCode": 5000109'
NEWV = '"versionCode": 5000110'

SVC_REPL += []  # 保持类型一致

# =====================================================================
# 执行
# =====================================================================
s_svc = io.open(SVC, encoding='utf-8').read()
s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if 'crashFlag' in s_svc:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'LanService.ets.v5110pre'), 'w', encoding='utf-8', newline='\n').write(s_svc)
io.open(os.path.join(BAK, 'Index.ets.v5110pre'), 'w', encoding='utf-8', newline='\n').write(s_idx)
io.open(os.path.join(BAK, 'app.json5.v5110pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成（3 个文件）')

for old, new, tag in SVC_REPL:
    n = s_svc.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s_svc = s_svc.replace(old, new, 1)

for old, new, tag in ((OLDP1, NEWP1, 'P1 toast 守卫'), (OLDP2, NEWP2, 'P2 守卫字段')):
    n = s_idx.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s_idx = s_idx.replace(old, new, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.9"') == 1
s_ver = s_ver.replace('"versionName": "5.1.9"', '"versionName": "5.1.10"', 1)

# ---------------- 不变量 ----------------
# 服务端
assert 'private crashFlag: string = \'\';' in s_svc
assert 'this.crashFlag = `${ctx.filesDir}/crash.flag`;' in s_svc
# ★ 关键：判据处必须用 crashFlag，**不能**用 accessSync(lockFile)
i_init = s_svc.find('  initLogFile(ctx: common.UIAbilityContext): void {')
j_init = s_svc.find('\n  }', i_init)
init_seg = s_svc[i_init:j_init]
assert 'fileIo.accessSync(this.crashFlag)' in init_seg, '判据未改用 crashFlag'
assert 'fileIo.accessSync(this.lockFile)' not in init_seg, '仍用 lockFile 判据 ⇒ bug 未修'
# flag 的写入与删除成对
assert 'fileIo.openSync(this.crashFlag,' in init_seg, '启动时未写 crash.flag'
i_clean = s_svc.find('  markCleanExit(): void {')
j_clean = s_svc.find('\n  }', i_clean)
clean_seg = s_svc[i_clean:j_clean]
assert 'fileIo.unlinkSync(this.crashFlag)' in clean_seg, 'markCleanExit 未删 crash.flag'
assert 'fileIo.unlinkSync(this.lockFile)' in clean_seg, 'markCleanExit 的 lock 删除被破坏'
# 页面
assert 'private crashTipShown: boolean = false;' in s_idx
assert 'this.service.prevCrashed && !this.crashTipShown' in s_idx
assert 'this.crashTipShown = true;' in s_idx
# 「复制日志」入口必须还在（这是排障通路）
assert '复制日志' in s_idx
# 前几版成果仍在
assert '@State localStateTick: number = 0;' in s_idx
assert 'private msgCarriesFileName(' in s_idx
assert 'if (this.showAbout) {' in s_idx
assert 'logAuto' in s_svc
assert 'private diagSnapshot(' not in s_idx and 'this.diagSnapshot(' not in s_idx

io.open(SVC, 'w', encoding='utf-8', newline='\n').write(s_svc)
io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s_idx)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  LanService.ets %d chars' % len(s_svc))
print('OK  Index.ets     %d chars' % len(s_idx))
print('OK  versionCode 5000109 -> 5000110 / 5.1.10')
