# -*- coding: utf-8 -*-
"""追加 5.0.57 段到当日工作日志。幂等：哨兵判重。"""
import io, sys

P = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
SENTINEL = '### 16:15 5.0.57'

ADD = '''

### 16:15 5.0.57 — 缩略图铺满方框 + 多选态加「存相册」

**vivi 要求**：① 框大小合适了，但图片没铺满，要填充显示铺满；② 长按选中消息时加「保存到相册」。

**① 铺满**：`mediaThumbFixed` 由 `Contain`（等比留白）改 **`Cover`（居中裁切铺满）**，
图片尺寸直接给 `side × side`（不再用 `thumbW/thumbH` 算框内尺寸）。框尺寸不变（88×88）。
⚠️ 只改宫格用的 `mediaThumbFixed`；**非宫格的 `mediaThumb`（单张气泡里的缩略图）保持 `Contain`**
—— 那里没有方框约束，裁切没必要。补丁里加了两条断言专门守这个边界。
这回是 vivi 明确要「铺满」，与 5.0.56「保持原图比例」的取舍**方向相反**，
是本人拍板的取舍变化，不是回退。

**② 多选态「存相册 (N)」**：
- 底部条从单按钮改两个（`存相册 (N)` + `删除 (N)`，各 `layoutWeight(1)`）。
- 数量用**新方法 `chatAlbumCount()`** 而不是 `chatSelected.length` ——
  用户可能同时选了图片和文本，用总数会说「存相册 (3)」但实际只有 1 张可存。
  ⚠️ 它带**签名缓存**（`chatSelected.join(',')|chat.length|albumIndex.size`）：
  底部条一次渲染会问它 **5 遍**（按钮文案 2 处 + backgroundColor + fontColor + enabled），
  每次都全量扫是 O(N²)。缓存字段是普通字段（非 @State），不会触发重绘循环。
- 可存判据 `albumPickable(m)`：**收到的**文件消息 + 有媒体名 + **还没有相册条目**
  （已在相册的要排除，否则相册里会多出重复的一张；被系统相册删过的
  `clearAlbumUri` 已摘掉 uri，会重新放行 —— 符合预期）。
- **复用 `autoSaveAlbumBatch(paths, keys, [])`** —— 那条链路已在真机跑通并修过三轮：
  `title` 去点号 + 批内去重、`awaitDialog` 20 秒超时、
  **数量不符不按位置硬配（改逐张）**、写字节 + 缓存缩略图 + 记相册索引。
  自己另写一份批量存相册 = 把那几个坑再踩一遍。`ready` 传空数组（那是自动存队列的结案清单）。
- 提交前把这些消息标进 `autoSaveHandled`，免得自动存那一队稍后又弹一次框。
- **与自动存相册同口径**：存进相册后**删掉沙箱副本**（5.0.53 定的）。
  ⇒ 手动存完之后文件页里那几条会消失，它们是同一份内容，不是丢失。
- 沙箱原图已被删、只剩缓存缩略图时也能存，但只能存 320px 小图 —— 如实写进 UI 日志
  （`其中 N 张只剩缓存缩略图（沙箱原图已删）`），不发额外 toast（怕覆盖 batch 的结果 toast）。
- 路径**去重**（同一份内容被两条消息指到时只提交一次；重复 title 会让系统少建资产）。

**产物**：`E:\\lanshare-harmony\\LANShare-5.0.57.hap`（2,441,692 B）；
`BUILD SUCCESSFUL in 1min53s`；解包搜到 `存相册 (` / `batchSaveChatToAlbum` /
`chatAlbumCount` / `albumPickable` / `手动存相册：提交 ` / `选中的消息里没有可存相册的图片/视频` /
`跳过已在相册的 `；`module.json` 报 5.0.57 / 5000057。commit `92c262f`，tag `v5.0.57`，夸克网盘。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.count('### 16:00 5.0.56') == 1, '找不到 5.0.56 小节'
s2 = s + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK: 日志已追加，%d -> %d' % (len(s), len(s2)))
