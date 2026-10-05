# -*- coding: utf-8 -*-
"""
v5.1.12 删掉「检测到上次闪退」的 toast 提示（vivi 22:0x）。

## 需求
「把检测到闪退的提示删除了」—— 起因是**每次升级软件后打开都会提示一次**。

★ 为什么升级后必现：`run.lock` / `crash.flag` 放在 `${ctx.filesDir}/`，
  升级 HAP 时 **`filesDir` 内容可能被系统清理/重建**（或标记还在、但新包的
  `prevCrashed` 读到了旧状态）⇒ 用户每次升级后的首次启动都看到这个提示。
  ⇒ 它对普通用户是**纯噪声**（用户没做任何事，凭什么被告知「上次闪退」）。

## 处置：只删 UI，**保留后台取证**（这是关键取舍）

★ **不能把整个闪退检测都删掉** ——
   `crashTail`（崩溃前最后 150 行日志挂到列表最前面）+ `ui_log.txt.1` 存档
   是**真机唯一的排障通路**（用户没 hdc，5.0.49 的原意）。
   删掉它 = 下次真闪退我**完全无法取证**，等于盲修。

所以本版只做三件事：
1. 删 `autoStart` 里的 `else if (prevCrashed)` **toast 分支**
   ⇒ 改为**只打一行日志**（`logAuto`）—— 需要时我能从日志里看到，
   用户界面干净。
2. 删 `crashTipShown` 字段（只为那个 toast 服务，没别的用途）。
3. `initLogFile` 里那条「⚠️ 检测到上次异常退出…」的 `pushLog` **保留**
   ⇒ 它在**日志页**里（不是弹窗），用户主动去看时能看到，仍是取证线索。

⚠️ 顺带提醒（写进代码注释）：`prevCrashed` / `crash.flag` 机制**全部保留**，
   别看到「提示删了」就以为「检测也删了」—— 那会让下次闪退变成盲修。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 改 1：删 toast 分支，改为只打日志
# =====================================================================
OLD1 = """      if (!ok) {
        this.toast(`自动开启失败：${this.snapshot.message}`);
      } else if (this.service.prevCrashed && !this.crashTipShown) {
        // 5.0.49：上次是闪退 —— 崩溃前的日志已经挂进日志列表最前面，
        //         明确引导用户去「复制日志」把它带出来（真机没有 hdc，这是唯一通路）
        // ★ 5.1.10：加一次性守卫 —— 切前台恢复共享会**再跑一次** `autoStart`，
        //   同一个闪退提示**不该弹第二次**。
        this.crashTipShown = true;
        this.toast('检测到上次闪退，点「复制日志」可把崩溃现场带出来');
      }"""
NEW1 = """      if (!ok) {
        this.toast(`自动开启失败：${this.snapshot.message}`);
      } else if (this.service.prevCrashed) {
        // ★★ 5.1.12（vivi 22:0x「把检测到闪退的提示删除了」）：**不弹 toast**。
        //
        // 【为什么删】`run.lock` / `crash.flag` 在 `filesDir` 里，**升级 HAP 时
        //   可能被系统清理/重建** ⇒ 用户**每次升级后首次启动**都会看到这条提示。
        //   而他什么都没做 ⇒ 纯噪声，且会让人以为「这软件一更新就崩」。
        //
        // 【⚠️ 只删 UI，检测与取证【全部保留】】
        //   `crashTail`（崩溃前 150 行挂到日志列表最前面）+ `ui_log.txt.1` 存档
        //   是**真机唯一的排障通路**（用户没 hdc，5.0.49 的原意）。
        //   删掉它 = 下次真闪退**完全无法取证**，只能盲修。
        //   ⇒ 这里改成**只打一行日志**：用户界面干净，我需要时仍能从日志看到。
        this.service.logAuto('检测到上次异常退出（闪退）：崩溃现场已挂在日志最前面');
      }"""

# =====================================================================
# 改 2：删 crashTipShown 字段
# =====================================================================
OLD2 = """  /** ★ 5.1.10：闪退提示**只弹一次**（切前台恢复共享会再跑 `autoStart`） */
  private crashTipShown: boolean = false;
"""
NEW2 = ""

# =====================================================================
# 版本号
# =====================================================================
OLDV = '"versionCode": 5000111'
NEWV = '"versionCode": 5000112'

REPL = [
    (OLD1, NEW1, 'P1 删 toast 改打日志'),
    (OLD2, NEW2, 'P2 删 crashTipShown 字段'),
]

s = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if '5.1.12' in s:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v5112pre'), 'w', encoding='utf-8', newline='\n').write(s)
io.open(os.path.join(BAK, 'app.json5.v5112pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成')

for old, new, tag in REPL:
    n = s.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s = s.replace(old, new, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.11"') == 1
s_ver = s_ver.replace('"versionName": "5.1.11"', '"versionName": "5.1.12"', 1)

# ---------------- 不变量 ----------------
# ① toast 与守卫已彻底消失
assert 'crashTipShown' not in s, 'crashTipShown 仍有残留'
assert '检测到上次闪退，点「复制日志」可把崩溃现场带出来' not in s, '旧 toast 文案仍在'
# ② 但检测与取证全部保留（★ 最关键的不变量）
assert 'this.service.prevCrashed' in s, 'prevCrashed 判断被误删'
assert '检测到上次异常退出（闪退）：崩溃现场已挂在日志最前面' in s, '应保留日志记录'
assert '复制日志' in s, '「复制日志」入口被误删（排障通路）'
assert 'logAuto' in s, 'logAuto 被误删'
# ③ 服务端的 crash.flag 机制一个都不动（本补丁只碰 Index.ets）
# 前几版成果仍在
assert '@State localStateTick: number = 0;' in s
assert 'private padHint(s: string, _tick: number = 0): string {' in s
assert s.count('this.markMessagesLocalByPaths(') == 3, \
    '批量记账应仍 3 处，实际 %d' % s.count('this.markMessagesLocalByPaths(')
assert 'private msgCarriesFileName(' in s
assert 'if (this.showAbout) {' in s
assert 'private diagSnapshot(' not in s and 'this.diagSnapshot(' not in s

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  Index.ets %d chars' % len(s))
print('OK  versionCode 5000111 -> 5000112 / 5.1.12')
