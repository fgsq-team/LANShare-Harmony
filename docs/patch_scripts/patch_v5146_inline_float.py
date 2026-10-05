# -*- coding: utf-8 -*-
"""
5.1.46 —— 浮层改为**内联写进 build()**（不用 @Builder）+ 补回传输中的地球

【vivi 5.1.45 实测（两张截图）】
  图1（传输中 31%）：换行修好了、副行 `接收 · 200.8 MB / 646.1 MB` 正确，
                    ★★ 但**地球没了** —— 这是 5.1.45 自己的回归：
                    重写 `transferFloatProgress` 时把第一行的
                    `LoadingProgress` 整个删掉了（标题只剩 `Text(tText)`）。
  图2（完成 100%）：★ **`✓` 图标与满格白条都出现了** ⇒ 5.1.45 把条件分支提到
                    `build()` 顶层**是有效的**（`tDone` 确实切到了完成态浮层），
                    ★★ **但底色仍是蓝的** —— `.backgroundColor(C_DONE_OK)`
                    这个**链式属性**在 `@Builder` 内没生效。

【★ 定案：ArkUI 里凡是「随状态变化的链式属性 / 条件渲染」，
        都要写在 `build()` 的执行上下文里，不能藏在 `@Builder` 里。】
  5.1.42 → 5.1.43 两次都在 `@Builder` 内改 `backgroundColor`，两次都没生效；
  5.1.45 把 `if (this.tDone)` 提到顶层后条件生效了，但 `@Builder` **内部**的
  `backgroundColor(C_DONE_OK)` 依旧是死的 ⇒ 说明「@Builder 整体」都不可靠，
  不只是「条件」。
  ⇒ 本版**彻底不用 @Builder**，把两个浮层的 UI 直接内联写在 `build()` 的
    `if / else` 分支里 —— 这是 ArkUI 最原始、最可靠的写法。

【本版三件事】
  1. 浮层 UI 从两个 `@Builder` 搬进 `build()` 内联（`if (this.tDone) {...} else {...}`）。
  2. ★ **补回传输中的 `LoadingProgress` 地球**（5.1.45 的回归）：
     传输中第一行 = `⟳ LoadingProgress` + 文件名（可两行）。
  3. 完成态 = 静态 `✓` + 文件名 + 满格白条 + 绿底 `C_DONE_OK`。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IX = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

ix = io.open(IX, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

SEN = '5.1.46 内联浮层'
if SEN in ix:
    print('ALREADY APPLIED'); sys.exit(0)

blocks = []
def cut(tag, old, new=''): blocks.append((tag, old, new))

# ═══ ① 删掉两个 @Builder（整段）═══
i = ix.index('  /**\n   * 全局传输进度浮层 —— **按完成态拆成两个独立 @Builder**。')
j = ix.index('  /**\n   * 「发文件给谁」弹窗（消息 tab 的「+」调起）。')
cut('drop-builders', ix[i:j], '')

# ═══ ② build() 顶层内联两个分支 ═══
cut('inline-float',
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
     "      }\n",
     """      // ---------------- 全局传输进度浮层（跨 tab）----------------
      // ★★★ 5.1.46：**完全内联**，不用 @Builder。
      //   依据（vivi 5.1.45 实测）：`if (this.tDone)` 提到 build() 顶层后条件生效了
      //   （完成态的 ✓ 图标与满格白条都出现了），**但同一个 @Builder 内部的
      //   `.backgroundColor(C_DONE_OK)` 依然是蓝的** ⇒ 说明「@Builder 整体」
      //   对随状态变化的链式属性都不可靠，不只是条件分支。
      //   ⇒ ArkUI 里凡是「随状态变化的样式/条件渲染」，一律写在 build() 的
      //     执行上下文里，这是最原始也最可靠的写法。
      if (this.tText.length > 0) {
        if (this.tDone) {
          // ── 完成态：绿底 + 静态 ✓ + 满格白条 ──
          // ⚠️ 不渲染 LoadingProgress：它是**动画组件**，挂在树上就一直转。
          Column({ space: 8 }) {
            Row({ space: 8 }) {
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
          .backgroundColor(C_DONE_OK)
          .borderRadius(12)
          .shadow({ radius: 16, color: '#20000000', offsetX: 0, offsetY: 6 })
          .margin({ top: this.topInset + 56 })
        } else {
          // ── 传输中：蓝底 + **转动的地球** + 文件名 + 进度条 + 副行 ──
          Column({ space: 8 }) {
            Row({ space: 8 }) {
              // ★ 5.1.46 补回：5.1.45 重写时把地球（LoadingProgress）删掉了，
              //   vivi 截图确认「传输过程中的地球也没了」。
              LoadingProgress()
                .width(18)
                .height(18)
                .color('#FFFFFF')
              // ★ 5.1.45 起标题只放文件名（动词在副行）；5.1.44 实测
              //   超长文件名时 ArkUI 的 ellipsis 会把可用宽度算成 0
              //   （只画 `...`），所以这里给两行。
              Text(this.tText)
                .layoutWeight(1)
                .fontSize(13)
                .fontColor('#FFFFFF')
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
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
""")

# ═══ 校验 + 落盘 ═══
for tag, old, new in blocks:
    n = ix.count(old)
    assert n == 1, '%s count=%d' % (tag, n)
    if new:
        assert ix.count(new) == 0, '%s 新文本已存在' % tag
for tag, old, new in blocks:
    ix = ix.replace(old, new, 1)

assert 'transferFloatProgress' not in ix and 'transferFloatDone' not in ix, '旧 Builder 残留'
assert 'LoadingProgress()' in ix, '地球未补回'
assert '.backgroundColor(C_DONE_OK)' in ix, '绿底缺失'
assert ix.count('.backgroundColor(C_PRIMARY)') >= 1, '蓝底缺失'

assert '"versionCode": 5000145' in app and '"versionName": "5.1.45"' in app, 'version'
app = app.replace('"versionCode": 5000145', '"versionCode": 5000146', 1)
app = app.replace('"versionName": "5.1.45"', '"versionName": "5.1.46"', 1)

io.open(IX, 'w', encoding='utf-8', newline='\n').write(ix)
io.open(APP, 'w', encoding='utf-8', newline='\n').write(app)

print('改块数 %d' % len(blocks))
print('旧 Builder 归零 :', 'transferFloatProgress' not in ix)
print('内联 if/else    :', 'if (this.tDone) {' in ix)
print('LoadingProgress :', ix.count('LoadingProgress()'))
print('绿底 C_DONE_OK  :', ix.count('.backgroundColor(C_DONE_OK)'))
print('蓝底 C_PRIMARY  :', ix.count('.backgroundColor(C_PRIMARY)'))
print('CRLF            :', ix.count('\r\n'))
print('OK 5.1.46 applied')
