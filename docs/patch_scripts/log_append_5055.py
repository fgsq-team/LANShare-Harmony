# -*- coding: utf-8 -*-
"""追加 5.0.55 段到当日工作日志。幂等：哨兵判重。"""
import io, sys

P = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
SENTINEL = '### 15:50 5.0.55'

ADD = '''

### 15:50 5.0.55 — 接收的多张图片/视频聚合成**一个宫格气泡**，且不再显示文件名

**vivi 要求**：「接受的图片和视频是否可以在一个气泡里显示多个缩略图，不需要显示图片和视频的文件名」。

**看似与 5.0.53 冲突，实则是两个层次**：
5.0.53 把「接收 N 张图」拆成 N 条消息，是为了**记账粒度**（每张各有相册条目 + 点击入口，
修「删一张整批失效 / 点不到第 2 张」）；这次要的「一个气泡」是**显示粒度**。
⇒ **显示聚合 ≠ 记账聚合**，加个批号在渲染层聚合即可，绝不能回去合并消息
（合并 = 把 5.0.53 的修复废掉）。

**改动**：
- `LanService.ets`：`ChatMessage` 加 `batchId`（同批共享）；`nextBatchId()`（自增+时间戳，
  避免与 `c…` 形态的消息 id 相撞）；`appendFileChat` 拆分时给 N 条打同一个批号；
  `appendChat` 加可选参数 `batchId`（全部既有调用点不传 → 行为不变）；
  **序列化/反序列化补 `batchId`**（不落盘的话重启后同批会散成 N 个气泡 —— 与 5.0.43
  「Map 落盘必须把 key 一起写」是同一类失配）。新增 `export class ChatGroup`（视图模型）。
- `Index.ets`：`@State chatGroups` + `buildChatGroups()`（按批号把**连续**的同批消息聚成一组，
  元素是原数组的**同一引用**）+ 签名判等（不换引用就不重建）；消息页 `ForEach` 数据源
  从 `this.chat` 换成 `this.chatGroups`；新增 `chatGroupBubble`（单条组**原样转发**老
  `chatBubble` —— 零风险，历史数据/文本/发送方向全不变）、`chatMediaBubble`（宫格气泡，
  结构同 chatBubble：Row+Blank 顶开、勾选圆、长按进多选）、`chatMediaGrid`（`Flex.wrap`
  每行 3 个，**每格自己的 onClick** → 落到**自己那条消息**上，这才是「点第 2 张开第 2 张」）；
  多选按**整组**（`enterChatGroupSelect`，勾选圆有 `✓`/`−`/空三态），多选态下点单格 = 只切那一张。
- 顺手做掉：**图片/视频不显示文件名**（`chatFileBubble` 里用 `if` 包裹；判据是
  「有没有可显示的媒体」而不是扩展名 —— 后者在媒体未落盘时会把名字闪一下再消失）；
  非媒体文件（zip/pdf/apk）仍显示文件名（那是唯一标识）。
- 版本号 5.0.55 / 5000055。

**踩到的两个细节**（已归档进 skill 第二十八节）：
① 宫格**不能写 `width('100%')`** —— 父 Column 是 wrapContent 宽，百分比会落到「无限宽」上
   （5.0.50 老坑同款），2 张图也撑满整行 ⇒ 改成按列数算固定宽度 `gridWidth(g)`。
② `ForEach` 的 key 必须带上**组内每条**的媒体路径与相册条目（`groupMediaSig` / `groupAlbumSig`），
   只放组 id 的话「缩略图从空变实」「相册条目从无到有」都不会重建那一行。

**产物**：`E:\\lanshare-harmony\\LANShare-5.0.55.hap`（2,420,078 B）；
`BUILD SUCCESSFUL in 45s 910ms`（构建两次：第一次成功后为「气泡宽度贴合内容」又改了一次）；
解包 `modules.abc` 搜到 `chatGroupBubble` / `chatMediaBubble` / `chatMediaGrid` / `buildChatGroups`
/ `已删` / `张 · ` / `groupMediaSig` / `enterChatGroupSelect` / `batchId`；
`module.json` 报 5.0.55 / 5000055。commit `7faef0e`，tag `v5.0.55`，夸克网盘。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.count('### 15:05 5.0.54') == 1, '找不到 5.0.54 小节'
s2 = s + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK: 日志已追加，%d -> %d' % (len(s), len(s2)))
