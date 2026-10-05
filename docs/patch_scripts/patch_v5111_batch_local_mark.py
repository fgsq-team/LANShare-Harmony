# -*- coding: utf-8 -*-
"""
v5.1.11 修「批量删除/清空后气泡状态不更新」（vivi 22:0x）。

## 根因（读代码确认，非推测）

`markMessagesLocal` 只有 **2 个调用点**（`saveAsFile` / `deleteOne`），
而**删除沙箱文件的入口有 4 处** ⇒ **漏了 2 处**：

| # | 入口 | 位置 | 状态 | 应记 |
|---|---|---|---|---|
| ① 单条另存为 | `saveAsFile` | :1668 | ✅ 已记 `已存本地` | — |
| ② 单条删除 | `deleteOne` | :1687 | ✅ 已记 `已删除` | — |
| ③ **多选批量另存** | `batchSaveSelected` | :1810 | ❌ **漏** | `已存本地` |
| ④ **多选批量删除** | `batchDeleteSelected` | :1832 | ❌ **漏** | `已删除` |
| ⑤ **清空所有** | `deleteAllFiles` | :1710 | ❌ **漏**（vivi 22:0x 反馈的就是这条） | `已删除` |
| ⑥ 存相册后删沙箱 | `autoSaveAlbumBatch` | :4278 | ⚠️ **刻意不记** | 那是**媒体**，走相册索引（`setAlbumIndex`），语义不同 |

★ 5.0.45 早就写过一条教训：「写完一条路径要问『还有别的路径会调同一个函数吗』」——
  本轮是它的**镜像**：「**同一个动作有多条入口，每条都要记账**」。

## 修法

给 ③④⑤ 三处补记账，并新增一个**按路径反查消息**的 helper
（③④⑤ 手里只有 `ReceivedFile.path` / 路径数组，**没有文件名**）。

⚠️ 关键：**按路径反查**要先看 `receivedFiles`（路径 → 名字），
  而「清空」是在 `deleteAll` **之后**才记 —— 那时 `receivedFiles` 还没刷新（仍是旧值），
  **恰好可以用**。⇒ **必须在 `refreshReceived()` 之前取名字**。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 改 1：新增 markMessagesLocalByPaths（按路径反查名字再记账）
# =====================================================================
OLD1 = """  /**
   * ★ 5.1.2：按**文件名**反查消息 id 并批量写本地落地状态。"""
NEW1 = """  /**
   * ★ 5.1.11：按**路径**批量记账（批量删除 / 清空 / 批量另存用）。
   *
   * ⚠️ **必须在 `refreshReceived()` 之前调用** —— 那些入口删完文件才调 refresh，
   *   而 `receivedFiles` 是**刷新前**的旧值，**恰好还留着「路径 → 文件名」的映射**。
   *   刷新之后映射就没了 ⇒ 拿不到名字 ⇒ 记不上账。
   *
   * ⚠️ 与 `markMessagesLocal` 的区别：那个按**文件名**查（单条入口手里是 `ReceivedFile`），
   *   这个按**路径**查（批量入口手里只有路径数组）。
   *   两者最终都走同一条消息匹配逻辑（`msgCarriesFileName`）。
   */
  private markMessagesLocalByPaths(paths: string[], state: string): void {
    if (paths.length === 0 || state.length === 0) {
      return;
    }
    for (let i: number = 0; i < paths.length; i++) {
      const p: string = paths[i];
      let name: string = Index.baseName(p);
      if (name.length === 0) {
        continue;
      }
      // 优先用 receivedFiles 里的原始名（可能带去重后缀，与消息里的完全一致）
      for (let k: number = 0; k < this.receivedFiles.length; k++) {
        if (this.receivedFiles[k].path === p) {
          name = this.receivedFiles[k].name;
          break;
        }
      }
      this.markMessagesLocal(name, state);
    }
  }

  /**
   * ★ 5.1.2：按**文件名**反查消息 id 并批量写本地落地状态。"""

# =====================================================================
# 改 2：deleteAllFiles（清空所有）
# =====================================================================
OLD2 = """    const r: DeleteResult = ExportService.deleteAll(this.service.receiveRoot);
    this.toast(r.failed === 0
      ? `已删除 ${r.ok} 个文件`
      : `已删除 ${r.ok} 个，失败 ${r.failed} 个（${r.firstError}）`);
    this.refreshReceived();"""
NEW2 = """    // ★ 5.1.11：先把**路径 → 文件名**记下来（此刻 receivedFiles 还是旧值），
    //   删完并 refreshReceived 之后就查不到了。
    const gonePaths: string[] = ExportService.allPaths(this.service.receiveRoot).slice();
    const r: DeleteResult = ExportService.deleteAll(this.service.receiveRoot);
    this.toast(r.failed === 0
      ? `已删除 ${r.ok} 个文件`
      : `已删除 ${r.ok} 个，失败 ${r.failed} 个（${r.firstError}）`);
    // ★ 5.1.11：清空也要记账 —— 否则消息页气泡永远停在「点击查看」
    //   （vivi 22:0x 反馈：单条删除会同步，清空不会）。
    if (r.ok > 0) {
      this.markMessagesLocalByPaths(gonePaths, Index.HINT_LOCAL_DELETED);
    }
    this.refreshReceived();"""

# =====================================================================
# 改 3：batchDeleteSelected（多选批量删除）
# =====================================================================
OLD3 = """    const r: DeleteResult = ExportService.deleteFiles(this.service.receiveRoot, paths);
    this.toast(r.failed === 0
      ? `已删除 ${r.ok} 个文件`
      : `已删除 ${r.ok} 个，失败 ${r.failed} 个（${r.firstError}）`);
    this.exitFileSelect();
    this.refreshReceived();"""
NEW3 = """    const r: DeleteResult = ExportService.deleteFiles(this.service.receiveRoot, paths);
    this.toast(r.failed === 0
      ? `已删除 ${r.ok} 个文件`
      : `已删除 ${r.ok} 个，失败 ${r.failed} 个（${r.firstError}）`);
    // ★ 5.1.11：批量删除同样要记账（与单条 deleteOne 口径一致）。
    //   ⚠️ 必须在 exitFileSelect / refreshReceived **之前**——
    //   后者会清掉 receivedFiles，「路径 → 文件名」的映射就没了。
    if (r.ok > 0) {
      this.markMessagesLocalByPaths(paths, Index.HINT_LOCAL_DELETED);
    }
    this.exitFileSelect();
    this.refreshReceived();"""

# =====================================================================
# 改 4：batchSaveSelected（多选批量另存）—— 记「已存本地」
# =====================================================================
OLD4 = """    let cleaned: number = 0;
    for (let i: number = 0; i < r.savedPaths.length; i++) {
      if (ExportService.deleteFile(this.service.receiveRoot, r.savedPaths[i]) === null) {
        cleaned += 1;
      }
    }
    this.toast(cleaned > 0 ? `${r.msg}；已清理 ${cleaned} 个沙箱副本` : r.msg);"""
NEW4 = """    // ★ 5.1.11：批量另存也要记「已存本地」（与单条 saveAsFile 口径一致）。
    //   ⚠️ 只记**删除成功**的那些（`deleteFile` 返回 null）——
    //   删失败说明内容还在沙箱里，不该显示「已存本地」（5.1.2 定的口径）。
    //   ⚠️ 在**同一个循环里**收集，不要另起一轮 deleteFile（会删两次）。
    let cleaned: number = 0;
    const savedOk: string[] = [];
    for (let i: number = 0; i < r.savedPaths.length; i++) {
      if (ExportService.deleteFile(this.service.receiveRoot, r.savedPaths[i]) === null) {
        cleaned += 1;
        savedOk.push(r.savedPaths[i]);
      }
    }
    if (savedOk.length > 0) {
      this.markMessagesLocalByPaths(savedOk, Index.HINT_LOCAL_SAVED);
    }
    this.toast(cleaned > 0 ? `${r.msg}；已清理 ${cleaned} 个沙箱副本` : r.msg);"""

# =====================================================================
# 版本号
# =====================================================================
OLDV = '"versionCode": 5000110'
NEWV = '"versionCode": 5000111'

REPL = [
    (OLD1, NEW1, 'P1 新增 markMessagesLocalByPaths'),
    (OLD2, NEW2, 'P2 清空记账'),
    (OLD3, NEW3, 'P3 批量删除记账'),
    (OLD4, NEW4, 'P4 批量另存记账'),
]

s = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if 'markMessagesLocalByPaths' in s:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v5111pre'), 'w', encoding='utf-8', newline='\n').write(s)
io.open(os.path.join(BAK, 'app.json5.v5111pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成')

for old, new, tag in REPL:
    n = s.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s = s.replace(old, new, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.10"') == 1
s_ver = s_ver.replace('"versionName": "5.1.10"', '"versionName": "5.1.11"', 1)

# ---------------- 不变量 ----------------
assert 'private markMessagesLocalByPaths(paths: string[], state: string): void {' in s
# 三处都记了账
# ⚠️ 判据要说清：**定义是 `private markMessagesLocalByPaths(`（不带 `this.`）**，
#   所以只数**调用点** = 3 处。上一版写成 4（含定义）⇒ 落盘前拦下。
assert s.count('this.markMessagesLocalByPaths(') == 3, \
    '应有 3 处调用，实际 %d' % s.count('this.markMessagesLocalByPaths(')
assert 'private markMessagesLocalByPaths(paths: string[], state: string): void {' in s
assert 'this.markMessagesLocalByPaths(gonePaths, Index.HINT_LOCAL_DELETED);' in s
assert 'this.markMessagesLocalByPaths(paths, Index.HINT_LOCAL_DELETED);' in s
assert 'this.markMessagesLocalByPaths(savedOk, Index.HINT_LOCAL_SAVED);' in s
# ⚠️ 记账必须在 refreshReceived / exitFileSelect 之前
for fn, marker in (('deleteAllFiles', 'markMessagesLocalByPaths(gonePaths'),
                   ('batchDeleteSelected', 'markMessagesLocalByPaths(paths')):
    i = s.find('  private async %s(' % fn)
    j = s.find('\n  }', i)
    seg = s[i:j]
    assert seg.index(marker) < seg.index('this.refreshReceived()'), \
        '%s: 记账必须在 refreshReceived 之前（否则名字查不到）' % fn
# ⚠️ 批量另存不能重复删文件
i = s.find('  private async batchSaveSelected(')
j = s.find('\n  }', i)
save_seg = s[i:j]
assert save_seg.count('ExportService.deleteFile(this.service.receiveRoot, r.savedPaths[i])') == 1, \
    '批量另存的 deleteFile 被重复调用了（会删两次）'
# 既有单条记账仍在
assert s.count('this.markMessagesLocal(f.name, Index.HINT_LOCAL_SAVED);') == 1
assert s.count('this.markMessagesLocal(f.name, Index.HINT_LOCAL_DELETED);') == 1
# 前几版成果仍在
assert '@State localStateTick: number = 0;' in s
assert 'private padHint(s: string, _tick: number = 0): string {' in s
assert 'private msgCarriesFileName(' in s
assert 'if (this.showAbout) {' in s
assert 'private crashTipShown: boolean = false;' in s
assert 'private diagSnapshot(' not in s and 'this.diagSnapshot(' not in s

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  Index.ets %d chars' % len(s))
print('OK  versionCode 5000110 -> 5000111 / 5.1.11')
