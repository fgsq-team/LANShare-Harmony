/**
 * 局域网 TCP 客户端 —— 平移自 LANService.makeSocket() / createSocket()。
 *
 * ## 必须遵守的建链约定（原实现的核心细节）
 * ```
 * connect(ip, port)
 *   -> 立刻 writeInt(MAGIC_NUM)      // 4 字节魔数，未混淆
 * ```
 * 服务端 accept 之后**第一件事就是读这 4 字节做协议分流**
 * （魔数 / HTTP / 丢弃）。少写或写错，对端只会把连接当成垃圾流量静默关掉，
 * 而且不会有任何错误日志 —— 所以这一步不能省。
 *
 * 之后的字节序完全由业务决定（例如 v4 文件传输先写 NEW_VERSION_4）。
 */
import { socket } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { DeviceCodec } from '../core/DeviceCodec';
import { Log } from '../core/Logger';
import { ClientAdapter, SocketLike, TcpChannel } from './NativeSocket';

const TAG: string = 'LanClient';

/**
 * 收发缓冲目标值 = 262144，这是 SDK 允许的**上限**
 * （`ExtraOptionsBase.sendBufferSize` 文档：范围 0~262144，默认 8192）。
 * 想再大也设不进去，所以直接顶格。
 *
 * ★★ 5.1.16：**别再想调到 4MB** —— 服务端曾经填过 4194304，
 *   而 SDK 原文是「**超出范围则回落默认 8192**」，即**静默失效**。
 *   发送端这个 262144 至少是**真生效**的（合法顶格）。
 *
 * ⚠️ 仍未解的疑点（待实测确认）：262144 = 256KB 而数据块是 1MB，
 *   理论上每发 4 个缓冲就装满一块、需等对端读走。
 *   若缓冲确为瓶颈，可考虑的方向是**减小 CHUNK**（对端缓冲也吃紧，暂不动）
 *   或**多条连接**（每条带自己的窗口）。
 */
const TUNE_BUFFER_SIZE: number = 262144;

/**
 * ★★ 5.1.17：是否显式设置收发缓冲。
 *
 * **默认 false = 不设**，让 Linux 内核自己做 TCP 自动调优。
 * 见 `applyTuning` 里的完整论证：显式设 SO_SNDBUF 会关闭自动调优，
 * 把缓冲钉死在 256KB，而数据块是 1MB ⇒ 背压等待全落在 `await write()` 里
 * （真机诊断：`send` 占 97.6%）。浏览器/官方安卓不设，所以能到 60MB/s。
 *
 * 改回 true 可恢复 5.1.16 及更早的显式设值行为（仅供对比回退）。
 */
const TUNE_SOCKET_BUFFERS: boolean = false;

export class LanClient {
  private sock: socket.TCPSocket | null = null;
  private chan: TcpChannel | null = null;
  private connectedIp: string = '';
  private connectedPort: number = 0;
  /** 最近一次 connect 失败的原因，供 UI 直接展示（不吞错误码） */
  private lastError: string = '';

  get channel(): TcpChannel | null {
    return this.chan;
  }

  get error(): string {
    return this.lastError;
  }

  get isConnected(): boolean {
    return this.chan !== null && !this.chan.isClosed;
  }

  get peer(): string {
    return `${this.connectedIp}:${this.connectedPort}`;
  }

  /**
   * 连接对端并写入魔数。
   *
   * ⚠️ 注册顺序很重要：`on('message')` / `on('close')` 必须在 `connect()` **之前**注册。
   * 反过来的话，`connect()` 到 `bind()` 之间（中间还夹着一次 `setExtraOptions` 的
   * 异步往返）到达的字节会**直接丢掉**——TCP 是字节流，先到的数据不会等你注册回调。
   * 对端目前都是「收到请求才应答」，实际不易踩到；但这是白送的隐患，顺手消掉。
   *
   * @param timeoutMs 连接超时。原 Android 写死 4000ms，这里放宽到 5s
   */
  async connect(ip: string, port: number, timeoutMs: number = 5000): Promise<boolean> {
    if (this.isConnected) {
      return true;
    }
    await this.close();
    this.lastError = '';
    try {
      const s: socket.TCPSocket = socket.constructTCPSocketInstance();
      this.sock = s;

      // 先建通道（内部完成 on('message')/on('close') 注册），再发起连接
      const adapter: SocketLike = new ClientAdapter(s);
      const chan: TcpChannel = new TcpChannel(adapter, ip, port);
      this.chan = chan;
      this.connectedIp = ip;
      this.connectedPort = port;

      await s.connect({
        address: { address: ip, port: port, family: 1 },
        timeout: timeoutMs
      });

      // ---- 套接字调优（对端无感，不影响 v4 互通）----
      // TCP_NODELAY：文件传输是「4 字节长度头 + 1MB 数据块」交替出现。
      //   开着 Nagle 时，那个 4 字节头会被攒着等 ACK（对端又开着 delayed ACK），
      //   一来一回最多 40ms —— 1MB 一片就要卡 40ms，等效吞吐直接被压到 25MB/s 量级。
      // 收发缓冲：SDK 文档写明**默认是 8192**（范围 0~262144）。
      //   8KB 的发送缓冲意味着每发 8KB 就要等一次对端确认，
      //   局域网 RTT 1ms 也能把吞吐摁在 8MB/s。拉到上限 256KB 是纯赚。
      // 不设 socketTimeout —— 它的语义是「本地 socket 连接超时」，取值边界没有明确文档，
      // 而我们所有读取都自带超时（TcpChannel.readExactly），不需要底层再插一脚。
      LanClient.applyTuning(s);

      // ★ 建链约定：先发魔数，服务端靠它分流
      await chan.send(DeviceCodec.magicPrefix());
      Log.i(TAG, `已连接 ${ip}:${port} 并发送魔数`);
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      this.lastError = `${err.code} ${err.message}`;
      Log.e(TAG, `连接 ${ip}:${port} 失败: ${this.lastError}`);
      await this.close();
      return false;
    }
  }

  /**
   * 套用调优参数。改的是**本机内核套接字属性**，线上字节流一个都不变，
   * 所以对端是原版 Android / Windows / 1.35 都照样互通。
   *
   * 失败一律吞掉：这些是「有则更快」的项，不是功能项，
   * 某些设备/ROM 不支持时不能连累连接本身。
   */
  private static async applyTuning(s: socket.TCPSocket): Promise<void> {
    try {
      if (TUNE_SOCKET_BUFFERS) {
        await s.setExtraOptions({
          TCPNoDelay: true,
          sendBufferSize: TUNE_BUFFER_SIZE,
          receiveBufferSize: TUNE_BUFFER_SIZE
        } as socket.TCPExtraOptions);
      } else {
        // ★★ 5.1.17：**只设 TCPNoDelay，绝不设 sendBufferSize / receiveBufferSize。**
        //
        // 【为什么这是发送慢的真根因】
        // 显式 `setsockopt(SO_SNDBUF)` 会**关闭 Linux 内核的 TCP 自动调优**：
        //   · 不设  ⇒ 内核按需自动扩缩容（16KB 起，逐步涨到 tcp_wmem 上限，
        //              常见数 MB）⇒ 浏览器/官方安卓网页能到 60MB/s；
        //   · 设为 262144 ⇒ **自动调优被关**，缓冲被钉死在 256KB。
        // 而我们的数据块是 **1MB**（`CHUNK = 1024*1024-12`）
        // ⇒ 每发 4 个缓冲就装满一块，必须等对端读走才能继续
        // ⇒ 背压等待落在 `await sock.write()` 里，正是诊断看到的
        //   `send` 占 97.6%（26~28ms/块）。
        //
        // 【为什么 262144 是最坏值】
        // SDK 上限恰好就是 262144（`@ohos.net.socket.d.ts:260`：范围 0~262144，
        // 超范围**静默回落**默认 8192）⇒ 「顶格」等于「钉死 256KB」，
        // 比内核自动扩容差一个数量级。
        await s.setExtraOptions({
          TCPNoDelay: true
        } as socket.TCPExtraOptions);
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `套接字调优未生效（沿用系统默认）: ${err.code}`);
    }
  }

  async close(): Promise<void> {
    const chan: TcpChannel | null = this.chan;
    this.chan = null;
    if (chan !== null) {
      await chan.closeAsync();
    }
    const s: socket.TCPSocket | null = this.sock;
    this.sock = null;
    if (s !== null) {
      try {
        await s.close();
      } catch (e) {
        // 已经关过了
      }
    }
  }
}
