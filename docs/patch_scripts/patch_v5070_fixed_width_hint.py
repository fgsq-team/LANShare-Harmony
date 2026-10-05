# -*- coding: utf-8 -*-
"""v5.0.70 —— 治「存相册成功后闪一下」：**气泡底部提示文案等宽化**。

★★★ 本轮有**日志证据 + 代码定位**，不是推断。

【为什么前四轮全都不对症】
5.0.63/64/67/69 改的全是「缩略图层」（key / 预生成 / TRUNC / @State 降级），
但 5.0.68 的诊断日志证明：**缩略图 src 签名从存相册前到后一字未变**
（`[c1-…jpg|rot0|gone0] x6` 前后完全一致）⇒ 缩略图压根不是闪的原因。

【真凶】
`bubbleHintOf()`（:2958）读 `albumPartOf(m.id, 0, 0).length > 0`：
    存相册前 -> 无 uri -> '点击查看 ›'
    存相册后 -> 有 uri -> '已存入相册 · 点击打开 ›'
它被渲染在**两处**消息页 UI：
    :5914  宫格气泡底部  `${g.msgs.length} 张 · ${bubbleHintOf(...)}`
    :6088  单张气泡底部  `bubbleHintOf(m, mediaPath)`
两处的容器都是 `constraintSize({ maxWidth: '92%' })` —— **是上限、不是固定宽**
⇒ 宽度由内容决定 ⇒ **文案多 7 个字 ⇒ 整行重排 ⇒ 视觉上「闪一下」。

【为什么 5.0.69 降级 chatMediaPaths 仍闪】
日志（5.0.69 实测）存相册那一行仍是 `mediaGroups=1 albumIndex=1`：
    - `chatMediaGroups` 同样是**没有消费者的 @State**（本轮顺带降级）
    - `albumIndex` 是**有真消费者的**（`albumPartOf` -> 气泡文案 / 缩略图源 /
      已删角标），**必须保留 @State** ⇒ 换引用无法避免
⇒ 既然 `albumIndex` 的换引用躲不掉，**唯一能消掉重排的办法就是让文案宽度恒定**。

【修法：等宽填充】
`bubbleHintOf` 改成按「长短两条文案里较长的那条」补足空格，
两个分支返回**字节数相同**的字符串 ⇒ Text 渲染宽度恒定 ⇒ 换 `albumIndex` 也不再重排。

⚠️ 为什么用「空格补齐」而不是改文案措辞：
   - 措辞改动无法保证**像素级等宽**（中文字形宽度不同、字体渲染有差异）
     ⇒ 只能「减小概率」，治不干净 —— 这正是前四轮反复失败的教训；
   - 空格补齐是**结构上恒定**，一次解决。
⚠️ 补齐用的是**半角空格**（U+0020）。全角空格（U+3000）宽度是全角的，
   会补得过头；且这两个字符串在 5.0.39 的注释里已被引用，形态不宜乱改。
⚠️ 不用不可见字符（如 U+200B）：部分渲染引擎对零宽字符处理不一致，
   反而可能引入新的宽度不确定性。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.70' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5070pre'), (VER, 'app.json5.v5070pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：bubbleHintOf 等宽化（核心）
# =====================================================================
OLD1 = """  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {
    // 5.0.39：已经在相册里了，就明确告诉用户「点一下是去相册」
    return this.albumPartOf(m.id, 0, 0).length > 0 ? '已存入相册 · 点击打开 ›' : '点击查看 ›';
  }"""
NEW1 = """  /**
   * 气泡底部的提示文案（**两个分支等宽**，见 5.0.70 的说明）。
   *
   * ★★★ 5.0.70：这里返回的字符串**长度必须相同**。
   *
   * 【为什么】存相册会让 `albumPartOf(m.id,0,0)` 从空变成有 uri ⇒ 本方法返回
   *   '点击查看 ›' -> '已存入相册 · 点击打开 ›'（多 7 个字符）。
   *   它被渲染在**两处**消息页 UI（宫格气泡底部、单张气泡底部），两处容器都是
   *   `constraintSize({ maxWidth: '92%' })` —— **是上限、不是固定宽**
   *   ⇒ 宽度由内容决定 ⇒ **文案变长 ⇒ 整行重排 ⇒ 视觉上「闪一下」**。
   *
   * 【为什么不能只改措辞】中文字形宽度不同、字体渲染有像素差 ⇒ 改措辞只能
   *   「减小概率」，治不干净。5.0.63/64/67/69 连着四轮都改在**缩略图层**
   *   （key / 预生成 / TRUNC / @State 降级），而 5.0.68 诊断日志证明缩略图
   *   `src` 签名**从存相册前到后一字未变** ⇒ 全都不对症。
   *   ⇒ 只有**结构上等宽**才是一次性的根治。
   *
   * 【为什么不能跳过 `albumIndex` 的换引用】`albumIndex` 是**有真消费者的**
   *   `@State`（气泡文案 / 缩略图源 / 已删角标都经 `albumPartOf` 读它），
   *   换引用躲不掉；既然躲不掉，就让**被它驱动的内容宽度恒定**。
   *
   * ⚠️ 用**半角空格**（U+0020）补齐：全角空格（U+3000）宽度是全角的，会补过头；
   *   也不用零宽字符（U+200B）—— 部分渲染引擎处理不一致，反而引入新的不确定性。
   * ⚠️ 补齐发生在**文案尾部**，视觉上就是「后面多个空格」，看不出差别。
   */
  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {
    // 5.0.39：已经在相册里了，就明确告诉用户「点一下是去相册」
    const inAlbum: string = '已存入相册 · 点击打开 ›';
    const notYet: string = '点击查看 ›';
    // 较长的那条为准，短的那条补半角空格 ⇒ 两个分支**渲染宽度恒定**
    const gap: number = inAlbum.length - notYet.length;
    if (gap <= 0) {
      return notYet;
    }
    return notYet + ' '.repeat(gap);
  }"""

# =====================================================================
# 改 2：chatMediaGroups 一并降级（顺带，日志显示它也没有消费者）
# =====================================================================
OLD2 = """  @State chatMediaGroups: Map<string, string[]> = new Map<string, string[]>();"""
NEW2 = """  /**
   * 每条消息 id -> 这一批媒体文件的沙箱路径（顺序 = 传输顺序）。
   *
   * ⚠️ 5.0.70：**从 `@State` 降级为普通字段**（依据见 `chatMediaPaths` 的注释
   *   —— 同一类问题：没有 UI 消费者的 `@State` 换引用照样触发全组件重绘）。
   *   唯一读取者是 `mediaPathsOf()`，而它 / `mediaCountOf` / `mediaPathAt`
   *   在整个 UI 里**零调用点**（全是历史遗留的死代码）。
   *   ⚠️ 若将来要在 UI 里用画廊的路径列表，**必须改回 @State**。
   */
  private chatMediaGroups: Map<string, string[]> = new Map<string, string[]>();"""

OLD3 = """  /** ★ 5.0.64：`chatMediaGroups` 换引用（经闸门） */
  private chatGroupNext2(v: Map<string, string[]>): void {
    if (this.stateSwapDepth > 0) {
      this.chatMediaGroupsNext = v;
      return;
    }
    this.chatMediaGroups = v;
  }"""
NEW3 = """  /**
   * ★ 5.0.70：`chatMediaGroups` 落地（**已降级为普通字段，不再走闸门**）。
   *
   * 与 `chatPathsNext2` 同理：去掉 `@State` 后换引用不再触发重绘，闸门失去意义。
   */
  private chatGroupNext2(v: Map<string, string[]>): void {
    this.chatMediaGroups = v;
  }"""

OLD4 = '"versionCode": 5000069'
NEW4 = '"versionCode": 5000070'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 文案等宽'),
                      (OLD2, NEW2, '改2 降级 chatMediaGroups'),
                      (OLD3, NEW3, '改3 落地不经闸门')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD4) == 1
v2 = v2.replace(OLD4, NEW4, 1)
assert v2.count('"versionName": "5.0.69"') == 1
v2 = v2.replace('"versionName": "5.0.69"', '"versionName": "5.0.70"', 1)

_code = '\n'.join(l for l in s2.split('\n')
                  if not l.strip().startswith('//')
                  and not l.strip().startswith('*')
                  and not l.strip().startswith('/*'))
# 降级到位
assert '@State chatMediaGroups' not in _code, 'chatMediaGroups 仍是 @State'
assert 'private chatMediaGroups: Map<string, string[]>' in _code
# 等宽逻辑在位
assert s2.count("const inAlbum: string = '已存入相册 · 点击打开 ›';") == 1
assert s2.count("return notYet + ' '.repeat(gap);") == 1
# 消费者仍在（bubbleHintOf 是 albumIndex 的真消费者，必须保持 @State）
assert '@State albumIndex' in s2
assert s2.count('this.bubbleHintOf(') == 2, s2.count('this.bubbleHintOf(')   # :5914 宫格 + :6088 单张
# 前几轮修复仍在
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')
assert 'this.chat = v;' in s2
assert '@State chatGroups' in s2
assert '5.0.68诊断' in s2   # 诊断日志保留

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000070' % (len(s_idx), len(s2)))
