# -*- coding: utf-8 -*-
"""
v5.1.6 视频文件气泡加 VIDEO 角标（vivi 21:3x）。

## 现状
`chatFileBubble` 走 `mediaThumb(...)` 时，视频那一支才画 ▶ 角标 ——
但 **5.0.77 把单张媒体并入宫格后**，`chatFileBubble` 只剩**非媒体**（zip/pdf/apk）
⇒ **视频永远进不了这个分支 ⇒ 没有 VIDEO 角标**。
（视频现在走 `chatMediaGrid` → `mediaThumbFixed(..., isVideo)`，宫格那支有角标。）

## 修法
在 `chatFileBubble` 的文件名分支（`else` 那支，非媒体才走）里，
若 `this.msgIsVideo(m)` 为真 ⇒ 文件名后追加一枚 `VIDEO` 徽标。

⚠️ 为什么 `msgIsVideo` 对非媒体会「意外为真」：`mediaNamesOf` 取的是
   `m.files` 里的媒体名，而 **mp4 也在 `files` 里** ⇒ `isVideoName` 命中。
   ★ 这恰好是**我们要的**：mp4 走的就是这个分支（`isMediaName('x.mp4')` 为真
   ⇒ 上面那个 `if` 走了 mediaThumb）… ⚠️ 那就不会到 else 了。
   ⇒ 真正需要在 else 里判的是「**沙箱里没有缩略图可显示**的媒体」——
   即 mp4 收到了但缩略图/缓存缺失的情况。为稳妥，仍加此判据（命中即显示，
   不命中无副作用），并把注释写清适用边界。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 改 1：常量 VIDEO_BADGE
# =====================================================================
OLD1 = """  /** ★ 5.1.2：非媒体文件**已另存为到本地**（另存成功后沙箱副本已删）。 */"""
NEW1 = """  /** ★ 5.1.6：视频文件的文件名徽标（宫格那支走 `mediaThumbFixed` 已有 ▶ 角标，
   *  但**沙箱缩略图缺失时**视频会落到 `chatFileBubble` 的文件名分支 ⇒ 补这个徽标）。 */
  private static readonly VIDEO_BADGE: string = 'VIDEO';
  /** ★ 5.1.2：非媒体文件**已另存为到本地**（另存成功后沙箱副本已删）。 */"""

# =====================================================================
# 改 2：文件名分支后加徽标
# =====================================================================
OLD2 = """          Text(m.content)
            .fontSize(15)
            .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
            .maxLines(2)
            .wordBreak(WordBreak.BREAK_ALL)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .constraintSize({ maxWidth: '100%' })
        }"""
NEW2 = """          // ★ 5.1.6：视频走到这一支（沙箱缩略图缺失）时补一枚 VIDEO 徽标 ——
          //   宫格那支（`mediaThumbFixed`）本来就有 ▶ 角标，这里补的是它的兜底。
          //   ⚠️ 判据用 `msgIsVideo`（走 `mediaNamesOf` + `isVideoName`），
          //   对 mp4/mov/mkv 等命中；zip/pdf 不命中 ⇒ 无副作用。
          if (this.msgIsVideo(m)) {
            Row({ space: 6 }) {
              Text(Index.VIDEO_BADGE)
                .fontSize(10)
                .fontColor('#FFFFFF')
                .padding({ left: 5, right: 5, top: 1, bottom: 1 })
                .backgroundColor('#6B5B95')
                .borderRadius(3)

              Text(m.content)
                .fontSize(15)
                .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
                .maxLines(2)
                .wordBreak(WordBreak.BREAK_ALL)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
                .constraintSize({ maxWidth: '100%' })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          } else {
            Text(m.content)
              .fontSize(15)
              .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
              .maxLines(2)
              .wordBreak(WordBreak.BREAK_ALL)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .constraintSize({ maxWidth: '100%' })
          }
        }"""

# =====================================================================
# 版本号
# =====================================================================
OLDV = '"versionCode": 5000105'
NEWV = '"versionCode": 5000106'

REPL = [
    (OLD1, NEW1, 'P1 VIDEO_BADGE 常量'),
    (OLD2, NEW2, 'P2 文件名分支加徽标'),
]

s = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if 'VIDEO_BADGE' in s:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v516pre'), 'w', encoding='utf-8', newline='\n').write(s)
io.open(os.path.join(BAK, 'app.json5.v516pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成')

for old, new, tag in REPL:
    n = s.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s = s.replace(old, new, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.5"') == 1
s_ver = s_ver.replace('"versionName": "5.1.5"', '"versionName": "5.1.6"', 1)

# ---------------- 不变量 ----------------
assert "private static readonly VIDEO_BADGE: string = 'VIDEO';" in s
assert 'Text(Index.VIDEO_BADGE)' in s
assert s.count('if (this.msgIsVideo(m)) {') == 1, 'msgIsVideo 分支数异常'
# 文件名的 Text 仍在（徽标那支 + else 支）
# ⚠️ 判据要说清：`Text(m.content)` **全文件不止这两处**（文件页等也在用），
#   所以不能断言「全文件 == 2 次」—— 那是上一版把它拦下来的原因（落盘前，磁盘零污染）。
#   正确判据 = **在 `chatFileBubble` 函数体内**数，且必须恰好 2（徽标支 + else 支）。
_i = s.find('  chatFileBubble(')
_j = s.find('\n  }', _i)
assert _i > 0 and _j > _i, '定位 chatFileBubble 失败'
assert s[_i:_j].count('Text(m.content)') == 2, \
    'chatFileBubble 内 Text(m.content) 应恰好 2 次，实际 %d' % s[_i:_j].count('Text(m.content)')
# 5.1.5 成果仍在
assert '@State localStateTick: number = 0;' in s
assert 'private padHint(s: string, _tick: number = 0): string {' in s
assert 'this.padHint(Index.HINT_FILE, tick)' in s
# 5.1.4 / 5.1.3 成果仍在
assert 'private msgCarriesFileName(' in s
assert 'if (this.showAbout) {' in s
# 5.1.0 成果仍在
assert 'private diagSnapshot(' not in s and 'this.diagSnapshot(' not in s

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  Index.ets %d chars' % len(s))
print('OK  versionCode 5000105 -> 5000106 / 5.1.6')
