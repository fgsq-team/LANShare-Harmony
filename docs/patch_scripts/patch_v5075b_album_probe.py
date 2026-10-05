# -*- coding: utf-8 -*-
"""v5.0.75（补）—— 新功能②：切到消息 tab 时**全量**探测相册资产是否被删。

vivi 2026-10-02 20:21：「每次切换到消息 tab，检查一下已经接收的图片是否删除」。

⚠️ 本脚本**只做新功能②**。同一版的①（文案定稿 + 整组判据 + 宫格改调）
**已在上一轮落盘并通过编译**（5.0.75 的 HAP 因构建被打断未产出，本轮一起出）。

【为什么需要这个功能】
`albumAssetAlive` 的三信号探测（5.0.51 定的）此前**只在点击气泡时**跑
（`onFileBubbleClick`）—— 被动的、且**只查被点的那一张**。
用户在系统相册里删了图，气泡上**没有任何提示**，只有点它才弹
「该文件已从相册删除」⇒ 体验上像是「列表没刷新」。

【做法】在 Tabs 的 `.onChange` 里，`index === 1`（消息 tab）分支加一次全量扫描：
遍历 `albumIndex` 所有 key，对**有 uri** 的逐个探 `albumAssetAlive`，
死掉的 `clearAlbumUri(key)`。

⚠️ **必须复用 `albumAssetAlive`，不新造判据**：那套三信号
   （stat size>0 → 只读打开真读几字节）是踩过坑定下来的 ——
   **写打开只能证伪**、stat/读打开可能**一律失败**（≠ 不存在，5.0.52 定案）。
   换一套必然退化成「全判为已删」或「永远判为还在」。
⚠️ **同步 IO 必须让帧**：`albumAssetAlive` 是 `statSync`/`openSync`/`readSync`，
   一批几十张会把主线程占住掉帧 ⇒ 先 `yieldOnce()` 再逐个探
   （与 5.0.63 的 `prefetchThumbInner` 同样处理过：同步 IO 挤在 build 里会掉帧）。
⚠️ **节流**：`albumClearedIds` 记住刚清过的 id ⇒ 同一批死 uri 不重复探，
   否则每次切 tab 都重做一遍同步 IO。
⚠️ **只清索引、不删缓存小图**：用户删的是**系统相册**里那份，我们自己的
   320px 缓存还要留着显示，否则气泡变空白
   （那是 5.0.52~5.0.56 折腾很久才稳定下来的行为）。
⚠️ 全程 try/catch：探测失败**绝不能**影响切 tab。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')

s_idx = io.open(IDX, encoding='utf-8').read()
if 'probeAlbumOnEnterChat' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
io.open(os.path.join(BK, 'Index.ets.v5075probepre'), 'w', encoding='utf-8', newline='\n')\
  .write(s_idx)
print('备份完成')

# ---------------------------------------------------------------- 改 1：切 tab 挂钩
OLD1 = """        .onChange((index: number) => {
          this.curTab = index;
          this.lastChatCount = this.snapshot.chat.length;
          if (index === 1) {
            try {
              this.chatScroller.scrollEdge(Edge.Bottom);
            } catch (e) {
              // 列表还没挂载，忽略
            }
          }"""
NEW1 = """        .onChange((index: number) => {
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
            //   用户看不到任何提示，只有点它才弹 toast。
            this.probeAlbumOnEnterChat();
          }"""

# ---------------------------------------------------------------- 改 2：探测方法
OLD2 = """  private albumAssetAlive(uri: string): boolean {"""
NEW2 = """  /**
   * ★ 5.0.75（vivi 20:21）：切到消息 tab 时**全量**探一次「相册资产还在不在」。
   *
   * 【为什么需要】`albumAssetAlive` 的三信号探测（5.0.51 定的）此前**只在
   *   点击气泡时**跑（`onFileBubbleClick`），是被动的、且只查被点的那一张。
   *   用户在系统相册里删了图，气泡上**没有任何提示**，只有点它才弹
   *   「该文件已从相册删除」⇒ 体验上像是「列表没刷新」。
   *
   * 【做法】遍历 `albumIndex` 所有 key，对**有 uri** 的逐个探，死掉的
   *   `clearAlbumUri(key)`（**只清 uri、保留缩略图** —— 气泡还能显示小图）。
   *
   * ⚠️ **必须复用 `albumAssetAlive`，不新造判据**：那套三信号
   *   （stat size>0 → 只读打开真读几字节）是踩过坑定下来的 ——
   *   **写打开只能证伪**、stat/读打开可能**一律失败**（≠ 不存在，5.0.52 定案）。
   *   换一套必然退化成「全判为已删」或「永远判为还在」。
   * ⚠️ **同步 IO 必须让帧**：`albumAssetAlive` 是 `statSync`/`openSync`/`readSync`，
   *   一批几十张会把主线程占住掉帧 ⇒ 先 `yieldOnce()` 再逐个探。
   * ⚠️ **节流**：`albumClearedIds` 记住刚清过的 id ⇒ 同一批死 uri 不重复探。
   * ⚠️ **只清索引、不删缓存小图**：用户删的是**系统相册**里那份，我们自己的
   *   320px 缓存还要留着显示，否则气泡变空白（5.0.52~5.0.56 稳定下来的行为）。
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

# ---------------------------------------------------------------- 改 3：节流字段
OLD3 = """  private albumIndexNext: Map<string, string> | null = null;"""
NEW3 = """  private albumIndexNext: Map<string, string> | null = null;
  // ★ 5.0.75：切消息页探测时**刚清过**的相册 key，避免每次切 tab 重复做同步 IO
  private albumClearedIds: Set<string> = new Set<string>();"""

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 切tab挂钩'),
                      (OLD2, NEW2, '改2 探测方法'),
                      (OLD3, NEW3, '改3 节流字段')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

# ---- 不变量 ----
assert s2.count('private async probeAlbumOnEnterChat(): Promise<void> {') == 1
assert s2.count('this.probeAlbumOnEnterChat();') == 1
assert s2.count('private albumClearedIds: Set<string> = new Set<string>();') == 1
# 必须复用既有三信号探测，不新造
assert s2.count('if (!this.albumAssetAlive(uri)) {') == 1
# 只清 uri 不删缩略图
assert s2.count('this.service.clearAlbumUri(dead[i]);') == 1
# 探测走闸门
assert s2.count('this.swapAlbumIndex();') >= 1
# ①（5.0.75 上一轮已落盘）做回归保护
assert s2.count('private bubbleHintOfGroup(g: ChatGroup): string {') == 1
assert s2.count('this.bubbleHintOfGroup(g)') == 1
assert s2.count("' '.repeat(gap)") == 2, s2.count("' '.repeat(gap)")
# 前几轮修复仍在
assert 'this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)' in s2
assert 'this.mediaFitOf(fixedSquare)' in s2
assert '${this.groupMediaSig(g)}|${this.groupGoneSig(g)}' in s2
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK  Index.ets %d -> %d  |  5000075 新功能②' % (len(s_idx), len(s2)))
