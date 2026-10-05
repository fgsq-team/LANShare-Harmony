# -*- coding: utf-8 -*-
"""
5.1.50
  A. ★★ 修 `扫描全能王 ...jpg (1)` 仍识别不出图片：剥完 `(1)` 尾部留空格
     ⇒ ext = 'jpg '（带尾随空格）匹配不上。
     （5.1.48 只剥了括号，忘了原文 `.jpg (1)` 里 `(` **前面**还有一个空格。）
  B. 浮层「接收」与文件名**同一行**（现在拼成一个字符串 → ArkUI 在空格处折行）
  C. 图片宫格气泡也显示「总大小 · 平均速度」
  D. 接收完成浮窗 3 秒 → **5 秒**
"""
import io, os, re, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
LS = os.path.join(ET, 'service', 'LanService.ets')
IX = os.path.join(ET, 'pages', 'Index.ets')
FT = os.path.join(ET, 'core', 'FileTypes.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '5.1.50'
if SENTINEL in io.open(LS, encoding='utf-8', newline='').read():
    print('ALREADY APPLIED'); sys.exit(0)

ls = io.open(LS, encoding='utf-8', newline='').read()
ix = io.open(IX, encoding='utf-8', newline='').read()
ft = io.open(FT, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

B = []
def rep(tag, old, new): B.append((tag, old, new))

# ══════════════════════════════════════════════════════════════════
# ① A：LanService.stripCopySuffix 剥完要 trim 尾空格（★ 真正的病根）
# ══════════════════════════════════════════════════════════════════
rep('LS:strip-trim',
    """  static stripCopySuffix(name: string): string {
    let n: string = name;
    // 最多剥 8 层，防御 `a (1) (2) (3) ...` 之类畸形输入
    for (let k: number = 0; k < 8; k++) {
      if (!n.endsWith(')')) {
        return n;
      }""",
    """  static stripCopySuffix(name: string): string {
    let n: string = name;
    // 最多剥 8 层，防御 `a (1) (2) (3) ...` 之类畸形输入
    for (let k: number = 0; k < 8; k++) {
      // ★★ 5.1.50：**先去掉尾部空白再判断**。
      //   `扫描全能王 2026-10-01 09.47.jpg (1)` 的 `(` **前面**有一个空格，
      //   剥掉 `(1)` 后剩下 `...jpg ` ⇒ ext 变成 `'jpg '`（带尾随空格）
      //   ⇒ 匹配不上 `'jpg'` ⇒ 图片仍被当普通文件（5.1.48 漏了这一步）。
      n = LanService.rtrim(n);
      if (!n.endsWith(')')) {
        return n;
      }""")

# 加 rtrim 工具方法（放在 stripCopySuffix 之前）
rep('LS:add-rtrim',
    """  static stripCopySuffix(name: string): string {
    let n: string = name;""",
    """  /** ★ 5.1.50：去尾部空白（空格/制表符）。ArkTS 无 `trimEnd`，手写。 */
  static rtrim(s: string): string {
    let e: number = s.length;
    while (e > 0) {
      const c: number = s.charCodeAt(e - 1);
      if (c !== 0x20 && c !== 0x09 && c !== 0x0A && c !== 0x0D) {
        break;
      }
      e -= 1;
    }
    return e === s.length ? s : s.substring(0, e);
  }

  static stripCopySuffix(name: string): string {
    let n: string = name;""")

# extOf 再加一道防御
rep('LS:ext-trim',
    """  static extOf(fileName: string): string {
    const base: string = LanService.stripCopySuffix(fileName);
    const dot: number = base.lastIndexOf('.');
    if (dot < 0 || dot === base.length - 1) {
      return '';
    }
    return base.substring(dot + 1).toLowerCase();
  }""",
    """  static extOf(fileName: string): string {
    // ★ 5.1.50：rtrim 兜底 —— 万一还有别的形态在点后留了空白（`jpg (1)` 是已知一例），
    //   这里再兜一层，避免「后缀多了个空格就整体失效」这种脆判定。
    const base: string = LanService.rtrim(LanService.stripCopySuffix(fileName));
    const dot: number = base.lastIndexOf('.');
    if (dot < 0 || dot === base.length - 1) {
      return '';
    }
    return LanService.rtrim(base.substring(dot + 1)).toLowerCase();
  }""")

# ══════════════════════════════════════════════════════════════════
# ② A：FileKinds.stripCopySuffix 同样修（core 的那份拷贝）
# ══════════════════════════════════════════════════════════════════
rep('FT:strip-trim',
    """  static stripCopySuffix(name: string): string {
    let n: string = name;
    for (let k: number = 0; k < 8; k++) {
      if (!n.endsWith(')')) {
        return n;
      }""",
    """  static stripCopySuffix(name: string): string {
    let n: string = name;
    for (let k: number = 0; k < 8; k++) {
      // ★ 5.1.50：与 `LanService.stripCopySuffix` 同款修正 ——
      //   剥完 `(1)` 要去掉尾部空格（`x.jpg (1)` → `x.jpg ` → 后缀 `jpg ` 失效）
      n = FileKinds.rtrim(n);
      if (!n.endsWith(')')) {
        return n;
      }""")

rep('FT:add-rtrim',
    """  static stripCopySuffix(name: string): string {
    let n: string = name;
    for (let k: number = 0; k < 8; k++) {""",
    """  /** ★ 5.1.50：去尾部空白（与 LanService.rtrim 同款，改一处必须改另一处） */
  static rtrim(s: string): string {
    let e: number = s.length;
    while (e > 0) {
      const c: number = s.charCodeAt(e - 1);
      if (c !== 0x20 && c !== 0x09 && c !== 0x0A && c !== 0x0D) {
        break;
      }
      e -= 1;
    }
    return e === s.length ? s : s.substring(0, e);
  }

  static stripCopySuffix(name: string): string {
    let n: string = name;
    for (let k: number = 0; k < 8; k++) {""")

rep('FT:classify-trim',
    """    const bare: string = FileKinds.stripCopySuffix(fileName);
    const dot: number = bare.lastIndexOf('.');
    if (dot < 0 || dot === bare.length - 1) {
      return FileCategory.OTHER;
    }
    const suffix: string = bare.substring(dot + 1).toLowerCase();""",
    """    const bare: string = FileKinds.rtrim(FileKinds.stripCopySuffix(fileName));
    const dot: number = bare.lastIndexOf('.');
    if (dot < 0 || dot === bare.length - 1) {
      return FileCategory.OTHER;
    }
    const suffix: string = FileKinds.rtrim(bare.substring(dot + 1)).toLowerCase();""")

# ══════════════════════════════════════════════════════════════════
# ③ B：「接收」与文件名同行 —— 拆成两个元素 + 不换行
# ══════════════════════════════════════════════════════════════════
# 3a. 协议侧 / 网页侧：transferText 恢复「纯文件名」，另加字段存动词
rep('LS:verb-field',
    """  private lastTransferSummary: string = '';""",
    """  private lastTransferSummary: string = '';
  /**
   * ★ 5.1.50：浮层标题的**动词**（`接收` / `网页接收`），与文件名**分两个元素**渲染。
   *
   * ## 为什么不能拼进 `transferText`
   *   5.1.49 把 `接收 ${nm}` 拼成一个字符串给 `Text`，ArkUI **在空格处自动折行**
   *   ⇒ 「接收」独占第一行、文件名被挤到第二行且再次截断（vivi 截图）。
   * ★ 「同一段文本」≠「视觉同一行」—— 要保证同行，必须是**两个独立组件**。
   */
  private verbText: string = '';""")

rep('LS:snap-verb',
    """  transferSub: string = '';""",
    """  transferSub: string = '';
  /** ★ 5.1.50：浮层标题的动词（与文件名分两个组件渲染，见 verbText 注释） */
  verb: string = '';""")

rep('LS:progress-verb2',
    """      // ★ 5.1.49：vivi 要求**标题行文件名前要有「接收」二字**。
      //   （5.1.45 曾把动词全移到副行、标题只留文件名，这里按要求加回来。）
      this.snapshot.transferText = `接收 ${nm}`;""",
    """      // ★ 5.1.50：动词**不再拼进 transferText**（拼进去 ArkUI 会在空格处折行）
      this.snapshot.verb = '接收';
      this.snapshot.transferText = nm;""")

rep('LS:web-verb2',
    """    // ★ 5.1.49：同协议侧，标题行加「接收」二字。
    this.snapshot.transferText = `接收 ${who.length > 0 ? who : '文件'}`;""",
    """    // ★ 5.1.50：同协议侧，动词独立成字段，不拼进 transferText
    this.snapshot.verb = '接收';
    this.snapshot.transferText = who.length > 0 ? who : '文件';""")

rep('LS:done-verb',
    """    this.snapshot.transferText = label.length > 0 ? label : '文件';""",
    """    this.snapshot.verb = '';   // ★ 5.1.50：完成态不显示动词
    this.snapshot.transferText = label.length > 0 ? label : '文件';""")

# 清空处也要清 verb（三处：else 分支 / 定时器 / emitThrottled 侧）
rep('LS:clear-verb1',
    """      this.snapshot.transferText = '';
      this.snapshot.transferPercent = 0;
      this.snapshot.transferSub = '';
      this.snapshot.transferDone = false;
      this.resetSpeed();
    }
    this.lastReportBytes = 0;""",
    """      this.snapshot.transferText = '';
      this.snapshot.transferPercent = 0;
      this.snapshot.transferSub = '';
      this.snapshot.transferDone = false;
      this.snapshot.verb = '';       // ★ 5.1.50
      this.resetSpeed();
    }
    this.lastReportBytes = 0;""")

rep('LS:clear-verb2',
    """      this.snapshot.transferDone = false;
      this.resetSpeed();
    }
    if (ok) {""",
    """      this.snapshot.transferDone = false;
      this.snapshot.verb = '';       // ★ 5.1.50
      this.resetSpeed();
    }
    if (ok) {""")

rep('LS:clear-verb-timer',
    """      this.snapshot.transferDone = false;
      this.resetSpeed();
      this.emit();
    }, 3000);""",
    """      this.snapshot.transferDone = false;
      this.snapshot.verb = '';       // ★ 5.1.50
      this.resetSpeed();
      this.emit();
    }, 3000);""")

# ══════════════════════════════════════════════════════════════════
# ④ D：完成浮窗 3 秒 → 5 秒
# ══════════════════════════════════════════════════════════════════
rep('LS:done-5s',
    """    }, 3000);""",
    """    }, 5000);   // ★ 5.1.50：vivi 要求完成浮窗保留 **5 秒**（原 3000ms）""")

# ══════════════════════════════════════════════════════════════════
# ⑤ C：图片宫格气泡显示「总大小 · 平均速度」
# ══════════════════════════════════════════════════════════════════
rep('IX:grid-meta',
    """        if (g.incoming && !this.chatSelectMode) {
          // ★ 5.0.75：改用「整组任一张已存」判据（原先只看 `g.msgs[0]`，见方法注释）
          Text(`${g.msgs.length} 张 · ${this.bubbleHintOfGroup(g)}`)
            .fontSize(10)
            .fontColor(C_PRIMARY)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }""",
    """        // ★ 5.1.50：宫格气泡也显示「总大小 · 平均速度」
        //   （5.1.49 只做了单文件气泡，宫格这条路径是 `appendFileChat` 的
        //   媒体分支，靠每条消息各自的 meta；这里把**整组**的汇总值取第一条非空的。
        //   ⚠️ 刻意不并进下面那行 —— 那行是「N 张 · 提示」，属固定文案，
        //     与 5.1.47 的 `bubbleFooterText` 同理，塞变长内容会抖布局。
        if (g.incoming && !this.chatSelectMode) {
          // ★ 5.0.75：改用「整组任一张已存」判据（原先只看 `g.msgs[0]`，见方法注释）
          Text(`${g.msgs.length} 张 · ${this.bubbleHintOfGroup(g)}`)
            .fontSize(10)
            .fontColor(C_PRIMARY)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          const gm: string = this.groupMetaText(g);
          if (gm.length > 0) {
            Text(gm)
              .fontSize(10)
              .fontColor(C_SUB)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
        }""")

# 加 groupMetaText 方法（放在 bubbleHintOfGroup 后面）
anchor_IX = '  private static readonly HINT_NOT_YET: string = \'长按存入相册\';'
rep('IX:add-groupmeta',
    anchor_IX,
    anchor_IX + """

  /**
   * ★ 5.1.50：取一组媒体消息的「总大小 · 平均速度」副信息。
   *
   * ## 数据来源
   *   每次接收 `appendFileChat` 会把**同一批**的 `meta`（`646.1 MB · 36.5 MB/s`）
   *   写进该批的**每一条**消息（它们共享 `batchId`）。
   *   ⇒ 取第一条非空的即可（同一批的值是同一个）。
   *
   * ## 为什么不在这里累加大小
   *   同一批每条都记了**整批**的总量（不是「这一张」的大小），
   *   累加会重复计算 N 倍。★ 要改成按张累加，得先让上报方带 per-file 大小。
   */
  private groupMetaText(g: ChatGroup): string {
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (g.msgs[i].meta.length > 0) {
        return g.msgs[i].meta;
      }
    }
    return '';
  }""")

# ══════════════════════════════════════════════════════════════════
# ⑥ 版本号 + ABOUT_FALLBACK
# ══════════════════════════════════════════════════════════════════
rep('APP:ver',
    """    "versionCode": 5000149,
    "versionName": "5.1.49\"""",
    """    "versionCode": 5000150,
    "versionName": "5.1.50\"""")
rep('IX:fallback',
    "const ABOUT_FALLBACK_VER: string = '5.1.49';",
    "const ABOUT_FALLBACK_VER: string = '5.1.50';")

# ══════════════════════════════════════════════════════════════════
# 按文件累积 + 先全部校验
# ══════════════════════════════════════════════════════════════════
cur = {'LS': ls, 'IX': ix, 'FT': ft, 'APP': app}
owner = {}
for t, _o, _n in B:
    owner[t] = ('IX' if t.startswith('IX:') else
                'FT' if t.startswith('FT:') else
                'APP' if t.startswith('APP:') else 'LS')

for tag, old, new in B:
    n = cur[owner[tag]].count(old)
    assert n == 1, '%s count=%d (期望 1)' % (tag, n)
for tag, old, new in B:
    f = owner[tag]
    cur[f] = cur[f].replace(old, new, 1)

ls, ix, ft, app = cur['LS'], cur['IX'], cur['FT'], cur['APP']

def code_only(s):
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)
    s = re.sub(r'//[^\n]*', '', s)
    return s
cl, ci, cf = code_only(ls), code_only(ix), code_only(ft)

assert cl.count('static rtrim(') == 1, 'LS.rtrim 缺失'
assert cf.count('static rtrim(') == 1, 'FT.rtrim 缺失'
assert 'LanService.rtrim(LanService.stripCopySuffix(fileName))' in cl, 'extOf 未 rtrim'
assert "snapshot.verb = '接收';" in cl, '动词未写入'
assert '`接收 ${nm}`' not in cl and '`接收 ${who' not in cl, '动词仍拼在 transferText'
# 4 处：协议侧 else / 网页侧 else / showRecvDoneFloat 完成态 / 3→5 秒定时器
assert cl.count("this.snapshot.verb = '';") == 4, 'verb 清理点不足: %d' % cl.count("this.snapshot.verb = '';")
assert '}, 5000);' in cl, '完成浮窗未改 5 秒'
assert 'private groupMetaText(g: ChatGroup): string {' in ci, 'groupMetaText 缺失'
assert 'const gm: string = this.groupMetaText(g);' in ci, '宫格未渲染 meta'
assert "'5.1.50'" in ix and '5.1.50' in app, '版本未同步'

for p, s in ((LS, ls), (IX, ix), (FT, ft), (APP, app)):
    assert '\r' not in s, '%s 含 CR' % p
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

print('改块数 :', len(B))
print('rtrim  : LS=%d FT=%d' % (ls.count('static rtrim('), ft.count('static rtrim(')))
print('verb   : 赋值 %d / 清理 %d' % (cl.count("snapshot.verb = '接收';"),
                                       cl.count("this.snapshot.verb = '';")))
print('OK 5.1.50 applied')