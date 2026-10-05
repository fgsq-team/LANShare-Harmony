# -*- coding: utf-8 -*-
"""
v5.1.1 修：非媒体文件（zip / pdf / apk）的气泡底部提示错显示「长按存入相册」。

【根因（读代码确认，非推测）】
5.0.76 把 `bubbleHintOf` 补成三分支（已删除 / 已存入相册 / 长按存入相册），
但**三个分支全是「媒体」语义** —— 判据只有「相册状态」，没有「是不是媒体」这一维。
而 5.0.77 把单张媒体并入宫格后，`chatFileBubble` 这条路**只剩非媒体文件**
（`groupAllMedia` 已接管所有媒体 ⇒ `chatBubble` → `chatFileBubble` 只可能是 zip/pdf/apk）
⇒ 那些文件必然落进「未存」分支 ⇒ 显示「长按存入相册」。

★ 附带第二个错：`bubbleCountText` 对非媒体也返回「1 张」⇒ 底部整行是
  `1 张 · 长按存入相册`，两个词都不对（zip 没有「张」的概念，也存不进相册）。

【修法】
- 新增常量 `HINT_FILE = '点击查看'`（非媒体唯一合理提示：点了跳沙箱预览）
- `bubbleHintOf` **最前面**加媒体判据分支：非媒体 ⇒ `HINT_FILE`
  （放最前：非媒体本来就不该问相册状态）
- 新增 `bubbleFooterText(m, mediaPath)` 统一拼整行：
  媒体 ⇒ `N 张/个 · 提示`；非媒体 ⇒ 只有 `点击查看`（不带「N 张」）
- 渲染点（`chatFileBubble` 底部）改调 `bubbleFooterText`
- `HINT_MAX_LEN` 把 `HINT_FILE` 也纳入计算（当前它更短，但别让常量成为隐含前提）

⚠️ 等宽补齐（5.0.70 的规矩）继续走 `padHint`：非媒体那行是**恒定文案**，
   不会在运行时切换 ⇒ 不存在重排闪动；补齐只是为了和媒体行视觉对齐。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 改 1：新增 HINT_FILE 常量 + HINT_MAX_LEN 纳入它
# =====================================================================
OLD1 = """  /** 存过、但已被用户在系统相册里删掉 */
  private static readonly HINT_GONE: string = '已删除';
  /** 三个里最长的那条长度 —— 等宽补齐的基准（5.0.70 的规矩） */
  private static readonly HINT_MAX_LEN: number = Index.HINT_IN_ALBUM.length > Index.HINT_NOT_YET.length
    ? (Index.HINT_IN_ALBUM.length > Index.HINT_GONE.length ? Index.HINT_IN_ALBUM.length : Index.HINT_GONE.length)
    : (Index.HINT_NOT_YET.length > Index.HINT_GONE.length ? Index.HINT_NOT_YET.length : Index.HINT_GONE.length);"""

NEW1 = """  /** 存过、但已被用户在系统相册里删掉 */
  private static readonly HINT_GONE: string = '已删除';
  /** ★ 5.1.1：**非媒体文件**（zip / pdf / apk…）的唯一合理提示。
   *  它们既没有缩略图、也存不进相册 ⇒ 说「长按存入相册」是错的（vivi 20:58 反馈）。 */
  private static readonly HINT_FILE: string = '点击查看';
  /** 四条里最长的那条长度 —— 等宽补齐的基准（5.0.70 的规矩）。
   *  ⚠️ 5.1.1：新增 HINT_FILE 后**必须一并纳入**，否则加长文案时会漏。 */
  private static readonly HINT_MAX_LEN: number = Math.max(
    Index.HINT_IN_ALBUM.length, Index.HINT_NOT_YET.length,
    Index.HINT_GONE.length, Index.HINT_FILE.length);"""

# =====================================================================
# 改 2：bubbleHintOf 最前面加「非媒体」分支
# =====================================================================
OLD2 = """    // ⚠️ 教训：整段重写容易只抄「长相」漏抄「判据」—— 编译能过、行为静默错误。
    //   所以「整段重写」之后必须**回读被改方法的每一行**，而不只看新写的部分。
    if (this.mediaGoneFromAlbum(m, 0)) {"""

NEW2 = """    // ⚠️ 教训：整段重写容易只抄「长相」漏抄「判据」—— 编译能过、行为静默错误。
    //   所以「整段重写」之后必须**回读被改方法的每一行**，而不只看新写的部分。
    //
    // ★★ 5.1.1：这里原本**只有相册状态三维、没有「是不是媒体」这一维** ⇒
    //   非媒体文件（zip/pdf/apk）必然落到「未存」分支 ⇒ 显示「长按存入相册」
    //   （vivi 20:58 反馈）。而 5.0.77 单张并入宫格后，`chatFileBubble`
    //   这条路**只剩非媒体**，所以是 100% 必现。
    //   ⇒ 判据必须**先问「是不是媒体」**，再问相册状态。
    if (mediaPath.length === 0 || !this.isMediaName(mediaPath)) {
      return this.padHint(Index.HINT_FILE);
    }
    if (this.mediaGoneFromAlbum(m, 0)) {"""

# =====================================================================
# 改 3：新增 bubbleFooterText（统一拼整行，非媒体不带「N 张」）
# =====================================================================
OLD3 = """  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {"""
NEW3 = """  /**
   * ★ 5.1.1：气泡底部**整行**提示。
   *
   * 媒体 ⇒ `N 张/个 · <相册状态>`（与宫格同款）
   * 非媒体 ⇒ 只有 `点击查看`（**不带「N 张」** —— zip/pdf/apk 没有「张」的概念，
   *   而且 5.1.1 之前那行是 `1 张 · 长按存入相册`，两个词都是错的）
   */
  private bubbleFooterText(m: ChatMessage, mediaPath: string): string {
    if (mediaPath.length === 0 || !this.isMediaName(mediaPath)) {
      return this.padHint(Index.HINT_FILE);
    }
    return `${this.bubbleCountText(m)} · ${this.bubbleHintOf(m, mediaPath)}`;
  }

  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {"""

# =====================================================================
# 改 4：渲染点改调 bubbleFooterText
# =====================================================================
OLD4 = """          Text(`${this.bubbleCountText(m)} · ${this.bubbleHintOf(m, mediaPath)}`)"""
NEW4 = """          // ★ 5.1.1：改由 bubbleFooterText 统一拼 —— 非媒体不帶「N 张」，
          //   也不再误报「长按存入相册」（它存不进相册）。
          Text(this.bubbleFooterText(m, mediaPath))"""

# =====================================================================
# 改 5：版本号 5000100 -> 5000101
# =====================================================================
OLD5 = '"versionCode": 5000100'
NEW5 = '"versionCode": 5000101'

REPL = [
    (OLD1, NEW1, '改1 HINT_FILE 常量 + MAX_LEN'),
    (OLD2, NEW2, '改2 bubbleHintOf 加非媒体分支'),
    (OLD3, NEW3, '改3 新增 bubbleFooterText'),
    (OLD4, NEW4, '改4 渲染点改调'),
]

# ---- 哨兵：已应用则干净退出 ----
s0 = io.open(IDX, encoding='utf-8').read()
SENT = "HINT_FILE"
if SENT in s0:
    print('ALREADY APPLIED (HINT_FILE 已在磁盘上)')
    sys.exit(0)

# ---- 备份 ----
os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v5111pre'), 'w', encoding='utf-8', newline='\n').write(s0)
io.open(os.path.join(BAK, 'app.json5.v5111pre'), 'w', encoding='utf-8', newline='\n').write(
    io.open(VER, encoding='utf-8').read())
print('备份完成')

# ---- 全部校验（先在内存里做完，最后统一落盘）----
s = s0
for old, new, tag in REPL:
    n = s.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s = s.replace(old, new, 1)

# ---- 不变量 ----
# ① 新方法与常量各一份
assert s.count("private static readonly HINT_FILE: string = '点击查看';") == 1
assert 'private bubbleFooterText(m: ChatMessage, mediaPath: string): string {' in s
# ② 渲染点已改调，且旧的拼法消失
assert s.count('Text(this.bubbleFooterText(m, mediaPath))') == 1
assert s.count('Text(`${this.bubbleCountText(m)} · ${this.bubbleHintOf(m, mediaPath)}`)') == 0
# ③ 宫格那行**不能**被误改（它传的是 group，自带「N 张 · 」）
assert s.count('Text(`${g.msgs.length} 张 · ${this.bubbleHintOfGroup(g)}`)') == 1
# ④ 三条媒体文案完好
for lit in ("HINT_IN_ALBUM: string = '已存入相册'",
            "HINT_NOT_YET: string = '长按存入相册'",
            "HINT_GONE: string = '已删除'"):
    assert lit in s, '媒体文案被误删: %s' % lit
# ⑤ MAX_LEN 已改成 Math.max 四参
assert 'Math.max(\n    Index.HINT_IN_ALBUM.length' in s
# ⑥ 5.1.0 的成果仍在（诊断已删、ABOUT 兜底已同步）
# ⚠️ 只查**方法定义/调用**，注释里保留一句「已移除」的说明是合理的（5.1.0 刻意留的）
assert 'private diagSnapshot(' not in s
assert 'this.diagSnapshot(' not in s
assert "const ABOUT_FALLBACK_VER: string = '5.1.0';" in s

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
print('OK  Index.ets %d -> %d' % (len(s0), len(s)))

# ---- 版本号 ----
v = io.open(VER, encoding='utf-8').read()
assert v.count(OLD5) == 1, 'versionCode 锚点异常: %d' % v.count(OLD5)
v = v.replace(OLD5, NEW5, 1)
assert v.count('"versionName": "5.1.0"') == 1
v = v.replace('"versionName": "5.1.0"', '"versionName": "5.1.1"', 1)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v)
print('OK  versionCode 5000100 -> 5000101 / 5.1.1')
