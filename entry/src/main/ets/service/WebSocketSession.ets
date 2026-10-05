/**
 * WebSocket 会话层 —— 接管已升级完成的通道，跑帧读写循环。
 *
 * ## 为什么必须有这一层
 * HttpRouter 只负责把 HTTP 请求变成 101 握手；握手之后这条 TCP 就不再是 HTTP 了，
 * 而是一个裸的帧通道。这一段必须有东西**持续读**，否则：
 *   - 浏览器发来的帧没人取，读缓冲越积越多
 *   - 连接空闲下来，HTTP 那边的读超时会把连接关掉
 *
 * 之前的缺口是：`WsUpgradeRouter.setSink()` 只在 HttpRouter 里定义过，
 * **全工程没有任何调用点**。于是升级后的通道被 push 进 `pending` 数组后无人认领，
 * 紧接着被 accept 循环 close 掉。浏览器侧立刻触发 `onclose`，
 * 弹出「连接断开，请启动LANShare后刷新页面」—— 这就是真机上看到的现象。
 *
 * ## 协议（与 rawfile/web/js/lanshareChat.min.js 严格对齐）
 *   服务端 -> 网页  {"cmd":1, isLeft, devName, devType, message, messageType, filePath, fileSize}
 *                   {"cmd":2, "data":[{"address":"...","devName":"...","devIP":"..."}]}
 *   网页 -> 服务端  {"cmd":1, isLeft:false, devName, message, messageType, selectedDevice, isClip}
 *
 * ## 帧层要点
 * - 客户端帧**必须**带掩码；服务端帧**必须不带**。违反这条浏览器直接断开。
 * - 控制帧（ping/pong/close）载荷 <= 125 字节且不可分片。
 * - 消息可能被分片（CONTINUATION），要累积到 fin 再交给业务。
 */
import { util } from '@kit.ArkTS';
import { Log } from '../core/Logger';
import { TcpChannel } from '../net/NativeSocket';
import { WsOpcode, WsProtocol } from '../net/WsProtocol';

const TAG: string = 'WsSession';

/** 与 WSCmd.js 保持一致 */
export const WS_CMD_SEND_MESSAGE: number = 1;
export const WS_CMD_SYNC_DEVICE_LIST: number = 2;
/**
 * 服务端主动推文件给网页端（本项目扩展，官方网页端原本没有这个方向）。
 *
 * 载荷：`{"cmd":3,"list":["<沙箱内绝对路径>", ...],"names":["<文件名>", ...]}`
 * 网页端收到后直接走 `/compressFiles` + `/downloadZipFile` 两步把文件取走。
 *
 * 为什么必须走这条：HTTP 是请求-响应式，服务端没法「推」一个文件给浏览器，
 * 只能推一个「快来取」的通知，真正的下载还是浏览器自己发起的。
 */
export const WS_CMD_PUSH_FILES: number = 3;

/** 空闲读超时。超时不等于断开：真断开时 channel.isClosed 会置位 */
const IDLE_TIMEOUT_MS: number = 120000;
/** 单帧上限，防止恶意长度把内存吃光 */
const MAX_PAYLOAD: number = 4 * 1024 * 1024;

export class WebSocketSession {
  private channel: TcpChannel;
  /** 取当前设备列表的完整 JSON 文本（SYNC_DEVICE_LIST 整包） */
  private deviceListJson: () => string;
  /** 网页发来的聊天消息，交给业务层转发（第二参数是会话标识 ip:port） */
  private onChat: (json: string, peer: string) => void;
  /** 会话结束时通知持有者，便于从列表里摘除 */
  private onClosed: (s: WebSocketSession) => void;
  private alive: boolean = true;
  private readonly label: string;

  constructor(channel: TcpChannel,
              deviceListJson: () => string,
              onChat: (json: string, peer: string) => void,
              onClosed: (s: WebSocketSession) => void) {
    this.channel = channel;
    this.deviceListJson = deviceListJson;
    this.onChat = onChat;
    this.onClosed = onClosed;
    this.label = `${channel.remoteIp}:${channel.remotePort}`;
  }

  get isAlive(): boolean {
    return this.alive && !this.channel.isClosed;
  }

  get peer(): string {
    return this.label;
  }

  /** 启动会话循环。**不阻塞调用方** —— accept 循环要立刻回去收下一条连接 */
  start(): void {
    this.loop()
      .catch((e: Error) => {
        Log.w(TAG, `[${this.label}] 会话异常: ${e.message}`);
      })
      .then(() => {
        this.alive = false;
        try {
          this.channel.close();
        } catch (e) {
          // 已关闭，忽略
        }
        this.onClosed(this);
      });
  }

  /** 往网页推一条文本消息。失败即视为会话结束 */
  sendText(json: string): void {
    if (!this.isAlive) {
      return;
    }
    this.channel.send(WsProtocol.encodeText(json)).catch((e: Error) => {
      Log.w(TAG, `[${this.label}] 发送失败: ${e.message}`);
    });
  }

  /** 推送设备列表（设备上下线时由业务层调用） */
  pushDeviceList(): void {
    this.sendText(this.deviceListJson());
  }

  /** 主动结束会话 */
  close(): void {
    if (!this.alive) {
      return;
    }
    this.alive = false;
    this.channel.send(WsProtocol.encodeClose(1001, 'server shutdown')).catch(() => {});
    try {
      this.channel.close();
    } catch (e) {
      // 忽略
    }
  }

  // ------------------------------------------------------------------
  // 帧循环
  // ------------------------------------------------------------------

  private async loop(): Promise<void> {
    // 连上先推一次设备列表，网页的下拉框靠它填充
    Log.i(TAG, `[${this.label}] WebSocket 会话建立，已推送设备列表`);
    this.pushDeviceList();

    let fragOpcode: number = -1;
    let fragPayload: Uint8Array = new Uint8Array(0);

    while (this.alive && !this.channel.isClosed) {
      const frame: WsFrameData | null = await this.readFrame();
      if (frame === null) {
        if (this.channel.isClosed) {
          break;
        }
        // 只是空闲超时，连接还活着，继续等
        continue;
      }

      const op: number = frame.opcode;

      if (op === WsOpcode.CLOSE) {
        Log.i(TAG, `[${this.label}] 收到 close 帧，会话结束`);
        this.alive = false;
        this.channel.send(WsProtocol.encodeClose(1000, '')).catch(() => {});
        break;
      }
      if (op === WsOpcode.PING) {
        this.channel.send(WsProtocol.encodePong(frame.payload)).catch(() => {});
        continue;
      }
      if (op === WsOpcode.PONG) {
        continue;
      }

      if (op === WsOpcode.CONTINUATION) {
        if (fragOpcode < 0) {
          Log.w(TAG, `[${this.label}] 收到无起始的续帧，丢弃`);
          continue;
        }
        fragPayload = WebSocketSession.concat(fragPayload, frame.payload);
        if (frame.fin) {
          this.deliver(fragOpcode, fragPayload);
          fragOpcode = -1;
          fragPayload = new Uint8Array(0);
        }
        continue;
      }

      if (op === WsOpcode.TEXT || op === WsOpcode.BINARY) {
        if (frame.fin) {
          this.deliver(op, frame.payload);
        } else {
          fragOpcode = op;
          fragPayload = frame.payload;
        }
      }
    }
  }

  /** 把一条完整消息交给业务 */
  private deliver(opcode: number, payload: Uint8Array): void {
    if (opcode !== WsOpcode.TEXT) {
      Log.w(TAG, `[${this.label}] 暂不处理二进制帧（${payload.length} 字节）`);
      return;
    }
    const text: string = new util.TextDecoder().decodeToString(payload);
    this.onChat(text, this.label);
  }

  /**
   * 读一个完整帧。
   *
   * 用 `channel.readExactly` 逐段读，而不是「先攒够再 parseFrame」——
   * readExactly 自带等待与超时，正好对上「按需读取」的语义，
   * 也省掉了一份自己的接收缓冲。
   *
   * @returns null 表示读超时或连接已断（由调用方区分）
   */
  private async readFrame(): Promise<WsFrameData | null> {
    const head: Uint8Array | null = await this.channel.readExactly(2, IDLE_TIMEOUT_MS);
    if (head === null) {
      return null;
    }

    const b0: number = head[0];
    const b1: number = head[1];
    const fin: boolean = (b0 & 0x80) !== 0;
    const opcode: number = b0 & 0x0F;
    const masked: boolean = (b1 & 0x80) !== 0;
    let len: number = b1 & 0x7F;

    if (len === 126) {
      const ext: Uint8Array | null = await this.channel.readExactly(2, IDLE_TIMEOUT_MS);
      if (ext === null) {
        return null;
      }
      len = (ext[0] << 8) | ext[1];
    } else if (len === 127) {
      const ext: Uint8Array | null = await this.channel.readExactly(8, IDLE_TIMEOUT_MS);
      if (ext === null) {
        return null;
      }
      const hi: number = (ext[0] << 24) | (ext[1] << 16) | (ext[2] << 8) | ext[3];
      if (hi !== 0) {
        Log.e(TAG, `[${this.label}] 帧过大（>4GB），断开`);
        this.alive = false;
        return null;
      }
      len = ((ext[4] << 24) >>> 0) + (ext[5] << 16) + (ext[6] << 8) + ext[7];
    }

    if (len > MAX_PAYLOAD) {
      Log.e(TAG, `[${this.label}] 帧载荷超限 ${len}，断开`);
      this.alive = false;
      return null;
    }

    // RFC 6455：客户端 -> 服务端的帧必须带掩码
    if (!masked) {
      Log.e(TAG, `[${this.label}] 客户端帧未带掩码，按协议断开`);
      this.alive = false;
      return null;
    }
    const mask: Uint8Array | null = await this.channel.readExactly(4, IDLE_TIMEOUT_MS);
    if (mask === null) {
      return null;
    }

    let payload: Uint8Array = new Uint8Array(0);
    if (len > 0) {
      const raw: Uint8Array | null = await this.channel.readExactly(len, IDLE_TIMEOUT_MS);
      if (raw === null) {
        return null;
      }
      for (let i = 0; i < len; i++) {
        raw[i] = raw[i] ^ mask[i & 3];
      }
      payload = raw;
    }

    const out: WsFrameData = new WsFrameData();
    out.fin = fin;
    out.opcode = opcode;
    out.payload = payload;
    return out;
  }

  private static concat(a: Uint8Array, b: Uint8Array): Uint8Array {
    const out: Uint8Array = new Uint8Array(a.length + b.length);
    out.set(a, 0);
    out.set(b, a.length);
    return out;
  }
}

/** 解析出的帧（本层内部用，不复用 WsProtocol.WsFrame 的 consumed 字段） */
class WsFrameData {
  fin: boolean = true;
  opcode: number = WsOpcode.TEXT;
  payload: Uint8Array = new Uint8Array(0);
}
