# -*- coding: utf-8 -*-
"""把 5.1.4 的两条判据写进 MEMORY.md + 今日日志 + 版本编年。"""
import io

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
VER = r'E:\lanshare项目\.workbuddy\memory\VERSION_HISTORY.md'

# ---------------- 1) MEMORY.md ----------------
s = io.open(MEM, encoding='utf-8').read()
if '5.1.4' not in s:
    ANCHOR = '7. ★ **`hdc` 无设备时交付不停**（夸克网盘）'
    assert s.count(ANCHOR) == 1, s.count(ANCHOR)
    ADD = '''4g. ★★★★★★ **「拆成多条」与「聚合成一个」是两个独立开关，别混为一谈**（5.1.4，踩过）。
    `buildChatGroups` **只按 `batchId` 聚合**；而「N 个文件合并成一条消息」是
    `appendFileChat` 决定的（`content`=label、`files`=全部名字、**`batchId` 空**）。
    ★ **想改成「每个文件一个气泡」，正确做法 = 逐个 `appendChat` + `batchId` 留空**。
    ⚠️⚠️ **绝不能顺手给它们共 `batchId`** —— 那会走进 `groupAllMedia`（走 `allMedia(names)`），
    而 `allMedia` 对 zip/pdf 返回 **false** ⇒ `isMedia=false` ⇒ 不走宫格
    ⇒ **界面看起来完全没变**，白改一轮。
    ★ 归类：`appendFileChat` 控**消息条数**，`batchId`+`groupAllMedia` 控**渲染形式**。
    5.0.55 只把「拆消息」用于媒体，本轮把非媒体也拆、宫格仍只给媒体。
4h. ★★★★★★ **自绘弹窗必须逐个登记到 `onBackPress`，漏一个 = 按返回就退出应用**（5.1.4）。
    本项目已有 6 个弹窗登记在册（`confirmVisible`/`imgPreview`/`fileSelectMode`/
    `chatSelectMode`/`showQr`/`pickStep`），`showAbout` **漏了** ⇒ 落到末尾
    `return false` 交还系统 ⇒ **直接退出到桌面、而弹窗还开着**。
    ★ **新增任何 `showXxx` 弹窗时，同步在 `onBackPress` 加一个分支**（写代码时就在注释里留提醒）。
    ★ 症状很好认：**「按返回退出应用，但界面上某个弹窗还开着」** ⇒ 就是漏登记。
4i. ★★ **断言写「不该出现 X」时，要先确认 X 不会在别处合法存在**（5.1.4，踩过）。
    我写「非媒体被误传 batchId」，判据 = `appendChat + names[i] + 行尾是 ', bid);'`
    ⇒ **把媒体那行（本来就该有 bid）也当成违规** ⇒ 断言在落盘前拦下、磁盘零污染。
    ✅ 正确判据 = **数「带该标记的行数」，断言改后恰好 N 行**（本例 N=1），
    而不是断言「这样的行不存在」。★ 通用：**「计数」比「存在性」更难被误判**。
'''
    s = s.replace(ANCHOR, ADD + ANCHOR, 1)
    assert '5.1.4' in s and chr(0xFFFD) not in s
    io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
    print('OK MEMORY -> %d' % len(s))
else:
    print('MEMORY 已有 5.1.4，跳过')

# ---------------- 2) VERSION_HISTORY.md ----------------
s2 = io.open(VER, encoding='utf-8').read()
if '5.1.4' not in s2:
    s2 = s2.rstrip('\n') + '''

## 5.1.4（2026-10-02 21:32）
- **收到多个文件改成多个气泡**：`appendFileChat` 的非媒体分支改为逐个建消息、
  **`batchId` 留空**（留空才各自成气泡；给 batchId 会走 `groupAllMedia` 而 zip 判非媒体 ⇒ 界面不变）。
  ⚠️ **「拆消息」与「聚合成宫格」是两个独立开关**。
- **「关于」页返回不再退到桌面**：`onBackPress` 补 `showAbout` 分支
  （此前处理了 6 个弹窗却漏了它 ⇒ `return false` 交还系统 ⇒ 退出应用）。
  ★ 新增 `showXxx` 弹窗必须同步登记到这里。
'''
    io.open(VER, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK VERSION_HISTORY -> %d' % len(s2))

# ---------------- 3) 今日日志 ----------------
s3 = io.open(LOG, encoding='utf-8').read()
if 'v5.1.4' not in s3:
    s3 = s3.rstrip('\n') + '''

## 21:32 v5.1.4 —— ①多文件多气泡 ②关于页返回不退到桌面

vivi 21:28 提两件事。

### ① 根因：聚合只按 batchId，而非媒体压根没给 batchId
`buildChatGroups` 只按 `batchId` 聚合；而 `appendFileChat` 的非媒体分支把整批塞进
**一条**消息（`content`=label、`files`=全部名字、**`batchId` 空**）
⇒ 聚合条件不成立 ⇒ **一个气泡**。媒体批在上一段已 return，所以只有非媒体如此。

修法：非媒体也**逐个 appendChat**、`batchId` **留空**。
⚠️ **绝不能顺手给共 batchId** —— 那会走 `groupAllMedia`（`allMedia` 对 zip 返回 false）
⇒ `isMedia=false` ⇒ 不走宫格 ⇒ **界面看起来完全没变**，白改。
★★ **「拆成多条消息」（appendFileChat）与「聚合成一个宫格」（batchId + groupAllMedia）
是两个独立开关**。5.0.55 只把前者用于媒体，本轮把非媒体也拆。

### ② 根因：`onBackPress` 漏登记 `showAbout`
它处理了 6 个弹窗（confirm / imgPreview / fileSelect / chatSelect / showQr / pickStep），
**唯独漏了 `showAbout`**（实测命中 0）⇒ `return false` 交还系统
⇒ **按返回直接退出到桌面、而弹窗还开着**。

★★ **自绘弹窗 + 系统返回**是本项目固有陷阱：**漏登记一个 = 按返回就退出应用**。
症状很好认：「按返回退出应用，但界面上某个弹窗还开着」。已在代码注释留提醒。

### 过程
- 断言拦一次（落盘前）：「非媒体被误传 batchId」的判据把**媒体那行**也当成违规
  ⇒ 改成**数「带 bid 的 `names[i]` 行数」，改后恰好 1 行**。
  ★ **「计数」比「存在性」更难被误判** —— 通用教训。
- ⚠️ 同轮 `BUILD SUCCESSFUL in 8 s` 是**旧代码**（补丁没落盘），已重新构建（24 executed）。
  **「构建成功」不能当「改动已生效」的证据** —— 5.1.1 吃过一次，这次 8s 就暴露了。

**产物**：`LANShare-5.1.4.hap`（2,498,677 B，已推手机 Download）；
commit `c75f906` + tag `v5.1.4`。

**待 vivi 复测**：① 收 3 个 zip → **3 个气泡**（不是 1 个）；
② 收 3 张图 → 仍是**1 个宫格**（不能被这次改动影响）；
③ 打开「关于」→ 按返回 → **回软件界面、弹窗关闭**；
④ 其余弹窗（确认框/预览/多选/二维码/选文件）返回仍正常；
⑤ 5.1.3 的「已存入本地/已删除」在多文件场景下仍对（现在每条消息只有 1 个文件名）。
'''
    io.open(LOG, 'w', encoding='utf-8', newline='\n').write(s3)
    print('OK LOG -> %d' % len(s3))
