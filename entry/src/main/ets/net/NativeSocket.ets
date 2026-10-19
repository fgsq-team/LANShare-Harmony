/**
 * 原生 socket 抽象层 —— 让「服务端接进来的连接」和「我们主动连出去的连接」
 * 共用同一套「推送模型 -> 拉取模型」的缓冲逻辑。
 *
 * ## 为什么需要这层
 * HarmonyOS 的 socket API 有两种形状：
 *   socket.TCPSocketConnection  服务端 accept 到的连接（bind 路由自动读取 remoteInfo）
 *   socket.TCPSocket            客户端主动 connect 的连接（无 remoteInfo，要自己查）
 * 两者的 send/on('message')/close 语义一样但类型不同，业务代码不该关心差异。
 * 所以这里定义 SocketLike，由两个 Adapter 适配，业务只跟 TcpChannel 打交道。
 *
 * ## 为什么是「拉取模型」
 * 原 Android 代码是阻塞 I/O（IOUtil.read 循环读满），平移到事件回调模型后
 * 最大的坑就是「一次 message 回调不等于一次完整业务包」——TCP 是字节流，
 * 分包完全由内核和网络决定。
 * TcpChannel 把 on('message') 的碎片累积起来，对外提供
 * readExactly(n) —— 语义等价于 Java 的「循环读满 n 字节」。
 */
import { socket } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { Log } from '../core/Logger';

const TAG: string = 'TcpChannel';

/**
 * 「攒够这么多字节才唤醒等待者」。
 *
 * 背景：实测做**接收方**时吞吐明显低于做发送方（约 2/3）。
 * 原因是 TCP 是字节流，内核每次 `on('message')` 只递一小块（受套接字接收缓冲影响，
 * 小到 8KB 量级）。原来每来一小块就唤醒一次读等待者：1 MB 的分片要唤醒上百次，
 * 每次都是一次事件循环切换 + 一次 `available` 检查 + 一次重新挂起。
 * 这些空转把吞吐吃掉一大截。
 *
 * 现在改成攒够 256KB 再唤醒，1 MB 分片只需 4 次。
 */
const WAKE_THRESHOLD: number = 256 * 1024;
/**
 * 数据来了但没攒够阈值时的兜底唤醒延迟。
 * 只在「流量很小或已到末尾」时才真正起作用（连续大流量会先撞上阈值），
 * 2ms 对信令交互无感。
 */
const WAKE_DELAY_MS: number = 2;

/**
 * ★★ 5.1.32：空闲等待的兜底检测间隔（毫秒）。
 *
 * 【为什么需要它】`waitForData` 原来**每个等待者各挂一个 `setTimeout(timeoutMs)`**。
 *   上传 645MB = 2240 块 ⇒ 每块一次「建 30 秒定时器 → 数据到 → clearTimeout」。
 *   定时器对象虽被清掉，但**创建与清除本身都要走主线程定时器管理器**，
 *   2240 次 × 6 并发连接 ≈ 1.3 万次操作全部压在同一个消息队列上。
 *
 * 【⚠️ 2026-10-03 修正】本段原写「真机后果：主线程并未冻结（hbWorstLag
 *   仅 631ms），看门狗判活任务被插队饿死」—— **该结论已被推翻**。
 *   ① 「hbWorstLag 631ms ⇒ 主线程未冻结」是**幸存者偏差**：该心跳本身
 *      从主线程打出，主线程真卡死时它根本打不出来（只证明卡死前不忙）。
 *   ② 真正的病根是 `MultipartStream.indexOfSeq` 逐字节扫描 53ms/块
 *      （6 并发 ⇒ 主线程饱和 ⇒ 渲染帧饿死 ⇒ THREAD_BLOCK_6S）。
 *   ★ 本单例定时器**本身仍是正确优化**（O(块数)→O(1)），只是理由换了。
 *
 * 【做法】改为**连接级单例定时器**：无论多少等待者，最多只有一个
 *   周期定时器在跑，且**只在真的有等待者时才启动**（空闲连接零开销）。
 *   定时器数量从 O(块数) 降到 O(1)。
 */
const WAIT_IDLE_TICK_MS: number = 250;

/**
 * 一条双向字节通道的最小能力集。
 * 两个实现见本文件底部的 ConnectionAdapter / ClientAdapter。
 */
export interface SocketLike {
  /** 注册数据到达 / 连接关闭回调。实现方需自行保存回调引用以便 unbind */
  bind(onMessage: (chunk: Uint8Array) => void, onClose: () => void): void;
  /** 注销回调。必须在 close 之前调用，否则连接对象会被回调闭包引用住 */
  unbind(): void;
  /** 发送一段字节。实现方保证顺序由调用方串行化 */
  write(data: ArrayBuffer): Promise<void>;
  /** 关闭底层套接字 */
  shutdown(): Promise<void>;
}

/** 包装服务端 accept 到的连接（socket.TCPSocketConnection） */
export class ConnectionAdapter implements SocketLike {
  private conn: socket.TCPSocketConnection;
  private msgCb: ((info: socket.SocketMessageInfo) => void) | null = null;
  private closeCb: (() => void) | null = null;

  constructor(conn: socket.TCPSocketConnection) {
    this.conn = conn;
  }

  bind(onMessage: (chunk: Uint8Array) => void, onClose: () => void): void {
    this.msgCb = (info: socket.SocketMessageInfo) => {
      onMessage(new Uint8Array(info.message));
    };
    this.closeCb = () => {
      onClose();
    };
    this.conn.on('message', this.msgCb);
    this.conn.on('close', this.closeCb);
  }

  unbind(): void {
    try {
      if (this.msgCb !== null) {
        this.conn.off('message', this.msgCb);
      }
      if (this.closeCb !== null) {
        this.conn.off('close', this.closeCb);
      }
    } catch (e) {
      // 连接已销毁时 off 可能抛，忽略
    }
    this.msgCb = null;
    this.closeCb = null;
  }

  async write(data: ArrayBuffer): Promise<void> {
    await this.conn.send({ data: data });
  }

  async shutdown(): Promise<void> {
    await this.conn.close();
  }
}

/** 包装客户端主动建立的连接（socket.TCPSocket） */
export class ClientAdapter implements SocketLike {
  private sock: socket.TCPSocket;
  private msgCb: ((info: socket.SocketMessageInfo) => void) | null = null;
  private closeCb: (() => void) | null = null;

  constructor(sock: socket.TCPSocket) {
    this.sock = sock;
  }

  bind(onMessage: (chunk: Uint8Array) => void, onClose: () => void): void {
    this.msgCb = (info: socket.SocketMessageInfo) => {
      onMessage(new Uint8Array(info.message));
    };
    this.closeCb = () => {
      onClose();
    };
    this.sock.on('message', this.msgCb);
    this.sock.on('close', this.closeCb);
  }

  unbind(): void {
    try {
      if (this.msgCb !== null) {
        this.sock.off('message', this.msgCb);
      }
      if (this.closeCb !== null) {
        this.sock.off('close', this.closeCb);
      }
    } catch (e) {
      // ignore
    }
    this.msgCb = null;
    this.closeCb = null;
  }

  async write(data: ArrayBuffer): Promise<void> {
    await this.sock.send({ data: data });
  }

  async shutdown(): Promise<void> {
    await this.sock.close();
  }
}

/**
 * 一条已完成协议分流的连接通道。
 * 提供阻塞式读取（readExactly）与串行化发送，业务层不感知底层 socket 类型。
 */
export class TcpChannel {
  private sock: SocketLike;
  /**
   * 接收缓冲。用「滑动窗口」而不是每来一片就 concat 出一个新数组。
   *
   * ⚠️ 原实现是 `pending = concat(pending, chunk)` —— 每收到一个分片都要把
   * **已有数据整份复制一遍**。上传 32 MiB 时数据分片约 500 次，
   * 累计复制量 O(n²) ≈ 8 GiB，真机实测把有效吞吐压到 **0.62 MiB/s**
   * （32 MiB 用掉 51.5 s，见 tests/live-probe/upload_probe.mjs）。
   * 一个千兆局域网里跑出 5 Mbps 的观感，就是这么来的。
   *
   * 现在改成单块 buf + [head, tail) 有效区间：
   *   - 追加：空间不足时先「压实」（copyWithin 把有效数据挪到 0），再按需倍增；
   *   - 消费：只推进 head，不搬数据；
   *   - 均摊每次追加 O(1)，且不产生中间垃圾对象。
   */
  private buf: Uint8Array = new Uint8Array(0);
  /** buf 中有效数据的起点（含） */
  private head: number = 0;
  /** buf 中有效数据的终点（不含） */
  private tail: number = 0;
  /** 等待数据的唤醒器（read 无数据时排队） */
  private waiters: Array<() => void> = [];
  /** 攒不够阈值时的兜底唤醒定时器句柄，-1 表示没挂 */
  private wakeTimer: number = -1;
  /** ★ 5.1.32：连接级「空闲唤醒」单例定时器（-1 = 未启动）。
   *  多个等待者共享同一个，数量与块数无关 ⇒ 不再塞爆消息队列。 */
  private idleTimer: number = -1;
  private closed: boolean = false;
  /** 所有权已转移给别的处理器（见 detached getter） */
  private detachedV: boolean = false;
  /** 发送队列尾指针，保证严格串行（并发 send 会打乱分片顺序） */
  private sendChain: Promise<void> = Promise.resolve();

  private remoteIpV: string;
  private remotePortV: number;

  constructor(sock: SocketLike, remoteIp: string, remotePort: number) {
    this.sock = sock;
    this.remoteIpV = remoteIp;
    this.remotePortV = remotePort;

    sock.bind((chunk: Uint8Array) => {
      if (chunk.length === 0) {
        return;
      }
      this.append(chunk);
      this.scheduleWake();
    }, () => {
      this.closed = true;
      // 连接已关：没有后续数据了，必须**立刻**唤醒，不能再等攒够
      this.flushWake();
    });
  }

  /**
   * 唤醒策略：够阈值就立刻唤醒，否则挂一个短定时器兜底。
   *
   * 为什么不能简单延迟固定时间：连续大流量下会白白多等 2ms×N；
   * 为什么不能只靠阈值：小包（4 字节命令字）永远攒不够，会卡到超时。
   * 所以两者都要，阈值优先。
   */
  private scheduleWake(): void {
    if (this.available >= WAKE_THRESHOLD) {
      this.flushWake();
      return;
    }
    if (this.wakeTimer >= 0) {
      return; // 已有兜底定时器在跑
    }
    this.wakeTimer = setTimeout(() => {
      this.wakeTimer = -1;
      this.flushWake();
    }, WAKE_DELAY_MS);
  }

  private flushWake(): void {
    if (this.wakeTimer >= 0) {
      clearTimeout(this.wakeTimer);
      this.wakeTimer = -1;
    }
    // ★ 5.1.32：数据到了 ⇒ 等待者会被唤醒；若唤醒后没有新等待者，
    //   单例 ticker 会在下一次 tick 自行停掉（见 ensureIdleTicker）。
    this.wakeAll();
  }

  get remoteIp(): string {
    return this.remoteIpV;
  }

  get remotePort(): number {
    return this.remotePortV;
  }

  /**
   * 回填对端地址。
   * 服务端 accept 出来的连接在 `on('connect')` 那一刻拿不到来源地址，
   * 只能异步调 `getRemoteAddress()`；通道要先建出来才能开始收字节，
   * 所以允许事后补。业务侧不依赖它做协议判断，只有日志。
   */
  setRemote(ip: string, port: number): void {
    this.remoteIpV = ip;
    this.remotePortV = port;
  }

  private wakeAll(): void {
    const waiting: Array<() => void> = this.waiters;
    this.waiters = [];
    for (let i = 0; i < waiting.length; i++) {
      waiting[i]();
    }
  }

  /**
   * 把 head 字节放回缓冲区头部。
   * 协议分流时前 4 字节已被读走，HTTP 处理器需要它们来解析请求行。
   */
  unshift(head: Uint8Array): void {
    if (head.length === 0) {
      return;
    }
    this.prepend(head);
  }

  /** 追加一段到有效区间尾部 */
  private append(chunk: Uint8Array): void {
    // 末尾空间够就直接写
    if (this.tail + chunk.length > this.buf.length) {
      // 先压实：把有效数据挪到头部，让出后面的连续空间
      if (this.head > 0) {
        this.buf.copyWithin(0, this.head, this.tail);
        this.tail -= this.head;
        this.head = 0;
      }
      // 压实后还不够，才扩容量（倍增，避免频繁 alloc）
      if (this.tail + chunk.length > this.buf.length) {
        let cap: number = this.buf.length > 0 ? this.buf.length * 2 : 8192;
        while (cap < this.tail + chunk.length) {
          cap *= 2;
        }
        const nb: Uint8Array = new Uint8Array(cap);
        nb.set(this.buf.subarray(0, this.tail), 0);
        this.buf = nb;
      }
    }
    this.buf.set(chunk, this.tail);
    this.tail += chunk.length;
  }

  /** 前插一段（unshift 用）。数据量很小，直接压实后腾出头部空间 */
  private prepend(chunk: Uint8Array): void {
    const avail: number = this.tail - this.head;
    if (this.head < chunk.length) {
      // 头部空间不足 → 整体右移有效数据
      const need: number = avail + chunk.length;
      if (need > this.buf.length) {
        let cap: number = this.buf.length > 0 ? this.buf.length * 2 : 8192;
        while (cap < need) {
          cap *= 2;
        }
        const nb: Uint8Array = new Uint8Array(cap);
        nb.set(this.buf.subarray(this.head, this.tail), chunk.length);
        this.buf = nb;
      } else {
        this.buf.copyWithin(chunk.length, this.head, this.tail);
      }
      this.head = 0;
      this.tail = need;
    } else {
      this.head -= chunk.length;
    }
    this.buf.set(chunk, this.head);
  }

  /** 已缓冲但未消费的字节数 */
  get available(): number {
    return this.tail - this.head;
  }

  get isClosed(): boolean {
    return this.closed;
  }

  /**
   * 所有权是否已被别的处理器接管（目前只有 WebSocket 会话层）。
   *
   * HTTP 是「处理完即关」的短连接模型，所以 accept 循环在 `handle()` 返回后
   * 会无条件 close。但 WebSocket 升级成功后 `HttpRouter.serve()` 同样会返回 ——
   * 而它是一条**长连接**，关掉就等于把刚建立的会话掐死
   * （浏览器侧表现为立刻 onclose，页面弹「连接断开」）。
   *
   * 所以由接管方显式打标，accept 循环据此放过这条连接。
   */
  get detached(): boolean {
    return this.detachedV;
  }

  /** 声明该连接已被其它处理器接管，accept 循环不要再 close 它 */
  markDetached(): void {
    this.detachedV = true;
  }

  /**
   * 阻塞直到至少收到 need 个字节，返回这 need 个字节。
   * 连接关闭或超时时返回 null。
   *
   * 对应 Java 的 `IOUtil.read(is, buf, off, len)`（循环读满）。
   */
  async readExactly(need: number, timeoutMs: number = 30000): Promise<Uint8Array | null> {
    if (need === 0) {
      return new Uint8Array(0);
    }
    const deadline: number = Date.now() + timeoutMs;
    while (this.available < need) {
      if (this.closed) {
        return null;
      }
      const remain: number = deadline - Date.now();
      if (remain <= 0) {
        Log.w(TAG, `readExactly 超时: 需要 ${need}，现有 ${this.available}`);
        return null;
      }
      await this.waitForData(remain);
    }
    const out: Uint8Array = this.buf.slice(this.head, this.head + need);
    this.head += need;
    this.compactIfIdle();
    return out;
  }

  /**
   * 取走当前已缓冲的**最多** maxBytes 字节 —— 「有多少给多少」。
   *
   * 与 readExactly 的区别：不追求读满，拿到 ≥1 字节就立刻返回。
   * 大 body 的流式落盘靠它：如果每块都要求读满 64 KiB 才返回，
   * 接收方就得把数据一直堆在内存里等对端把最后一块补齐，
   * 上传几百 MB 时会直接把内存打爆。
   *
   * @returns 字节块；连接关闭或超时且无数据时返回 null
   */
  async readSome(maxBytes: number, timeoutMs: number = 30000): Promise<Uint8Array | null> {
    if (maxBytes <= 0) {
      return new Uint8Array(0);
    }
    const deadline: number = Date.now() + timeoutMs;
    while (this.available === 0) {
      if (this.closed) {
        return null;
      }
      const remain: number = deadline - Date.now();
      if (remain <= 0) {
        return null;
      }
      await this.waitForData(remain);
    }
    const n: number = Math.min(this.available, maxBytes);
    const out: Uint8Array = this.buf.slice(this.head, this.head + n);
    this.head += n;
    this.compactIfIdle();
    return out;
  }

  /**
   * 缓冲被取空时把指针归零，并在大缓冲用完后释放内存。
   * 不释放的话，一次 500 MB 上传会在 buf 里长期留着一块巨型 Uint8Array，
   * 后续所有小请求（网页轮询等）都跟着吃这份内存。
   */
  private compactIfIdle(): void {
    if (this.head === this.tail) {
      this.head = 0;
      this.tail = 0;
      if (this.buf.length > 1024 * 1024) {
        this.buf = new Uint8Array(0);
      }
    }
  }

  /**
   * 等到有新数据、连接关闭或超时。
   *
   * ⚠️ 定时器必须显式 clear：早期版本数据先到时只 resolve 不 clearTimeout，
   * 于是每次「等数据」都在事件循环里留下一个 15~60 秒的僵尸定时器。
   * 上传一个几十万次分片的文件，就是在堆几万个待触发的 timer ——
   * 既拖慢事件循环，也让内存居高不下。
   */
  private waitForData(timeoutMs: number): Promise<void> {
    // ★★ 5.1.32：**不再每个等待者各挂一个 `setTimeout`**。
    //
    // 【旧写法的问题】每块数据都要「建一个 30s 定时器 → 数据到 → clear」。
    //   645MB / 256KB = 2240 块 × 6 并发连接 ≈ 1.3 万次定时器增删，
    //   全部走主线程定时器管理器 ⇒ 加重队列负载。
    // ⚠️ 原注释写「主线程未冻结（hbWorstLag 631ms）却仍被 THREAD_BLOCK_6S
    //   强杀 ⇒ 判活任务饿死」—— 该推理**错误**（幸存者偏差，见上）。
    //   真正的卡死点是 `MultipartStream.indexOfSeq` 的 53ms/块扫描。
    //
    // 【新写法】超时**不在这里**判定，改由调用方（`readSome`/`readExactly`）
    //   自己的 `deadline` 循环裁决；这里只负责「有新数据/连接关闭/周期 tick」时唤醒。
    //   定时器改为**连接级单例**：`ensureIdleTicker()` 保证最多一个在跑，
    //   且没有等待者时自动停 ⇒ 空闲连接零定时器。
    //
    // ⚠️ `timeoutMs` 保留在签名里是为了兼容调用方与**兜底**：
    //   若单例定时器的周期（`WAIT_IDLE_TICK_MS`）比 `timeoutMs` 还大，
    //   则用 `timeoutMs` 作为本次的唤醒间隔，保证不会比原来更迟钝。
    return new Promise<void>((resolve: () => void) => {
      this.waiters.push(resolve);
      this.ensureIdleTicker(timeoutMs);
    });
  }

  /**
   * 确保有一个「空闲唤醒」定时器在跑。★ 连接级单例，与等待者数量无关。
   *
   * 这是 5.1.32 修法的核心：把 `setTimeout` 的**创建次数从 O(块数) 降到 O(1)**。
   */
  private ensureIdleTicker(timeoutMs: number): void {
    if (this.idleTimer >= 0) {
      return; // 已有单例在跑，所有等待者共享
    }
    const period: number = timeoutMs > 0 && timeoutMs < WAIT_IDLE_TICK_MS
      ? timeoutMs
      : WAIT_IDLE_TICK_MS;
    this.idleTimer = setInterval(() => {
      if (this.waiters.length === 0) {
        // 没有等待者了 ⇒ 停掉自己，空闲连接不留定时器
        this.stopIdleTicker();
        return;
      }
      // 周期唤醒：让调用方的 deadline 循环有机会重新检查超时
      this.wakeAll();
    }, period);
  }

  private stopIdleTicker(): void {
    if (this.idleTimer >= 0) {
      clearInterval(this.idleTimer);
      this.idleTimer = -1;
    }
  }

  /** 发送全部字节。串行化，保证调用顺序 = 线上顺序 */
  send(data: Uint8Array): Promise<void> {
    if (data.length === 0) {
      return this.sendChain;
    }
    const task: () => Promise<void> = async () => {
      if (this.closed) {
        return;
      }
      try {
        await this.sock.write(TcpChannel.toArrayBuffer(data));
      } catch (e) {
        const err: BusinessError = e as BusinessError;
        Log.w(TAG, `send 失败: ${err.code} ${err.message}`);
        this.closed = true;
        // ★ 5.0.62：置 closed 之后必须唤醒所有等待者。
        //   否则 readExactly 会一直挂在 waitForData 上、干等自己的超时
        //   （表现成「等了 60 秒没数据」而不是「连接已断」），把真因藏起来。
        this.flushWake();
      }
    };
    this.sendChain = this.sendChain.then(task, task);
    return this.sendChain;
  }

  /**
   * 发送并**感知成败**。
   *
   * `send()` 为了不打断其它调用点，把写失败吞掉了（只置 closed、不抛）。
   * 但块级 / 文件级应答一旦没发出去，对端会一直阻塞在 recv 上等到超时 ——
   * 这是必须能被日志看见的失败，所以这里把 closed 翻成布尔返回值。
   */
  async sendChecked(data: Uint8Array): Promise<boolean> {
    await this.send(data);
    return !this.closed;
  }

  /** 同步关闭（不等待底层完成）。HttpRouter 等调用点不需要等待 */
  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.sock.unbind();
    this.sock.shutdown().catch((e: BusinessError) => {
      Log.d(TAG, `关闭连接异常(可忽略): ${e.code}`);
    });
    // 用 flushWake 而不是 wakeAll：顺手清掉兜底定时器，不留僵尸 timer
    this.flushWake();
  }

  /** 等待底层真正关闭。停服时需要它来确保端口干净释放 */
  async closeAsync(): Promise<void> {
    // ★ 5.1.32：连接关闭必须停掉空闲单例定时器，否则连接对象
    //   即使不再使用，也会留下一个 250ms 的周期定时器。
    this.stopIdleTicker();
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.sock.unbind();
    try {
      await this.sock.shutdown();
    } catch (e) {
      // 对端已断时 close 会抛，忽略
    }
    this.flushWake();
  }

  /**
   * Uint8Array -> ArrayBuffer（socket 层的 send 只接受 ArrayBuffer）。
   *
   * ## 为什么这里要判断「是否精确切片」
   * 早期版本无条件 `new Uint8Array(src.length); copy.set(src, 0)` —— 每发一块都要
   * **整块复制一遍**。1 MB 分片、1 GB 文件就是 1000 次 1 MB memcpy，
   * 纯属白烧 CPU，GC 压力还跟着涨。
   *
   * 实际上只有一种情况必须复制：视图是某个大缓冲的**一部分**
   * （byteOffset != 0 或 byteLength != buffer.byteLength）。
   * 这时直接把整个底层 buffer 交出去会把**视图之外的字节也一起发上线**，
   * 字节流立刻错位 —— 那是比慢严重得多的 bug。
   *
   * 所以规则很直白：
   *   精确独占 buffer  -> 零复制，直接交出去
   *   否则             -> 复制出一份精确大小的
   *
   * ⚠️ 走零复制分支的前提：调用方交出 buffer 后**不得再改它**。
   * 底层 send 是异步的，改了就等于改了正在发的字节。
   * 本项目所有发送点用的都是刚拼出来的一次性数组（ProtoIO.join / intBytes /
   * WsProtocol.encodeXxx / HttpResponse.encode），没有复用缓冲的写法。
   */
  static toArrayBuffer(src: Uint8Array): ArrayBuffer {
    if (src.byteOffset === 0 && src.byteLength === src.buffer.byteLength) {
      return src.buffer as ArrayBuffer;
    }
    return src.buffer.slice(src.byteOffset, src.byteOffset + src.byteLength) as ArrayBuffer;
  }

  /** 合并两段字节。用 Uint8Array 而不是 Array.concat，避免装箱开销 */
  static concat(a: Uint8Array, b: Uint8Array): Uint8Array {
    const out: Uint8Array = new Uint8Array(a.length + b.length);
    out.set(a, 0);
    out.set(b, a.length);
    return out;
  }
}
