# -*- coding: utf-8 -*-
"""5.1.9 的判据写进 MEMORY + 今日日志 + 版本编年。"""
import io

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
VER = r'E:\lanshare项目\.workbuddy\memory\VERSION_HISTORY.md'

s = io.open(MEM, encoding='utf-8').read()
if '5.1.9' not in s:
    ANCHOR = '7. ★ **`hdc` 无设备时交付不停**（夸克网盘）'
    assert s.count(ANCHOR) == 1, s.count(ANCHOR)
    ADD = '''4n. ★★★ **断言必须区分「代码」与「注释」**（5.1.9 连踩三次，磁盘零污染）。
    本轮三次断言失败**全部同一病因**：
    ① 判「`▶` 已移除」⇒ 漏了**画廊预览**（`:5319`，刻意保留的另一套标识）
       ⇒ 改为**只查目标函数段**；
    ② 该段里 `▶` 还有 3 处在 **5.1.7/5.1.8 自己写的注释**里（历史说明）
       ⇒ 改为**只查代码行**（过滤 `//` / `*` / `/*` 开头）；
    ③ 判「`Text('视频')` 应 2 处」⇒ 但**占位那处是三元表达式**
       `Text(isVideo ? '视频' : '图片')`，**不是字面量** ⇒ 改为 1。
    ★★ **通则：写「某符号应/不应出现」的断言前，先问三件事**：
       ① **别的函数**里有没有（同名符号合法共存）？
       ② **注释**里有没有（历史说明会提到）？
       ③ 是**字面量**还是**表达式/常量引用**？
    ⇒ 三个任一答错，断言就会误判 ⇒ 白跑一轮。
    ★ 另：同一轮里我自己还把 `seg` 定义写在**使用之后**（顺序错），
      也是断言自身的问题 —— **断言脚本本身也要 review，不能只 review 产品代码**。
4o. ★★ **`Text` 没有 `.align()`；定位要包一层 `Stack({alignContent})`**（5.1.9 踩到）。
    缩略图上的角标要避开正中（挡封面主体）时，
    `Text(...).align(Alignment.BottomStart)` **不存在**（`alignContent` 是 `Stack` 的参数）。
    ✅ 正确写法：`Stack({ alignContent: Alignment.BottomStart }) { Text(...) }.width('100%').height('100%')`。
    ★ 顺带发现：**多个角标共用同一个 `Stack` 时会叠在一起**（本项目「已删」与「视频」
      都在 `chatMediaGrid` 的那个 `Stack` 里、且**都默认居中**）⇒ 选不同角落避开。
'''
    s = s.replace(ANCHOR, ADD + ANCHOR, 1)
    assert '5.1.9' in s and chr(0xFFFD) not in s
    io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
    print('OK MEMORY -> %d' % len(s))
else:
    print('MEMORY 已有 5.1.9，跳过')

s2 = io.open(VER, encoding='utf-8').read()
if '5.1.9' not in s2:
    s2 = s2.rstrip('\n') + '''

## 5.1.9（2026-10-02 21:55）
- 视频标识 `▶` 图标 → **「视频」文字角标**（半透明黑底 + 白字 + 圆角），
  并**挪到左下角**（`Stack({alignContent: Alignment.BottomStart})` 包裹 ——
  `Text` **没有 `.align()`**；默认居中会挡住封面主体，且会与「已删」角标叠在一起）。
- `chatFileBubble` 的英文 `VIDEO` 徽标**统一改成中文「视频」**（样式也统一）。
- 画廊预览的 `▶`（`:5319`）**刻意保留**（另一语境）。
- ★ 沉淀：**断言必须区分「代码 / 注释 / 字面量 vs 表达式」** ——
  本轮三次断言失败全同一病因，磁盘零污染。
'''
    io.open(VER, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK VERSION_HISTORY -> %d' % len(s2))

s3 = io.open(LOG, encoding='utf-8').read()
if 'v5.1.9' not in s3:
    s3 = s3.rstrip('\n') + '''

## 21:55 v5.1.9 —— 视频标识改纯文字角标

vivi 21:51：「只能看到播放按钮，但播放按钮不太好看，改成文字显示」。

改动：`mediaThumbFixed` 末尾的 `▶` → **「视频」文字角标**（半透明黑底/白字/圆角 4），
**挪到左下角**。顺带把 `chatFileBubble` 的英文 `VIDEO` 徽标**统一成中文「视频」**
（用户界面与反馈都是中文）。画廊预览的 `▶`（`:5319`）**刻意保留**。

★ 位置：5.1.8 的 `▶` 靠默认居中压**正中**，换文字后那两个字正好盖住封面主体
⇒ 用 `Stack({alignContent: Alignment.BottomStart})` 挪到左下。
顺带发现「已删」角标也在**同一个 `Stack`** 里且同样默认居中 ⇒ 两者会叠
⇒ 视频选左下避开中心。
⚠️ 踩到 ArkTS 细节：**`Text` 没有 `.align()` 方法**（`alignContent` 是 `Stack` 的参数），
必须**包一层 `Stack`**。

判据不变（5.1.8 结论）：仍用 **`if (isVideo)`**（事实），**不受 `path` 门控**。

### ★ 断言连错三次，全同一病因：没区分「代码 / 注释 / 字面量」
① 漏了**画廊预览**的 `▶`（刻意保留）⇒ 改为只查目标函数段；
② 该段还有 3 处在 **5.1.7/5.1.8 自己的注释**里 ⇒ 改为**只查代码行**；
③ `Text('视频')` 应 2 处 —— 但**占位那处是三元表达式**，不是字面量 ⇒ 改为 1。
★ 另：自己把 `seg` 定义写在**使用之后**（顺序错）。
⇒ **写「某符号应/不应出现」的断言前先问三件事**：
别的函数里有吗？注释里有吗？是字面量还是表达式/常量引用？
★ **断言脚本本身也要 review** —— 它也会出 bug（本轮）。

**产物**：`LANShare-5.1.9.hap`（2,506,729 B，已推手机 Download）；commit `c27cfec` + tag `v5.1.9`。

**待 vivi 复测**：① 视频缩略图**左下角**显示「视频」文字、**没有 ▶ 图标**；
② 图片**没有**任何角标；③ 与「已删」角标**不重叠**；
④ 5.1.5 的「已存入本地/已删除」终于显示。
'''
    io.open(LOG, 'w', encoding='utf-8', newline='\n').write(s3)
    print('OK LOG -> %d' % len(s3))
