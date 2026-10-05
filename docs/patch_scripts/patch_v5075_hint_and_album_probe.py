# -*- coding: utf-8 -*-
"""v5.0.75 —— ①「已存入相册」提示不出现 ②切到消息 tab 主动检查相册资产是否被删。

【① 文案定稿（vivi 20:19）】
    已存 → `N 张 · 已存入相册，点击查看`
    未存 → `N 张 · 长按保存到相册，点击查看`
⚠️ 仍补半角空格保持等宽（5.0.70 的规矩）。

【① 根因：判据用错了对象，不是 key 没接上】
外层 key 5.0.72 已加了「已存入」维度（`groupGoneSig` 第 2 项），接得好好的。
但**文案**那行传的是 `bubbleHintOf(g.msgs[0], '')` —— 只看**第 1 张**。
存相册是**逐张**进行的（`autoSaveAlbumBatch` 循环里一张一张 `setAlbumIndex`），
**很可能第 3 张、第 7 张先存上而 `msgs[0]` 还没存** ⇒ 判据恒为「未存」。
⚠️ 与「已删」角标必须**逐张**判定（`mediaGoneFromAlbum(m, k)`）同理，
   我却在文案上偷懒只看 `msgs[0]`。
修法：新增 `bubbleHintOfGroup(g)` —— **整组任一张已存即算已存**。

【② 新功能：切到消息 tab 时主动检查相册资产是否被删】
vivi 20:21：「每次切换到消息 tab，检查一下已经接收的图片是否删除」。

现状：探测**只在点击气泡时**才做（`onFileBubbleClick` → `albumAssetAlive`，
被动、且只查被点的那一张）。用户看不到「已删」提示，直到点它才弹toast。

修法：在 `.onChange` 的 `index === 1`（消息 tab）分支里加一次**全量扫描**：
遍历 `albumIndex` 里所有 key，对每个有 uri 的做 `albumAssetAlive` 探测，
死掉的 `clearAlbumUri(key)`（**只清 uri、保留缩略图** —— 气泡还能显示小图）。

⚠️ **复用既有三信号探测**（`albumAssetAlive`，5.0.51 写的）：
   `stat(size>0)` → 只读打开真读几字节 → ……
   ⚠️ **不新造轮子**：那套判据是踩过坑定下来的（写打开**证伪**、
   stat/读打开可能一律失败），换一套必然退化。
⚠️ **节流**：同一 id 刚清过就跳过（`albumClearedIds`），
   避免每次切 tab 都对同一批死 uri 重复探测。
⚠️ **不在渲染路径上调用**：只在 `onChange`（用户动作）里跑，且
   `albumAssetAlive` 是**同步 IO** —— 故先让出一拍再逐个探（5.0.63 的
   `prefetchThumbInner` 同样处理过：同步 IO 挤在 build 里会掉帧）。
⚠️ 探测**只清索引、不删缓存小图**（`clearAlbumUri` 内已保证）——
   用户在系统相册删了图，我们自己的 320px 缓存还要留着显示，
   否则气泡会变成空白（那是 5.0.52~5.0.56 折腾很久才稳定下来的行为）。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.75' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5075pre'), (VER, 'app.json5.v5075pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：文案定稿
# =====================================================================
OLD1 = """    const inAlbum: string = '已存入相册，点击查看';
    const notYet: string = '点击查看';"""
NEW1 = """    // ★ 5.0.75（vivi 20:19 定稿）：未存那句补上「长按」——
    //   用户是**长按**存相册的，文案要如实反映操作方式。
    const inAlbum: string = '已存入相册，点击查看';
    const notYet: string = '长按保存到相册，点击查看';"""

# =====================================================================
# 改 2：新增「整组任一张已存即算已存」判据
# =====================================================================
OLD2 = """  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {"""
NEW2 = """  /**
   * ★ 5.0.75：宫格气泡用的提示文案 —— 判据是「**整组任一张已存入相册**」。
   *
   * 【为什么不能用 `bubbleHintOf(g.msgs[0])`】（5.0.75 修的真 bug）
   *   存相册是**逐张**进行的（`autoSaveAlbumBatch` 循环里一张一张 `setAlbumIndex`），
   *   **很可能第 3 张、第 7 张先被存上，而 `msgs[0]` 那一批还没存**
   *   ⇒ 只看第 1 张，判据恒为「未存」⇒ 文案永远停在「点击查看」，
   *   用户反馈「已存入相册也没有」就是这个。
   *   ⚠️ 与「已删」角标必须**逐张**判定（`mediaGoneFromAlbum(m, k)`）同理，
   *   我却在文案上偷懒只看 `msgs[0]`。
   */
  private bubbleHintOfGroup(g: ChatGroup): string {
    const inAlbum: string = '已存入相册，点击查看';
    const notYet: string = '长按保存到相册，点击查看';
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.albumPartOf(g.msgs[i].id, 0, 0).length > 0) {
        return inAlbum;
      }
    }
    // ⚠️ 等宽补齐：与 `bubbleHintOf` 同一套口径（5.0.70 的规矩）
    const gap: number = inAlbum.length - notYet.length;
    return gap > 0 ? `${notYet}${' '.repeat(gap)}` : notYet;
  }

  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {"""

# =====================================================================
# 改 3：宫格那行改调 bubbleHintOfGroup
# =====================================================================
OLD3 = """          Text(`${g.msgs.length} 张 · ${this.bubbleHintOf(g.msgs[0], '')}`)"""
NEW3 = """          // ★ 5.0.75：改用「整组任一张已存」判据（原先只看 `g.msgs[0]`，见方法注释）
          Text(`${g.msgs.length} 张 · ${this.bubbleHintOfGroup(g)}`)"""

# =====================================================================
# 改 4：新增「切消息 tab 时全量探测相册资产」
# =====================================================================
OLD4 = """        .onChange((index: number) => {
          this.curTab = index;
          this.lastChatCount = this.snapshot.chat.length;
          if (index === 1) {
            try {
              this.chatScroller.scrollEdge(Edge.Bottom);
            } catch (e) {
              // 列表还没挂载，忽略
            }
          }"""
NEW4 = """        .onChange((index: number) => {
          this.curTab = index;
          this.lastChatCount = this.snapshot.chat.length;
          if (index === 1) {
            try {
              this.chatScroller.scrollEdge(Edge.Bottom);
            } catch (e) {
              // 列表还没挂载，忽略
            }
            // ★ 5.0.75（vivi 20:21 新功能）：切到消息 tab 时**主动**全量探一次
            //   「相册里的图还在不在」—— 用户可能在系统相册里删了图，
            //   而此前**只有点击气泡时**才被动探测（`onFileBubbleClick`），
            //   用户看不到提示，直到点它才弹 toast。
            this.probeAlbumOnEnterChat();
          }"""

# =====================================================================
# 改 5：新增探测方法（插在 albumAssetAlive 之前）
# =====================================================================
OLD5 = """  private albumAssetAlive(uri: string): boolean {"""
NEW5 = """  /**
   * ★ 5.0.75（vivi 20:21）：切到消息 tab 时**全量**探一次「相册资产还在不在」。
   *
   * 【为什么需要】`albumAssetAlive` 的三信号探测（5.0.51 定的）此前**只在
   *   点击气泡时**跑（`onFileBubbleClick`），是被动的、且只查被点的那一张。
   *   用户在系统相册里删了图，气泡上**没有任何提示**，只有点它才弹
   *   「该文件已从相册删除」⇒ 体验上像是「列表没刷新」。
   *
   * 【做法】遍历 `albumIndex` 所有 key，对**有 uri** 的逐个探，
   *   死掉的 `clearAlbumUri(key)`（**只清 uri、保留缩略图**）。
   *
   * ⚠️ **必须复用 `albumAssetAlive`，不新造判据**：那套三信号
   *   （stat size>0 → 只读打开真读几字节）是踩过坑定下来的 ——
   *   **写打开只能证伪**、stat/读打开可能**一律失败**（≠ 不存在）。
   *   换一套必然退化成「全部判为已删」或「永远判为还在」。
   * ⚠️ **同步 IO 必须让帧**：`albumAssetAlive` 是 `statSync`/`openSync`/`readSync`，
   *   一批几十张会把主线程占住 ⇒ 先 `yieldOnce()` 再逐个探。
   * ⚠️ **节流**：`albumClearedIds` 记住刚清过的 id，同一轮不重复探 ——
   *   否则每次切 tab 都对同一批死 uri 重做一遍同步 IO。
   * ⚠️ **只清索引、不删缓存小图**：用户删的是**系统相册**里那份，
   *   我们自己的 320px 缓存还要留着显示，否则气泡会变空白
   *   （那是 5.0.52~5.0.56 折腾很久才稳定下来的行为）。
   * ⚠️ 全程 try/catch：探测失败**绝不能**影响切 tab。
   */
  private async probeAlbumOnEnterChat(): Promise<void> {
    try {
      await Index.yieldOnce();
      let checked: number = 0;
      const dead: string[] = [];
      for (const key of this.albumIndex.keys()) {
        // key 形如 `消息id#序号`；只看 part 0（相册 uri）
        const uri: string = this.albumPart(key, 0);
        if (uri.length === 0 || this.albumClearedIds.has(key)) {
          continue;
        }
        checked += 1;
        if (!this.albumAssetAlive(uri)) {
          dead.push(key);
        }
      }
      if (dead.length === 0) {
        this.service.logAuto(`[切消息页] 相册资产全量探测：${checked} 条，未发现被删`);
        return;
      }
      this.beginStateSwap();
      try {
        for (let i: number = 0; i < dead.length; i++) {
          this.service.clearAlbumUri(dead[i]);
          this.albumClearedIds.add(dead[i]);
          Log.i(TAG, `切消息页探测：相册资产已不存在，摘掉失效 URI：${dead[i]}`);
        }
        this.swapAlbumIndex();
      } finally {
        this.endStateSwap();
      }
      this.service.logAuto(`[切消息页] 相册资产探测：${checked} 条，`
        + `发现 ${dead.length} 条已被用户从相册删除（角标会更新）`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      // ⚠️ 探测失败**绝不能**影响切 tab，只记日志
      this.service.logAuto(`切消息页相册探测异常（已忽略）：${err.code} ${err.message}`);
    }
  }

  private albumAssetAlive(uri: string): boolean {"""

# =====================================================================
# 改 6：节流集合字段
# =====================================================================
OLD6 = """  private albumIndexNext: Map<string, string> | null = null;"""
NEW6 = """  private albumIndexNext: Map<string, string> | null = null;
  // ★ 5.0.75：切消息页探测时**刚清过**的相册 key，避免每次切 tab 重复做同步 IO
  private albumClearedIds: Set<string> = new Set<string>();"""

OLD7 = '"versionCode": 5000074'
NEW7 = '"versionCode": 5000075'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 文案定稿'),
                      (OLD2, NEW2, '改2 整组判据'),
                      (OLD3, NEW3, '改3 宫格改调'),
                      (OLD4, NEW4, '改4 切tab挂钩'),
                      (OLD5, NEW5, '改5 探测方法'),
                      (OLD6, NEW6, '改6 节流字段')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD7) == 1
v2 = v2.replace(OLD7, NEW7, 1)
assert v2.count('"versionName": "5.0.74"') == 1
v2 = v2.replace('"versionName": "5.0.74"', '"versionName": "5.0.75"', 1)

# ---- 不变量 ----
assert s2.count('private bubbleHintOfGroup(g: ChatGroup): string {') == 1
assert s2.count('this.bubbleHintOfGroup(g)') == 1
assert s2.count("const notYet: string = '长按保存到相册，点击查看';") == 2
assert s2.count("const inAlbum: string = '已存入相册，点击查看';") == 2
assert s2.count("' '.repeat(gap)") == 2, s2.count("' '.repeat(gap)")
# 新功能
assert s2.count('private async probeAlbumOnEnterChat(): Promise<void> {') == 1
assert s2.count('this.probeAlbumOnEnterChat();') == 1
assert s2.count('private albumClearedIds: Set<string> = new Set<string>();') == 1
# 必须复用既有三信号探测，不新造
assert s2.count('if (!this.albumAssetAlive(uri)) {') == 1
# 只清 uri 不删缩略图
assert s2.count('this.service.clearAlbumUri(dead[i]);') == 1
# 前几轮修复仍在
assert 'this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)' in s2
assert 'this.mediaFitOf(fixedSquare)' in s2
assert '${this.groupMediaSig(g)}|${this.groupGoneSig(g)}' in s2
assert 's += this.albumPartOf(g.msgs[i].id, 0, 0).length > 0 ? \'1\' : \'0\';' in s2
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')
# 单张那处仍用 bubbleHintOf
assert '`${this.bubbleCountText(m)} · ${this.bubbleHintOf(m, mediaPath)}`' in s2

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000075' % (len(s_idx), len(s2)))
