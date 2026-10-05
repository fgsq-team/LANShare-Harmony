/**
 * WebSocket 服务端（RFC 6455）—— 替代 jar 里的 com.fgsqw.websocket.WebSocketServer
 *
 * 对应原项目的 `/wss` 路由，服务 rawfile/web/js/lanshareChat.min.js 的网页聊天端。
 *
 * ## 为什么服务端 WS 必须自己写
 * 鸿蒙的 `@ohos.net.webSocket` 只提供**客户端**。
 * 服务端侧需要自己完成：握手（Sec-WebSocket-Accept 计算）+ 帧编解码。
 * 这部分是纯协议逻辑、有标准可依，属于确定性工程。
 *
 * ## 帧格式要点（踩坑清单）
 * - 客户端发往服务端的帧**必须**带掩码（MASK=1），服务端回包**必须不带**掩码。
 *   违反这条浏览器会直接断开。
 * - 长度编码有三档：<126 单字节、126 时后跟 2 字节、127 时后跟 8 字节。
 * - 控制帧（close/ping/pong）载荷不得超过 125 字节，且不可分片。
 * - close 帧需要回送，然后才能关 TCP。
 */
import { util } from '@kit.ArkTS';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { Log } from '../core/Logger';

const TAG: string = 'WsProtocol';

/** 帧操作码 */
export class WsOpcode {
  static readonly CONTINUATION: number = 0x0;
  static readonly TEXT: number = 0x1;
  static readonly BINARY: number = 0x2;
  static readonly CLOSE: number = 0x8;
  static readonly PING: number = 0x9;
  static readonly PONG: number = 0xA;
}

/** 解出的一个帧 */
export class WsFrame {
  fin: boolean = true;
  opcode: number = WsOpcode.TEXT;
  payload: Uint8Array = new Uint8Array(0);
  /** 该帧在接收缓冲里占用的字节数（含头部与掩码）。parseFrame 成功后有效 */
  consumed: number = 0;

  /** 文本帧内容（opcode=TEXT 时有效） */
  text(): string {
    return new util.TextDecoder().decodeToString(this.payload);
  }
}

/** 帧解析结果 */
export class WsParseResult {
  static readonly NEED_MORE: number = 0;
  static readonly DONE: number = 1;
  static readonly INVALID: number = 2;
}

export class WsProtocol {
  /** WebSocket 握手用的固定 GUID（RFC 6455 §1.3） */
  private static readonly WS_GUID: string = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

  /**
   * 计算 Sec-WebSocket-Accept。
   * 原 jar 用 `MessageDigest("SHA-1")` + `Base64`；鸿蒙侧用 cryptoFramework + util.Base64Helper。
   * 结果必须是 base64(SHA1(key + GUID))。
   */
  static acceptKey(clientKey: string): string {
    try {
      const generator: cryptoFramework.Md = cryptoFramework.createMd('SHA1');
      generator.updateSync({
        data: new util.TextEncoder().encodeInto(clientKey + WsProtocol.WS_GUID)
      });
      const digest: cryptoFramework.DataBlob = generator.digestSync();
      return new util.Base64Helper().encodeToStringSync(digest.data);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      // 工程器提示 createMd 并非所有设备都具备该能力（syscap），且会抛异常。
      // 这里退化为空串：调用方据此拒绝握手，而不是崩溃。
      Log.e(TAG, `计算 Sec-WebSocket-Accept 失败: ${err.code} ${err.message}`);
      return '';
    }
  }

  /**
   * 生成 101 Switching Protocols 响应头。
   *
   * ⚠️ 这里**不能**加 Content-Length / Transfer-Encoding ——
   * 握手后这条 TCP 连接就变成裸帧通道了，带上这些头浏览器会当成有 body 的响应。
   */
  static handshakeResponse(clientKey: string): Uint8Array {
    const accept: string = WsProtocol.acceptKey(clientKey);
    return new util.TextEncoder().encodeInto(
      'HTTP/1.1 101 Switching Protocols\r\n' +
      'Upgrade: websocket\r\n' +
      'Connection: Upgrade\r\n' +
      `Sec-WebSocket-Accept: ${accept}\r\n` +
      '\r\n'
    );
  }

  /** 请求是否是一个 WebSocket 升级请求 */
  static isUpgrade(headers: Map<string, string>): boolean {
    const upgrade: string | undefined = headers.get('upgrade');
    const connection: string | undefined = headers.get('connection');
    const key: string | undefined = headers.get('sec-websocket-key');
    if (upgrade === undefined || key === undefined) {
      return false;
    }
    const connOk: boolean = connection !== undefined && connection.toLowerCase().includes('upgrade');
    return upgrade.toLowerCase() === 'websocket' && connOk;
  }

  // ------------------------------------------------------------------
  // 发送侧：服务端 -> 客户端，一律不加掩码
  // ------------------------------------------------------------------

  /** 编码一个帧 */
  static encodeFrame(opcode: number, payload: Uint8Array, fin: boolean = true): Uint8Array {
    const len: number = payload.length;
    let headerLen: number;
    if (len < 126) {
      headerLen = 2;
    } else if (len <= 0xFFFF) {
      headerLen = 4;
    } else {
      headerLen = 10;
    }
    const out: Uint8Array = new Uint8Array(headerLen + len);
    out[0] = (fin ? 0x80 : 0x00) | (opcode & 0x0F);
    // 服务端帧 MASK 位必须为 0
    if (len < 126) {
      out[1] = len;
    } else if (len <= 0xFFFF) {
      out[1] = 126;
      out[2] = (len >>> 8) & 0xFF;
      out[3] = len & 0xFF;
    } else {
      out[1] = 127;
      // JS 位运算只有 32 位，高位直接写 0（单帧上限 2^32-1 字节，局域网够用）
      out[2] = 0; out[3] = 0; out[4] = 0; out[5] = 0;
      out[6] = (len >>> 24) & 0xFF;
      out[7] = (len >>> 16) & 0xFF;
      out[8] = (len >>> 8) & 0xFF;
      out[9] = len & 0xFF;
    }
    out.set(payload, headerLen);
    return out;
  }

  static encodeText(text: string): Uint8Array {
    return WsProtocol.encodeFrame(WsOpcode.TEXT, new util.TextEncoder().encodeInto(text));
  }

  static encodeBinary(data: Uint8Array): Uint8Array {
    return WsProtocol.encodeFrame(WsOpcode.BINARY, data);
  }

  static encodePong(payload: Uint8Array = new Uint8Array(0)): Uint8Array {
    return WsProtocol.encodeFrame(WsOpcode.PONG, payload);
  }

  static encodeClose(code: number = 1000, reason: string = ''): Uint8Array {
    const reasonBytes: Uint8Array = new util.TextEncoder().encodeInto(reason);
    // 控制帧载荷 <= 125
    const payload: Uint8Array = new Uint8Array(2 + Math.min(reasonBytes.length, 123));
    payload[0] = (code >>> 8) & 0xFF;
    payload[1] = code & 0xFF;
    payload.set(reasonBytes.subarray(0, payload.length - 2), 2);
    return WsProtocol.encodeFrame(WsOpcode.CLOSE, payload);
  }

  // ------------------------------------------------------------------
  // 接收侧：客户端 -> 服务端，必须带掩码，逐字节 XOR 还原
  // ------------------------------------------------------------------

  /**
   * 尝试从 buf 中解出一个帧。
   *
   * @param buf 接收缓冲
   * @param len buf 中的有效字节数
   * @param out 解析成功时填充
   * @returns NEED_MORE / DONE / INVALID；DONE 时调用方把 buf 前 `consumed` 字节丢弃
   */
  static parseFrame(buf: Uint8Array, len: number, out: WsFrame): number {
    if (len < 2) {
      return WsParseResult.NEED_MORE;
    }
    const b0: number = buf[0];
    const b1: number = buf[1];
    const fin: boolean = (b0 & 0x80) !== 0;
    const opcode: number = b0 & 0x0F;
    const masked: boolean = (b1 & 0x80) !== 0;
    let payloadLen: number = b1 & 0x7F;
    let offset: number = 2;

    if (payloadLen === 126) {
      if (len < offset + 2) {
        return WsParseResult.NEED_MORE;
      }
      payloadLen = (buf[offset] << 8) | buf[offset + 1];
      offset += 2;
    } else if (payloadLen === 127) {
      if (len < offset + 8) {
        return WsParseResult.NEED_MORE;
      }
      // 高 4 字节若非 0，说明超过 2^32，本项目不支持
      const hi: number = (buf[offset] << 24) | (buf[offset + 1] << 16) |
        (buf[offset + 2] << 8) | buf[offset + 3];
      if (hi !== 0) {
        Log.e(TAG, 'WebSocket 帧过大（>4GB），拒绝');
        return WsParseResult.INVALID;
      }
      payloadLen = ((buf[offset + 4] << 24) >>> 0) + (buf[offset + 5] << 16) +
        (buf[offset + 6] << 8) + buf[offset + 7];
      offset += 8;
    }

    if (payloadLen > 16 * 1024 * 1024) {
      Log.e(TAG, `WebSocket 帧过大: ${payloadLen}`);
      return WsParseResult.INVALID;
    }

    // 客户端帧必须带掩码，否则按协议拒绝
    if (!masked) {
      Log.e(TAG, '客户端帧未带掩码，按 RFC 6455 拒绝');
      return WsParseResult.INVALID;
    }
    if (len < offset + 4) {
      return WsParseResult.NEED_MORE;
    }
    const mask: Uint8Array = buf.slice(offset, offset + 4);
    offset += 4;

    if (len < offset + payloadLen) {
      return WsParseResult.NEED_MORE;
    }

    const payload: Uint8Array = new Uint8Array(payloadLen);
    for (let i = 0; i < payloadLen; i++) {
      payload[i] = buf[offset + i] ^ mask[i & 3];
    }

    out.fin = fin;
    out.opcode = opcode;
    out.payload = payload;
    // 消费长度 = 头部 + 掩码 + 载荷
    out.consumed = offset + payloadLen;
    return WsParseResult.DONE;
  }
}
