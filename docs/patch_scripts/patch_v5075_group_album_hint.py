# -*- coding: utf-8 -*-
"""v5.0.75 —— 修「已存入相册」提示不出现 + 定稿文案（vivi 2026-10-02 20:19）。

【现象】vivi 反馈：已经保存到相册了，气泡底部仍只显示「N 张 · 点击查看」，
**「已存入相册」那句从来没出现过**。

【根因】**判据用错了对象**，不是 key 没接上。
- 外层 key 里 5.0.72 已经加了「已存入」这一维（`groupGoneSig` 第 2 项，读
  `albumPartOf(g.msgs[i].id, 0, 0)`），**接得好好的**；
- 但**文案** `bubbleHintOf(m, ...)` 在宫格那行传的是 **`g.msgs[0]`**：
      Text(`${g.msgs.length} 张 · ${this.bubbleHintOf(g.msgs[0], '')}`)
  而 `bubbleHintOf` 内部只看 `albumPartOf(m.id, 0, 0)` ——
  **只看第 1 张**。
- 存相册是**逐张**进行的（`autoSaveAlbumBatch` 循环里一张一张 `setAlbumIndex`），
  **很可能第 3 张、第 7 张先被存上，而 `msgs[0]` 那一批还没存**
  ⇒ 判据恒为「未存」⇒ 文案永远停在「点击查看」。
  ⚠️ 这与「已删」角标必须**逐张**判定（`mediaGoneFromAlbum` 是按 `k` 判的）
  是同一个道理，我却在文案上偷懒只看 `msgs[0]`。

【修法】
1. `bubbleHintOf` 改成接收一个「整组消息」并**任一张已存即算已存**：
   新增重载 `bubbleHintOfGroup(g)`，宫格那行改调它；
   单张气泡只有一条消息，`bubbleHintOf` 行为不变。
   ⇒ 判据从「第 1 张」改成「**整组任一张**」，与「逐张存」的实际流程对齐。
2. 文案定稿（vivi 指定）：
     已存 → `已存入相册，点击查看`
     未存 → `长按保存到相册，点击查看`
   ⚠️ 两句长度差更大，**仍必须补半角空格保持等宽**（5.0.70 的规矩）。
   ⚠️ 未存这句从「点击查看」变成「长按保存到相册，点击查看」是**信息量增加**，
     但因为等宽，**存相册那一刻不会因宽度变化而重排**。

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
# 改 1：文案定稿（vivi 指定）
# =====================================================================
OLD1 = """    const inAlbum: string = '已存入相册，点击查看';
    const notYet: string = '点击查看';"""
NEW1 = """    // ★ 5.0.75（vivi 20:19 定稿）：未存那句补上「长按」——
    //   用户是**长按**存相册的（不是自动弹框），文案要如实反映操作方式。
    const inAlbum: string = '已存入相册，点击查看';
    const notYet: string = '长按保存到相册，点击查看';"""

# =====================================================================
# 改 2：新增「整组任一张已存即算已存」的判据
# =====================================================================
OLD2 = """  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {"""
NEW2 = """  /**
   * ★ 5.0.75：宫格气泡用的提示文案 —— 判据是「**整组任一张已存入相册**」。
   *
   * 【为什么不能用 `bubbleHintOf(g.msgs[0])`】（5.0.75 修的真 bug）
   *   存相册是**逐张**进行的（`autoSaveAlbumBatch` 循环里一张一张 `setAlbumIndex`），
   *   **很可能第 3 张、第 7 张先被存上，而 `msgs[0]` 那一批还没存**
   *   ⇒ 只看第 1 张的话，判据恒为「未存」⇒ 文案永远停在「点击查看」，
   *   用户反馈「已存入相册也没有」就是这个。
   *   ⚠️ 与「已删」角标必须**逐张**判定（`mediaGoneFromAlbum(m, k)`）是同一个道理，
   *   我却在文案上偷懒只看 `msgs[0]`。
   *
   * 【判据】
   *   任一张 `albumPartOf(msg.id, 0, 0)` 非空 ⇒ 整组按「已存」处理。
   *   这样只要用户存了其中一张，提示就切到「已存入相册」，与用户直觉一致。
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

OLD4 = '"versionCode": 5000074'
NEW4 = '"versionCode": 5000075'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 文案定稿'),
                      (OLD2, NEW2, '改2 整组判据'),
                      (OLD3, NEW3, '改3 宫格改调')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD4) == 1
v2 = v2.replace(OLD4, NEW4, 1)
assert v2.count('"versionName": "5.0.74"') == 1
v2 = v2.replace('"versionName": "5.0.74"', '"versionName": "5.0.75"', 1)

# ---- 不变量 ----
assert s2.count('private bubbleHintOfGroup(g: ChatGroup): string {') == 1
assert s2.count("const notYet: string = '长按保存到相册，点击查看';") == 2, s2.count("const notYet: string = '长按保存到相册，点击查看';")
assert s2.count("const inAlbum: string = '已存入相册，点击查看';") == 2
assert s2.count('this.bubbleHintOfGroup(g)') == 1
# 两处都要等宽补齐
assert s2.count("' '.repeat(gap)") == 2, s2.count("' '.repeat(gap)")
# 单张那处仍用 bubbleHintOf（只有一条消息）
assert s2.count('`${this.bubbleCountText(m)} · ${this.bubbleHintOf(m, mediaPath)}`') == 1
# 外层 key 的「已存入」维度仍在
assert 's += this.albumPartOf(g.msgs[i].id, 0, 0).length > 0 ? \'1\' : \'0\';' in s2
# 前几轮修复仍在
assert 'this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)' in s2
assert 'this.mediaFitOf(fixedSquare)' in s2
assert '${this.groupMediaSig(g)}|${this.groupGoneSig(g)}' in s2
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000075' % (len(s_idx), len(s2)))
