/**
 * 流式 multipart/form-data 解析器 —— 网页端上传的落地实现。
 *
 * ## 为什么必须流式
 * 网页端上传走的是 `new FormData(); append("file", f); xhr.send(formData)`
 * （见 rawfile/web/js/lanshare.min.js 的 startSendFile → uploadFile），
 * 也就是标准的 `Content-Type: multipart/form-data`。
 *
 * 原实现把整段 body 用 `readExactly(bodyLen)` **一次性读进内存**，会同时踩两个坑：
 *   1. 内存：用户拖一个 1 GB 文件就 OOM；
 *   2. 速度：配合旧的 TcpChannel O(n²) 缓冲策略，真机 32 MiB 实测要 51.5 s
 *      （0.62 MiB/s，见 tests/live-probe/upload_probe.mjs）。
 *
 * 本实现「边收边解析边落盘」：内存占用与文件大小无关，只跟单个网络分片有关。
 *
 * ## 格式与状态机
 * ```
 * --<boundary>\r\n
 * Content-Disposition: form-data; name="file"; filename="a.bin"\r\n
 * Content-Type: application/octet-stream\r\n
 * \r\n
 * <文件二进制内容>\r\n
 * --<boundary>\r\n            ← 下一个 part；若是 --<boundary>-- 则整体结束
 * ```
 * 四个状态：PREAMBLE（丢弃首个分隔符之前）→ HEADERS（读 part 头）
 * → BODY（写文件）→ EPILOGUE（收尾）。
 *
 * ## 关键实现细节
 * - **BODY 状态必须保留尾巴**：`\r\n--<boundary>` 可能正好跨两个网络分片，
 *   所以每次消费都要留 `marker.length + 1` 字节不写盘，等下一片到齐再判断。
 *   少了这一步，文件里就会夹杂被撕裂的分隔符。
 * - **文件名按 UTF-8 解码**：multipart 是二进制安全的，浏览器直接发原始 UTF-8
 *   字节（中文名不会做百分号编码），因此不能按 latin1 处理。
 */

const util = {
  TextEncoder: class {
    constructor(_e) {}
    encodeInto(s) { return new TextEncoder().encode(s); }
  },
  TextDecoder: class {
    constructor(_e) {}
    decodeToString(u) { return new TextDecoder('utf-8').decode(u); }
  }
};

import { FileSink, FileStorage } from './FileStorage.ts';
import { Log } from '../core/Logger.ts';

const TAG: string = 'MultipartStream';

/** 一个已落盘的 part */
export class MultipartFile {
  name: string = '';
  path: string = '';
  size: number = 0;
}

/** 解析失败的原因（给用户看的原文，不要吞掉） */
export class MultipartError {
  ok: boolean = true;
  message: string = '';
}

export class MultipartStream {
  private static readonly S_PREAMBLE: number = 0;
  private static readonly S_HEADERS: number = 1;
  private static readonly S_BODY: number = 2;
  private static readonly S_EPILOGUE: number = 3;

  /** 文件内容里用于界定结束的分隔标记：`\r\n--<boundary>` */
  private marker: Uint8Array;
  /** 首个分隔符（开头没有 CRLF）：`--<boundary>` */
  private opener: Uint8Array;
  private crlfcrlf: Uint8Array = new Uint8Array([13, 10, 13, 10]);

  private hold: Uint8Array = new Uint8Array(0);
  private state: number = MultipartStream.S_PREAMBLE;

  private sink: FileSink | null = null;
  private curName: string = '';
  private curSize: number = 0;

  private dirOf: (fileName: string) => string;
  private files: MultipartFile[] = [];
  private err: string = '';
  /** 已喂入的总字节（用于日志与「是否读满 Content-Length」的校验） */
  private fed: number = 0;

  /**
   * @param boundary 从 `Content-Type: multipart/form-data; boundary=xxx` 里取出的值
   * @param dirOf    按文件名给出目标目录（内部会 mkdir + 去重命名）。
   *                 用回调而不是直接收一个目录字符串 —— modern 端要按文件类型
   *                 分子目录（软件/图片/...），而分类必须等到解析出 filename 才能确定。
   */
  constructor(boundary: string, dirOf: (fileName: string) => string) {
    this.dirOf = dirOf;
    this.opener = MultipartStream.bytes(`--${boundary}`);
    this.marker = MultipartStream.bytes(`\r\n--${boundary}`);
  }

  private static bytes(s: string): Uint8Array {
    return new util.TextEncoder().encodeInto(s);
  }

  /** 从 `Content-Type` 头里提取 boundary。取不到返回空串 */
  static boundaryOf(contentType: string): string {
    const idx: number = contentType.toLowerCase().indexOf('boundary=');
    if (idx < 0) {
      return '';
    }
    let v: string = contentType.substring(idx + 'boundary='.length).trim();
    const semi: number = v.indexOf(';');
    if (semi >= 0) {
      v = v.substring(0, semi).trim();
    }
    if (v.startsWith('"') && v.endsWith('"') && v.length >= 2) {
      v = v.substring(1, v.length - 1);
    }
    // boundary 长度官方上限 70 字符
    return v.length > 0 && v.length <= 80 ? v : '';
  }

  /** 喂一片数据。可多次调用，内部状态机自行推进 */
  feed(chunk: Uint8Array): void {
    if (chunk.length === 0) {
      return;
    }
    this.fed += chunk.length;
    this.hold = MultipartStream.concat(this.hold, chunk);
    this.pump();
  }

  /** 数据喂完后调用：收尾并返回结果 */
  finish(): MultipartFile[] {
    // 收尾时把剩下的 hold 交给状态机做最后一次判断
    this.pump();
    if (this.sink !== null) {
      // BODY 中途结束 = 对端没把 boundary 发全，属于坏包
      this.sink.close();
      this.sink = null;
      if (this.err.length === 0) {
        this.err = '数据在文件内容中间就结束了（multipart 不完整）';
      }
    }
    return this.files;
  }

  get error(): string {
    return this.err;
  }

  get ok(): boolean {
    return this.err.length === 0;
  }

  get bytesIn(): number {
    return this.fed;
  }

  /**
   * 当前正在接收的分段文件名（用于上传进度显示）。
   *
   * part 头还没解析完时是空串 —— 调用方要能接受空串，
   * 别把「还没拿到名字」显示成「未知文件」之类吓人的字样。
   */
  get currentName(): string {
    return this.curName;
  }

  /** 遇到错误立刻停手：关掉半截文件并记录原因 */
  private fail(msg: string): void {
    if (this.err.length === 0) {
      this.err = msg;
    }
    if (this.sink !== null) {
      this.sink.close();
      this.sink = null;
    }
    this.state = MultipartStream.S_EPILOGUE;
  }

  /** 状态机主循环。只要还有推进空间就继续 */
  private pump(): void {
    let progress: boolean = true;
    while (progress) {
      progress = false;
      if (this.state === MultipartStream.S_PREAMBLE) {
        const i: number = MultipartStream.indexOfSeq(this.hold, this.opener, 0);
        if (i >= 0) {
          this.hold = this.hold.slice(i + this.opener.length);
          this.state = MultipartStream.S_HEADERS;
          progress = true;
        } else if (this.hold.length > this.opener.length) {
          // 分隔符还没到齐，只留可能构成前缀的尾巴
          this.hold = this.hold.slice(this.hold.length - this.opener.length);
        }
      } else if (this.state === MultipartStream.S_HEADERS) {
        const end: number = MultipartStream.indexOfSeq(this.hold, this.crlfcrlf, 0);
        if (end >= 0) {
          const headText: string = new util.TextDecoder().decodeToString(this.hold.slice(0, end));
          this.hold = this.hold.slice(end + this.crlfcrlf.length);
          this.curName = MultipartStream.parseFilename(headText);
          const target: string = FileStorage.uniquePathIn(this.dirOf(this.curName), this.curName);
          const s: FileSink | null = FileSink.create(target);
          if (s === null) {
            this.fail(`无法创建文件: ${target}`);
            return;
          }
          this.sink = s;
          this.curName = target.substring(target.lastIndexOf('/') + 1);
          this.curSize = 0;
          this.state = MultipartStream.S_BODY;
          progress = true;
        } else if (this.hold.length > 64 * 1024) {
          // part 头不可能这么大，视作坏包，避免无限堆积
          this.fail('multipart 分段头异常超长');
          return;
        }
      } else if (this.state === MultipartStream.S_BODY) {
        const i: number = MultipartStream.indexOfSeq(this.hold, this.marker, 0);
        if (i >= 0) {
          // marker 之前都是文件内容
          this.write(this.hold.slice(0, i));
          const after: number = i + this.marker.length;
          if (this.hold.length < after + 2) {
            // 还看不出是 `--`（结束）还是 `\r\n`（下一个 part），等下一片
            this.hold = this.hold.slice(i);
            return;
          }
          const c0: number = this.hold[after];
          const c1: number = this.hold[after + 1];
          this.closePart();
          if (c0 === 45 && c1 === 45) {
            this.state = MultipartStream.S_EPILOGUE;
          } else {
            // 跳过后面的 CRLF（若有），回到 HEADERS 读下一个 part
            let skip: number = after;
            if (c0 === 13 && c1 === 10) {
              skip = after + 2;
            }
            this.hold = this.hold.slice(skip);
            this.state = MultipartStream.S_HEADERS;
          }
          progress = true;
        } else {
          // 还没出现 boundary：保留可能构成 marker 前缀的尾巴，其余全部落盘
          const keep: number = this.marker.length + 1;
          if (this.hold.length > keep) {
            const n: number = this.hold.length - keep;
            this.write(this.hold.slice(0, n));
            this.hold = this.hold.slice(n);
            progress = true;
          }
        }
      } else {
        // EPILOGUE：后续数据无意义，丢弃
        this.hold = new Uint8Array(0);
        return;
      }
    }
  }

  private write(data: Uint8Array): void {
    if (data.length === 0 || this.sink === null) {
      return;
    }
    if (this.sink.append(data)) {
      this.curSize += data.length;
    } else {
      this.fail('写文件失败（存储空间不足或路径不可写）');
    }
  }

  private closePart(): void {
    if (this.sink === null) {
      return;
    }
    this.sink.close();
    const f: MultipartFile = new MultipartFile();
    f.name = this.curName;
    f.path = this.sink.path;
    f.size = this.curSize;
    this.files.push(f);
    Log.i(TAG, `收下一个分段: ${f.name} (${f.size} B)`);
    this.sink = null;
  }

  /**
   * 从 part 头里取文件名。
   * 优先 RFC 5987 的 `filename*=UTF-8''xxx`，其次普通 `filename="xxx"`。
   */
  private static parseFilename(headText: string): string {
    const star: string = MultipartStream.attrValue(headText, 'filename*');
    if (star.length > 0) {
      // 形如 UTF-8''%E4%B8%AD.txt
      const q: number = star.indexOf("''");
      const raw: string = q >= 0 ? star.substring(q + 2) : star;
      try {
        return FileStorage.sanitize(decodeURIComponent(raw));
      } catch (e) {
        // 解码失败就按原文继续
      }
    }
    const plain: string = MultipartStream.attrValue(headText, 'filename');
    if (plain.length > 0) {
      return FileStorage.sanitize(plain);
    }
    return FileStorage.sanitize(`upload_${Date.now()}`);
  }

  /** 取 `key=value` 中的 value，value 可带双引号 */
  private static attrValue(text: string, key: string): string {
    const lower: string = text.toLowerCase();
    let from: number = 0;
    while (true) {
      const i: number = lower.indexOf(key, from);
      if (i < 0) {
        return '';
      }
      // 必须紧邻 '='，否则可能是别的键名的一部分
      let j: number = i + key.length;
      while (j < text.length && text.charAt(j) === ' ') {
        j++;
      }
      if (text.charAt(j) !== '=') {
        from = i + key.length;
        continue;
      }
      j++;
      while (j < text.length && text.charAt(j) === ' ') {
        j++;
      }
      if (text.charAt(j) === '"') {
        const close: number = text.indexOf('"', j + 1);
        return close > j ? text.substring(j + 1, close) : text.substring(j + 1);
      }
      const semi: number = text.indexOf(';', j);
      const stop: number = semi >= 0 ? semi : text.length;
      return text.substring(j, stop).trim();
    }
  }

  /** 子串搜索。用首字节快速跳过，避免对二进制逐字节比对 */
  private static indexOfSeq(hay: Uint8Array, needle: Uint8Array, from: number): number {
    const n: number = needle.length;
    if (n === 0) {
      return from;
    }
    const limit: number = hay.length - n;
    const first: number = needle[0];
    for (let i = from; i <= limit; i++) {
      if (hay[i] !== first) {
        continue;
      }
      let j: number = 1;
      while (j < n && hay[i + j] === needle[j]) {
        j++;
      }
      if (j === n) {
        return i;
      }
    }
    return -1;
  }

  private static concat(a: Uint8Array, b: Uint8Array): Uint8Array {
    if (a.length === 0) {
      return b;
    }
    const out: Uint8Array = new Uint8Array(a.length + b.length);
    out.set(a, 0);
    out.set(b, a.length);
    return out;
  }
}
