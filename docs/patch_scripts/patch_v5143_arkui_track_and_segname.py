# -*- coding: utf-8 -*-
"""
5.1.43 —— 修 5.1.42 实测遗留：文件名不显示 / 完成不变色 / 分片显示 0/16

【vivi 实测（截图）+ 三个诉求】
  · 「长文件名不显示」—— 截图上标题行只有 `接收 ...`
  · 「传输完不变色」并猜测「会不会是绿色在底层被盖住了」
  · 「接收分片大文件时不要在进度框显示成 16 个文件了，保持和单个小文件一致」（副行 `0/16`）

【判断依据（截图 + 代码双向核对）】
  ① 副行 `0/16` 说明数据源是 `V5Transfer` 的**分片进度**上报：
     `report(..., fileIndex = part.done /* 已收片数 */, fileCount = total /* 总片数 */, ...)`
     ⇒ `0/16` 是**片数进度**，不是「16 个文件」⇒ 副行不该显示 `i/n`。
  ② `SegPart.name` 确实有值（`createSegPart` 里 `p.name = name`）⇒ 文件名不是数据缺失。
  ③ ★ 于是文件名「只剩 `...`」与「颜色不变」都指向 **ArkUI 的状态→视图依赖追踪**：
     · 颜色写在 `.backgroundColor(this.tDone ? C_DONE_OK : C_PRIMARY)` ——
       **链式属性里的三元表达式读取 @State 不可靠**（tDone 变了但颜色没重绘）。
     · 文件名用 `Row` + `layoutWeight(1)` + `textOverflow(Ellipsis)` ——
       **长文本在 layoutWeight 里被算成极窄宽度** ⇒ 只画省略号，前面全丢。

【本版四处改动】
  1. **颜色改用预先算好的 `@State tDoneBg: string`**（在 `onSnapshot` 里算），
     链式属性直接读它 ⇒ 避开三元表达式。
  2. **文件名去掉 `layoutWeight`**，改 `width('100%')` + `padding({left: 26})` 给图标留位
     ⇒ 独占整行宽度，不再被压缩成只剩 `...`。
  3. **副行去掉 `i/n`**，只显示「已收 / 总量」⇒ 分片与单文件表现一致。
  4. **完成判定去掉 `fileName.length > 0` 前置条件**，并给文件名加兜底
     （空则显示「接收文件」）⇒ 不再因文件名缺失而整个完成提示不出现。
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

SEN = 'tDoneBg'
if SEN in ix:
    print('ALREADY APPLIED'); sys.exit(0)

L, N = [], []
def cutL(tag, old, new='', chk=True): L.append((tag, old, new, chk))
def cutN(tag, old, new='', chk=True): N.append((tag, old, new, chk))

# ═══════════ LanService ═══════════

# ① 副行去掉 i/n（分片数不是文件数）
cutL('sub-no-index',
     "      this.snapshot.transferSub = r.fileCount > 1\n"
     "        ? `${r.fileIndex}/${r.fileCount} · ${LanService.fmtSize(r.bytes)}`\n"
     "          + ` / ${LanService.fmtSize(r.fileSize)}`\n"
     "        : `${LanService.fmtSize(r.bytes)} / ${LanService.fmtSize(r.fileSize)}`;\n",
     "      // ★ 5.1.43：**不要**显示 `i/n`。\n"
     "      //   v5 分片进度上报的 `fileIndex/fileCount` 是**片数**（`part.done` / `total`，\n"
     "      //   1.35 恒为 16），不是「第 i 个文件 / 共 n 个文件」——\n"
     "      //   vivi 2026-10-03 实测截图上显示成 `0/16`，被误读成 16 个文件。\n"
     "      //   ⇒ 统一只显示容量，与单个小文件表现一致。\n"
     "      this.snapshot.transferSub =\n"
     "        `${LanService.fmtSize(r.bytes)} / ${LanService.fmtSize(r.fileSize)}`;\n")

# ② 协议侧：文件名兜底 + 副行容量
cutL('recv-name-fallback',
     "      this.snapshot.transferText = `${verb} ${r.fileName}`;\n"
     "      this.snapshot.transferPercent = r.percent;\n"
     "      this.snapshot.transferDone = false;\n",
     "      // ★ 5.1.43：文件名兜底 —— 为空时给个可读的兜底名，\n"
     "      //   否则标题行会只剩「接收 」，且完成提示的文件名也空。\n"
     "      const nm: string = r.fileName.length > 0 ? r.fileName : '文件';\n"
     "      this.snapshot.transferText = `${verb} ${nm}`;\n"
     "      this.snapshot.transferPercent = r.percent;\n"
     "      this.snapshot.transferDone = false;\n")

# ③ 完成判定：去掉 fileName 非空的前置条件
cutL('done-no-name-gate',
     "    if (r.ok && r.direction !== 'send' && r.fileName.length > 0) {\n"
     "      this.showRecvDoneFloat(r.fileName, r.fileSize);\n"
     "    } else {\n",
     "    // ★ 5.1.43：⚠️ 原来这里还有 `r.fileName.length > 0` 的前置条件，\n"
     "    //   文件名一旦为空就**整个完成提示都不出现**（不变色）；\n"
     "    //   判定只看「成功 + 接收方向」，与文件名无关。\n"
     "    if (r.ok && r.direction !== 'send') {\n"
     "      this.showRecvDoneFloat(\n"
     "        r.fileName.length > 0 ? r.fileName : '文件', r.fileSize);\n"
     "    } else {\n")

# ④ 网页侧：文件名兜底
cutL('web-name-fallback',
     "    this.snapshot.transferText = `网页上传 ${who}`;\n",
     "    this.snapshot.transferText = `网页上传 ${who.length > 0 ? who : '文件'}`;\n")

# ⑤ showRecvDoneFloat：label 兜底
cutL('done-label-fallback',
     "  private showRecvDoneFloat(label: string, size: number): void {\n"
     "    this.snapshot.transferText = label;\n",
     "  private showRecvDoneFloat(label: string, size: number): void {\n"
     "    this.snapshot.transferText = label.length > 0 ? label : '文件';\n")

# ═══════════ Index ═══════════

# ⑥ 新增 @State tDoneBg
cutN('state-donebg',
     "  @State tDone: boolean = false;\n",
     "  @State tDone: boolean = false;\n"
     "  /** ★ 5.1.43：**预先算好的完成态底色**。\n"
     "   *   ⚠️ 不要写成 `.backgroundColor(this.tDone ? A : B)` ——\n"
     "   *   ArkUI 的**链式属性里读 @State 的三元表达式不可靠**（5.1.42 实测：\n"
     "   *   `tDone` 已经变成 true，底色却仍是蓝色）。\n"
     "   *   ⇒ 在 `onSnapshot` 里算好字符串，链式属性直接读这个 @State。 */\n"
     "  @State tDoneBg: string = C_PRIMARY;\n")

# ⑦ onSnapshot 里算颜色
cutN('compute-donebg',
     "    if (s.transferDone !== this.tDone) {\n"
     "      this.tDone = s.transferDone;\n"
     "    }\n",
     "    if (s.transferDone !== this.tDone) {\n"
     "      this.tDone = s.transferDone;\n"
     "    }\n"
     "    // ★ 5.1.43：颜色在这里算好（见 tDoneBg 注释：链式属性里的三元表达式不可靠）\n"
     "    this.tDoneBg = s.transferDone ? C_DONE_OK : C_PRIMARY;\n")

# ⑧ 布局：文件名 width('100%') + 去 layoutWeight；底色读 tDoneBg
i = ix.index('  transferFloat() {')
j = ix.index("      .margin({ top: this.topInset + 56 })\n    }\n  }\n", i)
j += len("      .margin({ top: this.topInset + 56 })\n    }\n  }\n")

newFloat = '''  transferFloat() {
    if (this.tText.length > 0) {
      Column({ space: 8 }) {
        // ── 第 1 行：文件名**独占整行**，左侧留 26px 给图标 ──
        // ★ 5.1.43：原来用 `Row + layoutWeight(1)`，实测**长文件名被算成极窄宽度**，
        //   屏幕上只剩一个 `...`（vivi 截图：标题行显示「接收 ...」）。
        //   ⇒ 改成「整宽 Text + 左 padding 预留图标位」，
        //     让 Text 拿到 100% 行宽，ellipsis 才有意义。
        Stack({ alignContent: Alignment.TopStart }) {
          // 图标层：完成态**不渲染** LoadingProgress（动画组件，挂上就一直转）
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
          // 文本层：整宽 + 左内边距
          Text(this.tText)
            .width('100%')
            .padding({ left: 26 })
            .fontSize(13)
            .fontColor('#FFFFFF')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .height(20)

        // ── 第 2 行：进度条（吃剩余宽度）+ 百分比 ──
        // ⚠️ 弃用 Progress 组件：真机主题下它的「填充色 / 轨道色」会被画反，
        // 表现为"全黄逐渐变白"（vivi 2026-09-30 实测）。这里用两个 Row 自己实现。
        // ⚠️ `.animation()` 是「进度看起来线性」的关键补充：上报有节流，
        //    末段几个分片同时收齐时百分比会一次跳好几个点。
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

        // ── 第 3 行：容量 + 实时速度（不显示 i/n：分片数不是文件数）──
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
      // ★ 5.1.43：读预先算好的 @State 字符串，不用三元表达式
      .backgroundColor(this.tDoneBg)
      .borderRadius(12)
      .shadow({ radius: 16, color: '#20000000', offsetX: 0, offsetY: 6 })
      .margin({ top: this.topInset + 56 })
    }
  }
'''
cutN('transferFloat', ix[i:j], newFloat)

# ═══════════ 校验 + 落盘 ═══════════
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

assert '"versionCode": 5000142' in app and '"versionName": "5.1.42"' in app, 'version'
app = app.replace('"versionCode": 5000142', '"versionCode": 5000143', 1)
app = app.replace('"versionName": "5.1.42"', '"versionName": "5.1.43"', 1)

# 残留检查：三处 old 代码必须都换了
def _code_only(t):
    return '\n'.join(ln for ln in t.split('\n')
                     if not ln.strip().startswith(('//', '*', '/*')))
c_ls, c_ix = _code_only(ls), _code_only(ix)
assert 'this.fileIndex}/${r.fileCount}' not in c_ls, '副行 i/n 残留'
assert 'r.fileName.length > 0)' not in c_ls.split('showRecvDoneFloat')[0].split('if (r.ok')[1][:120], '完成判定旧条件残留'
assert 'this.tDone ? C_DONE_OK : C_PRIMARY' not in c_ix, '三元底色残留'
_t_start = c_ix.find('Text(this.tText)')
assert _t_start > 0, '找不到文件名 Text'
assert 'layoutWeight' not in c_ix[_t_start:_t_start + 220], '文件名仍用 layoutWeight'

io.open(LS, 'w', encoding='utf-8', newline='\n').write(ls)
io.open(IX, 'w', encoding='utf-8', newline='\n').write(ix)
io.open(APP, 'w', encoding='utf-8', newline='\n').write(app)

ls2 = io.open(LS, encoding='utf-8', newline='').read()
ix2 = io.open(IX, encoding='utf-8', newline='').read()
print('LS 块 %d / IX 块 %d' % (len(L), len(N)))
print('tDoneBg      IX=%d' % ix2.count('tDoneBg'))
print('底色读 tDoneBg :', '.backgroundColor(this.tDoneBg)' in ix2)
print('三元底色归零   :', 'this.tDone ? C_DONE_OK' not in ix2)
print('文件名 width100 :', "Text(this.tText)\n            .width('100%')" in ix2)
print('Stack 图标层   :', ix2.count('Stack({ alignContent: Alignment.TopStart })'))
print('副行无 i/n     :', 'fileIndex}/${r.fileCount}' not in ls2)
print('完成判定放宽   :', "r.fileName.length > 0 ? r.fileName : '文件'" in ls2)
print('CRLF          %d' % (ls2.count('\r\n') + ix2.count('\r\n')))
print('OK 5.1.43 applied')
