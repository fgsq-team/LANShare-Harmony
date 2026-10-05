# -*- coding: utf-8 -*-
"""v5.0.78 —— 方案 A：单张图片/视频并入宫格渲染，长按逻辑统一（vivi 2026-10-02 20:43）。

【vivi 的洞察】**「单张不就相当于单个的宫格」** —— 说得对，两者是**同构**的：
    发送方名 + 时间 / 缩略图 / `N 张 · 提示`
唯一的差别只是「格数是 1 还是 N」。

【为什么之前是两套代码】历史原因：5.0.55 引入宫格气泡时判据写了
`g.msgs.length < 2` ⇒ 单张被排除 ⇒ 走 `chatBubble` → `chatFileBubble` 那条老路。
5.0.72~5.0.77 我一直在**两条路上分别修同一个问题**（缩略图尺寸、Cover 铺满、
已删角标、提示文案），导致单张接连漏掉「已删」角标、还多出一句「收到文件」。
⇒ 这次把**源头**修掉：让单张也走宫格。

【★ 长按逻辑天然统一，不需要新增任何代码】
vivi 20:43：「把单张各多张的长按逻辑统一起来，不必单独做单张的长按保存逻辑，
现在多张长按选中气泡后也可以选保存到相册」——
**查证结果：两条路的长按本来就已经都是「进多选」**：
    `chatBubble`      的 LongPressGesture → `enterChatSelect(m.id)`（进多选）
    `chatMediaBubble` 的 LongPressGesture → `enterChatGroupSelect(g)`（进多选）
而「存相册」在**多选态底部**（`batchSaveChatToAlbum`，5.0.57 加的「存相册 (N)」）。
⇒ 单张并入宫格后，**长按 → 多选 → 底部点「存相册」** 这条链自动就有，
   **零新增逻辑**，而且这正是 vivi 要的「统一」。

【改动】
1. `groupAllMedia` 去掉 `g.msgs.length < 2` 限制 ⇒ **单张也判为媒体组**
   ⇒ `chatGroupBubble` 自动派发到 `chatMediaBubble`，**两条老路就此合并**。
2. 顺带把「自己发出去的媒体」也纳入（原来还要求 `incoming`）——
   ⚠️ 但这会改变**自己发图**的气泡形态（从文件气泡变成宫格气泡），
   而自己发的图**沙箱里没有**（在对方手机上）⇒ 显示会变空白。
   ⇒ **本次只放开「收到的」这一条**（去掉 `length < 2`、保留 `incoming`），
     保守起见不扩大范围。要放开自己发的需单独确认（存相册逻辑对发出方无意义）。
3. `chatMediaGrid` 的 `rows` 对单张天然是 `[[m]]`（`GRID_COLS` 切行逻辑已覆盖），
   `gridWidth` 对 1 列也算得对 ⇒ 格子宽度与多张时**完全一致**。
4. 「已删」角标、Cover 铺满、提示文案、缩略图尺寸**全部自动统一**（因为走同一条路）。

⚠️ **`chatFileBubble` 与 `chatBubble` 的文件分支仍保留**：非媒体文件
（zip/pdf/apk）没有缩略图，仍走老路显示文件名 —— 那是**必需**的，不能删。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★★ 5.0.77' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5077bpre'), (VER, 'app.json5.v5077bpre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：groupAllMedia 放开「只有 1 张」
# =====================================================================
OLD1 = """  private groupAllMedia(g: ChatGroup): boolean {
    if (g.msgs.length < 2 || g.msgs[0].kind !== 'file' || !g.msgs[0].incoming) {
      return false;
    }"""
NEW1 = """  private groupAllMedia(g: ChatGroup): boolean {
    // ★★ 5.0.77（vivi 20:43「单张不就相当于单个的宫格」）：去掉 `length < 2` 限制。
    //
    // 【为什么要合】单张与多张是**同构**的（发送方名+时间 / 缩略图 / N张·提示），
    //   之前是两条独立代码路径，导致同一个问题要**分别修两遍**，而我接连漏掉：
    //     - 5.0.72 单张缩略图忘了改成 88 固定方框
    //     - 5.0.73 单张忘了改 `Cover` 铺满
    //     - 5.0.77 单张**漏了「已删」角标**（vivi 20:36 反馈）
    //     - 单张顶部还多一句「收到文件」（宫格那边是「发送方名 + 时间」）
    //   ⇒ 从**源头**合并，比继续在两条路上打补丁可靠。
    //
    // 【★ 长按逻辑天然统一，零新增代码】
    //   两条路的长按**本来就已经都是「进多选」**：
    //     `chatBubble`      → `enterChatSelect(m.id)`
    //     `chatMediaBubble` → `enterChatGroupSelect(g)`
    //   而「存相册」在**多选态底部**（`batchSaveChatToAlbum`，5.0.57 加的
    //   「存相册 (N)」）。⇒ 单张并入后，「长按 → 多选 → 底部点存相册」这条链
    //   自动就有 —— 正是 vivi 要求的「统一」（20:43）。
    //
    // ⚠️ **仍然只放开「收到的」**（`incoming` 保留）：自己发出去的图**沙箱里没有**
    //   （它在对方手机上）⇒ 走宫格会显示空白；而存相册对发出方也没有意义。
    //   要放开自己发的需单独确认，不在本轮擅自扩大范围。
    if (g.msgs[0].kind !== 'file' || !g.msgs[0].incoming) {
      return false;
    }"""

# =====================================================================
# 改 2：groupMediaSig 之类的分组签名不必改（g.key 已含条数）；
#        但 buildChatGroups 里 rows 的切分对 1 张天然正确 —— 无需改。
# =====================================================================

OLD2 = '"versionCode": 5000076'
NEW2 = '"versionCode": 5000077'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 放开单张'),):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD2) == 1
v2 = v2.replace(OLD2, NEW2, 1)
assert v2.count('"versionName": "5.0.76"') == 1
v2 = v2.replace('"versionName": "5.0.76"', '"versionName": "5.0.77"', 1)

# ---- 不变量 ----
# 判据已放开
assert 'g.msgs.length < 2' not in s2, 'length < 2 限制仍在'
assert "if (g.msgs[0].kind !== 'file' || !g.msgs[0].incoming) {" in s2
# 非媒体文件的老路必须保留（zip/pdf/apk 没缩略图，要显示文件名）
assert 'this.chatFileBubble(' in s2, 'chatFileBubble 被误删'
assert 'this.chatBubble(g.msgs[0])' in s2, 'chatGroupBubble 派发被误改'
# rows 切分对 1 张天然正确（buildChatGroups 里的 GRID_COLS 循环）
assert 'for (let k: number = 0; k < g.msgs.length; k += Index.GRID_COLS) {' in s2
assert 'private gridWidth(g: ChatGroup)' in s2
# 前几轮修复仍在
# 单张并入宫格后，角标只须存在于宫格那一处；chatFileBubble 里若还有残留也不影响
# （那条路已不被媒体消息走到），但为清晰起见要求 >=1
assert "Text('已删')" in s2, '宫格的已删角标丢了'
assert 'this.mediaThumbFixed(' in s2
assert 'this.probeAlbumOnEnterChat();' in s2
assert 'private padHint(s: string): string {' in s2
for c in ('HINT_IN_ALBUM', 'HINT_NOT_YET', 'HINT_GONE'):
    assert 'Index.%s' % c in s2
assert '${this.groupMediaSig(g)}|${this.groupGoneSig(g)}' in s2
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000077' % (len(s_idx), len(s2)))
