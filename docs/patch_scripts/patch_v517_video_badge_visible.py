# -*- coding: utf-8 -*-
"""
v5.1.7 修「视频」占位文字被缩略图盖住（vivi 21:44）。

## 根因
`mediaThumbFixed` 的 `Stack` 里三个子项**都没写 `align`**，全部默认居中、
并**按声明顺序叠放**（后写的盖在先写的上面）：

```typescript
Stack() {
  Text(isVideo ? '视频' : '图片')   // ①  最先声明 => 最低层 => 被 Image 盖住
  if (path.length > 0) {
    if (isVideo && isVideoName) {
      if (hasVideoThumb) Image(...)   // ②  盖住 ①
      Text('▶')                        // ③  最后声明 => 最上层（所以 ▶ 看得见）
    } else {
      Image(...)                       // ②' 盖住 ①
    }
  }
}
```
⇒ 缩略图一旦载入，**「视频」两个字必然被盖住**（占位文字本来就是「还没解出来时的样子」）。

## 修法
把「视频/图片」占位文字**明确放到最底层**（`align(Alignment.Bottom)` 移到底边），
让它在**图片没解出来时**显示在下方，而**图片载入后仍保留一小截可见** ——
★ 更稳的做法：给占位文字加 `.zIndex`? ArkUI 的 `Stack` 用**声明顺序**决定层级，
所以「最低层」= **必须第一个声明**（已经是了）⇒ 问题不在层级，而在**它与 Image 完全重叠**。
⇒ 真正的修法 = **把占位文字挪出重叠区**（`align(Alignment.Bottom)` + 底部留白），
  这样即使图片铺满方框，底部那一小条仍然可见。

★ 另一种更彻底的选择：占位文字**只在没有图时显示**（`if (path.length === 0)`），
  视频的区分**完全交给 ▶ 角标**（它已验证可见）。
  ⇒ 选这条：**语义更干净**（「视频」本就是「还没解出来时的占位」），
  且不会与 Image 抢层级。

## 顺带
`▶` 角标**加 `align` 居中**（现在靠默认居中，能用但显式更稳），
并给它加一个半透明底衬 —— 否则在浅色图上白字看不清。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 改 1：占位文字只在「没有图」时显示（挪出与 Image 的重叠区）
# =====================================================================
OLD1 = """    Stack() {
      // 占位（也是解码失败 / 还没解出来的样子），真图载入后盖住它
      Text(isVideo ? '视频' : '图片')
        .fontSize(11)
        .fontColor('#AAAAAA')
      if (path.length > 0) {"""
NEW1 = """    Stack() {
      // ★ 5.1.7：占位文字**只在「没有图」时显示**。
      //   ⚠️ 原写法是**无条件**显示（靠「写在 Stack 第一个子项 = 最低层」想让它被
      //     盖住），但 `Stack` 的三个子项**都没写 `align`、全部居中且完全重叠** ⇒
      //     图片铺满方框后**必然把它盖住**（vivi 21:44 反馈「视频文字被缩略图盖住了」）。
      //   ⇒ 现在把「视频/图片」**限定为占位语义**（图还没解出来时的样子），
      //     视频的区分**交给 ▶ 角标**（它写在最后 = 最上层，一直可见）。
      //   ★ 语义也更干净：这两个字本来就是「占位」，不是「类型标签」。
      if (path.length === 0) {
        Text(isVideo ? '视频' : '图片')
          .fontSize(11)
          .fontColor('#AAAAAA')
      }
      if (path.length > 0) {"""

# =====================================================================
# 改 2：▶ 角标显式居中 + 加半透明底衬（浅色图上白字看不清）
# =====================================================================
OLD2 = """          // 播放角标：盖在图上，一眼区分「图」和「视频」
          Text('▶')
            .fontSize(24)
            .fontColor('#FFFFFF')"""
NEW2 = """          // 播放角标：盖在图上，一眼区分「图」和「视频」。
          // ★ 5.1.7：`align` 从「靠默认居中」改成**显式居中**（别依赖默认值），
          //   并加半透明黑底衬 —— 白字在浅色图上几乎看不见（5.0.57 之后图片都铺满方框，
          //   浅色内容很容易出现）。
          Stack({ alignContent: Alignment.Center }) {
            Text('▶')
              .fontSize(24)
              .fontColor('#FFFFFF')
          }
          .width(34)
          .height(34)
          .backgroundColor('#66000000')
          .borderRadius(17)"""

# =====================================================================
# 版本号
# =====================================================================
OLDV = '"versionCode": 5000106'
NEWV = '"versionCode": 5000107'

REPL = [
    (OLD1, NEW1, 'P1 占位文字只在无图时显示'),
    (OLD2, NEW2, 'P2 ▶ 角标显式居中 + 底衬'),
]

s = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if '5.1.7' in s:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v517pre'), 'w', encoding='utf-8', newline='\n').write(s)
io.open(os.path.join(BAK, 'app.json5.v517pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成')

for old, new, tag in REPL:
    n = s.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s = s.replace(old, new, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.6"') == 1
s_ver = s_ver.replace('"versionName": "5.1.6"', '"versionName": "5.1.7"', 1)

# ---------------- 不变量 ----------------
assert 'if (path.length === 0) {' in s, '占位文字未加条件'
assert "Text('▶')" in s, '▶ 角标丢了'
assert 'alignContent: Alignment.Center' in s, '▶ 角标未显式居中'
assert "'#66000000'" in s, '▶ 角标底衬未加'
# 图片仍铺满（5.0.57 / 5.0.59b 的成果）
assert 'objectFit(ImageFit.Cover)' in s
assert '.autoResize(true)' in s
assert 'sourceSize' not in s.split('mediaThumbFixed(')[1].split('\n  @Builder')[0], 'sourceSize 回来了（会拉伸）'
# 5.1.5 / 5.1.6 / 5.1.4 成果仍在
assert '@State localStateTick: number = 0;' in s
assert 'private padHint(s: string, _tick: number = 0): string {' in s
assert "private static readonly VIDEO_BADGE: string = 'VIDEO';" in s
assert 'if (this.showAbout) {' in s
assert 'private msgCarriesFileName(' in s
assert 'private diagSnapshot(' not in s and 'this.diagSnapshot(' not in s

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  Index.ets %d chars' % len(s))
print('OK  versionCode 5000106 -> 5000107 / 5.1.7')
