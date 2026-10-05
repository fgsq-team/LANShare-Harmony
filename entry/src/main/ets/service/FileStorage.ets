/**
 * 文件落盘与读取 —— 替代 Android 侧基于 java.io.File / FileInputStream 的那一套。
 *
 * ## 落盘位置的选择（鸿蒙与 Android 的形态差异）
 * Android 版直接写外部存储 `Environment.getExternalStorageDirectory()/LANShare/`。
 * 鸿蒙没有「全盘读写」这种能力，只有两条路：
 *
 * | 方案 | 权限 | 用户体验 |
 * |---|---|---|
 * | `Environment.getUserDownloadDir()` | `READ_WRITE_DOWNLOAD_DIRECTORY`（user_grant，需弹窗） | 文件直接进「下载」，文件管理器可见 |
 * | 应用沙箱 `ctx.filesDir` | 无需任何权限 | 文件在应用私有目录，用户不容易找到 |
 *
 * 本实现**优先走下载目录**（拿到授权后体验与原版一致），
 * 未授权或调用失败时**自动降级到沙箱**并如实汇报给 UI ——
 * 宁可功能可用但位置不同，也不要因为一个权限没给就整个收不了文件。
 *
 * ## 读取待发文件
 * 走系统文件选择器（DocumentViewPicker）拿到的 URI 可直接 `fileIo.openSync`，
 * 不需要任何存储权限 —— 这是鸿蒙"用户授权目录"模型的标准姿势。
 */
import { fileIo, Environment } from '@kit.CoreFileKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { FileKinds } from '../core/FileTypes';
import { Log } from '../core/Logger';
import { PermissionGate } from './PermissionGate';

const TAG: string = 'FileStorage';

/** 落盘位置类型 */
export class SaveLocation {
  static readonly DOWNLOAD: number = 1;
  static readonly SANDBOX: number = 2;
  static readonly UNRESOLVED: number = 0;
}

export class FileStorage {
  /** 实际生效的保存根目录 */
  private root: string = '';
  private location: number = SaveLocation.UNRESOLVED;
  /** 沙箱兜底目录，始终可用 */
  private sandboxRoot: string = '';
  /**
   * 没能用上「下载」目录的原因。
   * 必须留着 —— 因为「权限已给但系统不支持这个 API」和「权限没给」
   * 在 `describe` 里长得一模一样，但对用户的处置建议完全相反。
   */
  private fallbackWhy: string = '';

  /** 是否按类型分子目录。对应 Config.SAVE_FILES_CATEGORY */
  private byCategory: boolean = true;

  init(sandboxRoot: string): void {
    this.sandboxRoot = sandboxRoot;
    this.root = sandboxRoot;
    this.location = SaveLocation.SANDBOX;
    this.fallbackWhy = '未申请授权';
    this.tryDownloadDir();
    try {
      fileIo.mkdirSync(this.root, true);
    } catch (e) {
      // 已存在会抛，忽略
    }
    Log.i(TAG, `保存根目录 = ${this.root}（${this.describe}）`);
  }

  /**
   * 试一次「下载」目录，成功就切过去，失败就记下原因。
   *
   * ⚠️ 第一步必须是**设备能力**判定，不能上来就申请权限：
   * `Environment.getUserDownloadDir()` 需要 `SystemCapability.FileManagement.File.Environment.FolderObtain`，
   * 该能力官方仅 PC/2in1 与 Tablet 提供。手机形态上它不存在，
   * 直接申请 `READ_WRITE_DOWNLOAD_DIRECTORY` 只会拿回 `authResult=2`（请求非法），
   * 现象像"权限怎么都申请不上"，其实跟权限无关 —— 要先把这条误判路径掐掉。
   */
  private tryDownloadDir(): boolean {
    if (!PermissionGate.supportsUserDownloadDir()) {
      this.fallbackWhy = '本机不支持预授权目录（官方仅 PC/2in1 与平板提供该能力）';
      Log.i(TAG, 'canIUse(FolderObtain)=false，直接使用沙箱目录');
      return false;
    }
    try {
      const dl: string = Environment.getUserDownloadDir();
      if (dl.length === 0) {
        this.fallbackWhy = '系统返回了空的下载目录';
        return false;
      }
      this.root = `${dl}/LANShare`;
      this.location = SaveLocation.DOWNLOAD;
      this.fallbackWhy = '';
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      // 能力已存在的前提下：201 = 权限未授予；801 = 能力不支持；其它按未知处理
      if (err.code === 201) {
        this.fallbackWhy = '未取得「下载」目录权限';
      } else if (err.code === 801) {
        this.fallbackWhy = '本机不支持预授权目录（801）';
      } else {
        this.fallbackWhy = `下载目录不可用（${err.code}）`;
      }
      Log.w(TAG, `下载目录不可用（${this.fallbackWhy}）`);
      return false;
    }
  }

  get saveRoot(): string {
    return this.root;
  }

  get where(): number {
    return this.location;
  }

  /** 人类可读的位置说明，直接展示到 UI */
  get describe(): string {
    if (this.location === SaveLocation.DOWNLOAD) {
      return '下载/LANShare';
    }
    if (this.location === SaveLocation.SANDBOX) {
      const why: string = this.fallbackWhy.length > 0 ? `：${this.fallbackWhy}` : '';
      // 「文件管理器里看不到」这句必须写出来 —— 否则用户收完文件找不到，
      // 会以为是传输失败，而实际上文件好好地躺在沙箱里。
      return `应用沙箱（系统文件管理器中看不到）${why}`;
    }
    return '未初始化';
  }

  /** 尝试重新申请下载目录（用户刚给了权限时调用） */
  refreshDownloadDir(): void {
    if (this.tryDownloadDir()) {
      try {
        fileIo.mkdirSync(this.root, true);
      } catch (e) {
        // 已存在
      }
      Log.i(TAG, `已切换到下载目录: ${this.root}`);
    }
  }

  /** 按分类算出目标目录并确保存在 */
  categoryDir(fileName: string): string {
    const dir: string = this.byCategory ? `${this.root}/${FileKinds.classify(fileName)}` : this.root;
    FileStorage.mkdirs(dir);
    return dir;
  }

  /** 递归建目录。已存在不报错 */
  static mkdirs(dir: string): void {
    try {
      fileIo.mkdirSync(dir, true);
    } catch (e) {
      // 已存在会抛，忽略
    }
  }

  /** 指定目录下的不重名路径（等价于 this.uniquePath，供静态调用） */
  static uniquePathIn(dir: string, fileName: string): string {
    const safeName: string = FileStorage.sanitize(fileName);
    const name: string = FileKinds.dedupeName(safeName, (candidate: string): boolean => {
      try {
        return fileIo.accessSync(`${dir}/${candidate}`);
      } catch (e) {
        return false;
      }
    });
    return `${dir}/${name}`;
  }

  /**
   * 在目录下生成不冲突的文件名。
   * 对应 FileUtil.avoidDuplication() —— 重名追加 (n)，不是覆盖。
   */
  uniquePath(dir: string, fileName: string): string {
    return FileStorage.uniquePathIn(dir, fileName);
  }

  /**
   * 去掉文件名里的路径分隔符。
   * ⚠️ 必须做：对端可以发来 `../../xxx` 这种名字，直接拼接会写到目录外。
   */
  static sanitize(fileName: string): string {
    let out: string = fileName.replace(/[\\/]/g, '_');
    out = out.replace(/^\.+/, '');
    if (out.length === 0) {
      out = `unnamed_${Date.now()}`;
    }
    return out;
  }
}

/**
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
  /**
   * 读文件头 N 字节；失败返回长度 0 的数组（上层据此跳过探测）。
   *
   * ⚠️ 写法照抄 `Index.jpegExifDeg`：**用模块函数 `fileIo.readSync(fd, buf)`**，
   *   不是 `File` 实例方法（`f.readSync` / `f.closeSync` 在本 SDK **不存在**，
   *   编译报 `Property 'readSync' does not exist on type 'File'`）。
   */
  private static head(path: string, n: number): Uint8Array {
    let fd: number = -1;
    try {
      const f: fileIo.File = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);
      fd = f.fd;
      const buf: ArrayBuffer = new ArrayBuffer(n);
      const got: number = fileIo.readSync(fd, buf);
      return new Uint8Array(buf, 0, got);
    } catch (e) {
      return new Uint8Array(0);
    } finally {
      if (fd >= 0) {
        try {
          fileIo.closeSync(fd);
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

  /** ★ 5.1.52：去尾部空白（与 LanService.rtrim / FileKinds.rtrim 同款）。
   *  ⚠️ 本类不能反向依赖那两个（会成循环依赖），故自带一份。 */
  private static rtrim(s: string): string {
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

  /**
   * ★★ 5.1.54：**同一媒体类型的「等价后缀组」** —— 判「末尾后缀对不对」的唯一标准。
   *
   * ## 为什么需要它
   *   vivi 定的规则是「后缀正确就不管，不正确就把正确后缀**加到文件名最后**」。
   *   但 `a.jpeg` 与 `a.jpg` 的内容都是 jpeg —— **同一类型，不该互相改名**
   *   （否则 `a.jpeg` → `a.jpeg.jpg`，荒谬）。
   *   ⇒ 必须有「等价组」才能判断「末尾后缀是否已经正确」。
   *
   * ★ 这张表就是 UTD `TypeDescriptor.filenameExtensions` 的等价物
   *   （同一份类型描述符下的所有标准后缀），只是我用魔数直接驱动、不查 UTD。
   */
  private static readonly EQUIV_EXTS: string[][] = [
    ['jpg',  'jpg', 'jpeg', 'jpe', 'jfif'],
    ['png',  'png'],
    ['gif',  'gif'],
    ['bmp',  'bmp'],
    ['webp', 'webp'],
    ['heic', 'heic', 'heif', 'heics'],
    ['avif', 'avif'],
    ['tiff', 'tif', 'tiff'],
    ['mp4',  'mp4', 'm4v', 'mpeg4'],
    ['mov',  'mov', 'qt'],
    ['3gp',  '3gp', '3g2', '3gpp'],
    ['mkv',  'mkv', 'webm'],
    ['avi',  'avi'],
    ['flv',  'flv'],
    ['mp3',  'mp3'],
    ['m4a',  'm4a', 'aac', 'mp4a'],
    ['wav',  'wav', 'wave'],
    ['ogg',  'ogg', 'opus'],
    ['flac', 'flac'],
  ];

  /** ★ 5.1.54：`tail` 与魔数探测结果 `det` 是否属于同一媒体类型（大小写不敏感） */
  /// ★★ 5.1.63 B1 BUG FIX：原为 `row.indexOf(t) >= 1`。
  ///   `EQUIV_EXTS` 的 **row[0] 就是规范名本身**，所以 `indexOf('jpg')` 返回 **0**，
  ///   `0 >= 1` 为 false ⇒ **jpg 与 jpg 被判成不同类** ⇒ 触发改名。
  ///   现象（vivi 2026-10-05 真机 425 张批量）：
  ///     `SelfieCity_xxx_save.jpg` → `SelfieCity_xxx_save_jpg.jpg`
  ///   （再经 5.1.57 的 dotsToUnderscores 把点换成 _ ⇒ 成了 `_jpg.jpg`）
  ///   ★ 只有**非规范名**（jpeg/jpe/jfif）碰巧正确 ⇒ 表现为「**有些** jpg 被加后缀」。
  ///   正解：`>= 0`（0 位是规范名本身，也算等价）。
  static sameKind(tail: string, det: string): boolean {
    const t: string = MagicType.rtrim(tail).toLowerCase();
    const d: string = MagicType.rtrim(det).toLowerCase();
    if (t.length === 0) {
      return false;
    }
    for (let i: number = 0; i < MagicType.EQUIV_EXTS.length; i++) {
      const row: string[] = MagicType.EQUIV_EXTS[i];
      if (row[0] === d) {
        return row.indexOf(t) >= 0;   // ★ 5.1.63 B1：0 位是规范名本身，必须算等价
      }
    }
    return t === d;
  }

  /** ★ 5.1.54：剥掉文件名尾部的 ` (n)` 复制后缀（最多 8 层） */
  static rstripCopy(name: string): string {
    let n: string = name;
    for (let k: number = 0; k < 8; k++) {
      n = MagicType.rtrim(n);
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
   * ★★ 5.1.57：把 stem 里的**所有 `.` 换成 `_`** —— 改名时用。
   *
   * ## 为什么（vivi 2026-10-03 观察到的现象）
   *   相册把 `abc.1` 存成 `abc_1.jpg` / `abc_1_1.jpg` / `abc_1_2.jpg`
   *   ⇒ 沙箱里也保持同样写法，文件名与相册一致、也不再有多扩展名歧义。
   *
   * ## 为什么不用 `replaceAll`
   *   ArkTS 的 `String.replaceAll` 在低版本 SDK 上行为不稳，
   *   项目里统一用 `split().join()`（同 `LanService` 等处的既有写法）。
   *
   * ⚠️ **只在「已经决定要改名」之后调用**：
   *   判「末尾后缀对不对」必须用**原始名**（仍带点），
   *   否则 `a.b.jpg` 会被算成「后缀 `_jpg`」⇒ 误判需要改名。
   */
  static dotsToUnderscores(s: string): string {
    if (s.indexOf('.') < 0) {
      return s;
    }
    return s.split('.').join('_');
  }

  /** ★ 5.1.55：取路径里的**文件名部分**（去掉目录） */
  static baseNameOf(path: string): string {
    const slash: number = path.lastIndexOf('/');
    return slash >= 0 ? path.substring(slash + 1) : path;
  }

  /** ★ 5.1.54：取文件名**末尾那一段**后缀（剥掉 ` (n)` 之后） */
  private static tailExt(base: string): string {
    const dot: number = base.lastIndexOf('.');
    if (dot <= 0 || dot === base.length - 1) {
      return '';
    }
    return MagicType.rtrim(base.substring(dot + 1)).toLowerCase();
  }

  /** ★ 5.1.52：已知扩展名全表（比 MEDIA_EXTS 宽，含 zip/apk/pdf 等） */
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
   * ★★ 5.1.52：文件名 → `[stem, ext]`。
   *
   * ## 为什么不能用 `lastIndexOf('.')`（5.1.51 实测失败的原因）
   *   `IMG_20260929_201632.jpg.1` —— 最后一个点是 `.1`
   *   ⇒ 旧逻辑取到 ext=`'1'` ⇒ ① 判不出该改成 jpg（**没改名**）
   *                            ② 存相册 `fileNameExtension='1'` ⇒ **系统拒绝**。
   *   `a.jpg (1)` / `.jpg.1.1` / `报告 v1.2.pdf` 同样会被误切。
   *
   * ## 规则：**从右往左**找**第一个命中 KNOWN_EXTS** 的段当扩展名，
   *   其左侧全部是 stem。命中不了（如 `data.2026-10-01.dat`）⇒ 返回空 ext，
   *   **交给魔数**判断。
   * ⚠️ 不能用「段长 1~5 且字母数字」这种宽松判据 —— `1` 恰好满足（实测踩过）。
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
      const dir: string = slash >= 0 ? path.substring(0, slash) : '';
      // ★★★ 5.1.54：**完全不看「文件名里有哪些扩展名」，只看末尾那一段**。
      //   规则（vivi 定）：**后缀正确就不管，不正确就把正确后缀加到文件名最后。**
      //   1) 先剥掉 ` (n)` 复制后缀 —— `a.jpg (1)` 的真实名字是 `a.jpg`；
      //   2) 取**最后一个点之后**那段（`abc.1` ⇒ `1`）；
      //   3) 与魔数结果**同类型**（等价组判重）⇒ 已正确，不动；
      //   4) 否则把规范后缀**追加**到末尾（不替换、不删原名）。
      const base: string = MagicType.rstripCopy(MagicType.rtrim(
        slash >= 0 ? path.substring(slash + 1) : path));
      if (MagicType.sameKind(MagicType.tailExt(base), real)) {
        return path;                       // 后缀已正确 ⇒ 不管
      }
      const target: string = `${dir}/${base}.${real}`;
      if (target === path) {
        return path;
      }
      // ★★★★★ 5.1.56 真凶修复：`fileIo.accessSync` 的签名是 **返回 boolean**
      //   （`accessSync(path, mode?): boolean`，文件不存在时返回 false、**不抛异常**）。
      //   旧代码写成「try { accessSync } catch { 不存在 }」⇒ 不抛异常被当成「已存在」
      //   ⇒ **每一次都在这里 return，renameSync 从未执行过**（5.1.51~5.1.55 全白改）。
      //   ⚠️ 同一个 SDK 语义在别处（HttpRouter / LanService / dedupeName）都是用返回值判的，
      //      只有这一处反了 —— 这就是「换个 bug 还会撞上」的那类坑。
      //   ★ 5.1.56 目标已存在 ⇒ **递增去重**而不是放弃：
      //     「放弃」会让同名文件第二次接收时又变成非图片 ⇒ 又一次「不弹相册框」，
      //     等于把 bug 换个入口复现。要保住不变量：**纠错后后缀必然正确**。
      // ★★ 5.1.57：决定改名之后，把 stem 里的点全换成下划线，
      //   只保留这里新增的**一个**后缀点（`abc.1` → `abc_1.jpg`）。
      //   ⚠️ 上面的 `sameKind` 判定用的是**原始 base**（仍带点）—— 顺序不能颠倒。
      const stem: string = MagicType.dotsToUnderscores(base);
      let finalName: string = `${stem}.${real}`;
      let exists: boolean = false;
      try {
        exists = fileIo.accessSync(`${dir}/${finalName}`);
      } catch (e) {
        exists = false;   // 查不到就当作不存在，交给 renameSync 裁决
      }
      if (exists) {
        for (let k: number = 2; k < 50; k++) {
          const cand: string = `${stem} (${k}).${real}`;
          let hit: boolean = false;
          try {
            hit = fileIo.accessSync(`${dir}/${cand}`);
          } catch (e2) {
            hit = false;
          }
          if (!hit) {
            finalName = cand;
            exists = false;
            break;
          }
        }
        if (exists) {
          Log.w(TAG, `魔数纠错：${stem}.${real} 的候选名都被占用，保持原名`);
          return path;
        }
      }
      const finalPath: string = `${dir}/${finalName}`;
      fileIo.renameSync(path, finalPath);
      Log.i(TAG, `魔数纠错：${MagicType.baseNameOf(path)} → ${finalName}`);
      return finalPath;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `魔数纠错失败（保持原名）: ${err.code} ${err.message}`);
      return path;
    }
  }
}

/** 接收侧的文件写入器：边收边写，不整包缓存 */
export class FileSink {

  private fd: number = -1;
  private written: number = 0;
  readonly path: string;

  private constructor(path: string, fd: number) {
    this.path = path;
    this.fd = fd;
  }

  /** 创建（或截断）目标文件 */
  static create(path: string): FileSink | null {
    try {
      const f: fileIo.File = fileIo.openSync(
        path,
        fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC
      );
      return new FileSink(path, f.fd);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `创建文件失败 ${path}: ${err.code} ${err.message}`);
      return null;
    }
  }

  /** 创建空文件（用于 0 字节文件 / 目录占位） */
  static createEmpty(path: string): boolean {
    try {
      const f: fileIo.File = fileIo.openSync(
        path, fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE);
      fileIo.closeSync(f.fd);
      return true;
    } catch (e) {
      Log.e(TAG, `创建空文件失败 ${path}`);
      return false;
    }
  }

  get bytesWritten(): number {
    return this.written;
  }

  append(data: Uint8Array): boolean {
    if (this.fd < 0) {
      return false;
    }
    try {
      // ⚠️⚠️ 5.1.38 回退说明（**踩过的坑，勿再改**）：
      //   5.1.37 曾改成 `writeSync(fd, data.buffer, {offset, length})` 想省掉这次拷贝，
      //   **是错的** —— SDK WriteOptions 的 offset 语义是
      //   「Start position of the file to write (current filePointer + offset)」，
      //   即**文件内偏移**，不是 buffer 内偏移。
      //   真机后果：处理 586 MB，落地文件只有 1.0 MB（写到了错误位置）。
      //   而 `writeSync` 并没有「只写 buffer 子区间」的参数 ⇒ 传 subarray 视图
      //   必须先拷贝出精确大小的 buffer。
      const exact: boolean = data.byteOffset === 0 && data.byteLength === data.buffer.byteLength;
      const buf: ArrayBuffer = exact
        ? data.buffer as ArrayBuffer
        : data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;
      const n: number = fileIo.writeSync(this.fd, buf);
      this.written += n;
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `写文件失败: ${err.code} ${err.message}`);
      return false;
    }
  }

  close(): void {
    if (this.fd < 0) {
      return;
    }
    try {
      fileIo.closeSync(this.fd);
    } catch (e) {
      // ignore
    }
    this.fd = -1;
  }
}

/** 待发送文件：由系统文件选择器给出的 URI 打开 */
export class OutgoingFile {
  /** 展示名 */
  name: string = '';
  /** 字节大小。仅当 sizeKnown=true 时可信 */
  size: number = 0;
  /**
   * 大小是否已成功探测。
   *
   * ⚠️ 这个标志是**必须**的，不能省。
   *
   * v4 协议的接收方**完全按 transferJson 里声明的 length 收字节**，收满即停；
   * 发送方则「读文件读到 EOF 就结束」。两边都只看 length。
   * 所以在「拿不到真实大小」时如果填了 0，会同时踩两个坑：
   *   1. 接收端直接建一个 0 字节空文件（它的逻辑是 length<=0 就 createNewFile）；
   *   2. 发送端也「按约定」一片都不发。
   * 双方都认为自己成功了，用户拿到一个空文件 —— 而且没有任何报错。
   *
   * 因此「大小未知」必须是**硬错误**，绝不能与「真的是 0 字节文件」混为一谈。
   */
  sizeKnown: boolean = false;
  /** 内容 URI（file:// 或 datashare://），DocumentViewPicker 的返回值 */
  uri: string = '';
  /** 协议 fileType，由扩展名推断，见 FileKinds.inferType */
  fileType: number = 0;

  static fromUri(uri: string): OutgoingFile {
    const f: OutgoingFile = new OutgoingFile();
    f.uri = uri;
    f.name = OutgoingFile.displayName(uri);
    f.fileType = FileKinds.inferType(f.name);
    // ★ DocumentViewPicker 只返回 URI，不带 size。
    //   这里必须自己 stat 一次，否则 transferJson 里的 length 恒为 0。
    const st: FileSizeResult = OutgoingFile.statSize(uri);
    f.size = st.size;
    f.sizeKnown = st.ok;
    return f;
  }

  /**
   * 探测文件大小。走 openSync + statSync(fd)，与 FileSource.open 同一条路径，
   * 保证「报给对端的大小」和「实际读出来的字节数」同源。
   */
  private static statSize(uri: string): FileSizeResult {
    const out: FileSizeResult = new FileSizeResult();
    let fd: number = -1;
    try {
      fd = fileIo.openSync(uri, fileIo.OpenMode.READ_ONLY).fd;
      const n: number = fileIo.statSync(fd).size;
      out.size = n > 0 ? n : 0;
      out.ok = true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `取文件大小失败（该文件将被拒绝发送）${uri}: ${err.code} ${err.message}`);
      out.ok = false;
    } finally {
      if (fd >= 0) {
        try {
          fileIo.closeSync(fd);
        } catch (e) {
          // 已关闭，忽略
        }
      }
    }
    return out;
  }

  /** 从 URI 尾部取文件名，并做一次 URL 解码 */
  static displayName(uri: string): string {
    let s: string = uri;
    const q: number = s.indexOf('?');
    if (q >= 0) {
      s = s.substring(0, q);
    }
    const slash: number = s.lastIndexOf('/');
    if (slash >= 0) {
      s = s.substring(slash + 1);
    }
    try {
      s = decodeURIComponent(s);
    } catch (e) {
      // 解码失败就用原文
    }
    return FileStorage.sanitize(s.length > 0 ? s : `file_${Date.now()}`);
  }
}

/** statSize 的结果。用具名类而不是元组，避免 ArkTS 对解构的限制 */
class FileSizeResult {
  ok: boolean = false;
  size: number = 0;
}

/** 发送侧的文件读取器：按块读，不整包加载 */
export class FileSource {
  private fd: number = -1;
  readonly size: number;

  private constructor(fd: number, size: number) {
    this.fd = fd;
    this.size = size;
  }

  static open(uri: string): FileSource | null {
    try {
      const f: fileIo.File = fileIo.openSync(uri, fileIo.OpenMode.READ_ONLY);
      let size: number = 0;
      try {
        size = fileIo.statSync(f.fd).size;
      } catch (e) {
        Log.w(TAG, 'stat 失败，按 0 处理');
      }
      return new FileSource(f.fd, size);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `打开文件失败 ${uri}: ${err.code} ${err.message}`);
      return null;
    }
  }

  /**
   * 读一块，返回实际读到的字节。
   *
   * ⚠️ 每次按 `size` 新分配一个 ArrayBuffer 而不是复用一个大缓冲：
   * `readSync(fd, buffer)` 是按**传入缓冲区的长度**去读的，
   * 复用 1MB 大缓冲去读最后一个不满的块，就会把下一个文件的开头也读进来，
   * 造成整条流错位。宁可多几次小分配，也不要那种错位 bug。
   *
   * fileIo 的内部文件偏移会随每次 readSync 自动推进，所以不需要手动 seek。
   *
   * @returns 读到的字节；null 表示已到末尾或出错
   */
  readChunk(size: number): Uint8Array | null {
    if (this.fd < 0 || size <= 0) {
      return null;
    }
    try {
      const buf: ArrayBuffer = new ArrayBuffer(size);
      const n: number = fileIo.readSync(this.fd, buf);
      if (n <= 0) {
        return null;
      }
      return new Uint8Array(buf, 0, n);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `读文件失败: ${err.code} ${err.message}`);
      return null;
    }
  }

  /**
   * 把读指针定位到**绝对偏移**（默认 `SEEK_SET`，从文件开头算）。
   *
   * 分片发送（1110）时每片只发 `[start, start+len)` 这一段，所以必须先定位。
   * `fileIo.lseek(fd, pos)` 第三参省略即 `SEEK_SET`（`@ohos.file.fs.d.ts:1689`）。
   */
  seek(pos: number): boolean {
    if (this.fd < 0 || pos < 0) {
      return false;
    }
    try {
      fileIo.lseek(this.fd, pos);
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `seek(${pos}) 失败: ${err.code} ${err.message}`);
      return false;
    }
  }

  close(): void {
    if (this.fd < 0) {
      return;
    }
    try {
      fileIo.closeSync(this.fd);
    } catch (e) {
      // ignore
    }
    this.fd = -1;
  }
}
