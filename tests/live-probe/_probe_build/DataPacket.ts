/**
 * LanShare 私有封包协议 —— 平移自
 *   app/src/main/java/com/fgsqw/lanshare/utils/DataEnc.java
 *   app/src/main/java/com/fgsqw/lanshare/utils/DataDec.java
 *
 * ## 协议布局（全部大端）
 * ```
 * offset  size  field
 *   0      4    cmd     命令码（见 LCmd.ets），有符号 int
 *   4      4    count   序号 / 分片计数
 *   8      4    length  payload 字节长度（不含 12 字节头）
 *  12      N    payload
 * ```
 *
 * ## 混淆层
 * 封装完成后对 `[0, 12+length)` 全段（含头）做一次字节变换：
 *   编码： b' = ((b - 1) & 0xFF) ^ 0x45
 *   解码： b' = ((b ^ 0x45) + 1) & 0xFF
 * 解码时**必须先解头再解体**，因为体长度来自头里的 length 字段。
 *
 * ⚠️ 这不是加密。它只是把明文特征打散，防止同网段随手抓包直接可读。
 *    真正的机密性由上层 AES（AesCodec.ets）承担。
 *
 * ## UDP 数据报
 * UDP 报文在混淆包之前再前置 4 字节魔数 MAGIC_NUM，用于快速丢弃杂包：
 * ```
 * [0..3] MAGIC_NUM  未混淆
 * [4..]  混淆包      4 + 12 + length 字节
 * ```
 * TCP 流上不发魔数，见 CustomDataStream。
 */

const ArkUtil = {
  TextEncoder: class { encodeInto(s) { return new TextEncoder().encode(s); } },
  TextDecoder: { create(_e) { return { decodeToString: (u) => new TextDecoder('utf-8').decode(u) }; } }
};

import { ByteReader } from './ByteCodec.ts';
import { LanConfig } from './LanConfig.ts';

/** 混淆异或常量（与 Java 端一致） */
const XOR_KEY: number = 0x45;

/** 全局复用的 UTF-8 编码器 */
const UTF8: ArkUtil.TextEncoder = new ArkUtil.TextEncoder();

export class DataPacket {
  /** 协议头长度：cmd(4) + count(4) + length(4) */
  static readonly HEADER_LEN: number = 12;
  /** 魔数长度（仅 UDP 报文使用） */
  static readonly MAGIC_LEN: number = 4;

  /**
   * 原地混淆。范围 [0, end)。
   * 逐字节 8 位无符号运算，与 Java `(byte)((b-1) ^ 0x45)` 的结果位级一致
   * （Java 的符号扩展经强制转换回 byte 后等价于 8 位模运算）。
   */
  static scramble(buf: Uint8Array, end: number): void {
    const bound: number = end < buf.length ? end : buf.length;
    for (let i = 0; i < bound; i++) {
      buf[i] = ((buf[i] - 1) & 0xFF) ^ XOR_KEY;
    }
  }

  /**
   * 原地解混淆。范围 [start, end)。
   * 注意 start 一般为 0（头）或 HEADER_LEN（体），不可跳过头部。
   */
  static unscramble(buf: Uint8Array, start: number, end: number): void {
    const from: number = start < 0 ? 0 : start;
    const bound: number = end < buf.length ? end : buf.length;
    for (let i = from; i < bound; i++) {
      buf[i] = ((buf[i] ^ XOR_KEY) + 1) & 0xFF;
    }
  }
}

/**
 * 数据封装器。与 Java `DataEnc` 一一对应，保持链式调用风格，
 * 使从 LANService / LHttpServer 平移过来的调用点可以机械替换。
 *
 * ```ts
 * // Java: DataEnc enc = new DataEnc(); enc.packData(cmd); enc.putString(name); ...
 * const enc = new DataEnc();
 * enc.packData(LCmd.UDP_SET_DEVICES);
 * enc.putString('我的手机');
 * const bytes = enc.encode();   // == Java 的 encData()
 * ```
 */
export class DataEnc {
  private buf: Uint8Array;
  private pos: number;
  /** 是否已执行过混淆（Java 中的 canEncData），防止重复混淆 */
  private scrambled: boolean = false;

  private cmdValue: number = 0;
  private countValue: number = 0;

  constructor(size: number = 0) {
    this.buf = new Uint8Array(DataPacket.HEADER_LEN + (size > 0 ? size : 0));
    this.pos = DataPacket.HEADER_LEN;
  }

  /** 用一个已完成混淆的裸缓冲区构造（用于解析或转发场景） */
  static wrap(bs: Uint8Array): DataEnc {
    const e: DataEnc = new DataEnc();
    e.buf = bs;
    e.pos = bs.length;
    e.scrambled = true;
    return e;
  }

  /** 确保剩余可写空间 */
  private ensure(need: number): void {
    const required: number = this.pos + need;
    if (required <= this.buf.length) {
      return;
    }
    let cap: number = this.buf.length > 0 ? this.buf.length : DataPacket.HEADER_LEN;
    while (cap < required) {
      cap = cap * 2;
    }
    const next: Uint8Array = new Uint8Array(cap);
    next.set(this.buf.subarray(0, this.pos), 0);
    this.buf = next;
  }

  /** 写入大端 int（私有，直接操作 buf，避开 ByteWriter 的独立指针） */
  private writeIntAt(offset: number, v: number): void {
    this.buf[offset] = (v >>> 24) & 0xFF;
    this.buf[offset + 1] = (v >>> 16) & 0xFF;
    this.buf[offset + 2] = (v >>> 8) & 0xFF;
    this.buf[offset + 3] = v & 0xFF;
  }

  /**
   * 重置为一条新包：写指针回到 12，cmd/count/length 归零。
   * 对应 Java `DataEnc.packData(cmd)`。
   */
  packData(cmd: number): DataEnc {
    this.pos = DataPacket.HEADER_LEN;
    this.scrambled = false;
    this.setCmd(cmd);
    this.setCount(0);
    this.setLength(0);
    return this;
  }

  setCmd(cmd: number): DataEnc {
    this.cmdValue = cmd;
    this.writeIntAt(0, cmd);
    return this;
  }

  setCount(count: number): DataEnc {
    this.countValue = count;
    this.writeIntAt(4, count);
    return this;
  }

  setLength(length: number): DataEnc {
    this.writeIntAt(8, length);
    return this;
  }

  putByte(b: number): DataEnc {
    this.ensure(1);
    this.buf[this.pos] = b & 0xFF;
    this.pos += 1;
    return this;
  }

  putBoolean(v: boolean): DataEnc {
    return this.putByte(v ? 1 : 0);
  }

  putShort(v: number): DataEnc {
    this.ensure(2);
    this.buf[this.pos] = (v >>> 8) & 0xFF;
    this.buf[this.pos + 1] = v & 0xFF;
    this.pos += 2;
    return this;
  }

  putInt(v: number): DataEnc {
    this.ensure(4);
    this.writeIntAt(this.pos, v);
    this.pos += 4;
    return this;
  }

  putLong(v: number): DataEnc {
    const hi: number = Math.floor(v / 4294967296);
    const lo: number = v - hi * 4294967296;
    this.putInt(hi);
    this.putInt(lo);
    return this;
  }

  /** 写入原始字节，无长度前缀 */
  putRaw(src: Uint8Array): DataEnc {
    this.ensure(src.length);
    this.buf.set(src, this.pos);
    this.pos += src.length;
    return this;
  }

  /** 写入「4 字节长度 + 数据」，对应 Java DataEnc.putBytes() */
  putBytes(src: Uint8Array): DataEnc {
    this.putInt(src.length);
    return this.putRaw(src);
  }

  /** 写入「4 字节长度 + UTF-8」，对应 Java DataEnc.putString()
   *
   * 注意 ArkTS 的 TextEncoder 方法与 Web 不同：是 encodeInto()，
   * 不是 encode()。TextDecoder 侧同理用 decodeToString()。
   */
  putString(v: string): DataEnc {
    const bytes: Uint8Array = UTF8.encodeInto(v);
    this.putInt(bytes.length);
    return this.putRaw(bytes);
  }

  getCmd(): number {
    return this.cmdValue;
  }

  getCount(): number {
    return this.countValue;
  }

  /** 当前整包长度（含 12 字节头）。对应 Java DataEnc.getDataLen() */
  getDataLen(): number {
    return this.pos;
  }

  /** 从头回填 length 字段 */
  private fillLength(): void {
    this.setLength(this.pos - DataPacket.HEADER_LEN);
  }

  /**
   * 完成封装：回填 length -> 全段混淆 -> 返回截断到实际长度的副本。
   * 对应 Java `DataEnc.encData()`。
   *
   * ⚠️ fillLength() 必须和 scramble 一起被 scrambled 标志守卫。
   * Java 侧 `if (canEncData) return bytes;` 的提前返回同样在保护这一点：
   * 一旦混淆完成，再写 length 就会把已混淆的字节覆盖成明文，破坏整包。
   * 所以本方法**幂等** —— 重复调用返回同一份字节。
   */
  encode(): Uint8Array {
    if (!this.scrambled) {
      this.fillLength();
      DataPacket.scramble(this.buf, this.pos);
      this.scrambled = true;
    }
    return this.buf.slice(0, this.pos);
  }

  /**
   * 组装 UDP 数据报：`MAGIC_NUM(4, 未混淆) + 混淆包`。
   * 对应 Android 侧 UDPTools.sendData() 的装包逻辑。
   */
  encodeUdp(): Uint8Array {
    const body: Uint8Array = this.encode();
    const out: Uint8Array = new Uint8Array(DataPacket.MAGIC_LEN + body.length);
    out[0] = (LanConfig.MAGIC_NUM >>> 24) & 0xFF;
    out[1] = (LanConfig.MAGIC_NUM >>> 16) & 0xFF;
    out[2] = (LanConfig.MAGIC_NUM >>> 8) & 0xFF;
    out[3] = LanConfig.MAGIC_NUM & 0xFF;
    out.set(body, DataPacket.MAGIC_LEN);
    return out;
  }
}

/**
 * 数据解析器。与 Java `DataDec` 一一对应。
 *
 * 典型用法：
 * ```ts
 * const dec = DataDec.fromUdp(datagram);   // 自动剥魔数 + 全段解混淆
 * if (dec === null) { return; }            // 不是 LanShare 报文
 * switch (dec.getCmd()) {
 *   case LCmd.UDP_SET_DEVICES: {
 *     const name = dec.getString();
 *     ...
 *   }
 * }
 * ```
 */
export class DataDec {
  private buf: Uint8Array;
  private limit: number = 0;
  private pos: number = DataPacket.HEADER_LEN;
  private decoded: boolean = false;

  private constructor(bs: Uint8Array) {
    this.buf = bs;
    this.limit = bs.length;
  }

  /** 直接从 TCP 流读到的裸包构造（还未解混淆） */
  static raw(bs: Uint8Array): DataDec {
    return new DataDec(bs);
  }

  /** 从 UDP 数据报构造：校验魔数 -> 剥掉 4 字节头 -> 解混淆。失败返回 null */
  static fromUdp(datagram: Uint8Array): DataDec | null {
    if (datagram.length < DataPacket.MAGIC_LEN + DataPacket.HEADER_LEN) {
      return null;
    }
    const magic: number =
      (datagram[0] << 24) | (datagram[1] << 16) | (datagram[2] << 8) | datagram[3];
    if (magic !== LanConfig.MAGIC_NUM) {
      return null;
    }
    const body: Uint8Array = datagram.slice(DataPacket.MAGIC_LEN);
    const dec: DataDec = new DataDec(body);
    dec.decodeAll();
    return dec;
  }

  /** 解头部（必需先行，否则读不到 body 长度） */
  decodeHeader(): void {
    if (this.decoded) {
      return;
    }
    DataPacket.unscramble(this.buf, 0, DataPacket.HEADER_LEN);
  }

  /** 解全部（头 + 体） */
  decodeAll(): void {
    if (this.decoded) {
      return;
    }
    this.decodeHeader();
    const bodyLen: number = this.readIntAt(8);
    if (bodyLen > 0) {
      const end: number = DataPacket.HEADER_LEN + bodyLen;
      DataPacket.unscramble(this.buf, DataPacket.HEADER_LEN, end < this.limit ? end : this.limit);
    }
    this.decoded = true;
  }

  /** 仅头部已解时可用；返回有序号的原始命令码 */
  getCmd(): number {
    return this.readIntAt(0);
  }

  getCount(): number {
    return this.readIntAt(4);
  }

  getLength(): number {
    return this.readIntAt(8);
  }

  getByteLen(): number {
    return this.limit;
  }

  private readIntAt(offset: number): number {
    if (offset + 4 > this.limit) {
      return 0;
    }
    return (
      (this.buf[offset] << 24) |
      (this.buf[offset + 1] << 16) |
      (this.buf[offset + 2] << 8) |
      this.buf[offset + 3]
    );
  }

  /** 读取偏移（相对 payload 起点） */
  getDataIndex(): number {
    return this.pos - DataPacket.HEADER_LEN;
  }

  seek(offset: number): void {
    const p: number = DataPacket.HEADER_LEN + offset;
    this.pos = p < DataPacket.HEADER_LEN ? DataPacket.HEADER_LEN : (p > this.limit ? this.limit : p);
  }

  skip(n: number): void {
    this.seek(this.getDataIndex() + n);
  }

  private reader(): ByteReader {
    const r: ByteReader = new ByteReader(this.buf);
    r.seek(this.pos);
    return r;
  }

  private syncFrom(r: ByteReader): void {
    this.pos = r.position;
  }

  readByte(): number {
    if (this.pos >= this.limit) {
      return 0;
    }
    const v: number = this.buf[this.pos];
    this.pos += 1;
    return v;
  }

  readBoolean(): boolean {
    return this.readByte() === 1;
  }

  readShort(): number {
    const r: ByteReader = this.reader();
    const v: number = r.readShort();
    this.syncFrom(r);
    return v;
  }

  readInt(): number {
    const r: ByteReader = this.reader();
    const v: number = r.readInt();
    this.syncFrom(r);
    return v;
  }

  readLong(): number {
    const r: ByteReader = this.reader();
    const v: number = r.readLong();
    this.syncFrom(r);
    return v;
  }

  /** 读取「4 字节长度 + 数据」 */
  readBytes(): Uint8Array {
    const r: ByteReader = this.reader();
    const v: Uint8Array = r.readBytes();
    this.syncFrom(r);
    return v;
  }

  /** 读取「4 字节长度 + UTF-8」，null 用长度 -1 表示 */
  readString(): string | null {
    const r: ByteReader = this.reader();
    const v: string | null = r.readString();
    this.syncFrom(r);
    return v;
  }

  /** 取剩余全部字节 */
  readRemaining(): Uint8Array {
    if (this.pos >= this.limit) {
      return new Uint8Array(0);
    }
    const out: Uint8Array = this.buf.slice(this.pos, this.limit);
    this.pos = this.limit;
    return out;
  }

  /** 取剩余字节写入调用方提供的缓冲区（对应 Java getSurplusBytes(buff, off)） */
  readRemainingInto(buff: Uint8Array, off: number): number {
    const rest: Uint8Array = this.readRemaining();
    buff.set(rest, off);
    return rest.length;
  }

  /** 直接访问解混淆后的底层缓冲区 */
  raw(): Uint8Array {
    return this.buf;
  }
}

/** 常用包构造快捷方法，减少在业务层的样板代码 */
export class Packets {
  /** 构造带单个字符串字段的 UDP 包（如设备心跳） */
  static udpString(cmd: number, s: string): Uint8Array {
    const e: DataEnc = new DataEnc(64);
    e.packData(cmd);
    e.putString(s);
    return e.encodeUdp();
  }

  /** 构造带整数字段 + JSON 字符串的 UDP 包 */
  static udpJson(cmd: number, count: number, json: string): Uint8Array {
    const e: DataEnc = new DataEnc(json.length + 16);
    e.packData(cmd);
    e.setCount(count);
    e.putString(json);
    return e.encodeUdp();
  }

  /** 构造空 body 的心跳/探测包 */
  static udpEmpty(cmd: number): Uint8Array {
    const e: DataEnc = new DataEnc(0);
    e.packData(cmd);
    return e.encodeUdp();
  }

  /** 构造 TCP 流上的包（无魔数） */
  static tcp(cmd: number, count: number, body: Uint8Array): Uint8Array {
    const e: DataEnc = new DataEnc(body.length + 8);
    e.packData(cmd);
    e.setCount(count);
    e.putRaw(body);
    return e.encode();
  }
}
