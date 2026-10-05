#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""追加 5.0.59 工作日志（幂等：哨兵串命中即跳过）。"""
import io
import os
import sys

P = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
SENTINEL = '### 16:57 5.0.59 —— 宫格缩略图「拉伸」根治'

ENTRY = """

### 16:57 5.0.59 —— 宫格缩略图「拉伸」根治

**现象**：vivi 眼睛确认宫格缩略图被**拉伸变形**（人像压扁）；代码里 `objectFit(ImageFit.Cover)` 明明写了。

**根因**：`sourceSize` 是**解码尺寸**（SDK 文档 "Sets the decoding size of the image"），
宫格给的是 `{width: side*2, height: side*2}` —— **正方形**：
→ 解码阶段就把图压成正方形 → `Cover` 拿到的是方图、**无从裁切** → 原样铺满 = 拉伸。
`objectFit` 只能裁「解码后剩下的比例」，解码阶段丢掉的救不回来。

**中途否掉的一版**：5.0.59 先改成「等比 `sourceSize`」（复用 `thumbW/thumbH`）。
方向对但**不稳** —— `thumbW/thumbH` 依赖 `mediaRatio` 比例表，而比例表由
`ensureMediaRatio()` 读**沙箱文件**量出；自动存相册会删沙箱副本 ⇒ 量不出来 ⇒ `ratioOf()` 兜底 1
⇒ `sourceSize` 又变正方形 ⇒ **又拉伸**。只要比例表缺一项就复发。

**定案**：改用 **`autoResize(true)`**（官方文档：原图 800×1200、显示区 200×200 ⇒ 解码 **200×300**，**等比**）。
它按显示区域推目标尺寸，**不需要预先知道原图比例** ⇒ 比例表缺失也正确 —— 决定性优势。
配套把 `mediaThumb`（文件气泡 48vp，等比框 + `Contain`）的 `sourceSize` 一并换掉：
它同款隐患（比例缺失 ⇒ 正方形框 + 正方形解码 ⇒ 变形），换后降级方向是「留白」而非「拉伸」。

**改动**：`Index.ets` 两处 `.sourceSize({...})` → `.autoResize(true)`（宫格 + 小缩略图），
文件里 `sourceSize` **调用**清零；版本 5.0.58→5.0.59（5000058→5000059）。

**取证**：`snapshot_display` 截图 + 拉手机沙箱 12 张原图（5184×3456 = 3:2）→
裁剪宫格逐格与「stretch / crop」两种变换比对（脚本人已写好，vivi 表示眼睛已确认、无需再跑）。

**踩到的子串坑（连续两次）**：断言里 `${12空格}.objectFit(...)` 会被 14 空格那行子串命中；
`${10空格}.autoResize(true)` 会被 12 空格那行命中 ⇒ 缩进串**必须带前导 `\\n`**。
另：括号 delta 不能作判据（新增**注释里的 ASCII 括号**会算进去）。

**产物**：`LANShare-5.0.59.hap` 2,446,742 B，sha256 `2342e473…`；commit `f936202` + tag `v5.0.59`；
已推到手机 `Download/LANShare-5.0.59.hap`，同时上传夸克网盘（fileId `27cd0b20841e4ad2bebb3964f193b9b6`）。
skill `harmonyos-arkui-ui-pitfalls` 新增**第二十九节**（`sourceSize` = 解码尺寸 / `autoResize` 等比下采样 /
含两条否掉的中间方案与验证手段）。
"""

d = os.path.dirname(P)
if not os.path.isdir(d):
    os.makedirs(d)

if not os.path.exists(P):
    io.open(P, 'w', encoding='utf-8', newline='\n').write('# 2026-10-02 工作日志\n')

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED')
    sys.exit(0)

assert '\r' not in s, '目标日志里有 CRLF'
s = s.rstrip('\n') + '\n' + ENTRY
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)

chk = io.open(P, encoding='utf-8', newline='').read()
print('OK: 已追加 5.0.59 日志')
print('  len:', len(chk), '| CRLF:', '\r' in chk, '| 5.0.59 段:', chk.count(SENTINEL))
