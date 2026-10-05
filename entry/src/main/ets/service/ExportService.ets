/**
 * 「另存为」导出服务 —— 把沙箱里收到的文件搬到用户能看到的地方。
 *
 * ## 为什么必须有它
 * 手机的 `Environment.getUserDownloadDir()` 依赖
 * `SystemCapability.FileManagement.File.Environment.FolderObtain`，
 * 而该能力官方只给 PC / 2in1 / 平板（实测见 docs/迁移对照表.md 第十三节，
 * 本机 `const.product.devicetype = phone`，`canIUse()` 直接返回 false）。
 *
 * 后果：**手机形态上收到的文件只能落在应用沙箱**
 * （`/data/storage/el2/base/haps/entry/files/LANShare/`），
 * 在系统「文件管理」里根本看不到。用户传完文件找不到，
 * 观感上跟"传输失败"一模一样。
 *
 * ## 这里补的三件事
 *   1. `listReceived()` —— 列出沙箱里已接收的文件，供 UI 展示
 *   2. `saveAs()`       —— 弹系统保存对话框，用户选定位置后复制过去
 *   3. `deleteFile()` / `deleteAll()` —— 删掉沙箱里的文件
 *
 * 走的是「用户显式选一次」的模型：鸿蒙不向三方应用开放常驻的全盘写权限，
 * 但**用户主动选定的位置**是可写的，这正是 DocumentViewPicker 的用途。
 *
 * ## ⚠️ 删除必须带路径守卫
 * 删除入口收到的路径只信任「落盘根目录」以内的。**不做校验等于给了一个任意文件删除口**——
 * 路径里带 `..` 或指向 root 之外的一律拒绝，宁可让用户删不掉，也不能误删系统或别的应用的文件。
 */
import { common } from '@kit.AbilityKit';
import { picker } from '@kit.CoreFileKit';
import { fileIo } from '@kit.CoreFileKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { Log } from '../core/Logger';

const TAG: string = 'Export';

/** 一次列出的文件条数上限，避免目录很大时卡 UI */
/// ★★ 5.1.63 B3：40 → 1000。
///   vivi 2026-10-05 真机：存了 200 张进相册，但**文件页只显示 40 个**
///   ⇒ 剩下 360 个「看不到」（其实都在沙箱里）。
///   ⚠️ UI 上那句「列表最多显示最近 40 个」的提示文案也要一起改（见 Index.ets）。
const MAX_LIST: number = 1000;
/** 目录递归深度。落盘是一层分类目录（见 FileStorage.categoryDir） */
const MAX_DEPTH: number = 2;
/** 复制缓冲。64KB 在手机上是吞吐与内存的平衡点 */
const COPY_CHUNK: number = 64 * 1024;
/** 「清空」时的最大删除条数，防止目录异常庞大时卡死主线程 */
const MAX_DELETE: number = 3000;

/** 批量删除的结果 */
export class DeleteResult {
  /** 成功删除的条数 */
  ok: number = 0;
  /** 删除失败的条数 */
  failed: number = 0;
  /** 第一条失败原因（给 UI toast 用）；全部成功时为空串 */
  firstError: string = '';
}

/**
 * 批量另存的结果。
 *
 * ⚠️ 为什么不能只返回一个字符串：UI 必须能区分
 *   **「用户主动取消了保存对话框」** 与 **「保存动作失败了」**，
 *   因为两者的后续处理完全相反 ——
 *   取消 ⇒ 保留用户已经勾好的那些文件（否则用户得重新一份份勾回来）；
 *   失败 ⇒ 可以提示结果，但同样不该把用户的勾选清掉。
 *   上一版只有一个字符串，UI 只能无条件退出多选，
 *   于是「取消保存 → 多选也没了」（vivi 2026-10-01 真机反馈）。
 */
export class SaveOutcome {
  /** 用户取消了保存对话框（没选目标位置） */
  cancelled: boolean = false;
  /** 实际成功保存的条数 */
  saved: number = 0;
  /**
   * ★ 5.0.53：**成功保存过的那些源文件**（沙箱绝对路径）。
   * 调用方据此把沙箱副本删掉 —— vivi 2026-10-02 要求「另存到本地后不留双份」。
   * ⚠️ 只收成功的：失败 / 用户取消的一律不收（那份还没落到应用之外，是唯一的一份）。
   */
  savedPaths: string[] = [];
  /** 给用户看的文案 */
  msg: string = '';
}

/** 沙箱里一个已接收的文件 */
export class ReceivedFile {
  name: string = '';
  /** 沙箱绝对路径（另存为的源） */
  path: string = '';
  size: number = 0;
  /** 毫秒时间戳 */
  time: number = 0;

  /** 给 UI 用的可读大小 */
  get sizeText(): string {
    return ExportService.humanSize(this.size);
  }

  /** 给 UI 用的可读时间 */
  get timeText(): string {
    const d: Date = new Date(this.time);
    return `${d.getMonth() + 1}-${ExportService.pad2(d.getDate())} ` +
      `${ExportService.pad2(d.getHours())}:${ExportService.pad2(d.getMinutes())}`;
  }
}

export class ExportService {
  /**
   * 列出某个根目录下已接收的文件（含一层分类子目录），按修改时间倒序。
   *
   * 目录不存在或不可读时返回空数组 —— 这不是错误状态，
   * 「还没收过文件」和「目录读不了」对用户都是"列表为空"，不必区分。
   */
  static listReceived(root: string): ReceivedFile[] {
    const out: ReceivedFile[] = [];
    if (root.length === 0) {
      return out;
    }
    ExportService.scan(root, 0, out);
    out.sort((a: ReceivedFile, b: ReceivedFile) => b.time - a.time);
    return out.length > MAX_LIST ? out.slice(0, MAX_LIST) : out;
  }

  private static scan(dir: string, depth: number, out: ReceivedFile[]): void {
    if (depth > MAX_DEPTH || out.length > MAX_LIST * 3) {
      return;
    }
    let names: string[] = [];
    try {
      names = fileIo.listFileSync(dir);
    } catch (e) {
      return;
    }
    for (let i = 0; i < names.length; i++) {
      const name: string = names[i];
      const full: string = `${dir}/${name}`;
      try {
        const st: fileIo.Stat = fileIo.statSync(full);
        if (st.isDirectory()) {
          ExportService.scan(full, depth + 1, out);
        } else {
          const f: ReceivedFile = new ReceivedFile();
          f.name = name;
          f.path = full;
          f.size = st.size;
          f.time = st.mtime * 1000;
          out.push(f);
        }
      } catch (e) {
        // 单个条目读不了就跳过，不影响整表
      }
    }
  }

  /**
   * 删除落盘根目录里的一个文件。
   *
   * @param root 落盘根目录 —— 删除范围的上界。root 为空（共享未开启）时直接拒绝
   * @param path 要删的文件绝对路径
   * @returns null 表示删除成功；非空字符串是给用户的错误文案
   */
  static deleteFile(root: string, path: string): string | null {
    const guard: string | null = ExportService.checkInRoot(root, path);
    if (guard !== null) {
      return guard;
    }
    try {
      fileIo.unlinkSync(path);
      Log.i(TAG, `已删除 ${path}`);
      return null;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `删除失败: ${path} ${err.code} ${err.message}`);
      return `删除失败（${err.code}）`;
    }
  }

  /** 批量删除。逐条独立 —— 一条失败不影响其余（权限/占用往往只影响个别文件） */
  static deleteFiles(root: string, paths: string[]): DeleteResult {
    const r: DeleteResult = new DeleteResult();
    const n: number = paths.length > MAX_DELETE ? MAX_DELETE : paths.length;
    for (let i = 0; i < n; i++) {
      const err: string | null = ExportService.deleteFile(root, paths[i]);
      if (err === null) {
        r.ok++;
      } else {
        r.failed++;
        if (r.firstError.length === 0) {
          r.firstError = err;
        }
      }
    }
    return r;
  }

  /**
   * 落盘目录里的全部文件（**不受列表上限约束**）。
   * 「清空」要删的是所有文件，而 `listReceived` 只给前 40 条，所以这里单独扫一遍。
   */
  static allPaths(root: string): string[] {
    const out: string[] = [];
    if (root.length === 0) {
      return out;
    }
    ExportService.collectAll(root, 0, out);
    return out;
  }

  /** 清空：删掉全部已接收文件，并顺手回收空目录 */
  static deleteAll(root: string): DeleteResult {
    const r: DeleteResult = ExportService.deleteFiles(root, ExportService.allPaths(root));
    ExportService.pruneEmptyDirs(root, 0);
    Log.i(TAG, `清空完成: ok=${r.ok} failed=${r.failed}`);
    return r;
  }

  /**
   * 路径守卫：只放行落盘根目录以内的、不含 `..` 的路径。
   *
   * 这是删除接口的**唯一**边界。宁可让用户删不掉一个文件，
   * 也不能让一个来自网络/剪贴板的路径删掉沙箱外的东西。
   */
  private static checkInRoot(root: string, path: string): string | null {
    if (root.length === 0) {
      return '共享未开启，无法删除';
    }
    if (path.indexOf('..') >= 0) {
      Log.w(TAG, `拒绝删除含 .. 的路径: ${path}`);
      return '路径不合法，已拒绝';
    }
    // ⚠️ 必须比到目录分隔符：`startsWith(root)` 会把 `${root}Backup/a.txt` 这类
    // 「同前缀的兄弟目录」当成在 root 之内而放行 —— 那就是一个目录穿越口子。
    const prefix: string = root.endsWith('/') ? root : `${root}/`;
    if (!path.startsWith(prefix)) {
      Log.w(TAG, `拒绝删除根目录之外的文件: ${path}`);
      return '该文件不在接收目录内，已拒绝删除';
    }
    return null;
  }

  private static collectAll(dir: string, depth: number, out: string[]): void {
    if (depth > MAX_DEPTH || out.length >= MAX_DELETE) {
      return;
    }
    let names: string[] = [];
    try {
      names = fileIo.listFileSync(dir);
    } catch (e) {
      return;
    }
    for (let i = 0; i < names.length; i++) {
      const full: string = `${dir}/${names[i]}`;
      try {
        const st: fileIo.Stat = fileIo.statSync(full);
        if (st.isDirectory()) {
          ExportService.collectAll(full, depth + 1, out);
        } else {
          out.push(full);
        }
      } catch (e) {
        // 单个条目读不了就跳过
      }
    }
  }

  /** 回收空目录。rmdir 对非空目录会失败，失败即忽略 —— 目录不空说明还有文件，不该删 */
  private static pruneEmptyDirs(dir: string, depth: number): void {
    if (depth > MAX_DEPTH) {
      return;
    }
    let names: string[] = [];
    try {
      names = fileIo.listFileSync(dir);
    } catch (e) {
      return;
    }
    for (let i = 0; i < names.length; i++) {
      const full: string = `${dir}/${names[i]}`;
      try {
        const st: fileIo.Stat = fileIo.statSync(full);
        if (st.isDirectory()) {
          ExportService.pruneEmptyDirs(full, depth + 1);
        }
      } catch (e) {
        // 忽略
      }
    }
    if (depth > 0) {
      try {
        fileIo.rmdirSync(dir);
      } catch (e) {
        // 目录非空 —— 正常情况，不处理
      }
    }
  }

  /**
   * 弹系统保存对话框，把 srcPath 另存到用户选定的位置。
   *
   * @returns 成功时的提示文案；用户取消时返回「已取消」
   */
  static async saveAs(ctx: common.UIAbilityContext,
                      srcPath: string,
                      suggestName: string): Promise<string> {
    let dstUri: string = '';
    try {
      const opts: picker.DocumentSaveOptions = new picker.DocumentSaveOptions();
      opts.newFileNames = [suggestName];
      const docPicker: picker.DocumentViewPicker = new picker.DocumentViewPicker(ctx);
      const uris: string[] = await docPicker.save(opts);
      if (uris === undefined || uris.length === 0 || uris[0].length === 0) {
        return '已取消';
      }
      dstUri = uris[0];
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `打开保存对话框失败: ${err.code} ${err.message}`);
      return `打开保存对话框失败（${err.code}）`;
    }

    return ExportService.copyTo(srcPath, dstUri, suggestName);
  }

  /**
   * 批量另存：**一次**弹窗选好目标位置，把多个文件都复制过去。
   *
   * 走 `DocumentSaveOptions.newFileNames` 一次传多个文件名 —— 系统在该目录下
   * 一次性创建它们并返回**同样数量**的 URI（见 `@ohos.file.picker.d.ts` 的
   * `newFileNames?: Array<string>` 与 `save(): Promise<Array<string>>`）。
   * 比「一个一个弹窗」少 N-1 次交互（vivi 2026-10-01 要求「多选后可以一次保存」）。
   *
   * @returns {@link SaveOutcome} —— UI 需要 `cancelled` 来决定「要不要保留多选状态」，
   *          所以这里不能只回一个字符串（见 SaveOutcome 的注释）
   */
  static async saveMany(ctx: common.UIAbilityContext, files: ReceivedFile[]): Promise<SaveOutcome> {
    const out: SaveOutcome = new SaveOutcome();
    if (files.length === 0) {
      out.msg = '未选择文件';
      return out;
    }
    const names: string[] = [];
    for (let i = 0; i < files.length; i++) {
      names.push(files[i].name);
    }
    let uris: string[] = [];
    try {
      const opts: picker.DocumentSaveOptions = new picker.DocumentSaveOptions();
      opts.newFileNames = names;
      const docPicker: picker.DocumentViewPicker = new picker.DocumentViewPicker(ctx);
      const ret: string[] = await docPicker.save(opts);
      if (ret === undefined || ret.length === 0) {
        out.cancelled = true;
        out.msg = '已取消保存（选择已保留）';
        return out;
      }
      uris = ret;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `打开批量保存对话框失败: ${err.code} ${err.message}`);
      out.msg = `打开保存对话框失败（${err.code}）`;
      return out;
    }
    // 正常情况 uris.length === files.length（一个文件名对一个 URI）。
    // 万一系统行为不一致，就按「可配对的」逐对复制，并把差额如实说清楚 ——
    // 宁可少存几个并写明，也不能静默丢掉用户的文件。
    const n: number = uris.length < files.length ? uris.length : files.length;
    let ok: number = 0;
    let firstErr: string = '';
    for (let i = 0; i < n; i++) {
      const msg: string = await ExportService.copyTo(files[i].path, uris[i], files[i].name);
      if (msg.startsWith('已保存')) {
        ok += 1;
        // ★ 5.0.53：记下成功的源路径，UI 拿去删沙箱副本
        out.savedPaths.push(files[i].path);
      } else if (firstErr.length === 0) {
        firstErr = msg;
      }
    }
    out.saved = ok;
    if (ok === files.length) {
      out.msg = `已保存 ${ok} 个文件`;
    } else if (firstErr.length > 0) {
      out.msg = `已保存 ${ok}/${files.length} 个（${firstErr}）`;
    } else {
      out.msg = `已保存 ${ok}/${files.length} 个（保存对话框返回 ${uris.length} 个位置）`;
    }
    return out;
  }

  /** 真正复制。抽出来是为了能在不弹窗的情况下单独测 */
  /**
   * ★★ 5.1.65：改成 **async** —— 原来同步 `readSync`/`writeSync` 逐块拷贝，
   *   40 张图把主线程占满 2~4 秒（vivi 2026-10-05 真机实测，存相册期间界面全冻）。
   *   ⚠️ **两个调用点都要加 `await`**（Index.ets 的 saveImageToAlbum 与批量主循环）。
   *   ⚠️ 与「5.1.34 落盘改异步掉速 1/6」不冲突：那次是**网页上传流控**
   *   （6 并发连接 + 边收边落盘，microtask 饿死流控）；这里是**串行、
   *   用户已点确认、无协议交织**，让出的主线程时间没有状态机要抢。
   */
  static async copyTo(srcPath: string, dstUri: string, name: string): Promise<string> {
    let src: fileIo.File | null = null;
    let dst: fileIo.File | null = null;
    let written: number = 0;
    try {
      src = fileIo.openSync(srcPath, fileIo.OpenMode.READ_ONLY);
      // TRUNC：Picker 可能返回一个已存在的空文件，直接覆盖
      dst = fileIo.openSync(dstUri, fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);

      // ★★ 5.1.65：同步 64KB 拷贝改**异步**（40 张图曾把主线程占满 2~4 秒）。
      //
      // ## 为什么这里异步是安全的（与「5.1.34 掉速 1/6」不冲突）
      //   那次是**网页上传流控**：1.35 每块 256KiB × 6 并发连接、边收边落盘，
      //   microtask 抢占宏任务导致**流控饿死**（要按时 ack / 看流控窗口）。
      //   这里是 `copyTo`：**串行、用户已点确认框、无协议交织** ——
      //   异步让出的主线程时间没有任何状态机要抢，只会让 UI 呼吸。
      //
      // ## SDK 真实签名（别照抄 Node 的写法）
      //   `read(fd, buffer, options?): Promise<ReadOut>` —— **要自己传入 buffer**，
      //   返回 `ReadOut.bytesRead`；它**不是**「返回读到的 buffer」。
      //   `write(fd, buffer, options?): Promise<number>` —— 传要写的 buffer。
      //   ⇒ 出处：@ohos.file.fs 第 2664 行（read）/ 2664 附近（write）。
      const buf: ArrayBuffer = new ArrayBuffer(COPY_CHUNK);
      while (true) {
        // ★ 5.1.65：异步 `read` **直接返回字节数**。
        //   ⚠️ 别照抄 `ets/api/@ohos.fileio.d.ts`（**旧命名空间，已过时**）：
        //   那里写的是 `Promise<ReadOut>` + `ReadOut.bytesRead`。
        //   工程实际 import 的是 `@kit.CoreFileKit` 的 `fileIo`
        //   ⇒ 其源头 `@ohos.file.fs` 第 2664 行是
        //      `read(fd, buffer, options?): Promise<number>`
        //   所以既没有 `ReadOut` 类型，也没有 `bytesRead` 字段。
        const n: number = await fileIo.read(src.fd, buf);
        if (n <= 0) {
          break;
        }
        // 只写实际读到的部分（`fileIo` 没有导出 WriteOptions 类型，
        // 与其硬凑 options 对象，不如裁一段 ArrayBuffer 来得稳）。
        const piece: ArrayBuffer = buf.slice(0, n);
        await fileIo.write(dst.fd, piece);
        written += n;
      }
      Log.i(TAG, `已另存 ${name} -> ${dstUri}（${written} 字节）`);
      return `已保存到所选位置（${ExportService.humanSize(written)}）`;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `另存失败: ${err.code} ${err.message}`);
      return `另存失败（${err.code} ${err.message}）`;
    } finally {
      if (src !== null) {
        try {
          fileIo.closeSync(src);
        } catch (e) {
          // 忽略
        }
      }
      if (dst !== null) {
        try {
          fileIo.closeSync(dst);
        } catch (e) {
          // 忽略
        }
      }
    }
  }

  static humanSize(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    if (bytes < 1024 * 1024 * 1024) {
      return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }

  static pad2(n: number): string {
    return n < 10 ? `0${n}` : `${n}`;
  }
}
