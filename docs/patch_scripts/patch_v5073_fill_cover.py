# -*- coding: utf-8 -*-
"""v5.0.73 —— 修 5.0.72 引入的「单张图片/视频没铺满图框」。

【问题】vivi 2026-10-02 20:04：「单张图片和视频的缩放有点问题，没有铺满图框。
多张图片正常」。

【根因】5.0.72 我给 `mediaThumb` 加了 `fixedSquare`（容器恒 88×88 正方形），
但**图片本身仍用 `ImageFit.Contain`** —— 等比**完整**显示、**留白**。
而宫格 `mediaThumbFixed` 用的是 `ImageFit.Cover` —— 等比**铺满**并居中裁切。
⇒ 容器变成正方形后，Contain 的留白反而更明显（正方形里放竖图/横图都留边）。

多张图片正常，正是因为它们走的是宫格那条 `mediaThumbFixed`（Cover）。

【修法】`fixedSquare` 为 true 时改用 `Cover`。
⚠️ **不会变形**（这是 5.0.59 早就验证过的结论）：
   `Cover` = 等比铺满 + 居中裁切；配合 `autoResize(true)`（按显示区域**等比**
   下采样，官方定义）⇒ 像素本身不变形，只是被**裁掉**了超出方框的部分。
   5.0.59 之所以放弃 `sourceSize`，正是因为它是**解码尺寸**、给正方形会把图
   **压扁**；而 `autoResize(true)` 不需要预先知道原图比例，所以安全。
⚠️ `fixedSquare = false`（文件页仍传 48）**保持 `Contain` 不变** ——
   那里是「不裁切、完整显示小图」的设计，动它会裁掉文件页缩略图的内容。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.73' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5073pre'), (VER, 'app.json5.v5073pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# 改 1：加一个「图片填充模式」helper
OLD1 = """  /** 5.0.72：固定方框时恒返回 `maxSide`，否则按比例算（供 @Builder 内表达式调用） */
  private boxSide(path: string, maxSide: number, fixedSquare: boolean): number {"""
NEW1 = """  /**
   * ★ 5.0.73：这张图该用哪种填充（供 @Builder 内表达式调用，不能在 Builder 里写 const）。
   *
   * 【为什么】5.0.72 给 `mediaThumb` 加了 `fixedSquare`（容器恒 88×88 正方形），
   * 但图片本身仍是 `ImageFit.Contain` —— 等比**完整**显示、**留白**。
   * 容器变成正方形后留白反而更明显（vivi 20:04 反馈「没有铺满图框」）。
   * 宫格 `mediaThumbFixed` 用的是 `ImageFit.Cover`（等比**铺满** + 居中裁切），
   * 所以「多张图片正常」。
   *
   * ⇒ `fixedSquare` 时用 `Cover`（铺满），否则保持 `Contain`（文件页仍传 48，
   *   那里是「不裁切、完整显示小图」的设计，裁掉内容反而是回归）。
   *
   * ⚠️ **`Cover` 不会变形**（5.0.59 验证过）：等比铺满 + 居中裁切，配合
   *   `autoResize(true)`（按显示区域**等比**下采样）⇒ 像素不变形，只是**裁掉**超出部分。
   */
  private mediaFitOf(fixedSquare: boolean): ImageFit {
    return fixedSquare ? ImageFit.Cover : ImageFit.Contain;
  }

  /** 5.0.72：固定方框时恒返回 `maxSide`，否则按比例算（供 @Builder 内表达式调用） */
  private boxSide(path: string, maxSide: number, fixedSquare: boolean): number {"""

# 改 2：视频那一支
OLD2 = """            .width(this.boxSide(path, maxSide, fixedSquare))
            .height(this.boxSideH(path, maxSide, fixedSquare))
            .objectFit(ImageFit.Contain)
        }
        // 播放角标：盖在图上，一眼区分「图」和「视频」"""
NEW2 = """            .width(this.boxSide(path, maxSide, fixedSquare))
            .height(this.boxSideH(path, maxSide, fixedSquare))
            // ★ 5.0.73：固定方框时铺满（vivi 反馈「视频图框也没铺满」）
            .objectFit(this.mediaFitOf(fixedSquare))
            .autoResize(true)
        }
        // 播放角标：盖在图上，一眼区分「图」和「视频」"""

# 改 3：图片那一支
OLD3 = """        Image(this.imageUri(path))
          .width(this.boxSide(path, maxSide, fixedSquare))
          .height(this.boxSideH(path, maxSide, fixedSquare))
          .objectFit(ImageFit.Contain)"""
NEW3 = """        Image(this.imageUri(path))
          .width(this.boxSide(path, maxSide, fixedSquare))
          .height(this.boxSideH(path, maxSide, fixedSquare))
          // ★ 5.0.73：固定方框时铺满（同上），否则仍 Contain（文件页不改）
          .objectFit(this.mediaFitOf(fixedSquare))"""

OLD4 = '"versionCode": 5000072'
NEW4 = '"versionCode": 5000073'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 填充模式 helper'),
                      (OLD2, NEW2, '改2 视频铺满'),
                      (OLD3, NEW3, '改3 图片铺满')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD4) == 1
v2 = v2.replace(OLD4, NEW4, 1)
assert v2.count('"versionName": "5.0.72"') == 1
v2 = v2.replace('"versionName": "5.0.72"', '"versionName": "5.0.73"', 1)

# ---- 不变量 ----
assert s2.count('private mediaFitOf(fixedSquare: boolean): ImageFit {') == 1
assert s2.count('this.mediaFitOf(fixedSquare)') == 2, s2.count('this.mediaFitOf(fixedSquare)')
# mediaThumb 里不该再有裸 Contain
_mt = s2.split('  mediaThumb(path: string')[1].split('\n  }\n')[0]
assert 'ImageFit.Contain' not in _mt, 'mediaThumb 里仍有裸 Contain'
# 宫格那条必须仍是 Cover（多张图片正常，别动）
assert s2.count('.objectFit(ImageFit.Cover)') >= 2, s2.count('.objectFit(ImageFit.Cover)')
# autoResize 保留（不变形）
assert s2.count('.autoResize(true)') >= 2
# 文件页仍传 48 且未开 fixedSquare（默认 false => Contain）
assert 'this.mediaThumb(f.path, 48, this.isVideoName(f.path))' in s2
# 前几轮修复仍在
assert 'this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)' in s2
assert '${this.groupMediaSig(g)}|${this.groupGoneSig(g)}' in s2
assert "albumPartOf(g.msgs[i].id, 0, 0).length > 0 ? '1' : '0'" in s2
assert "return notYet + ' '.repeat(gap);" in s2
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')
# helper 仍在 @Builder 之前（5.0.72 踩过的坑）
assert s2.index('private mediaFitOf(') < s2.index('  @Builder\n  mediaThumb(')

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000073' % (len(s_idx), len(s2)))
