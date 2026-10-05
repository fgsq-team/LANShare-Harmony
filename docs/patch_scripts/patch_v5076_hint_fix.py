# -*- coding: utf-8 -*-
"""v5.0.76 —— 修 bubbleHintOf 判据丢失 + 三条文案需求（vivi 2026-10-02 20:30）。

【① 单张「不管有没有保存都提示长按」—— 根因是判据被整段重写时弄丢了】
5.0.74 我用「整段重写」改 `chatFileBubble` 时，顺手把 `bubbleHintOf` 也重写了，
而**新版本里根本没写判据** —— 开头就是 `const inAlbum = ...`，
无条件 `return notYet`（= `长按保存到相册，点击查看`）。
⇒ 所以单张气泡无论存没存，都显示「长按保存到相册，点击查看」。
⚠️ 这是「整段重写」的固有风险：**重写时容易只抄「长相」漏抄「判据」** ——
   编译能过、行为静默错误。（5.0.74 当时只 dry-run 看了 `chatFileBubble`，
   没回看 `bubbleHintOf`。）

修法：把判据补回去 —— `albumPartOf(m.id, 0, 0).length > 0`。

【② 文案（vivi 20:30 定稿）】
    已存   → `已存入相册`      （去掉「，点击查看」）
    未存   → `长按存入相册`    （改用「存入」，并去掉「，点击查看」）
    已删除 → `已删除`
⚠️ 三个分支**仍必须等宽**（5.0.70 的规矩）—— 补齐逻辑改成「按最长那条」。

【③ 删掉所有「点击查看」】
两个方法里的文案都换掉 ⇒ 单张与宫格**都不再有「点击查看」**。
⚠️ 注意：点击行为**不变**（整颗气泡的 onClick 照旧跳预览/相册），
   只是**文案里不再承诺「点击查看」** —— 因为存了之后点开的是**系统相册**，
   写「点击查看」本来就不准确（vivi 20:11 起文案已反复调整过三版）。

【④ 「全删了还提示长按保存」→ 改成「已删除」】
场景：一批图**全部**在系统相册里被删 ⇒ uri 全被 5.0.75 的
`probeAlbumOnEnterChat` 清掉 ⇒ 而「未存」分支只看 `uri.length === 0`，
**分不清「从没存过」和「存过又被删」** ⇒ 误报「长按保存到相册」。
判据：任一张满足 `mediaGoneFromAlbum(m, 0)`（= 无 uri + 有缩略图 + 沙箱也没了
⇒ 确实存过又被删）⇒ 整组按「已删除」处理。
⚠️ 用**整组任一张**而非全部：与 5.0.75 的 `bubbleHintOfGroup` 同口径。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.76' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5076pre'), (VER, 'app.json5.v5076pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：bubbleHintOfGroup —— 三分支（已存 / 未存 / 已删除）+ 补回判据
# =====================================================================
OLD1 = """  private bubbleHintOfGroup(g: ChatGroup): string {
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
  }"""
NEW1 = """  private bubbleHintOfGroup(g: ChatGroup): string {
    // ★ 5.0.76（vivi 20:30 定稿）：三个分支，且**判据按优先级**
    //   1) 任一张**已删除**（存过又被删）  => `已删除`
    //   2) 任一张**已存**（有 uri）      => `已存入相册`
    //   3) 否则（都没存过）               => `长按存入相册`
    // ⚠️ 「已删除」必须**排在最前**：存过又被删之后 uri 已被清掉（5.0.75 的
    //   `probeAlbumOnEnterChat`），此时 part 0 为空，与「从没存过」**无法区分**
    //   ⇒ 只看 uri 会把「全删了」误报成「长按保存到相册」（vivi 20:30 反馈）。
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.mediaGoneFromAlbum(g.msgs[i], 0)) {
        return this.padHint(Index.HINT_GONE);
      }
    }
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.albumPartOf(g.msgs[i].id, 0, 0).length > 0) {
        return this.padHint(Index.HINT_IN_ALBUM);
      }
    }
    return this.padHint(Index.HINT_NOT_YET);
  }"""

# =====================================================================
# 改 2：bubbleHintOf —— 补回被弄丢的判据 + 同样的三分支
# =====================================================================
OLD2 = """    const inAlbum: string = '已存入相册，点击查看';
    const notYet: string = '长按保存到相册，点击查看';
    // 较长的那条为准，短的那条补半角空格 ⇒ 两个分支**渲染宽度恒定**
    const gap: number = inAlbum.length - notYet.length;
    if (gap <= 0) {
      return notYet;
    }
    return notYet + ' '.repeat(gap);
  }"""
NEW2 = """    // ★★ 5.0.76：**判据在这里** —— 5.0.74 整段重写时把它弄丢了，
    //   导致单张气泡无论存没存都显示「长按保存到相册，点击查看」（vivi 20:30 反馈）。
    // ⚠️ 教训：整段重写容易只抄「长相」漏抄「判据」—— 编译能过、行为静默错误。
    //   所以「整段重写」之后必须**回读被改方法的每一行**，而不只看新写的部分。
    if (this.mediaGoneFromAlbum(m, 0)) {
      return this.padHint(Index.HINT_GONE);
    }
    if (this.albumPartOf(m.id, 0, 0).length > 0) {
      return this.padHint(Index.HINT_IN_ALBUM);
    }
    return this.padHint(Index.HINT_NOT_YET);
  }

  /**
   * ★ 5.0.76：把提示文案**补齐到同一宽度**（5.0.70 立的规矩，必须一直守住）。
   *
   * ⚠️ 存相册那一刻 uri 从无变有 ⇒ 文案从「长按存入相册」切到「已存入相册」，
   *   两者字数不同 ⇒ 若不补齐就会**整行重排 ⇒ 闪一下**（5.0.70~5.0.75 反复踩过）。
   *   三个分支（含「已删除」）统一按**最长那条**补半角空格。
   */
  private padHint(s: string): string {
    const gap: number = Index.HINT_MAX_LEN - s.length;
    return gap > 0 ? `${s}${' '.repeat(gap)}` : s;
  }"""

# =====================================================================
# 改 3：加三个文案常量（与 GRID_SIDE 放一起）
# =====================================================================
OLD3 = """  private static GRID_SIDE: number = 88;"""
NEW3 = """  private static GRID_SIDE: number = 88;
  // ★ 5.0.76：气泡底部提示的**三个文案**（vivi 20:30 定稿）
  /** 已存入系统相册（点击可跳系统相册，文案不再写「点击查看」——存了之后跳的是相册） */
  private static readonly HINT_IN_ALBUM: string = '已存入相册';
  /** 还没存：提示用户长按气泡触发保存 */
  private static readonly HINT_NOT_YET: string = '长按存入相册';
  /** 存过、但已被用户在系统相册里删掉 */
  private static readonly HINT_GONE: string = '已删除';
  /** 三个里最长的那条长度 —— 等宽补齐的基准（5.0.70 的规矩） */
  private static readonly HINT_MAX_LEN: number = Index.HINT_IN_ALBUM.length > Index.HINT_NOT_YET.length
    ? (Index.HINT_IN_ALBUM.length > Index.HINT_GONE.length ? Index.HINT_IN_ALBUM.length : Index.HINT_GONE.length)
    : (Index.HINT_NOT_YET.length > Index.HINT_GONE.length ? Index.HINT_NOT_YET.length : Index.HINT_GONE.length);"""

OLD4 = '"versionCode": 5000075'
NEW4 = '"versionCode": 5000076'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 宫格三分支'),
                      (OLD2, NEW2, '改2 单张补回判据 + padHint'),
                      (OLD3, NEW3, '改3 文案常量')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD4) == 1
v2 = v2.replace(OLD4, NEW4, 1)
assert v2.count('"versionName": "5.0.75"') == 1
v2 = v2.replace('"versionName": "5.0.75"', '"versionName": "5.0.76"', 1)

# ---- 不变量 ----
assert s2.count('private padHint(s: string): string {') == 1
for c in ('HINT_IN_ALBUM', 'HINT_NOT_YET', 'HINT_GONE'):
    assert s2.count('Index.%s' % c) >= 2, (c, s2.count('Index.%s' % c))
assert s2.count('private static readonly HINT_IN_ALBUM: string = \'已存入相册\';') == 1
assert s2.count('private static readonly HINT_NOT_YET: string = \'长按存入相册\';') == 1
assert s2.count('private static readonly HINT_GONE: string = \'已删除\';') == 1
# 判据必须在（①的修复点）
assert s2.count('if (this.mediaGoneFromAlbum(m, 0)) {') == 2  # :6170 宫格「已删」角标 + 本轮新增的单张判据
assert s2.count('if (this.mediaGoneFromAlbum(g.msgs[i], 0)) {') == 1
# 「点击查看」必须从代码里彻底消失（注释可留历史）
_code = '\n'.join(l for l in s2.split('\n')
                  if not l.strip().startswith('//')
                  and not l.strip().startswith('*')
                  and not l.strip().startswith('/*'))
assert '点击查看' not in _code, '仍有「点击查看」'
assert '长按保存到相册' not in _code, '仍有旧文案'
# 前几轮修复仍在
assert 'this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)' in s2
assert 'this.mediaFitOf(fixedSquare)' in s2
assert 'this.probeAlbumOnEnterChat();' in s2
assert '${this.groupMediaSig(g)}|${this.groupGoneSig(g)}' in s2
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000076' % (len(s_idx), len(s2)))
