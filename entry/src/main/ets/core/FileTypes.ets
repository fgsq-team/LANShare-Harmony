/**
 * 文件类型常量与落盘分类 —— 平移自
 *   app/src/main/java/com/fgsqw/lanshare/pojo/message/MessageFileContent.java
 *   app/src/main/java/com/fgsqw/lanshare/config/Config.java (fileTypes 表)
 *   app/src/main/java/com/fgsqw/lanshare/utils/FileUtil.java (getNameType)
 *
 * ## ⚠️ 两个容易搞混的类型常量
 * 协议报文里 `fileType` 字段用的是 **MessageFileContent** 的那套（1~9），
 * **不是** LCmd 里的 3001~3004！两者数值完全不同：
 *
 *   LCmd.FILE_IMAGE = 3001      <- 老版本 DataEnc 包体里的字段
 *   MsgFileType.IMAGE = 1       <- v4 JSON 里 "fileType" 的值
 *
 * 用错会导致对端把图片当成普通文件、把文件夹当成单文件（静默丢内容）。
 */
export class MsgFileType {
  static readonly IMAGE: number = 0x1;
  static readonly VIDEO: number = 0x2;
  static readonly AUDIO: number = 0x3;
  static readonly APK: number = 0x4;
  static readonly FILE: number = 0x5;
  static readonly FOLDER: number = 0x6;
  static readonly DOWNLOAD_INFO: number = 0x7;
  static readonly STREAM: number = 0x8;
  static readonly URI: number = 0x9;

  /** 协议里没写 fileType 时的默认值（与原实现一致） */
  static readonly DEFAULT: number = MsgFileType.FILE;
}

/** 分类名常量，与 Config.fileTypes 第二列一致 */
export class FileCategory {
  static readonly ARCHIVE: string = '压缩包';
  static readonly APP: string = '软件';
  static readonly VIDEO: string = '视频';
  static readonly AUDIO: string = '音频';
  static readonly IMAGE: string = '图片';
  static readonly DOC: string = '文档';
  static readonly SHEET: string = '表格';
  static readonly OTHER: string = '其他';
}

export class FileKinds {
  /**
   * 扩展名 -> 分类目录名。
   * 逐条照抄原 Config.fileTypes（后缀 -> 分类），未命中返回「其他」。
   * 对应 FileUtil.getNameType()。
   */
  /**
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

  /** ★★ 5.1.52：取扩展名（空串 = 识别不出，交给魔数）。见 LanService.splitExt 注释。 */
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

  static classify(fileName: string): string {
    // ★ 5.1.48：先剥尾部的 ` (n)` 复制后缀，否则 `xxx.jpg (1)` 归到「其他」。
    // ★ 5.1.52：改用 `extOf`（从右往左找已知扩展名），
    //   否则 `x.jpg.1` 会取出 `'1'` 而归到「其他」。
    const suffix: string = FileKinds.extOf(fileName);
    if (suffix.length === 0) {
      return FileCategory.OTHER;
    }
    // 用并列 if 而不是 Map：条目少、编译期常量折叠、无哈希开销
    if (suffix === 'zip' || suffix === 'rar' || suffix === '7z') {
      return FileCategory.ARCHIVE;
    }
    if (suffix === 'apk') {
      return FileCategory.APP;
    }
    if (suffix === 'mp4' || suffix === 'avi' || suffix === 'rmvb' || suffix === '3gp') {
      return FileCategory.VIDEO;
    }
    if (suffix === 'aac' || suffix === 'm4a' || suffix === 'ape'
      || suffix === 'flac' || suffix === 'wav') {
      return FileCategory.AUDIO;
    }
    if (suffix === 'png' || suffix === 'jpg' || suffix === 'jpeg' || suffix === 'gif') {
      return FileCategory.IMAGE;
    }
    if (suffix === 'txt' || suffix === 'doc' || suffix === 'docx' || suffix === 'obt') {
      return FileCategory.DOC;
    }
    if (suffix === 'xls' || suffix === 'xlsx') {
      return FileCategory.SHEET;
    }
    return FileCategory.OTHER;
  }

  /**
   * ★ 5.1.48：剥掉文件名尾部的**复制/去重后缀** ` (n)`。
   * `扫描全能王 2026-10-01 09.47.jpg (1)` → `扫描全能王 2026-10-01 09.47.jpg`。
   *
   * ⚠️ 本函数与 `LanService.stripCopySuffix` 是**同一份逻辑的两处拷贝**
   *   （core 不能反向依赖 service）。改一处必须改另一处。
   */
  /** ★ 5.1.50：去尾部空白（与 LanService.rtrim 同款，改一处必须改另一处） */
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
    for (let k: number = 0; k < 8; k++) {
      // ★ 5.1.50：与 `LanService.stripCopySuffix` 同款修正 ——
      //   剥完 `(1)` 要去掉尾部空格（`x.jpg (1)` → `x.jpg ` → 后缀 `jpg ` 失效）
      n = FileKinds.rtrim(n);
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
   * 判断文件类型代号是否属于「媒体」，用于决定是否记录到媒体库。
   * 对应原实现的 FILE_TYPE_IMAGE || FILE_TYPE_VIDEO 判断。
   */
  static isMedia(fileType: number): boolean {
    return fileType === MsgFileType.IMAGE || fileType === MsgFileType.VIDEO;
  }

  /**
   * 从文件名推导协议 fileType。用于**发送**时给每个文件打标签。
   * 原 Android 侧的发送方是按用户从哪个界面选的来决定类型，鸿蒙侧
   * 统一走系统文件选择器，只能按扩展名推断 —— 这是行为差异，但协议兼容。
   */
  static inferType(fileName: string): number {
    const category: string = FileKinds.classify(fileName);
    switch (category) {
      case FileCategory.IMAGE: return MsgFileType.IMAGE;
      case FileCategory.VIDEO: return MsgFileType.VIDEO;
      case FileCategory.AUDIO: return MsgFileType.AUDIO;
      case FileCategory.APP: return MsgFileType.APK;
      default: return MsgFileType.FILE;
    }
  }

  /**
   * 重名时追加 (n)。对应 FileUtil.avoidDuplication()。
   * 调用方提供 exists 判断（沙箱里查文件是否存在）。
   */
  static dedupeName(name: string, exists: (candidate: string) => boolean): string {
    if (!exists(name)) {
      return name;
    }
    const dot: number = name.lastIndexOf('.');
    const hasExt: boolean = dot > 0;
    const prefix: string = hasExt ? name.substring(0, dot) : name;
    const ext: string = hasExt ? name.substring(dot) : '';
    for (let s = 1; s < 65535; s++) {
      const candidate: string = `${prefix}(${s})${ext}`;
      if (!exists(candidate)) {
        return candidate;
      }
    }
    return `${prefix}(${Date.now()})${ext}`;
  }
}
