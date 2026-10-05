# -*- coding: utf-8 -*-
"""
更新 skill `harmonyos-arkui-ui-pitfalls` 第二十八节：
把「宫格每行固定 N 个」的正确做法补全 —— 之前只写了「宽度不能写 100%」，
但真机实测发现**光固定宽度还不够**：
  ① `Flex(wrap)` + **等比宽度**的格子 ⇒ 一行个数飘忽（横/竖/方宽度各不相同）；
  ② 格子用 `margin({right:4})` 时**末位也带右边距** ⇒ 3×88+3×4=276 > 容器 272，第 3 个被挤下去。
正确做法 = **固定外框 + 数据层预分行**。

幂等：哨兵判重。写文件保持 LF。
"""
import io, sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'
SENTINEL = '#### 要让「每行固定 N 个」，光固定宽度**还不够**'

ADD = '''

#### 要让「每行固定 N 个」，光固定宽度**还不够**（宫格实测）

上一版只固定了容器宽度，真机仍然不是每行 3 个。两个叠加的成因：

**① 格子宽度是「等比」的 ⇒ 一行个数飘忽**

缩略图要保原图比例，很容易写成「按比例算框尺寸」（横图 `88×44`、竖图 `44×88`、方图 `88×88`）。
这时用 `Flex({ wrap: Wrap })`，换行取决于"这一行还塞不塞得下**下一个宽度不同**的元素"——
一行 3 个还是 4 个完全看图片比例，**不可预测**。

**② 用 `margin` 做间距 ⇒ 末位也占位，正好挤出下一行**

```ts
Stack().margin({ right: 4, bottom: 4 })        // ❌ 每行最后一个也带 4
// 容器 272，3×88 + 3×4 = 276 > 272  ⇒ 第 3 个被挤到下一行
```

**正确做法：固定外框 + 在数据层预分行**

```ts
// ① 外框恒为正方形，图片在框内 Contain（保比例、留白，不裁切）
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
}

// ② 分行在**数据层**切好，渲染时 Column{ Row{…} } —— 结构上恒定 N 个
//    ChatGroup.rows: ChatMessage[][]   （每 N 个一行）
@Builder
chatMediaGrid(g: ChatGroup) {
  Column({ space: GRID_GAP }) {
    ForEach(g.rows, (row: ChatMessage[]) => {
      Row({ space: GRID_GAP }) {           // ★ 用 space 而不是 margin
        ForEach(row, (m: ChatMessage) => { … })
      }
    }, (row) => this.rowKey(row))
  }
  .width(n * GRID_SIDE + (n - 1) * GRID_GAP)
}

// ③ 宽度按列数算死：3×88 + 2×4 = 272（加气泡内边距 16 = 288，
//    320vp 窄屏上仍 ≤ 92%×320 = 294，不会溢出）
```

**三条要点**：

- **外框固定**是「每行个数固定」的前提 —— 只要每格占地一样，排布才可预测。
- **比例靠 `Contain` 保**，不靠"框尺寸随比例变"。框是框、图是图，两者解耦。
- **间距用 `Row/Column` 的 `space`，不要用 `margin`** —— 后者末位也占位，会平白挤掉一格。
  （`Flex` 的 `space` 需要 `LengthMetrics.vp()`，比 `Row/Column` 的 `space` 啰嗦，非必要不用。）
- 分行放**数据层**（`rows: T[][]`）而不是渲染层临时算 —— 渲染层算需要索引，
  `ForEach` 的 itemGenerator 虽然有 `index`，但在嵌套 `@Builder` 里用起来更容易出错。

#### 排查口诀（再补）

- 「宫格一行几个不固定」→ 先查**格子宽度是不是等比的**，再查**间距是不是用了 margin**。
- 两个都改完还是不对 → 查容器宽度有没有和「列数 × 边长 + 间距」算错（多算或少算一个间距）。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
anchor = '### 排查口诀\n\n- 「一批的多条想合成一个卡片」'
assert s.count(anchor) == 1, '锚点命中 %d 次' % s.count(anchor)
s2 = s.replace(anchor, ADD.lstrip('\n') + '\n' + anchor)
assert s2 != s
io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK: 第二十八节已补「每行固定 N 个」，%d -> %d' % (len(s), len(s2)))
