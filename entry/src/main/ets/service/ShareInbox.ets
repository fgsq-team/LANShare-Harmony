/**
 * 系统分享 → LANShare 的「待发送 inbox」
 *
 * ## 为什么需要这个类（而不是在 EntryAbility 里直接发）
 *
 * 1. **跨 Ability 边界**：分享是系统拉起 `EntryAbility`（`ohos.want.action.sendData`），
 *    而选设备 + 发送的 UI 在 `Index` 页。两者之间只能靠进程内单例传递。
 * 2. **两份 Want 两种回调**：`onCreate`（应用没开）与 `onNewWant`（应用已在后台）
 *    都要能接住 ⇒ 必须先入队，再由 UI 侧统一取。
 * 3. **★ 临时授权会过期**：系统分享给的是 `datashare://` / `file://` 授权 URI，
 *    **只在分享方应用还活着的一小段时间内可读**。若直接把 URI 丢给 UI，
 *    等用户在设备列表上纠结几秒，可能就已读不到。
 *    ⇒ 入队时**立刻同步复制进沙箱**，之后一律用沙箱路径发送。
 *
 * ## 落盘目录为什么单独一个
 * 沙箱里已有 `${filesDir}/LANShare`（接收的文件）与 `album_thumbs`（缩略图）。
 * 分享进来的中间物必须能被**独立识别**，否则「用完即删」会误删用户数据
 * （同源教训见 MEMORY.md「程序自己创建的临时文件必须登记 + 用完即删」）。
 * ⇒ 专用子目录 `${filesDir}/share_inbox` 就是那个「独立凭据」。
 */
import { fileIo } from '@kit.CoreFileKit';
import { Want } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { Log } from '../core/Logger';
import { FileStorage, OutgoingFile } from './FileStorage';
import { ExportService } from './ExportService';

const TAG: string = 'ShareInbox';

/** 一次分享解析出来的结果 */
export class ShareBatch {
  /** 已落盘到沙箱的绝对路径，可直接喂 OutgoingFile.fromUri */
  paths: string[] = [];
  /** 展示名，与 paths 同序 */
  names: string[] = [];
  /** 落在 filesDir 下的中转目录（用完整目录清） */
  dir: string = '';
  /**
   * ★ 5.1.84：这段分享是不是「纯文本/链接」。
   * 系统分享链接时给的是 text/plain，**没有文件 uri**（见 urisOf 的过滤规则），
   * 而本工程没有 ShareKit 的 getSharedData ⇒ 拿不到「系统文本分享」语义，
   * 于是按用户口径「链接就以文本形式分享」：把文本落成 .txt 走同一条发送链路。
   * 标了 true 时，UI 标题/说明会写「文本内容将以文字形式发送」。
   */
  isText: boolean = false;

  get count(): number {
    return this.paths.length;
  }

  /** 摘要文案，给 toast / 弹窗标题用 */
  summary(): string {
    if (this.count === 0) {
      return '没有可发送的文件';
    }
    if (this.count === 1) {
      return this.names[0];
    }
    return `${this.names[0]} 等 ${this.count} 个文件`;
  }
}

/** 取 want 里的 uri 列表。★ 多路兜底，不依赖任何单一 key 名 */
function urisOf(want: Want): string[] {
  const out: string[] = [];
  const push = (v: string): void => {
    if (v.length === 0) {
      return;
    }
    // 只要像 uri（datashare:// / file:// / content://）才收，
    // 免得把 title / description 之类的文本参数误当文件。
    if (v.indexOf('://') < 0) {
      return;
    }
    for (let i = 0; i < out.length; i++) {
      if (out[i] === v) {
        return;
      }
    }
    out.push(v);
  };

  // ① 单文件：want.uri（最常见的形态）
  if (want.uri !== undefined && want.uri.length > 0) {
    push(want.uri);
  }
  // ② 多文件：parameters 里各种可能的 key，全部扫一遍
  const params: Record<string, Object> | undefined = want.parameters;
  if (params === undefined) {
    return out;
  }
  const keys: string[] = Object.keys(params);
  for (let i = 0; i < keys.length; i++) {
    const k: string = keys[i];
    // 命中文件名数组的 key 就跳过（那是名字不是 uri）
    if (k.indexOf('file_name') >= 0 || k.indexOf('fileName') >= 0
      || k.indexOf('file_name_array') >= 0) {
      continue;
    }
    const v: Object = params[k];
    if (typeof v === 'string') {
      push(v as string);
    } else if (Array.isArray(v)) {
      const arr: Object[] = v as Object[];
      for (let j: number = 0; j < arr.length; j++) {
        if (typeof arr[j] === 'string') {
          push(arr[j] as string);
        }
      }
    }
  }
  return out;
}

/** 扫描参数里有没有「文件名数组」，用来给 datashare uri 补上真名 */
function fileNamesOf(want: Want): string[] {
  const out: string[] = [];
  const params: Record<string, Object> | undefined = want.parameters;
  if (params === undefined) {
    return out;
  }
  const keys: string[] = Object.keys(params);
  for (let i = 0; i < keys.length; i++) {
    const k: string = keys[i];
    if (k.indexOf('file_name') < 0 && k.indexOf('fileName') < 0) {
      continue;
    }
    const v: Object = params[k];
    if (typeof v === 'string') {
      out.push(v as string);
    } else if (Array.isArray(v)) {
      const arr: Object[] = v as Object[];
      for (let j: number = 0; j < arr.length; j++) {
        if (typeof arr[j] === 'string') {
          out.push(arr[j] as string);
        }
      }
    }
  }
  return out;
}

/**
 * ★ 5.1.84：从 want 里挖出「纯文本 / 链接」。
 *
 * ## 为什么需要（vivi 反馈：「分享链接也不会弹窗」）
 * `urisOf` 只收含 `://` 的串 ⇒ 分享链接时系统给的是
 * `parameters.text` = `"https://…"`（**没有 scheme 前缀的纯字符串**），
 * 于是 uris 为空 ⇒ `accept` 直接 `return false` ⇒ **不弹窗**。
 * 典型来源：浏览器「分享链接」、短信/备忘录选文本、聊天软件转发 URL。
 *
 * ## 找哪些字段（不依赖任何单一 key 名 —— 与 urisOf 同一思路）
 * 常见 key：`text` / `text/plain` / `url` / `uri_string` / `content` / `subject` / `title`。
 * 另有形态：`want.uri` 直接就是一段纯文本（无 `://`）。
 * 全都取不到 ⇒ 返回空串，调用方按「非文本分享」处理。
 */
function textOf(want: Want): string {
  const KEY_HINTS: string[] = [
    'text', 'url', 'uri_string', 'content', 'subject', 'title', 'description', 'extra_text'
  ];
  const params: Record<string, Object> | undefined = want.parameters;
  if (params !== undefined) {
    const keys: string[] = Object.keys(params);
    for (let i: number = 0; i < keys.length; i++) {
      const k: string = keys[i].toLowerCase();
      let hit: boolean = false;
      for (let j: number = 0; j < KEY_HINTS.length; j++) {
        if (k === KEY_HINTS[j] || k.indexOf(KEY_HINTS[j]) >= 0) {
          hit = true;
          break;
        }
      }
      if (!hit) {
        continue;
      }
      const v: Object = params[keys[i]];
      const s: string = typeof v === 'string' ? v as string : '';
      // 太短的（如空串、单个字符）不当作可分享文本
      if (s.trim().length > 0) {
        return s.trim();
      }
    }
  }
  // 形态二：want.uri 本身就是一段纯文本（分享链接的应用常这么塞）
  const u: string = want.uri !== undefined ? want.uri : '';
  if (u.length > 0 && u.indexOf('://') < 0) {
    return u.trim();
  }
  return '';
}

/**
 * 待发送分享批次的进程内单例。
 *
 * 只有一个待发批次（不是队列）：用户从分享面板点进来就是「现在要发这一批」，
 * 再攒多批反而要在 UI 上做批次管理。重复分享时后到覆盖先到，
 * 且覆盖前会清掉上一批的中转目录，不留残留。
 */
export class ShareInbox {
  private static pending: ShareBatch | null = null;
  private static inboxRoot: string = '';
  /** 有新批次时的回调（Index 注册）。用它而不是轮询 */
  private static notify: (() => void) | null = null;
  /**
   * ★ 5.1.82：`inboxRoot` 还没准备好时收到的分享，先存这儿。
   * 冷启动时 `EntryAbility.onCreate` 早于 `LanService.startSharing` ⇒
   * 目录还没建 ⇒ 原来直接放弃（真机症状：「尤其APP没打开过的时候」失败）。
   */
  private static pendingWant: Want | null = null;
  /** 中转目录保留时长：近于此值的一律不清理（正在等用户选设备的那批） */
  private static readonly KEEP_MS: number = 600000;

  /**
   * 记住沙箱根目录。必须在服务初始化时调一次。
   *
   * ★★ 5.1.82：`purgeStale()` 从 LanService.startSharing **移到这里**。
   * 原因：startSharing 每次冷启动都会跑，而那之后可能紧接着就有
   * `accept()` 落盘 ⇒ purge 会**把刚落盘的文件自己删掉**
   * （真机症状：「分享的文件找不到了」）。
   * `init` 的语义就是「一次冷启动的起点」，在这里清残留才正确。
   */
  static init(filesDir: string): void {
    ShareInbox.inboxRoot = `${filesDir}/share_inbox`;
    FileStorage.mkdirs(ShareInbox.inboxRoot);
    ShareInbox.purgeStale();
    // ★ 5.1.82：可能冷启动前就收到了分享（EntryAbility.onCreate 比 startSharing 早）
    //   ⇒ 此时 inboxRoot 当时是空串，accept 把它存进了 pendingWant。
    //   现在目录有了，补处理。
    ShareInbox.drainPending();
  }

  /**
   * 补处理「init 之前收到的分享」。
   * 没有这一步 ⇒ 冷启动分享被静默丢弃（症状之一）。
   */
  private static drainPending(): void {
    if (ShareInbox.pendingWant === null) {
      return;
    }
    const w: Want = ShareInbox.pendingWant;
    ShareInbox.pendingWant = null;
    Log.i(TAG, '补处理 init 之前收到的分享');
    ShareInbox.accept(w);
  }

  /** UI 注册回调。返回的函数用于注销 */
  static setListener(fn: (() => void) | null): void {
    ShareInbox.notify = fn;
  }

  /** 当前待发批次；null = 没有 */
  static peek(): ShareBatch | null {
    return ShareInbox.pending;
  }

  /**
   * 取出并清空（= 认领这批文件的所有权）。
   * ⚠️ 必须「取走即清」：否则取消一次发送后，下次进页面又弹出同一批。
   */
  static claim(): ShareBatch | null {
    const b: ShareBatch | null = ShareInbox.pending;
    ShareInbox.pending = null;
    return b;
  }

  /**
   * 退回一批（UI 侧条件不满足时用，比如服务没就绪 / 没发现设备）。
   * 必须在同一次会话内退回 —— 下一批分享进来会直接覆盖它。
   */
  static restore(batch: ShareBatch): void {
    ShareInbox.pending = batch;
    Log.i(TAG, `退回分享批次: ${batch.summary()}`);
  }

  /** 丢弃当前批次并删掉它的中转目录（用户取消发送时走这条） */
  static discard(): void {
    const b: ShareBatch | null = ShareInbox.pending;
    ShareInbox.pending = null;
    if (b !== null) {
      ShareInbox.cleanDir(b.dir);
    }
  }

  /**
   * 收到分享 want：解析 uri → 落盘到中转目录 → 入队 → 通知 UI。
   *
   * 落盘是**同步**的：必须在授权失效前完成，而且这批文件是用户刚选中的，
   * 数量通常个位数，同步拷贝不会明显卡（真要卡，交给下面的 toast 提示）。
   */
  static accept(want: Want): boolean {
    const uris: string[] = urisOf(want);
    // ★ 5.1.84：没有文件 uri **不等于** 放弃 ——
    //   分享链接/选中文本时系统给的是纯文本（vivi：「分享链接也不会弹窗」）。
    //   按用户口径「链接就以文本形式分享」⇒ 落成 .txt 走同一条链路。
    const text: string = uris.length === 0 ? textOf(want) : '';
    if (uris.length === 0 && text.length === 0) {
      Log.w(TAG, '分享 want 里既没有文件 uri 也没有可分享的文本');
      return false;
    }
    if (ShareInbox.inboxRoot.length === 0) {
      // ★ 5.1.82：原来这里直接 `return false` 放弃 —— 冷启动分享必丢
      //   （onCreate 早于 startSharing，目录还没建）。
      //   改为**存下 want**，等 `init(filesDir)` 里 `drainPending()` 补处理。
      ShareInbox.pendingWant = want;
      Log.w(TAG, 'share_inbox 尚未初始化，先暂存本次分享待补处理');
      return false;
    }
    // 上一批还没发就又来一批：清掉上一批的中转目录，不留残留
    ShareInbox.discard();

    const hinted: string[] = fileNamesOf(want);
    const dir: string = `${ShareInbox.inboxRoot}/${Date.now()}`;
    FileStorage.mkdirs(dir);

    const batch: ShareBatch = new ShareBatch();
    batch.dir = dir;
    let skipped: number = 0;

    if (uris.length === 0) {
      // ---- 纯文本 / 链接：落成一个 .txt ----
      // 文件名带时间戳，避免与同目录下别的中转文件重名；
      // 编码 UTF-8 —— 链接与中文混排是常态。
      const name: string = `分享文本_${Date.now()}.txt`;
      const dst: string = `${dir}/${name}`;
      try {
        const out: fileIo.File = fileIo.openSync(dst,
          fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
        fileIo.writeSync(out.fd, text);
        fileIo.closeSync(out);
        batch.paths.push(dst);
        batch.names.push(name);
        batch.isText = true;
        Log.i(TAG, `分享文本已落盘: ${name} (${text.length} 字)`);
      } catch (e) {
        const err: BusinessError = e as BusinessError;
        Log.w(TAG, `分享文本落盘失败: ${err.code} ${err.message}`);
      }
      if (batch.count === 0) {
        ShareInbox.cleanDir(dir);
        return false;
      }
      ShareInbox.pending = batch;
      Log.i(TAG, `分享文本批次就绪: ${name}`);
      if (ShareInbox.notify !== null) {
        ShareInbox.notify();
      }
      return true;
    }

    for (let i: number = 0; i < uris.length; i++) {
      const name: string = i < hinted.length && hinted[i].length > 0
        ? FileStorage.sanitize(hinted[i])
        : OutgoingFile.displayName(uris[i]);
      const dst: string = `${dir}/${name}`;
      try {
        // openSync 直接吃 datashare://（同工程 stageForWeb 已验证）
        const src: fileIo.File = fileIo.openSync(uris[i], fileIo.OpenMode.READ_ONLY);
        const out: fileIo.File = fileIo.openSync(dst,
          fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
        const buf: ArrayBuffer = new ArrayBuffer(65536);
        let total: number = 0;
        while (true) {
          // ★ 同步循环：这里刻意不用 await —— 必须在**这个回调返回前**拷完，
          //   出了这个函数临时授权就可能失效。COPY_CHUNK 与 ExportService 同值。
          const n: number = fileIo.readSync(src.fd, buf);
          if (n <= 0) {
            break;
          }
          fileIo.writeSync(out.fd, buf.slice(0, n));
          total += n;
        }
        fileIo.closeSync(src);
        fileIo.closeSync(out);
        if (total <= 0) {
          skipped++;
          fileIo.unlinkSync(dst);
          Log.w(TAG, `分享文件为空已跳过: ${name}`);
          continue;
        }
        batch.paths.push(dst);
        batch.names.push(name);
        Log.i(TAG, `分享已落盘: ${name} (${ExportService.humanSize(total)})`);
      } catch (e) {
        skipped++;
        const err: BusinessError = e as BusinessError;
        Log.w(TAG, `分享文件读取失败已跳过: ${name} ${err.code} ${err.message}`);
      }
    }

    if (batch.count === 0) {
      ShareInbox.cleanDir(dir);
      Log.w(TAG, `分享的 ${uris.length} 个文件全部不可读`);
      return false;
    }
    if (skipped > 0) {
      Log.w(TAG, `分享中 ${skipped} 个文件不可读，已跳过`);
    }
    ShareInbox.pending = batch;
    Log.i(TAG, `分享批次就绪：${batch.summary()}`);
    if (ShareInbox.notify !== null) {
      ShareInbox.notify();
    }
    return true;
  }

  /** 把沙箱路径转成发送链路要的 OutgoingFile */
  static toOutgoing(batch: ShareBatch): OutgoingFile[] {
    const out: OutgoingFile[] = [];
    for (let i = 0; i < batch.paths.length; i++) {
      const f: OutgoingFile = OutgoingFile.fromUri(batch.paths[i]);
      if (f.sizeKnown) {
        out.push(f);
      } else {
        Log.w(TAG, `待发文件读不到已剔除: ${batch.names[i]}`);
      }
    }
    return out;
  }

  /**
   * 发完之后清理中转目录。
   * ⚠️ 必须在**发送真正完成之后**才调 —— 提前删会让 FileSource 读不到字节。
   */
  static cleanup(batch: ShareBatch | null): void {
    if (batch === null) {
      return;
    }
    ShareInbox.cleanDir(batch.dir);
    Log.i(TAG, `已清理分享中转目录: ${batch.dir}`);
  }

  /** 删整个目录（跳过目录本身，只删它的内容） */
  private static cleanDir(dir: string): void {
    if (dir.length === 0) {
      return;
    }
    try {
      const names: string[] = fileIo.listFileSync(dir);
      for (let i: number = 0; i < names.length; i++) {
        const p: string = `${dir}/${names[i]}`;
        try {
          if (fileIo.statSync(p).isDirectory()) {
            continue;
          }
          fileIo.unlinkSync(p);
        } catch (e) {
          // 单个文件删不掉不影响其余，继续
        }
      }
    } catch (e) {
      // 目录本来就不存在
    }
  }

  /**
   * 启动时清掉**上一次残留**的中转目录。
   * 进程被杀 / 用户强退都会留下半批文件，下次进来必须先扫干净。
   */
  static purgeStale(): void {
    if (ShareInbox.inboxRoot.length === 0) {
      return;
    }
    try {
      const dirs: string[] = fileIo.listFileSync(ShareInbox.inboxRoot);
      const now: number = Date.now();
      let n: number = 0;
      let keep: number = 0;
      for (let i: number = 0; i < dirs.length; i++) {
        // ★★ 5.1.82：**只清「旧于 10 分钟」的中转目录**。
        //   原来是无条件清空全部 ⇒ 会把「本轮刚落盘、正在等用户选设备」的
        //   那批文件删掉（真机症状：「分享的文件找不到了」）。
        //   目录名是 accept 时的 `Date.now()`，直接当时间戳解析。
        const ts: number = Number(dirs[i]);
        if (!isNaN(ts) && now - ts < ShareInbox.KEEP_MS) {
          // 可能是本次会话刚落的（或者是 pending 批次）⇒ 保留
          keep++;
          continue;
        }
        ShareInbox.cleanDir(`${ShareInbox.inboxRoot}/${dirs[i]}`);
        n++;
      }
      if (n > 0) {
        Log.i(TAG, `已清理过期分享中转目录 ${n} 个（保留 ${keep} 个近期）`);
      } else if (keep > 0) {
        Log.i(TAG, `保留近期分享中转目录 ${keep} 个`);
      }
    } catch (e) {
      // 还没有 share_inbox 目录，正常
    }
  }
}
// 5.1.84 patched-by-fix_5184_share_ui_text.py
