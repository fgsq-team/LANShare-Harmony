/**
 * v4 协议的裸序列化读写 —— 平移自
 *   app/src/main/java/com/fgsqw/lanshare/service/CustomDataOutputStream.java
 *   app/src/main/java/com/fgsqw/lanshare/service/CustomDataInputStream.java
 *
 * ## 与 DataPacket 的区别（关键）
 * LanShare 有两套完全不同的 TCP 编码：
 *
 * | | 旧版（dataVersion < 4） | v4（NEW_VERSION_4 起头） |
 * |---|---|---|
 * | 命令 | 包在 DataEnc 12 字节头里，全段 0x45 混淆 | 裸 int，**无混淆** |
 * | 字符串 | DataEnc.putString（4 字节长度 + UTF-8） | 同样 4 字节长度 + UTF-8 |
 * | 结构 | 一个包一个命令 | 一条流上顺序写多个字段，长度由业务字段自带 |
 *
 * 两套都从「4 字节魔数」之后的字节开始。本文件只负责 v4 这套裸编码 ——
 * 混淆包那套见 DataPacket.ets。
 *
 * ## 为什么必须有「读满」语义
 * TCP 是字节流，`on('message')` 一次回调可能只给半个 int。
 * 所以这里全部走 channel.readExactly()，语义等价于 Java 的循环读满。
 */
import { util } from '@kit.ArkTS';
import { TcpChannel } from './NativeSocket';

const UTF8_ENC: util.TextEncoder = new util.TextEncoder();

export class ProtoIO {
  // ------------------------------------------------------------------
  // 写：构造字节段（调用方用 channel.send 发出）
  // ------------------------------------------------------------------

  static intBytes(v: number): Uint8Array {
    const out: Uint8Array = new Uint8Array(4);
    out[0] = (v >>> 24) & 0xFF;
    out[1] = (v >>> 16) & 0xFF;
    out[2] = (v >>> 8) & 0xFF;
    out[3] = v & 0xFF;
    return out;
  }

  static longBytes(v: number): Uint8Array {
    const out: Uint8Array = new Uint8Array(8);
    // 高 32 位 / 低 32 位分开算，避免位运算被截断成 32 位
    const hi: number = Math.floor(v / 4294967296);
    const lo: number = v - hi * 4294967296;
    out[0] = (hi >>> 24) & 0xFF;
    out[1] = (hi >>> 16) & 0xFF;
    out[2] = (hi >>> 8) & 0xFF;
    out[3] = hi & 0xFF;
    out[4] = (lo >>> 24) & 0xFF;
    out[5] = (lo >>> 16) & 0xFF;
    out[6] = (lo >>> 8) & 0xFF;
    out[7] = lo & 0xFF;
    return out;
  }

  static boolBytes(v: boolean): Uint8Array {
    return new Uint8Array([v ? 1 : 0]);
  }

  static byteBytes(v: number): Uint8Array {
    return new Uint8Array([v & 0xFF]);
  }

  /** 4 字节长度（大端）+ UTF-8。null 用长度 -1 表示，与原实现一致 */
  static stringBytes(s: string | null): Uint8Array {
    if (s === null) {
      return ProtoIO.intBytes(-1);
    }
    const body: Uint8Array = UTF8_ENC.encodeInto(s);
    const out: Uint8Array = new Uint8Array(4 + body.length);
    out[0] = (body.length >>> 24) & 0xFF;
    out[1] = (body.length >>> 16) & 0xFF;
    out[2] = (body.length >>> 8) & 0xFF;
    out[3] = body.length & 0xFF;
    out.set(body, 4);
    return out;
  }

  /** 把多段字节拼成一段，减少 send 次数 */
  static join(parts: Uint8Array[]): Uint8Array {
    let total: number = 0;
    for (let i = 0; i < parts.length; i++) {
      total += parts[i].length;
    }
    const out: Uint8Array = new Uint8Array(total);
    let off: number = 0;
    for (let i = 0; i < parts.length; i++) {
      out.set(parts[i], off);
      off += parts[i].length;
    }
    return out;
  }

  // ------------------------------------------------------------------
  // 读
  // ------------------------------------------------------------------

  static beInt(b: Uint8Array): number {
    return ((b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]) | 0;
  }

  /** 读 4 字节大端 int。连接断开/超时返回 null */
  static async readInt(channel: TcpChannel, timeoutMs: number = 30000): Promise<number | null> {
    const b: Uint8Array | null = await channel.readExactly(4, timeoutMs);
    if (b === null) {
      return null;
    }
    return ProtoIO.beInt(b);
  }

  /** 读 1 字节布尔 */
  static async readBoolean(channel: TcpChannel, timeoutMs: number = 30000): Promise<boolean | null> {
    const b: Uint8Array | null = await channel.readExactly(1, timeoutMs);
    if (b === null) {
      return null;
    }
    return b[0] === 1;
  }

  /**
   * 读「4 字节长度 + UTF-8」。
   * 长度 -1 表示 null（原实现的空串约定）；长度异常时返回 null 并已经在日志里留痕。
   */
  static async readString(channel: TcpChannel, timeoutMs: number = 30000): Promise<string | null> {
    const lenBuf: Uint8Array | null = await channel.readExactly(4, timeoutMs);
    if (lenBuf === null) {
      return null;
    }
    const len: number = ProtoIO.beInt(lenBuf);
    if (len < 0) {
      return '';
    }
    // 8MB 上限：设备 JSON 与文件列表 JSON 都在几十 KB 量级，
    // 超限说明流已错位，继续读只会把内存吃光。
    if (len > 8 * 1024 * 1024) {
      return null;
    }
    if (len === 0) {
      return '';
    }
    const body: Uint8Array | null = await channel.readExactly(len, timeoutMs);
    if (body === null) {
      return null;
    }
    return new util.TextDecoder().decodeToString(body);
  }
}
