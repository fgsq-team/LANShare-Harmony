# -*- coding: utf-8 -*-
"""
5.1.47 —— 完成浮窗显示「文件大小 + 平均速度」；同样信息同步到消息页文件气泡

【vivi 需求】传输完成的浮窗显示文件大小和平均速度；这两个值也同步到消息页的气泡里。

【实现要点】
1. **平均速度**：现有的 `speedEma` 是**瞬时**速度（相邻两次上报的差值），
   传输完成时会被 `resetSpeed()` 清掉 ⇒ 浮窗上什么都看不到。
   ⇒ 新增「本次传输起始时刻」`xferStartAt`，完成时用
     `总量 / (now - xferStartAt)` 算出**平均速度**并定格。
2. **完成浮窗副行**：`接收完成 · 646.1 MB · 30.2 MB/s`
3. **消息页气泡**：`ChatMessage` 加 `meta` 字段，`appendChat`/`appendFileChat`
   透传，气泡里在文件名**下面**独立渲染一行。
   ⚠️ **刻意不改 `bubbleFooterText`** —— 它有「文案必须等宽，否则布局抖一下就闪」
   的硬约束（5.0.70 / 5.0.74 / 5.0.76 连续踩过三次），往里塞变长文案会破坏它。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
LS = os.path.join(ET, 'service', 'LanService.ets')
IX = os.path.join(ET, 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

ls = io.open(LS, encoding='utf-8', newline='').read()
ix = io.open(IX, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

SEN = 'avgSpeedText'
if SEN in ls:
    print('ALREADY APPLIED'); sys.exit(0)

B = []
def cutLS(t, o, n=''): B.append(('LS', t, o, n))
def cutIX(t, o, n=''): B.append(('IX', t, o, n))

# ═══ ① ChatMessage 加 meta ═══
cutLS('CM-meta',
      "  /** 来源：device（局域网设备）/ web（浏览器网页端）/ app（本机发出） */\n"
      "  source: string = 'device';\n",
      "  /** 来源：device（局域网设备）/ web（浏览器网页端）/ app（本机发出） */\n"
      "  source: string = 'device';\n"
      "  /**\n"
      "   * ★ 5.1.47：文件消息的**副信息**（`646.1 MB · 30.2 MB/s`）——\n"
      "   *   文件大小 + **平均**速度。空串 = 不显示（如纯文本消息）。\n"
      "   */\n"
      "  meta: string = '';\n")

# ═══ ② appendChat 加 meta 参数 ═══
cutLS('AC-sig',
      "    kind: string = 'text', files: string = '', batchId: string = ''\n"
      "  ): void {\n",
      "    kind: string = 'text', files: string = '', batchId: string = '',\n"
      "    meta: string = ''\n"
      "  ): void {\n")
cutLS('AC-assign',
      "    m.source = source;\n"
      "    m.kind = kind;\n"
      "    m.files = files;\n",
      "    m.source = source;\n"
      "    m.kind = kind;\n"
      "    m.files = files;\n"
      "    m.meta = meta;   // ★ 5.1.47\n")

# ═══ ③ appendFileChat 加 meta 参数 ═══
cutLS('AFC-sig',
      "  private appendFileChat(incoming: boolean, peerName: string, peerIp: string,\n"
      "                         label: string, names: string[], source: string): void {\n",
      "  private appendFileChat(incoming: boolean, peerName: string, peerIp: string,\n"
      "                         label: string, names: string[], source: string,\n"
      "                         meta: string = ''): void {   // ★ 5.1.47\n")

# ═══ ④ 记录传输起始时刻 ═══
cutLS('start-at-field',
      "  /** ★ 5.1.41：速度采样点（EMA 平滑，避免速度文字乱跳） */\n",
      "  /** ★ 5.1.47：最近一次完成传输的「大小 · 平均速度」，插消息气泡时用 */\n"
      "  private lastTransferSummary: string = '';\n"
      "  /** ★ 5.1.47：本次传输的**起始时刻**，用于算完成时的**平均速度** */\n"
      "  private xferStartAt: number = 0;\n"
      "  /** ★ 5.1.41：速度采样点（EMA 平滑，避免速度文字乱跳） */\n")

cutLS('start-at-mark',
      "  private updateSpeed(bytes: number): void {\n"
      "    const now: number = Date.now();\n"
      "    if (this.speedAt === 0) {\n",
      "  private updateSpeed(bytes: number): void {\n"
      "    const now: number = Date.now();\n"
      "    // ★ 5.1.47：第一次采样时记下起始时刻，供完成时算平均速度。\n"
      "    if (this.xferStartAt === 0) {\n"
      "      this.xferStartAt = now;\n"
      "    }\n"
      "    if (this.speedAt === 0) {\n")

cutLS('start-at-reset',
      "  private resetSpeed(): void {\n"
      "    this.speedBytes = 0;\n"
      "    this.speedAt = 0;\n"
      "    this.speedEma = 0;\n",
      "  private resetSpeed(): void {\n"
      "    this.speedBytes = 0;\n"
      "    this.speedAt = 0;\n"
      "    this.speedEma = 0;\n"
      "    this.xferStartAt = 0;   // ★ 5.1.47：下一段传输重新计时\n")

# ═══ ⑤ 平均速度工具 + 完成浮窗副行 ═══
cutLS('avg-helper',
      "  /**\n"
      "   * ★★ 5.1.40：**所有**接收路径的完成提示统一走这里（网页上传 + v4/v5/分片/FileTransfer）。\n",
      "  /**\n"
      "   * ★ 5.1.47：算**本次传输的平均速度**（`总量 / 耗时`）。\n"
      "   *\n"
      "   * 【为什么不用 `speedEma`】那是**瞬时**速度（相邻两次上报的差值），\n"
      "   *   抖动大，而且传输完成时会被 `resetSpeed()` 清掉 ⇒ 浮窗上什么都看不到。\n"
      "   * 【为什么要 `dt >= 200` 门限】太快的小文件除出来的速度没有意义。\n"
      "   *\n"
      "   * @param size 本次传输的总字节数\n"
      "   */\n"
      "  /**\n"
      "   * ★★ 5.1.40：**所有**接收路径的完成提示统一走这里（网页上传 + v4/v5/分片/FileTransfer）。\n"
      "  private avgSpeedText(size: number): string {\n"
      "    if (this.xferStartAt <= 0 || size <= 0) {\n"
      "      return '';\n"
      "    }\n"
      "    const dt: number = Date.now() - this.xferStartAt;\n"
      "    if (dt < 200) {\n"
      "      return '';\n"
      "    }\n"
      "    return `${LanService.fmtSize(Math.round(size * 1000 / dt))}/s`;\n"
      "  }\n"
      "\n"
      "  /**\n"
      "   * ★ 5.1.47：本次传输的「大小 + 平均速度」摘要，给浮窗副行与消息气泡共用。\n"
      "   */\n"
      "  private transferSummary(size: number): string {\n"
      "    const sz: string = LanService.fmtSize(size);\n"
      "    const avg: string = this.avgSpeedText(size);\n"
      "    return avg.length > 0 ? `${sz} · ${avg}` : sz;\n"
      "  }\n"
      "\n"
      "  /** ★ 5.1.40：**所有**接收路径的完成提示统一走这里（网页上传 + v4/v5/分片/FileTransfer）。\n")

cutLS('done-sub',
      "    this.snapshot.transferSub = `接收完成 · ${LanService.fmtSize(size)}`;\n",
      "    // ★ 5.1.47：副行加上**平均速度**（`646.1 MB · 30.2 MB/s`）。\n"
      "    this.snapshot.transferSub = `接收完成 · ${this.transferSummary(size)}`;\n"
      "    // 供完成时插消息气泡用（消息页要显示同样的大小 + 平均速度）。\n"
      "    this.lastTransferSummary = this.transferSummary(size);\n")

# ═══ ⑦ 两个接收调用点传 meta ═══
cutLS('call-protocol',
      "      this.appendFileChat(incoming, r.peer, this.transferPeerIp, r.fileName,\n"
      "        r.fileNames, incoming ? 'device' : 'app');\n",
      "      // ★ 5.1.47：把「大小 · 平均速度」带进气泡。\n"
      "      this.appendFileChat(incoming, r.peer, this.transferPeerIp, r.fileName,\n"
      "        r.fileNames, incoming ? 'device' : 'app',\n"
      "        incoming ? this.lastTransferSummary : '');\n")

cutLS('call-web',
      "      this.appendFileChat(true, '网页端', '', label, names, 'web');\n",
      "      // ★ 5.1.47：同样带「大小 · 平均速度」。\n"
      "      this.appendFileChat(true, '网页端', '', label, names, 'web',\n"
      "        this.lastTransferSummary);\n")

# ═══ ⑧ 气泡里渲染 meta（独立一行，不动 bubbleFooterText）═══
cutIX('bubble-meta',
      "        if (m.incoming && !this.chatSelectMode) {\n"
      "          // ★ 5.0.74：与宫格**同款** —— `N 张/个 · 提示`，落在**左下角**。\n",
      "        // ★★ 5.1.47：文件大小 + 平均速度，落在文件名**下面**独立一行。\n"
      "        //   ⚠️ **刻意不并进 `bubbleFooterText`** —— 那个函数的文案必须**等宽**\n"
      "        //   （5.0.70 / 5.0.74 / 5.0.76 连续踩过三次：字数一变就布局抖一下）。\n"
      "        if (m.meta.length > 0) {\n"
      "          Text(m.meta)\n"
      "            .fontSize(10)\n"
      "            .fontColor(m.incoming ? C_SUB : '#DCE8FF')\n"
      "            .maxLines(1)\n"
      "            .textOverflow({ overflow: TextOverflow.Ellipsis })\n"
      "            .constraintSize({ maxWidth: '100%' })\n"
      "        }\n"
      "        if (m.incoming && !this.chatSelectMode) {\n"
      "          // ★ 5.0.74：与宫格**同款** —— `N 张/个 · 提示`，落在**左下角**。\n")

# ═══ 校验 + 落盘 ═══
cur = {'LS': ls, 'IX': ix}
for tgt, tag, old, new in B:
    n = cur[tgt].count(old)
    assert n == 1, '%s %s count=%d' % (tgt, tag, n)
    if new:
        assert cur[tgt].count(new) == 0, '%s %s 新文本已存在' % (tgt, tag)
for tgt, tag, old, new in B:
    cur[tgt] = cur[tgt].replace(old, new, 1)
ls, ix = cur['LS'], cur['IX']

assert '"versionCode": 5000146' in app and '"versionName": "5.1.46"' in app, 'version'
app = app.replace('"versionCode": 5000146', '"versionCode": 5000147', 1)
app = app.replace('"versionName": "5.1.46"', '"versionName": "5.1.47"', 1)

io.open(LS, 'w', encoding='utf-8', newline='\n').write(ls)
io.open(IX, 'w', encoding='utf-8', newline='\n').write(ix)
io.open(APP, 'w', encoding='utf-8', newline='\n').write(app)

print('改块数 %d' % len(B))
assert len(B) == 12, '块数 %d' % len(B)
print('ChatMessage.meta :', ls.count("meta: string = '';"))
print('appendChat 参数  :', ls.count('meta: string = \'\'\n  ): void {'))
print('appendFileChat   :', ls.count("source: string,\n                         meta: string = ''"))
print('avgSpeedText     :', ls.count('avgSpeedText'))
print('transferSummary  :', ls.count('transferSummary'))
print('xferStartAt      :', ls.count('xferStartAt'))
print('完成副行带速度   :', ls.count('接收完成 · ${this.transferSummary(size)}'))
print('气泡 meta 行     :', ix.count('if (m.meta.length > 0)'))
print('CRLF             :', ls.count('\r\n') + ix.count('\r\n'))
print('OK 5.1.47 applied')
