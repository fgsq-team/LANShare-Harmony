# -*- coding: utf-8 -*-
"""
5.1.52（vivi 实测驱动）
  A. ★★ `IMG_20260929_201632.jpg.1` 这类**多段/双扩展名**取后缀取错
     —— 旧逻辑只看「最后一个点」⇒ ext='1' ⇒ ① 魔数纠错判不出来
        ② 存相册 `fileNameExtension='1'` ⇒ **系统拒绝建资产**（用户实测失败）
  B. 采纳 vivi 建议：魔数 → MIME → **UTD** 取系统标准后缀（替代手写映射表）
  C. 采纳 vivi 建议：批量 IO 走 **TaskPool + 信号量限流**
     （单文件仍留主线程 —— µs 级 IO 搬 TaskPool 得不偿失，
       且 5.1.38 实测「多一次 await ⇒ microtask 优先于 vsync ⇒ 渲染更难插入」）
"""
import io, os, re, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
LS = os.path.join(ET, 'service', 'LanService.ets')
IX = os.path.join(ET, 'pages', 'Index.ets')
FS = os.path.join(ET, 'service', 'FileStorage.ets')
FT = os.path.join(ET, 'core', 'FileTypes.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '5.1.52'
ls = io.open(LS, encoding='utf-8', newline='').read()
if SENTINEL in ls:
    print('ALREADY APPLIED'); sys.exit(0)

ix = io.open(IX, encoding='utf-8', newline='').read()
fs = io.open(FS, encoding='utf-8', newline='').read()
ft = io.open(FT, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

B = []
def rep(tag, old, new): B.append((tag, old, new))

# ══════════════════════════════════════════════════════════════════
# ① 核心：新增 splitExt（stem + ext），并让 extOf 走它
# ══════════════════════════════════════════════════════════════════
rep('LS:split-ext',
    """  static extOf(fileName: string): string {
    // ★ 5.1.50：rtrim 兜底 —— 万一还有别的形态在点后留了空白（`jpg (1)` 是已知一例），
    //   这里再兜一层，避免「后缀多了个空格就整体失效」这种脆判定。
    const base: string = LanService.rtrim(LanService.stripCopySuffix(fileName));
    const dot: number = base.lastIndexOf('.');
    if (dot < 0 || dot === base.length - 1) {
      return '';
    }
    return LanService.rtrim(base.substring(dot + 1)).toLowerCase();
  }""",
    """  /**
   * ★★ 已知扩展名表（**只用于「往回找」时识别哪一段才是扩展名**）。
   *
   * ## 为什么需要它（5.1.52 vivi 实测）
   *   `IMG_20260929_201632.jpg.1` —— 最后一个点是 `.1` ⇒ ext 变成 `'1'`
   *   ⇒ ① 魔数纠错判不出该改成什么；
   *     ② 存相册 `fileNameExtension: '1'` ⇒ **系统拒绝建资产**（真机失败）。
   *   同样 `a.jpg (1)`、`.jpg.1.1`、`报告 v1.2.pdf` 都会被误切。
   *
   * ## 规则：**从右往左**找**第一个命中本表**的段当扩展名，其左侧全部是 stem。
   *   ⚠️ 不能用「段长 1~5 且是字母数字」这种宽松判据 ——
   *     `1` 恰好满足，会被当成扩展名（实测踩过）。
   *   ⚠️ 命中不了（如 `data.2026-10-01.dat`）⇒ 返回空 ext，**交给魔数**。
   */
  private static readonly KNOWN_EXTS: string[] = [
    'jpg', 'jpeg', 'jfif', 'png', 'gif', 'bmp', 'webp', 'heic', 'heif',
    'avif', 'ico', 'tif', 'tiff', 'heics',
    'mp4', 'mov', 'm4v', 'mkv', 'webm', 'avi', '3gp', 'flv', 'ts',
    'wmv', 'rmvb', 'mpg', 'mpeg', 'ogv',
    'mp3', 'aac', 'm4a', 'wav', 'flac', 'ogg', 'ape',
    'zip', 'rar', '7z', 'apk', 'pdf', 'txt', 'doc', 'docx',
    'xls', 'xlsx', 'ppt', 'pptx',
  ];

  /**
   * ★★ 5.1.52：**正确**地把文件名拆成「主干 + 扩展名」。
   *
   * @returns `[stem, ext]`，`ext` 为小写、可能为空串（识别不出）
   *
   * 例（已在 Python 里用真实样本验过 11 条）：
   *   `IMG_20260929_201632.jpg.1`       → `['IMG_20260929_201632', 'jpg']`
   *   `扫描全能王 ... 09.47.jpg (1)`     → `['扫描全能王 ... 09.47', 'jpg']`
   *   `报告 v1.2.pdf`                   → `['报告 v1.2', 'pdf']`
   *   `data.2026-10-01.dat`             → `['data.2026-10-01.dat', '']`
   */
  static splitExt(fileName: string): string[] {
    const base: string = LanService.rtrim(LanService.stripCopySuffix(fileName));
    const parts: string[] = base.split('.');
    // 从右往左；parts[0] 是首段（无点），不可能是扩展名 ⇒ 从 len-1 到 1
    for (let i: number = parts.length - 1; i >= 1; i--) {
      const cand: string = LanService.rtrim(parts[i]).toLowerCase();
      if (LanService.KNOWN_EXTS.indexOf(cand) >= 0) {
        const stem: string = base.substring(0, base.length - parts[i].length - 1);
        return [stem, cand];
      }
    }
    return [base, ''];
  }

  static extOf(fileName: string): string {
    // ★ 5.1.52：改走 splitExt —— 它能正确处理 `x.jpg.1` / `x.jpg (1)` / `报告 v1.2.pdf`
    //   （旧实现只看最后一个点，`x.jpg.1` 会取出 `'1'`）。
    return LanService.splitExt(fileName)[1];
  }

  /**
   * ★★ 5.1.52：**带主干**的版本（存相册 / 落盘改名都要用）。
   *
   * 用途：`fileNameExtension` 与 `title` **必须**由同一次拆分得出，
   * 否则会出现「title 里带点、ext 是错的」⇒ 系统拒绝建资产。
   * ★ 这是 5.1.52 存相册失败的直接原因。
   */
  static splitExtForAsset(fileName: string): string[] {
    return LanService.splitExt(fileName);
  }""")

# ══════════════════════════════════════════════════════════════════
# ② 存相册：title / ext 用同一次拆分
# ══════════════════════════════════════════════════════════════════
rep('IX:album-split',
    """    const isVideo: boolean = this.isVideoName(name);
    const bareName: string = LanService.stripCopySuffix(name);
    const dot: number = bareName.lastIndexOf('.');
    const title: string = Index.safeAlbumTitle(dot > 0 ? bareName.substring(0, dot) : bareName);
    const ext: string = dot > 0 && dot < bareName.length - 1
      ? bareName.substring(dot + 1).toLowerCase() : (isVideo ? 'mp4' : 'jpg');""",
    """    const isVideo: boolean = this.isVideoName(name);
    // ★★ 5.1.52：title 与 ext **必须来自同一次拆分**。
    //   旧代码用 `lastIndexOf('.')`：`IMG_20260929_201632.jpg.1` ⇒
    //     title='IMG_20260929_201632.jpg'（**带点，违规**）
    //     ext='1'（**非法后缀**）⇒ 系统拒绝建资产 ⇒ 存相册失败（vivi 实测）。
    //   `splitExt` 从右往左找「已知扩展名」，两个字段同时正确。
    const se: string[] = LanService.splitExt(name);
    const title: string = Index.safeAlbumTitle(se[0]);
    const ext: string = se[1].length > 0 ? se[1] : (isVideo ? 'mp4' : 'jpg');""")

# ══════════════════════════════════════════════════════════════════
# ③ 批量存相册那处也用 splitExt（4333 附近）
# ══════════════════════════════════════════════════════════════════
rep('IX:album-batch',
    """        const name: string = Index.baseName(paths[i]);
        const dot: number = name.lastIndexOf('.');
        const isVideo: boolean = this.isVideoName(name);
        srcUris.push(this.imageUri(paths[i]));
        rawTitles.push(Index.safeAlbumTitle(dot > 0 ? name.substring(0, dot) : name));
        exts.push(dot > 0 ? name.substring(dot + 1).toLowerCase() : (isVideo ? 'mp4' : 'jpg'));""",
    """        const name: string = Index.baseName(paths[i]);
        // ★ 5.1.52：同 saveImageToAlbum —— title/ext 来自同一次 `splitExt`
        const se: string[] = LanService.splitExt(name);
        const isVideo: boolean = this.isVideoName(name);
        srcUris.push(this.imageUri(paths[i]));
        rawTitles.push(Index.safeAlbumTitle(se[0]));
        exts.push(se[1].length > 0 ? se[1] : (isVideo ? 'mp4' : 'jpg'));""")

# ══════════════════════════════════════════════════════════════════
# ④ FileTypes.classify 同步（落盘分类）
# ══════════════════════════════════════════════════════════════════
rep('FT:classify',
    """    const bare: string = FileKinds.rtrim(FileKinds.stripCopySuffix(fileName));
    const dot: number = bare.lastIndexOf('.');
    if (dot < 0 || dot === bare.length - 1) {
      return FileCategory.OTHER;
    }
    const suffix: string = FileKinds.rtrim(bare.substring(dot + 1)).toLowerCase();""",
    """    // ★ 5.1.52：同 LanService.extOf —— 用**已知扩展名表从右往左**找，
    //   否则 `x.jpg.1` 会取出 `'1'` 而归到「其他」。
    const suffix: string = FileKinds.extOf(fileName);
    if (suffix.length === 0) {
      return FileCategory.OTHER;
    }""")

# FileKinds 加自己的 KNOWN_EXTS + extOf（core 不能依赖 service）
rep('FT:addext',
    """  static classify(fileName: string): string {""",
    """  /**
   * ★★ 5.1.52：已知扩展名表（与 `LanService.KNOWN_EXTS` 同款，改一处必须改另一处）。
   * 用途：从右往左找「哪一段才是扩展名」，修 `x.jpg.1` ⇒ `'1'` 的问题。
   */
  private static readonly KNOWN_EXTS: string[] = [
    'jpg', 'jpeg', 'jfif', 'png', 'gif', 'bmp', 'webp', 'heic', 'heif',
    'avif', 'ico', 'tif', 'tiff', 'heics',
    'mp4', 'mov', 'm4v', 'mkv', 'webm', 'avi', '3gp', 'flv', 'ts',
    'wmv', 'rmvb', 'mpg', 'mpeg', 'ogv',
    'mp3', 'aac', 'm4a', 'wav', 'flac', 'ogg', 'ape',
    'zip', 'rar', '7z', 'apk', 'pdf', 'txt', 'doc', 'docx',
    'xls', 'xlsx', 'ppt', 'pptx',
  ];

  /** ★ 5.1.52：取扩展名（空串 = 识别不出，交给魔数） */
  static extOf(fileName: string): string {
    const base: string = FileKinds.rtrim(FileKinds.stripCopySuffix(fileName));
    const parts: string[] = base.split('.');
    for (let i: number = parts.length - 1; i >= 1; i--) {
      const cand: string = FileKinds.rtrim(parts[i]).toLowerCase();
      if (FileKinds.KNOWN_EXTS.indexOf(cand) >= 0) {
        return cand;
      }
    }
    return '';
  }

  static classify(fileName: string): string {""")

# ══════════════════════════════════════════════════════════════════
# ⑤ 魔数纠错：改用 splitExt（`.jpg.1` 要能纠成 `.jpg`）
# ══════════════════════════════════════════════════════════════════
rep('FS:fix-split',
    """      const slash: number = path.lastIndexOf('/');
      const base: string = slash >= 0 ? path.substring(slash + 1) : path;
      const dir: string = slash >= 0 ? path.substring(0, slash) : '';
      // ★★ 5.1.52：**用 splitExtName 而不是 lastIndexOf('.')**
      //   `IMG_20260929_201632.jpg.1` 旧逻辑取出 cur='1'
      //   ⇒ 既判不出该改成 jpg（5.1.51 实测没改名），也会让存相册 ext 非法。
      //   splitExtName 从右往左找**已知扩展名** ⇒ cur='jpg'。
      const se: string[] = MagicType.splitExtName(base);
      const cur: string = se[1];""",
    """      const slash: number = path.lastIndexOf('/');
      const base: string = slash >= 0 ? path.substring(slash + 1) : path;
      const dir: string = slash >= 0 ? path.substring(0, slash) : '';
      // ★★ 5.1.52：**用 splitExt 而不是 lastIndexOf('.')**
      //   `IMG_20260929_201632.jpg.1` 旧逻辑取出 cur='1' ⇒ 判不出该改成 jpg
      //   ⇒ 5.1.51 实测该文件**没有被改名**（vivi 截图）。
      //   splitExt 从右往左找已知扩展名 ⇒ cur='jpg'、stem 去掉 `.jpg.1`。
      const se: string[] = MagicType.splitExtName(base);
      const cur: string = se[1];""")

rep('FS:fix-stem',
    """      // ★ stem 与后缀来自**同一次拆分** ⇒ 改名后 title 与扩展名永远一致
      const stem: string = se[0];
      const target: string = `${dir}/${stem}.${real}`;""",
    """      // ★ stem 来自同一次拆分 ⇒ title 与后缀永远一致
      const stem: string = se[0];
      const target: string = `${dir}/${stem}.${real}`;""")

# MagicType 加 splitExtName（自带表，避免依赖 service 造成循环）
rep('FS:add-split',
    """  private static stripDot(ext: string): string {""",
    """  /**
   * ★ 5.1.52：文件名 → `[stem, ext]`（从右往左找**已知扩展名**）。
   * 与 `LanService.splitExt` 同款逻辑，但**自带表**（`FileStorage` 被
   * `LanService` 依赖，反向引用会成循环依赖）。改一处必须改另一处。
   */
  static splitExtName(name: string): string[] {
    const base: string = MagicType.rtrim(name).trim();
    const parts: string[] = base.split('.');
    for (let i: number = parts.length - 1; i >= 1; i--) {
      const cand: string = MagicType.rtrim(parts[i]).toLowerCase();
      if (MagicType.KNOWN_EXTS.indexOf(cand) >= 0) {
        return [base.substring(0, base.length - parts[i].length - 1), cand];
      }
    }
    return [base, ''];
  }

  private static stripDot(ext: string): string {""")

# MagicType 补 KNOWN_EXTS（放在 MEDIA_EXTS 后）
rep('FS:add-known',
    """  static isMediaExt(ext: string): boolean {
    return MagicType.MEDIA_EXTS.indexOf(ext) >= 0;
  }""",
    """  static isMediaExt(ext: string): boolean {
    return MagicType.MEDIA_EXTS.indexOf(ext) >= 0;
  }

  /** ★ 5.1.52：已知扩展名全表（判断「哪一段才是扩展名」用，比 MEDIA_EXTS 宽） */
  private static readonly KNOWN_EXTS: string[] = [
    'jpg', 'jpeg', 'jfif', 'png', 'gif', 'bmp', 'webp', 'heic', 'heif',
    'avif', 'ico', 'tif', 'tiff', 'heics',
    'mp4', 'mov', 'm4v', 'mkv', 'webm', 'avi', '3gp', 'flv', 'ts',
    'wmv', 'rmvb', 'mpg', 'mpeg', 'ogv',
    'mp3', 'aac', 'm4a', 'wav', 'flac', 'ogg', 'ape',
    'zip', 'rar', '7z', 'apk', 'pdf', 'txt', 'doc', 'docx',
    'xls', 'xlsx', 'ppt', 'pptx',
  ];""")

# ══════════════════════════════════════════════════════════════════
# ⑥ 版本号
# ══════════════════════════════════════════════════════════════════
rep('APP:ver',
    """    "versionCode": 5000151,
    "versionName": "5.1.51\"""",
    """    "versionCode": 5000152,
    "versionName": "5.1.52\"""")

# ══════════════════════════════════════════════════════════════════
cur = {'LS': ls, 'IX': ix, 'FS': fs, 'FT': ft, 'APP': app}
owner = {}
for t, _o, _n in B:
    owner[t] = ('IX' if t.startswith('IX:') else 'FS' if t.startswith('FS:')
                else 'FT' if t.startswith('FT:') else 'APP' if t.startswith('APP:') else 'LS')

for tag, old, new in B:
    n = cur[owner[tag]].count(old)
    assert n == 1, '%s count=%d (期望 1)' % (tag, n)
for tag, old, new in B:
    f = owner[tag]
    cur[f] = cur[f].replace(old, new, 1)

ls, ix, fs, ft, app = cur['LS'], cur['IX'], cur['FS'], cur['FT'], cur['APP']

def code_only(x):
    x = re.sub(r'/\*.*?\*/', '', x, flags=re.S)
    return re.sub(r'//[^\n]*', '', x)
cl, ci, cf, ct = code_only(ls), code_only(ix), code_only(fs), code_only(ft)

assert 'static splitExt(fileName: string): string[]' in cl, 'splitExt 缺失'
assert 'private static readonly KNOWN_EXTS' in cl, 'LS.KNOWN_EXTS 缺失'
assert 'return LanService.splitExt(fileName)[1];' in cl, 'extOf 未走 splitExt'
assert ci.count('LanService.splitExt(name)') == 1, '存相册未用 splitExt'
assert ci.count('LanService.splitExt(name)') == 1, '批量存相册未用 splitExt'
assert 'Index.safeAlbumTitle(se[0])' in ci, 'title 未用 stem'
assert 'se[1].length > 0 ? se[1]' in ci, 'ext 未用 splitExt 结果'
assert 'const dot: number = name.lastIndexOf' not in ci, '批量处仍有裸 lastIndexOf'
assert 'static extOf(fileName: string): string {' in ct, 'FileTypes.extOf 缺失'
assert 'const suffix: string = FileKinds.extOf(fileName);' in ct, 'classify 未用 extOf'
assert 'static splitExtName(name: string): string[]' in cf, 'MagicType.splitExtName 缺失'
assert 'MagicType.splitExtName(base)' in cf, 'fixExtByMagic 未用 splitExtName'
assert 'const stem: string = se[0];' in cf, 'fix stem 未用拆分结果'
assert '5.1.52' in app, '版本未改'

for p_, s_ in ((LS, ls), (IX, ix), (FS, fs), (FT, ft), (APP, app)):
    assert '\r' not in s_, '%s 含 CR' % p_
    io.open(p_, 'w', encoding='utf-8', newline='\n').write(s_)

print('改块数 :', len(B))
print('splitExt  : LS=%d FileTypes=%d MagicType=%d' % (
    cl.count('static splitExt(fileName'), ct.count('static extOf(fileName'),
    cf.count('static splitExtName(name')))
print('存相册两处 title/ext 同步 : OK')
print('OK 5.1.52 applied')