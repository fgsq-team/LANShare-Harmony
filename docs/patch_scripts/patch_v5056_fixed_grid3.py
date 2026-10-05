# -*- coding: utf-8 -*-
"""
5.0.56（vivi 2026-10-02 反馈：「现在实测并不是每行固定 3 个，能不能固定每个缩略图框的
最大宽度和高度，照片的宽高比例还保持原图比例，让他固定每行可以显示 3 个」）

根因（两条叠加）
  ① 宫格用的是 `Flex({ wrap: FlexWrap.Wrap })`，而每个格子的**宽度是等比的** ——
     `mediaThumb` 内部按原图比例算框尺寸（横图 88×44、竖图 44×88、方图 88×88）。
     Flex 换行取决于"这一行还塞不塞得下下一个**不同宽度**的元素"，所以一行的个数飘。
  ② 格子用 `.margin({right:4, bottom:4})`，**末位元素也带 4 的右边距** ——
     3×88 + 3×4 = 276 > 容器 272 ⇒ 第 3 个被挤到下一行（这正是"不是 3 个"的直接原因）。

修法
  ① **固定每个缩略图的框**（外框恒为 88×88 正方形，圆角/底色/裁剪照旧），
     图片在框内 `ImageFit.Contain` —— 框固定了，**每行个数才可能固定**，
     而 `Contain` 保证**原图比例不被拉伸/裁切**（横图上下留白、竖图左右留白）。
  ② 不再依赖 Flex 的 wrap 计算：在数据层把组内消息**按 3 个一行**切好（`ChatGroup.rows`），
     渲染时用 `Column{ Row{…} }` —— 结构上就**恒定 3 个一行**，与图片比例彻底无关。

幂等：哨兵 `mediaThumbFixed`。写文件保持 LF。
"""
import io, sys

LS = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\service\LanService.ets'
IX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
AJ = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'

SENTINEL = 'mediaThumbFixed'

# ================================================================ 1. ChatGroup 加 rows
A_OLD = """  /** 组内**全部**是图片/视频 —— 决定了渲染成宫格而不是文件名气泡 */
  isMedia: boolean = false;
"""
A_NEW = """  /** 组内**全部**是图片/视频 —— 决定了渲染成宫格而不是文件名气泡 */
  isMedia: boolean = false;
  /**
   * ★ 5.0.56：宫格的**行**划分 —— 每行最多 3 个（在数据层切好，不在渲染层算）。
   *
   * ⚠️ 为什么要在数据层预切：宫格此前用 `Flex({ wrap: Wrap })` + **等比宽度**的格子，
   *   一行的个数取决于"还塞不塞得下下一个不同宽度的元素" ⇒ 实测不是固定 3 个
   *   （横图/竖图/方图宽度各不相同）。改成"固定框 + 手动分行"后，
   *   **结构上**就恒定每行 3 个，与图片比例彻底无关。
   */
  rows: ChatMessage[][] = [];
"""

# ================================================================ 2. buildChatGroups 填 rows
B_OLD = """      g.isMedia = this.groupAllMedia(g);
"""
B_NEW = """      g.isMedia = this.groupAllMedia(g);
      // ★ 5.0.56：按 3 个一行切好（只有宫格才需要 rows，非媒体组不用浪费）
      if (g.isMedia) {
        for (let k: number = 0; k < g.msgs.length; k += Index.GRID_COLS) {
          const row: ChatMessage[] = [];
          for (let t: number = k; t < k + Index.GRID_COLS && t < g.msgs.length; t++) {
            row.push(g.msgs[t]);
          }
          g.rows.push(row);
        }
      }
"""

# ================================================================ 3. gridWidth（换固定框算法）
C_OLD = """  /**
   * 宫格宽度：按**列数**（最多 3）算，让气泡贴合内容而不是撑满。
   * 每格 88 vp + 4 vp 间距，末尾那 4 vp 减掉。等比缩略图有宽有窄，
   * 只按最大列数算宽度 —— 窄图排得更松一点，绝不会溢出。
   */
  private gridWidth(g: ChatGroup): number {
    const n: number = g.msgs.length < 3 ? g.msgs.length : 3;
    return n * 92 - 4;
  }
"""
C_NEW = """  /**
   * 宫格宽度：按**列数**（最多 3）算，让气泡贴合内容而不是撑满。
   *
   * ★ 5.0.56：格子的**外框固定为 `GRID_SIDE` 正方形**（图片在框内 `Contain` 按比例留白），
   *   所以宽度就是 `列数 × 边长 + (列数-1) × 间距` —— 与图片比例无关，恒定可预测。
   *   （旧实现按 88 算宽度、格子却是等比宽度，两者对不上，Flex 换行点因此飘忽。）
   */
  private gridWidth(g: ChatGroup): number {
    const n: number = g.msgs.length < Index.GRID_COLS ? g.msgs.length : Index.GRID_COLS;
    return n * Index.GRID_SIDE + (n - 1) * Index.GRID_GAP;
  }

  /** ★ 5.0.56：一行（最多 3 个）的 key —— 带上行内每条**各自**的媒体源与解码 tick */
  private rowKey(row: ChatMessage[]): string {
    let s: string = `${this.videoThumbTick}|${this.thumbTick}|`;
    for (let i: number = 0; i < row.length; i++) {
      s += `${row[i].id}:${this.mediaSrcOf(row[i], 0)},`;
    }
    return s;
  }
"""
# --------------------------------------------------------------------------------------------
# mediaThumb 之后追加 fixed 版
D_OLD = """  @Builder
  chatTab() {
"""
D_NEW = """  /**
   * ★ 5.0.56：**固定外框**的缩略图 —— 宫格专用。
   *
   * 与 `mediaThumb` 的唯一区别：外框恒为 `side × side` **正方形**，
   * 图片按原图比例 `Contain` 填进框内（横图上下留白、竖图左右留白）。
   *
   * ⚠️ 为什么必须固定外框：宫格要「每行恒定 3 个」就必须让**每个格子的占地一致**；
   *   而等比框（横 88×44 / 竖 44×88）会让一行的个数随图片比例飘 —— 真机实测正是如此。
   * ⚠️ 为什么用 `Contain` 而不是 `Cover`：`Cover` 会把图片**裁切**成正方形，
   *   与 vivi「照片的宽高比例还保持原图比例」的要求相悖。
   * ⚠️ 框尺寸复用 `thumbW/thumbH`（它们本就是「按比例 contain 到 maxSide 方框」），
   *   不必另写一份比例计算。
   */
  @Builder
  mediaThumbFixed(path: string, side: number) {
    Stack() {
      // 占位（也是解码失败 / 还没解出来的样子），真图载入后盖住它
      Text(this.isVideoName(path) ? '视频' : '图片')
        .fontSize(11)
        .fontColor('#AAAAAA')
      if (path.length > 0) {
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
    }
    // ★ 固定外框 —— 宫格「每行 3 个」的基础
    .width(side)
    .height(side)
    .backgroundColor('#EFF2F6')
    .borderRadius(8)
    .clip(true)
  }

  @Builder
  chatTab() {
"""

# ================================================================ 5. chatMediaGrid 重写
E_OLD = """  chatMediaGrid(g: ChatGroup) {
    Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.Start }) {
      ForEach(g.msgs, (m: ChatMessage) => {
        Stack() {
          this.mediaThumb(this.mediaSrcOf(m, 0), 88)
          if (this.albumPartOf(m.id, 0, 0).length === 0
            && this.albumPartOf(m.id, 0, 1).length > 0) {
            Text('已删')
              .fontSize(10)
              .fontColor('#FFFFFF')
              .padding({ left: 4, right: 4, top: 1, bottom: 1 })
              .backgroundColor('#99000000')
              .borderRadius(4)
          }
        }
        .margin({ right: 4, bottom: 4 })
        .onClick(() => {
          if (Date.now() < this.clickMuteUntil) {
            return;
          }
          if (this.chatSelectMode) {
            this.toggleChatSelect(m.id);
            return;
          }
          this.onFileBubbleClick(m);
        })
      }, (m: ChatMessage) => `${m.id}|${this.videoThumbTick}|${this.thumbTick}|${this.mediaSrcOf(m, 0)}`)
    }
    // ⚠️ **不能写 `width('100%')`**：父 Column 是 wrapContent 宽，
    //   百分比会落到「无限宽」上（5.0.50 那个老坑的同款），于是 2 张图也撑到 92% 上限。
    //   按**列数**算一个确定宽度，气泡就贴合内容了。
    .width(this.gridWidth(g))
  }
"""
E_NEW = """  chatMediaGrid(g: ChatGroup) {
    // ★ 5.0.56：`Column{ Row{…} }` —— 每行**恒定 3 个**（分行在 `ChatGroup.rows` 里切好）。
    //   不再用 `Flex(wrap)`：它的换行取决于元素宽度，而格子宽度此前是等比的，
    //   于是「一行几个」飘忽不定（vivi 2026-10-02 实测反馈）。
    //   现在外框固定 + 分行固定 ⇒ 与图片比例彻底无关。
    Column({ space: Index.GRID_GAP }) {
      ForEach(g.rows, (row: ChatMessage[]) => {
        Row({ space: Index.GRID_GAP }) {
          ForEach(row, (m: ChatMessage) => {
            Stack() {
              this.mediaThumbFixed(this.mediaSrcOf(m, 0), Index.GRID_SIDE)
              if (this.albumPartOf(m.id, 0, 0).length === 0
                && this.albumPartOf(m.id, 0, 1).length > 0) {
                Text('已删')
                  .fontSize(10)
                  .fontColor('#FFFFFF')
                  .padding({ left: 4, right: 4, top: 1, bottom: 1 })
                  .backgroundColor('#99000000')
                  .borderRadius(4)
              }
            }
            .onClick(() => {
              if (Date.now() < this.clickMuteUntil) {
                return;
              }
              if (this.chatSelectMode) {
                this.toggleChatSelect(m.id);
                return;
              }
              this.onFileBubbleClick(m);
            })
          }, (m: ChatMessage) => `${m.id}|${this.videoThumbTick}|${this.thumbTick}|${this.mediaSrcOf(m, 0)}`)
        }
      }, (row: ChatMessage[]) => this.rowKey(row))
    }
    .alignItems(HorizontalAlign.Start)
    // ⚠️ **不能写 `width('100%')`**：父 Column 是 wrapContent 宽，
    //   百分比会落到「无限宽」上（5.0.50 那个老坑的同款），于是 2 张图也撑到 92% 上限。
    //   按**列数**算一个确定宽度，气泡就贴合内容了。
    .width(this.gridWidth(g))
  }
"""

# ================================================================ 6. GRID_COLS / GAP 常量
F_OLD = """  /** 缩略图宫格边长（vp）。3 列 × 88 + 2×4 间距 = 272，塞得进 88% 宽的气泡 */
  private static GRID_SIDE: number = 88;
"""
F_NEW = """  /** ★ 5.0.56：缩略图宫格 —— 外框边长（vp）。固定正方形，图片在框内按比例 Contain */
  private static GRID_SIDE: number = 88;
  /** ★ 5.0.56：每行**恒定**这么多个（vivi 2026-10-02 明确要求「固定每行 3 个」） */
  private static GRID_COLS: number = 3;
  /** ★ 5.0.56：格子间距（vp）。3×88 + 2×4 = 272，加气泡左右内边距 16 = 288，
   *  在 320vp 窄屏上仍 ≤ 92%×320 = 294 —— 不会溢出。 */
  private static GRID_GAP: number = 4;
"""

# ================================================================ 7. 版本号
AJ_OLD = """    "versionCode": 5000055,
    "versionName": "5.0.55",
"""
AJ_NEW = """    "versionCode": 5000056,
    "versionName": "5.0.56",
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


ls_src = io.open(LS, encoding='utf-8', newline='').read()
if SENTINEL in ls_src + io.open(IX, encoding='utf-8', newline='').read():
    print('ALREADY APPLIED')
    sys.exit(0)

new_ls = apply(LS, [(A_OLD, A_NEW)], 'LanService')
src_ix = io.open(IX, encoding='utf-8', newline='').read()
new_ix = apply(IX, [(B_OLD, B_NEW), (C_OLD, C_NEW), (D_OLD, D_NEW),
                    (E_OLD, E_NEW), (F_OLD, F_NEW)], 'Index')
new_aj = apply(AJ, [(AJ_OLD, AJ_NEW)], 'app.json5')

for tag, s, syms in [
  ('LS', new_ls, [('rows: ChatMessage[][] = [];', 1)]),
  ('IX', new_ix, [('private static GRID_SIDE: number = 88;', 1),
                  ('private static GRID_COLS: number = 3;', 1),
                  ('private static GRID_GAP: number = 4;', 1),
                  ('mediaThumbFixed(path: string, side: number) {', 1),
                  ('this.mediaThumbFixed(this.mediaSrcOf(m, 0), Index.GRID_SIDE)', 1),
                  ('private rowKey(row: ChatMessage[]): string {', 1),
                  ('this.rowKey(row)', 1),
                  ('ForEach(g.rows, (row: ChatMessage[]) => {', 1),
                  ('g.rows.push(row);', 1),
                  ('k += Index.GRID_COLS', 1),
                  ('n * Index.GRID_SIDE + (n - 1) * Index.GRID_GAP', 1),
                  ('Column({ space: Index.GRID_GAP }) {', 1),
                  ('Row({ space: Index.GRID_GAP }) {', 1)]),
]:
    for sym, want in syms:
        got = s.count(sym)
        assert got == want, '%s 符号校验失败 %r: 期望 %d 实为 %d' % (tag, sym, want, got)
        print('  OK %2d  %s  %s' % (got, tag, sym[:52]))

assert 'Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.Start })' not in new_ix, '旧 Flex 宫格仍在'
assert 'this.mediaThumb(this.mediaSrcOf(m, 0), 88)' not in new_ix, '旧宫格缩略图调用仍在'
assert '5000056' in new_aj and '"5.0.56"' in new_aj

for tag, b, a in [('LanService', ls_src, new_ls), ('Index', src_ix, new_ix)]:
    d = {}
    for ch in '{}()[]':
        d[ch] = a.count(ch) - b.count(ch)
    print('%s 括号增量: %s' % (tag, d))

io.open(LS, 'w', encoding='utf-8', newline='\n').write(new_ls)
io.open(IX, 'w', encoding='utf-8', newline='\n').write(new_ix)
io.open(AJ, 'w', encoding='utf-8', newline='\n').write(new_aj)
print('OK: 5.0.56 已应用')
