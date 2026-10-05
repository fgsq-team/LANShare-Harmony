# -*- coding: utf-8 -*-
"""5.1.5 / 5.1.6 的判据写进 MEMORY + 今日日志 + 版本编年。"""
import io

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
VER = r'E:\lanshare项目\.workbuddy\memory\VERSION_HISTORY.md'

s = io.open(MEM, encoding='utf-8').read()
if '5.1.5' not in s:
    ANCHOR = '7. ★ **`hdc` 无设备时交付不停**（夸克网盘）'
    assert s.count(ANCHOR) == 1, s.count(ANCHOR)
    ADD = '''4j. ★★★★★★★★ **「同一个坑踩第二次」= 必须把它升格成「新建某类东西时的强制检查项」**。
    5.0.71→5.0.72 总结过一次「靠表达式承载的显示必须让那一层真的重建」；
    **5.1.2 又踩了同一个坑的变体**（5.1.5 修复）—— 我把那条写进 commit 就当完了，
    **没写进「新建 Map / 新建判据时该问什么」的检查清单** ⇒ 隔两版重犯。
    ★★ **通则（`localMap` 这类踩坑的通用形态）**：
    **显示读的值若是「服务端普通 Map / 普通字段」⇒ 那一格没有 @State 依赖 ⇒ 改它不重建 ⇒ 界面停在旧值。**
    ✅ 修法 = 加一个 `@State` 版本号（tick），**在显示处读一次**（或传给一个不参与拼接的 helper 形参），
    **写入处 ++**（且要配闸门缓冲，避免 N 次重渲染）。
    ⚠️ **两条缺一不可**：只 `++` 没人读 ⇒ 依赖建不起来；只读但永不变 ⇒ 一样不重建。
    ⚠️ **tick 绝不参与拼接返回值**（拼进去会因改文案而销毁重建）。
    ★ 与 5.0.63 对 `thumbTick`、5.0.72 对 `groupGoneSig` **是同一套手法的三种形态**。
    ★★ **判定「要不要重建」**：先问「这个显示读的值**是不是 @State**」——
       不是 ⇒ 它变了一定不刷新，**必须**补一个 @State 通道。
4k. ★★ **「我以为某调用会刷新 UI」必须验证它刷的是哪一个状态**（5.1.5）。
    5.1.2 调 `swapAlbumIndex()` 时**注释乐观地写**「走换引用闸门 ⇒ 气泡提示会真的重新求值」——
    而它换的是 `albumIndex`，**与 `localMap` 毫无依赖关系** ⇒ 白调。
    ★ **写「这样做会触发刷新」之前，先问「触发的那个 @State，是不是这个显示所依赖的」**；
    不确定就去显示表达式里看它读了谁。★ **注释里的因果断言也要当代码校验** ——
    它会骗你，且骗得比代码还久（因为没人会去编译它）。
'''
    s = s.replace(ANCHOR, ADD + ANCHOR, 1)
    assert '5.1.5' in s and chr(0xFFFD) not in s
    io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
    print('OK MEMORY -> %d' % len(s))
else:
    print('MEMORY 已有 5.1.5，跳过')

s2 = io.open(VER, encoding='utf-8').read()
if '5.1.6' not in s2:
    s2 = s2.rstrip('\n') + '''

## 5.1.5 / 5.1.6（2026-10-02 21:42）
- **5.1.5** 修「已存入本地/已删除」**不显示**（5.1.2 写下状态但看不见）：
  `localMap` 是服务端**普通 Map** ⇒ `bubbleFooterText` 非媒体分支**不读任何 @State**
  ⇒ 那一格不重建 ⇒ `Text` 停在 build 时的「点击查看」。
  ⇒ 新增 `@State localStateTick`（+ 闸门缓冲 `localStateTickNext`），
  **显示处读一次并传给 `padHint` 的 `_tick` 形参**（不参与拼接），
  写入处 `++`（替换掉 5.1.2 那句无效的 `swapAlbumIndex()`）。
  ★ **与 5.0.71→5.0.72 同一个坑的变体，隔两版重犯** —— 已升格为检查项。
- **5.1.6** 视频加 `VIDEO` 角标：`chatFileBubble` 的文件名分支里
  `msgIsVideo(m)` 为真时加徽标（宫格那支已有 ▶，这个是兜底）。
'''
    io.open(VER, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK VERSION_HISTORY -> %d' % len(s2))

s3 = io.open(LOG, encoding='utf-8').read()
if 'v5.1.6' not in s3:
    s3 = s3.rstrip('\n') + '''

## 21:42 v5.1.5 / v5.1.6 —— 修「已存入本地/已删除」不显示 + 视频角标

vivi 21:35 反馈 5.1.4 的记账**不好使了**（状态写了但看不见）。

### ★★ 同一个坑踩第二次
5.0.71→5.0.72 我总结过「靠表达式承载的显示必须让那一层真的重建」，
**5.1.2 又踩了同一个坑的变体** —— 而且 5.1.2 的注释里还乐观地写着
「走换引用闸门 ⇒ 气泡提示会真的重新求值」，**这句是错的**：
`swapAlbumIndex()` 换的是 `albumIndex`，与 `localMap` **毫无依赖关系**。

根因：`bubbleFooterText` 的非媒体分支读的全是**非 @State**
（`service.localStateOf` 读服务端普通 Map、`padHint` 只读静态常量）
⇒ **那一格没有任何 @State 依赖** ⇒ 记账后不重建
⇒ `Text(...)` **永远停在 build 那一刻的值**（＝「点击查看」）。

修法（与 5.0.63 对 `thumbTick` 一致）：
新增 `@State localStateTick`（+ 闸门缓冲 `localStateTickNext`），
**显示处读一次**并传给 `padHint` 的 `_tick` 形参（**不参与拼接**），
写入处 `++`（**替换掉那句无效的 `swapAlbumIndex()`**）。
⚠️ 两条缺一不可：只 `++` 没人读 ⇒ 依赖建不起来；只读但永不变 ⇒ 一样不重建。

★★ **教训已升格**：「显示读的值是不是 @State」**必须**成为「新建 Map / 新建判据」时的
强制检查项 —— 我上轮只把它写进 commit message，**没进检查清单** ⇒ 隔两版重犯。
★ 另外：**注释里的因果断言也要当代码校验** —— 它会骗你，且骗得比代码更久。

### 5.1.6 视频角标
`chatFileBubble` 的 `mediaThumb` 分支有 ▶，但 **5.0.77 单张并入宫格后**
`chatFileBubble` 只剩非媒体 ⇒ 视频进不了那个分支。
现补：文件名分支里 `msgIsVideo(m)` 为真时加 `VIDEO` 徽标（紫底白字）。

### 过程
- 断言又拦两次（**都在落盘前**）：`Text(m.content) == 2` **全文件不止 2 处**
  ⇒ 改成**在 `chatFileBubble` 函数体内**数。
- ⚠️ **`BUILD SUCCESSFUL` 是旧代码**（补丁被断言拦住没落盘）——
  这是 5.1.1 以来**第三次**，已成固定检查项：**先确认补丁落盘，再看构建结果**。

**产物**：`LANShare-5.1.6.hap`（2,503,690 B，已推手机 Download）；commit `38a1474` + tag `v5.1.6`。

**待 vivi 复测**：① 另存 zip → **气泡变「已存入本地」（这条之前一直没生效，务必确认）**；
② 文件页删除 → 变「已删除」；③ **多发 zip 每个气泡各自独立变**；
④ 视频气泡有 `VIDEO` 角标；⑤ 重启后状态仍在。
'''
    io.open(LOG, 'w', encoding='utf-8', newline='\n').write(s3)
    print('OK LOG -> %d' % len(s3))
