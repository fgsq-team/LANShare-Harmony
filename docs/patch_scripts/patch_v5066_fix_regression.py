# -*- coding: utf-8 -*-
"""v5.0.66 —— 紧急修 5.0.65 的回归（vivi：存相册功能整个没了 + 新消息不进消息页）。

★ 根因（读代码确认，非推测）：
   5.0.65 把 `chat` 也塞进了换引用闸门（`chatNext`），但——

   **闸门只该缓冲「通知」，绝不能缓冲「同一条链上其它代码要读的值」。**

   5.0.65 的闸门段里有三个方法读 `this.chat`：
     ① `syncChatMediaPaths()`  —— 遍历 this.chat 建媒体路径表
     ② `buildChatGroups()`     —— 遍历 this.chat 建气泡分组
     ③ `autoSaveNewMedia(oldCount)` —— **第一行就是
        `if (oldCount >= this.chat.length) return;`**
   而 `chat` 此时还躺在 `chatNext` 里没落地 ⇒ `this.chat` 仍是**旧数组** ⇒：
     - ③ 直接 return ⇒ **自动存相册整个不执行**（vivi 症状 1：存相册功能没了）
     - ①② 遍历旧数组 ⇒ 新消息的路径/分组都没建 ⇒ **消息页不显示**
       （vivi 症状 2：切一下 TAB 才出来 —— 切 TAB 触发新一轮 refresh 才补上）

   ⇒ 同一个原因造成两个症状。这就是「**闸门上提」做过头**。

修法：**`chat` 立即落地，不进缓冲**。
   它是「数据源」，闸门要合并的是「派生表 + albumIndex」这些**通知型**状态。
   `chat` 本来就只换一次引用，多一次重渲染可接受；换来的是数据正确性。

同时把 5.0.65 里另外两个**同类隐患**一并修掉（它们是同一个错误模式）：
   - `receivedFiles` 也不能缓冲：`rebuildRecvIndex` / `syncChatMediaPaths`
     都要读它 ⇒ 同样读到旧值。★ 实际上 5.0.64 就已经有这个隐患了，
     只是当时「条数变了」分支还在闸门外，恰好掩盖了它。
   - `chatMediaPaths` / `chatGroups` 本身是**派生表**，只在 flush 里落地，
     而它们的**计算**读的是立即落地的 `chat`/`receivedFiles` ⇒ 安全，保留。

⚠️ 判据（写进注释）：
   「进缓冲」的前提 = 这个值**只给 UI 读**、**没有别的代码在同一条链上读它**。
   一旦有别的代码读它 ⇒ 必须立即落地。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.66' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5066pre'), (VER, 'app.json5.v5066pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：swapChat —— 立即落地（核心修复）
# =====================================================================
OLD1 = """  private swapChat(v: ChatMessage[]): void {
    if (this.stateSwapDepth > 0) {
      this.chatNext = v;
      return;
    }
    this.chat = v;
  }"""
NEW1 = """  private swapChat(v: ChatMessage[]): void {
    // ★★★ 5.0.66：**这里必须立即落地，不能进闸门缓冲。**
    //
    // 5.0.65 的回归根因：`chat` 进了 `chatNext`，于是闸门段里
    //   syncChatMediaPaths() / buildChatGroups() / autoSaveNewMedia()
    // 这三个方法读到的 `this.chat` 仍是**旧数组** ——
    //   - autoSaveNewMedia 第一行 `if (oldCount >= this.chat.length) return;`
    //     直接 return ⇒ **自动存相册整个不执行**；
    //   - 另两个遍历旧数组 ⇒ 新消息的路径/分组没建 ⇒ **消息页不显示**
    //     （切 TAB 触发新一轮 refresh 才补上，故 vivi 看到「要切一下才对」）。
    //
    // ⚠️ 闸门缓冲的前提是这个值「**只给 UI 读**、没有别的代码在同一条链上读它」。
    //   一旦有别的代码读它，就必须立即落地 —— 它是**数据源**，不是通知。
    //   闸门该合并的是**派生表**（chatMediaPaths/chatGroups/...）这类通知型状态。
    this.chat = v;
  }"""

# =====================================================================
# 改 2：receivedFiles 同样立即落地（5.0.64 起就有的隐患）
# =====================================================================
OLD2 = """    if (this.stateSwapDepth > 0) {
      this.receivedFilesNext = list;
    } else {
      this.receivedFiles = list;
    }"""
NEW2 = """    // ⚠️ 5.0.66：同理**必须立即落地**。`rebuildRecvIndex(list)` 与
    //   `syncChatMediaPaths()` 都要读 `this.receivedFiles`（经 recvPathFor），
    //   进缓冲就会让它们读到旧列表 ⇒ 路径解析不出来。5.0.64 引入闸门时就带着
    //   这个隐患，只是当时「条数变了」分支恰好在闸门外把它掩盖了。
    this.receivedFiles = list;"""

# =====================================================================
# 改 3：flushStateSwap 里删掉 chat / receivedFiles 的落地（已不用）
# =====================================================================
OLD3 = """    if (this.receivedFilesNext !== null) {
      this.receivedFiles = this.receivedFilesNext;
      this.receivedFilesNext = null;
    }
"""
NEW3 = """    // ⚠️ 5.0.66：`receivedFiles` 与 `chat` 改为**立即落地**（见 swapChat 的注释），
    //   这里不再需要它们的缓冲字段。
"""

OLD4 = """    if (this.chatNext !== null) {
      this.chat = this.chatNext;
      this.chatNext = null;
    }
  }"""
NEW4 = """  }"""

# =====================================================================
# 改 4：删掉两个不再使用的缓冲字段
# =====================================================================
OLD5 = """  private receivedFilesNext: ReceivedFile[] | null = null;
  private chatMediaPathsNext: Map<string, string> | null = null;"""
NEW5 = """  private chatMediaPathsNext: Map<string, string> | null = null;"""

OLD6 = """  private albumIndexNext: Map<string, string> | null = null;
  private chatNext: ChatMessage[] | null = null;
"""
NEW6 = """  private albumIndexNext: Map<string, string> | null = null;
"""

# =====================================================================
# 组装 + 全量校验
# =====================================================================
s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 swapChat 立即落地'),
                      (OLD2, NEW2, '改2 receivedFiles 立即落地'),
                      (OLD3, NEW3, '改3 flush 删 receivedFiles'),
                      (OLD4, NEW4, '改4 flush 删 chat'),
                      (OLD5, NEW5, '改5 删字段 receivedFilesNext'),
                      (OLD6, NEW6, '改6 删字段 chatNext')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count('"versionCode": 5000065') == 1
v2 = v2.replace('"versionCode": 5000065', '"versionCode": 5000066', 1)
assert v2.count('"versionName": "5.0.65"') == 1
v2 = v2.replace('"versionName": "5.0.65"', '"versionName": "5.0.66"', 1)

# ---- 关键不变量：缓冲字段必须彻底消失（只看代码行，排除注释里的字样） ----
_code = '\n'.join(l for l in s2.split('\n') if not l.strip().startswith('//'))
_code = '\n'.join(l for l in _code.split('\n') if not l.strip().startswith('*')
                  and not l.strip().startswith('/*'))
assert 'chatNext' not in _code, 'chatNext 仍有代码残留'
assert 'receivedFilesNext' not in _code, 'receivedFilesNext 仍有代码残留'
# 立即落地必须就位
assert s2.count('    this.chat = v;\n  }') == 1, 'swapChat 未立即落地'
assert s2.count('    this.receivedFiles = list;') == 1, 'receivedFiles 未立即落地'
# autoSaveNewMedia 的守卫必须还在（它是症状 1 的判据）
assert 'if (oldCount >= this.chat.length) {' in s2, 'autoSaveNewMedia 守卫被动过'
# 派生表仍走缓冲（这部分 5.0.64 已验证有效，保留）
assert s2.count('if (this.chatMediaPathsNext !== null) {') == 1
assert s2.count('if (this.chatGroupsNext !== null) {') == 1
assert s2.count('if (this.chatMediaGroupsNext !== null) {') == 1
assert s2.count('if (this.albumIndexNext !== null) {') == 1
# 闸门开合仍是 4 对
assert s2.count('this.beginStateSwap();') == 4
assert s2.count('this.endStateSwap();') == 4

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000066' % (len(s_idx), len(s2)))
