/**
 * 大端字节编解码 —— 平移自 com.fgsqw.utils.ByteUtil +
 * app/src/main/java/com/fgsqw/lanshare/service/CustomData{Input,Output}Stream.java
 *
 * ## 为什么必须自己写
 * JS/ArkTS 的 DataView / TypedArray **原生是小端**，而原 Java 实现跟随
 * java.io.DataOutputStream 的约定，是**大端**（见 CustomDataOutputStream.writeInt:
 * `buffer[0] = (byte)(v >>> 24)`）。协议互通的前提是字节序完全一致，
 * 所以这里显式手写位移，不依赖平台默认。
 *
 * ## 与 Java 的语义对齐
 * - int  ：4 字节大端，**有符号**（readInt 返回 -2^31 ~ 2^31-1，与 Java 一致）
 * - long ：8 字节大端，用「高位/低位拆成两个 int」的方式实现。
 *          JS 的 number 是 double，位运算只有 32 位，所以不能用 <<56。
 * - String：先写 4 字节长度，再写 UTF-8 字节；长度 -1 表示 null（与 Java 一致）
 */

const ArkUtil = {
  TextEncoder: class { encodeInto(s) { return new TextEncoder().encode(s); } },
  TextDecoder: { create(_e) { return { decodeToString: (u) => new TextDecoder('utf-8').decode(u) }; } }
};

/** UTF-8 编解码器，全局复用（TextEncoder 每次构造有开销） */
const TEXT_ENCODER: ArkUtil.TextEncoder = new ArkUtil.TextEncoder();
const TEXT_DECODER: ArkUtil.TextDecoder = ArkUtil.TextDecoder.create('utf-8');

/** 32 位有符号整数的取值范围，用于 long 的拆分 */
const TWO_POW_32: number = 4294967296;

/**
 * 大端写入器。内部缓冲区按需扩容，避免调用方预估长度。
 */
export class ByteWriter {
  private buf: Uint8Array;
  private pos: number = 0;

  constructor(capacity: number = 64) {
    this.buf = new Uint8Array(capacity > 8 ? capacity : 8);
  }

  /** 当前已写入字节数 */
  get length(): number {
    return this.pos;
  }

  /** 确保还能再写 need 个字节 */
  private ensure(need: number): void {
    const required: number = this.pos + need;
    if (required <= this.buf.length) {
      return;
    }
    // 容量翻倍直到够用（均摊 O(1)）
    let cap: number = this.buf.length > 0 ? this.buf.length : 8;
    while (cap < required) {
      cap = cap * 2;
    }
    const next: Uint8Array = new Uint8Array(cap);
    next.set(this.buf.subarray(0, this.pos), 0);
    this.buf = next;
  }

  writeByte(v: number): ByteWriter {
    this.ensure(1);
    this.buf[this.pos] = v & 0xFF;
    this.pos += 1;
    return this;
  }

  writeBoolean(v: boolean): ByteWriter {
    return this.writeByte(v ? 1 : 0);
  }

  /** 2 字节大端 */
  writeShort(v: number): ByteWriter {
    this.ensure(2);
    this.buf[this.pos] = (v >>> 8) & 0xFF;
    this.buf[this.pos + 1] = v & 0xFF;
    this.pos += 2;
    return this;
  }

  /** 4 字节大端有符号。与 Java DataOutputStream.writeInt 位级一致 */
  writeInt(v: number): ByteWriter {
    this.ensure(4);
    this.buf[this.pos] = (v >>> 24) & 0xFF;
    this.buf[this.pos + 1] = (v >>> 16) & 0xFF;
    this.buf[this.pos + 2] = (v >>> 8) & 0xFF;
    this.buf[this.pos + 3] = v & 0xFF;
    this.pos += 4;
    return this;
  }

  /**
   * 8 字节大端。
   * 用「除以 2^32 取高位」而不是位移，因为 JS 位运算仅 32 位，v << 32 会溢出。
   * 支持 long 全量正数范围（时间戳、文件大小足够）。
   */
  writeLong(v: number): ByteWriter {
    const hi: number = Math.floor(v / TWO_POW_32);
    const lo: number = v - hi * TWO_POW_32;
    this.writeInt(hi);
    this.writeInt(lo);
    return this;
  }

  /** 写入原始字节（无长度前缀） */
  writeRaw(src: Uint8Array): ByteWriter {
    this.ensure(src.length);
    this.buf.set(src, this.pos);
    this.pos += src.length;
    return this;
  }

  /** 写入「4 字节长度 + 数据」，对应 Java DataDec.getBytes()/putBytes() 的格式 */
  writeBytes(src: Uint8Array): ByteWriter {
    this.writeInt(src.length);
    return this.writeRaw(src);
  }

  /** 写入「4 字节长度 + UTF-8」。null 写 -1，空串写 0 */
  writeString(s: string | null): ByteWriter {
    if (s === null) {
      return this.writeInt(-1);
    }
    if (s.length === 0) {
      return this.writeInt(0);
    }
    return this.writeBytes(TEXT_ENCODER.encodeInto(s));
  }

  /** 导出已写入部分（复制，调用方可安全持有） */
  toArray(): Uint8Array {
    const out: Uint8Array = new Uint8Array(this.pos);
    out.set(this.buf.subarray(0, this.pos), 0);
    return out;
  }

  /**
   * 在指定绝对偏移原地覆盖写入 4 字节 int。
   * 用于回填长度字段（协议头部的 length 字段需要在 payload 拼完后才知道）。
   */
  patchIntAt(offset: number, v: number): void {
    if (offset + 4 > this.pos) {
      throw new Error(`patchIntAt 越界: offset=${offset}, length=${this.pos}`);
    }
    this.buf[offset] = (v >>> 24) & 0xFF;
    this.buf[offset + 1] = (v >>> 16) & 0xFF;
    this.buf[offset + 2] = (v >>> 8) & 0xFF;
    this.buf[offset + 3] = v & 0xFF;
  }

  /** 直接访问底层缓冲区（配合 patchIntAt 使用，避免二次拷贝） */
  buffer(): Uint8Array {
    return this.buf;
  }
}

/**
 * 大端读取器。越界时返回 0 / 空数组而不是抛异常，
 * 与 Java 侧 DataDec 的既有行为一致（它用 `if (dataIndex <= byteLen)` 守卫）。
 */
export class ByteReader {
  private buf: Uint8Array;
  private pos: number = 0;
  private limit: number = 0;

  constructor(src: Uint8Array) {
    this.buf = src;
    this.limit = src.length;
  }

  /** 剩余可读字节数 */
  get remaining(): number {
    return this.limit - this.pos;
  }

  /** 已读偏移 */
  get position(): number {
    return this.pos;
  }

  /** 绝对定位（用于跳过协议头） */
  seek(offset: number): void {
    this.pos = offset < 0 ? 0 : (offset > this.limit ? this.limit : offset);
  }

  skip(n: number): void {
    this.seek(this.pos + n);
  }

  readByte(): number {
    if (this.pos >= this.limit) {
      return 0;
    }
    const v: number = this.buf[this.pos];
    this.pos += 1;
    return v;
  }

  /** 读取一个有符号字节（-128~127），对齐 Java 的 byte 语义 */
  readSignedByte(): number {
    const v: number = this.readByte();
    return v > 127 ? v - 256 : v;
  }

  readBoolean(): boolean {
    return this.readByte() === 1;
  }

  readShort(): number {
    const b0: number = this.readByte();
    const b1: number = this.readByte();
    return (b0 << 8) | b1;
  }

  /** 4 字节大端有符号。与 Java DataInputStream.readInt 位级一致（可返回负数） */
  readInt(): number {
    const b0: number = this.readByte();
    const b1: number = this.readByte();
    const b2: number = this.readByte();
    const b3: number = this.readByte();
    return (b0 << 24) | (b1 << 16) | (b2 << 8) | b3;
  }

  /** 在绝对偏移读取 4 字节大端 int，不移动读指针 */
  readIntAt(offset: number): number {
    if (offset + 4 > this.limit) {
      return 0;
    }
    const b0: number = this.buf[offset];
    const b1: number = this.buf[offset + 1];
    const b2: number = this.buf[offset + 2];
    const b3: number = this.buf[offset + 3];
    return (b0 << 24) | (b1 << 16) | (b2 << 8) | b3;
  }

  /**
   * 8 字节大端。`hi * 2^32 + (lo >>> 0)` —— lo 用无符号解释，
   * 因为 readInt 返回的是有符号值。
   */
  readLong(): number {
    const hi: number = this.readInt();
    const lo: number = this.readInt();
    return hi * TWO_POW_32 + (lo >>> 0);
  }

  /** 读取长度前缀 + 数据。负长度返回空数组 */
  readBytes(): Uint8Array {
    const len: number = this.readInt();
    if (len <= 0 || this.pos + len > this.limit) {
      return new Uint8Array(0);
    }
    const out: Uint8Array = this.buf.slice(this.pos, this.pos + len);
    this.pos += len;
    return out;
  }

  /** 读取长度前缀 + UTF-8。长度 -1 对应 null */
  readString(): string | null {
    const len: number = this.readInt();
    if (len === -1) {
      return null;
    }
    if (len === 0) {
      return '';
    }
    if (this.pos + len > this.limit) {
      return null;
    }
    const out: string = TEXT_DECODER.decodeToString(this.buf.subarray(this.pos, this.pos + len));
    this.pos += len;
    return out;
  }

  /** 读取剩余全部字节 */
  readRemaining(): Uint8Array {
    if (this.pos >= this.limit) {
      return new Uint8Array(0);
    }
    const out: Uint8Array = this.buf.slice(this.pos, this.limit);
    this.pos = this.limit;
    return out;
  }
}
