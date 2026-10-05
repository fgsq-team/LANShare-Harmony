# -*- coding: utf-8 -*-
"""
5.0.57（vivi 2026-10-02 两条要求）
  ① 「现在的框大小很合适，但是图片没有把框铺满，让图片填充显示，把框铺满」
     → `mediaThumbFixed` 由 `Contain`（留白）改 `Cover`（铺满方框、居中裁切），
       图片尺寸直接给 `side × side`，不再按比例算框内尺寸。
  ② 「长按选中这条消息的时候，加一个保存到相册的功能」
     → 消息多选态底部条加「存相册 (N)」，复用已跑通的 `autoSaveAlbumBatch`
       （title 去重 / 20 秒超时 / 数量不符不按位置硬配 / 逐张回退 / 记相册索引）。

幂等：哨兵 `batchSaveChatToAlbum`。写文件保持 LF。
"""
import io, sys

IX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
AJ = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'

SENTINEL = 'batchSaveChatToAlbum'

# ================================================================ 1. 缓存字段
A_OLD = """  private autoSaveHandled: Set<string> = new Set<string>();
"""
A_NEW = """  private autoSaveHandled: Set<string> = new Set<string>();
  /** ★ 5.0.57：`chatAlbumCount()` 的缓存 —— 多选态底部条一次渲染会问它 4 遍 */
  private chatAlbumCountCache: number = -1;
  /** ★ 5.0.57：上面那个缓存对应的签名（选中项 / 消息数 / 相册索引任一变化都要重算） */
  private chatAlbumCountSig: string = '';
"""

# ================================================================ 2. mediaThumbFixed 改铺满
B_OLD = """      if (path.length > 0) {
        if (this.isVideoName(path)) {
          if (this.hasVideoThumb(path)) {
            Image(this.videoThumbOf(path) as image.PixelMap)
              .width(this.thumbW(path, side))
              .height(this.thumbH(path, side))
              .objectFit(ImageFit.Contain)
          }
          // 播放角标：盖在图上，一眼区分「图」和「视频」
          Text('▶')
            .fontSize(24)
            .fontColor('#FFFFFF')
        } else {
          Image(this.imageUri(path))
            .width(this.thumbW(path, side))
            .height(this.thumbH(path, side))
            .objectFit(ImageFit.Contain)
            // 5.0.41：缓存小图按 `mediaRot` 补转；沙箱原图不在表里 -> AUTO（Image 自己读 EXIF）
            .orientation(this.thumbOri(path))
            .sourceSize({ width: side * 2, height: side * 2 })
        }
      }
"""
B_NEW = """      if (path.length > 0) {
        if (this.isVideoName(path)) {
          if (this.hasVideoThumb(path)) {
            Image(this.videoThumbOf(path) as image.PixelMap)
              // ★ 5.0.57：直接撑满方框 + `Cover` 居中裁切（vivi：把框铺满）
              .width(side)
              .height(side)
              .objectFit(ImageFit.Cover)
          }
          // 播放角标：盖在图上，一眼区分「图」和「视频」
          Text('▶')
            .fontSize(24)
            .fontColor('#FFFFFF')
        } else {
          Image(this.imageUri(path))
            .width(side)
            .height(side)
            .objectFit(ImageFit.Cover)
            // 5.0.41：缓存小图按 `mediaRot` 补转；沙箱原图不在表里 -> AUTO（Image 自己读 EXIF）
            .orientation(this.thumbOri(path))
            .sourceSize({ width: side * 2, height: side * 2 })
        }
      }
"""

# ================================================================ 3. 方法体
C_OLD = """    this.service.deleteChatMessages(ids);
    this.exitChatSelect();
  }
"""
C_NEW = """    this.service.deleteChatMessages(ids);
    this.exitChatSelect();
  }

  /**
   * 这条消息能不能「存相册」：是**收到**的文件消息、有媒体名、**且还没有相册条目**。
   *
   * ⚠️ 已有相册条目的要排除 —— 否则用户会看到「存了但相册里多出一张重复的」。
   *   真在系统相册里被删掉的那种，`clearAlbumUri` 已经把 uri 摘掉了（只剩缩略图），
   *   所以这里也会重新放行，符合预期。
   */
  private albumPickable(m: ChatMessage): boolean {
    if (m.kind !== 'file' || !m.incoming) {
      return false;
    }
    if (this.mediaNamesOf(m).length === 0) {
      return false;
    }
    return this.albumPartOf(m.id, 0, 0).length === 0;
  }

  /**
   * ★ 5.0.57（vivi 2026-10-02）：多选态里**可存相册**的条数 —— 底部按钮上的数字。
   *
   * ⚠️ 带缓存：多选态底部条一次渲染会问它 4 遍（按钮文案 + 配色 + enabled 各一次），
   *   每次都全量扫 `chat × chatSelected` 是 O(N²)。签名一变就重算，其余时候直接返回。
   */
  private chatAlbumCount(): number {
    if (this.chatSelected.length === 0) {
      return 0;
    }
    const sig: string =
      `${this.chatSelected.join(',')}|${this.chat.length}|${this.albumIndex.size}`;
    if (sig === this.chatAlbumCountSig) {
      return this.chatAlbumCountCache;
    }
    const sel: Set<string> = new Set<string>();
    for (let k: number = 0; k < this.chatSelected.length; k++) {
      sel.add(this.chatSelected[k]);
    }
    let n: number = 0;
    for (let i: number = 0; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (sel.has(m.id) && this.albumPickable(m)) {
        n += 1;
      }
    }
    this.chatAlbumCountSig = sig;
    this.chatAlbumCountCache = n;
    return n;
  }

  /**
   * ★ 5.0.57（vivi 2026-10-02 要求）：多选态 -> 把选中的图片/视频**存进相册**。
   *
   * 典型用途：自动存相册被取消过、或在系统相册里删掉过之后补存。
   *
   * ⚠️ 复用 `autoSaveAlbumBatch` —— 那条链路已经在真机上跑通并修过三轮坑：
   *   `title` 去点号 + 批内去重、20 秒超时（`awaitDialog`）、
   *   **数量不符不按位置硬配**（改逐张）、写字节 + 缓存缩略图 + 记相册索引。
   *   自己另写一份批量存相册等于把这几个坑再踩一遍。
   *   `ready` 传空数组：那是「自动存队列」的结案清单，手动存不碰它。
   * ⚠️ 提交前把这些消息标进 `autoSaveHandled` —— 否则自动存相册那一队
   *   （`autoSavePending`）稍后可能又对它们弹一次框。
   * ⚠️ 与自动存相册**同口径**：内容落到相册后**删掉沙箱副本**（5.0.53 定的）。
   *   所以手动存完之后，文件页里那几条会消失 —— 它们是同一份内容，不是丢失。
   */
  private async batchSaveChatToAlbum(): Promise<void> {
    if (this.chatSelected.length === 0) {
      this.toast('请先选择要保存的图片或视频');
      return;
    }
    const paths: string[] = [];
    const keys: string[] = [];
    let skippedAlbum: number = 0;
    let skippedNone: number = 0;
    let thumbOnly: number = 0;
    for (let i: number = 0; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (this.chatSelected.indexOf(m.id) < 0) {
        continue;
      }
      if (m.kind !== 'file' || !m.incoming) {
        skippedNone += 1;
        continue;
      }
      const medias: string[] = this.mediaNamesOf(m);
      if (medias.length === 0) {
        skippedNone += 1;
        continue;
      }
      if (this.albumPartOf(m.id, 0, 0).length > 0) {
        skippedAlbum += 1;
        continue;
      }
      // ★ 优先沙箱**原图**；沙箱副本已被删（只剩缓存缩略图）时也能存，但只能存小图
      const raw: string = this.recvPathFor(medias[0], 0, m.timeMs);
      const src: string = raw.length > 0 ? raw : this.mediaSrcOf(m, 0);
      if (src.length === 0) {
        skippedNone += 1;
        continue;
      }
      if (raw.length === 0) {
        thumbOnly += 1;
      }
      // 去重按路径：同一份内容被两条消息指到时只提交一次（重复 title 会让系统少建资产）
      if (paths.indexOf(src) >= 0) {
        continue;
      }
      paths.push(src);
      keys.push(Index.albumKeyOf(m.id, 0));
      this.autoSaveHandled.add(m.id);
    }
    if (paths.length === 0) {
      const why: string = skippedAlbum > 0 ? `（${skippedAlbum} 张已在相册里）` : '';
      this.toast(`选中的消息里没有可存相册的图片/视频${why}`);
      return;
    }
    this.service.logAuto(`手动存相册：提交 ${paths.length} 张`
      + (skippedAlbum > 0 ? `，跳过已在相册的 ${skippedAlbum} 张` : '')
      + (thumbOnly > 0 ? `，其中 ${thumbOnly} 张只剩缓存缩略图（沙箱原图已删）` : '')
      + (skippedNone > 0 ? `，${skippedNone} 条不是可存的媒体` : ''));
    await this.autoSaveAlbumBatch(paths, keys, []);
    this.albumIndex = this.service.albumSnapshot();
    this.exitChatSelect();
  }
"""

# ================================================================ 4. 底部条加按钮
D_OLD = """      // ---------------- 消息多选态底部删除条 ----------------
      if (this.chatSelectMode) {
        Row({ space: 10 }) {
          Button(this.chatSelected.length > 0 ? `删除 (${this.chatSelected.length})` : '删除')
            .fontSize(14)
            .height(38)
            .width('100%')
            .backgroundColor(this.chatSelected.length > 0 ? '#FDECEA' : '#F2F2F2')
            .fontColor(this.chatSelected.length > 0 ? '#E84026' : '#AAAAAA')
            .enabled(this.chatSelected.length > 0)
            .onClick(() => this.batchDeleteChat())
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: 8, bottom: 12 })
      } else {
"""
D_NEW = """      // ---------------- 消息多选态底部操作条 ----------------
      if (this.chatSelectMode) {
        Row({ space: 10 }) {
          // ★ 5.0.57（vivi 2026-10-02）：多选态加「存相册」—— 补存那些
          //   自动存相册被取消过 / 在系统相册里删掉过的图片视频。
          //   ⚠️ 数量用 `chatAlbumCount()`（只数**可存**的），不用 `chatSelected.length` ——
          //      否则用户选了 3 条（1 张图 + 2 条文本）时按钮会说「存相册 (3)」，是错的。
          Button(this.chatAlbumCount() > 0 ? `存相册 (${this.chatAlbumCount()})` : '存相册')
            .fontSize(14)
            .height(38)
            .layoutWeight(1)
            .backgroundColor(this.chatAlbumCount() > 0 ? '#E8F0FE' : '#F2F2F2')
            .fontColor(this.chatAlbumCount() > 0 ? C_PRIMARY : '#AAAAAA')
            .enabled(this.chatAlbumCount() > 0)
            .onClick(() => this.batchSaveChatToAlbum())
          Button(this.chatSelected.length > 0 ? `删除 (${this.chatSelected.length})` : '删除')
            .fontSize(14)
            .height(38)
            .layoutWeight(1)
            .backgroundColor(this.chatSelected.length > 0 ? '#FDECEA' : '#F2F2F2')
            .fontColor(this.chatSelected.length > 0 ? '#E84026' : '#AAAAAA')
            .enabled(this.chatSelected.length > 0)
            .onClick(() => this.batchDeleteChat())
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: 8, bottom: 12 })
      } else {
"""

# ================================================================ 5. 版本号
AJ_OLD = """    "versionCode": 5000056,
    "versionName": "5.0.56",
"""
AJ_NEW = """    "versionCode": 5000057,
    "versionName": "5.0.57",
"""


def apply(path, pairs, label):
    s = io.open(path, encoding='utf-8', newline='').read()
    for i, (old, new) in enumerate(pairs):
        n = s.count(old)
        assert n == 1, '%s 锚点#%d 命中 %d 次' % (label, i + 1, n)
        assert s.count(new) == 0, '%s 新文本#%d 此前已存在' % (label, i + 1)
    for old, new in pairs:
        s = s.replace(old, new)
    return s


src = io.open(IX, encoding='utf-8', newline='').read()
if SENTINEL in src:
    print('ALREADY APPLIED')
    sys.exit(0)

new_ix = apply(IX, [(A_OLD, A_NEW), (B_OLD, B_NEW), (C_OLD, C_NEW), (D_OLD, D_NEW)], 'Index')
new_aj = apply(AJ, [(AJ_OLD, AJ_NEW)], 'app.json5')

for sym, want in [('private chatAlbumCountCache: number = -1;', 1),
                  ('private chatAlbumCountSig: string = \'\';', 1),
                  ('private albumPickable(m: ChatMessage): boolean {', 1),
                  ('private chatAlbumCount(): number {', 1),
                  ('private async batchSaveChatToAlbum(): Promise<void> {', 1),
                  # ⚠️ 5 处：按钮文案那行有 2 处（条件 + 插值），再加 backgroundColor/fontColor/enabled
                  ('this.chatAlbumCount()', 5),
                  ('this.batchSaveChatToAlbum()', 1),
                  ('await this.autoSaveAlbumBatch(paths, keys, []);', 1),
                  ('this.autoSaveHandled.add(m.id);', 1)]:
    got = new_ix.count(sym)
    assert got == want, '符号校验失败 %r: 期望 %d 实为 %d' % (sym, want, got)
    print('  OK %2d  %s' % (got, sym[:56]))

# mediaThumbFixed 里不能再有 Contain / thumbW
i = new_ix.find('mediaThumbFixed(path: string, side: number) {')
seg = new_ix[i:i + 1400]
assert seg.count('ImageFit.Contain') == 0, 'mediaThumbFixed 里仍有 Contain'
assert seg.count('ImageFit.Cover') == 2, 'mediaThumbFixed 里 Cover 应为 2，实为 %d' % seg.count('ImageFit.Cover')
assert seg.count('.width(this.thumbW(') == 0, 'mediaThumbFixed 里仍按比例算框内尺寸'
print('  OK  mediaThumbFixed: Cover=2, Contain=0, thumbW=0')
# 非宫格的 mediaThumb 必须保持 Contain（那是气泡里的独立缩略图，不能裁）
j = new_ix.find('  mediaThumb(path: string, maxSide: number) {')
seg2 = new_ix[j:j + 1600]
assert seg2.count('ImageFit.Contain') == 2, 'mediaThumb 的 Contain 被误改（应为 2，实为 %d）' % seg2.count('ImageFit.Contain')
print('  OK  mediaThumb 未受影响: Contain=2')
assert '5000057' in new_aj and '"5.0.57"' in new_aj

d = {}
for ch in '{}()[]':
    d[ch] = new_ix.count(ch) - src.count(ch)
print('Index 括号增量:', d)

io.open(IX, 'w', encoding='utf-8', newline='\n').write(new_ix)
io.open(AJ, 'w', encoding='utf-8', newline='\n').write(new_aj)
print('OK: 5.0.57 已应用')
