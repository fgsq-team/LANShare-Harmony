# -*- coding: utf-8 -*-
"""
5.1.48 修两个 bug
  A. 完成浮层永远不变色/无副行 —— onTransferReport 里 showRecvDoneFloat 之后
     有两行**无条件**清理（transferSub='' / transferDone=false），把刚设好的
     完成态又抹掉了。showRecvDoneFloat 内部 emit 过（所以 Toast 会弹），
     但最后一次 emit 发的是 transferDone=false ⇒ UI 永远走不进完成分支。
  B. 「扫描全能王 2026-10-01 09.47.jpg (1)」识别成文件而不是图片
     —— lastIndexOf('.') 取到 `.jpg` 的点，suffix = "jpg (1)" 匹配不上。
     正解：取后缀前先剥掉尾部的 " (n)" 去重后缀。
"""
import io, os, re, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
LS = os.path.join(ET, 'service', 'LanService.ets')
IX = os.path.join(ET, 'pages', 'Index.ets')
FT = os.path.join(ET, 'core', 'FileTypes.ets')
HP = os.path.join(ET, 'net', 'HttpProtocol.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '5.1.48'
if SENTINEL in io.open(LS, encoding='utf-8', newline='').read():
    print('ALREADY APPLIED'); sys.exit(0)

ls = io.open(LS, encoding='utf-8', newline='').read()
ix = io.open(IX, encoding='utf-8', newline='').read()
ft = io.open(FT, encoding='utf-8', newline='').read()
hp = io.open(HP, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()


def code_only(s):
    """剥离 // 与 /* */ 注释，避免残留断言误伤注释里的符号名"""
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)
    s = re.sub(r'//[^\n]*', '', s)
    return s


B = []


def rep(name, old, new):
    B.append((name, old, new))


# ══════════════════════════════════════════════════════════════════
# ① LanService：新增 stripCopySuffix + extOf，改 isMediaFileName 用 extOf
# ══════════════════════════════════════════════════════════════════

old_media = """  static isMediaFileName(name: string): boolean {
    const dot: number = name.lastIndexOf('.');
    if (dot < 0) {
      return false;
    }
    const ext: string = name.substring(dot + 1).toLowerCase();
    return ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'gif'"""
new_media = """  /**
   * ★★ 5.1.48：剥掉文件名尾部的**复制/去重后缀** ` (n)`。
   *
   * ## 为什么必须剥
   *   `扫描全能王 2026-10-01 09.47.jpg (1)`（安卓相册/QQ/微信导出常见形态）
   *   直接 `lastIndexOf('.')` 取到的后缀是 `jpg (1)` ⇒ 匹配不上 `jpg`
   *   ⇒ 图片被当成普通文件：不进媒体库、消息气泡不显示缩略图、落盘归「其他」。
   *   ★ 注意这个文件名里**有两个点**（`09.47` 和 `.jpg`），所以不能简单取第一个点。
   *
   * ## 形态覆盖（只需认「空格 + 圆括号 + 纯数字 + 右括号」这一种）
   *   `a.jpg (1)` → `a.jpg`   `a (1).jpg` → 本来就对（点在括号后）
   *   `a.jpg (12)` → `a.jpg`  `a.jpg(1)` → `a.jpg`（左括号前无空格也认）
   *   `a.jpg (1) (2)` → `a.jpg`（循环剥）
   *   `report (2026).pdf` → **不剥**（括号里不是纯数字，是文件名的一部分）
   */
  static stripCopySuffix(name: string): string {
    let n: string = name;
    // 最多剥 8 层，防御 `a (1) (2) (3) ...` 之类畸形输入
    for (let k: number = 0; k < 8; k++) {
      if (!n.endsWith(')')) {
        return n;
      }
      const lp: number = n.lastIndexOf('(');
      if (lp < 0) {
        return n;
      }
      const inner: string = n.substring(lp + 1, n.length - 1);
      if (inner.length === 0 || inner.length > 6) {
        return n;
      }
      let allDigit: boolean = true;
      for (let i: number = 0; i < inner.length; i++) {
        const c: number = inner.charCodeAt(i);
        if (c < 0x30 || c > 0x39) {
          allDigit = false;
          break;
        }
      }
      if (!allDigit) {
        return n;
      }
      n = n.substring(0, lp);
    }
    return n;
  }

  /**
   * ★★ 5.1.48：取小写扩展名（**唯一真源**）。
   * 先剥 ` (n)` 再取点后段，避免 `xxx.jpg (1)` 这类文件名拿不到真扩展名。
   * 无扩展名时返回空串。**所有判定扩展名的地方都必须走这个函数。**
   */
  static extOf(fileName: string): string {
    const base: string = LanService.stripCopySuffix(fileName);
    const dot: number = base.lastIndexOf('.');
    if (dot < 0 || dot === base.length - 1) {
      return '';
    }
    return base.substring(dot + 1).toLowerCase();
  }

  static isMediaFileName(name: string): boolean {
    const ext: string = LanService.extOf(name);
    if (ext.length === 0) {
      return false;
    }
    return ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'gif'"""
rep('LS:isMediaFileName', old_media, new_media)

# ══════════════════════════════════════════════════════════════════
# ② ★核心修复：onTransferReport 里那两行无条件清理
# ══════════════════════════════════════════════════════════════════

old_done = """    if (r.ok && r.direction !== 'send') {
      this.showRecvDoneFloat(
        r.fileName.length > 0 ? r.fileName : '文件', r.fileSize);
    } else {
      this.snapshot.transferText = '';
      this.snapshot.transferPercent = 0;
    }
    this.snapshot.transferSub = '';
    this.snapshot.transferDone = false;
    this.resetSpeed();
    this.lastReportBytes = 0;"""
new_done = """    if (r.ok && r.direction !== 'send') {
      // ★★★ 5.1.48 修 BUG：这里**原来还有两行无条件清理**
      //   `this.snapshot.transferSub = '';` 与 `this.snapshot.transferDone = false;`
      //   写在 if/else **外面**，把 showRecvDoneFloat 刚设好的完成态又抹掉了。
      //   ⇒ showRecvDoneFloat 内部的 emit 还能弹到 Toast（状态当时是对的），
      //     但本方法末尾最后一次 emit 发出去的是 transferDone=false
      //     ⇒ UI 永远走不进完成分支 ⇒ 浮层不变色、副行不显示。
      //   ⇒ 现在只在 else（失败）分支里清理；成功分支由 showRecvDoneFloat
      //     自己的 3 秒定时器负责清空（transferText 已经是同一套机制）。
      this.showRecvDoneFloat(
        r.fileName.length > 0 ? r.fileName : '文件', r.fileSize);
    } else {
      this.snapshot.transferText = '';
      this.snapshot.transferPercent = 0;
      this.snapshot.transferSub = '';
      this.snapshot.transferDone = false;
      this.resetSpeed();
    }
    this.lastReportBytes = 0;"""
rep('LS:done-cleanup', old_done, new_done)

# ══════════════════════════════════════════════════════════════════
# ③ Index：isImageName / isVideoName 改走 LanService.extOf
# ══════════════════════════════════════════════════════════════════

old_img = """  private isImageName(name: string): boolean {
    const dot: number = name.lastIndexOf('.');
    if (dot < 0) {
      return false;
    }
    const ext: string = name.substring(dot + 1).toLowerCase();
    return ext === 'jpg'"""
new_img = """  private isImageName(name: string): boolean {
    // ★ 5.1.48：统一走 LanService.extOf —— 它会先剥掉 ` (n)` 复制后缀，
    //   否则 `扫描全能王 2026-10-01 09.47.jpg (1)` 取到 `jpg (1)` 判不出图片。
    const ext: string = LanService.extOf(name);
    if (ext.length === 0) {
      return false;
    }
    return ext === 'jpg'"""
rep('IX:isImageName', old_img, new_img)

old_vid = """  private isVideoName(name: string): boolean {
    const dot: number = name.lastIndexOf('.');
    if (dot < 0) {
      return false;
    }
    const ext: string = name.substring(dot + 1).toLowerCase();
    return ext === 'mp4'"""
new_vid = """  private isVideoName(name: string): boolean {
    const ext: string = LanService.extOf(name);   // ★ 5.1.48 同 isImageName
    if (ext.length === 0) {
      return false;
    }
    return ext === 'mp4'"""
rep('IX:isVideoName', old_vid, new_vid)

# saveImageToAlbum 的 ext/title 也要用 extOf（否则存相册时 title 带空格括号）
old_alb = """    const dot: number = name.lastIndexOf('.');
    // ⚠️ title 的硬性规则：**不能带扩展名**（扩展名单独走 fileNameExtension）、
    //    不能含 \\ / : * ? " ' ` < > | { } [ ]、总长 1~255。
    const isVideo: boolean = this.isVideoName(name);
    const title: string = Index.safeAlbumTitle(dot > 0 ? name.substring(0, dot) : name);
    const ext: string = dot > 0 ? name.substring(dot + 1).toLowerCase() : (isVideo ? 'mp4' : 'jpg');"""
new_alb = """    // ⚠️ title 的硬性规则：**不能带扩展名**（扩展名单独走 fileNameExtension）、
    //    不能含 \\ / : * ? " ' ` < > | { } [ ]、总长 1~255。
    // ★ 5.1.48：先剥 ` (n)` 再切，否则 `xxx.jpg (1)` 的 title 会变成
    //   `扫描全能王 2026-10-01 09.47`（丢了 .jpg）、ext 变成 `jpg (1)`。
    const isVideo: boolean = this.isVideoName(name);
    const bareName: string = LanService.stripCopySuffix(name);
    const dot: number = bareName.lastIndexOf('.');
    const title: string = Index.safeAlbumTitle(dot > 0 ? bareName.substring(0, dot) : bareName);
    const ext: string = dot > 0 && dot < bareName.length - 1
      ? bareName.substring(dot + 1).toLowerCase() : (isVideo ? 'mp4' : 'jpg');"""
rep('IX:saveImageToAlbum', old_alb, new_alb)

# ══════════════════════════════════════════════════════════════════
# ④ FileTypes.classify / inferType：也用剥后缀的取法
# ══════════════════════════════════════════════════════════════════

old_cls = """  static classify(fileName: string): string {
    const dot: number = fileName.lastIndexOf('.');
    if (dot < 0 || dot === fileName.length - 1) {
      return FileCategory.OTHER;
    }
    const suffix: string = fileName.substring(dot + 1).toLowerCase();"""
new_cls = """  static classify(fileName: string): string {
    // ★ 5.1.48：先剥尾部的 ` (n)` 复制后缀，否则 `xxx.jpg (1)` 归到「其他」。
    const bare: string = FileKinds.stripCopySuffix(fileName);
    const dot: number = bare.lastIndexOf('.');
    if (dot < 0 || dot === bare.length - 1) {
      return FileCategory.OTHER;
    }
    const suffix: string = bare.substring(dot + 1).toLowerCase();"""
rep('FT:classify', old_cls, new_cls)

# FileTypes 里加自己的 stripCopySuffix（core 不能依赖 service）
old_fd_end = """  /**
   * 判断文件类型代号是否属于「媒体」，用于决定是否记录到媒体库。"""
new_fd_end = """  /**
   * ★ 5.1.48：剥掉文件名尾部的**复制/去重后缀** ` (n)`。
   * `扫描全能王 2026-10-01 09.47.jpg (1)` → `扫描全能王 2026-10-01 09.47.jpg`。
   *
   * ⚠️ 本函数与 `LanService.stripCopySuffix` 是**同一份逻辑的两处拷贝**
   *   （core 不能反向依赖 service）。改一处必须改另一处。
   */
  static stripCopySuffix(name: string): string {
    let n: string = name;
    for (let k: number = 0; k < 8; k++) {
      if (!n.endsWith(')')) {
        return n;
      }
      const lp: number = n.lastIndexOf('(');
      if (lp < 0) {
        return n;
      }
      const inner: string = n.substring(lp + 1, n.length - 1);
      if (inner.length === 0 || inner.length > 6) {
        return n;
      }
      let allDigit: boolean = true;
      for (let i: number = 0; i < inner.length; i++) {
        const c: number = inner.charCodeAt(i);
        if (c < 0x30 || c > 0x39) {
          allDigit = false;
          break;
        }
      }
      if (!allDigit) {
        return n;
      }
      n = n.substring(0, lp);
    }
    return n;
  }

  /**
   * 判断文件类型代号是否属于「媒体」，用于决定是否记录到媒体库。"""
rep('FT:stripCopySuffix', old_fd_end, new_fd_end)

# ══════════════════════════════════════════════════════════════════
# ⑤ HttpProtocol.of（MIME 推断）同样要剥
# ══════════════════════════════════════════════════════════════════

old_mime = """  static of(fileName: string): string {
    const dot: number = fileName.lastIndexOf('.');
    if (dot < 0 || dot === fileName.length - 1) {
      return 'application/octet-stream';
    }
    const ext: string = fileName.substring(dot + 1).toLowerCase();
    const v: string | undefined = ContentTypes.TABLE.get(ext);"""
new_mime = """  static of(fileName: string): string {
    // ★ 5.1.48：先剥 ` (n)`，否则 `xxx.jpg (1)` 拿不到 image/jpeg。
    const bare: string = FileKinds.stripCopySuffix(fileName);
    const dot: number = bare.lastIndexOf('.');
    if (dot < 0 || dot === bare.length - 1) {
      return 'application/octet-stream';
    }
    const ext: string = bare.substring(dot + 1).toLowerCase();
    const v: string | undefined = ContentTypes.TABLE.get(ext);"""
rep('HP:of', old_mime, new_mime)

# ══════════════════════════════════════════════════════════════════
# ⑥ 版本号 + ABOUT_FALLBACK_VER 同步（发版体检项）
# ══════════════════════════════════════════════════════════════════

old_app = """    "versionCode": 5000147,
    "versionName": "5.1.47\""""
new_app = """    "versionCode": 5000148,
    "versionName": "5.1.48\""""
rep('APP:version', old_app, new_app)

# ══════════════════════════════════════════════════════════════════
# 校验 + 落盘
# ══════════════════════════════════════════════════════════════════
# ⚠️ 同一个文件可能被多个块改 —— 必须**按文件累积**，不能每块各自 replace
#    （否则后一块基于原始副本替换，会把前一块的结果覆盖掉）
cur = {'LS': ls, 'IX': ix, 'FT': ft, 'HP': hp, 'APP': app}
owner = {'LS:isMediaFileName': 'LS', 'LS:done-cleanup': 'LS',
         'IX:isImageName': 'IX', 'IX:isVideoName': 'IX',
         'IX:saveImageToAlbum': 'IX', 'FT:classify': 'FT',
         'FT:stripCopySuffix': 'FT', 'HP:of': 'HP', 'APP:version': 'APP'}

# ── 第一遍：全部校验（任一不满足则一个文件都不写）──────────────────
for name, old, new in B:
    f = owner[name]
    n = cur[f].count(old)
    assert n == 1, '%s count=%d (期望 1)' % (name, n)

# ── 第二遍：统一落盘 ────────────────────────────────────────────
for name, old, new in B:
    f = owner[name]
    cur[f] = cur[f].replace(old, new, 1)

ls, ix, ft, hp, app = cur['LS'], cur['IX'], cur['FT'], cur['HP'], cur['APP']

# ── 残留检查（剥离注释后查）────────────────────────────
cl, ci = code_only(ls), code_only(ix)
assert 'transferSub = \'\';\n    this.snapshot.transferDone = false;' not in cl, \
    'onTransferReport 的无条件清理仍在'
assert 'stripCopySuffix' in cl, 'LS.stripCopySuffix 缺失'
assert 'static extOf(' in cl, 'LS.extOf 定义缺失'
assert 'LanService.extOf' in ci, 'Index 未走 extOf'
assert 'FileKinds.stripCopySuffix' in code_only(ft), 'FT.stripCopySuffix 缺失'
assert 'FileKinds.stripCopySuffix' in code_only(hp), 'HP 未剥后缀'
# isImageName/isVideoName/isMediaFileName 里不应再有裸 lastIndexOf('.')
for tag, src, fn in (('LS', cl, 'isMediaFileName'), ('IX', ci, 'isImageName'),
                     ('IX', ci, 'isVideoName')):
    i = src.find(fn + '(name: string)')
    assert i >= 0, fn
    j = src.find('}', i)
    assert 'lastIndexOf' not in src[i:j], '%s 里仍有裸 lastIndexOf' % fn

for p, s in ((LS, ls), (IX, ix), (FT, ft), (HP, hp), (APP, app)):
    assert '\r' not in s, '%s 含 CR' % p
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

print('改块数 :', len(B))
print('extOf  :', ls.count('static extOf('), '| stripCopySuffix:',
      ls.count('static stripCopySuffix('), '+', ft.count('static stripCopySuffix('))
print('version:', '5.1.48' in app)
print('OK 5.1.48 applied')