# -*- coding: utf-8 -*-
"""
5.1.44 —— ① 文件名超长时改用两行 ② 完成提示加 toast 可靠通道 ③ 恢复多文件 i/n

【vivi 两张截图的关键差异（这是定案依据）】
  图1（传输中 28%）：第一行 `接收 ...`  ← 文件名一个字符都没显示
  图2（完成 100%）：第一行 `launchermap_3.9.151-0930jffghjtdfjddvhdxhxcgij...`
       ★ 同一行宽、同样 `width('100%')`，却能显示 50+ 字符
  ⇒ **不是宽度不够，也不是 `layoutWeight`**（5.1.43 已去掉它，仍复现）
  ⇒ 是「文本更长时 ArkUI 的 ellipsis 把整行可用宽度算成 0，只画省略号」
  ⇒ ★ **换行是唯一可靠解**：`maxLines(1)` → `maxLines(2)`。
     （5.1.41 之前 maxLines(2) 会挤掉百分比，**但现在百分比已独立到第 2 行**，
       所以换行不再有副作用。）

【图2 还暴露：副行消失了 + 仍是蓝色 + 地球在转】
  ⇒ 浮层这条链路（`transferDone` → `tDoneBg` → 背景色）连续两版不可靠。
  ⇒ ★ **加一条不依赖 ArkUI 状态追踪的通道：`showToast`（系统组件）**。
     这同时满足 vivi 的原始需求「完成后加完成提示、保留 3 秒」，
     并且**自带自证能力**：toast 出现 = 完成逻辑确实跑了；
     toast 不出现 = 完成逻辑没跑（不用再猜）。

【③ i/n 的正确语义（vivi：「多个文件也不显示 i/n 了」）】
  需要区分两种「计数」：
    · **分片**：`fileIndex = part.done`（已收片数）、`fileCount = 16`（1.35 硬编码片数）
      ⇒ 显示 `0/16` 会被误读成「16 个文件」⇒ 不显示。
    · **多文件**：`fileIndex = i+1`、`fileCount = items.length`
      ⇒ 是「第 i 个 / 共 n 个文件」，**应该显示**。
  两者在数值上无法区分（都可能等于 fileCount），⇒ 新增显式标记 `isSeg`。

【改动清单】
  1. `TransferReport` 加 `isSeg: boolean = false`；`V5Transfer.report()` 加同名可选参数；
     分片三处上报传 `true`。
  2. `LanService.onTransferReport` 副行：`isSeg` 时只显示容量，否则恢复 `i/n · 容量`。
  3. `Index.onSnapshot`：`transferDone` 为 true 时弹 **toast（3 秒）**，内容为完成文案。
     toast 走 `getUIContext().getPromptAction().showToast`，与浮层状态追踪完全无关。
  4. 文件名 `maxLines(1)` → `maxLines(2)`，行高 20 → 34（两行放得下）。
  5. `toast()` 增加可选 `duration` 参数（默认 2000 不变，避免影响既有调用）。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
LS = os.path.join(ET, 'service', 'LanService.ets')
VT = os.path.join(ET, 'service', 'V5Transfer.ets')
FT = os.path.join(ET, 'service', 'FileTransfer.ets')
IX = os.path.join(ET, 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

ls = io.open(LS, encoding='utf-8', newline='').read()
vt = io.open(VT, encoding='utf-8', newline='').read()
ft = io.open(FT, encoding='utf-8', newline='').read()
ix = io.open(IX, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

SEN = 'isSeg'
if SEN in ft:
    print('ALREADY APPLIED'); sys.exit(0)

blocks = []
def cut(tag, old, new='', chk=True):
    blocks.append((tag, old, new, chk))

# ═══ ① TransferReport 加 isSeg ═══
cut('TR-field',
     "  /** 整批进度 0-100 */\n"
     "  percent: number = 0;\n",
     "  /** 整批进度 0-100 */\n"
     "  percent: number = 0;\n"
     "  /**\n"
     "   * ★ 5.1.44：这次上报是不是「**分片**」进度。\n"
     "   *\n"
     "   * 【为什么需要】分片上报的 `fileIndex/fileCount` 是**片数**\n"
     "   *   （`part.done` / `total`，1.35 硬编码 16），而多文件上报的是\n"
     "   *   「第 i 个 / 共 n 个文件」。**两者数值上无法区分**（都可能相等），\n"
     "   *   所以只能由上报方显式声明。\n"
     "   * ⇒ 分片时 UI 不显示 `i/n`（否则被误读成 16 个文件），多文件时显示。\n"
     "   */\n"
     "  isSeg: boolean = false;\n")

# ═══ ② V5Transfer.report 签名与赋值 ═══
cut('VT-report-sig',
     "    message: string,\n"
     "    names: string[] = []\n"
     "  ): void {\n",
     "    message: string,\n"
     "    names: string[] = [],\n"
     "    isSeg: boolean = false\n"
     "  ): void {\n")
cut('VT-report-assign',
     "    r.message = message;\n"
     "    r.fileNames = names;\n"
     "    cb(r);\n",
     "    r.message = message;\n"
     "    r.fileNames = names;\n"
     "    r.isSeg = isSeg;\n"
     "    cb(r);\n")

# ═══ ③ 分片三处上报标记 isSeg ═══
cut('VT-seg-1',
     "          V5Transfer.report(onReport, 'recv', fromName, part.name, part.done, total,\n"
     "            part.received, part.fileSize, pct, false, true, '');\n",
     "          // ★ 5.1.44：标记这是**分片**进度（fileIndex/Count 是片数，不是文件数）\n"
     "          V5Transfer.report(onReport, 'recv', fromName, part.name, part.done, total,\n"
     "            part.received, part.fileSize, pct, false, true, '', [], true);\n")

cut('VT-seg-2',
     "      V5Transfer.report(onReport, 'recv', fromName, part.name, part.done, total,\n"
     "        part.received, part.fileSize, percent, false, true, '');\n",
     "      // ★ 5.1.44：同上，标记为分片进度\n"
     "      V5Transfer.report(onReport, 'recv', fromName, part.name, part.done, total,\n"
     "        part.received, part.fileSize, percent, false, true, '', [], true);\n")

cut('VT-seg-3',
     "      V5Transfer.report(onReport, 'recv', fromName, part.name, total, total,\n"
     "        part.fileSize, part.fileSize, 100, true, true,\n"
     "        `已接收 ${V5Transfer.human(part.fileSize)}，保存到 ${storage.describe}`);\n",
     "      V5Transfer.report(onReport, 'recv', fromName, part.name, total, total,\n"
     "        part.fileSize, part.fileSize, 100, true, true,\n"
     "        `已接收 ${V5Transfer.human(part.fileSize)}，保存到 ${storage.describe}`,\n"
     "        [], true);\n")

# ═══ ④ LanService：副行按 isSeg 决定是否显示 i/n ═══
cut('LS-sub-isSeg',
     "      // ★ 5.1.43：**不要**显示 `i/n`。\n"
     "      //   v5 分片进度上报的 `fileIndex/fileCount` 是**片数**（`part.done` / `total`，\n"
     "      //   1.35 恒为 16），不是「第 i 个文件 / 共 n 个文件」——\n"
     "      //   vivi 2026-10-03 实测截图上显示成 `0/16`，被误读成 16 个文件。\n"
     "      //   ⇒ 统一只显示容量，与单个小文件表现一致。\n"
     "      this.snapshot.transferSub =\n"
     "        `${LanService.fmtSize(r.bytes)} / ${LanService.fmtSize(r.fileSize)}`;\n",
     "      // ★ 5.1.44：**按 `isSeg` 决定要不要显示 `i/n`**（5.1.43 一刀切去掉是错的，\n"
     "      //   vivi 反馈「多个文件时也不显示 i/n 了」）。\n"
     "      //   · `isSeg=true`（分片）：`fileIndex/fileCount` 是**片数**（1.35 恒 16），\n"
     "      //     显示 `0/16` 会被误读成 16 个文件 ⇒ 只显示容量。\n"
     "      //   · `isSeg=false`（多文件）：是「第 i 个 / 共 n 个文件」⇒ 应当显示。\n"
     "      const cap: string =\n"
     "        `${LanService.fmtSize(r.bytes)} / ${LanService.fmtSize(r.fileSize)}`;\n"
     "      this.snapshot.transferSub = (!r.isSeg && r.fileCount > 1)\n"
     "        ? `${r.fileIndex}/${r.fileCount} · ${cap}`\n"
     "        : cap;\n")

# ═══ ⑤ 完成文案里直接带 ✓（不依赖任何状态追踪的视觉兜底）═══
cut('LS-done-tick',
     "  private showRecvDoneFloat(label: string, size: number): void {\n"
     "    this.snapshot.transferText = label.length > 0 ? label : '文件';\n",
     "  private showRecvDoneFloat(label: string, size: number): void {\n"
     "    // ★★ 5.1.44：文案里**直接写死 `✓` 前缀**。\n"
     "    //   5.1.43 把它去掉了（理由是「状态应由 transferDone 字段表达」）——\n"
     "    //   但实测 `transferDone` 驱动的底色与图标连续两版不生效，\n"
     "    //   于是完成提示**看起来和传输中完全一样**，用户毫无感知。\n"
     "    //   ⇒ 文案里的 `✓` 是不依赖 ArkUI 状态追踪的**最后一道视觉兜底**：\n"
     "    //     字段负责颜色/图标，字符负责「一定看得到完成」。\n"
     "    this.snapshot.transferText = `✓ ${label.length > 0 ? label : '文件'}`;\n")
cut('IX-toast-dur',
     "  private toast(msg: string): void {\n"
     "    try {\n",
     "  /**\n"
     "   * ★ 5.1.44：加 `duration` 参数（默认 2000 保持既有调用行为不变）。\n"
     "   *   完成提示要 3 秒（vivi 需求），而浮层那条链路连续两版不可靠\n"
     "   *   （`tDoneBg` 不重绘、文件名被 ellipsis 吃光）⇒ 需要这条独立通道。\n"
     "   */\n"
     "  private toast(msg: string, duration: number = 2000): void {\n"
     "    try {\n")
cut('IX-toast-use',
     "      this.getUIContext().getPromptAction().showToast({ message: msg, duration: 2000 });\n",
     "      this.getUIContext().getPromptAction().showToast({ message: msg, duration: duration });\n")

# ═══ ⑥ 完成时弹 toast（3 秒）═══
cut('IX-onSnapshot-toast',
     "    // ★ 5.1.43：颜色在这里算好（见 tDoneBg 注释：链式属性里的三元表达式不可靠）\n"
     "    this.tDoneBg = s.transferDone ? C_DONE_OK : C_PRIMARY;\n",
     "    // ★ 5.1.43：颜色在这里算好（见 tDoneBg 注释：链式属性里的三元表达式不可靠）\n"
     "    this.tDoneBg = s.transferDone ? C_DONE_OK : C_PRIMARY;\n"
     "    // ★★ 5.1.44：完成提示的**可靠通道** —— 浮层的颜色/图标连续两版不生效，\n"
     "    //   而 toast 走系统组件，与 ArkUI 的 @State → 视图追踪**完全无关**。\n"
     "    //   这条同时满足 vivi 的原始需求「完成后加完成提示、保留 3 秒」，\n"
     "    //   并且**自带自证能力**：toast 出现 = 完成逻辑确实跑了。\n"
     "    if (s.transferDone && !this.tDoneToastShown) {\n"
     "      this.tDoneToastShown = true;\n"
     "      this.toast(`接收完成：${s.transferText}`, 3000);\n"
     "    } else if (!s.transferDone) {\n"
     "      this.tDoneToastShown = false;\n"
     "    }\n")

# ═══ ⑦ 文件名改两行 ═══
cut('IX-name-2lines',
     "          // 文本层：整宽 + 左内边距\n"
     "          Text(this.tText)\n"
     "            .width('100%')\n"
     "            .padding({ left: 26 })\n"
     "            .fontSize(13)\n"
     "            .fontColor('#FFFFFF')\n"
     "            .maxLines(1)\n"
     "            .textOverflow({ overflow: TextOverflow.Ellipsis })\n"
     "        }\n"
     "        .width('100%')\n"
     "        .height(20)\n",
     "          // 文本层：整宽 + 左内边距\n"
     "          // ★ 5.1.44：`maxLines(1)` → **`maxLines(2)`**。\n"
     "          //   实测（vivi 截图）：超长文件名时 ArkUI 的 ellipsis 会把整行\n"
     "          //   **可用宽度算成 0**，只画一个 `...`，前面一个字都不显示；\n"
     "          //   而稍短的名字能正常显示 50+ 字符 ⇒ 是长度触发的测量异常，\n"
     "          //   不是行宽不够。**换行是唯一可靠解**。\n"
     "          //   ⚠️ 5.1.41 之前 maxLines(2) 会把百分比挤掉，但**百分比已独立到\n"
     "          //     第 2 行**（5.1.41 改动），所以这里换行没有副作用。\n"
     "          Text(this.tText)\n"
     "            .width('100%')\n"
     "            .padding({ left: 26 })\n"
     "            .fontSize(13)\n"
     "            .fontColor('#FFFFFF')\n"
     "            .maxLines(2)\n"
     "            .textOverflow({ overflow: TextOverflow.Ellipsis })\n"
     "        }\n"
     "        .width('100%')\n"
     "        .height(36)\n")

# ═══ ⑧ tDoneToastShown 字段 ═══
cut('IX-toast-flag',
     "  @State tDoneBg: string = C_PRIMARY;\n",
     "  @State tDoneBg: string = C_PRIMARY;\n"
     "  /** ★ 5.1.44：完成 toast 只弹一次的去重标记（`transferDone` 会连续多次为 true） */\n"
     "  private tDoneToastShown: boolean = false;\n")

# ═══════════ 校验 + 落盘 ═══════════
T = {'LS': ls, 'VT': vt, 'FT': ft, 'IX': ix}
for tag, old, new, chk in blocks:
    # 定位目标文件
    if tag.startswith('TR'):
        tgt, cur = 'FT', ft
    elif tag.startswith('VT'):
        tgt, cur = 'VT', vt
    elif tag.startswith('LS'):
        tgt, cur = 'LS', ls
    else:
        tgt, cur = 'IX', ix
    n = cur.count(old)
    assert n == 1, '%s %s count=%d' % (tgt, tag, n)
    if chk and new:
        assert cur.count(new) == 0, '%s %s 新文本已存在' % (tgt, tag)

for tag, old, new, chk in blocks:
    if tag.startswith('TR'):
        ft = ft.replace(old, new, 1)
    elif tag.startswith('VT'):
        vt = vt.replace(old, new, 1)
    elif tag.startswith('LS'):
        ls = ls.replace(old, new, 1)
    else:
        ix = ix.replace(old, new, 1)

assert '"versionCode": 5000143' in app and '"versionName": "5.1.43"' in app, 'version'
app = app.replace('"versionCode": 5000143', '"versionCode": 5000144', 1)
app = app.replace('"versionName": "5.1.43"', '"versionName": "5.1.44"', 1)

def _code_only(t):
    return '\n'.join(ln for ln in t.split('\n')
                     if not ln.strip().startswith(('//', '*', '/*')))
assert _code_only(ls).count("!, r.isSeg") >= 0
assert "r.isSeg && r.fileCount > 1" in _code_only(ls), 'isSeg 未用于副行'
assert "maxLines(2)" in _code_only(ix), '文件名未改两行'
assert "this.toast(`接收完成：" in _code_only(ix), '完成 toast 未接上'
assert vt.count("'', [], true)") == 2, '分片进度标记 %d' % vt.count("'', [], true)")
assert vt.count("\n        [], true);") == 1, '分片完成标记 %d' % vt.count("\n        [], true);")

for p, s in ((LS, ls), (VT, vt), (FT, ft), (IX, ix), (APP, app)):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

print('改块数 %d' % len(blocks))
print('isSeg 字段     FT=%d' % ft.count('isSeg'))
print('report 签名    VT=%d' % vt.count('isSeg: boolean = false'))
print('分片标记       VT=%d' % (vt.count("'', [], true)") + vt.count("[], true);")))
print('副行用 isSeg   LS=%d' % ls.count('r.isSeg'))
print('i/n 恢复       LS=%d' % ls.count('${r.fileIndex}/${r.fileCount} ·'))
print('完成 toast     IX=%d' % ix.count('接收完成：${s.transferText}'))
print('toast duration IX=%d' % ix.count('duration: number = 2000'))
print('maxLines(2)    IX=%d' % ix.count('maxLines(2)'))
print('CRLF           %d' % (ls.count('\r\n') + vt.count('\r\n') + ft.count('\r\n') + ix.count('\r\n')))
print('OK 5.1.44 applied')
