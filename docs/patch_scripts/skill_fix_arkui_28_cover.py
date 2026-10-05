#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修正 skill `harmonyos-arkui-ui-pitfalls` 第 28 节里**已过时**的缩略图填充示例。

背景：第 28 节写于 5.0.56，当时用 `Contain`（保比例留白）并注明
「⚠️ 用 Cover 会把图裁成正方形」。5.0.57 vivi 拍板改成 `Cover` 铺满；
5.0.59 又查明 **`Cover` 必须配 `autoResize(true)`，绝不能有 `sourceSize`**
（否则解码阶段就变形 ⇒ 拉伸）。第 28 节不同步的话，下次照抄就会重踩。

幂等：哨兵串命中即跳过。
"""
import io
import sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'
SENTINEL = '★ 本节的 `Cover` 必须配 `autoResize(true)`'

A_OLD = """// ① 外框恒为正方形，图片在框内 Contain（保比例、留白，不裁切）
@Builder
mediaThumbFixed(path: string, side: number) {
  Stack() {
    Text('图片') /* 占位，真图盖住 */
    if (path.length > 0) {
      Image(this.imageUri(path))
        .width(this.thumbW(path, side))   // ← 框内按比例
        .height(this.thumbH(path, side))
        .objectFit(ImageFit.Contain)      // ⚠️ 用 Cover 会把图裁成正方形
    }
  }
  .width(side).height(side)               // ★ 外框固定 —— 每格占地一致
  .backgroundColor('#EFF2F6').borderRadius(8).clip(true)
}"""

A_NEW = """// ① 外框恒为正方形，图片在其中「等比铺满 + 居中裁切」（= 微信九宫格的观感）
@Builder
mediaThumbFixed(path: string, side: number) {
  Stack() {
    Text('图片') /* 占位，真图盖住 */
    if (path.length > 0) {
      Image(this.imageUri(path))
        .width(side)                      // ★ 铺满外框
        .height(side)
        .objectFit(ImageFit.Cover)        // 居中裁切：object-fit: cover; object-position: center
        .autoResize(true)                 // ★★ 必须（见第二十九节）！
        // ⛔ 这里**绝不能**再写 .sourceSize({...}) —— 那是**解码尺寸**，
        //    给正方形等于解码阶段就把图压变形，Cover 拿到的已是方图 ⇒ **拉伸**
    }
  }
  .width(side).height(side)               // ★ 外框固定 —— 每格占地一致
  .backgroundColor('#EFF2F6').borderRadius(8).clip(true)
}"""

B_OLD = "- **比例靠 `Contain` 保**，不靠\"框尺寸随比例变\"。框是框、图是图，两者解耦。"
B_NEW = """- **比例靠 `objectFit` + `autoResize` 保**，不靠"框尺寸随比例变"。框是框、图是图，两者解耦。
  ★ 本节的 `Cover` 必须配 `autoResize(true)`，且**不能有 `sourceSize`** —— 详见第二十九节
  （`sourceSize` 是解码尺寸，给正方形会让 `Cover` 彻底失效、表现为**拉伸**）。"""

C_OLD = """- **外框固定**是「每行个数固定」的前提 —— 只要每格占地一样，排布才可预测。"""
C_NEW = """- **外框固定**是「每行个数固定」的前提 —— 只要每格占地一样，排布才可预测。
  框内怎么填是**另一个自由度**：`Contain` = 留白不变形；`Cover` = 铺满 + 居中裁切（本项目 5.0.57 选的）。
  两者都**不能**靠 `sourceSize` 去控解码 —— 见第二十九节。"""

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED')
    sys.exit(0)

pairs = [(A_OLD, A_NEW), (B_OLD, B_NEW), (C_OLD, C_NEW)]
for i, (old, new) in enumerate(pairs):
    assert s.count(old) == 1, '锚点#%d 命中 %d 次' % (i + 1, s.count(old))
    assert s.count(new) == 0, '新文本#%d 此前已存在' % (i + 1)
for old, new in pairs:
    s = s.replace(old, new)

assert '.autoResize(true)                 // ★★ 必须' in s
assert '用 Cover 会把图裁成正方形' not in s, '过时的 Cover 警告还在'
assert s.count('## 二十九、') == 1, '第 29 节不在（应先跑 skill_append_arkui_29_sourcesize.py）'

io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
chk = io.open(P, encoding='utf-8', newline='').read()
print('OK: 第 28 节已同步（Contain → Cover + autoResize）')
print('  len:', len(chk), '| CRLF:', '\r' in chk)
print('  第29节:', chk.count('## 二十九、'), '| autoResize:', chk.count('autoResize(true)'))
