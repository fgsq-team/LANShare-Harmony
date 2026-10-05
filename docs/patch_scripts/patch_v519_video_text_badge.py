# -*- coding: utf-8 -*-
"""
v5.1.9 视频标识改纯文字（vivi 21:51）。

## 需求
「现在看不到视频文字，只能看到播放按钮。但播放按钮不太好看，改成文字显示吧」

## 现状（5.1.8 之后）
`mediaThumbFixed` 末尾有：
```typescript
if (isVideo) {
  Stack({ alignContent: Alignment.Center }) {
    Text('▶')  ...
  }.width(32).height(32).backgroundColor('#66000000').borderRadius(16)
}
```
⇒ 只有 `▶` 图标；而「视频」两个字在 5.1.7 之后**只在 `path.length === 0` 时**显示
（有图就被 Image 盖住 / 被 5.1.7 的条件排除）⇒ 用户说「看不到视频文字」。

## 修法
把 `▶` 图标**换成「视频」文字角标**（保留底衬、显式居中），
与 5.1.6 给 `chatFileBubble` 加的 `VIDEO` 徽标**同一套视觉**（紫底白字 + 圆角）——
★ 顺带统一：之前 5.1.6 用英文 `VIDEO`，这里用中文「视频」，
  **统一改成中文**（用户在中文界面，反馈也是中文用词「视频文字」）。

⚠️ **判据仍是形参 `isVideo`**（事实），**不受 `path` 门控** —— 5.1.8 的结论不变：
  「标识」与「图是否就绪」是**两件独立的事**。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 改 1：▶ 图标 → 「视频」文字角标（mediaThumbFixed 宫格那支）
# =====================================================================
OLD1 = """      if (isVideo) {
        Stack({ alignContent: Alignment.Center }) {
          Text('▶')
            .fontSize(22)
            .fontColor('#FFFFFF')
        }
        .width(32)
        .height(32)
        .backgroundColor('#66000000')
        .borderRadius(16)
      }"""
NEW1 = """      if (isVideo) {
        // ★ 5.1.9：文字角标（vivi「播放按钮不太好看，改成文字显示」）。
        //   ⚠️ **挪到左下角**：用一层 `Stack({alignContent})` 定位 ——
        //     `Text` **没有 `.align()` 方法**（那是 `Stack` 的参数），
        //     直接写在 `Stack` 里会沿用默认居中、正好盖住封面主体。
        //     另：「已删」角标也在同一个 `Stack` 里（且同样默认居中），
        //     两者同时出现时叠在一起 ⇒ 视频角标选左下、避开中心。
        Stack({ alignContent: Alignment.BottomStart }) {
          Text('视频')
            .fontSize(11)
            .fontColor('#FFFFFF')
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .backgroundColor('#66000000')
            .borderRadius(4)
        }
        .width('100%')
        .height('100%')
      }"""

# =====================================================================
# 改 2：chatFileBubble 的英文 VIDEO 徽标 → 中文「视频」（统一视觉与用词）
# =====================================================================
OLD2 = """  private static readonly VIDEO_BADGE: string = 'VIDEO';"""
NEW2 = """  private static readonly VIDEO_BADGE: string = '视频';"""

OLD3 = """              Text(Index.VIDEO_BADGE)
                .fontSize(10)
                .fontColor('#FFFFFF')
                .padding({ left: 5, right: 5, top: 1, bottom: 1 })
                .backgroundColor('#6B5B95')
                .borderRadius(3)"""
NEW3 = """              Text(Index.VIDEO_BADGE)
                .fontSize(11)
                .fontColor('#FFFFFF')
                .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                .backgroundColor('#66000000')
                .borderRadius(4)"""

# =====================================================================
# 版本号
# =====================================================================
OLDV = '"versionCode": 5000108'
NEWV = '"versionCode": 5000109'

REPL = [
    (OLD1, NEW1, 'P1 ▶ 图标改「视频」文字'),
    (OLD2, NEW2, 'P2 VIDEO_BADGE 改中文'),
    (OLD3, NEW3, 'P3 徽标样式与 P1 统一'),
]

s = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if '5.1.9' in s:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v519pre'), 'w', encoding='utf-8', newline='\n').write(s)
io.open(os.path.join(BAK, 'app.json5.v519pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成')

for old, new, tag in REPL:
    n = s.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s = s.replace(old, new, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.8"') == 1
s_ver = s_ver.replace('"versionName": "5.1.8"', '"versionName": "5.1.9"', 1)

# ---------------- 不变量 ----------------
# ▶ 已彻底移除
# 两处都是「视频」文字，且样式一致（fontSize 11 / #66000000 / borderRadius 4）
assert s.count('Text(' + chr(39) + '视频' + chr(39) + ')') == 1, 'mediaThumbFixed 的角标应恰好 1 处「视频」文字（占位那处是三元表达式，不算）'
assert "private static readonly VIDEO_BADGE: string = '视频';" in s
# 先定位 mediaThumbFixed 段（▶ 的判据要用它）
_i = s.find('  mediaThumbFixed(')
_j = s.find('\n  }', _i)
# ⚠️ ▶ 在**画廊预览**(5319) 与**注释**里仍存在 —— 那是 5.1.9 **刻意不动**的
#   （画廊的播放标识是另一回事）。所以只查 mediaThumbFixed 这一段。
seg = s[_i:_j]
# ⚠️ 5.1.7/5.1.8 写的**注释里**提到过 ▶（那是历史说明）——
#   所以判据只查**代码行**，别对整段判。
_seg_code = '\n'.join(l for l in seg.split('\n')
                    if not l.strip().startswith('//')
                    and not l.strip().startswith('*')
                    and not l.strip().startswith('/*'))
assert chr(9654) not in _seg_code, 'mediaThumbFixed 的代码里仍有 ▶'
assert 'Text(' + chr(39) + '视频' + chr(39) + ')' in seg
# 判据仍是事实、不受 path 门控
assert 'if (isVideo) {' in seg
i_b = seg.find('if (isVideo) {')
badge_seg = seg[i_b:seg.find('\n      }', i_b)]
assert 'path.length' not in badge_seg, '「视频」角标不该再依赖 path'
assert 'alignContent: Alignment.BottomStart' in badge_seg, '角标未定位到左下角'
assert "'.align(Alignment" not in badge_seg, 'Text 不支持 .align()，必须用 Stack 包裹'
# 图片分支未被破坏
_code = '\n'.join(l for l in seg.split('\n')
                  if not l.strip().startswith('//') and not l.strip().startswith('*'))
assert 'objectFit(ImageFit.Cover)' in _code
assert '.autoResize(true)' in _code
assert 'sourceSize' not in _code
# 前几版成果仍在
assert '@State localStateTick: number = 0;' in s
assert 'private padHint(s: string, _tick: number = 0): string {' in s
assert 'private msgCarriesFileName(' in s
assert 'if (this.showAbout) {' in s
assert 'private diagSnapshot(' not in s and 'this.diagSnapshot(' not in s

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  Index.ets %d chars' % len(s))
print('OK  versionCode 5000108 -> 5000109 / 5.1.9')
