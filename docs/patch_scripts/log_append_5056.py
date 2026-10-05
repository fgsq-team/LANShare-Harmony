# -*- coding: utf-8 -*-
"""追加 5.0.56 段到当日工作日志。幂等：哨兵判重。"""
import io, sys

P = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
SENTINEL = '### 16:00 5.0.56'

ADD = '''

### 16:00 5.0.56 — 宫格「每行固定 3 个」（vivi 实测反馈：5.0.55 不是固定 3 个）

**vivi 反馈**：实测并不是每行固定 3 个；要求固定每个缩略图框的最大宽高、
照片仍保持原图比例、每行固定显示 3 个。

**根因（两条叠加）**：
① 宫格用的是 `Flex({ wrap: FlexWrap.Wrap })`，而每个格子的**宽度是等比的** ——
   `mediaThumb` 按原图比例算框尺寸（横图 88×44、竖图 44×88、方图 88×88）。
   Flex 换行取决于「这一行还塞不塞得下下一个**不同宽度**的元素」⇒ 一行个数飘忽。
② 格子用 `.margin({right:4, bottom:4})`，**末位元素也带 4 右边距** ⇒
   3×88 + 3×4 = 276 > 容器 272 ⇒ 第 3 个被挤到下一行。这正是「不是 3 个」的直接原因。

**修法**（两条都要做，缺一不可）：
- **固定外框**：新增 `mediaThumbFixed(path, side)` —— 外框恒为 `side × side` 正方形
  （圆角/底色/裁剪照旧），图片在框内 `ImageFit.Contain` 按原图比例留白。
  ⚠️ 用 `Cover` 会把图**裁成正方形**，与「保持原图比例」相悖，所以必须 `Contain`。
  框尺寸复用既有的 `thumbW/thumbH`（它们本就是「按比例 contain 到方框」）。
- **数据层预分行**：`ChatGroup.rows: ChatMessage[][]`（每 3 个一行），渲染改
  `Column{ Row{…} }` + `Row({space:4})` —— **结构上恒定 3 个**，与图片比例彻底无关；
  间距改用 `Row/Column 的 space` 而不是 `margin`（后者末位占位）。
- 常量：`GRID_SIDE=88` / `GRID_COLS=3` / `GRID_GAP=4`；宽度 = `n×88 + (n-1)×4`
  （3 列 = 272，加气泡内边距 16 = 288 ≤ 320vp 屏的 92%×320 = 294，窄屏也不溢出）。
- 版本号 5.0.56 / 5000056。

**验证**：跨模块互引（`Index.GRID_COLS` 用在 Index 内、二维数组 `ChatMessage[][]`）
ArkTS 均接受，`BUILD SUCCESSFUL in 54s`。解包搜到 `mediaThumbFixed` / `GRID_COLS` /
`GRID_GAP` / `GRID_SIDE` / `rowKey`；`module.json` 报 5.0.56 / 5000056。
commit `b0b0faa`，tag `v5.0.56`，夸克网盘。
**知识归档**：skill `harmonyos-arkui-ui-pitfalls` 第二十八节补「要让每行固定 N 个，
光固定宽度还不够」（含 Flex 等比格子 + margin 末位占位两个成因）。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.count('### 15:50 5.0.55') == 1, '找不到 5.0.55 小节'
s2 = s + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK: 日志已追加，%d -> %d' % (len(s), len(s2)))
