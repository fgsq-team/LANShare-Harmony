# -*- coding: utf-8 -*-
"""
v5.1.8 治「视频连播放按钮都看不到」（vivi 21:4x，5.1.7 之后的第二个症状）。

## ★ 真根因（与 5.1.7 不同，是更外层的问题）

5.1.7 我把「视频/图片」占位文字限定在 `path.length === 0` 时显示，逻辑对；
但**没注意到 `▶` 角标整块被包在 `if (path.length > 0)` 里面**：

```typescript
if (path.length > 0) {                     // ★ path 为空时整块跳过
  if (isVideo && isVideoName(path)) {
    if (this.hasVideoThumb(path)) Image(...)
    Text('▶')                              // ← 角标在这里，被 path.length 门控
  } else { Image(...) }
}
```

而 `chatMediaGrid` 传的是 `this.mediaThumbSrcOf(m, 0)` ——
**缓存小图还没生成时它返回空串**（5.0.63 的「源恒定」设计：没生成时走空串占位）。
⇒ `path.length === 0` ⇒ **`▶` 那一支根本不执行** ⇒ 用户看到的就是**一个空白灰框**，
连「视频」两个字都没有（因为 5.1.7 让占位文字只在无图时显示，而 5.1.7 那版正好
把这条路径补上了，但用户反馈的是**装了 5.1.7 之后**仍然没标识）。

## 修法

把 `▶` 角标**提到 `if (path.length > 0)` 之外**（作为 `Stack` 的最后一个子项），
条件改成 **`if (isVideo)`**（用**传进来的参数** `isVideo`，不依赖 `path`/`isVideoName(path)`
—— 因为 `path` 为空时根本没法判断扩展名）。

★ 关键点：**判据必须用「消息本身是视频」这个事实（`isVideo` 形参，由 `msgIsVideo(m)` 算出）**，
  **不能用「这个路径是不是视频文件」**（路径为空时后者恒为 false）。
  这与 5.1.6 的「文案判据要覆盖所有输入类别」是同一族教训：
  **「事实」与「从路径派生的判断」要分开用，路径可能是空的。**

⚠️ 同时把 `hasVideoThumb` 的 Image 也**移出来**吗？**不** —— 那必须是视频封面图，
  没有就不画。★ 只把「身份标识（▶）」提出来，**图仍然受 path 门控**。
  ⇒ 于是三种状态都成立：
  - 有缓存封面 ⇒ 封面 + ▶
  - 无缓存但 `isVideo` ⇒ **空框 + ▶**（★ 本轮修的就是这个）
  - 图片 ⇒ 缩略图（无 ▶）
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 改 1：▶ 角标从 path 门控里提出来，作为 Stack 最后一个子项
# =====================================================================
OLD1 = """      if (path.length > 0) {
        if (isVideo && this.isVideoName(path)) {
          if (this.hasVideoThumb(path)) {
            Image(this.videoThumbOf(path) as image.PixelMap)
              // ★ 5.0.57：直接撑满方框 + `Cover` 居中裁切（vivi：把框铺满）
              .width(side)
              .height(side)
              .objectFit(ImageFit.Cover)
          }
          // 播放角标：盖在图上，一眼区分「图」和「视频」。
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
          .borderRadius(17)
        } else {"""

NEW1 = """      if (path.length > 0) {
        if (isVideo && this.isVideoName(path)) {
          if (this.hasVideoThumb(path)) {
            Image(this.videoThumbOf(path) as image.PixelMap)
              // ★ 5.0.57：直接撑满方框 + `Cover` 居中裁切（vivi：把框铺满）
              .width(side)
              .height(side)
              .objectFit(ImageFit.Cover)
          }
          // ★★ 5.1.8：▶ 角标**移走了**（到 Stack 末尾）——
          //   它原先被包在 `if (path.length > 0)` 里，而 `chatMediaGrid` 传的是
          //   `mediaThumbSrcOf(m, 0)`，**缓存小图未生成时为空串** ⇒ 整块跳过
          //   ⇒ **连播放按钮都看不到、只剩一个空白灰框**（vivi 21:4x 反馈）。
        } else {"""

# =====================================================================
# 改 2：在 Stack 末尾（图片分支之后）无条件加 ▶
# =====================================================================
OLD2 = """            .autoResize(true)
        }
      }
    }
    // ★ 固定外框 —— 宫格「每行 3 个」的基础
    .width(side)
    .height(side)"""

NEW2 = """            .autoResize(true)
        }
      }
      // ★★★ 5.1.8：视频身份标识，**无条件**画（只要这条消息是视频）。
      //   ⚠️ 判据用**形参 `isVideo`**（由 `msgIsVideo(m)` 从消息算出来），
      //     **不用 `isVideoName(path)`** —— `path` 为空时后者恒为 false
      //     ⇒ 这正是「▶ 连同『视频』两个字一起消失」的真根因。
      //   ⚠️ 放**Stack 最后一个子项** ⇒ 在最上层，不会被 Image 盖住（5.1.7 的教训）。
      //   ⚠️ 半透明黑底衬：白字在浅色封面上几乎看不见（图片都铺满方框）。
      if (isVideo) {
        Stack({ alignContent: Alignment.Center }) {
          Text('▶')
            .fontSize(22)
            .fontColor('#FFFFFF')
        }
        .width(32)
        .height(32)
        .backgroundColor('#66000000')
        .borderRadius(16)
      }
    }
    // ★ 固定外框 —— 宫格「每行 3 个」的基础
    .width(side)
    .height(side)"""

# =====================================================================
# 版本号
# =====================================================================
OLDV = '"versionCode": 5000107'
NEWV = '"versionCode": 5000108'

REPL = [
    (OLD1, NEW1, 'P1 从 path 门控里移除 ▶'),
    (OLD2, NEW2, 'P2 Stack 末尾无条件加 ▶'),
]

s = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if '5.1.8' in s:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v518pre'), 'w', encoding='utf-8', newline='\n').write(s)
io.open(os.path.join(BAK, 'app.json5.v518pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成')

for old, new, tag in REPL:
    n = s.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s = s.replace(old, new, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.7"') == 1
s_ver = s_ver.replace('"versionName": "5.1.7"', '"versionName": "5.1.8"', 1)

# ---------------- 不变量 ----------------
# ▶ 恰好一处，且在 path 门控之外
_i = s.find('  mediaThumbFixed(')
_j = s.find('\n  }', _i)
seg = s[_i:_j]
assert seg.count("Text('▶')") == 1, 'mediaThumbFixed 内 ▶ 应恰好 1 处，实际 %d' % seg.count("Text('▶')")
# ▶ 所在的 if 必须在 `if (path.length > 0)` 的**收尾之后**
i_badge = seg.find('if (isVideo) {')
i_pathgate = seg.find('if (path.length > 0) {')
assert i_badge > i_pathgate, '▶ 仍在 path 门控内'
# 关键：▶ 那一段的末尾（`if (isVideo) {` 到它收尾）不含 path.length
i_b = seg.find('if (isVideo) {')
i_b_end = seg.find('\n      }', i_b)
badge_seg = seg[i_b:i_b_end]
assert 'path.length' not in badge_seg, '▶ 分支里不该再依赖 path'
assert "'#66000000'" in badge_seg, '▶ 底衬丢了'
# 视频封面 Image 仍在门控内
assert seg.count('Image(this.videoThumbOf(path) as image.PixelMap)') == 1
# 图片分支未被破坏
assert 'objectFit(ImageFit.Cover)' in seg
assert '.autoResize(true)' in seg
# ⚠️ 判据要说清：`sourceSize` 会出现在**注释里**（5.0.59b 那段专门解释
#   「为什么不要用它」），所以不能对整段判 —— 只查**代码行**。
_code = '\n'.join(l for l in seg.split('\n')
                 if not l.strip().startswith('//')
                 and not l.strip().startswith('*')
                 and not l.strip().startswith('/*'))
assert 'sourceSize' not in _code, 'sourceSize 回到代码里了（会拉伸）'
# 5.1.7 / 5.1.6 / 5.1.5 成果仍在
assert 'if (path.length === 0) {' in seg, '5.1.7 的占位文字条件被破坏'
assert "private static readonly VIDEO_BADGE: string = 'VIDEO';" in s
assert '@State localStateTick: number = 0;' in s
assert 'private padHint(s: string, _tick: number = 0): string {' in s
assert 'if (this.showAbout) {' in s
assert 'private msgCarriesFileName(' in s
assert 'private diagSnapshot(' not in s and 'this.diagSnapshot(' not in s

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  Index.ets %d chars' % len(s))
print('OK  versionCode 5000107 -> 5000108 / 5.1.8')
