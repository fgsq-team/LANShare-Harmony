# -*- coding: utf-8 -*-
"""v5.0.65 —— 把「换引用闸门」上提一层，罩住 onSnapshot 整个「条数变了」分支。

vivi 2026-10-02 反馈 5.0.64 后「还会闪一次」。

★ 先纠正上一轮（我自己的）判断错误：
   上一轮我以为是 `thumbTick`（优化点 B），但读代码发现 —— **消息页宫格根本不读比例**。
   `chatMediaGrid` 用 `mediaThumbFixed(path, GRID_SIDE)`（:5833），5.0.56 起就是
   **固定正方形**（为了「每行固定 3 个」），里面 `autoResize(true)` 也不需要预先知道比例。
   ⇒ `ratioOf`/`thumbW`/`thumbH` 只服务**文件页**，与消息页无关。**优化点 B 找错目标了。**

真实来源（读 onSnapshot 得出）：
   接收完成那一次 `onSnapshot` 回调里，**连续换了 5 个 @State**：
     ① tText / tPercent（进度浮层；传输由非空变空 ⇒ 两个都变）
     ② transferring
     ③ chat（条数变了 ⇒ slice 换引用）
     ④ chatMediaPaths（syncChatMediaPaths）
     ⑤ chatGroups（buildChatGroups）
   而 5.0.64 的闸门**只包住了 `refreshReceived` 内部**（即 ④⑤ 的一部分），
   ①②③ 以及「条数变了」分支里的 ④⑤ 仍在闸门**之外** ⇒ ArkTS 逐个触发重渲染。

修法：**闸门上提** —— 把 `if (s.chat.length !== this.lastChatCount)` 整个分支
     （含 chat / syncChatMediaPaths / buildChatGroups / autoSaveNewMedia / 滚到底）
     包进同一个闸门；并把 ①②③ 也纳入，即整段「传输结束 + 条数变化」共用一次落地。

⚠️ 为什么这次能真正合并：ArkTS 不会合并连续赋值，但**同一次 onSnapshot 回调
   内**的多次赋值如果都只是往缓冲写、最后一次 `flushStateSwap`，就只重渲染一次。
⚠️ `scrollEdge` 必须在**闸门关闭之后**调用 —— 它要在布局更新后再滚，
   放在闸门内会滚到旧布局位置。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.65' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5065pre'), (VER, 'app.json5.v5065pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：把「传输结束」判定 + 「条数变了」整段包进一个闸门
# =====================================================================
OLD1 = """    const wasTransfer: boolean = this.lastHadTransferText;
    this.lastHadTransferText = hadTransfer;
    if (wasTransfer && !hadTransfer) {
      this.refreshReceived();
    }
    // 聊天：只在条数真的变了时才 slice 一份新数组给 @State
    // （slice 换引用是让列表刷新的关键，见 chat 字段的注释）
    if (s.chat.length !== this.lastChatCount) {
      const oldCount: number = this.lastChatCount;
      this.lastChatCount = s.chat.length;
      this.chat = s.chat.slice();
      // 聊天条数变了 -> 重算每条消息的媒体路径（新收到的图/视频要能立刻出缩略图）
      this.syncChatMediaPaths();
      // ★ 5.0.55：条数变了也要重算「气泡分组」（同批的多条媒体要合成一个气泡）
      this.buildChatGroups();
      // 5.0.38：刚收到的图片/视频 -> 自动存相册（见 autoSaveNewMedia 注释）
      this.autoSaveNewMedia(oldCount);
      if (this.curTab === 1) {
        try {
          this.chatScroller.scrollEdge(Edge.Bottom);
        } catch (e) {
          // 列表还没挂载，忽略
        }
      }
    }"""
NEW1 = """    const wasTransfer: boolean = this.lastHadTransferText;
    this.lastHadTransferText = hadTransfer;
    // 聊天：只在条数真的变了时才 slice 一份新数组给 @State
    // （slice 换引用是让列表刷新的关键，见 chat 字段的注释）
    const chatCountChanged: boolean = s.chat.length !== this.lastChatCount;
    const oldCount: number = this.lastChatCount;
    // ★★ 5.0.65：闸门**上提到这里** —— 接收完成的这一次 onSnapshot 里，
    //   ①②（tText/tPercent 传输由非空变空）+ ③④⑤（chat / chatMediaPaths /
    //   chatGroups）**连续换了 5 个 @State**；5.0.64 的闸门只包住了
    //   `refreshReceived` 内部那部分，剩下这些仍在闸门之外 ⇒ 仍会重渲染多次。
    //   现在整段共用一次 `flushStateSwap()` ⇒ 一次重渲染。
    //   ⚠️ `lastChatCount` / `lastHadTransferText` 仍**立即**落值（它们是幂等标记，
    //   不是给 UI 看的；延迟落值会让下一次 emit 重复进这个分支）。
    let needScroll: boolean = false;
    this.beginStateSwap();
    try {
      if (wasTransfer && !hadTransfer) {
        this.refreshReceivedInner();
      }
      if (chatCountChanged) {
        this.lastChatCount = s.chat.length;
        this.swapChat(s.chat.slice());
        // 聊天条数变了 -> 重算每条消息的媒体路径（新收到的图/视频要能立刻出缩略图）
        this.syncChatMediaPaths();
        // ★ 5.0.55：条数变了也要重算「气泡分组」（同批的多条媒体要合成一个气泡）
        this.buildChatGroups();
        // 5.0.38：刚收到的图片/视频 -> 自动存相册（见 autoSaveNewMedia 注释）
        this.autoSaveNewMedia(oldCount);
        needScroll = this.curTab === 1;
      }
    } finally {
      this.endStateSwap();
    }
    // ⚠️ scrollEdge 必须在闸门**外**、也就是布局已更新之后再调 ——
    //   放在闸门内会滚到「旧布局」的位置（列表还没按新数据重排）。
    if (needScroll) {
      try {
        this.chatScroller.scrollEdge(Edge.Bottom);
      } catch (e) {
        // 列表还没挂载，忽略
      }
    }"""

# =====================================================================
# 改 2：tText / tPercent / transferring 也纳入闸门
# =====================================================================
OLD2 = """    if (s.transferText !== this.tText) {
      this.tText = s.transferText;
    }
    if (s.transferPercent !== this.tPercent) {
      this.tPercent = s.transferPercent;
    }
    // ---- 2. 设备列表：syncDeviceList 内部自带签名节流，成本极低 ----
    this.syncDeviceList();"""
NEW2 = """    // ★ 5.0.65：进度浮层的三个 @State 也走闸门 —— 传输**结束**时 tText 由非空
    //   变空、tPercent 归 0、transferring 变 false，三个一起变；加上下面
    //   「条数变了」那批，一次接收完成原本要触发 6~7 次重渲染。
    //   ⚠️ 进度在传输期间是 10Hz 刷的，那属于**正常**刷新（浮层本就该动），
    //   合并它们不影响观感；这里只求「一次结束动作只重渲染一次」。
    //   ⚠️ `hadTransfer` 必须在开闸**之前**算出来：它只读 s，不依赖任何 @State。
    const hadTransfer: boolean = s.transferText.length > 0;
    this.beginStateSwap();
    if (s.transferText !== this.tText) {
      this.tText = s.transferText;
    }
    if (s.transferPercent !== this.tPercent) {
      this.tPercent = s.transferPercent;
    }
    this.transferring = this.service.isTransferring;
    this.endStateSwap();
    // ---- 2. 设备列表：syncDeviceList 内部自带签名节流，成本极低 ----
    this.syncDeviceList();"""

# =====================================================================
# 改 3：新增 swapChat（chat 也走闸门）
# =====================================================================
OLD3 = """  /** `albumIndex` 的统一入口：闸门开着就记到缓冲，否则直接换 */"""
NEW3 = """  /**
   * ★ 5.0.65：`chat` 换引用的统一入口（经闸门）。
   *
   * ⚠️ 为什么要专门一个方法：`chat` 是在 `onSnapshot` 里换的，而 `onSnapshot`
   *   一次会换好几个 @State；闸门开着时只记缓冲，由 `flushStateSwap()` 一次落地。
   */
  private swapChat(v: ChatMessage[]): void {
    if (this.stateSwapDepth > 0) {
      this.chatNext = v;
      return;
    }
    this.chat = v;
  }

  /** `albumIndex` 的统一入口：闸门开着就记到缓冲，否则直接换 */"""

# =====================================================================
# 改 4：补 chatNext 字段 + flushStateSwap 里落地
# =====================================================================
OLD4 = """  private albumIndexNext: Map<string, string> | null = null;"""
NEW4 = """  private albumIndexNext: Map<string, string> | null = null;
  private chatNext: ChatMessage[] | null = null;"""

OLD5 = """    if (this.albumIndexNext !== null) {
      this.albumIndex = this.albumIndexNext;
      this.albumIndexNext = null;
    }
  }"""
NEW5 = """    if (this.albumIndexNext !== null) {
      this.albumIndex = this.albumIndexNext;
      this.albumIndexNext = null;
    }
    if (this.chatNext !== null) {
      this.chat = this.chatNext;
      this.chatNext = null;
    }
  }"""

OLD6 = '"versionCode": 5000064'
NEW6 = '"versionCode": 5000065'

# ---- 组装 + 全量校验 ----
s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 闸门上提'), (OLD2, NEW2, '改2 进度入闸门'),
                      (OLD3, NEW3, '改3 swapChat'), (OLD4, NEW4, '改4 chatNext 字段'),
                      (OLD5, NEW5, '改5 flush 落地')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD6) == 1
v2 = v2.replace(OLD6, NEW6, 1)
assert v2.count('"versionName": "5.0.64"') == 1
v2 = v2.replace('"versionName": "5.0.64"', '"versionName": "5.0.65"', 1)

# 不变量
assert s2.count('private swapChat(v: ChatMessage[]): void {') == 1
assert s2.count('this.swapChat(s.chat.slice());') == 1
assert s2.count('private chatNext: ChatMessage[] | null = null;') == 1
assert s2.count('if (this.chatNext !== null) {') == 1
# 闸门开合必须成对（改1 内 1 对 + 改2 内 1 对 + refreshReceived 包装 1 对 + 存相册 1 对）
assert s2.count('this.beginStateSwap();') == 4, s2.count('this.beginStateSwap();')
assert s2.count('this.endStateSwap();') == 4, s2.count('this.endStateSwap();')
# scrollEdge 必须已挪到闸门外
# scrollEdge 全文有 3 处（583 本次挪出闸门 / 745 / 6739），
# 只需保证 583 那处已挪到 `if (needScroll)` 之外
assert s2.count('this.chatScroller.scrollEdge(Edge.Bottom);') == 3
assert 'if (needScroll) {\n      try {\n        this.chatScroller.scrollEdge(Edge.Bottom);' in s2, 'scrollEdge 未挪到闸门外'
# 幂等标记仍立即落值
assert 'this.lastChatCount = s.chat.length;' in s2
assert 'this.lastHadTransferText = hadTransfer;' in s2
# refreshReceived 包装层仍在（11 处调用点依赖它）
assert s2.count('this.refreshReceivedInner();') == 3   # 改1 内 + 包装层 + 存相册收尾
assert len(s2) > len(s_idx)

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000065' % (len(s_idx), len(s2)))
