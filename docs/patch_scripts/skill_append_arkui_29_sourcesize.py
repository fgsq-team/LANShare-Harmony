#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""向 skill `harmonyos-arkui-ui-pitfalls` 追加第二十九节：
「`sourceSize` 是**解码尺寸** —— 用它求 cover 必然变形」。
幂等：哨兵串命中即跳过。
"""
import io
import sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'
SENTINEL = '## 二十九、'

SECTION = """

## 二十九、`sourceSize` 是**解码尺寸**——想「铺满 + 不变形」必须用 `autoResize(true)`

### 症状

宫格/头像类缩略图要求「**居中裁切铺满方框**」（= CSS `object-fit: cover; object-position: center`），
代码里 `objectFit(ImageFit.Cover)` 写得明明白白，真机上却是**拉伸变形**（人像被压扁/拉长）。

### 根因：`sourceSize` 在**解码阶段**就把宽高比改掉了

SDK 文档对 `sourceSize` 的定义是 **"Sets the decoding size of the image"**，
且只在「目标尺寸小于源尺寸」时生效 —— 它是**降分辨率省内存**的手段，**不是显示属性**：

```ts
Image(this.imageUri(path))
  .width(side).height(side)
  .objectFit(ImageFit.Cover)
  .sourceSize({ width: side * 2, height: side * 2 })   // ✗ 正方形 = 解码就压成方图
```

执行顺序是：**解码（按 sourceSize 出位图）→ objectFit 缩放**。
`sourceSize` 给了正方形，解码产物**已经是**正方形（原图比例在这一步就没了），
之后 `Cover` 拿到的是一张方图 —— 铺进方框正好铺满，**它无从裁切** ⇒ 表现为**拉伸**。

> 口诀：**`objectFit` 只能裁「解码之后剩下的比例」；解码阶段丢掉的，它救不回来。**

### 也**不要**改成「等比 `sourceSize`」——它依赖比例表，会退化

第一反应是「那我把 `sourceSize` 按原图比例给」。方向对，但**不稳**：

```ts
.sourceSize({ width: this.thumbW(path, side) * 2,
              height: this.thumbH(path, side) * 2 })   // ⚠️ 依赖 mediaRatio 比例表
```

`thumbW/thumbH` 依赖「比例表」（`mediaRatio`），而比例表通常是**读文件**量出来的
（`image.createImageSource(path)` → `getImageInfoSync`）。一旦这个文件**不在了**
（被清理、被"落盘后删源文件"的策略删掉、只剩余缓存缩略图），比例就量不出来，
实现里 `ratioOf()` 通常**兜底返回 1** ⇒ 又变正方形 ⇒ **又拉伸**。
即：**只要比例表缺一项就复发**，是隐蔽的定时炸弹。

### 正解：`autoResize(true)` —— 按显示区域**等比**下采样

```ts
Image(this.imageUri(path))
  .width(side).height(side)
  .objectFit(ImageFit.Cover)
  .orientation(this.thumbOri(path))
  .autoResize(true)          // ✓ 等比下采样，比例天然正确
```

官方文档原文（`autoResize`）：

> if the original image size is 800 x 1200 and the display area size is 200 x 200,
> the image will be decoded to **200 x 300** at a downsampled resolution

**等比**，而且**不需要预先知道原图比例** —— 它按「显示区域」推目标尺寸。
所以比例表缺失也不影响，这是它相对 `sourceSize` 的决定性优势。
内存收益与 `sourceSize` 同级（甚至更好，因为按实际显示区域算）。

⚠️ `autoResize` 默认值是 **false**，要显式开。

### 配套：等比框 + `Contain` 的场景也要一起改

同一份代码里往往还有「按原图比例算框 + `Contain`」的缩略图（不变形，所以看起来没问题）：

```ts
.width(this.thumbW(path, maxSide))
.height(this.thumbH(path, maxSide))
.objectFit(ImageFit.Contain)
.sourceSize({ width: this.thumbW(path, maxSide) * 2, ... })   // ⚠️ 同款隐患
```

比例表缺失时 `thumbW/thumbH` 一起退化成正方形 ⇒ 正方形 `sourceSize` ⇒ **同样变形**。
换成 `.autoResize(true)` 后：比例已知 = 等比框 + 等比解码（原样）；
比例缺失 = 正方形框 + 等比解码 ⇒ `Contain` **留白**，**不变形**（降级是"更好看"的方向）。

### 三条判据 / 排查清单

1. 看到「`Cover` 写了却像拉伸」⇒ **先查同一个组件上有没有 `sourceSize`**。
2. 看到「明明设了等比框/等比 `sourceSize`，偶尔还是变形」⇒ 查**比例表的来源**：
   是不是读文件量出来的？那个文件会不会被删？会不会兜底返回 1？
3. 想「省内存 + 不变形」⇒ 用 `autoResize(true)`，并把 `sourceSize` **整个删掉**（别两存）。

### 验证手段（本坑的取证方式，可复用）

真机截图 → 裁出目标格子 → 与原始图片分别做两种变换（`stretch` = 直接 resize 成方形、
`crop` = 先居中裁成方形再缩放）→ 按灰度归一化后算 MSE，看最佳匹配落在哪一种。
本项目实测：`sourceSize` 正方形那版，所有格子都匹配 `stretch`；换成 `autoResize` 后匹配 `crop`。

> ⚠️ 注意：截图取证只能在**肉眼已确认**的前提下做交叉验证；用户已明确说过"我眼睛确认了"
> 时不必再跑一遍，直接改。
"""

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED')
    sys.exit(0)

assert s.endswith('\n'), '文件末尾不是换行，append 会黏行'
assert '## 二十八、' in s, '第 28 节不见了 —— 可能不是同一个 skill 文件'
assert 'autoResize(true)' not in s, 'autoResize 已经写过了'

s = s + SECTION
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)

chk = io.open(P, encoding='utf-8', newline='').read()
print('OK: 已追加第 29 节')
print('  len:', len(chk), '| CRLF:', '\r' in chk)
print('  第29节:', chk.count('## 二十九、'), '| autoResize(true):', chk.count('autoResize(true)'))
