# -*- coding: utf-8 -*-
"""v5.0.71 —— 治「存相册成功后闪一下」：外层气泡 key 的 `groupAlbumSig` 只保留「已删」。

★★★ 本轮定位到的**结构性**根因（前九轮都在改内层签名，从没动过外层）。

【真凶】
最外层 `List` 的 `ForEach` key（`Index.ets:6384`）：
    `${g.key}|${this.videoThumbTick}|${this.groupMediaSig(g)}|${this.groupAlbumSig(g)}`

而 `groupAlbumSig`（:1904）逐条读 `albumPartOf(mid, 0, 0).length > 0`：
存相册时它从「无 uri」变成「有 uri」⇒ 该位从 `0` 变 `1` ⇒ **key 变**
⇒ **整颗气泡（`ListItem`）销毁重建** ⇒ 闪。

★ 为什么前九轮都不对症：5.0.63 把**内层** `thumbSigOf` 改成了
  `id:src:rot`（已不含 albumPart），我一直在内层打转，
  而**外层这个 `groupAlbumSig` 仍在读 albumPart**，从没动过。

【为什么不能简单删掉 groupAlbumSig】
`mediaGoneFromAlbum`（已删角标的唯一判据，:3439）第一行就是
「有相册 uri ⇒ 返回 false」：
    存相册前：有 thumb + 沙箱已删 + 无 uri ⇒ **true**  （显示「已删」）
    存相册后：有 uri ⇒ **false**                        （「已删」角标要消失）
⚠️ 这个翻转**必须靠重建才能刷掉**，删掉 key 分量会导致角标一直挂着。

【本轮方案（vivi 选 B）：拆分「已存入」与「已删」两种变化】
只有**「已删」翻转**才触发重建；**「已存入」不触发**：
  - 「已存入」的提示由 `bubbleHintOf` 的文案承载，而 5.0.70 已把它**等宽化**
    ⇒ 文案能变、宽度不变 ⇒ 不需要重建也不会闪；
  - 「已删」角标只能靠重建刷新 ⇒ 保留它的触发。

实现：新增 `groupGoneSig`（只读 `mediaGoneFromAlbum`），替换外层 key 里的
     `groupAlbumSig`。`groupAlbumSig` 保留（文件页那处 key 还在用，:5749 附近
     的同类逻辑不动），只是消息页外层不再拿它当 key 分量。

⚠️ 已知遗留：`videoThumbTick` 也是**整表级**信号（任意视频首帧解码完成就 ++
   ⇒ 全部气泡重建）。视频多的场景仍会闪。本轮**不动**它 —— 它是 5.0.55
   为了「异步解出的视频首帧能出现」而故意加的，拿掉会让视频缩略图不刷新，
   属于另一个话题，需单独一轮。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.71' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5071pre'), (VER, 'app.json5.v5071pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：新增 groupGoneSig（只读「已删」判据）
# =====================================================================
OLD1 = """  private groupAlbumSig(g: ChatGroup): string {"""
NEW1 = """  /**
   * ★ 5.0.71：组内**每条**消息的「已删」角标签名（**消息页外层气泡 key 用**）。
   *
   * ★★★ 为什么不能用 `groupAlbumSig` 当外层 key（这是「闪」的真正结构性原因）：
   *   `groupAlbumSig` 逐条读 `albumPartOf(mid, 0, 0).length > 0`，
   *   而「存相册」这个动作**恰好就是**把 uri 从空变成有 ⇒ 该位 `0 -> 1`
   *   ⇒ **外层 ForEach key 变** ⇒ **整颗气泡（`ListItem`）销毁重建** ⇒ 闪。
   *   5.0.63 已把**内层** `thumbSigOf` 改成不含 albumPart 的 `id:src:rot`，
   *   但**外层这一处一直还在读 albumPart** —— 前九轮都在内层打转，漏了它。
   *
   * 【为什么不能干脆删掉】
   *   `mediaGoneFromAlbum`（已删角标的唯一判据，:3439）第一行就是
   *   「有相册 uri ⇒ 返回 false」，所以存相册时它会 **`true -> false`**：
   *       存相册前：有 thumb + 沙箱已删 + 无 uri ⇒ true  （显示「已删」）
   *       存相册后：有 uri                        ⇒ false （角标要消失）
   *   这个翻转**只能靠重建刷新**，删掉 key 分量会让「已删」角标一直挂着。
   *
   * 【所以只保留「已删」这一半】
   *   - 「已删」翻转 ⇒ 保留触发（角标是唯一提示途径，必须刷）；
   *   - 「已存入」 ⇒ **不触发**：提示由 `bubbleHintOf` 的文案承载，
   *     而 5.0.70 已把那条文案**等宽化** ⇒ 文案能变而宽度不变 ⇒ 无需重建。
   */
  private groupGoneSig(g: ChatGroup): string {
    let s: string = '';
    for (let i: number = 0; i < g.msgs.length; i++) {
      s += this.mediaGoneFromAlbum(g.msgs[i], 0) ? '1' : '0';
    }
    return s;
  }

  private groupAlbumSig(g: ChatGroup): string {"""

# =====================================================================
# 改 2：外层 key 换掉 groupAlbumSig -> groupGoneSig
# =====================================================================
OLD2 = """            // ⚠️ key 带上 `videoThumbTick`：视频首帧是**异步**解出来的，
            //    key 不变的话 ForEach 会复用旧行、缩略图永远不出现。
            //    List 是懒加载的，只重建可见那几行，代价可忽略。
            // ★ 5.0.55：还要带上组内**每条**的媒体路径与相册条目 ——
            //   路径从空变实、相册条目从无到有，都要让这一行重建。
          }, (g: ChatGroup) => `${g.key}|${this.videoThumbTick}|${this.groupMediaSig(g)}|${this.groupAlbumSig(g)}`)"""
NEW2 = """            // ⚠️ key 带上 `videoThumbTick`：视频首帧是**异步**解出来的，
            //    key 不变的话 ForEach 会复用旧行、缩略图永远不出现。
            //    List 是懒加载的，只重建可见那几行，代价可忽略。
            // ★ 5.0.55：带上组内**每条**的媒体路径 ——
            //   路径从空变实要让这一行重建（缩略图源变了）。
            // ★★ 5.0.71：相册那一维**从 `groupAlbumSig` 换成 `groupGoneSig`** ——
            //   「存相册」会让 uri 从空变有 ⇒ `groupAlbumSig` 必变 ⇒
            //   **整颗气泡销毁重建**（这才是「存完闪一下」的结构性原因）。
            //   而「已存入」的提示已由 5.0.70 的**等宽文案**承载，无需重建；
            //   只有「已删」角标翻转（true->false）仍需重建刷掉 ⇒ 只保留它。
          }, (g: ChatGroup) => `${g.key}|${this.videoThumbTick}|${this.groupMediaSig(g)}|${this.groupGoneSig(g)}`)"""

OLD3 = '"versionCode": 5000070'
NEW3 = '"versionCode": 5000071'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 新增 groupGoneSig'),
                      (OLD2, NEW2, '改2 外层 key 换分量')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD3) == 1
v2 = v2.replace(OLD3, NEW3, 1)
assert v2.count('"versionName": "5.0.70"') == 1
v2 = v2.replace('"versionName": "5.0.70"', '"versionName": "5.0.71"', 1)

# ---- 不变量 ----
assert s2.count('private groupGoneSig(g: ChatGroup): string {') == 1
# 外层 key 已换
outer = 'this.groupMediaSig(g)}|${this.groupGoneSig(g)}'
assert outer in s2, '外层 key 未换成分'
assert '${this.groupMediaSig(g)}|${this.groupAlbumSig(g)}' not in s2, '外层仍用 groupAlbumSig'
# groupAlbumSig 本身保留（别处可能还在用）
assert s2.count('private groupAlbumSig(g: ChatGroup): string {') == 1
# 已删判据完好
assert 'if (this.albumPartOf(m.id, k, 0).length > 0) {' in s2
# 前几轮修复仍在
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')
assert "return notYet + ' '.repeat(gap);" in s2       # 5.0.70 等宽文案
assert 'this.chat = v;' in s2                          # 5.0.66
assert '5.0.68诊断' in s2                              # 诊断日志保留
assert '@State albumIndex' in s2 and '@State chatGroups' in s2

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000071' % (len(s_idx), len(s2)))
