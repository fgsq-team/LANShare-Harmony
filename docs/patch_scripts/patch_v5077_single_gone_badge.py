# -*- coding: utf-8 -*-
"""v5.0.77 —— 单张图片/视频的缩略图上也打「已删」标记。

vivi 2026-10-02 20:36：「单张的图片或者视频上缩略图上没有打已删除标记，
**多张打了标记**」。

【根因】**「已删」角标只写在宫格那一条路上**。
- 宫格 `chatMediaGrid` 的结构是 `Stack { mediaThumbFixed(...); if (gone) Text('已删') }`
  ⇒ 角标**有** `Stack` 才能叠在缩略图上；
- 单张 `chatFileBubble` 里是 `Column { Text('收到文件'); mediaThumb(...); Text(提示) }`
  ⇒ **压根没有那个 `Stack`**，也没有角标 ⇒ 无论删没删都不显示。
⚠️ 不是判据问题（`mediaGoneFromAlbum` 两边共用同一个），是**单张那条路没写角标**。

【修法】给单张的缩略图包一层 `Stack`，角标**照抄宫格的样式**（含
`fontSize(10)` / `#FFFFFF` / `padding` / `#99000000` / `borderRadius(4)`），
判据同样用 `mediaGoneFromAlbum(m, 0)`。
⚠️ 关键：`mediaThumb(...)` 自己**就是一个 `Stack`**（内含占位 Text + Image）。
   但我们需要的层级是「缩略图**之上**再叠一个角标」，所以要在**外面**再包一层
   `Stack` —— 直接把角标塞进 `mediaThumb` 内部会与它的占位 Text / ▶ 角标
   混在一起，且那个方法还被**文件页**共用（传 48 + fixedSquare=false），
   改它会波及文件页。⇒ **在 `chatFileBubble` 里包，不动 `mediaThumb`。**

【顺带】单张也用 `mediaThumbSrcOf` 的判据一致性检查：
   角标与底部提示都读 `mediaGoneFromAlbum(m, 0)` ⇒ 两者**必然同时出现/消失**，
   不会出现「角标说已删、底下提示说长按存入」的矛盾。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.77' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5077pre'), (VER, 'app.json5.v5077pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改：单张气泡的缩略图外面包一层 Stack + 角标
# =====================================================================
OLD1 = """        if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
          // ★ 5.0.72：48 -> `GRID_SIDE`(88) + 固定方框；5.0.73：改 `Cover` 铺满
          this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)
        } else {"""
NEW1 = """        if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
          // ★★ 5.0.77（vivi 20:36）：单张也打「已删」标记。
          // ⚠️ 根因：「已删」角标**只写在宫格**（`chatMediaGrid` 的
          //   `Stack { 缩略图; if (gone) Text('已删') }`），单张这条路上
          //   **压根没有那个 `Stack`、也没有角标** ⇒ 不是判据问题，是**没写**。
          // ⚠️ 为什么在**外面**再包一层 Stack：`mediaThumb(...)` 自己就是一个
          //   `Stack`（内含占位 Text + Image），我们需要的层级是「缩略图**之上**
          //   再叠角标」；而把角标塞进 `mediaThumb` 内部会与它的占位 Text / ▶
          //   混在一起，且那个方法被**文件页**共用（传 48 + fixedSquare=false），
          //   改它会**波及文件页**。⇒ 在 `chatFileBubble` 里包，不动 `mediaThumb`。
          Stack() {
            // ★ 5.0.72：48 -> `GRID_SIDE`(88) + 固定方框；5.0.73：改 `Cover` 铺满
            this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)
            // 角标样式**照抄宫格**（`chatMediaGrid`），两边必须一致
            if (this.mediaGoneFromAlbum(m, 0)) {
              Text('已删')
                .fontSize(10)
                .fontColor('#FFFFFF')
                .padding({ left: 4, right: 4, top: 1, bottom: 1 })
                .backgroundColor('#99000000')
                .borderRadius(4)
            }
          }
        } else {"""

OLD2 = '"versionCode": 5000076'
NEW2 = '"versionCode": 5000077'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 单张包 Stack + 角标'),):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD2) == 1
v2 = v2.replace(OLD2, NEW2, 1)
assert v2.count('"versionName": "5.0.76"') == 1
v2 = v2.replace('"versionName": "5.0.76"', '"versionName": "5.0.77"', 1)

# ---- 不变量 ----
# 「已删」角标现在应有两处（宫格 + 单张）
assert s2.count("Text('已删')") == 2, s2.count("Text('已删')")
# 两处都用同一个判据
assert s2.count('if (this.mediaGoneFromAlbum(m, 0)) {') == 2
# 单张的 Stack 必须在 chatFileBubble 内
_b = s2.split('  chatFileBubble(')[1].split('\n  }\n')[0]
assert _b.count('Stack() {') == 1, '单张应有且仅有一个 Stack'
assert "Text('已删')" in _b, '单张缺角标'
# 前几轮修复仍在
assert 'this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)' in s2
assert 'this.mediaFitOf(fixedSquare)' in s2
assert 'this.probeAlbumOnEnterChat();' in s2
assert 'private padHint(s: string): string {' in s2
assert '${this.groupMediaSig(g)}|${this.groupGoneSig(g)}' in s2
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')
# 5.0.76 的三分支文案常量仍在
for c in ('HINT_IN_ALBUM', 'HINT_NOT_YET', 'HINT_GONE'):
    assert 'Index.%s' % c in s2

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000077' % (len(s_idx), len(s2)))
