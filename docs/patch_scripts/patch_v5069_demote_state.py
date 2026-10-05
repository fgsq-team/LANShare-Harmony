# -*- coding: utf-8 -*-
"""v5.0.69 —— 治「存相册成功后闪一下」：`chatMediaPaths` 降级为非 @State。

★★ 这次有**日志证据**，不是推断（5.0.68 诊断版实测，vivi 复现后 USB 取日志）。

日志（19:25:22 存相册前后紧邻两行）：
  存相册-前  mediaPaths=n=8 空=0   签名[c1-…jpg|rot0|gone0]×6  groups=1
  存相册-后  mediaPaths=n=8 空=8   签名[c1-…jpg|rot0|gone0]×6  groups=1
             ↑ src 签名**完全没变**、groups 也没变，只有 mediaPaths 变成**全空**

因果链（读代码 + 日志双向确认）：
  ① 存相册成功 → deleteFile() 删掉沙箱副本
  ② refreshReceivedInner() → receivedFiles **立即落地**（已不含这些文件）
  ③ syncChatMediaPaths() → recvPathFor() 在 receivedFiles 找不到、
     兜底查 recvIndex 也空 → **返回空串**
  ④ chatMediaPaths 从 8 条有效路径变成 8 条**空串** ⇒ 换 @State 引用
     ⇒ **全组件重渲染 ⇒ 闪**

★★★ 决定性发现：**`chatMediaPaths` 在 UI 里一个读取点都没有。**
  穷举全部引用（grep 全文件）后确认，只有：
    - `:3432/:3435` 它**自己**的签名比较
    - `:3462` 它自己的赋值
    - `:3304/:3307` 5.0.68 的诊断日志
  真正给画廊用的是 `chatMediaGroups`（`mediaPathsOf` → `:2917`）。
  而气泡缩略图从 5.0.61 起走 `mediaThumbSrcOf()` → 读**相册索引**，也不用它。
  ⇒ 它是一张**没有消费者的 @State**：内容变了没人看，但换引用照样触发全组件重绘。

修法：降级为**普通字段**（去掉 `@State`）。
  ⚠️ 它的签名比较逻辑只依赖普通 Map 的读（`.size` / `.get`），不依赖可观察性 ⇒ 逻辑不变。
  ⚠️ 它**没有 UI 消费者** ⇒ 去掉 `@State` 不会有任何 UI 读不到东西的风险。
     （这是本改动成立的前提，改前必须重新 grep 确认）

顺带：`flushStateSwap` 里它的换引用也随之消失 ⇒ 存相册那次重渲染少一个来源。

⚠️ **诊断日志保留不删** —— 下次若还有残留闪，需要它继续定位。
   成本已验证可接受（存相册收尾才打，一行）。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.69' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5069pre'), (VER, 'app.json5.v5069pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：@State chatMediaPaths -> 普通字段（核心）
# =====================================================================
OLD1 = """  /** 每条消息 id -> 其「收到的图片/视频」沙箱路径；空串 = 无缩略图。见 syncChatMediaPaths */
  @State chatMediaPaths: Map<string, string> = new Map<string, string>();"""
NEW1 = """  /**
   * 每条消息 id -> 其「收到的图片/视频」沙箱路径；空串 = 无缩略图。见 syncChatMediaPaths
   *
   * ★★ 5.0.69：**从 `@State` 降级为普通字段**（有日志证据，不是推断）。
   *
   * 5.0.68 诊断日志（存相册前后紧邻两行）：
   *   前  mediaPaths=n=8 空=0
   *   后  mediaPaths=n=8 **空=8**   ← 而 src 签名与 groups **完全没变**
   * 成因：存相册删掉沙箱副本 ⇒ recvPathFor 找不到 ⇒ 全部返回空串 ⇒ 换引用 ⇒ 闪。
   *
   * ⚠️ 降级的前提（本改动成立的全部依据）：
   *   **这张表在 UI 里一个读取点都没有**。穷举全文件引用后确认，只有
   *     - `syncChatMediaPaths` **自己**的签名比较（`.size` / `.get`）
   *     - 它自己的赋值
   *     - 5.0.68 的诊断日志
   *   真正给画廊用的是 `chatMediaGroups`（`mediaPathsOf`）；气泡缩略图从 5.0.61
   *   起走 `mediaThumbSrcOf()` 读相册索引，也不用它。
   *   ⇒ 它是一张**没有消费者的 @State**：内容变了没人看，
   *     但换引用照样触发**全组件重绘** —— 纯浪费，正是闪烁来源。
   *   ⇒ 去掉 `@State` 后 UI 读不到任何东西，行为零变化。
   *
   * ⚠️ 改前若新增了 UI 读取点，**必须把它改回 @State**，否则界面会停在旧值
   *   （普通字段的写不会触发重绘）—— 这是本改动唯一的维护成本。
   * ⚠️ 签名比较逻辑只依赖普通 Map 的读，不依赖可观察性 ⇒ 逻辑完全不变。
   */
  private chatMediaPaths: Map<string, string> = new Map<string, string>();"""

# =====================================================================
# 改 2：flushStateSwap 里不再换 chatMediaPaths（降级后不需要通知）
# =====================================================================
OLD2 = """    // ★★ 5.0.68（诊断）：逐项记录「换了哪些」，让下一次复现能一锤定音。
    const swP: boolean = this.chatMediaPathsNext !== null;
    const swG: boolean = this.chatMediaGroupsNext !== null;
    const swC: boolean = this.chatGroupsNext !== null;
    const swA: boolean = this.albumIndexNext !== null;
    if (swP) {
      this.chatMediaPaths = this.chatMediaPathsNext as Map<string, string>;
      this.chatMediaPathsNext = null;
    }"""
NEW2 = """    // ★★ 5.0.68（诊断）：逐项记录「换了哪些」，让下一次复现能一锤定音。
    // ⚠️ 5.0.69：`chatMediaPaths` 已降级为普通字段 ⇒ **不需要通知**，
    //   缓冲里那份直接落地即可（换引用不再触发重绘）。
    if (this.chatMediaPathsNext !== null) {
      this.chatMediaPaths = this.chatMediaPathsNext as Map<string, string>;
      this.chatMediaPathsNext = null;
    }
    const swP: boolean = false;   // 5.0.69：不再触发 UI，诊断口径固定为 N
    const swG: boolean = this.chatMediaGroupsNext !== null;
    const swC: boolean = this.chatGroupsNext !== null;
    const swA: boolean = this.albumIndexNext !== null;"""

# =====================================================================
# 改 3：chatPathsNext2 去掉闸门分支（普通字段直接落地）
# =====================================================================
OLD3 = """  /** ★ 5.0.64：`chatMediaPaths` 换引用（经闸门） */
  private chatPathsNext2(v: Map<string, string>): void {
    if (this.stateSwapDepth > 0) {
      this.chatMediaPathsNext = v;
      return;
    }
    this.chatMediaPaths = v;
  }"""
NEW3 = """  /**
   * ★ 5.0.69：`chatMediaPaths` 落地（**已降级为普通字段，不再走闸门**）。
   *
   * 5.0.64 时它是 @State，所以要经闸门合并、并在 flush 里换引用。
   * 5.0.69 去掉 @State 后，换引用不再触发重绘 ⇒ **闸门对它失去意义**，
   * 直接落地即可（保留这个方法名与调用点，避免牵动 syncChatMediaPaths 的结构）。
   */
  private chatPathsNext2(v: Map<string, string>): void {
    this.chatMediaPaths = v;
  }"""

OLD4 = '"versionCode": 5000068'
NEW4 = '"versionCode": 5000069'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 降级为普通字段'),
                      (OLD2, NEW2, '改2 flush 不再通知'),
                      (OLD3, NEW3, '改3 落地不经闸门')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD4) == 1
v2 = v2.replace(OLD4, NEW4, 1)
assert v2.count('"versionName": "5.0.68"') == 1
v2 = v2.replace('"versionName": "5.0.68"', '"versionName": "5.0.69"', 1)

# ---- 不变量 ----
_code = '\n'.join(l for l in s2.split('\n')
                  if not l.strip().startswith('//')
                  and not l.strip().startswith('*')
                  and not l.strip().startswith('/*'))
assert '@State chatMediaPaths' not in _code, 'chatMediaPaths 仍是 @State'
assert 'private chatMediaPaths: Map<string, string>' in _code
# UI 零读取这条前提必须仍然成立（若将来有人加了读取点，这句会提醒改回）
assert s2.count('this.chatMediaPaths.get(') == 2, s2.count('this.chatMediaPaths.get(')   # 签名比较 + 诊断日志
assert s2.count('this.chatMediaPaths.size') == 2, s2.count('this.chatMediaPaths.size')   # 签名比较 + 诊断日志
assert s2.count('this.chatMediaPaths = v;') == 1, 'chatPathsNext2 应直接落地'
# 诊断日志必须保留
assert '5.0.68诊断' in s2
# 前几轮的修复必须仍在
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')
assert 'this.chat = v;' in s2
assert 'receivedFilesNext' not in _code
# 画廊那张表仍是 @State（它有真消费者）
assert '@State chatMediaGroups' in s2
assert '@State chatGroups' in s2

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000069' % (len(s_idx), len(s2)))
