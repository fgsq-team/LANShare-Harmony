# -*- coding: utf-8 -*-
"""5.1.11 的判据写进 MEMORY + 今日日志 + 版本编年。"""
import io

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
VER = r'E:\lanshare项目\.workbuddy\memory\VERSION_HISTORY.md'

s = io.open(MEM, encoding='utf-8').read()
if '5.1.11' not in s:
    ANCHOR = '7. ★ **`hdc` 无设备时交付不停**（夸克网盘）'
    assert s.count(ANCHOR) == 1, s.count(ANCHOR)
    ADD = '''4r. ★★★★★★★★★★ **同一个动作有多条入口时，每条都要记账**（5.1.11）。
    5.1.2 只在「单条另存 / 单条删除」两处加了本地状态记账，
    而**删沙箱文件的入口有 4 处** ⇒ 漏了「多选批量删除」「清空所有」
    （vivi 22:0x：「单条删除会同步，清空不会」），另漏「多选批量另存」。
    ★ 这是 **5.0.45 那条教训的镜像**：
       5.0.45 = 「写完一条路径，要问**还有别的路径调同一个函数**吗」
       5.1.11 = 「**同一个动作有多条入口，每条都要记账**」
    ⚠️ 排查手法（很有效）：**列出所有「调用了删除/写入」的入口**，
       逐个对照「有没有配套的记账」⇒ 一眼看出漏了哪些。
       本项目 `grep -n 'ExportService.delete'` 直接列出 4 处。
    ★ 例外要**写明理由**：`autoSaveAlbumBatch`（存相册后删沙箱）**刻意不记**
       「已删除」—— 那是**媒体**，走 `setAlbumIndex` 相册索引，语义不同。
4s. ★★★★ **「先记路径、再删文件、最后 refresh」——顺序错了就记不上**（5.1.11）。
    批量入口手里只有**路径**，要反查**文件名**才能匹配消息（消息里记的是名字）。
    ⚠️ 而「路径 → 文件名」的映射在 `receivedFiles` 里 ——
    `refreshReceived()` 一刷新就没了 ⇒ **必须在 refresh 之前完成记账**。
    ★ 推论：**依赖「即将被清空的数据」做记账，就必须抢在清空动作之前**。
    这与 5.0.45「先记账再删文件（顺序不能反）」是同一族：**顺序是契约，不是细节**。
'''
    s = s.replace(ANCHOR, ADD + ANCHOR, 1)
    assert '5.1.11' in s and chr(0xFFFD) not in s
    io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
    print('OK MEMORY -> %d' % len(s))
else:
    print('MEMORY 已有 5.1.11，跳过')

s2 = io.open(VER, encoding='utf-8').read()
if '5.1.11' not in s2:
    s2 = s2.rstrip('\n') + '''

## 5.1.11（2026-10-02 22:05）
- 修「**批量删除 / 清空后气泡状态不更新**」：5.1.2 只在**单条**另存/删除记了账，
  而删沙箱文件的入口有 **4 处** ⇒ 补上「多选批量删除」「清空所有」「多选批量另存」。
- 新增 `markMessagesLocalByPaths(paths, state)`（批量入口手里只有路径，按路径反查名字）。
- ⚠️ **记账必须在 `refreshReceived()` 之前** —— 映射在 `receivedFiles` 里，刷新后就没了。
- ⚠️ 存相册后删沙箱（`autoSaveAlbumBatch`）**刻意不记**「已删除」——
  那是**媒体**，走相册索引，语义不同。
- ★ 沉淀：**同一个动作有多条入口时，每条都要记账**（5.0.45 那条教训的镜像）。
'''
    io.open(VER, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK VERSION_HISTORY -> %d' % len(s2))

s3 = io.open(LOG, encoding='utf-8').read()
if 'v5.1.11' not in s3:
    s3 = s3.rstrip('\n') + '''

## 22:05 v5.1.11 —— 修「批量删除/清空后气泡状态不更新」

vivi 22:0x：「点单独的文件删除，气泡状态可以同步，但点文件页的清空所有文件，
气泡状态不会更新」。

### 根因：4 处删除入口，只有 2 处记账
`markMessagesLocal` 只有 2 个调用点（单条另存/单条删除），而删沙箱文件的入口有 **4 处**：

| 入口 | 状态 |
|---|---|
| 单条另存为 / 单条删除 | ✅ 已记 |
| **多选批量另存** | ❌ 漏 |
| **多选批量删除** | ❌ 漏 |
| **清空所有** | ❌ 漏（vivi 反馈这条） |
| 存相册后删沙箱 | ⚠️ **刻意不记**（那是媒体，走相册索引） |

排查手法（有效）：`grep -n 'ExportService.delete'` 列出所有删除入口，
逐个对照「有没有配套记账」⇒ 一眼看出漏了哪些。

### 修法
新增 `markMessagesLocalByPaths(paths, state)`（批量入口手里只有路径）。
⚠️ **记账必须在 `refreshReceived()` 之前** ——
「路径 → 文件名」的映射在 `receivedFiles` 里，刷新后就没了 ⇒ 拿不到名字。
（「清空」还要在 `deleteAll` **之前**把路径 `slice()` 一份出来。）

⚠️ 批量另存**只记删除成功的**（`deleteFile` 返回 null）——
删失败说明内容还在沙箱里，不该显示「已存本地」。
且收集与删除必须在**同一个循环**里：我第一版另起一轮 `deleteFile`，
**等于删两次文件**，dry-run 抓到。

### 沉淀
**同一个动作有多条入口时，每条都要记账** —— 这是 5.0.45
（「还有别的路径调同一个函数吗」）那条教训的**镜像**。
★ 另：**依赖「即将被清空的数据」做记账，就必须抢在清空动作之前**。
与 5.0.45「先记账再删文件」同族：**顺序是契约，不是细节**。

### 过程
- 断言拦一次（**落盘前**）：`markMessagesLocalByPaths(` 应数 3 处 ——
  我把**定义**也算了（定义是 `private ...(`，**不带 `this.`**）⇒ 磁盘零污染。
- ⚠️ 又一次 `BUILD SUCCESSFUL in 8 s` 是**旧代码** —— 5.1.1 以来**第五次**。

**产物**：`LANShare-5.1.11.hap`（2,511,551 B，已推手机 Download）；commit `c102935` + tag `v5.1.11`。

**待 vivi 复测**：① 单条删除 → 气泡变「已删除」（本来就 OK，确认没退化）；
② **多选批量删除 → 全部对应气泡变「已删除」**；
③ **清空所有 → 全部气泡变「已删除」**（本轮目标）；
④ 多选批量另存 → 变「已存入本地」；
⑤ 5.1.10 闪退提示不再每次弹；⑥ 5.1.9 视频「视频」文字角标正常。
'''
    io.open(LOG, 'w', encoding='utf-8', newline='\n').write(s3)
    print('OK LOG -> %d' % len(s3))
