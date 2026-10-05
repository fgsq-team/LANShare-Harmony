# -*- coding: utf-8 -*-
"""5.1.50 补：浮层「接收」独立组件（主补丁脚本因插入位置错乱漏了这四块）"""
import io, sys

P = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
SENT = '5.1.50'

s = io.open(P, encoding='utf-8', newline='').read()
if '@State tVerb' in s:
    print('ALREADY'); sys.exit(0)

B = []
def rep(tag, old, new): B.append((tag, old, new))

# ① State 字段
rep('state',
    "  @State tSub: string = '';",
    "  @State tSub: string = '';\n"
    "  /**\n"
    "   * ★ 5.1.50：浮层标题的**动词**（`接收`）。\n"
    "   * 与文件名**分成两个组件**渲染 —— 5.1.49 拼成 `Text('接收 ' + 文件名)`\n"
    "   * 一个字符串时，ArkUI **在空格处自动折行** ⇒「接收」独占第一行、\n"
    "   * 文件名被挤到第二行且再次截断（vivi 截图）。\n"
    "   */\n"
    "  @State tVerb: string = '';")

# ② onSnapshot 同步
rep('sync',
    """    if (s.transferSub !== this.tSub) {
      this.tSub = s.transferSub;
    }""",
    """    if (s.transferSub !== this.tSub) {
      this.tSub = s.transferSub;
    }
    // ★ 5.1.50：动词同步（与文件名分两个组件，见 tVerb 注释）
    if (s.verb !== this.tVerb) {
      this.tVerb = s.verb;
    }""")

# ③ 传输中标题行：[地球][动词 32 宽][文件名 独占剩余]
rep('ui-progress',
    """              LoadingProgress()
                .width(18)
                .height(18)
                .color('#FFFFFF')
              // ★ 5.1.45 起标题只放文件名（动词在副行）；5.1.44 实测
              //   超长文件名时 ArkUI 的 ellipsis 会把可用宽度算成 0
              //   （只画 `...`），所以这里给两行。
              Text(this.tText)
                .layoutWeight(1)""",
    """              LoadingProgress()
                .width(18)
                .height(18)
                .color('#FFFFFF')
              // ★★ 5.1.50：动词是**独立组件**，保证与文件名同一行。
              //   5.1.49 把它拼进 transferText，ArkUI 在空格处折行 ⇒
              //   「接收」独占第一行、文件名被挤掉（vivi 截图）。
              //   ⚠️ 宽度**固定 32**，绝不能给 layoutWeight（那是文件名该用的）。
              if (this.tVerb.length > 0) {
                Text(this.tVerb)
                  .fontSize(13)
                  .fontColor('#FFFFFF')
                  .width(32)
                  .maxLines(1)
              }
              // ★ 文件名独占剩余宽度，最多两行。
              //   5.1.44 实测超长文件名时 ArkUI 的 ellipsis 会把可用宽度算成 0
              //   （只画 `...`），所以给两行。
              Text(this.tText)
                .layoutWeight(1)""")

# ④ 完成态标题行：补一个 32 宽空占位，与传输中**对齐**（否则文件名会横向跳）
rep('ui-done',
    """              Text('\\u2713')
                .fontSize(16)
                .fontColor('#FFFFFF')
                .width(18)
                .textAlign(TextAlign.Center)
              Text(this.tText)
                .layoutWeight(1)""",
    """              Text('\\u2713')
                .fontSize(16)
                .fontColor('#FFFFFF')
                .width(18)
                .textAlign(TextAlign.Center)
              // ★ 5.1.50：与传输中**同样的两段结构**（32 宽占位 + 文件名），
              //   否则切到完成态时文件名会横向跳一下。
              //   传输中：[地球18][动词32][文件名]；完成态：[✓18][空32][文件名]
              Text('')
                .width(32)
                .maxLines(1)
              Text(this.tText)
                .layoutWeight(1)""")

for tag, old, new in B:
    n = s.count(old)
    assert n == 1, '%s count=%d (期望 1)' % (tag, n)
for tag, old, new in B:
    s = s.replace(old, new, 1)

assert '@State tVerb' in s
assert s.count('this.tVerb') == 4, 'tVerb 引用数 %d' % s.count('this.tVerb')
assert '\r' not in s
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('块数 %d | tVerb 引用 %d | OK' % (len(B), s.count('this.tVerb')))