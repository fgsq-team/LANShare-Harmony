# -*- coding: utf-8 -*-
"""v5.0.74 —— 单张气泡：提示行移到左下角（与宫格同款）+ 带数量 + 换文案。

vivi 2026-10-02 20:11 诉求：
  ① 单张图片的「点击查看」**放到气泡左下角，和宫格位置一样**
  ② **也写上数量**：图片「1 张」、视频「1 个」
  ③ 文案改成 **「已存入相册，点击查看」**

【设计决定：整段重写 `chatFileBubble`，不做「插入嵌套 Column」】
先在 dry-run 里试过「外层 Row 内再套一个 Column」的最小改动，结果**结构错乱**
（留下一���裸 `{`，`chatFileBubble` 的花括号虽然总数平衡但层级是错的）
⇒ 改为**整段替换**，把竖排结构一次写对。
⚠️ 教训：改 `@Builder` 的**层级结构**时，**「插入一层」比「整段重写」更容易出错** ——
   插入法要同时维护上下两层的收尾括号，而 5.0.72 已经栽过一次
   （helper 插到 `@Builder` 标记与函数之间 ⇒ 标记配错函数）。
   整段重写虽然「动作大」，但**改完的结构是完整可读的**。

【布局对照】
宫格 `chatMediaBubble`（Column，竖排）：
    发送方名 + 时间
    缩略图宫格
    `N 张 · 提示`        ← 左下角
单张 `chatFileBubble`（本轮改成同款竖排）：
    收到文件 / 已发送文件
    缩略图（88 固定方框）
    `1 张/个 · 提示`     ← 左下角，与宫格同位置

⚠️ 5.0.35 当初把单张改成**横排**（左图右名）是为了「像文件页那样矮」；
   现在按 vivi 要求让位给「与宫格一致」—— **这是取舍变更，不是回退**。

【数量单位】
`bubbleCountText`：**视频 → 「1 个」，图片 → 「1 张」**（vivi 明确要求）。
判据用 `msgIsVideo(m)`（从**消息本身**判断，不看显示源扩展名 ——
视频的缓存封面是普通 `.jpg`，看路径会误判）。
⚠️ 宫格那行仍恒用「张」，本轮**不动**（只按 vivi 的要求改单张，不擅自扩大范围）。

【文案 + 等宽】
`bubbleHintOf` 两分支改成用户指定口径：
    未存：`点击查看`        （4 字）
    已存：`已存入相册，点击查看`  （10 字）
⚠️ **仍必须等宽**（5.0.70 立的规矩）：短的那条补半角空格，
   否则存相册瞬间又会重排闪一下。注意新文案**没有「›」**⇒ 长度差要重算。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.74' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5074pre'), (VER, 'app.json5.v5074pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：bubbleHintOf 文案换成用户指定口径（保持等宽）
# =====================================================================
OLD1 = """    const inAlbum: string = '已存入相册 · 点击打开 ›';
    const notYet: string = '点击查看 ›';"""
NEW1 = """    // ★ 5.0.74（vivi 20:11 指定口径）：已存 → 「已存入相册，点击查看」
    //   ⚠️ 仍**必须等宽**（5.0.70 的规矩）：两句字数不同 ⇒ 短的补半角空格，
    //     否则存相册瞬间又会重排闪一下。
    const inAlbum: string = '已存入相册，点击查看';
    const notYet: string = '点击查看';"""

# =====================================================================
# 改 2：新增数量文案 helper（视频「1 个」/ 图片「1 张」）
# =====================================================================
OLD2 = """  /** 5.0.72：固定方框时恒返回 `maxSide`，否则按比例算（供 @Builder 内表达式调用） */
  private boxSide(path: string, maxSide: number, fixedSquare: boolean): number {"""
NEW2 = """  /**
   * ★ 5.0.74：气泡底部提示行的**数量 + 单位**（单张气泡用）。
   *
   * vivi 20:11：「也写上 1 张，视频写成 1 个」⇒ **视频的单位是「个」不是「张」**。
   * 判据用 `msgIsVideo(m)`（从**消息本身**判断，不看显示源的扩展名 ——
   * 视频的缓存封面是普通 `.jpg`，看路径会把视频误判成图片）。
   *
   * ⚠️ 宫格那行目前恒用「张」（`${g.msgs.length} 张`）。一批里混了视频时
   * 单位会不准 —— 那是**既有行为**，本轮只按 vivi 的要求改单张，
   * 不擅自扩大范围（避免又一次「改了没问」）。
   */
  private bubbleCountText(m: ChatMessage): string {
    return this.msgIsVideo(m) ? '1 个' : '1 张';
  }

  /** 5.0.72：固定方框时恒返回 `maxSide`，否则按比例算（供 @Builder 内表达式调用） */
  private boxSide(path: string, maxSide: number, fixedSquare: boolean): number {"""

# =====================================================================
# 改 3b：同步更新 bubbleHintOf 文档注释里的旧文案描述（否则注释会过时）
# =====================================================================
OLD3B = """   *   '点击查看 ›' -> '已存入相册 · 点击打开 ›'（多 7 个字符）。"""
NEW3B = """   *   '点击查看' -> '已存入相册，点击查看'（5.0.74 改成用户指定口径）。"""

# =====================================================================
# 改 3：整段重写 chatFileBubble（竖排 + 左下角提示 + 带数量）
# =====================================================================
OLD3 = """  chatFileBubble(m: ChatMessage, mediaPath: string, isVideo: boolean) {
    // 5.0.35：改横排「左缩略图 + 右文件名」（像文件页那样，但不用那么长），整体更矮。
    Row({ space: 8 }) {
      if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
        // ★ 5.0.72：48 -> `GRID_SIDE`(88)，并**固定方框**（vivi 诉求②③：
        //   「单张图片目前是很小的窗口，也固定一下大小，和气泡里的缩略图框一样大」）
        this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)
      }
      Column({ space: 2 }) {
        Text(m.incoming ? '收到文件' : '已发送文件')
          .fontSize(11)
          .fontColor(m.incoming ? C_SUB : '#DCE8FF')
        // ★ 5.0.55（vivi 2026-10-02）：**图片/视频不再显示文件名** ——
        //   缩略图已经说明内容了，再挂一串 `IMG_20260907_092804.jpg` 只是噪音。
        //   非媒体的文件（zip / pdf / apk…）没有缩略图，文件名是**唯一**的标识，
        //   必须保留。判据用「有没有可显示的媒体」而不是扩展名 ——
        //   后者在媒体还没落盘时会把文件名闪出来一下再消失。
        if (!(mediaPath.length > 0 && this.isMediaName(mediaPath))) {
          // 5.0.50：文件名**必须**带宽度上限 —— wrapContent 的 Row 会用「无限宽」
          //   测量子项，长文件名单行摊开、直接画出气泡背景之外
          //   （vivi 反馈「气泡中文件名会溢出气泡」）。
          //   `maxLines(2)` 只有拿到有限宽度才会真的折行，所以把约束一路下沉到 Text。
          Text(m.content)
            .fontSize(15)
            .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
            .maxLines(2)
            .wordBreak(WordBreak.BREAK_ALL)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .constraintSize({ maxWidth: '100%' })
        }
        if (m.incoming && !this.chatSelectMode) {
          // 只有「收到的」才给入口：收到的文件落在沙箱里，
          // 系统「文件管理」看不到，不指路用户就找不到。
          // 自己发出去的原文件还在用户自己手上，不需要跳。
          Text(this.bubbleHintOf(m, mediaPath))
            .fontSize(10)
            .fontColor(C_PRIMARY)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .constraintSize({ maxWidth: '100%' })
        }
      }
      // 5.0.36：不再 `layoutWeight(1)` 撑满 —— 气泡按文件名长度自适应收缩，
      // 长名字才长到 maxWidth 上限（88%），短名字就短短一条。
      // 5.0.50：加 `maxWidth: '100%'` 把外层的 88% 上限**透传**给内部文本 ——
      //   这是「既自适应又不溢出」的关键（只靠 Row 上那一条约束不够）。
      .alignItems(HorizontalAlign.Start)
      .constraintSize({ maxWidth: '100%' })
    }
    .alignItems(VerticalAlign.Center)
    .constraintSize({ maxWidth: '88%' })
    .padding({ left: 10, right: 10, top: 6, bottom: 6 })
    .backgroundColor(m.incoming ? C_CARD : C_PRIMARY)
    .borderRadius(10)
  }"""
NEW3 = """  chatFileBubble(m: ChatMessage, mediaPath: string, isVideo: boolean) {
    // ★★ 5.0.74（vivi 20:11）：整段重写成**竖排**，让提示行落到**左下角**、
    //   与宫格 `chatMediaBubble` 的位置一致。
    // ⚠️ 取舍变更说明：5.0.35 当初改成**横排**（左图右名）是为了「像文件页那样矮」，
    //   现在按 vivi 要求让位给「与宫格一致」—— **不是回退**。
    // ⚠️ 为什么整段重写而不是「往 Row 里再插一层 Column」：插入法要同时维护
    //   上下两层的收尾括号，dry-run 里实测**结构就错乱了**（留下裸 `{`）。
    //   改层级结构时，**整段重写比插入更可控**（5.0.72 已栽过一次：
    //   helper 插到 `@Builder` 标记与函数之间 ⇒ 标记配错函数）。
    // ⚠️ 外层 Row 的 `Blank()` 顶开（自己发的靠右）在 `chatBubble` 里，不在这里。
    Row() {
      Column({ space: 3 }) {
        // 「收到文件 / 已发送文件」：宫格那边是「发送方名 + 时间」，
        //   单张保留原措辞，只把它放在缩略图**上方**。
        Text(m.incoming ? '收到文件' : '已发送文件')
          .fontSize(11)
          .fontColor(m.incoming ? C_SUB : '#DCE8FF')
        if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
          // ★ 5.0.72：48 -> `GRID_SIDE`(88) + 固定方框；5.0.73：改 `Cover` 铺满
          this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)
        } else {
          // ★ 5.0.55（vivi 2026-10-02）：**图片/视频不显示文件名**（缩略图已说明内容）。
          //   非媒体的文件（zip / pdf / apk…）没有缩略图，文件名是**唯一**标识，必须保留。
          //   ⚠️ 5.0.50：文件名**必须**带宽度上限 —— wrapContent 的容器会用「无限宽」
          //   测量子项，长文件名单行摊开、直接画出气泡背景之外。
          //   `maxLines(2)` 只有拿到有限宽度才会真的折行，所以把约束一路下沉到 Text。
          Text(m.content)
            .fontSize(15)
            .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
            .maxLines(2)
            .wordBreak(WordBreak.BREAK_ALL)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .constraintSize({ maxWidth: '100%' })
        }
        if (m.incoming && !this.chatSelectMode) {
          // ★ 5.0.74：与宫格**同款** —— `N 张/个 · 提示`，落在**左下角**。
          //   只有「收到的」才给入口：收到的文件落在沙箱里，系统「文件管理」看不到，
          //   不指路用户就找不到。自己发出去的原文件还在用户手上，不需要跳。
          Text(`${this.bubbleCountText(m)} · ${this.bubbleHintOf(m, mediaPath)}`)
            .fontSize(10)
            .fontColor(C_PRIMARY)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .constraintSize({ maxWidth: '100%' })
        }
      }
      // 5.0.36：不再 `layoutWeight(1)` 撑满 —— 气泡按内容自适应收缩。
      // 5.0.50：`maxWidth: '100%'` 把外层的 88% 上限**透传**给内部文本。
      .alignItems(HorizontalAlign.Start)
      .constraintSize({ maxWidth: '100%' })
    }
    .alignItems(VerticalAlign.Center)
    .constraintSize({ maxWidth: '88%' })
    .padding({ left: 10, right: 10, top: 6, bottom: 6 })
    .backgroundColor(m.incoming ? C_CARD : C_PRIMARY)
    .borderRadius(10)
  }"""

OLD4 = '"versionCode": 5000073'
NEW4 = '"versionCode": 5000074'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 文案口径'),
                      (OLD3B, NEW3B, '改3b 注释里的旧文案'),
                      (OLD2, NEW2, '改2 数量 helper'),
                      (OLD3, NEW3, '改3 整段重写')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD4) == 1
v2 = v2.replace(OLD4, NEW4, 1)
assert v2.count('"versionName": "5.0.73"') == 1
v2 = v2.replace('"versionName": "5.0.73"', '"versionName": "5.0.74"', 1)

# ---- 不变量 ----
assert s2.count('private bubbleCountText(m: ChatMessage): string {') == 1
assert s2.count("return this.msgIsVideo(m) ? '1 个' : '1 张';") == 1
assert s2.count('`${this.bubbleCountText(m)} · ${this.bubbleHintOf(m, mediaPath)}`') == 1
assert "const inAlbum: string = '已存入相册，点击查看';" in s2
assert "const notYet: string = '点击查看';" in s2
assert "return notYet + ' '.repeat(gap);" in s2, '等宽补齐必须保留'
# 竖排结构：Row 内只有一个 Column，且提示行在 Column 内
_b = s2.split('  chatFileBubble(')[1].split('\n  }\n')[0]
assert _b.count('Column({ space: 3 }) {') == 1, '竖排 Column 应恰好一个'
assert _b.count('Row({ space: 8 }) {') == 0, '旧的横排 Row 应已移除'
assert _b.count('Row() {') == 1, '外层 Row 应无 space'
# 旧文案必须从**代码**里消失（文档注释允许保留历史描述）
_code = '\n'.join(l for l in s2.split('\n')
                  if not l.strip().startswith('//')
                  and not l.strip().startswith('*')
                  and not l.strip().startswith('/*'))
assert '已存入相册 · 点击打开 ›' not in _code, '旧文案仍在代码里'
assert '点击查看 ›' not in _code, '旧文案仍在代码里'
# 前几轮修复仍在
assert 'this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)' in s2
assert 'this.mediaFitOf(fixedSquare)' in s2
assert '${this.groupMediaSig(g)}|${this.groupGoneSig(g)}' in s2
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000074' % (len(s_idx), len(s2)))
