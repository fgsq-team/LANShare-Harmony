# -*- coding: utf-8 -*-
"""v5.0.64 —— 优化点 A：把「一次操作换 N 次 @State 引用」压成 1 次。

vivi 2026-10-02 反馈 v5.0.63 后「大概会闪 2 次」。读代码定位剩余的来源：

  ArkTS 的 @State **每次换引用都会触发一次独立重渲染**，连续赋值**不会**自动合并。
  存相册这一条链路上一次操作换了 4 个 @State 引用：
    ① albumIndex      （autoSaveAlbumBatch 结尾，存相册记账）
    ② receivedFiles   （refreshReceived 内，refreshReceived 开头）
    ③ chatMediaPaths  （syncChatMediaPaths，沙箱副本被删 => 路径必然变）
    ④ chatGroups / chatMediaGroups（靠签名守住，通常不变）
  ⇒ 4 次重渲染 ⇒ 观感就是「闪几下」。

修法：**先算完全部新值，最后统一换引用**（沿用本文件既有的「签名没变就不换引用」手法，
5.0.33 引入、5.0.63 沿用）。不改变任何数据语义，只改「什么时候通知 UI」。

⚠️ 为什么不能靠「干脆别换引用」来消闪：数据真的变了（沙箱副本已删、缩略图已存），
   不换引用 = 界面不更新。只能**把 4 次合并成 1 次**。

⚠️ 为什么 `receivedFiles` 也在合并范围内：它在这条链路上几乎必然要换（文件列表真变了），
   但把它的赋值挪到**最后**，就能让它和 ①②③ 落在同一次重渲染里。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.64' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5064pre'), (VER, 'app.json5.v5064pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：refreshReceived —— 引入「延迟换引用」闸门
# =====================================================================
OLD1 = """  private refreshReceived(): void {
    const list: ReceivedFile[] = ExportService.listReceived(this.service.receiveRoot);
    this.receivedFiles = list;
    // 消息页的图片缩略图靠它把「文件名」翻回「沙箱路径」（保留：气泡长按存图仍要用）
    this.rebuildRecvIndex(list);"""
NEW1 = """  /**
   * ★ 5.0.64：一次刷新里的**换引用闸门**。
   *
   * ArkTS 的 `@State` 每换一次引用就触发一次独立重渲染，**连续赋值不会合并**。
   * 存相册那条链路上一次操作要换 4 个（albumIndex / receivedFiles /
   * chatMediaPaths / chatGroups）⇒ 4 次重渲染 ⇒ 观感是「闪几下」。
   *
   * 做法：**先全部算完，最后统一换**。开关开着时，`syncChatMediaPaths` /
   * `buildChatGroups` / 存相册收尾都只把新值记到 xxxNext，**不碰 @State**；
   * 由 `flushStateSwap()` 在最末尾一次性换完 ⇒ 4 次重渲染变 1 次。
   *
   * ⚠️ 只改「什么时候通知 UI」，**不改变任何数据语义**。
   * ⚠️ 绝不能「干脆不换引用」来消闪 —— 数据真的变了（沙箱副本已删、缩略图已存），
   *    不换 = 界面不更新。只能合并，不能跳过。
   */
  private stateSwapDepth: number = 0;
  private receivedFilesNext: ReceivedFile[] | null = null;
  private chatMediaPathsNext: Map<string, string> | null = null;
  private chatMediaGroupsNext: Map<string, string[]> | null = null;
  private chatGroupsNext: ChatGroup[] | null = null;
  private albumIndexNext: Map<string, string> | null = null;

  /** 打开闸门（可重入 ⇒ 用计数器，不用 boolean） */
  private beginStateSwap(): void {
    this.stateSwapDepth += 1;
  }

  /** 关闭闸门；归零时统一换引用 */
  private endStateSwap(): void {
    if (this.stateSwapDepth > 0) {
      this.stateSwapDepth -= 1;
    }
    if (this.stateSwapDepth > 0) {
      return;
    }
    this.flushStateSwap();
  }

  /**
   * ★ 5.0.64：把闸门期间攒下的新值**一次性**交给 UI。
   *
   * 逐个「换引用」而不是整体替换，是为了让每一处原有的
   * 「内容没变就不换引用」判断继续有效（避免无谓重绘）。
   */
  private flushStateSwap(): void {
    if (this.receivedFilesNext !== null) {
      this.receivedFiles = this.receivedFilesNext;
      this.receivedFilesNext = null;
    }
    if (this.chatMediaPathsNext !== null) {
      this.chatMediaPaths = this.chatMediaPathsNext;
      this.chatMediaPathsNext = null;
    }
    if (this.chatMediaGroupsNext !== null) {
      this.chatMediaGroups = this.chatMediaGroupsNext;
      this.chatMediaGroupsNext = null;
    }
    if (this.chatGroupsNext !== null) {
      this.chatGroups = this.chatGroupsNext;
      this.chatGroupsNext = null;
    }
    if (this.albumIndexNext !== null) {
      this.albumIndex = this.albumIndexNext;
      this.albumIndexNext = null;
    }
  }

  /** `albumIndex` 的统一入口：闸门开着就记到缓冲，否则直接换 */
  private swapAlbumIndex(): void {
    const snap: Map<string, string> = this.service.albumSnapshot();
    if (this.stateSwapDepth > 0) {
      this.albumIndexNext = snap;
      return;
    }
    this.albumIndex = snap;
  }

  private refreshReceived(): void {
    this.beginStateSwap();
    this.refreshReceivedInner();
    this.endStateSwap();
  }

  /** ★ 5.0.64：原 `refreshReceived` 的真身，包在换引用闸门里跑 */
  private refreshReceivedInner(): void {
    const list: ReceivedFile[] = ExportService.listReceived(this.service.receiveRoot);
    if (this.stateSwapDepth > 0) {
      this.receivedFilesNext = list;
    } else {
      this.receivedFiles = list;
    }
    // 消息页的图片缩略图靠它把「文件名」翻回「沙箱路径」（保留：气泡长按存图仍要用）
    this.rebuildRecvIndex(list);"""

# =====================================================================
# 改 2：syncChatMediaPaths 尾部 —— 经闸门换引用
# =====================================================================
OLD2 = """    if (sig !== this.chatMediaGroupsSig) {
      this.chatMediaGroupsSig = sig;
      this.chatMediaGroups = g;
    }
    // 内容没变就不换引用，避免无谓重绘（文件页刷新很频繁）
    if (this.chatMediaPaths.size === m.size) {
      let same: boolean = true;
      for (const key of m.keys()) {
        if (this.chatMediaPaths.get(key) !== m.get(key)) {
          same = false;
          break;
        }
      }
      if (same) {
        return;
      }
    }
    this.chatMediaPaths = m;
  }"""
NEW2 = """    if (sig !== this.chatMediaGroupsSig) {
      this.chatMediaGroupsSig = sig;
      this.chatGroupNext2(g);
    }
    // 内容没变就不换引用，避免无谓重绘（文件页刷新很频繁）
    if (this.chatMediaPaths.size === m.size) {
      let same: boolean = true;
      for (const key of m.keys()) {
        if (this.chatMediaPaths.get(key) !== m.get(key)) {
          same = false;
          break;
        }
      }
      if (same) {
        return;
      }
    }
    this.chatPathsNext2(m);
  }

  /** ★ 5.0.64：`chatMediaGroups` 换引用（经闸门） */
  private chatGroupNext2(v: Map<string, string[]>): void {
    if (this.stateSwapDepth > 0) {
      this.chatMediaGroupsNext = v;
      return;
    }
    this.chatMediaGroups = v;
  }

  /** ★ 5.0.64：`chatMediaPaths` 换引用（经闸门） */
  private chatPathsNext2(v: Map<string, string>): void {
    if (this.stateSwapDepth > 0) {
      this.chatMediaPathsNext = v;
      return;
    }
    this.chatMediaPaths = v;
  }"""

# =====================================================================
# 改 3：buildChatGroups 尾部 —— 经闸门换引用
# =====================================================================
OLD3 = """    if (sig !== this.chatGroupsSig) {
      this.chatGroupsSig = sig;
      this.chatGroups = out;
    }
  }"""
NEW3 = """    if (sig !== this.chatGroupsSig) {
      this.chatGroupsSig = sig;
      if (this.stateSwapDepth > 0) {
        this.chatGroupsNext = out;
      } else {
        this.chatGroups = out;
      }
    }
  }"""

# =====================================================================
# 改 4：存相册收尾 —— albumIndex + refreshReceived 合进同一次重渲染
# =====================================================================
OLD4 = """      this.autoSavePending = rest;
      this.albumIndex = this.service.albumSnapshot();
      this.refreshReceived();
    }
  }"""
NEW4 = """      this.autoSavePending = rest;
      // ★ 5.0.64：整段包进换引用闸门 —— 原先这里是「换 albumIndex」+
      //   「refreshReceived 内部再换 receivedFiles/chatMediaPaths/chatGroups」
      //   = 一次操作 4 次重渲染（观感：闪几下）。现在合成 1 次。
      this.beginStateSwap();
      try {
        this.swapAlbumIndex();
        this.refreshReceivedInner();
      } finally {
        this.endStateSwap();
      }
    }
  }"""

# =====================================================================
# 改 5：自动存相册的另一处收尾（saveOneImageToAlbum 手动路径 :3335）
# =====================================================================
OLD5 = """      this.albumIndex = this.service.albumSnapshot();
      return true;"""
NEW5 = """      this.swapAlbumIndex();
      return true;"""

# =====================================================================
# 组装 + 全量校验
# =====================================================================
s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 闸门'), (OLD2, NEW2, '改2 mediaPaths'),
                      (OLD3, NEW3, '改3 chatGroups'), (OLD4, NEW4, '改4 存相册收尾'),
                      (OLD5, NEW5, '改5 手动存图')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count('"versionCode": 5000063') == 1
v2 = v2.replace('"versionCode": 5000063', '"versionCode": 5000064', 1)
assert v2.count('"versionName": "5.0.63"') == 1
v2 = v2.replace('"versionName": "5.0.63"', '"versionName": "5.0.64"', 1)

# 不变量校验
assert s2.count('private flushStateSwap()') == 1
assert s2.count('private beginStateSwap()') == 1
assert s2.count('private endStateSwap()') == 1
assert s2.count('private swapAlbumIndex(): void {') == 1   # 定义
assert s2.count('this.swapAlbumIndex();') == 2             # 改4 + 改5 两处调用
assert s2.count('private refreshReceivedInner(): void {') == 1
assert s2.count('this.refreshReceivedInner();') == 2       # 改1 包装 + 改4 收尾
assert s2.count('private chatPathsNext2(v: Map<string, string>): void {') == 1
assert s2.count('this.chatPathsNext2(m);') == 1
assert s2.count('private chatGroupNext2(v: Map<string, string[]>): void {') == 1
assert s2.count('this.chatGroupNext2(g);') == 1
# refreshReceived 里不能再有裸的 this.receivedFiles = list
assert 'this.receivedFiles = list;\n    // 消息页的图片缩略图' not in s2, '改1 未生效'
# 闸门内不得再有裸换 albumIndex
assert 'this.albumIndexNext = snap;' in s2
# 原有签名守卫仍在
assert s2.count('if (sig !== this.chatGroupsSig) {') == 1
assert s2.count('if (sig !== this.chatMediaGroupsSig) {') == 1
assert len(s2) > len(s_idx)

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000064' % (len(s_idx), len(s2)))
