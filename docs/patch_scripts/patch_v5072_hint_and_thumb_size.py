# -*- coding: utf-8 -*-
"""v5.0.72 —— 三个诉求（vivi 2026-10-02 19:53）：

① 「已存入相册 · 点击打开」小蓝字**没有加回来**
② **单张图片气泡**的缩略图窗口太小 ⇒ 固定成与宫格格框一样大（`GRID_SIDE` = 88）
③ **视频图框**也一样（同一处代码，一起改）

【① 为什么没加回来（我自己查出来了）】
5.0.71 我按 B 方案把外层 key 里的 `groupAlbumSig` 换成了 `groupGoneSig`，
理由是「已存入」的提示由 `bubbleHintOf` 的**等宽文案**承载、不必重建。
但实测发现用户根本没看到那行小蓝字 ⇒ 说明承载它的**渲染条件**不满足：

    宫格气泡 :5985  `if (g.incoming && !this.chatSelectMode)`
    单张气泡 :6159  `if (m.incoming && !this.chatSelectMode)`

而这两处提示只在**「收到的」**气泡上显示。真实场景里，
**多张图片收进来后聚合成一颗宫格气泡**（5.0.55）⇒ 走 :5985 那条；
若那批里已存进相册，`g.incoming` 为 true，条件本应满足……
⚠️ 但 5.0.71 同时把 `groupAlbumSig` 从 key 里拿掉了 ⇒ **气泡不再重建**
⇒ ArkUI **不会重新执行**这行 `Text` 的表达式（它只在 build 时求值）
⇒ **文案永远停留在 build 那一刻的值**（存相册之前 = 「点击查看」），
    即使 `bubbleHintOf` 此刻返回的已是「已存入相册」。

★★ 这就是 B 方案的**致命前提被我漏了**：
   「文案能承载」成立的条件是**它被重新求值**，而 key 不变 ⇒ 不重建 ⇒ 不求值。
   ⇒ **凡是「靠文案/颜色等表达式承载的显示」，就必须让那一层真的重建。**
   这与 5.0.70「等宽化」不冲突（等宽化解决的是**宽度重排**，
   重建解决的是**值更新**，两者是不同的问题）。

修法：把「已存入」这一维**加回 key**，但用**不参与宽度**的方式 ——
      新增 `groupAlbumHintSig`（读 `albumPartOf(mid,0,0).length > 0`），
      与 `groupGoneSig` **合并**成一个分量。既是「重建触发」，又因文案等宽
      而不会造成可见的宽度跳动。

【②③ 单张/视频缩略图窗口固定】
`chatFileBubble` 调的是 `this.mediaThumb(mediaPath, 48, isVideo)` ——
**48vp 就是「很小窗口」的来源**（5.0.34 定的，与文件页一致）。
而 `thumbW/thumbH` 按 `mediaRatio` 算等比尺寸 ⇒ 比例未知时退回**正方形 48**。
vivi 要求：**与宫格格框一样大** ⇒ 直接给 `GRID_SIDE`（88），
并让容器**恒为 88×88 正方形**（与 `mediaThumbFixed` 同款思路）。
⚠️ 图片本身仍用 `autoResize(true)` 等比下采样 + `Contain` ⇒ **不变形**。
⚠️ 视频那一支（`hasVideoThumb` 分支）同样改成 88 固定框 ⇒ 需求③。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.72' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5072pre'), (VER, 'app.json5.v5072pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：groupGoneSig 扩容 —— 把「已存入」这一维并回来（修诉求①）
# =====================================================================
OLD1 = """  private groupGoneSig(g: ChatGroup): string {
    let s: string = '';
    for (let i: number = 0; i < g.msgs.length; i++) {
      s += this.mediaGoneFromAlbum(g.msgs[i], 0) ? '1' : '0';
    }
    return s;
  }"""
NEW1 = """  private groupGoneSig(g: ChatGroup): string {
    let s: string = '';
    for (let i: number = 0; i < g.msgs.length; i++) {
      // ★ 5.0.72 把「**已存入相册**」这一维**并回来**（5.0.71 拿掉后
      // 「已存入相册 · 点击打开」那行小蓝字**一直没出现**，见方法注释的完整说明）。
      //
      // ★★ 关键教训：5.0.71 我以为「提示由 `bubbleHintOf` 的等宽文案承载、
      //   不必重建」—— **前提漏了**：ArkTS 只在 **build 时**求值表达式，
      //   key 不变 ⇒ 不重建 ⇒ **那行 `Text` 永远停留在 build 那一刻的值**
      //   （存相册之前 = 「点击查看」），哪怕 `bubbleHintOf` 此刻返回的
      //   已经是「已存入相册 …」。
      //   ⇒ **凡是「靠表达式（文案/颜色/长度）承载的显示」，就必须让那一层真的重建。**
      //   这与 5.0.70 的「等宽化」不冲突：等宽化解决**宽度重排**，
      //   重建解决**值更新**，是**两个不同的问题**。
      s += this.mediaGoneFromAlbum(g.msgs[i], 0) ? '1' : '0';
      s += this.albumPartOf(g.msgs[i], 0, 0).length > 0 ? '1' : '0';
    }
    return s;
  }"""

# =====================================================================
# 改 2：mediaThumb 加「固定方框」模式（修诉求②③）
# =====================================================================
OLD2 = """  mediaThumb(path: string, maxSide: number, isVideo: boolean) {
    Stack() {"""
NEW2 = """  /**
   * 气泡里的缩略图。
   *
   * ★★ 5.0.72（vivi 2026-10-02）：`fixedSquare` = true 时**容器恒为
   * `maxSide × maxSide` 正方形**，与宫格 `mediaThumbFixed` 同款；
   * 图片本身仍走 `autoResize(true)` 等比下采样 + `Contain` ⇒ **不变形**。
   *
   * ⚠️ 为什么单张气泡要这样：此前 `chatFileBubble` 传的是 `48`
   *   （5.0.34 定的「与文件页一致的小缩略图」），vivi 反馈「很小窗口」，
   *   要求**与宫格格框一样大** ⇒ 改传 `GRID_SIDE`（88）。
   * ⚠️ 比例表（`mediaRatio`）缺失时 `thumbW/thumbH` 会退回「正方形 maxSide」，
   *   所以**固定方框**反而更稳：框恒定 ⇒ 只有图片内容随比例变，不会跳动。
   */
  mediaThumb(path: string, maxSide: number, isVideo: boolean, fixedSquare: boolean = false) {
    // 固定方框模式下，图片显示区恒为 maxSide；非固定时沿用按比例算的尺寸
    const boxW: number = fixedSquare ? maxSide : this.thumbW(path, maxSide);
    const boxH: number = fixedSquare ? maxSide : this.thumbH(path, maxSide);
    Stack() {"""

OLD3 = """        if (this.hasVideoThumb(path)) {
          Image(this.videoThumbOf(path) as image.PixelMap)
            .width(this.thumbW(path, maxSide))
            .height(this.thumbH(path, maxSide))
            .objectFit(ImageFit.Contain)
        }
        // 播放角标：盖在图上，一眼区分「图」和「视频」
        Text('▶')
          .fontSize(maxSide >= 100 ? 30 : 16)
          .fontColor('#FFFFFF')
      } else {
        Image(this.imageUri(path))
          .width(this.thumbW(path, maxSide))
          .height(this.thumbH(path, maxSide))
          .objectFit(ImageFit.Contain)"""
NEW3 = """        if (this.hasVideoThumb(path)) {
          // ★ 5.0.72：视频图框也固定（vivi 诉求③）
          Image(this.videoThumbOf(path) as image.PixelMap)
            .width(boxW)
            .height(boxH)
            .objectFit(ImageFit.Contain)
        }
        // 播放角标：盖在图上，一眼区分「图」和「视频」
        Text('▶')
          .fontSize(maxSide >= 100 ? 30 : 16)
          .fontColor('#FFFFFF')
      } else {
        Image(this.imageUri(path))
          .width(boxW)
          .height(boxH)
          .objectFit(ImageFit.Contain)"""

OLD4 = """    .width(this.thumbW(path, maxSide))
    .height(this.thumbH(path, maxSide))
    .backgroundColor('#EFF2F6')
    .borderRadius(8)
    .clip(true)
  }"""
NEW4 = """    .width(boxW)
    .height(boxH)
    .backgroundColor('#EFF2F6')
    .borderRadius(8)
    .clip(true)
  }"""

# =====================================================================
# 改 3：chatFileBubble 传 GRID_SIDE + fixedSquare
# =====================================================================
OLD5 = """      if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
        this.mediaThumb(mediaPath, 48, isVideo)
      }"""
NEW5 = """      if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
        // ★ 5.0.72：48 -> `GRID_SIDE`(88)，并**固定方框**（vivi 诉求②③：
        //   「单张图片目前是很小的窗口，也固定一下大小，和气泡里的缩略图框一样大」）
        this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)
      }"""

OLD6 = '"versionCode": 5000071'
NEW6 = '"versionCode": 5000072'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 已存入维度并回'),
                      (OLD2, NEW2, '改2 固定方框参数'),
                      (OLD3, NEW3, '改3 图片/视频用 boxW'),
                      (OLD4, NEW4, '改4 容器用 boxW'),
                      (OLD5, NEW5, '改5 单张气泡传 GRID_SIDE')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD6) == 1
v2 = v2.replace(OLD6, NEW6, 1)
assert v2.count('"versionName": "5.0.71"') == 1
v2 = v2.replace('"versionName": "5.0.71"', '"versionName": "5.0.72"', 1)

_code = '\n'.join(l for l in s2.split('\n')
                  if not l.strip().startswith('//')
                  and not l.strip().startswith('*')
                  and not l.strip().startswith('/*'))
# 改1：已存入维度并回
assert "s += this.albumPartOf(g.msgs[i], 0, 0).length > 0 ? '1' : '0';" in s2
# 改2/3/4：boxW/boxH 到位，容器不再用 thumbW/thumbH
assert s2.count('private boxW') or True
assert s2.count('const boxW: number = fixedSquare ? maxSide : this.thumbW(path, maxSide);') == 1
assert s2.count('const boxH: number = fixedSquare ? maxSide : this.thumbH(path, maxSide);') == 1
assert '.width(boxW)' in s2 and '.height(boxH)' in s2
# 文件页那处 48 必须保持不变（只有消息页单张气泡改成 88）
assert 'this.mediaThumb(f.path, 48, this.isVideoName(f.path))' in s2, '文件页 48 被误改'
assert s2.count('this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)') == 1
# autoResize 保留（不变形）
assert '.autoResize(true)' in s2
# 前几轮修复仍在
assert '${this.groupMediaSig(g)}|${this.groupGoneSig(g)}' in s2
assert "return notYet + ' '.repeat(gap);" in s2
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')
assert 'this.chat = v;' in s2

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000072' % (len(s_idx), len(s2)))
