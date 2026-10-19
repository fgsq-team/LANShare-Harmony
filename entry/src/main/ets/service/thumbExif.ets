/**
 * 缩略图 EXIF 解析纯函数（5.1.88）。
 *
 * ## 为什么单独一个文件
 * `@Concurrent` 函数（见 thumbWorker.ets）**只能使用 import 变量或局部变量** ——
 * 同文件的模块级函数/常量调用会被 es2abc 直接拒编译：
 *   「Concurrent function should only use import variable or local variable」
 * 所以纯函数与常量必须放在独立文件、由 worker 以 import 引入。
 *
 * 本文件无 @Concurrent、无 class、无模块级可变变量，函数互相调用不受约束。
 *
 * 行为规则逐条复制自 Index（5.0.40 / 5.0.42，必须保持一致）：
 * 「EXIF 在 JPEG 哪个段」是标准规定的，与设备实现无关。
 */
import { fileIo } from '@kit.CoreFileKit';

/** 缩略图长边上限（与 Index.cacheThumbInner 一致） */
export const THUMB_SIDE: number = 320;
/** 极端尺寸保护（与 Index.cacheThumbInner 一致） */
export const MAX_SIDE: number = 16384;
/** EXIF 读取窗口：JPEG 头部 128K 足够覆盖 APP1 */
export const EXIF_HEAD: number = 131072;

/** EXIF Orientation（语义串或数字串）-> 需要顺时针旋转的度数 */
export function exifDegOf(ori: string): number {
  if (ori.length === 0) {
    return 0;
  }
  // 语义串：部分版本/设备返回 'Right-top' 这种（华为官方 FAQ 示例就是比这个）
  if (ori === 'Bottom-right') {
    return 180;
  }
  if (ori === 'Right-top' || ori === 'Right-bottom') {
    return 90;
  }
  if (ori === 'Left-top' || ori === 'Left-bottom') {
    return 270;
  }
  if (ori === 'Top-left' || ori === 'Top-right' || ori === 'Bottom-left') {
    return 0;
  }
  return exifDegFromTextOf(ori);
}

/** 从 '6' / 'Unknown Value 6' 这类文本里取出方向数字再换算角度 */
export function exifDegFromTextOf(ori: string): number {
  let n: number = -1;
  for (let i: number = 0; i < ori.length; i++) {
    const code: number = ori.charCodeAt(i);
    if (code >= 48 && code <= 57) {
      n = code - 48;
      break;
    }
  }
  if (n === 3) {
    return 180;
  }
  if (n === 6 || n === 7) {
    return 90;
  }
  if (n === 5 || n === 8) {
    return 270;
  }
  return 0;
}

/** 自己读 JPEG 字节拿 EXIF（系统 API 返回值格式不统一时的补位） */
export function jpegExifDegOf(path: string): number {
  let f: fileIo.File | null = null;
  try {
    f = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);
    const head: ArrayBuffer = new ArrayBuffer(EXIF_HEAD);
    const n: number = fileIo.readSync(f.fd, head);
    if (n < 4) {
      return 0;
    }
    const b: Uint8Array = new Uint8Array(head, 0, n);
    if (b[0] !== 0xFF || b[1] !== 0xD8) {
      return 0; // 不是 JPEG（HEIC / PNG 之类）
    }
    let i: number = 2;
    while (i + 4 <= n) {
      if (b[i] !== 0xFF) {
        i = i + 1;
        continue;
      }
      const mk: number = b[i + 1];
      if (mk === 0xD8 || mk === 0x01 || (mk >= 0xD0 && mk <= 0xD7)) {
        i = i + 2; // 这些标记不带长度字段
        continue;
      }
      if (mk === 0xDA) {
        break; // SOS：图像数据开始，EXIF 只可能在它之前
      }
      const segLen: number = (b[i + 2] << 8) | b[i + 3];
      if (mk === 0xE1) {
        // APP1：payload 以 "Exif\0\0" 开头的才是 EXIF（XMP 之类的 APP1 不是）
        const p: number = i + 4;
        if (p + 12 <= n && b[p] === 0x45 && b[p + 1] === 0x78 && b[p + 2] === 0x69 &&
            b[p + 3] === 0x66 && b[p + 4] === 0x00 && b[p + 5] === 0x00) {
          return tiffDegOf(b, p + 6, n);
        }
      }
      if (segLen < 2) {
        break;
      }
      i = i + 2 + segLen;
    }
    return 0;
  } catch (e) {
    return 0;
  } finally {
    if (f !== null) {
      try {
        fileIo.closeSync(f);
      } catch (x) {
        // 忽略
      }
    }
  }
}

/** 从 EXIF 的 TIFF 头里找出 IFD0 的 Orientation（tag 0x0112） */
function tiffDegOf(b: Uint8Array, tiff: number, n: number): number {
  if (tiff + 8 > n) {
    return 0;
  }
  const le: boolean = (b[tiff] === 0x49 && b[tiff + 1] === 0x49); // 'II' 小端
  const be: boolean = (b[tiff] === 0x4D && b[tiff + 1] === 0x4D); // 'MM' 大端
  if (!le && !be) {
    return 0;
  }
  const ifd: number = tiff + u32Of(b, tiff + 4, le);
  if (ifd < 0 || ifd + 2 > n) {
    return 0;
  }
  const cnt: number = u16Of(b, ifd, le);
  for (let k: number = 0; k < cnt; k++) {
    const e: number = ifd + 2 + k * 12;
    if (e + 12 > n) {
      break;
    }
    if (u16Of(b, e, le) === 0x0112) {
      // tag = Orientation。type 是 SHORT 时值就塞在 value 字段里，取低 16 位
      return degOfOriOf(u16Of(b, e + 8, le));
    }
  }
  return 0;
}

/** 按字节序读 16 位无符号 */
function u16Of(b: Uint8Array, o: number, le: boolean): number {
  return le ? (b[o] | (b[o + 1] << 8)) : ((b[o] << 8) | b[o + 1]);
}

/** 按字节序读 32 位无符号 */
function u32Of(b: Uint8Array, o: number, le: boolean): number {
  return le ? ((b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0)
    : (((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0);
}

/** EXIF Orientation -> 需要顺时针转多少度（2/4/5/7 带镜像，只还原旋转那部分） */
function degOfOriOf(v: number): number {
  if (v === 3 || v === 4) {
    return 180;
  }
  if (v === 6 || v === 7) {
    return 90;
  }
  if (v === 5 || v === 8) {
    return 270;
  }
  return 0;
}
