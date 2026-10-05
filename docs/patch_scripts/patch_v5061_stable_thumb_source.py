# -*- coding: utf-8 -*-
"""LANShare V5 5.0.61 —— 缩略图显示源恒定化（治「接收好了、存完相册又整屏刷一遍」）

vivi 2026-10-02 确认走方案 A。四件事：
  ① 气泡缩略图改用**恒定源** `mediaThumbSrcOf`（缓存小图优先；缓存文件名只由
     「消息 id + 媒体序号」决定，幂等 ⇒ 是个不会消失的显示身份）；
  ② 接收 / 渲染时**按需预生成**缓存小图（`maybePrefetchThumb`），让「存相册 →
     删沙箱副本」这一步**不改变显示源**；
  ③ ForEach key 里的**全局 `thumbTick` 换成每项自己的签名** —— 一张图的变化
     不再波及整屏（原来一张存相册 = 全部气泡销毁重建）；
  ④ 「已删」标记判据补上「沙箱副本也没了」，否则预生成后每张新图都会被标成「已删」。

不动的东西（重要）：
  - `mediaSrcOf` 语义不变（沙箱原图优先）→ 全屏预览 / 画廊 / 长按存图清晰度不受影响；
  - EXIF 方向照片（deg≠0）不参与恒定路径 —— 它们 5.0.60 起走「复制原图当缓存」
    （`_full`），内容与原图逐字节相同 ⇒ 切换视觉零变化，而预生成会让每张竖拍
    照片多存一份原图（磁盘翻倍），不划算。
"""
import io
import sys

BASE = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets'
P_INDEX = BASE + r'\pages\Index.ets'
P_SVC = BASE + r'\service\LanService.ets'


def read(p):
    s = io.open(p, encoding='utf-8', newline='').read()
    return s.replace('\r\n', '\n')


def write(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(s)


def rep(s, tag, old, new, probe):
    n = s.count(old)
    assert n == 1, '锚点不唯一/未命中 [%s]: %d 次' % (tag, n)
    assert probe not in s, '新文本已存在，疑似重复执行 [%s]: %s' % (tag, probe)
    return s.replace(old, new, 1)


# ============================ Index.ets ============================
idx = read(P_INDEX)
if 'mediaThumbSrcOf' in idx:
    print('ALREADY APPLIED')
    sys.exit(0)

# ---- R1 新增字段 -------------------------------------------------
idx = rep(
    idx, 'R1_field',
    '''  /** 正在量尺寸的路径（防重复提交） */
  private mediaRatioBusy: Set<string> = new Set<string>();
''',
    '''  /** 正在量尺寸的路径（防重复提交） */
  private mediaRatioBusy: Set<string> = new Set<string>();
  /**
   * ★ 5.0.61：**已经提交过**缓存缩略图预生成的 key（`消息id#媒体序号`）。
   * 目的只有一个：让「渲染时按需补缩略图」不会每次重绘都重复提交。
   * ⚠️ 生成失败时会把记录撤掉（见 `prefetchThumbInner`），不会「一失手就永久没图」。
   */
  private thumbPrepare: Set<string> = new Set<string>();
''',
    'private thumbPrepare')

# ---- R2 mediaSrcOf 之后插入一堆新方法 ----------------------------
OLD_MEDIASRC = '''  /**
   * ★ 5.0.52：这条消息第 k 个媒体**当前最好的显示源**：
   * 沙箱那份还在就用它（原图），已经被删（存进相册了）就用**这一张自己的**缓存缩略图。
   */
  private mediaSrcOf(m: ChatMessage, k: number): string {
    const names: string[] = this.mediaNamesOf(m);
    if (k < 0 || k >= names.length) {
      return '';
    }
    const p: string = this.recvPathFor(names[k], k, m.timeMs);
    if (p.length > 0) {
      return p;
    }
    return this.albumPartOf(m.id, k, 1);
  }
'''

NEW_MEDIASRC = '''  /**
   * ★ 5.0.52：这条消息第 k 个媒体**当前最好的显示源**：
   * 沙箱那份还在就用它（原图），已经被删（存进相册了）就用**这一张自己的**缓存缩略图。
   *
   * ⚠️ 5.0.61 起这个方法**只给「要看清楚」的场合用**（全屏预览 / 画廊 / 长按存图）——
   *    气泡缩略图请走 `mediaThumbSrcOf()`。原因见那个方法的注释：
   *    本方法的返回值会随「沙箱副本被删」而变，挂进 ForEach key 就会引发整屏重建。
   */
  private mediaSrcOf(m: ChatMessage, k: number): string {
    const names: string[] = this.mediaNamesOf(m);
    if (k < 0 || k >= names.length) {
      return '';
    }
    const p: string = this.recvPathFor(names[k], k, m.timeMs);
    if (p.length > 0) {
      return p;
    }
    return this.albumPartOf(m.id, k, 1);
  }

  /**
   * ★ 5.0.61：气泡缩略图的**恒定显示源** —— 缓存小图优先。
   *
   * 与 `mediaSrcOf` 的分工（本次改动的核心，别混用）：
   *   - `mediaSrcOf`  = **尽力高清**源（沙箱原图优先）→ 全屏预览 / 画廊 / 长按存图；
   *   - 本方法        = **稳定**源（缓存小图优先）→ 气泡缩略图 + ForEach key。
   *
   * ⚠️ 为什么必须另立一个：`mediaSrcOf` 的返回值会随「沙箱副本被删」而切换
   *    （沙箱原图 → 缓存小图）。而 ForEach 的 key 里带着它 ⇒ 一次「存相册」
   *    就把**整屏**气泡的 key 全改掉 ⇒ 全部销毁重建、重新解码。vivi 2026-10-02
   *    反馈的「接收完那一刻缩略图已经生成了，保存完相册又刷一遍」就是这条链
   *    （三层成因里的第一、二层）。
   *    缓存文件名只由「消息 id + 媒体序号」决定（幂等），正好提供了一个
   *    **不会消失的显示身份** —— 接收时就把小图生成好，之后源恒定、key 恒定。
   *
   * ⚠️ 为什么 `_full`（原图复制兜底）不参与恒定路径：那类图的内容与沙箱原图
   *    **逐字节相同**，切过去视觉上零变化、用户本来就感知不到；而预生成会让每张
   *    竖拍照片都多存一份原图（磁盘翻倍），不值。所以它们继续「沙箱优先」。
   */
  private mediaThumbSrcOf(m: ChatMessage, k: number): string {
    const names: string[] = this.mediaNamesOf(m);
    if (k < 0 || k >= names.length) {
      return '';
    }
    const cached: string = this.albumPartOf(m.id, k, 1);
    if (cached.length > 0 && !Index.isFullCopyThumb(cached)) {
      return cached;
    }
    const p: string = this.recvPathFor(names[k], k, m.timeMs);
    if (p.length > 0) {
      // 沙箱那份还在 —— 顺手把缓存小图补出来（**渲染到才补**，不做全量预热）
      this.maybePrefetchThumb(m.id, k, p);
      return p;
    }
    return cached;
  }

  /** `_full` = 5.0.60 起的「原图复制兜底」，内容与原图相同 ⇒ 不参与恒定显示源 */
  private static isFullCopyThumb(p: string): boolean {
    return p.indexOf('_full.') >= 0;
  }

  /**
   * 这条消息的第 1 个媒体是不是视频。
   *
   * ⚠️ 必须从**消息本身**判断，不能看显示源的扩展名 —— 视频的缓存封面是普通
   *    `.jpg`，看路径会把「视频的封面」误判成图片，丢掉 ▶ 角标。
   */
  private msgIsVideo(m: ChatMessage): boolean {
    const ns: string[] = this.mediaNamesOf(m);
    return ns.length > 0 && this.isVideoName(ns[0]);
  }

  /**
   * 气泡缩略图在 ForEach key 里的**每项签名**：显示源 + 比例 + 补转角度。
   *
   * ★ 5.0.61：用它替掉 key 里的**全局** `thumbTick` —— 那个计数器每生成一张缩略图
   *   就 +1，于是「一张图存进相册」会把整屏气泡的 key 全改掉、全部销毁重建。
   *   签名下移到每一项自己的显示要素之后，只有真正变了的那个格子会重建。
   */
  private thumbSigOf(m: ChatMessage): string {
    const src: string = this.mediaThumbSrcOf(m, 0);
    if (src.length === 0) {
      return `${m.id}:-`;
    }
    return `${m.id}:${src}:${this.ratioOf(src)}:${this.service.rotOf(src) ?? 0}`;
  }

  /**
   * ★ 5.0.61：缓存缩略图的**按需预生成** —— 渲染到哪张补哪张，不做全量预热
   * （5.0.33 那次「刷新就把全部文件同步算一遍」的卡顿不能再犯）。
   *
   * 三道去重：内存 `thumbPrepare`（本轮已提交）、磁盘索引（已有缓存）、
   * `cacheThumb` 自己的单飞表。生成失败撤销记录 —— 下次渲染还能再试。
   */
  private maybePrefetchThumb(id: string, k: number, srcPath: string): void {
    const key: string = Index.albumKeyOf(id, k);
    if (this.thumbPrepare.has(key)) {
      return;
    }
    this.thumbPrepare.add(key);
    this.prefetchThumbInner(key, srcPath).catch(() => {
      this.thumbPrepare.delete(key);
    });
  }

  private async prefetchThumbInner(key: string, srcPath: string): Promise<void> {
    try {
      // ⚠️ 先让出一拍：本方法是从**渲染路径**上发起的，而下一步读 EXIF 是同步 IO。
      //   不 await 的话这段 IO 会挤在 build 阶段里，滚动时掉帧。
      await Index.yieldOnce();
      // ⚠️ 带 EXIF 方向的图**不预生成**（理由见 mediaThumbSrcOf 的注释）：
      //   5.0.60 对它们走「复制原图当缓存」，预生成等于给每张竖拍照片多存一份原图。
      if (!this.isVideoName(srcPath) && Index.jpegExifDeg(srcPath) !== 0) {
        return;
      }
      const ctx: common.UIAbilityContext =
        this.getUIContext().getHostContext() as common.UIAbilityContext;
      const thumb: string = await this.cacheThumb(ctx, srcPath, key);
      if (thumb.length === 0) {
        this.thumbPrepare.delete(key);
        return;
      }
      const rot: number = this.service.rotOf(thumb) ?? 0;
      // ⚠️ 只补缩略图，**绝不碰相册 URI** —— 用户还没点确认框（见 setThumbOnly）
      await this.service.setThumbOnly(key, thumb, rot);
      this.albumIndex = this.service.albumSnapshot();
      Log.i(TAG, `缩略图预生成就绪（显示源此后恒定）: ${Index.baseName(srcPath)}`
        + ` -> ${Index.baseName(thumb)}`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `预生成缩略图失败: ${err.code} ${err.message}`);
      this.thumbPrepare.delete(key);
    }
  }

  /**
   * 这一张是不是「已经不在沙箱、也不在相册」= 用户在系统相册里把它删了。
   *
   * ★ 5.0.61：判据里补上「沙箱副本也没了」这一条。改之前是
   *   「无相册 URI 且 有缩略图」⇒ 已删；可**预生成之后，还没存过相册的图也有缩略图**，
   *   那种判法会把每张新图都标成「已删」。
   */
  private mediaGoneFromAlbum(m: ChatMessage, k: number): boolean {
    if (this.albumPartOf(m.id, k, 0).length > 0) {
      return false;
    }
    if (this.albumPartOf(m.id, k, 1).length === 0) {
      return false;
    }
    const names: string[] = this.mediaNamesOf(m);
    if (k < 0 || k >= names.length) {
      return false;
    }
    return this.recvPathFor(names[k], k, m.timeMs).length === 0;
  }
'''
idx = rep(idx, 'R2_mediaSrcOf', OLD_MEDIASRC, NEW_MEDIASRC, 'private mediaThumbSrcOf')

# ---- R3 bubbleMediaPath 改恒定源 --------------------------------
idx = rep(
    idx, 'R3_bubbleMediaPath',
    '''  /** 气泡缩略图的来源：沙箱那份还在就用它，已被删（存进相册了）就用缓存的小图 */
  private bubbleMediaPath(m: ChatMessage): string {
    // ★ 5.0.52：气泡显示的是**这一批里的第 1 张**，缩略图必须取第 1 张自己的那份。
    //   （5.0.51 之前取的是「这条消息那唯一一个槽位」= 一批里最后写进去的那张，
    //    于是「缩略图显示的不是刚收到的那张」。）
    return this.mediaSrcOf(m, 0);
  }
''',
    '''  /**
   * 气泡缩略图的来源 —— **恒定源**（缓存小图优先，见 `mediaThumbSrcOf`）。
   *
   * ★ 5.0.61：从 `mediaSrcOf` 换成 `mediaThumbSrcOf`。两者取图的取舍不同：
   *   缩略图只要「稳定 + 够清楚」，而沙箱原图换来的是每次存相册一次全屏重建。
   *   点开大图那条路（`onFileBubbleClick` → 画廊 / 全屏预览）走的仍是 `mediaSrcOf`，
   *   清晰度不受影响。
   */
  private bubbleMediaPath(m: ChatMessage): string {
    // ★ 5.0.52：气泡显示的是**这一批里的第 1 张**，缩略图必须取第 1 张自己的那份。
    //   （5.0.51 之前取的是「这条消息那唯一一个槽位」= 一批里最后写进去的那张，
    //    于是「缩略图显示的不是刚收到的那张」。）
    return this.mediaThumbSrcOf(m, 0);
  }
''',
    '从 `mediaSrcOf` 换成 `mediaThumbSrcOf`')

# ---- R4 groupMediaSig 换签名 ------------------------------------
idx = rep(
    idx, 'R4_groupMediaSig',
    '''  /** 组内**每条**消息的媒体路径签名（ForEach key 用，见调用点注释） */
  private groupMediaSig(g: ChatGroup): string {
    let s: string = '';
    for (let i: number = 0; i < g.msgs.length; i++) {
      const mid: string = g.msgs[i].id;
      const v: string | undefined = this.chatMediaPaths.get(mid);
      s += `${v === undefined ? '' : v},`;
    }
    return s;
  }
''',
    '''  /**
   * 组内**每条**消息的缩略图签名（ForEach key 用，见调用点注释）。
   *
   * ★ 5.0.61：从这里**去掉全局 `thumbTick`**（原来挂在 ListItem 的 key 上）——
   *   那个计数器每生成一张缩略图就 +1，于是「一张图存进相册」会把**整屏**气泡的
   *   key 全部改掉、全部销毁重建（「保存完相册又刷一遍」的第三层成因）。
   *   现在签名下移到**这一组自己**的显示要素（显示源 + 比例 + 补转角度）：
   *   只有真正变了的那一组会重建，其余行的 key 完全不动。
   */
  private groupMediaSig(g: ChatGroup): string {
    let s: string = '';
    for (let i: number = 0; i < g.msgs.length; i++) {
      s += `${this.thumbSigOf(g.msgs[i])};`;
    }
    return s;
  }
''',
    '现在签名下移到**这一组自己**的显示要素')

# ---- R5 外层 ListItem key 去掉 thumbTick ------------------------
idx = rep(
    idx, 'R5_outer_key',
    "}, (g: ChatGroup) => `${g.key}|${this.videoThumbTick}|${this.thumbTick}|${this.groupMediaSig(g)}|${this.groupAlbumSig(g)}`)",
    "}, (g: ChatGroup) => `${g.key}|${this.videoThumbTick}|${this.groupMediaSig(g)}|${this.groupAlbumSig(g)}`)",
    '${g.key}|${this.videoThumbTick}|${this.groupMediaSig(g)}')

# ---- R6 内层格子 key --------------------------------------------
idx = rep(
    idx, 'R6_inner_key',
    "}, (m: ChatMessage) => `${m.id}|${this.videoThumbTick}|${this.thumbTick}|${this.mediaSrcOf(m, 0)}`)",
    "}, (m: ChatMessage) => `${this.videoThumbTick}|${this.thumbSigOf(m)}`)",
    '${this.videoThumbTick}|${this.thumbSigOf(m)}')

# ---- R7 rowKey --------------------------------------------------
idx = rep(
    idx, 'R7_rowKey',
    '''  /** ★ 5.0.56：一行（最多 3 个）的 key —— 带上行内每条**各自**的媒体源与解码 tick */
  private rowKey(row: ChatMessage[]): string {
    let s: string = `${this.videoThumbTick}|${this.thumbTick}|`;
    for (let i: number = 0; i < row.length; i++) {
      s += `${row[i].id}:${this.mediaSrcOf(row[i], 0)},`;
    }
    return s;
  }
''',
    '''  /**
   * ★ 5.0.56：一行（最多 3 个）的 key —— 带上行内每条**各自**的媒体源与解码 tick。
   * ★ 5.0.61：`thumbTick` 换成每项自己的签名（见 `thumbSigOf`），一张图的变化
   *   不再波及整屏。
   */
  private rowKey(row: ChatMessage[]): string {
    let s: string = `${this.videoThumbTick}|`;
    for (let i: number = 0; i < row.length; i++) {
      s += `${this.thumbSigOf(row[i])},`;
    }
    return s;
  }
''',
    '不再波及整屏。')

# ---- R8 宫格：缩略图源 + 已删判据 --------------------------------
idx = rep(
    idx, 'R8_grid_cell',
    '''              this.mediaThumbFixed(this.mediaSrcOf(m, 0), Index.GRID_SIDE)
              if (this.albumPartOf(m.id, 0, 0).length === 0
                && this.albumPartOf(m.id, 0, 1).length > 0) {''',
    '''              this.mediaThumbFixed(this.mediaThumbSrcOf(m, 0), Index.GRID_SIDE,
                this.msgIsVideo(m))
              if (this.mediaGoneFromAlbum(m, 0)) {''',
    'this.mediaThumbSrcOf(m, 0), Index.GRID_SIDE')

# ---- R9 mediaThumb 加 isVideo 参数 ------------------------------
idx = rep(
    idx, 'R9_mediaThumb_sig',
    '  mediaThumb(path: string, maxSide: number) {',
    '  mediaThumb(path: string, maxSide: number, isVideo: boolean) {',
    'mediaThumb(path: string, maxSide: number, isVideo: boolean)')

idx = rep(
    idx, 'R9b_mediaThumb_body',
    '''      // 占位（也是解码失败 / 还没解出来的样子），真图载入后盖住它
      Text(this.isVideoName(path) ? '视频' : '图片')
        .fontSize(11)
        .fontColor('#AAAAAA')
      if (this.isVideoName(path)) {
        if (this.hasVideoThumb(path)) {
          Image(this.videoThumbOf(path) as image.PixelMap)
            .width(this.thumbW(path, maxSide))''',
    '''      // 占位（也是解码失败 / 还没解出来的样子），真图载入后盖住它
      Text(isVideo ? '视频' : '图片')
        .fontSize(11)
        .fontColor('#AAAAAA')
      if (isVideo && this.isVideoName(path)) {
        if (this.hasVideoThumb(path)) {
          Image(this.videoThumbOf(path) as image.PixelMap)
            .width(this.thumbW(path, maxSide))''',
    'if (isVideo && this.isVideoName(path)) {')

# ---- R10 mediaThumbFixed 加 isVideo 参数 ------------------------
idx = rep(
    idx, 'R10_mediaThumbFixed_sig',
    '  mediaThumbFixed(path: string, side: number) {',
    '  mediaThumbFixed(path: string, side: number, isVideo: boolean) {',
    'mediaThumbFixed(path: string, side: number, isVideo: boolean)')

idx = rep(
    idx, 'R10b_mediaThumbFixed_body',
    '''      // 占位（也是解码失败 / 还没解出来的样子），真图载入后盖住它
      Text(this.isVideoName(path) ? '视频' : '图片')
        .fontSize(11)
        .fontColor('#AAAAAA')
      if (path.length > 0) {
        if (this.isVideoName(path)) {''',
    '''      // 占位（也是解码失败 / 还没解出来的样子），真图载入后盖住它
      Text(isVideo ? '视频' : '图片')
        .fontSize(11)
        .fontColor('#AAAAAA')
      if (path.length > 0) {
        if (isVideo && this.isVideoName(path)) {''',
    '''      if (path.length > 0) {
        if (isVideo && this.isVideoName(path)) {''')

# ---- R11 文件页 mediaThumb 调用点 -------------------------------
idx = rep(
    idx, 'R11_filepage_thumb',
    '''                  // 5.0.31：等比缩略图（见 mediaThumb 的注释）
                  this.mediaThumb(f.path, 48)''',
    '''                  // 5.0.31：等比缩略图（见 mediaThumb 的注释）
                  this.mediaThumb(f.path, 48, this.isVideoName(f.path))''',
    'this.mediaThumb(f.path, 48, this.isVideoName(f.path))')

# ---- R12 chatFileBubble 加 isVideo 参数 -------------------------
idx = rep(
    idx, 'R12a_call',
    '          this.chatFileBubble(m, this.bubbleMediaPath(m))',
    '          this.chatFileBubble(m, this.bubbleMediaPath(m), this.msgIsVideo(m))',
    'this.chatFileBubble(m, this.bubbleMediaPath(m), this.msgIsVideo(m))')

idx = rep(
    idx, 'R12b_sig',
    '  chatFileBubble(m: ChatMessage, mediaPath: string) {',
    '  chatFileBubble(m: ChatMessage, mediaPath: string, isVideo: boolean) {',
    'chatFileBubble(m: ChatMessage, mediaPath: string, isVideo: boolean)')

idx = rep(
    idx, 'R12c_thumb',
    '''      if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
        this.mediaThumb(mediaPath, 48)
      }''',
    '''      if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
        this.mediaThumb(mediaPath, 48, isVideo)
      }''',
    'this.mediaThumb(mediaPath, 48, isVideo)')

write(P_INDEX, idx)

# ============================ LanService.ets ============================
svc = read(P_SVC)
if 'setThumbOnly' in svc:
    print('ALREADY APPLIED (service)')
    sys.exit(0)

OLD_SET = '''  async setAlbumIndex(id: string, uri: string, thumb: string, rot: number = 0): Promise<void> {
    this.albumLoaded = true;
    this.albumMap.set(id, `${uri}|${thumb}`);
    this.albumRotMap.set(thumb, rot);
    await this.persistAlbumIndex();
    await this.persistAlbumRot();
  }
'''

NEW_SET = OLD_SET + '''
  /**
   * ★ 5.0.61：**只**补一条「缩略图缓存路径」，**绝不碰已有的相册 URI**。
   *
   * 用途：接收 / 渲染缩略图时**预生成**缓存小图，好让气泡的显示源从一开始就恒定
   * 指向 `album_thumbs/<key>.jpg` —— 之后存相册、删沙箱副本时源不变、ForEach key
   * 不变，缩略图**不会再整屏重刷一遍**。
   *
   * ⚠️ 与 `setAlbumIndex` 的区别只有一条，但极其关键：这条路径上**用户还没点
   *    相册确认框**，uri 必须是空的。如果直接把已有行覆盖成 `|thumb`，就把
   *    「点图跳相册」的能力冲掉了（`clearAlbumUri` 那种失效场景重演）。
   */
  async setThumbOnly(id: string, thumb: string, rot: number = 0): Promise<void> {
    if (thumb.length === 0) {
      return;
    }
    this.albumLoaded = true;
    const cur: string | undefined = this.albumMap.get(id);
    const segs: string[] = cur === undefined ? [] : cur.split('|');
    const curUri: string = segs.length > 0 ? segs[0] : '';
    this.albumMap.set(id, `${curUri}|${thumb}`);
    this.albumRotMap.set(thumb, rot);
    await this.persistAlbumIndex();
    await this.persistAlbumRot();
  }
'''
svc = rep(svc, 'S1_setThumbOnly', OLD_SET, NEW_SET, 'async setThumbOnly')
write(P_SVC, svc)

print('PATCHED OK')
