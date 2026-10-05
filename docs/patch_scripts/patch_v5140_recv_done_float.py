# -*- coding: utf-8 -*-
"""
5.1.40 —— 所有「接收完成」都给浮层完成提示，保留 3 秒

【问题】
  网页上传有完成提示（`onWebUploadEnd`：显示完成态、1.5s 后清空），
  但**私有协议**（v4 / v5 / v5 分片 / FileTransfer）走的是 `onTransferReport`，
  它在 `r.done` 分支里**第一件事就是 `transferText = ''`**
  ⇒ 完成态一闪而过，用户基本看不到（这与 5.1.28 修的是同一个坑，
  当时只修了网页那条路径，漏了协议侧）。

【改法】
  1. 抽一个公共方法 `showRecvDoneFloat(text)`：
     设完成态 → emit → 3 秒后清空（复用并重命名原 `uploadDoneTimer`）。
     ⚠️ **清空动作必须仍然发生** —— 5.0.51 顺序契约：
       `transferText` 的「非空 → 空」跳变是**文件页自动刷新**的触发信号。
  2. `onWebUploadEnd` 成功分支改用它，时长 1500ms → **3000ms**。
  3. `onTransferReport` 的 `done && ok && 接收方向` 分支也调它
     ⇒ v4 / v5 / v5 分片 / FileTransfer 四条协议路径**一处覆盖**。
  4. 文案统一为 `✓ 接收完成：{文件名}（{大小}）`。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
LS = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'LanService.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

s = io.open(LS, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

SEN = "showRecvDoneFloat"
if SEN in s:
    print('ALREADY APPLIED'); sys.exit(0)

blocks = []
def cut(tag, old, new='', chk=True):
    blocks.append((tag, old, new, chk))

# ── ① 字段重命名：uploadDoneTimer → doneFloatTimer（用途扩大了）─────
cut('field-rename',
    "   * ★ 5.1.28：「上传完成」浮层的清除定时器句柄，-1 = 没挂。\n"
    "   *   必须存句柄：连着传多个文件时，前一次的定时器要作废，\n"
    "   *   否则会提前抹掉后一次的完成提示。\n"
    "   */\n"
    "  private uploadDoneTimer: number = -1;",
    "   * 「接收完成」浮层的清除定时器句柄，-1 = 没挂。\n"
    "   *   必须存句柄：连着传多个文件时，前一次的定时器要作废，\n"
    "   *   否则会提前抹掉后一次的完成提示。\n"
    "   * ★ 5.1.40：原先只服务网页上传（故名 uploadDoneTimer），\n"
    "   *   现由 `showRecvDoneFloat` 统一供**所有**接收路径使用。\n"
    "   */\n"
    "  private doneFloatTimer: number = -1;")

# ── ② 新增公共方法 + 网页路径改用它 ───────────────────────────────
cut('onWebUploadEnd',
    "  private onWebUploadEnd(ok: boolean, names: string[], totalBytes: number, error: string): void {\n"
    "    if (ok) {\n"
    "      const label: string = names.length === 1 ? names[0] : `${names.length} 个文件`;\n"
    "      this.snapshot.transferText = `✓ 网页上传完成：${label}`\n"
    "        + `（${LanService.fmtSize(totalBytes)}）`;\n"
    "      this.snapshot.transferPercent = 100;\n"
    "      this.emit();\n"
    "      // ★ 定时器句柄存起来：连着传多个文件时，旧的定时器要作废，\n"
    "      //   否则前一次的「清空」会提前把后一次的完成提示抹掉。\n"
    "      if (this.uploadDoneTimer >= 0) {\n"
    "        clearTimeout(this.uploadDoneTimer);\n"
    "      }\n"
    "      this.uploadDoneTimer = setTimeout(() => {\n"
    "        this.uploadDoneTimer = -1;\n"
    "        this.snapshot.transferText = '';\n"
    "        this.snapshot.transferPercent = 0;\n"
    "        this.emit();\n"
    "      }, 1500);\n"
    "    } else {",
    "  private onWebUploadEnd(ok: boolean, names: string[], totalBytes: number, error: string): void {\n"
    "    if (ok) {\n"
    "      const label: string = names.length === 1 ? names[0] : `${names.length} 个文件`;\n"
    "      // ★ 5.1.40：改走公共完成提示（与协议侧同一套，保留 3 秒）\n"
    "      this.showRecvDoneFloat(label, totalBytes);\n"
    "    } else {")

# ── ③ 公共方法本体：插在 fmtSize 之前 ────────────────────────────
cut('insert-helper',
    "  private static fmtSize(n: number): string {",
    "  /**\n"
    "   * ★★ 5.1.40：**所有**接收路径的完成提示统一走这里（网页上传 + v4/v5/分片/FileTransfer）。\n"
    "   *\n"
    "   * 【为什么要抽出来】此前只有网页上传有完成提示（1.5s），\n"
    "   *   而协议侧走 `onTransferReport`，它在 `r.done` 分支第一件事就是\n"
    "   *   `transferText = ''` ⇒ 完成态一闪而过，用户基本看不到。\n"
    "   *   （这与 5.1.28 修的是同一个坑，当时只补了网页那条路径。）\n"
    "   *\n"
    "   * 【⚠️ 顺序契约 —— 5.0.51 踩过的坑，勿改】\n"
    "   *   `transferText` 的「非空 → 空」跳变是**文件页自动刷新**的触发信号\n"
    "   *   （`Index.ets` 的 `onSnapshot` 靠它调 `refreshReceived()`）。\n"
    "   *   所以**清空动作必须仍然发生**，只是推迟 3 秒。\n"
    "   *\n"
    "   * @param label  文件名（多文件时传「N 个文件」）\n"
    "   * @param size   字节数，用于显示大小\n"
    "   */\n"
    "  private showRecvDoneFloat(label: string, size: number): void {\n"
    "    this.snapshot.transferText = `✓ 接收完成：${label}（${LanService.fmtSize(size)}）`;\n"
    "    this.snapshot.transferPercent = 100;\n"
    "    this.emit();\n"
    "    // ★ 定时器句柄存起来：连着传多个文件时，旧的定时器要作废，\n"
    "    //   否则前一次的「清空」会提前把后一次的完成提示抹掉。\n"
    "    if (this.doneFloatTimer >= 0) {\n"
    "      clearTimeout(this.doneFloatTimer);\n"
    "    }\n"
    "    this.doneFloatTimer = setTimeout(() => {\n"
    "      this.doneFloatTimer = -1;\n"
    "      this.snapshot.transferText = '';\n"
    "      this.snapshot.transferPercent = 0;\n"
    "      this.emit();\n"
    "    }, 3000);\n"
    "  }\n"
    "\n"
    "  private static fmtSize(n: number): string {")

# ── ④ onTransferReport：协议侧完成时也给提示 ─────────────────────
cut('onTransferReport-done',
    "    this.snapshot.transferText = '';\n"
    "    this.snapshot.transferPercent = 0;\n"
    "    this.lastReportBytes = 0;\n"
    "    if (r.message.length > 0) {",
    "    // ★★ 5.1.40：接收完成也给 3 秒完成提示（此前只有网页上传有）。\n"
    "    //   `showRecvDoneFloat` 内部会设完成态 + emit + 3s 后清空，\n"
    "    //   「非空 → 空」的跳变仍然发生 ⇒ 文件页照常自动刷新。\n"
    "    if (r.ok && r.direction !== 'send' && r.fileName.length > 0) {\n"
    "      this.showRecvDoneFloat(r.fileName, r.fileSize);\n"
    "    } else {\n"
    "      this.snapshot.transferText = '';\n"
    "      this.snapshot.transferPercent = 0;\n"
    "    }\n"
    "    this.lastReportBytes = 0;\n"
    "    if (r.message.length > 0) {")

# ══════════════════════════════════════════════════════════════════
for tag, old, new, chk in blocks:
    n = s.count(old)
    assert n == 1, '%s count=%d (期望 1)' % (tag, n)
    if chk and new:
        assert s.count(new) == 0, '%s 新文本已存在' % tag

for tag, old, new, chk in blocks:
    s = s.replace(old, new, 1)

# 版本号
assert '"versionCode": 5000139' in app, 'versionCode anchor'
assert '"versionName": "5.1.39"' in app, 'versionName anchor'
app = app.replace('"versionCode": 5000139', '"versionCode": 5000140', 1)
app = app.replace('"versionName": "5.1.39"', '"versionName": "5.1.40"', 1)

# 残留检查：**只查代码**（剥离 // 与 * 注释行）——
# 注释里提到旧名 uploadDoneTimer 是刻意保留的（说明重命名来由）。
def _code_only(t):
    return '\n'.join(ln for ln in t.split('\n')
                     if not ln.strip().startswith(('//', '*', '/*')))
assert 'uploadDoneTimer' not in _code_only(s), '代码中仍有 uploadDoneTimer'

io.open(LS, 'w', encoding='utf-8', newline='\n').write(s)
io.open(APP, 'w', encoding='utf-8', newline='\n').write(app)

s2 = io.open(LS, encoding='utf-8', newline='').read()
print('改块数        :', len(blocks))
print('showRecvDoneFloat:', s2.count('showRecvDoneFloat'), '(定义1 + 调用2)')
print('doneFloatTimer:', s2.count('doneFloatTimer'))
print('接收完成文案   :', s2.count('✓ 接收完成：'))
print('3000ms       :', s2.count('}, 3000);'))
print('1500ms 残留  :', s2.count('}, 1500);'))
print('CRLF         :', s2.count('\r\n'))
print('OK 5.1.40 applied')
