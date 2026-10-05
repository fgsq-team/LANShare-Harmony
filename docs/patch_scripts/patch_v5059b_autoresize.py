#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""5.0.59b —— 宫格缩略图拉伸的**最终**修法：`sourceSize` → `autoResize(true)`。

【为什么不是「等比 sourceSize」】上一版（5.0.59）把 `sourceSize` 从正方形改成
  等比（复用 `thumbW/thumbH`），方向对了但**不够稳**：
  `thumbW/thumbH` 依赖 `ratioOf()` → `mediaRatio` 比例表，而比例表是
  `ensureMediaRatio()` 用 `image.createImageSource(path)` 读**沙箱文件**量出来的。
  自动存相册后会**删掉沙箱副本**（5.0.53 起的统一口径）⇒ 读不到 ⇒ `ratioOf` 返回 1
  ⇒ `sourceSize` 又变正方形 ⇒ **又拉伸**。也就是说：只要比例表缺一项就复发。

【最终修法】改用 `autoResize(true)`：
  * 官方文档明确是「按显示区域**等比**下采样」——
    原图 800×1200、显示区 200×200 ⇒ 解码为 **200×300**（比例不变）；
  * **不需要预先知道原图比例** ⇒ 不受「比例表量不出来」影响；
  * 内存收益与 `sourceSize` 同级（甚至更好，按显示区域算）。

【顺带】`mediaThumb`（文件气泡里 48vp 的小缩略图）有**同款隐患**：
  它的框是等比框（`thumbW/thumbH`）+ `Contain`，一旦比例量不出来，
  框变正方形 + 正方形 `sourceSize` ⇒ 图被压进方框 ⇒ 变形。
  同样换成 `autoResize(true)`：比例表缺失时退化为「正方形框内等比留白」，**不变形**。
"""
import io
import sys

IX = r'entry/src/main/ets/pages/Index.ets'
SENTINEL = '5.0.59b：改用 `autoResize(true)`'

# ============================================================ 1. 宫格（固定方框 + Cover）
A_OLD = """            .objectFit(ImageFit.Cover)
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

A_NEW = """            .objectFit(ImageFit.Cover)
            // 5.0.41：缓存小图按 `mediaRot` 补转；沙箱原图不在表里 -> AUTO（Image 自己读 EXIF）
            .orientation(this.thumbOri(path))
            // ★ 5.0.59b：改用 `autoResize(true)`，**不要用 `sourceSize`**。
            //   ① `sourceSize` 是**解码尺寸** —— 旧写法给正方形 `{side*2, side*2}`
            //      等于在**解码阶段**就把图压成正方形，`Cover` 拿到的已是方图、
            //      无从裁切，只能原样铺满 ⇒ **拉伸变形**（vivi 真机眼睛确认）。
            //   ② 改成「等比 `sourceSize`」方向对但不稳：它依赖 `mediaRatio` 比例表，
            //      而比例表靠 `ensureMediaRatio()` 读**沙箱文件**量 —— 自动存相册会删
            //      沙箱副本 ⇒ 量不出来 ⇒ 退回 1（正方形）⇒ **又拉伸**。
            //   ③ `autoResize(true)` 是「按显示区域**等比**下采样」，官方文档原文：
            //      原图 800×1200、显示区 200×200 ⇒ 解码为 **200×300**（比例不变）。
            //      **它不需要预先知道原图比例** ⇒ 比例表缺失也照样正确 —— 决定性优势。
            .autoResize(true)"""

# ============================================================ 2. 文件气泡小缩略图（等比框 + Contain）
B_OLD = """          .objectFit(ImageFit.Contain)
          // 5.0.41：缓存小图按 `mediaRot` 补转；沙箱原图不在表里 -> AUTO（Image 自己读 EXIF）
          .orientation(this.thumbOri(path))
          .sourceSize({
            width: this.thumbW(path, maxSide) * 2,
            height: this.thumbH(path, maxSide) * 2
          })"""

B_NEW = """          .objectFit(ImageFit.Contain)
          // 5.0.41：缓存小图按 `mediaRot` 补转；沙箱原图不在表里 -> AUTO（Image 自己读 EXIF）
          .orientation(this.thumbOri(path))
          // ★ 5.0.59b：与宫格同款原因换成 `autoResize(true)`。
          //   旧写法给的是等比 `sourceSize`，看着没问题，但 `thumbW/thumbH` 依赖
          //   `mediaRatio` 比例表 —— 比例量不出来时退回 1，`sourceSize` 变正方形
          //   而框也是正方形 ⇒ 图被压进方框 ⇒ **变形**。
          //   换成 `autoResize(true)` 后：比例已知 = 等比框 + 等比解码（原样）；
          //   比例缺失 = 正方形框 + 等比解码 ⇒ `Contain` 留白，**不变形**。
          .autoResize(true)"""

# ============================================================ 3. 更新两条过时注释
C_OLD = """   * ⚠️ **`Cover` 生效的前提是 `sourceSize` 等比**（5.0.59 踩实的坑）：
   *   `sourceSize` 是**解码尺寸**，给正方形等于解码阶段就把图压正方形，
   *   `Cover` 之后无事可做 ⇒ 表现为**拉伸**。必须让解码产物保持原比例。
   * ⚠️ 框尺寸复用 `thumbW/thumbH`（它们本就是「按比例 contain 到 maxSide 方框」），
   *   不必另写一份比例计算 —— 这里只取它们的**比例**，尺寸本身不用。"""

C_NEW = """   * ⚠️ **`Cover` 生效的前提是「解码阶段不改变宽高比」**（5.0.59 踩实的坑）：
   *   用 `sourceSize` 指定解码尺寸时，只要给的不是原图比例（旧写法给正方形），
   *   图在**解码阶段**就已经变形，`Cover` 之后无事可做 ⇒ 表现为**拉伸**。
   *   所以这里用 `autoResize(true)`：按显示区域**等比**下采样，
   *   **不需要预先知道原图比例** ⇒ 不受「比例表量不出来」影响。
   * ⚠️ 框尺寸复用 `thumbW/thumbH`（「按比例 contain 到 maxSide 方框」）。"""

D_OLD = """   *   ③ `sourceSize` 按**同一个比例**给（解码尺寸不压的话 40 张原图会整张进内存，压成正方形又会把图拉变形 —— 两个坑都得躲）。"""
D_NEW = """   *   ③ 解码尺寸交给 `autoResize(true)` 按显示区域**等比**下采样（不压的话 40 张原图会整张进内存；用 `sourceSize` 压成正方形/依赖比例表都会把图弄变形 —— 三个坑都得躲）。"""


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

new_ix = apply(IX, [(A_OLD, A_NEW), (B_OLD, B_NEW), (C_OLD, C_NEW), (D_OLD, D_NEW)], 'Index')

# ---------------------------------------------------------------- 三道保险
# ① 代码里的 sourceSize **调用**彻底清零
#    ⚠️ 用 `.sourceSize({` 而不是 `.sourceSize(` —— 注释里有一句
#    「⚠️ `.sourceSize()` 把解码尺寸压到 96×96」（L5067 的历史记录），
#    裸串会被它误报（本项目踩过多次的同款子串坑）。
assert new_ix.count('.sourceSize({') == 0, \
    '仍有 sourceSize 调用残留 %d 处' % new_ix.count('.sourceSize({')
# ② 新写法齐备
#    ⚠️ 缩进串**必须带前导换行** —— 「10 空格 + .autoResize」是「12 空格 + .autoResize」
#    的子串，裸串会让 12 空格那处被算两次（本项目踩过多次的同款坑）。
for sym, want in [('\n            .autoResize(true)', 1),
                  ('\n          .autoResize(true)', 1),
                  ('5.0.59b：改用 `autoResize(true)`', 1),
                  ('5.0.59b：与宫格同款原因换成 `autoResize(true)`', 1),
                  ("原图 800×1200、显示区 200×200 ⇒ 解码为 **200×300**", 1)]:
    got = new_ix.count(sym)
    assert got == want, '符号校验失败 %r: 期望 %d 实为 %d' % (sym[:48], want, got)
    print('  OK %2d  %s' % (got, sym[:56]))
# ③ 两个 Cover / Contain 都还在（没被改坏），且布局属性未动
assert new_ix.count('\n            .objectFit(ImageFit.Cover)') == 1, '宫格 Cover 丢了'
# `Contain` 总数应为 5（预览页 3：L4400/4413/4423 + `mediaThumb` 2：视频分支与图片分支）
assert new_ix.count('.objectFit(ImageFit.Contain)') == 5, \
    'Contain 总数变了（应 5），实为 %d' % new_ix.count('.objectFit(ImageFit.Contain)')
assert new_ix.count('.width(side)\n            .height(side)') == 1, '宫格固定宽高被动过'
assert ('private static GRID_SIDE: number = 88;' in new_ix
        and 'private static GRID_COLS: number = 3;' in new_ix), '宫格常量被动过'

io.open(IX, 'w', encoding='utf-8', newline='\n').write(new_ix)
print('OK: 5.0.59b 已应用')
