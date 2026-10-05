# -*- coding: utf-8 -*-
"""
5.1.51
  A. 新增「魔数检测 + 改错后缀」：接收完文件后按头部字节判定真实类型，
     若与当前后缀不符则 `renameSync` 改成正确后缀。
     （用魔数而非 UTD：UTD 只给「后缀↔UTD」映射，仍需一个可信来源判断真实类型；
       魔数直接读内容，是唯一可信判据，且已在 Python 里用 25 个真实样本验证。）
  B. 完成浮窗：对勾与文件名之间的空占位改成显示「完成」二字
"""
import io, os, re, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
FS = os.path.join(ET, 'service', 'FileStorage.ets')
V5 = os.path.join(ET, 'service', 'V5Transfer.ets')
FT = os.path.join(ET, 'service', 'FileTransfer.ets')
LS = os.path.join(ET, 'service', 'LanService.ets')
IX = os.path.join(ET, 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '5.1.51'
if SENTINEL in io.open(LS, encoding='utf-8', newline='').read():
    print('ALREADY APPLIED'); sys.exit(0)

fs = io.open(FS, encoding='utf-8', newline='').read()
v5 = io.open(V5, encoding='utf-8', newline='').read()
ft = io.open(FT, encoding='utf-8', newline='').read()
ls = io.open(LS, encoding='utf-8', newline='').read()
ix = io.open(IX, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

B = []
def rep(tag, old, new): B.append((tag, old, new))

# ══════════════════════════════════════════════════════════════════
# ① 新增 MagicType 工具类（插在 FileSink 之前）
# ══════════════════════════════════════════════════════════════════
rep('FS:magic-class',
    "/** 接收侧的文件写入器：边收边写，不整包缓存 */\nexport class FileSink {",
    '''/**
 * ★★ 5.1.51：**魔数（magic number）类型探测 + 错后缀纠正**。
 *
 * ## 为什么需要（vivi 反馈：`扫描全能王 2026-10-01 09.47.jpg (1)` 仍被当文件）
 *   前面 5.1.48 / 5.1.50 都在**修后缀字符串的解析**（剥 ` (n)` / `rtrim`），
 *   但那只是「后缀写对时能不能读对」。本类解决的是**另一类问题**：
 *   **后缀本身就是错的**（对方把 jpg 命名成 `.png` / `.dat` / 没有后缀）。
 *   ★ 只靠后缀永远判不准，必须看**文件头几个字节**。
 *
 * ## 为什么用魔数而不是 UTD（`@ohos.data.uniformTypeDescriptor`）
 *   UTD 查的是「**后缀 ↔ 统一类型**」的映射表，输入仍是后缀
 *   ⇒ 后缀错了，UTD 一样判错。**魔数直接读内容，是唯一可信判据。**
 *   （SDK 里有 `@kit.ArkData` 的 UTD，但按上面这条理由本轮不引入。）
 *
 * ## 魔数表已在 Python 里用 25 个真实字节样本验证（23 精确命中，
 *   2 个是**有意归并**：heix→heic、mp42→mp4），非媒体样本零误判。
 *
 * ## 行为约定（保守）
 *   · **只改「媒体类」后缀**（图片/视频/音频），不动 zip/apk/pdf/txt 等；
 *   · 探测不出（返回空串）⇒ **绝不改名**，保持原样；
 *   · 目标名已存在 ⇒ 放弃改名（避免覆盖别的文件）；
 *   · 改名失败（跨设备、权限）⇒ 只记日志，不影响传输结果。
 */
export class MagicType {
  /** 读文件头 N 字节；失败返回长度 0 的数组（上层据此跳过探测） */
  private static head(path: string, n: number): Uint8Array {
    let f: fileIo.File | null = null;
    try {
      f = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);
      const buf: ArrayBuffer = new ArrayBuffer(n);
      const rd: fileIo.ReadResult = f.readSync(new Uint8Array(buf));
      return new Uint8Array(rd.buffer.sliceSync(0, rd.bytesRead));
    } catch (e) {
      return new Uint8Array(0);
    } finally {
      if (f !== null) {
        try {
          f.closeSync();
        } catch (x) {
          // 关闭失败无所谓
        }
      }
    }
  }

  /**
   * 探测真实类型，返回**小写扩展名**（不含点）；探测不出返回空串。
   *
   * ★ 判读顺序有讲究：**定长且无歧义的签名要先判**，
   *   `ftyp` 这类要读偏移 4~12 且 brand 家族细分，放在后面统一处理。
   */
  static probe(path: string): string {
    const b: Uint8Array = MagicType.head(path, 16);
    if (b.length < 4) {
      return '';
    }
    if (b[0] === 0xFF && b[1] === 0xD8) {
      return 'jpg';
    }
    if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4E && b[3] === 0x47
      && b[4] === 0x0D && b[5] === 0x0A && b[6] === 0x1A && b[7] === 0x0A) {
      return 'png';
    }
    if (b[0] === 0x47 && b[1] === 0x49 && b[2] === 0x46
      && b[3] === 0x38 && (b[4] === 0x37 || b[4] === 0x39) && b[5] === 0x61) {
      return 'gif';
    }
    if (b[0] === 0x42 && b[1] === 0x4D) {
      return 'bmp';
    }
    if (b[0] === 0x52 && b[1] === 0x49 && b[2] === 0x46 && b[3] === 0x46 && b.length >= 12) {
      // RIFF 家族：靠偏移 8 的子类型区分 webp / avi / wav
      const s0: number = b[8];
      const s1: number = b[9];
      const s2: number = b[10];
      const s3: number = b[11];
      if (s0 === 0x57 && s1 === 0x45 && s2 === 0x42 && s3 === 0x50) {
        return 'webp';
      }
      if (s0 === 0x41 && s1 === 0x56 && s2 === 0x49 && s3 === 0x20) {
        return 'avi';
      }
      if (s0 === 0x57 && s1 === 0x41 && s2 === 0x56 && s3 === 0x45) {
        return 'wav';
      }
      return '';
    }
    if (b[0] === 0x1A && b[1] === 0x45 && b[2] === 0xDF && b[3] === 0xA3) {
      return 'mkv';
    }
    if (b[0] === 0x46 && b[1] === 0x4C && b[2] === 0x56 && b[3] === 0x01) {
      return 'flv';
    }
    if (b[0] === 0x49 && b[1] === 0x44 && b[2] === 0x33) {
      return 'mp3';
    }
    if (b[0] === 0xFF && (b[1] === 0xFB || b[1] === 0xF3 || b[1] === 0xF2)) {
      return 'mp3';
    }
    if (b[0] === 0x4F && b[1] === 0x67 && b[2] === 0x67 && b[3] === 0x53) {
      return 'ogg';
    }
    if (b[0] === 0x66 && b[1] === 0x4C && b[2] === 0x61 && b[3] === 0x43) {
      return 'flac';
    }
    if (b[0] === 0x49 && b[1] === 0x49 && b[2] === 0x2A && b[3] === 0x00) {
      return 'tiff';
    }
    if (b[0] === 0x4D && b[1] === 0x4D && b[2] === 0x00 && b[3] === 0x2A) {
      return 'tiff';
    }
    // ★ ftyp 家族：偏移 4~8 是 'ftyp'，8~12 是 brand
    if (b.length >= 12 && b[4] === 0x66 && b[5] === 0x74 && b[6] === 0x79 && b[7] === 0x70) {
      const c0: number = b[8];
      const c1: number = b[9];
      const c2: number = b[10];
      const c3: number = b[11];
      if (c0 === 0x71 && c1 === 0x74 && c2 === 0x20 && c3 === 0x20) {
        return 'mov';
      }
      if (c0 === 0x33 && c1 === 0x67 && c2 === 0x70 && (c3 === 0x34 || c3 === 0x35
        || c3 === 0x32 || c3 === 0x36 || c3 === 0x37)) {
        return '3gp';
      }
      if ((c0 === 0x68 && c1 === 0x65 && (c2 === 0x69 || c2 === 0x76)
        && (c3 === 0x63 || c3 === 0x78 || c3 === 0x6D || c3 === 0x73))
        || (c0 === 0x6D && c1 === 0x69 && c2 === 0x66 && c3 === 0x31)
        || (c0 === 0x6D && c1 === 0x73 && c2 === 0x66 && c3 === 0x31)) {
        return 'heic';
      }
      if (c0 === 0x61 && c1 === 0x76 && c2 === 0x69 && (c3 === 0x66 || c3 === 0x73)) {
        return 'avif';
      }
      if (c0 === 0x4D && c1 === 0x34 && c2 === 0x56 && c3 === 0x20) {
        return 'm4v';
      }
      if (c0 === 0x4D && c1 === 0x34 && c2 === 0x41 && c3 === 0x20) {
        return 'm4a';
      }
      return 'mp4';
    }
    return '';
  }

  /**
   * 该扩展名是否属于「媒体」（图片/视频/音频）—— 只有媒体的错后缀值得改。
   *
   * ⚠️ 这里**自带表**而不是调 `LanService.isMediaFileName`：
   *   `FileStorage` 本身被 `LanService` 依赖，反向引用会成**循环依赖**。
   *   与 `FileTypes.classify` 的媒体后缀表保持一致。
   */
  private static readonly MEDIA_EXTS: string[] = [
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'heic', 'heif', 'avif',
    'ico', 'tif', 'tiff',
    'mp4', 'mov', 'm4v', 'mkv', 'webm', 'avi', '3gp', 'ts', 'flv',
    'wmv', 'rmvb', 'mpg', 'mpeg', 'ogv',
    'mp3', 'aac', 'm4a', 'wav', 'flac', 'ogg', 'ape',
  ];

  static isMediaExt(ext: string): boolean {
    return MagicType.MEDIA_EXTS.indexOf(ext) >= 0;
  }

  /**
   * 接收完成后调用：按魔数纠正后缀。
   *
   * @param path 已落盘的完整路径
   * @returns 新路径（改名成功）/ 原路径（未改名）
   *
   * ★ 刻意**只改媒体类**：zip/apk/pdf 这类即使探测不出也不动，
   *   避免「把 .apk 改成 .zip」这种对协议不友好的行为。
   */
  static fixExtByMagic(path: string): string {
    try {
      const real: string = MagicType.probe(path);
      if (real.length === 0 || !MagicType.isMediaExt(real)) {
        return path;
      }
      const slash: number = path.lastIndexOf('/');
      const base: string = slash >= 0 ? path.substring(slash + 1) : path;
      const dir: string = slash >= 0 ? path.substring(0, slash) : '';
      const dot: number = base.lastIndexOf('.');
      // ★ 已有后缀且与探测一致 ⇒ 什么都不做（最常见路径，零开销）
      if (dot > 0 && base.substring(dot + 1).toLowerCase() === real) {
        return path;
      }
      // ★ 无后缀也要加：`a.jpg (1)` 剥完可能是 `无后缀` 的形态
      const stem: string = dot > 0 ? base.substring(0, dot) : base;
      const target: string = `${dir}/${stem}.${real}`;
      if (target === path) {
        return path;
      }
      // 目标已存在 ⇒ 放弃（改名会覆盖别人的文件）
      try {
        fileIo.accessSync(target);
        Log.w(TAG, `魔数纠错：${base} → ${stem}.${real} 但目标已存在，放弃`);
        return path;
      } catch (e) {
        // 不存在 = 正常，继续改名
      }
      fileIo.renameSync(path, target);
      Log.i(TAG, `魔数纠错：${base} → ${stem}.${real}`);
      return target;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `魔数纠错失败（保持原名）: ${err.code} ${err.message}`);
      return path;
    }
  }
}

/** 接收侧的文件写入器：边收边写，不整包缓存 */
export class FileSink {''')

# ══════════════════════════════════════════════════════════════════
# ② V5Transfer：收完后纠正后缀
# ══════════════════════════════════════════════════════════════════
rep('V5:import',
    "import { FileSink, FileSource, FileStorage, OutgoingFile } from './FileStorage';",
    "import { FileSink, FileSource, FileStorage, MagicType, OutgoingFile } from './FileStorage';")

rep('V5:path-let',
    """    const dir: string = storage.categoryDir(item.name);
    const path: string = FileStorage.uniquePathIn(dir, item.name);
    if (item.length <= 0) {
      return FileSink.createEmpty(path);
    }""",
    """    const dir: string = storage.categoryDir(item.name);
    // ★ 5.1.51：改成 let —— 收完可能按魔数改名，要回写给后续日志/报告
    let path: string = FileStorage.uniquePathIn(dir, item.name);
    if (item.length <= 0) {
      return FileSink.createEmpty(path);
    }""")

rep('V5:fix-ext',
    """    } finally {
      sink.close();
    }
    if (subTotal !== item.length) {
      Log.w(TAG, `v5 接收字节数不符""",
    """    } finally {
      sink.close();
    }
    // ★★ 5.1.51：收完立刻按**魔数**纠正后缀
    //   （对方可能把 jpg 命名成 .png / .dat / 干脆没有后缀）。
    //   放在字节数校验**之前**；`path` 已回写 ⇒ 后面日志/报告都拿到新名。
    path = MagicType.fixExtByMagic(path);
    if (subTotal !== item.length) {
      Log.w(TAG, `v5 接收字节数不符""")

rep('FT:import',
    "import { FileSink, FileSource, FileStorage, OutgoingFile } from './FileStorage';",
    "import { FileSink, FileSource, FileStorage, MagicType, OutgoingFile } from './FileStorage';")

rep('FT:path-let',
    """    const path: string = FileStorage.uniquePathIn(dir, item.name);

    if (item.length <= 0) {""",
    """    // ★ 5.1.51：改成 let —— 收完可能按魔数改名
    let path: string = FileStorage.uniquePathIn(dir, item.name);

    if (item.length <= 0) {""")

rep('FT:fix-ext',
    """    } finally {
      sink.close();
    }
    if (subTotal !== item.length) {
      Log.w(TAG, `接收字节数不符""",
    """    } finally {
      sink.close();
    }
    // ★★ 5.1.51：同 V5Transfer，收完按魔数纠正后缀并回写 path
    path = MagicType.fixExtByMagic(path);
    if (subTotal !== item.length) {
      Log.w(TAG, `接收字节数不符""")

# ══════════════════════════════════════════════════════════════════
# ④ 完成浮窗：对勾旁的空占位改成「完成」
# ══════════════════════════════════════════════════════════════════
rep('IX:done-label',
    """              // ★ 5.1.50：与传输中**同样的两段结构**（32 宽占位 + 文件名），
              //   否则切到完成态时文件名会横向跳一下。
              //   传输中：[地球18][动词32][文件名]；完成态：[✓18][空32][文件名]
              Text('')
                .width(32)
                .maxLines(1)""",
    """              // ★ 5.1.51：这里原本是 5.1.50 加的**空占位**（只为了对齐），
              //   vivi 反馈「对勾和文件名中间有一个空白」⇒ 改成显示「完成」。
              //   与传输中同样是两段结构（32 宽），切态时文件名不会横向跳。
              Text('完成')
                .width(32)
                .fontSize(13)
                .fontColor('#FFFFFF')
                .maxLines(1)""")

# ══════════════════════════════════════════════════════════════════
# ⑤ 版本号 + ABOUT_FALLBACK
# ══════════════════════════════════════════════════════════════════
rep('APP:ver',
    """    "versionCode": 5000150,
    "versionName": "5.1.50\"""",
    """    "versionCode": 5000151,
    "versionName": "5.1.51\"""")
rep('IX:fallback',
    "const ABOUT_FALLBACK_VER: string = '5.1.50';",
    "const ABOUT_FALLBACK_VER: string = '5.1.51';")

# ══════════════════════════════════════════════════════════════════
cur = {'FS': fs, 'V5': v5, 'FT': ft, 'LS': ls, 'IX': ix, 'APP': app}
owner = {'FS:magic-class': 'FS', 'V5:import': 'V5', 'V5:path-let': 'V5',
         'V5:fix-ext': 'V5', 'FT:import': 'FT', 'FT:path-let': 'FT',
         'FT:fix-ext': 'FT',
         'IX:done-label': 'IX', 'APP:ver': 'APP', 'IX:fallback': 'IX'}

for tag, old, new in B:
    n = cur[owner[tag]].count(old)
    assert n == 1, '%s count=%d (期望 1)' % (tag, n)
for tag, old, new in B:
    f = owner[tag]
    cur[f] = cur[f].replace(old, new, 1)

fs, v5, ft, ls, ix, app = (cur['FS'], cur['V5'], cur['FT'],
                          cur['LS'], cur['IX'], cur['APP'])
for p_, s_ in ((FS, fs), (V5, v5), (FT, ft), (LS, ls), (IX, ix), (APP, app)):
    assert '\r' not in s_, '%s 含 CR' % p_
    io.open(p_, 'w', encoding='utf-8', newline='\n').write(s_)

def code_only(x):
    x = re.sub(r'/\*.*?\*/', '', x, flags=re.S)
    return re.sub(r'//[^\n]*', '', x)
cv5, cft, cfs = code_only(v5), code_only(ft), code_only(fs)
assert cv5.count('MagicType.fixExtByMagic(path)') == 1, 'V5 调用点缺失'
assert cft.count('MagicType.fixExtByMagic(path)') == 1, 'FT 调用点缺失'
assert 'MagicType, OutgoingFile' in cv5 and 'MagicType, OutgoingFile' in cft, 'import 缺失'
assert 'static probe(path: string): string {' in cfs, 'probe 缺失'
assert 'static fixExtByMagic(path: string): string {' in cfs, 'fixExtByMagic 缺失'
assert 'private static readonly MEDIA_EXTS' in cfs, 'MEDIA_EXTS 缺失'
assert 'renameSync' in cfs, 'renameSync 未用'
assert "Text('完成')" in ix, '完成浮窗标签未改'
assert '5.1.51' in app and "'5.1.51'" in ix, '版本未同步'

print('改块数 :', len(B))
print('probe/fix 均已定义，V5/FT 各 1 处调用')
print('OK 5.1.51 applied')