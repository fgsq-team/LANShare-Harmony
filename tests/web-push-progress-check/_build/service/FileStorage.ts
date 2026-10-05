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

import * as __fs from 'node:fs';
const fileIo = {
  OpenMode: { READ_ONLY: 0, WRITE_ONLY: 1, READ_WRITE: 2, CREATE: 64, TRUNC: 512, APPEND: 1024 },
  openSync(p, mode) {
    const m = (mode === 0) ? 'r' : ((mode & 512) ? 'w' : 'a');
    return { fd: __fs.openSync(p, m) };
  },
  writeSync(fd, buf) { return __fs.writeSync(fd, Buffer.from(buf)); },
  readSync(fd, buf) { return __fs.readSync(fd, Buffer.from(buf), 0, buf.byteLength, null); },
  closeSync(f) { try { __fs.closeSync(typeof f === 'number' ? f : f.fd); } catch (e) {} },
  mkdirSync(p, recursive) { try { __fs.mkdirSync(p, { recursive: !!recursive }); } catch (e) {} },
  // ⚠️ 真机 fileIo.accessSync 返回 boolean；Node 的 accessSync 是不存在就抛。
  //    不接住的话交付代码里 "if (!fileIo.accessSync(dir))" 会直接抛到 catch，
  //    表现成"临时目录不可用"，与真实行为完全相反。
  accessSync(p) { try { __fs.accessSync(p); return true; } catch (e) { return false; } },
  unlinkSync(p) { __fs.unlinkSync(p); },
  listFileSync(p) { return __fs.readdirSync(p); },
  statSync(p) {
    const s = (typeof p === 'number') ? __fs.fstatSync(p) : __fs.statSync(p);
    return {
      size: s.size,
      mtime: Math.floor(s.mtimeMs / 1000),
      isDirectory: () => s.isDirectory(),
      isFile: () => s.isFile()
    };
  }
};
const Environment = { getUserDownloadDir: () => '' };

class BusinessError extends Error {
  constructor(code, message) { super(message || ''); this.code = code || 0; }
}

import { FileKinds } from '../core/FileTypes.ts';
import { Log } from '../core/Logger.ts';

class PermissionGate {
  static supportsUserDownloadDir() { return false; }
  static async ensureDownloadDirDetailed() { return { granted: false, detail: '' }; }
}

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
      // 快速路径：切片出来的 Uint8Array 其 buffer 通常就是精确大小
      // （byteOffset=0 且 byteLength=buffer.byteLength），这时不必再复制一份。
      // 上传落盘是逐块写的，每块省一次整块复制，累积起来很可观。
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
