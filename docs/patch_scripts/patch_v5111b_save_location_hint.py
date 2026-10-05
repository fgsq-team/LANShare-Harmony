# -*- coding: utf-8 -*-
"""
v5.1.1（与「非媒体提示」同批）：文件页顶部说明补一句「可点击『另存为』保存到本地」。

【为什么要加】
`saveLocationHint()` 原来只说「落盘位置：<沙箱路径>」。但那个路径**在系统「文件管理」里
根本看不到**（沙箱隔离），对普通用户等于「文件在哪？拿不出来」。
本项目里「另存为」是**唯一的取文件通道**（文件页注释 5707 行已写明），
但顶部说明**一个字都没提** ⇒ 用户不知道要点那个按钮。

【改法】
`saveLocationHint()` 追加 ` · 可点击「另存为」保存到本地`。
⚠️ 仅当 `receivedFiles.length > 0` 时才追加 —— 空列表时提「另存为」是噪声。
⚠️ `fileSelectMode` 下那一行显示的是多选提示（`? :` 三元已处理），不受影响。

★ 为什么加在**这个方法**里而不是渲染处：它是纯展示字符串的拼装，
  而「有没有文件」这个判据必须在**同一处**判定 —— 拆开就会出现
  「文案说有按钮、实际没有」的不一致（5.0.75 刚踩过「判据与展示不同源」）。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 改 1：saveLocationHint 追加「可点击『另存为』保存到本地」
# =====================================================================
OLD1 = """  /** 当前落盘位置说明，直接给用户看 */
  private saveLocationHint(): string {
    const loc: string = this.snapshot.saveLocation;
    return `落盘位置：${loc.length > 0 ? loc : '共享未开启'}`;
  }"""

NEW1 = """  /**
   * 当前落盘位置说明，直接给用户看。
   *
   * ★ 5.1.1（vivi 21:02）：追加「可点击『另存为』保存到本地」。
   *   原因：那个沙箱路径在系统「文件管理」里**根本看不到**（沙箱隔离），
   *   只报路径对普通用户等于「拿不出来」。而「另存为」是本项目**唯一的取文件通道**
   *   （文件页注释已写明），顶部说明却一个字都没提。
   *   ⚠️ 仅在**有文件时**追加 —— 空列表提「另存为」是噪声。
   *   ⚠️ 判据与文案必须**在同一处**判定：拆开会出现「文案说有、实际没有」的不一致
   *   （5.0.75 刚踩过「判据与展示不同源」）。
   */
  private saveLocationHint(): string {
    const loc: string = this.snapshot.saveLocation;
    const where: string = `落盘位置：${loc.length > 0 ? loc : '共享未开启'}`;
    if (this.receivedFiles.length === 0) {
      return where;
    }
    return `${where} · 可点击「另存为」保存到本地`;
  }"""

# =====================================================================
# 改 2：多选批量「另存为」也一并提及（用户可能只想找「一个入口」）
#   —— 底部条已有 `另存为 (N)`，顶部说明在多选态被三元换掉，故这里只需注释说明。
# =====================================================================
OLD2 = """      Text(this.fileSelectMode ? '点击文件可切换勾选（长按同样有效）' : this.saveLocationHint())"""
NEW2 = """      // ★ 5.1.1：非多选态时 `saveLocationHint()` 里已含「可点击『另存为』保存到本地」；
      //   多选态换成勾选提示（底部条本来就有 `另存为 (N)`，两处入口都指得到）。
      Text(this.fileSelectMode ? '点击文件可切换勾选（长按同样有效）' : this.saveLocationHint())"""

REPL = [
    (OLD1, NEW1, '改1 saveLocationHint 追加提示'),
    (OLD2, NEW2, '改2 渲染点加注释'),
]

s0 = io.open(IDX, encoding='utf-8').read()
SENT = '可点击「另存为」保存到本地'
if SENT in s0:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v5111bpre'), 'w', encoding='utf-8', newline='\n').write(s0)
print('备份完成')

s = s0
for old, new, tag in REPL:
    n = s.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s = s.replace(old, new, 1)

# ---- 不变量 ----
assert s.count(SENT) == 1, s.count(SENT)          # 只在方法体内出现一次（改2 注释是概述，不含整句）
assert 'return where;' in s
assert "return `${where} · 可点击「另存为」保存到本地`;" in s
# 5.1.1 的非媒体修复仍在
assert "private static readonly HINT_FILE: string = '点击查看';" in s
assert 'private bubbleFooterText(m: ChatMessage, mediaPath: string): string {' in s
# 多选三元未被破坏
assert s.count("this.fileSelectMode ? '点击文件可切换勾选（长按同样有效）' : this.saveLocationHint()") == 1
# 版本号仍是 5000101（本批不再动）
v = io.open(r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5', encoding='utf-8').read()
assert '"versionCode": 5000101' in v
assert '"versionName": "5.1.1"' in v

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
print('OK  Index.ets %d -> %d' % (len(s0), len(s)))
