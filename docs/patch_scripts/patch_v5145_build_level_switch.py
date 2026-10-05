# -*- coding: utf-8 -*-
"""
5.1.45 —— ★ 决定性修复：条件判断从 @Builder 内部提到 build() 顶层 + 标题只放文件名

【vivi 5.1.44 实测（两张截图）—— 拿到了分水岭证据】
  图2 底部出现系统 Toast：`接收完成：✓ launchermap_3.9.151-0930jffghjtdfjddvhdxhxcgij.apk`
  ★★ 这个 Toast 是在 `onSnapshot` 里用
     `if (s.transferDone && !this.tDoneToastShown) { this.toast(...) }` 弹的
     ⇒ **它出现，就证明 `s.transferDone === true` 走到了 UI 层、`this.tDone` 也被赋了值。**
  ★★ 而同一时刻浮层**仍然是蓝色 + 转动的地球**（图2 第一行是 `⟳ ✓`：
     地球是组件、✓ 是我写进文案的字符兜底）。
  ⇒ ★★ **定案：不是数据问题，也不是「状态没传到」，而是
     ArkUI 对「@Builder 内部的 `if (this.tDone)` 与链式属性
     `.backgroundColor(this.tDoneBg)`」的依赖追踪不生效。**
     （对比证据：同一浮层里 `tText` / `tPercent` / `tSub` / `tSpeed` 四个
       @State 都刷新正常，唯独**只变一次**的 `tDone`/`tDoneBg` 不生效。）

【★ 正解：把条件分支从 @Builder 内部提到 `build()` 顶层】
  ArkUI 里 `@Builder` 会被编译成局部渲染函数，**嵌在别的 @Builder 里时
  内部的状态条件不一定触发重建**；而 `build()` 是根组件，直接依赖状态最可靠。
  ⇒ 拆成两个独立 @Builder（`transferFloatProgress` / `transferFloatDone`），
    在根 `build()` 里：
        if (this.tText.length > 0) {
          if (this.tDone) { this.transferFloatDone() } else { this.transferFloatProgress() }
        }
  这样 `tDone` 变化 ⇒ **根组件重渲染 ⇒ 整个浮层按完成态重建** ⇒ 绿底 + 静态 ✓。

【换行逻辑修正（vivi：换行逻辑不太对）】
  图1 第一行是「接收」，第二行才是文件名（缩进 26px）—— 因为 `tText` 是
  `接收 <长文件名>`，换行后「接收」独占第一行。
  ⇒ ★ **`transferText` 改成只放文件名**（动词移到副行）：
        第一行：文件名（独占，最多两行）
        第二行：进度条 + 百分比
        第三行：`接收 · 110.0 MB / 646.1 MB` + 速度
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

SEN = 'transferFloatProgress'
if SEN in ix:
    print('ALREADY APPLIED'); sys.exit(0)

blocks = []
def cutLS(tag, old, new=''): blocks.append(('LS', tag, old, new))
def cutIX(tag, old, new=''): blocks.append(('IX', tag, old, new))

# ═══════════ LanService：标题只放文件名，动词进副行 ═══════════
cutLS('LS-title-plain',
     "      const nm: string = r.fileName.length > 0 ? r.fileName : '文件';\n"
     "      this.snapshot.transferText = `${verb} ${nm}`;\n",
     "      // ★ 5.1.45：标题**只放文件名**（动词移到副行）。\n"
     "      //   原来 `接收 <长文件名>` 换行后「接收」独占第一行、文件名被挤到第二行\n"
     "      //   （vivi 截图），观感很差。\n"
     "      const nm: string = r.fileName.length > 0 ? r.fileName : '文件';\n"
     "      this.snapshot.transferText = nm;\n")

cutLS('LS-sub-verb',
     "      const cap: string =\n"
     "        `${LanService.fmtSize(r.bytes)} / ${LanService.fmtSize(r.fileSize)}`;\n"
     "      this.snapshot.transferSub = (!r.isSeg && r.fileCount > 1)\n"
     "        ? `${r.fileIndex}/${r.fileCount} · ${cap}`\n"
     "        : cap;\n",
     "      const cap: string =\n"
     "        `${LanService.fmtSize(r.bytes)} / ${LanService.fmtSize(r.fileSize)}`;\n"
     "      // ★ 5.1.45：动词（接收/发送）移到副行，标题只留文件名。\n"
     "      const seq: string = (!r.isSeg && r.fileCount > 1)\n"
     "        ? `${r.fileIndex}/${r.fileCount} · `\n"
     "        : '';\n"
     "      this.snapshot.transferSub = `${seq}${verb} · ${cap}`;\n")

cutLS('LS-web-title',
     "    this.snapshot.transferText = `网页上传 ${who.length > 0 ? who : '文件'}`;\n",
     "    // ★ 5.1.45：同协议侧，标题只放文件名，「网页上传」进副行。\n"
     "    this.snapshot.transferText = who.length > 0 ? who : '文件';\n")

cutLS('LS-web-sub',
     "    this.snapshot.transferSub = total > 0\n"
     "      ? `${LanService.fmtSize(received)} / ${LanService.fmtSize(total)}`\n"
     "      : `已收 ${LanService.fmtSize(received)}`;\n",
     "    this.snapshot.transferSub = `网页上传 · ` + (total > 0\n"
     "      ? `${LanService.fmtSize(received)} / ${LanService.fmtSize(total)}`\n"
     "      : `已收 ${LanService.fmtSize(received)}`);\n")

# 完成态：副行加「接收完成」前缀
cutLS('LS-done-sub',
     "    this.snapshot.transferSub = LanService.fmtSize(size);\n",
     "    this.snapshot.transferSub = `接收完成 · ${LanService.fmtSize(size)}`;\n")

# ═══════════ Index：拆两个 @Builder + build 顶层切换 ═══════════
i = ix.index('  transferFloat() {')
j = ix.index("      .margin({ top: this.topInset + 56 })\n    }\n  }\n", i)
j += len("      .margin({ top: this.topInset + 56 })\n    }\n  }\n")

newBuilders = '''  /**
   * 全局传输进度浮层 —— **按完成态拆成两个独立 @Builder**。
   *
   * ★★ 5.1.45 决定性修复：原来只有一个 `transferFloat()`，完成态靠它**内部**的
   *   `if (this.tDone)` 与 `.backgroundColor(this.tDoneBg)` 表达 ——
   *   实测（vivi 截图 + 系统 Toast 已弹出）证明这两处**都不生效**：
   *   `tText`/`tPercent`/`tSub`/`tSpeed` 四个 @State 刷新正常，
   *   唯独只变一次的 `tDone`/`tDoneBg` 触发不了重绘。
   *   ⇒ ArkUI 里「@Builder 嵌套 @Builder + 状态条件 + 链式属性」不可靠。
   *   ⇒ **条件分支必须提到 `build()` 顶层**（根组件直接依赖状态最可靠），
   *     拆成两个独立浮层整体重建。
   */
  @Builder
  transferFloatProgress() {
    if (this.tText.length > 0) {
      Column({ space: 8 }) {
        // 第 1 行：文件名（独占整行，最多两行）
        // ★ 5.1.45：`transferText` 已只放文件名（动词移到副行），这里直接铺满。
        //   maxLines(2)：文本更长时 ArkUI 的 ellipsis 会把可用宽度算成 0
        //   （只画 `...`，一个字符都不显示，vivi 实测），换行是唯一可靠解。
        Text(this.tText)
          .width('100%')
          .fontSize(13)
          .fontColor('#FFFFFF')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .height(36)
        // 第 2 行：进度条 + 百分比
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
        // 第 3 行：`接收 · 容量` + 速度
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
      .backgroundColor(C_PRIMARY)
      .borderRadius(12)
      .shadow({ radius: 16, color: '#20000000', offsetX: 0, offsetY: 6 })
      .margin({ top: this.topInset + 56 })
    }
  }

  /**
   * ★ 完成态浮层（**独立 @Builder**，由 `build()` 顶层条件切换）。
   * 绿底 + 静态 ✓（**不渲染 `LoadingProgress`** —— 它是动画组件，挂上就一直转）。
   * 标题文案里已有 `✓ ` 前缀（5.1.44 加的兜底），这里再放一个图标，
   * 两者都不依赖 ArkUI 的状态追踪逻辑。
   */
  @Builder
  transferFloatDone() {
    if (this.tText.length > 0) {
      Column({ space: 8 }) {
        Row({ space: 8 }) {
          // 静态对勾（不是动画组件）
          Text('\\u2713')
            .fontSize(16)
            .fontColor('#FFFFFF')
            .width(18)
            .textAlign(TextAlign.Center)
          Text(this.tText)
            .layoutWeight(1)
            .fontSize(13)
            .fontColor('#FFFFFF')
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        Row() {
          Row()
            .height(4)
            .borderRadius(2)
            .backgroundColor('#FFFFFF')
            .width('100%')
        }
        .width('100%')
        .height(4)
        .borderRadius(2)
        .backgroundColor('#FFFFFF')
        if (this.tSub.length > 0) {
          Text(this.tSub)
            .fontSize(11)
            .fontColor('#E0E0E0')
            .width('100%')
        }
      }
      .width('96%')
      .padding({ left: 14, right: 14, top: 12, bottom: 12 })
      // ★ 完成态绿底：写在**这个独立浮层**里，不再依赖任何状态三元表达式。
      .backgroundColor(C_DONE_OK)
      .borderRadius(12)
      .shadow({ radius: 16, color: '#20000000', offsetX: 0, offsetY: 6 })
      .margin({ top: this.topInset + 56 })
    }
  }
'''
cutIX('IX-split-builders', ix[i:j], newBuilders)

# build() 顶层：条件切换
cutIX('IX-build-switch',
     "      // ---------------- 全局传输进度浮层（跨 tab） ----------------\n"
     "      this.transferFloat()\n",
     "      // ---------------- 全局传输进度浮层（跨 tab）----------------\n"
     "      // ★★ 5.1.45：条件分支必须放在 **build() 顶层**（根组件直接依赖\n"
     "      //   `tDone` ⇒ 状态一变就整体重建浮层）。\n"
     "      //   放在 `@Builder` 内部实测不触发重绘（vivi 截图 + Toast 已弹出佐证）。\n"
     "      if (this.tText.length > 0) {\n"
     "        if (this.tDone) {\n"
     "          this.transferFloatDone()\n"
     "        } else {\n"
     "          this.transferFloatProgress()\n"
     "        }\n"
     "      }\n")

# ═══════════ 校验 + 落盘 ═══════════
cur = {'LS': ls, 'IX': ix}
for tgt, tag, old, new in blocks:
    n = cur[tgt].count(old)
    assert n == 1, '%s %s count=%d' % (tgt, tag, n)
    if new:
        assert cur[tgt].count(new) == 0, '%s %s 新文本已存在' % (tgt, tag)
for tgt, tag, old, new in blocks:
    cur[tgt] = cur[tgt].replace(old, new, 1)

ls, ix = cur['LS'], cur['IX']

assert '"versionCode": 5000144' in app and '"versionName": "5.1.44"' in app, 'version'
app = app.replace('"versionCode": 5000144', '"versionCode": 5000145', 1)
app = app.replace('"versionName": "5.1.44"', '"versionName": "5.1.45"', 1)

assert 'this.transferFloat()' not in ix, '旧调用点残留'
assert 'transferFloatProgress' in ix and 'transferFloatDone' in ix, '新 builder 缺失'
assert '`${verb} ${nm}`' not in ls, '标题仍带动词'

io.open(LS, 'w', encoding='utf-8', newline='\n').write(ls)
io.open(IX, 'w', encoding='utf-8', newline='\n').write(ix)
io.open(APP, 'w', encoding='utf-8', newline='\n').write(app)

print('改块数 %d' % len(blocks))
print('LS 标题只文件名 :', '`${verb} ${nm}`' not in ls)
print('LS 副行带动词   :', ls.count('${seq}${verb} · ${cap}'))
print('完成副行        :', ls.count('接收完成 · ${LanService.fmtSize(size)}'))
print('IX 两个 Builder :', ix.count('transferFloatProgress'), '/', ix.count('transferFloatDone'))
print('build 顶层切换  :', 'if (this.tDone) {' in ix)
print('C_DONE_OK 绿底  :', ix.count('backgroundColor(C_DONE_OK)'))
print('CRLF            :', ls.count('\r\n') + ix.count('\r\n'))
print('OK 5.1.45 applied')
