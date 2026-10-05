# -*- coding: utf-8 -*-
"""
5.1.41 —— 进度框：① 加传输速度 ② 完成时小地球停转 ③ 完成时换色
             ④ 修长文件名把百分比挤出可视区的布局 bug

【问题 ④ 的根因（vivi 实测：长文件名时「连进度百分比都看不见」）】
  旧 `transferText` 把「动词 + 文件名 + 百分比 + 计数」全塞进**一个字符串**：
      协议侧 `接收 4.5Ui-18_...877d72c3931513ce36fd7.zip 45%（1/3）`
      网页侧 `网页上传 xxx.apk 45%（12.3 MB / 60.0 MB）`
  浮层标题行 `Text(tText).maxLines(2)` ⇒ 长文件名把末尾的百分比顶到第二行之外，
  整行被 ellipsis 截断 ⇒ 百分比（以及「已收/总量」）**完全不可见**。

【改法：文案拆分 + UI 重排（不靠加行数掩盖）】
  LanService：
    · `transferText` 只保留「动词 + 文件名」（文件名自己会省略号）
    · 新增 `transferPercent` 已有 → 标题行**右侧独立显示百分比**
    · 新增 `transferSub`（序号 / 已收-总量）→ 放到进度条**下方**一行
    · 新增 `transferSpeed`（EMA 平滑的实时速度）
  Index：
    · 标题行 = [图标] [文件名 layoutWeight=1 maxLines=1] [百分比 加粗]
    · 第二行 = 进度条
    · 第三行 = [副信息] .... [速度右对齐]
    · 完成态（`tText` 以 `✓` 开头）：`LoadingProgress` 换成 `Text('✓')`（不转），
      底色由 `C_PRIMARY`（蓝）换成 `C_DONE_OK`（绿）

【速度算法】
  相邻两次进度上报的字节差 / 时间差 = 瞬时速度，再做 EMA（0.6/0.4）平滑，
  采样间隔 <200ms 不更新（否则文字会疯狂跳动）。传输结束/清空时一并重置。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
LS = os.path.join(ET, 'service', 'LanService.ets')
IX = os.path.join(ET, 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

ls = io.open(LS, encoding='utf-8', newline='').read()
ix = io.open(IX, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

SEN = 'transferSpeed'
if SEN in ls:
    print('ALREADY APPLIED'); sys.exit(0)

L = []          # LanService 块
N = []          # Index 块
def cutL(tag, old, new='', chk=True): L.append((tag, old, new, chk))
def cutN(tag, old, new='', chk=True): N.append((tag, old, new, chk))

# ═══════════════ LanService ═══════════════

# ① snapshot 加两个字段
cutL('snapshot-fields',
     "  /** 正在传输的整体进度 0-100（浮层进度条用） */\n"
     "  transferPercent: number = 0;\n",
     "  /** 正在传输的整体进度 0-100（浮层进度条用） */\n"
     "  transferPercent: number = 0;\n"
     "  /** ★ 5.1.41：实时速度，如「28.5 MB/s」；空串 = 不显示 */\n"
     "  transferSpeed: string = '';\n"
     "  /** ★ 5.1.41：副信息（序号 / 已收-总量），放进度条下方，\n"
     "   *   不再挤在标题行里（★ 挤在那里会被长文件名顶出可视区） */\n"
     "  transferSub: string = '';\n")

# ② 速度采样字段（放在 uploadDoneTimer 已被改名后的 doneFloatTimer 旁边）
cutL('speed-fields',
     "  private doneFloatTimer: number = -1;\n",
     "  private doneFloatTimer: number = -1;\n"
     "  /** ★ 5.1.41：速度采样点（EMA 平滑，避免速度文字乱跳） */\n"
     "  private speedBytes: number = 0;\n"
     "  private speedAt: number = 0;\n"
     "  private speedEma: number = 0;\n")

# ③ 速度计算 + 重置方法（插在 updateSpeed 用到之前：放在 onTransferReport 之前）
cutL('speed-methods',
     "  private onTransferReport(r: TransferReport): void {",
     "  /**\n"
     "   * ★ 5.1.41：更新实时速度（相邻两次上报的字节差 / 时间差，EMA 平滑）。\n"
     "   *\n"
     "   * 【为什么要 EMA】瞬时值抖动极大（网络分片到达不均），直接显示会疯狂跳字。\n"
     "   * 【为什么要 200ms 门限】上报本身有节流，再密也用不上；间隔太短会让\n"
     "   *   分母趋近 0 放大噪声。\n"
     "   */\n"
     "  private updateSpeed(bytes: number): void {\n"
     "    const now: number = Date.now();\n"
     "    if (this.speedAt === 0) {\n"
     "      this.speedAt = now;\n"
     "      this.speedBytes = bytes;\n"
     "      return;\n"
     "    }\n"
     "    const dt: number = now - this.speedAt;\n"
     "    if (dt < 200) {\n"
     "      return;\n"
     "    }\n"
     "    const inst: number = Math.max(0, bytes - this.speedBytes) * 1000 / dt;\n"
     "    this.speedEma = this.speedEma === 0 ? inst : (this.speedEma * 0.6 + inst * 0.4);\n"
     "    this.speedBytes = bytes;\n"
     "    this.speedAt = now;\n"
     "    this.snapshot.transferSpeed = this.speedEma > 0\n"
     "      ? `${LanService.fmtSize(Math.round(this.speedEma))}/s`\n"
     "      : '';\n"
     "  }\n"
     "\n"
     "  /** ★ 5.1.41：传输结束/清空时重置速度采样，避免下一段沿用上一段的基数 */\n"
     "  private resetSpeed(): void {\n"
     "    this.speedBytes = 0;\n"
     "    this.speedAt = 0;\n"
     "    this.speedEma = 0;\n"
     "    this.snapshot.transferSpeed = '';\n"
     "  }\n"
     "\n"
     "  private onTransferReport(r: TransferReport): void {")

# ④ 协议侧进度分支：文案拆分 + 速度
cutL('report-progress',
     "      const verb: string = r.direction === 'send' ? '发送' : '接收';\n"
     "      this.snapshot.transferText =\n"
     "        `${verb} ${r.fileName} ${r.percent}%（${r.fileIndex}/${r.fileCount}）`;\n"
     "      this.snapshot.transferPercent = r.percent;\n",
     "      const verb: string = r.direction === 'send' ? '发送' : '接收';\n"
     "      // ★ 5.1.41：标题行只放「动词 + 文件名」。\n"
     "      //   百分比由浮层右侧独立显示、计数与容量移到下一行 ⇒\n"
     "      //   长文件名不再把百分比顶出可视区（vivi 实测「连百分比都看不见」）。\n"
     "      this.snapshot.transferText = `${verb} ${r.fileName}`;\n"
     "      this.snapshot.transferPercent = r.percent;\n"
     "      this.snapshot.transferSub = r.fileCount > 1\n"
     "        ? `${r.fileIndex}/${r.fileCount} · ${LanService.fmtSize(r.bytes)}`\n"
     "          + ` / ${LanService.fmtSize(r.fileSize)}`\n"
     "        : `${LanService.fmtSize(r.bytes)} / ${LanService.fmtSize(r.fileSize)}`;\n"
     "      this.updateSpeed(r.bytes);\n")

# ⑤ 协议侧终态：清 speed/sub
cutL('report-done-clear',
     "    } else {\n"
     "      this.snapshot.transferText = '';\n"
     "      this.snapshot.transferPercent = 0;\n"
     "    }\n"
     "    this.lastReportBytes = 0;\n",
     "    } else {\n"
     "      this.snapshot.transferText = '';\n"
     "      this.snapshot.transferPercent = 0;\n"
     "    }\n"
     "    this.snapshot.transferSub = '';\n"
     "    this.resetSpeed();\n"
     "    this.lastReportBytes = 0;\n")

# ⑥ 网页侧进度：文案拆分 + 速度
cutL('web-progress',
     "    this.snapshot.transferText = total > 0\n"
     "      ? `网页上传 ${who} ${pct}%（${LanService.fmtSize(received)} / ${LanService.fmtSize(total)}）`\n"
     "      : `网页上传 ${who}（已收 ${LanService.fmtSize(received)}）`;\n"
     "    this.snapshot.transferPercent = pct;\n",
     "    // ★ 5.1.41：同协议侧 —— 标题只留「动词 + 文件名」，其余拆到副行。\n"
     "    this.snapshot.transferText = `网页上传 ${who}`;\n"
     "    this.snapshot.transferPercent = pct;\n"
     "    this.snapshot.transferSub = total > 0\n"
     "      ? `${LanService.fmtSize(received)} / ${LanService.fmtSize(total)}`\n"
     "      : `已收 ${LanService.fmtSize(received)}`;\n"
     "    this.updateSpeed(received);\n")

# ⑦ 完成提示：速度清空、副行显示总大小（完成态不再显示速度）
cutL('done-float',
     "    this.snapshot.transferText = `✓ 接收完成：${label}（${LanService.fmtSize(size)}）`;\n"
     "    this.snapshot.transferPercent = 100;\n"
     "    this.emit();\n",
     "    this.snapshot.transferText = `✓ ${label}`;\n"
     "    this.snapshot.transferPercent = 100;\n"
     "    // ★ 5.1.41：完成态把大小放到副行，标题行留给文件名（长度不受限）。\n"
     "    this.snapshot.transferSub = LanService.fmtSize(size);\n"
     "    this.resetSpeed();\n"
     "    this.emit();\n")

# ⑧ 完成提示清空时也清副行
cutL('done-float-clear',
     "      this.doneFloatTimer = -1;\n"
     "      this.snapshot.transferText = '';\n"
     "      this.snapshot.transferPercent = 0;\n"
     "      this.emit();\n",
     "      this.doneFloatTimer = -1;\n"
     "      this.snapshot.transferText = '';\n"
     "      this.snapshot.transferPercent = 0;\n"
     "      this.snapshot.transferSub = '';\n"
     "      this.resetSpeed();\n"
     "      this.emit();\n")

# ⑨ onWebUploadEnd 失败分支：清副行
cutL('web-fail-clear',
     "    } else {\n"
     "      this.snapshot.transferText = '';\n"
     "      this.snapshot.transferPercent = 0;\n"
     "    }\n"
     "    if (ok) {\n"
     "      const label: string = names.length === 1 ? names[0] : `${names.length} 个文件`;\n"
     "      this.pushLog(`网页上传完成：${label}（${LanService.fmtSize(totalBytes)}）`);",
     "    } else {\n"
     "      this.snapshot.transferText = '';\n"
     "      this.snapshot.transferPercent = 0;\n"
     "      this.snapshot.transferSub = '';\n"
     "      this.resetSpeed();\n"
     "    }\n"
     "    if (ok) {\n"
     "      const label: string = names.length === 1 ? names[0] : `${names.length} 个文件`;\n"
     "      this.pushLog(`网页上传完成：${label}（${LanService.fmtSize(totalBytes)}）`);")

# ═══════════════ Index ═══════════════

# ⑩ 颜色常量
cutN('color-const',
     "const C_PAGE: string = '#F1F3F5';\n",
     "const C_PAGE: string = '#F1F3F5';\n"
     "/** ★ 5.1.41：传输完成态的浮层底色（绿）—— 与进行中的蓝区分 */\n"
     "const C_DONE_OK: string = '#1E8E3E';\n")

# ⑪ 两个新 @State
cutN('new-state',
     "  @State tText: string = '';\n"
     "  @State tPercent: number = 0;\n",
     "  @State tText: string = '';\n"
     "  @State tPercent: number = 0;\n"
     "  /** ★ 5.1.41：实时速度（独立 @State ⇒ 10Hz 刷新只动这个浮层） */\n"
     "  @State tSpeed: string = '';\n"
     "  /** ★ 5.1.41：副信息（序号 / 已收-总量） */\n"
     "  @State tSub: string = '';\n")

# ⑫ onSnapshot 同步这两个
cutN('snapshot-sync',
     "    if (s.transferPercent !== this.tPercent) {\n"
     "      this.tPercent = s.transferPercent;\n"
     "    }\n",
     "    if (s.transferPercent !== this.tPercent) {\n"
     "      this.tPercent = s.transferPercent;\n"
     "    }\n"
     "    if (s.transferSpeed !== this.tSpeed) {\n"
     "      this.tSpeed = s.transferSpeed;\n"
     "    }\n"
     "    if (s.transferSub !== this.tSub) {\n"
     "      this.tSub = s.transferSub;\n"
     "    }\n")

# ⑬ 进度浮层整体重排
i = ix.index('  transferFloat() {')
j = ix.index("      .margin({ top: this.topInset + 56 })\n    }\n  }\n", i)
j += len("      .margin({ top: this.topInset + 56 })\n    }\n  }\n")
newFloat = '''  transferFloat() {
    if (this.tText.length > 0) {
      Column({ space: 8 }) {
        // ── 标题行：图标 + 文件名（吃剩余宽度）+ 百分比（固定不被挤掉）──
        Row({ space: 8 }) {
          // ★ 5.1.41：完成态不再转「小地球」—— LoadingProgress 是**动画组件**，
          //   只要它还挂在树上就一直转，哪怕进度早已 100%。改用静态 ✓。
          if (this.tDone) {
            Text('\\u2713')
              .fontSize(16)
              .fontColor('#FFFFFF')
              .width(18)
              .textAlign(TextAlign.Center)
          } else {
            LoadingProgress()
              .width(18)
              .height(18)
              .color('#FFFFFF')
          }
          // ★ 5.1.41：maxLines 2 → **1**。原来允许折两行，长文件名会把末尾的
          //   百分比顶到第二行之外被 ellipsis 吃掉（vivi 实测「连百分比都看不见」）。
          Text(this.tText)
            .fontSize(13)
            .fontColor('#FFFFFF')
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(`${this.tPercent}%`)
            .fontSize(13)
            .fontColor('#FFFFFF')
            .fontWeight(FontWeight.Bold)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 进度条：空白部分=白色轨道，跟随进度用黄色从左向右填充。
        // ⚠️ 弃用 Progress 组件：真机主题下它的「填充色 / 轨道色」会被画反，
        // 表现为"全黄逐渐变白"（vivi 2026-09-30 实测）。这里用两个 Row 自己实现：
        // 外层轨道固定白色（空白即白色），内层 Row 宽度按百分比增长 = 黄色实心填充。
        // 浮层底色是蓝（C_PRIMARY），白轨道 + 黄填充在蓝底上对比清晰。
        // ⚠️ 这条 `.animation()` 是「进度看起来线性」的关键补充：
        //    接收侧的上报再密也有 100ms 的节流，末段几个分片同时收齐时
        //    百分比仍可能一次跳好几个点。给宽度加 240ms 线性过渡后，
        //    视觉上是「追上去」而不是「啪一下跳过去」。
        Row() {
          Row()
            .height(4)
            .borderRadius(2)
            .backgroundColor('#FFD54F')
            .width(`${this.tPercent}%`)
            .animation({ duration: 240, curve: Curve.Linear })
        }
        .width('100%')
        .height(4)
        .borderRadius(2)
        .backgroundColor('#FFFFFF')

        // ★ 5.1.41 新增：副信息（序号 / 已收-总量）+ 实时速度。
        //   放这一行而不是标题行 —— 标题行要给文件名留足宽度。
        if (this.tSub.length > 0 || this.tSpeed.length > 0) {
          Row() {
            Text(this.tSub)
              .fontSize(11)
              .fontColor('#E0E0E0')
              .layoutWeight(1)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            Text(this.tSpeed)
              .fontSize(11)
              .fontColor('#FFFFFF')
              .fontWeight(FontWeight.Medium)
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
        }
      }
      .width('96%')
      .padding({ left: 14, right: 14, top: 12, bottom: 12 })
      // ★ 5.1.41：完成态换成绿色底，一眼区分「还在传」与「已传完」
      .backgroundColor(this.tDone ? C_DONE_OK : C_PRIMARY)
      .borderRadius(12)
      .shadow({ radius: 16, color: '#20000000', offsetX: 0, offsetY: 6 })
      .margin({ top: this.topInset + 56 })
    }
  }
'''
cutN('transferFloat', ix[i:j], newFloat, chk=False)

# ⑭ tDone 判定（放在 tText 状态声明之后）
cutN('tDone-getter',
     "  /** 自检进行中，防连点 */\n"
     "  private diagBusy: boolean = false;\n",
     "  /**\n"
     "   * ★ 5.1.41：浮层是否处于「完成态」。\n"
     "   *   判据：`LanService` 在完成时把 `transferText` 写成 `✓ <文件名>`\n"
     "   *   （见 `showRecvDoneFloat`），所以前缀 `✓` 就是完成标记。\n"
     "   */\n"
     "  private get tDone(): boolean {\n"
     "    return this.tText.startsWith('\\u2713');\n"
     "  }\n"
     "  /** 自检进行中，防连点 */\n"
     "  private diagBusy: boolean = false;\n")

# ═══════════════ 校验 + 落盘 ═══════════════
for tag, old, new, chk in L:
    n = ls.count(old)
    assert n == 1, 'LS %s count=%d' % (tag, n)
    if chk and new:
        assert ls.count(new) == 0, 'LS %s 新文本已存在' % tag
for tag, old, new, chk in N:
    n = ix.count(old)
    assert n == 1, 'IX %s count=%d' % (tag, n)
    if chk and new:
        assert ix.count(new) == 0, 'IX %s 新文本已存在' % tag

for tag, old, new, chk in L:
    ls = ls.replace(old, new, 1)
for tag, old, new, chk in N:
    ix = ix.replace(old, new, 1)

# 版本号
assert '"versionCode": 5000140' in app, 'versionCode'
assert '"versionName": "5.1.40"' in app, 'versionName'
app = app.replace('"versionCode": 5000140', '"versionCode": 5000141', 1)
app = app.replace('"versionName": "5.1.40"', '"versionName": "5.1.41"', 1)

io.open(LS, 'w', encoding='utf-8', newline='\n').write(ls)
io.open(IX, 'w', encoding='utf-8', newline='\n').write(ix)
io.open(APP, 'w', encoding='utf-8', newline='\n').write(app)

ls2 = io.open(LS, encoding='utf-8', newline='').read()
ix2 = io.open(IX, encoding='utf-8', newline='').read()
print('LS 块 %d / IX 块 %d' % (len(L), len(N)))
print('transferSpeed  LS=%d IX=%d' % (ls2.count('transferSpeed'), ix2.count('transferSpeed')))
print('transferSub    LS=%d IX=%d' % (ls2.count('transferSub'), ix2.count('transferSub')))
print('updateSpeed    LS=%d' % ls2.count('updateSpeed'))
print('resetSpeed     LS=%d' % ls2.count('resetSpeed'))
print('tDone          IX=%d' % ix2.count('tDone'))
print('C_DONE_OK      IX=%d' % ix2.count('C_DONE_OK'))
print('maxLines(1)     IX=%d' % ix2.count('maxLines(1)'))
print('CRLF           %d' % (ls2.count('\r\n') + ix2.count('\r\n')))
print('OK 5.1.41 applied')
