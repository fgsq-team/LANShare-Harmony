/**
 * 局域网 TCP 服务端 —— 替代 LANService.fileServer() 那段 ServerSocket + accept 循环
 *
 * ## 关键设计：单端口三协议分流（必须保留）
 * 原 Android 实现（LANService.java 1838-1857）在**同一个端口 5856** 上根据前 4 字节分流：
 * ```
 * 前 4 字节 == MAGIC_NUM(0x66677371)      -> LanShare 私有协议
 * 前 4 字节是大写含 "GET" 或 "POST" 的 ASCII -> HTTP 服务（Web 网页端）
 * 其它                                     -> 直接关闭连接
 * ```
 * 好处：一个端口同时提供「文件互传」和「浏览器访问」，用户只需记住一个地址/端口。
 *
 * ## ⚠️ 坑 1：`listen()` bind 失败会**静默换端口**
 * `TCPSocketServer.listen()` 的官方注释原文：
 *
 * > The server uses this API to perform the **bind**, **listen**, and **accept** operations.
 * > **If the bind operation fails, the system randomly allocates a port number.**
 *
 * 也就是说 **bind 失败既不抛异常也不返回错误码，而是静默换一个随机端口**。
 * 一旦 stop() 忘记调用 close()，端口就被旧实例一直占着，下一次 listen 必然 bind 失败，
 * 于是：界面照样显示 5856、`listen()` 照样 resolve、UDP 广播照样通，
 * 但 **没有任何外部设备能连上** —— 静默的假成功，最难查的一类故障。
 *
 * 因此本实现对 listen 之后**强制回读真实绑定端口**（getLocalAddress + getState），
 * 端口不符即判定失败并关闭套接字；另外 stop() 必须 `await server.close()`。
 *
 * ## ⚠️ 坑 2：`on('connect')` 必须在 `listen()` **成功之后**注册
 * SDK 对该方法的注释原文：
 *
 * > on(type: 'connect', callback: Callback<TCPSocketConnection>): void;
 * > **NOTE: This API can be called only after `listen` is successfully called.**
 *
 * 本文件第一版把注册放在 `listen` 之前（当时想的是「避免错过第一个连接」），
 * 与官方前置条件相反。后果是 accept 回调可能根本不触发 ——
 * 连接被内核排进 accept 队列却没人处理，客户端表现为「连上了但永远没有响应」。
 * 现已按官方要求改为**先 listen，再注册**。
 *
 * ## ⚠️ 坑 3：TCP 握手成功 **不代表** 应用层能收到连接
 * `connect()` 只要能完成 SYN/SYN-ACK/ACK 就会成功 —— 这由**内核**完成，
 * 与我们的 `on('connect')` 回调有没有触发**完全无关**。
 * 所以「本机自连 127.0.0.1 成功」是一个**假绿灯**：端口确实开着，但应用层可能是死的。
 *
 * 本文件的 `e2eSelfTest()` 因此改成**真端到端**：自连之后发一个真 HTTP 请求，
 * 要求**收到响应字节**，并且要求 accept 计数确实增加。三项都过才算通过。
 * 这样「端口开着但应用层不响应」这类故障会在自己的日志里现形，而不是等用户拿别的设备试。
 *
 * ## 鸿蒙侧映射
 *   java.net.ServerSocket.accept()          -> socket.constructTCPSocketServerInstance() + on('connect')
 *   Socket.getInputStream()                 -> TCPSocketConnection.on('message')
 *   Socket.getOutputStream().write()        -> TCPSocketConnection.send({ data: ArrayBuffer })
 *   ServerSocketChannel(非阻塞)             -> 不需要，TCPSocketServer 内部已并发处理多客户端
 */
import { socket } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { LanConfig } from '../core/LanConfig';
import { Log } from '../core/Logger';
import { ConnectionAdapter, SocketLike, TcpChannel } from './NativeSocket';

const TAG: string = 'LanTcpServer';

/**
 * 收发缓冲目标值 = 262144（SDK 上限，默认 8192）。
 * 与 LanClient 用同一档，收发两侧才对称。
 */
/**
 * 监听套接字的 SO_RCVBUF / SO_SNDBUF（accept 出来的连接会继承这两个值）。
 *
 * ★★ 5.1.21（vivi 决定）：**接收端也改成「不设」**，与发送端一致。
 *
 * 【历程（三次改动都是基于错误前提）】
 * - 5.0.58：`256KB → 4MB`，注释写「把接收窗口放大到一个块以上，纯赚」
 *   ⇒ **无效**：`4MB` 超 SDK 上限，按文档**静默回落 8192**（不是报错，毫无征兆）
 * - 5.1.16：`4MB → 262144`（合法顶格，至少比回落强 32 倍）
 * - 5.1.21：**干脆不设** ⇒ 与 `LanClient` 同策略，让内核自己做 TCP 自动调优。
 *
 * 【为什么「不设」比「顶格」更好】（与发送端同一个道理）
 * 显式 `setsockopt(SO_RCVBUF)` 会**关闭 Linux 内核的 TCP 窗口自动调优**。
 * 发送端已实测：不设 ⇒ 35.7 → 52.9MB/s（+48%）。
 * 接收端同理 —— 不设才能让内核按实际吞吐自动放大窗口。
 *
 * 【SDK 原文】`@ohos.net.socket.d.ts:260`（`TCPExtraOptions.sendBufferSize`）：
 *   > Size of the TX buffer, in bytes. **The value ranges from 0 to 262144.**
 *   > If this parameter is left unspecified or the unspecified value
 *   > **exceeds the value range, the default value 8192 is used.**
 *
 * 【回退】把 `TUNE_SERVER_BUFFERS` 改回 true 即恢复显式设值行为。
 *
 * ⚠️ 纯本机内核参数，**线上字节流一个都不变** ⇒ 对原版 Android / 1.35 / PC 全部照旧互通。
 * ⚠️ 若日后遇到 5.0.58 记录过的那个老问题（对端裸 `::send()` 把「部分发送」当硬错误
 *    ⇒ 中止文件改发 FS_CLOSE ⇒ 我方干等 60 秒），可把此开关改回 true 顶格 262144。
 */
const TUNE_BUFFER_SIZE: number = 262144;

/** ★ 5.1.21：是否显式设置收发缓冲。false = 不设（内核自动调优，与 LanClient 一致） */
/**
 * ★ 5.1.22（vivi 12:02 决定回退）：**接收端恢复显式设值**。
 *
 * 【为什么回退】5.1.21 改成「不设」后实测**接收速度毫无提升**（仍 ~50MB/s）
 *   ⇒ 瓶颈在**对端发送速度**，不在我方接收窗口 ⇒ 该改动**收益为零**。
 *   而它带着一个已知风险（记忆里 5.0.58 记录：接收窗口小会触发对端
 *   裸 `::send()` 的「部分发送」⇒ 改发 FS_CLOSE ⇒ 我方干等 60 秒）。
 *   ★ **没有收益的改动就是负担**，凭它占着风险没道理。
 *
 * 【取值】`TUNE_BUFFER_SIZE` 保持 **262144**（合法顶格，0~262144）。
 *   ⚠️ 绝不能填 4MB —— 超上限会**静默回落 8192**（5.0.58 那次白改）。
 */
const TUNE_SERVER_BUFFERS: boolean = true;

/** 前 4 字节的十六进制展示，仅用于日志 */
function hex4(b: Uint8Array): string {
  let s: string = '';
  for (let i = 0; i < b.length; i++) {
    s += b[i].toString(16).padStart(2, '0');
  }
  return s;
}

/** 前 4 字节的判定结果 */
export class ProtocolKind {
  /** LanShare 私有二进制协议 */
  static readonly MAGIC: number = 1;
  /** HTTP（浏览器网页端） */
  static readonly WEB: number = 2;
  /** 未知流量，直接断开 */
  static readonly UNKNOWN: number = 0;
}

/**
 * 一条已建立、且已完成协议分流的连接。
 * 业务处理器（私有协议 / HTTP）只跟这个抽象打交道，不直接碰 socket。
 */
export interface ChannelHandler {
  /**
   * 处理一条连接。
   *
   * ⚠️ **必须返回 Promise，而且调用方必须 await 它。**
   * 这不是风格问题：连接的生命周期由「处理完成」决定 —— 调用方在处理返回后
   * 才会关闭通道。如果这里只声明 `void`，调用方会认为「处理已经结束」而立刻
   * `close()`，而业务代码其实才刚开始读第一个字段。
   * 真机上踩过：表现就是「连上了但永远没有响应」，因为连接被自己的 accept 循环关掉了。
   *
   * @param channel 已分流后的通道，`head` 是判定协议时读走的前 4 字节
   *                （HTTP 处理器需要把它拼回请求流里）
   */
  handle(channel: TcpChannel, kind: number, head: Uint8Array): Promise<void>;
}

/** 启动结果，用于把失败原因原样带到 UI（而不是只给一个 false） */
export class ListenResult {
  ok: boolean = false;
  /** 实际绑定到的端口。-1 表示未知 */
  boundPort: number = -1;
  /** 失败原因 / 成功备注，直接展示给用户 */
  detail: string = '';
  /** 端到端自检失败时的具体结论，成功时为空串 */
  selfTestDetail: string = '';
}

/** 端到端自检的逐项结果 */
class SelfTestResult {
  /** 自连 127.0.0.1 是否成功（只证明内核在听） */
  tcpConnected: boolean = false;
  /** accept 回调是否真的触发（证明应用层拿到了连接） */
  acceptFired: boolean = false;
  /** 收到了多少字节的 HTTP 响应 */
  bytesBack: number = 0;

  get ok(): boolean {
    return this.tcpConnected && this.acceptFired && this.bytesBack > 0;
  }

  /** 按「最先失败的一环」给出结论 —— 这一句就是排查结论，不是套话 */
  describe(port: number): string {
    if (!this.tcpConnected) {
      return `本机都连不上 127.0.0.1:${port}，监听未真正生效`;
    }
    if (!this.acceptFired) {
      return `端口在听，但应用层收不到连接（accept 回调未触发）——外部设备同样连不上`;
    }
    if (this.bytesBack === 0) {
      return `连接已收到，但服务端没有回任何数据（HTTP 路由没响应）`;
    }
    return '';
  }
}

export class LanTcpServer {
  private server: socket.TCPSocketServer | null = null;
  private handler: ChannelHandler | null = null;
  private port: number = LanConfig.DEFAULT_FILE_SERVER_PORT;
  private running: boolean = false;
  /** 实际绑定端口，由 getLocalAddress() 回读，可能 != port（静默换端口时） */
  private boundPort: number = -1;
  private activeConnections: number = 0;
  /** 累计 accept 次数。自检与排障都靠它判断「应用层到底有没有收到连接」 */
  private acceptCount: number = 0;
  /** 跟踪活跃通道，停服时逐个关闭，避免留下半开连接 */
  private channels: Set<TcpChannel> = new Set<TcpChannel>();
  private selfTestPassed: boolean = false;
  private selfTestDetail: string = '';
  /** UI 日志下沉口。socket 层的关键事件必须能被用户看到，否则真机只能靠猜 */
  private logSink: ((line: string) => void) | null = null;

  /** 设置业务处理器（HTTP + 私有协议）。必须在 start() 之前调用 */
  setHandler(handler: ChannelHandler): void {
    this.handler = handler;
  }

  /** 设置 UI 日志下沉口。可选，未设置时只走 hilog */
  setLogSink(sink: (line: string) => void): void {
    this.logSink = sink;
  }

  private log(line: string): void {
    Log.i(TAG, line);
    const sink: ((line: string) => void) | null = this.logSink;
    if (sink !== null) {
      sink(line);
    }
  }

  setPort(port: number): void {
    this.port = port;
  }

  get connectionCount(): number {
    return this.activeConnections;
  }

  get isRunning(): boolean {
    return this.running;
  }

  /** 累计 accept 次数 */
  get accepted(): number {
    return this.acceptCount;
  }

  /** 真实监听端口。UI 应展示它而不是配置值 */
  get listeningPort(): number {
    return this.boundPort;
  }

  /** 端到端自检是否通过 —— 证明「accept + 业务响应」整条链路可用 */
  get isSelfTestPassed(): boolean {
    return this.selfTestPassed;
  }

  get selfTestFailure(): string {
    return this.selfTestDetail;
  }

  async start(port: number = this.port): Promise<ListenResult> {
    const result: ListenResult = new ListenResult();
    if (this.running) {
      result.ok = true;
      result.boundPort = this.boundPort;
      result.detail = '已在运行';
      return result;
    }
    this.port = port;
    this.boundPort = -1;
    this.selfTestPassed = false;
    this.selfTestDetail = '';
    this.acceptCount = 0;

    try {
      const srv: socket.TCPSocketServer = socket.constructTCPSocketServerInstance();
      this.server = srv;

      // ---- 1. 先 listen ----
      // 官方前置条件：on('connect') 只能在 listen 成功之后调用。
      // （第一版写反了，见文件头「坑 2」。）
      const addr: socket.NetAddress = { address: '0.0.0.0', port: port, family: 1 };
      await srv.listen(addr);

      // ---- 1.5 监听套接字调优 ----
      // ⚠️ 只能设在 **listen 之后**：SDK 明确要求 setExtraOptions 在 bind 成功后调用，
      //    而 `listen()` 内部才做 bind。放在 listen 之前会抛。
      // ⚠️ 为什么监听套接字也要设：accept 出来的 `TCPSocketConnection` **没有**
      //    setExtraOptions 接口（翻 SDK 的接口定义，它只有 send/close/on/getRemoteAddress），
      //    所以接收侧拿到的连接没法单独调。好在 Linux 语义下 accept 的连接会
      //    **继承 listen fd 的 SO_RCVBUF / SO_SNDBUF**，这是接收侧唯一能影响缓冲的入口。
      //    默认 8192 的接收缓冲意味着对端每发 8KB 就要停一次，吞吐被 RTT 卡死。
      // TCP_NODELAY 不会被继承，但设在监听套接字上无害；发送侧（LanClient）那边设过了。
      await LanTcpServer.applyTuning(srv);

      // ---- 2. listen 成功后再注册 accept 回调 ----
      srv.on('connect', (client: socket.TCPSocketConnection) => {
        this.acceptCount += 1;
        this.onConnect(client);
      });
      srv.on('error', (e: BusinessError) => {
        this.log(`监听套接字错误 ${e.code} ${e.message}`);
      });

      // ---- 3. 强制校验真实端口（见文件头「坑 1」：bind 失败会静默换端口）----
      const verify: string = await this.verifyBound(port);
      if (verify.length > 0) {
        result.ok = false;
        result.detail = verify;
        await this.closeServer();
        return result;
      }

      this.running = true;
      result.ok = true;
      result.boundPort = this.boundPort;

      // ---- 4. 端到端自检 ----
      // 不是「端口开没开」，而是「外部连进来能不能拿到响应」。
      // 见文件头「坑 3」：只测 TCP 握手会给假绿灯。
      const st: SelfTestResult = await this.e2eSelfTest(this.boundPort);
      this.selfTestPassed = st.ok;
      this.selfTestDetail = st.describe(this.boundPort);
      result.selfTestDetail = this.selfTestDetail;

      if (st.ok) {
        result.detail = `监听 0.0.0.0:${this.boundPort}，端到端自检通过`;
      } else {
        result.detail = `监听 0.0.0.0:${this.boundPort}，但自检未通过：${this.selfTestDetail}`;
      }
      return result;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      // 2303198 = Address already in use；2303199 = Cannot assign requested address
      result.ok = false;
      result.detail = `端口 ${port} 监听失败 ${err.code} ${err.message}`;
      await this.closeServer();
      return result;
    }
  }

  /**
   * 回读真实绑定端口与状态。
   * @returns 空串表示校验通过；非空为失败原因
   */
  private async verifyBound(expected: number): Promise<string> {
    if (this.server === null) {
      return '内部错误：server 为空';
    }
    let actualPort: number = -1;
    try {
      const local: socket.NetAddress = await this.server.getLocalAddress();
      actualPort = local.port !== undefined ? local.port : -1;
      this.boundPort = actualPort;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      // getLocalAddress 万一不可用，不让整条链路失败，但要留痕
      Log.w(TAG, `回读绑定地址失败（继续）: ${err.code} ${err.message}`);
    }

    if (actualPort >= 0 && actualPort !== expected) {
      return `端口 ${expected} 未绑定成功，系统实际分配了 ${actualPort}（通常是被占用），已中止`;
    }

    try {
      const state: socket.SocketStateBase = await this.server.getState();
      if (!state.isBound || state.isClose) {
        return `监听状态异常: isBound=${state.isBound} isClose=${state.isClose}`;
      }
    } catch (e) {
      Log.w(TAG, '读取 socket 状态失败（继续）');
    }
    return '';
  }

  /**
   * 监听套接字调优。与 LanClient 同理：只动本机内核参数，线上字节流一个都不变，
   * 因此对端是原版 Android / Windows / 1.35 都照样互通。
   * 失败只告警不中断 —— 这是「有则更快」，不是功能项。
   */
  private static async applyTuning(srv: socket.TCPSocketServer): Promise<void> {
    try {
      if (TUNE_SERVER_BUFFERS) {
        await srv.setExtraOptions({
          TCPNoDelay: true,
          sendBufferSize: TUNE_BUFFER_SIZE,
          receiveBufferSize: TUNE_BUFFER_SIZE
        } as socket.TCPExtraOptions);
      } else {
        // ★★ 5.1.21：**只设 TCPNoDelay，绝不设 sendBufferSize / receiveBufferSize。**
        //   显式 setsockopt 会关闭内核的 TCP 窗口自动调优（发送端已实测 +48%）。
        //   且旧值 4MB 超 SDK 上限 ⇒ 静默回落 8192，压根没生效过。
        await srv.setExtraOptions({
          TCPNoDelay: true
        } as socket.TCPExtraOptions);
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `监听套接字调优未生效（沿用系统默认）: ${err.code}`);
    }
  }

  /**
   * 端到端自检：自连 127.0.0.1，发一个真 HTTP 请求，要求**收到响应字节**。
   *
   * 为什么不能只 `connect()` 就算通过：
   * TCP 三次握手由内核完成，即使应用层从不调用 accept，`connect()` 也会成功。
   * 所以「连得上」和「有人处理」是两件事，必须分开验证。
   *
   * 三项判据（任一不过都会给出具体结论）：
   *   1. TCP 能连上        -> 内核层面端口是开的
   *   2. accept 回调触发   -> 应用层真的拿到了这条连接
   *   3. 收到响应字节      -> 业务（HTTP 路由）真的在干活
   */
  private async e2eSelfTest(port: number): Promise<SelfTestResult> {
    const st: SelfTestResult = new SelfTestResult();
    let probe: socket.TCPSocket | null = null;
    const acceptBefore: number = this.acceptCount;
    let got: Uint8Array = new Uint8Array(0);

    try {
      probe = socket.constructTCPSocketInstance();
      probe.on('message', (info: socket.SocketMessageInfo) => {
        got = TcpChannel.concat(got, new Uint8Array(info.message));
      });
      await probe.connect({
        address: { address: '127.0.0.1', port: port, family: 1 },
        timeout: 3000
      });
      st.tcpConnected = true;

      // HTTP/1.0 + Connection: close，让服务端写完就收，自检不留下 keep-alive 连接
      await probe.send({
        data: 'GET / HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n'
      });

      // 轮询等响应。用轮询而不是回调 Promise，是为了让超时路径简单可读
      const deadline: number = Date.now() + 5000;
      while (got.length === 0 && Date.now() < deadline) {
        await LanTcpServer.sleep(100);
      }
      st.bytesBack = got.length;
      st.acceptFired = this.acceptCount > acceptBefore;
      return st;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `端到端自检失败: ${err.code} ${err.message}`);
      st.acceptFired = this.acceptCount > acceptBefore;
      return st;
    } finally {
      if (probe !== null) {
        try {
          probe.off('message');
          await probe.close();
        } catch (e) {
          // 已关闭，忽略
        }
      }
    }
  }

  private static sleep(ms: number): Promise<void> {
    return new Promise<void>((resolve: () => void) => {
      setTimeout(resolve, ms);
    });
  }

  private onConnect(client: socket.TCPSocketConnection): void {
    this.activeConnections += 1;
    const adapter: SocketLike = new ConnectionAdapter(client);
    // connect 事件不带来源地址，异步取一次；HTTP/私有协议本身不依赖它，
    // 但日志和「已连接设备」列表需要。
    const placeholder: TcpChannel = new TcpChannel(adapter, '', 0);
    this.channels.add(placeholder);

    client.getRemoteAddress().then((remote: socket.NetAddress) => {
      // NetAddress.port 在类型上是可选的，实际有值；给个兜底免得类型报错
      const rp: number = remote.port !== undefined ? remote.port : 0;
      placeholder.setRemote(remote.address, rp);
      this.log(`新连接来自 ${remote.address}:${rp}`);
    }).catch((e: BusinessError) => {
      this.log(`新连接（取对端地址失败 ${e.code}）`);
    });

    this.dispatch(placeholder, client).then(() => {
      // ⚠️ WebSocket 升级成功后所有权已转给会话层（detached）。
      // 那是长连接，`handle()` 返回只代表「HTTP 职责结束」，
      // 这里若照常 close，会把刚建立的 WS 会话当场掐死。
      if (!placeholder.detached) {
        placeholder.close();
      }
    }).catch((e: Error) => {
      Log.w(TAG, `连接处理异常: ${e.message}`);
      placeholder.close();
    }).finally(() => {
      this.channels.delete(placeholder);
      this.activeConnections = this.activeConnections > 0 ? this.activeConnections - 1 : 0;
    });
  }

  /**
   * 协议分流：读前 4 字节，判定是私有协议还是 HTTP。
   * 判定逻辑与 LANService.java 1838-1857 完全一致。
   */
  private async dispatch(channel: TcpChannel, client: socket.TCPSocketConnection): Promise<void> {
    // 15s 足够正常客户端发完首包；自检那条连接会正常走完，不留超时噪声
    const head: Uint8Array | null = await channel.readExactly(4, 15000);
    if (head === null) {
      // 只有真收到过字节又没凑够 4 个才值得报，纯粹的端口探测不打扰用户
      if (channel.available > 0) {
        this.log('连接字节数不足 4，已断开');
      }
      return;
    }

    const magic: number =
      ((head[0] << 24) | (head[1] << 16) | (head[2] << 8) | head[3]) | 0;

    let kind: number = ProtocolKind.UNKNOWN;
    if (magic === LanConfig.MAGIC_NUM) {
      kind = ProtocolKind.MAGIC;
    } else {
      // 原实现是 String(magicBytes).toUpperCase().contains("GET"/"POST")
      // 只有 4 字节，能匹配到的就是 "GET " 和 "POST"
      const ascii: string = String.fromCharCode(head[0], head[1], head[2], head[3]).toUpperCase();
      if (ascii.includes('GET') || ascii.includes('POST')) {
        kind = ProtocolKind.WEB;
      }
    }

    if (kind === ProtocolKind.UNKNOWN) {
      this.log(`未知协议流量，已断开（首 4 字节 ${hex4(head)}）`);
      return;
    }

    const kindName: string = kind === ProtocolKind.WEB ? '网页(HTTP)' : 'LanShare 私有协议';
    this.log(`已分流为${kindName}`);

    if (this.handler === null) {
      Log.e(TAG, '未设置 ChannelHandler，无法处理连接');
      return;
    }

    // HTTP 处理器需要完整请求行，把 4 字节还回去。
    // ★ 必须 await：处理返回意味着这条连接的业务已经做完，
    //   调用方随后才会关闭通道（见 ChannelHandler.handle 的说明）。
    await this.handler.handle(channel, kind, head);
    this.log('连接处理结束');
  }

  /** 关闭底层 TCPSocketServer 并等待完成 */
  private async closeServer(): Promise<void> {
    const srv: socket.TCPSocketServer | null = this.server;
    this.server = null;
    this.running = false;
    this.boundPort = -1;
    this.selfTestPassed = false;
    if (srv === null) {
      return;
    }
    try {
      srv.off('connect');
      srv.off('error');
    } catch (e) {
      // ignore
    }
    try {
      await srv.close();
      this.log('监听套接字已关闭，端口已释放');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `关闭监听套接字异常: ${err.code} ${err.message}`);
    }
  }

  /**
   * 停止服务。**必须 await**，否则端口可能还没释放就再次 start，
   * 下一次 listen 会 bind 失败 -> 静默换随机端口 -> 假成功。
   */
  async stop(): Promise<void> {
    // 先断开所有活跃连接，再关监听
    const alive: TcpChannel[] = [];
    this.channels.forEach((c: TcpChannel) => {
      alive.push(c);
    });
    this.channels.clear();
    for (let i = 0; i < alive.length; i++) {
      await alive[i].closeAsync();
    }
    this.activeConnections = 0;
    await this.closeServer();
    Log.i(TAG, 'TCP 服务已停止');
  }

  /**
   * 手动再跑一次端到端自检。UI 上给一个「网络自检」按钮，
   * 用户不用重启服务就能拿到当前的真实结论。
   */
  async runSelfTest(): Promise<string> {
    if (!this.running || this.boundPort < 0) {
      return '服务未启动，无法自检';
    }
    const st: SelfTestResult = await this.e2eSelfTest(this.boundPort);
    this.selfTestPassed = st.ok;
    this.selfTestDetail = st.describe(this.boundPort);
    const msg: string = st.ok
      ? `自检通过：HTTP 响应 ${st.bytesBack} 字节，accept ${this.acceptCount} 次`
      : `自检未通过：${this.selfTestDetail}`;
    this.log(msg);
    return msg;
  }
}
