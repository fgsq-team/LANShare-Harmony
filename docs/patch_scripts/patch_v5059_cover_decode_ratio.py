#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""5.0.59 —— 宫格缩略图「拉伸变形」根治。

【问题】vivi 真机眼睛确认：宫格里的图片被**拉伸**填满方框（人像变形）。
        而代码写的明明是 `.objectFit(ImageFit.Cover)`（= CSS `object-fit: cover`）。

【根因】`sourceSize` 的语义是**解码尺寸**（SDK 文档原文 "Image decode width/height"），
        不是「显示尺寸」。宫格给的是 `{width: side*2, height: side*2}` —— 一个**正方形**：
          → 解码器按正方形输出位图 ⇒ **比例在解码阶段就被压掉了**
          → `Image` 组件拿到的是「已经变形的方图」
          → 此时 `objectFit(Cover)` 无事可做（方图铺方框正好铺满）⇒ 表现为**拉伸**
        所以 `Cover` 写了也没用 —— 它在错误的阶段之后才生效。

【修法】把 `sourceSize` 改成**等比**（复用 `thumbW/thumbH` —— 它们本就是
        「按原图比例 contain 到 side 方框」的尺寸），让解码产物保持原图比例；
        再由 `Cover` 在**显示阶段**做「等比放大到覆盖 + 居中裁切」。
        这样才等价于 `object-fit: cover; object-position: center`。

⚠️ 只改 `mediaThumbFixed`（宫格专用）。`mediaThumb` 本来就是「等比框 + Contain +
   等比 sourceSize」，三者自洽，不动它。
"""
import io
import sys

IX = r'entry/src/main/ets/pages/Index.ets'
AJ = r'AppScope/app.json5'
SENTINEL = '5.0.59：`sourceSize` 必须**等比**'

# ---------------------------------------------------------------- A. 核心修复
A_OLD = """            .objectFit(ImageFit.Cover)
            // 5.0.41：缓存小图按 `mediaRot` 补转；沙箱原图不在表里 -> AUTO（Image 自己读 EXIF）
            .orientation(this.thumbOri(path))
            .sourceSize({ width: side * 2, height: side * 2 })"""

A_NEW = """            .objectFit(ImageFit.Cover)
            // 5.0.41：缓存小图按 `mediaRot` 补转；沙箱原图不在表里 -> AUTO（Image 自己读 EXIF）
            .orientation(this.thumbOri(path))
            // ★ 5.0.59：`sourceSize` 必须**等比** —— 它是**解码尺寸**（不是显示尺寸）。
            //   给正方形（旧写法 `{side*2, side*2}`）= 在**解码阶段**就把图压成正方形，
            //   于是 `Cover` 拿到的是「已经变形的方图」，只能原样铺满 ⇒ **拉伸变形**
            //   （vivi 真机眼睛确认）。复用 `thumbW/thumbH`（本就是「按原图比例
            //   contain 到 side 方框」），解码产物保持原比例，`Cover` 才能真正裁切。
            .sourceSize({
              width: this.thumbW(path, side) * 2,
              height: this.thumbH(path, side) * 2
            })"""

# ------------------------------------------------- B. 更新过时的 @Builder 文档注释
B_OLD = """   * 与 `mediaThumb` 的唯一区别：外框恒为 `side × side` **正方形**，
   * 图片按原图比例 `Contain` 填进框内（横图上下留白、竖图左右留白）。"""
B_NEW = """   * 与 `mediaThumb` 的唯一区别：外框恒为 `side × side` **正方形**，
   * 图片 `Cover`（等比放大到覆盖 + **居中裁切**）填满框内，等价于
   * CSS `object-fit: cover; object-position: center`（vivi 2026-10-02 明确要求）。"""

C_OLD = """   * ⚠️ 为什么用 `Contain` 而不是 `Cover`：`Cover` 会把图片**裁切**成正方形，
   *   与 vivi「照片的宽高比例还保持原图比例」的要求相悖。
   * ⚠️ 框尺寸复用 `thumbW/thumbH`（它们本就是「按比例 contain 到 maxSide 方框」），
   *   不必另写一份比例计算。"""
C_NEW = """   * ⚠️ **`Cover` 生效的前提是 `sourceSize` 等比**（5.0.59 踩实的坑）：
   *   `sourceSize` 是**解码尺寸**，给正方形等于解码阶段就把图压正方形，
   *   `Cover` 之后无事可做 ⇒ 表现为**拉伸**。必须让解码产物保持原比例。
   * ⚠️ 框尺寸复用 `thumbW/thumbH`（它们本就是「按比例 contain 到 maxSide 方框」），
   *   不必另写一份比例计算 —— 这里只取它们的**比例**，尺寸本身不用。"""

D_OLD = "  /** ★ 5.0.56：缩略图宫格 —— 外框边长（vp）。固定正方形，图片在框内按比例 Contain */"
D_NEW = "  /** ★ 5.0.56：缩略图宫格 —— 外框边长（vp）。固定正方形，图片 `Cover` 居中裁切铺满 */"

E_OLD = """   * ★ 5.0.56：格子的**外框固定为 `GRID_SIDE` 正方形**（图片在框内 `Contain` 按比例留白），"""
E_NEW = """   * ★ 5.0.56：格子的**外框固定为 `GRID_SIDE` 正方形**（图片 `Cover` 铺满 + 居中裁切），"""

# ---------------------------------------------------------------- F. 版本号
AJ_OLD = '''    "versionCode": 5000058,
    "versionName": "5.0.58"'''
AJ_NEW = '''    "versionCode": 5000059,
    "versionName": "5.0.59"'''


def apply(path, pairs, label):
    s = io.open(path, encoding='utf-8', newline='').read()
    for i, (old, new) in enumerate(pairs):
        assert s.count(old) == 1, '%s 锚点#%d 命中 %d 次' % (label, i + 1, s.count(old))
        assert s.count(new) == 0, '%s 新文本#%d 此前已存在' % (label, i + 1)
    for old, new in pairs:
        s = s.replace(old, new)
    return s


src = io.open(IX, encoding='utf-8', newline='').read()
if SENTINEL in src:
    print('ALREADY APPLIED')
    sys.exit(0)

new_ix = apply(IX, [(A_OLD, A_NEW), (B_OLD, B_NEW), (C_OLD, C_NEW),
                    (D_OLD, D_NEW), (E_OLD, E_NEW)], 'Index')
new_aj = apply(AJ, [(AJ_OLD, AJ_NEW)], 'app.json5')

# ---------------------------------------------------------------- 三道保险
# ① 旧写法彻底清零
assert '.sourceSize({ width: side * 2, height: side * 2 })' not in new_ix, \
    '旧的「正方形解码」写法仍在'
assert '图片按原图比例 `Contain` 填进框内' not in new_ix, '旧的 Contain 描述仍在'
# ② 新写法齐备
for sym, want in [('.sourceSize({\n              width: this.thumbW(path, side) * 2,\n'
                   '              height: this.thumbH(path, side) * 2\n            })', 1),
                  ('5.0.59：`sourceSize` 必须**等比**', 1),
                  ('object-fit: cover; object-position: center', 1),
                  ('图片 `Cover` 居中裁切铺满', 1)]:
    got = new_ix.count(sym)
    assert got == want, '符号校验失败 %r: 期望 %d 实为 %d' % (sym[:50], want, got)
    print('  OK %2d  %s' % (got, sym[:56]))
# ③ 宫格里 Cover 仍是 Cover（没被顺手改成 Contain），且 mediaThumb 未被波及
# ⚠️ 必须带**前导换行**：视频分支是 14 空格缩进，裸的「12 空格 + .objectFit」
#    是它的子串（后 12 个空格），会算成 2 处 —— 这个坑本项目踩过多次。
assert new_ix.count('\n            .objectFit(ImageFit.Cover)') == 1, '宫格图片分支的 Cover 数量不对'
assert new_ix.count('\n              .objectFit(ImageFit.Cover)') == 1, '视频分支的 Cover 丢了'
assert new_ix.count(""".sourceSize({
            width: this.thumbW(path, maxSide) * 2,
            height: this.thumbH(path, maxSide) * 2
          })""") == 1, 'mediaThumb 的等比 sourceSize 被动过'
assert '5000059' in new_aj and '"5.0.59"' in new_aj

# ---------------------------------------------------------------- 落盘
io.open(IX, 'w', encoding='utf-8', newline='\n').write(new_ix)
io.open(AJ, 'w', encoding='utf-8', newline='\n').write(new_aj)
print('OK: 5.0.59 已应用')
