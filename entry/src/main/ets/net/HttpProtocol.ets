/**
 * HTTP/1.1 最小实现 —— 替代 app/libs/HttpServer-1.9.57.jar 中的
 * com.fgsqw.Request / Response / ContentTypes / HttpConstant
 *
 * 原 jar 是 NanoHTTPD 的私有 fork（含 com.fgsqw.websocket），无法在鸿蒙上运行。
 * 但 HTTP/1.1 是公开标准，这一层属于"确定性工程"：按 RFC 7230-7235 实现即可，
 * 不需要逆向原 jar 的内部结构。
 *
 * ## 与原始实现的兼容点
 * - 服务端监听在**文件传输 TCP 端口**（默认 5856）上，而不是独立 HTTP 端口。
 *   见 LanTcpServer：靠前 4 字节是 "GET "/"POST" 还是魔数来分流。
 * - 静态资源根目录 = rawfile/web（原 assets/web，已 100% 复用）
 * - 路由表与原 LHttpServer 完全一致，见 HttpRouter
 */
import { util } from '@kit.ArkTS';
// ★ 5.1.48：MimeTypes.of 要用 FileKinds.stripCopySuffix 剥掉 ` (n)` 复制后缀
import { FileKinds } from '../core/FileTypes';

/** 单次请求头的最大长度，防御畸形请求打爆内存 */
const MAX_HEADER_BYTES: number = 16 * 1024;

export class HttpRequest {
  method: string = 'GET';
  /** 不含 query 的路径，例如 /files */
  path: string = '/';
  /** 原始请求目标，例如 /files?dir=/sdcard */
  target: string = '/';
  query: Map<string, string> = new Map<string, string>();
  version: string = 'HTTP/1.1';
  headers: Map<string, string> = new Map<string, string>();
  /** 请求头部分的原始字节（分流时可回填给解析器） */
  headerBytes: Uint8Array = new Uint8Array(0);
  body: Uint8Array = new Uint8Array(0);

  /** 取请求头，键名大小写不敏感 */
  header(name: string): string {
    const v: string | undefined = this.headers.get(name.toLowerCase());
    return v === undefined ? '' : v;
  }

  queryParam(name: string): string {
    const v: string | undefined = this.query.get(name);
    return v === undefined ? '' : v;
  }

  /** 客户端地址，由 TCP 连接层填入 */
  remoteIp: string = '';
  remotePort: number = 0;
}

/** 解析结果：需要更多数据 / 解析完成 / 报文非法
 *
 * 用 static readonly 常量而不是 enum：ArkTS 的 enum 是运行期构造，
 * 而 TS 类型擦除环境不支持，保持代码在两种执行方式下行为一致。
 */
export class ParseState {
  static readonly NEED_MORE: number = 0;
  static readonly DONE: number = 1;
  static readonly INVALID: number = 2;
}

export class HttpProtocol {
  /**
   * 从缓冲区解析请求头。
   *
   * 分两步：先在 buf[0..len) 里找 `\r\n\r\n`，找不到返回 NEED_MORE，
   * 调用方继续从 socket 读；找到后再解析请求行与头部字段。
   *
   * @param buf 已读入的字节
   * @param len buf 中有效字节数
   * @param out 解析成功时填充
   * @returns 解析状态；DONE 时 out.headerEnd 给出头部结束偏移
   */
  static parseHeader(buf: Uint8Array, len: number, out: HttpRequest): number {
    if (len > MAX_HEADER_BYTES) {
      return ParseState.INVALID;
    }
    const headerEnd: number = HttpProtocol.findHeaderEnd(buf, len);
    if (headerEnd < 0) {
      return ParseState.NEED_MORE;
    }

    const text: string = new util.TextDecoder().decodeToString(buf.subarray(0, headerEnd - 4));
    const lines: string[] = text.split('\r\n');
    if (lines.length === 0 || lines[0].length === 0) {
      return ParseState.INVALID;
    }

    // ---- 请求行：  METHOD SP request-target SP HTTP-version ----
    const parts: string[] = lines[0].split(' ');
    if (parts.length < 3) {
      return ParseState.INVALID;
    }
    out.method = parts[0].toUpperCase();
    out.target = parts[1];
    out.version = parts[2];

    const q: number = out.target.indexOf('?');
    if (q >= 0) {
      out.path = HttpProtocol.urlDecodePath(out.target.substring(0, q));
      HttpProtocol.parseQuery(out.target.substring(q + 1), out.query);
    } else {
      out.path = HttpProtocol.urlDecodePath(out.target);
    }

    // ---- 头部字段：  name: value ----
    for (let i = 1; i < lines.length; i++) {
      const line: string = lines[i];
      if (line.length === 0) {
        continue;
      }
      const colon: number = line.indexOf(':');
      if (colon <= 0) {
        continue;
      }
      const name: string = line.substring(0, colon).trim().toLowerCase();
      const value: string = line.substring(colon + 1).trim();
      // 同名头按 RFC 应逗号合并（Cookie 除外，但本项目用不到）
      const prev: string | undefined = out.headers.get(name);
      out.headers.set(name, prev === undefined ? value : `${prev}, ${value}`);
    }

    out.headerBytes = buf.slice(0, headerEnd);
    return ParseState.DONE;
  }

  /** 头部结束偏移（含结尾的 \r\n\r\n）；未找到返回 -1 */
  static findHeaderEnd(buf: Uint8Array, len: number): number {
    for (let i = 0; i + 3 < len; i++) {
      if (buf[i] === 13 && buf[i + 1] === 10 && buf[i + 2] === 13 && buf[i + 3] === 10) {
        return i + 4;
      }
    }
    return -1;
  }

  /** URL 解码 + 归一化。拒绝上跳目录，防止路径穿越 */
  static urlDecodePath(raw: string): string {
    let s: string = raw;
    try {
      s = decodeURIComponent(raw);
    } catch (e) {
      s = raw;
    }
    // 归一化反斜杠，杜绝 Windows 风格路径绕过
    s = s.replace(/\\/g, '/');
    // 折叠 // 与 /./ ，并消解 /../
    const segs: string[] = s.split('/');
    const stack: string[] = [];
    for (let i = 0; i < segs.length; i++) {
      const seg: string = segs[i];
      if (seg === '' || seg === '.') {
        continue;
      }
      if (seg === '..') {
        stack.pop();
        continue;
      }
      stack.push(seg);
    }
    return `/${stack.join('/')}`;
  }

  static parseQuery(raw: string, into: Map<string, string>): void {
    if (raw.length === 0) {
      return;
    }
    const pairs: string[] = raw.split('&');
    for (let i = 0; i < pairs.length; i++) {
      const pair: string = pairs[i];
      if (pair.length === 0) {
        continue;
      }
      const eq: number = pair.indexOf('=');
      let k: string = eq < 0 ? pair : pair.substring(0, eq);
      let v: string = eq < 0 ? '' : pair.substring(eq + 1);
      try {
        k = decodeURIComponent(k.replace(/\+/g, ' '));
        v = decodeURIComponent(v.replace(/\+/g, ' '));
      } catch (e) {
        // 保留原值
      }
      into.set(k, v);
    }
  }

  /** 请求体长度：Content-Length 或分块传输时的 -1 */
  static bodyLength(req: HttpRequest): number {
    const te: string = req.header('transfer-encoding');
    if (te.toLowerCase().includes('chunked')) {
      return -1;
    }
    const cl: string = req.header('content-length');
    if (cl.length === 0) {
      return 0;
    }
    const n: number = Number.parseInt(cl, 10);
    return Number.isNaN(n) || n < 0 ? 0 : n;
  }

  /**
   * 解析 Range 头，用于视频拖动和断点续传。
   * 只支持单区间 `bytes=start-end`（本项目够用）。
   *
   * @returns [start, end] 闭区间；无效或不支持时返回 null
   */
  static parseRange(headerValue: string, totalSize: number): number[] | null {
    if (headerValue.length === 0 || !headerValue.startsWith('bytes=')) {
      return null;
    }
    const spec: string = headerValue.substring(6).trim();
    if (spec.includes(',')) {
      // 多区间过于少见，按不支持处理（返回 200 全量）
      return null;
    }
    const dash: number = spec.indexOf('-');
    if (dash < 0) {
      return null;
    }
    const startStr: string = spec.substring(0, dash).trim();
    const endStr: string = spec.substring(dash + 1).trim();

    let start: number;
    let end: number;
    if (startStr.length === 0) {
      // bytes=-N  取最后 N 字节
      const suffix: number = Number.parseInt(endStr, 10);
      if (Number.isNaN(suffix) || suffix <= 0) {
        return null;
      }
      start = Math.max(0, totalSize - suffix);
      end = totalSize - 1;
    } else {
      start = Number.parseInt(startStr, 10);
      end = endStr.length === 0 ? totalSize - 1 : Number.parseInt(endStr, 10);
      if (Number.isNaN(start) || Number.isNaN(end)) {
        return null;
      }
    }
    if (start > end || start >= totalSize) {
      return null;
    }
    if (end >= totalSize) {
      end = totalSize - 1;
    }
    return [start, end];
  }
}

/** MIME 类型表 —— 替代 jar 里的 com.fgsqw.ContentTypes */
export class ContentTypes {
  private static readonly TABLE: Map<string, string> = ContentTypes.build();

  private static build(): Map<string, string> {
    const m: Map<string, string> = new Map<string, string>();
    const rows: string[][] = [
      ['html', 'text/html; charset=utf-8'],
      ['htm', 'text/html; charset=utf-8'],
      ['js', 'application/javascript; charset=utf-8'],
      ['mjs', 'application/javascript; charset=utf-8'],
      ['css', 'text/css; charset=utf-8'],
      ['json', 'application/json; charset=utf-8'],
      ['txt', 'text/plain; charset=utf-8'],
      ['xml', 'application/xml; charset=utf-8'],
      ['md', 'text/markdown; charset=utf-8'],
      ['csv', 'text/csv; charset=utf-8'],
      ['png', 'image/png'],
      ['jpg', 'image/jpeg'],
      ['jpeg', 'image/jpeg'],
      ['gif', 'image/gif'],
      ['webp', 'image/webp'],
      ['bmp', 'image/bmp'],
      ['svg', 'image/svg+xml'],
      ['ico', 'image/x-icon'],
      ['heic', 'image/heic'],
      ['mp3', 'audio/mpeg'],
      ['wav', 'audio/wav'],
      ['ogg', 'audio/ogg'],
      ['m4a', 'audio/mp4'],
      ['flac', 'audio/flac'],
      ['mp4', 'video/mp4'],
      ['webm', 'video/webm'],
      ['mkv', 'video/x-matroska'],
      ['mov', 'video/quicktime'],
      ['avi', 'video/x-msvideo'],
      ['3gp', 'video/3gpp'],
      ['pdf', 'application/pdf'],
      ['zip', 'application/zip'],
      ['rar', 'application/vnd.rar'],
      ['7z', 'application/x-7z-compressed'],
      ['gz', 'application/gzip'],
      ['tar', 'application/x-tar'],
      ['apk', 'application/vnd.android.package-archive'],
      ['hap', 'application/vnd.harmonyos.package-archive'],
      ['woff', 'font/woff'],
      ['woff2', 'font/woff2'],
      ['ttf', 'font/ttf']
    ];
    for (let i = 0; i < rows.length; i++) {
      m.set(rows[i][0], rows[i][1]);
    }
    return m;
  }

  /** 按扩展名推断 MIME；未命中返回 application/octet-stream */
  static of(fileName: string): string {
    // ★ 5.1.48：先剥 ` (n)`，否则 `xxx.jpg (1)` 拿不到 image/jpeg。
    const bare: string = FileKinds.stripCopySuffix(fileName);
    const dot: number = bare.lastIndexOf('.');
    if (dot < 0 || dot === bare.length - 1) {
      return 'application/octet-stream';
    }
    const ext: string = bare.substring(dot + 1).toLowerCase();
    const v: string | undefined = ContentTypes.TABLE.get(ext);
    return v === undefined ? 'application/octet-stream' : v;
  }

  /** 是否属于"可直接在浏览器里预览"的类型 */
  static isInline(fileName: string): boolean {
    const t: string = ContentTypes.of(fileName);
    return t.startsWith('image/') || t.startsWith('video/') ||
      t.startsWith('audio/') || t.startsWith('text/') ||
      t === 'application/pdf';
  }
}

/** HTTP 状态码 -> 标准原因短语 */
export function reasonPhrase(code: number): string {
  switch (code) {
    case 200: return 'OK';
    case 204: return 'No Content';
    case 206: return 'Partial Content';
    case 301: return 'Moved Permanently';
    case 302: return 'Found';
    case 304: return 'Not Modified';
    case 400: return 'Bad Request';
    case 401: return 'Unauthorized';
    case 403: return 'Forbidden';
    case 404: return 'Not Found';
    case 405: return 'Method Not Allowed';
    case 408: return 'Request Timeout';
    case 413: return 'Payload Too Large';
    case 416: return 'Range Not Satisfiable';
    case 500: return 'Internal Server Error';
    case 501: return 'Not Implemented';
    case 503: return 'Service Unavailable';
    default: return 'Unknown';
  }
}

/**
 * 响应构造器。
 * 支持两种形态：一次性 body（bytes/text/json）与流式 body（用于大文件）。
 */
export class HttpResponse {
  status: number = 200;
  headers: Map<string, string> = new Map<string, string>();
  body: Uint8Array = new Uint8Array(0);
  /** 是否保持连接。HTTP/1.1 默认 keep-alive */
  keepAlive: boolean = true;

  /** 流式 body：返回文件的一个区间。由 HttpRouter 在下载大文件时设置 */
  streamFile: FileStreamSpec | null = null;

  static of(status: number): HttpResponse {
    const r: HttpResponse = new HttpResponse();
    r.status = status;
    return r;
  }

  static text(status: number, body: string, contentType: string = 'text/plain; charset=utf-8'): HttpResponse {
    const r: HttpResponse = HttpResponse.of(status);
    r.body = new util.TextEncoder().encodeInto(body);
    r.set('Content-Type', contentType);
    return r;
  }

  static json(status: number, body: string): HttpResponse {
    return HttpResponse.text(status, body, 'application/json; charset=utf-8');
  }

  static notFound(msg: string = 'Not Found'): HttpResponse {
    return HttpResponse.text(404, msg);
  }

  static forbidden(msg: string = 'Forbidden'): HttpResponse {
    return HttpResponse.text(403, msg);
  }

  static serverError(msg: string = 'Internal Server Error'): HttpResponse {
    return HttpResponse.text(500, msg);
  }

  set(name: string, value: string): HttpResponse {
    this.headers.set(name, value);
    return this;
  }

  /** 序列化响应头（不含 body） */
  encodeHead(): Uint8Array {
    const sb: string[] = [];
    sb.push(`HTTP/1.1 ${this.status} ${reasonPhrase(this.status)}\r\n`);

    // 统一由这里补齐通用头，避免各处重复
    if (!this.headers.has('Content-Type') && this.body.length > 0) {
      this.headers.set('Content-Type', 'application/octet-stream');
    }
    if (this.keepAlive) {
      this.headers.set('Connection', 'keep-alive');
      this.headers.set('Keep-Alive', 'timeout=60, max=200');
    } else {
      this.headers.set('Connection', 'close');
    }
    this.headers.set('Server', 'LANShare-HarmonyOS/1.0');
    // 局域网服务，浏览器会跨源取图，放开 CORS 更省事
    this.headers.set('Access-Control-Allow-Origin', '*');

    // ★ 必须自动补 Content-Length，这一条是网页端「打开要等 15 秒」的根因。
    //
    // HTTP/1.1 里判定响应体结束有两种方式：Content-Length，或 chunked 编码。
    // 两者都没有时，浏览器只能「等连接关闭」才知道响应收完了。
    // 而本服务的响应走 keep-alive（连接不会主动关），`serve()` 发完响应后
    // 会回到 `readExactly(1, 15000)` 等下一个请求 —— 于是浏览器的
    // /initConfig、/checkPass、/files 这些 JSON 接口，每次都要卡满
    // **15 秒**（那正是首个字节读取的超时值）才拿到结果。
    //
    // 静态资源之所以没这个毛病，是因为 serveRawFile 自己 set 了 Content-Length；
    // 而 HttpResponse.text/json 没有，所以「页面 15 秒后才显示内容」
    // 精确地只体现在 JSON 接口上，HTML/CSS/JS 都是秒开 —— 这个差异就是判据。
    //
    // 204/304 按规范不得带 body，自然也不该有 Content-Length。
    if (!this.headers.has('Content-Length')
      && !this.headers.has('Transfer-Encoding')
      && this.status !== 204 && this.status !== 304) {
      this.headers.set('Content-Length', `${this.body.length}`);
    }

    this.headers.forEach((v: string, k: string) => {
      sb.push(`${k}: ${v}\r\n`);
    });
    sb.push('\r\n');
    return new util.TextEncoder().encodeInto(sb.join(''));
  }
}

/** 流式文件响应描述，替代原实现里直接持有 RandomAccessFile 的做法 */
export class FileStreamSpec {
  /** 应用沙箱内或经用户授权后的绝对路径 */
  filePath: string = '';
  /** 文件总大小 */
  totalSize: number = 0;
  /** 本次要发送的闭区间 [start, end] */
  start: number = 0;
  end: number = 0;
  /** 文件名，用于 Content-Disposition */
  fileName: string = '';

  constructor(filePath: string, totalSize: number, start: number, end: number, fileName: string) {
    this.filePath = filePath;
    this.totalSize = totalSize;
    this.start = start;
    this.end = end;
    this.fileName = fileName;
  }

  get chunkSize(): number {
    return this.end - this.start + 1;
  }
}
