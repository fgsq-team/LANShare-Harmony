# -*- coding: utf-8 -*-
"""
5.1.42 —— 修 5.1.41 两个问题：① 完成态判定失效（不变色/球不转）② 长文件名只剩三个点

【vivi 实测反馈】
  「长文件名只显示三个点，并且传输完成没有变色。地球也没有停止，
    可以改成传输完成后不显示地球」

【问题 ① 完成态判定失效 —— 根因是「靠字符串前缀推断完成态」】
  5.1.41 判完成态靠 `private get tDone() { return this.tText.startsWith('\\u2713'); }`
  —— 三个隐患叠在一起：
    ① `\\u2713` 是**转义写法**，与 `showRecvDoneFloat` 里直接写的 `✓` 不是同一份源码；
    ② 依赖字符串前缀 ⇒ 文案一改就失效（本次文案确实被我在 5.1.41 改过）；
    ③ **getter 读 @State 在 ArkUI @Builder 里的追踪不可靠**。
  ⇒ 正解：**完成态改成显式字段** `snapshot.transferDone: boolean`，
    由 `showRecvDoneFloat` 置 true、清空时置 false；UI 侧存成 `@State`。
    零字符串解析、零转义、零 getter 依赖追踪。

【问题 ② 长文件名只剩 `...` —— 根因是百分比和文件名抢同一行】
  5.1.41 布局：`Row[ 图标 18px | 文件名 layoutWeight=1 | 百分比 ]`
  ⇒ 长文件名被百分比挤到极窄，ellipsis 只剩三个点。
  ⇒ 正解：**文件名独占第一行整宽**，百分比挪到**进度条右侧**：
        Row1:  [图标] [文件名 layoutWeight=1 maxLines=1]           ← 独占
        Row2:  [██████████░░░░] [45%]                              ← 进度条 + 百分比
        Row3:  [1/3 · 12.3 MB / 60.0 MB]              [28.5 MB/s]

【★ vivi 明确要求：「传输完成后不显示地球」】
  ⇒ 完成态**不渲染 LoadingProgress**（它是动画组件，挂上就一直在转），
    改渲染静态 `✓`。
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

SEN = 'transferDone'
if SEN in ls:
    print('ALREADY APPLIED'); sys.exit(0)

L, N = [], []
def cutL(tag, old, new='', chk=True): L.append((tag, old, new, chk))
def cutN(tag, old, new='', chk=False): N.append((tag, old, new, chk))

# ═══════════════ LanService ═══════════════

# ① snapshot 加显式完成态字段
cutL('snapshot-done',
     "  /** ★ 5.1.41：副信息（序号 / 已收-总量），放进度条下方，\n"
     "   *   不再挤在标题行里（★ 挤在那里会被长文件名顶出可视区） */\n"
     "  transferSub: string = '';\n",
     "  /** ★ 5.1.41：副信息（序号 / 已收-总量），放进度条下方，\n"
     "   *   不再挤在标题行里（★ 挤在那里会被长文件名顶出可视区） */\n"
     "  transferSub: string = '';\n"
     "  /** ★ 5.1.42：**显式**完成态标记。\n"
     "   *   ★ 5.1.41 曾用「transferText 以 ✓ 开头」来推断完成态，实测失效\n"
     "   *   （不变色 / 地球不消失）—— 靠字符串前缀 + getter 读 @State 都不可靠。\n"
     "   *   ⇒ 完成态必须是**独立字段**，由 `showRecvDoneFloat` 负责置位。 */\n"
     "  transferDone: boolean = false;\n")

# ② showRecvDoneFloat：置位
cutL('done-set',
     "    this.snapshot.transferText = `✓ ${label}`;\n"
     "    this.snapshot.transferPercent = 100;\n",
     "    this.snapshot.transferText = label;\n"
     "    this.snapshot.transferPercent = 100;\n"
     "    this.snapshot.transferDone = true;\n")

# ③ 清空处统一置 false（三处 + 计时器回调）
cutL('clear-done-timer',
     "      this.doneFloatTimer = -1;\n"
     "      this.snapshot.transferText = '';\n"
     "      this.snapshot.transferPercent = 0;\n"
     "      this.snapshot.transferSub = '';\n"
     "      this.resetSpeed();\n"
     "      this.emit();\n",
     "      this.doneFloatTimer = -1;\n"
     "      this.snapshot.transferText = '';\n"
     "      this.snapshot.transferPercent = 0;\n"
     "      this.snapshot.transferSub = '';\n"
     "      this.snapshot.transferDone = false;\n"
     "      this.resetSpeed();\n"
     "      this.emit();\n")

cutL('clear-done-webfail',
     "    } else {\n"
     "      this.snapshot.transferText = '';\n"
     "      this.snapshot.transferPercent = 0;\n"
     "      this.snapshot.transferSub = '';\n"
     "      this.resetSpeed();\n"
     "    }\n",
     "    } else {\n"
     "      this.snapshot.transferText = '';\n"
     "      this.snapshot.transferPercent = 0;\n"
     "      this.snapshot.transferSub = '';\n"
     "      this.snapshot.transferDone = false;\n"
     "      this.resetSpeed();\n"
     "    }\n")

cutL('clear-done-report',
     "    this.snapshot.transferSub = '';\n"
     "    this.resetSpeed();\n"
     "    this.lastReportBytes = 0;\n",
     "    this.snapshot.transferSub = '';\n"
     "    this.snapshot.transferDone = false;\n"
     "    this.resetSpeed();\n"
     "    this.lastReportBytes = 0;\n")

# ④ 进度开始时清完成态（连传多个文件时上一段的绿底不能残留）
cutL('progress-clear-done',
     "      this.snapshot.transferText = `${verb} ${r.fileName}`;\n"
     "      this.snapshot.transferPercent = r.percent;\n",
     "      this.snapshot.transferText = `${verb} ${r.fileName}`;\n"
     "      this.snapshot.transferPercent = r.percent;\n"
     "      this.snapshot.transferDone = false;\n")

cutL('web-progress-clear-done',
     "    this.snapshot.transferText = `网页上传 ${who}`;\n"
     "    this.snapshot.transferPercent = pct;\n",
     "    this.snapshot.transferText = `网页上传 ${who}`;\n"
     "    this.snapshot.transferPercent = pct;\n"
     "    this.snapshot.transferDone = false;\n")

# ═══════════════ Index ═══════════════

# ⑤ 删掉失效的 getter，改成 @State
cutN('drop-getter',
     "  /**\n"
     "   * ★ 5.1.41：浮层是否处于「完成态」。\n"
     "   *   判据：`LanService` 在完成时把 `transferText` 写成 `✓ <文件名>`\n"
     "   *   （见 `showRecvDoneFloat`），所以前缀 `✓` 就是完成标记。\n"
     "   */\n"
     "  private get tDone(): boolean {\n"
     "    return this.tText.startsWith('\\u2713');\n"
     "  }\n",
     "  /**\n"
     "   * ★ 5.1.42：浮层是否处于「完成态」。\n"
     "   *   ⚠️ 5.1.41 用 getter + 字符串前缀（`startsWith('\\u2713')`）判定，实测失效\n"
     "   *   不变色 / 地球不消失）—— 根因是「转义写法 + 依赖文案 + getter 读 @State\n"
     "   *   在 @Builder 里追踪不可靠」三者叠加。\n"
     "   *   ⇒ 改为**独立 @State**，由 `snapshot.transferDone` 显式驱动。\n"
     "   */\n"
     "  @State tDone: boolean = false;\n")

# ⑥ onSnapshot 同步
cutN('snapshot-sync-done',
     "    if (s.transferSub !== this.tSub) {\n"
     "      this.tSub = s.transferSub;\n"
     "    }\n",
     "    if (s.transferSub !== this.tSub) {\n"
     "      this.tSub = s.transferSub;\n"
     "    }\n"
     "    if (s.transferDone !== this.tDone) {\n"
     "      this.tDone = s.transferDone;\n"
     "    }\n")

# ⑦ 布局整体重排
i = ix.index('  transferFloat() {')
j = ix.index("      .margin({ top: this.topInset + 56 })\n    }\n  }\n", i)
j += len("      .margin({ top: this.topInset + 56 })\n    }\n  }\n")

newFloat = '''  transferFloat() {
    if (this.tText.length > 0) {
      Column({ space: 8 }) {
        // ── 第 1 行：图标 + 文件名，**独占整行剩余宽度** ──
        // ★ 5.1.42：5.1.41 把「文件名 + 百分比」放同一行，长文件名被百分比挤到
        //   只剩 `...`（vivi 实测）。⇒ 百分比挪到第 2 行的进度条右侧，
        //   文件名独占一行，ellipsis 才有意义。
        Row({ space: 8 }) {
          // ★ 完成态**不渲染** LoadingProgress —— 它是动画组件，只要挂在树上
          //   就一直转（vivi：「地球也没有停止，可以改成传输完成后不显示地球」）。
          //   改渲染静态 ✓。
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
          Text(this.tText)
            .fontSize(13)
            .fontColor('#FFFFFF')
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // ── 第 2 行：进度条（吃剩余宽度）+ 百分比（固定不被挤掉）──
        // ⚠️ 弃用 Progress 组件：真机主题下它的「填充色 / 轨道色」会被画反，
        // 表现为"全黄逐渐变白"（vivi 2026-09-30 实测）。这里用两个 Row 自己实现：
        // 外层轨道固定白色（空白即白色），内层 Row 宽度按百分比增长 = 黄色实心填充。
        // ⚠️ 这条 `.animation()` 是「进度看起来线性」的关键补充：
        //    接收侧的上报再密也有 100ms 的节流，末段几个分片同时收齐时
        //    百分比仍可能一次跳好几个点。给宽度加 240ms 线性过渡后，
        //    视觉上是「追上去」而不是「啪一下跳过去」。
        Row({ space: 8 }) {
          Row() {
            Row()
              .height(4)
              .borderRadius(2)
              .backgroundColor('#FFD54F')
              .width(`${this.tPercent}%`)
              .animation({ duration: 240, curve: Curve.Linear })
          }
          .layoutWeight(1)
          .height(4)
          .borderRadius(2)
          .backgroundColor('#FFFFFF')

          Text(`${this.tPercent}%`)
            .fontSize(13)
            .fontColor('#FFFFFF')
            .fontWeight(FontWeight.Bold)
            .width(46)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // ── 第 3 行：副信息（序号 / 已收-总量）+ 实时速度 ──
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
      .backgroundColor(this.tDone ? C_DONE_OK : C_PRIMARY)
      .borderRadius(12)
      .shadow({ radius: 16, color: '#20000000', offsetX: 0, offsetY: 6 })
      .margin({ top: this.topInset + 56 })
    }
  }
'''
cutN('transferFloat', ix[i:j], newFloat)

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

assert '"versionCode": 5000141' in app and '"versionName": "5.1.41"' in app, 'version'
app = app.replace('"versionCode": 5000141', '"versionCode": 5000142', 1)
app = app.replace('"versionName": "5.1.41"', '"versionName": "5.1.42"', 1)

# 残留检查：getter 版判定必须彻底消失
def _code_only(t):
    return '\n'.join(ln for ln in t.split('\n')
                     if not ln.strip().startswith(('//', '*', '/*')))
assert 'tText.startsWith' not in _code_only(ix), 'tText.startsWith 判定残留'
assert 'private get tDone' not in _code_only(ix), '旧 getter 残留'

io.open(LS, 'w', encoding='utf-8', newline='\n').write(ls)
io.open(IX, 'w', encoding='utf-8', newline='\n').write(ix)
io.open(APP, 'w', encoding='utf-8', newline='\n').write(app)

ls2 = io.open(LS, encoding='utf-8', newline='').read()
ix2 = io.open(IX, encoding='utf-8', newline='').read()
print('LS 块 %d / IX 块 %d' % (len(L), len(N)))
print('transferDone  LS=%d IX=%d' % (ls2.count('transferDone'), ix2.count('transferDone')))
print('tDone @State IX=%d' % ix2.count('tDone'))
print('完成文案无 ✓   :', '✓ ${label}' not in ls2)
print('C_DONE_OK     IX=%d' % ix2.count('C_DONE_OK'))
print('百分比在第2行   :', ix2.count('.width(46)'))
print('CRLF          %d' % (ls2.count('\r\n') + ix2.count('\r\n')))
print('OK 5.1.42 applied')
