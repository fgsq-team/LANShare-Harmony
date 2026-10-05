# -*- coding: utf-8 -*-
"""
5.0.53② （vivi 2026-10-02 要求）
「文件另存到本地后，也把沙箱里的删除了」—— 不再留双份。

与「存相册后删沙箱副本」（5.0.38 起）统一口径：内容已经**落到应用之外**的，
就把它从沙箱里清掉。
⚠️ 只删**确实保存成功**的那些：取消 / 失败的一律不动 —— 那份是唯一的一份。

幂等：哨兵 `savedPaths`，打过直接 SKIP。写文件保持 LF。
"""
import io, sys

EX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\service\ExportService.ets'
IX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'

SENTINEL = 'savedPaths'

# ---------------------------------------------------------------- 1. SaveOutcome 加字段
EX_A_OLD = """  /** 实际成功保存的条数 */
  saved: number = 0;
  /** 给用户看的文案 */
  msg: string = '';
"""
EX_A_NEW = """  /** 实际成功保存的条数 */
  saved: number = 0;
  /**
   * ★ 5.0.53：**成功保存过的那些源文件**（沙箱绝对路径）。
   * 调用方据此把沙箱副本删掉 —— vivi 2026-10-02 要求「另存到本地后不留双份」。
   * ⚠️ 只收成功的：失败 / 用户取消的一律不收（那份还没落到应用之外，是唯一的一份）。
   */
  savedPaths: string[] = [];
  /** 给用户看的文案 */
  msg: string = '';
"""

# ---------------------------------------------------------------- 2. saveMany 记录成功路径
EX_B_OLD = """    for (let i = 0; i < n; i++) {
      const msg: string = ExportService.copyTo(files[i].path, uris[i], files[i].name);
      if (msg.startsWith('已保存')) {
        ok += 1;
      } else if (firstErr.length === 0) {
        firstErr = msg;
      }
    }
"""
EX_B_NEW = """    for (let i = 0; i < n; i++) {
      const msg: string = ExportService.copyTo(files[i].path, uris[i], files[i].name);
      if (msg.startsWith('已保存')) {
        ok += 1;
        // ★ 5.0.53：记下成功的源路径，UI 拿去删沙箱副本
        out.savedPaths.push(files[i].path);
      } else if (firstErr.length === 0) {
        firstErr = msg;
      }
    }
"""

# ---------------------------------------------------------------- 3. Index.saveAsFile 删沙箱
IX_A_OLD = """  private async saveAsFile(f: ReceivedFile): Promise<void> {
    const ctx: common.UIAbilityContext =
      this.getUIContext().getHostContext() as common.UIAbilityContext;
    const msg: string = await ExportService.saveAs(ctx, f.path, f.name);
    this.toast(msg);
    if (msg.startsWith('已保存')) {
      this.refreshReceived();
    }
  }
"""
IX_A_NEW = """  private async saveAsFile(f: ReceivedFile): Promise<void> {
    const ctx: common.UIAbilityContext =
      this.getUIContext().getHostContext() as common.UIAbilityContext;
    const msg: string = await ExportService.saveAs(ctx, f.path, f.name);
    if (!msg.startsWith('已保存')) {
      // 取消 / 失败一律**不动**沙箱 —— 那份是唯一的一份（见 deleteOne 的注释）
      this.toast(msg);
      return;
    }
    // ★ 5.0.53（vivi 要求）：另存成功后**删掉沙箱副本**，不再留双份。
    //   与「存相册后删沙箱副本」同一口径：内容已经落到应用之外了。
    const err: string | null = ExportService.deleteFile(this.service.receiveRoot, f.path);
    this.toast(err === null ? `${msg}，沙箱副本已删除` : `${msg}（沙箱副本删除失败：${err}）`);
    this.refreshReceived();
  }
"""

# ---------------------------------------------------------------- 4. Index.batchSaveSelected
IX_B_OLD = """    const r: SaveOutcome = await ExportService.saveMany(ctx, picked);
    this.toast(r.msg);
    // ⚠️ 用户**取消**保存对话框时不能退出多选：
    //    他刚才勾了 N 个文件，一按取消就把勾选全清掉，等于白勾一遍。
    //    取消 ⇒ 原样停在多选界面（勾选、模式都保留），用户可以再点一次。
    if (r.cancelled) {
      return;
    }
    // 真正保存过（哪怕部分失败）才收起多选；失败也刷新一下，让大小/条数同步
    this.exitFileSelect();
    this.refreshReceived();
  }
"""
IX_B_NEW = """    const r: SaveOutcome = await ExportService.saveMany(ctx, picked);
    // ⚠️ 用户**取消**保存对话框时不能退出多选：
    //    他刚才勾了 N 个文件，一按取消就把勾选全清掉，等于白勾一遍。
    //    取消 ⇒ 原样停在多选界面（勾选、模式都保留），用户可以再点一次。
    if (r.cancelled) {
      this.toast(r.msg);
      return;
    }
    // ★ 5.0.53（vivi 要求）：已保存成功的那些**删掉沙箱副本**（不再留双份）。
    //   ⚠️ 只删 `r.savedPaths` 里的 —— 失败的那几个还没落到应用之外，删了就真没了。
    let cleaned: number = 0;
    for (let i: number = 0; i < r.savedPaths.length; i++) {
      if (ExportService.deleteFile(this.service.receiveRoot, r.savedPaths[i]) === null) {
        cleaned += 1;
      }
    }
    this.toast(cleaned > 0 ? `${r.msg}；已清理 ${cleaned} 个沙箱副本` : r.msg);
    // 真正保存过（哪怕部分失败）才收起多选；失败也刷新一下，让大小/条数同步
    this.exitFileSelect();
    this.refreshReceived();
  }
"""


def apply(path, pairs, label):
    s = io.open(path, encoding='utf-8', newline='').read()
    for i, (old, new) in enumerate(pairs):
        assert s.count(old) == 1, '%s 锚点#%d 命中 %d 次' % (label, i + 1, s.count(old))
        assert s.count(new) == 0, '%s 新文本#%d 此前已存在' % (label, i + 1)
    for old, new in pairs:
        s = s.replace(old, new)
    return s


ex_src = io.open(EX, encoding='utf-8', newline='').read()
if SENTINEL in ex_src:
    print('ALREADY APPLIED')
    sys.exit(0)

new_ex = apply(EX, [(EX_A_OLD, EX_A_NEW), (EX_B_OLD, EX_B_NEW)], 'ExportService')
new_ix = apply(IX, [(IX_A_OLD, IX_A_NEW), (IX_B_OLD, IX_B_NEW)], 'Index')

assert new_ex.count('out.savedPaths.push(') == 1
assert new_ex.count('savedPaths: string[] = [];') == 1
# ⚠️ 用精确串断言：裸 `r.savedPaths` 会被自己刚写的**注释**误报（本项目踩过）
assert new_ix.count('i < r.savedPaths.length') == 1
assert new_ix.count('r.savedPaths[i])') == 1
assert new_ix.count('沙箱副本已删除') == 1
assert new_ix.count('个沙箱副本') == 1

for tag, path in [('ExportService', EX), ('Index', IX)]:
    before = io.open(path, encoding='utf-8', newline='').read()
    after = new_ex if tag == 'ExportService' else new_ix
    delta = {}
    for ch in '{}()[]':
        delta[ch] = after.count(ch) - before.count(ch)
    print('%s 括号增量: %s' % (tag, delta))

io.open(EX, 'w', encoding='utf-8', newline='\n').write(new_ex)
io.open(IX, 'w', encoding='utf-8', newline='\n').write(new_ix)
print('OK: 5.0.53② 已应用')
