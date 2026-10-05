/**
 * v5 协议（局域网互传 1.35 修改版）的帧编解码
 *
 * ## 为什么要有这一份，而不是改 v4 的 ProtoIO
 * 1.35 不是"调参"，是**换了一代协议**：v4 的「boolean + JSON」载荷被整体替换成
 * 纯二进制流式编码，并且**没有保留旧格式回退**。两份协议的字节完全不兼容，
 * 所以不能在同一份代码里用开关切 —— 这里是并行的一份实现，供 V5 包专用。
 *
 * ## 取证来源（不是推断，全部来自 1.35 dex 字节）
 * 见 docs/forensics/：编码器 `Lq2/c`、解码器 `Lx1/b`、写出 `Lq2/k->M2`、
 * 设备头 `LANService->r`、UDP 混淆 `Lq2/k->g2`、服务端帧循环 `LANService->o/q`。
 *
 * ### 帧结构（TCP 与 UDP 共用，12 字节头）
 * ```
 * [0..3]  int32  cmd     命令码（1101/1105/1002…-1 表示"续帧"）
 * [4..7]  int32  arg     命令相关参数（1101 时 = 文件数）
 * [8..11] int32  len     payload 长度
 * [12...]        payload
 * ```
 * 大端。TCP 上建连后先写 4 字节 MAGIC('fgsq')，之后每帧裸写；
 * UDP 上每帧前置 MAGIC（明文 4 字节），其后整帧（头+payload）做**逐字节混淆** `(b-1)^69`（见 V5Udp）。
 *
 * ### 命令帧 payload = 设备头 + 命令参数
 * ```
 * int    devPort
 * String devIp
 * String devName
 * int    devMode
 * String uniqueUuid + "-" + dataVersion
 * int    dataVersion   (= 5)
 * int    batteryLevel
 * byte   chargeStatus
 * int    已知设备数
 *   已知设备数 × (int port, String ip, String name)
 * ```
 *
 * ### 1101（发送文件）
 * ```
 * 帧1  cmd=1101 arg=文件数  payload = 设备头 + byte(encData)
 * 帧2… cmd=-1   arg=0       payload = 每文件一条：
 *        long length / String name / int type(3001|3002|3003|3004)
 *        / String extra(视频时长或空) [/ int childrenCount 仅 3004]
 *        [/ long mediaId 仅 3001、3002]
 * 应答  cmd=1102（同意）/ 1103（拒绝），arg=0，len=0 —— 只有 12 字节头
 * 数据帧 头[0] 单字节写流命令（1=FS_DATA / 2=FS_END / 3=FS_CLOSE），
 *        len 在 [8..11]，payload 是原始字节
 * 流控  接收端在每文件收完后回**裸单字节** 5(FS_NEXT) / 6(FS_BREAK)
 * ```
 *
 * ⚠️ 与 v4 的三处硬差异，记牢：
 *   1. v4 是「裸 int 命令 + 裸字段」，v5 一律套 12 字节头；
 *   2. v4 用 JSON 传文件清单，v5 是每文件一帧的二进制；
 *   3. v5 的 1105 消息帧**去掉了 isClip 布尔位**。
 */
import { util } from '@kit.ArkTS';
import { LanConfig } from './LanConfig';
import { LanDevice } from './DeviceCodec';
import { Log } from './Logger';

const TAG: string = 'V5Codec';

const UTF8: util.TextEncoder = new util.TextEncoder();
const UTF8_DEC: util.TextDecoder = new util.TextDecoder();

/** 文件条目帧的 cmd（1.35 的 `Lq2/c->g()` 里写的是 -1） */
export const V5_FRAME_CONT: number = -1;

/** UDP 混淆常数（1.35 的 g2：逐字节 b[i] = ((b[i]-1)^69)） */
const UDP_XOR: number = 69;

// ==================================================================
// 编码
// ==================================================================

/**
 * 帧编码器，对应 1.35 的 `Lq2/c`。
 *
 * 用法：`new V5Enc(cap)` → `reset(cmd, arg)` → 写字段 → `bytes()`。
 * `bytes()` 会把 payload 长度补写到头 [8..11]（对应 `Lq2/c->a()`）。
 */
export class V5Enc {
  private buf: Uint8Array;
  private pos: number = 12;
  /** 容量不足时的扩容倍数上限，防止异常字符串把内存吃光 */
  private static readonly MAX_CAP: number = 64 * 1024 * 1024;

  constructor(cap: number = 1024) {
    this.buf = new Uint8Array(Math.max(64, cap) + 12);
  }

  /** 回到空帧状态并写入命令字/参数（对应 `g()` + `h()` + `i()`） */
  reset(cmd: number, arg: number = 0): void {
    this.pos = 12;
    this.putIntAt(0, cmd);
    this.putIntAt(4, arg);
  }

  /** 只重置写指针，不改命令字（数据片用：头[0] 要单独写单字节流命令） */
  resetKeepHeader(): void {
    this.pos = 12;
  }

  /** 往头 [0] 写**单字节**流命令（数据片专用，会覆盖 int 的第 1 个字节） */
  setStreamCmd(cmd: number): void {
    this.buf[0] = cmd & 0xFF;
    // 1.35 的 g() 先写 int -1 再被单字节覆盖，剩下 3 字节是 0xFF；
    // 这里保持一致，接收端只读第 1 个字节，其余字节无意义但对齐原包。
    this.buf[1] = 0xFF;
    this.buf[2] = 0xFF;
    this.buf[3] = 0xFF;
    this.putIntAt(4, 0);
  }

  byte(v: number): void {
    this.ensure(1);
    this.buf[this.pos] = v & 0xFF;
    this.pos += 1;
  }

  int(v: number): void {
    this.ensure(4);
    this.putIntAt(this.pos, v);
    this.pos += 4;
  }

  long(v: number): void {
    this.ensure(8);
    const hi: number = Math.floor(v / 4294967296);
    const lo: number = v - hi * 4294967296;
    this.buf[this.pos] = (hi >>> 24) & 0xFF;
    this.buf[this.pos + 1] = (hi >>> 16) & 0xFF;
    this.buf[this.pos + 2] = (hi >>> 8) & 0xFF;
    this.buf[this.pos + 3] = hi & 0xFF;
    this.buf[this.pos + 4] = (lo >>> 24) & 0xFF;
    this.buf[this.pos + 5] = (lo >>> 16) & 0xFF;
    this.buf[this.pos + 6] = (lo >>> 8) & 0xFF;
    this.buf[this.pos + 7] = lo & 0xFF;
    this.pos += 8;
  }

  /**
   * 4 字节长度 + UTF-8。与 `Lq2/c->f()` 完全一致。
   *
   * ⚠️ **致命坑（真机复现过的崩溃）**：ArkTS 的 `util.TextEncoder.encodeInto('')`
   * 返回的是 **`undefined`**（不是空 Uint8Array，见 @ohos.util.d.ts:488-489
   * "If the input parameter is an empty string, the return value is undefined"）。
   * 标准 WHATWG 这里是返回空 Uint8Array，但 ArkTS 不是。直接 `body.length`
   * 会抛 `Cannot read property length of undefined`。
   * 实测崩溃就在「构造文件清单帧」里对 `extra` 字段调 `enc.string('')` 的那一行。
   * 所以空串必须特判：只写 4 字节长度 0，跳过编码。这与 1.35 的 `f("")` 字节一致。
   */
  string(s: string): void {
    if (s === undefined || s === null || s.length === 0) {
      this.int(0);
      return;
    }
    const body: Uint8Array = UTF8.encodeInto(s);
    if (body === undefined || body === null) {
      this.int(0);
      return;
    }
    this.int(body.length);
    this.ensure(body.length);
    this.buf.set(body, this.pos);
    this.pos += body.length;
  }

  /** 当前 payload 长度 */
  get length(): number {
    return this.pos - 12;
  }

  /** 直接拿到内部缓冲的写指针（数据片要自己 arraycopy 进去，避免多拷一次） */
  rawBuffer(): Uint8Array {
    return this.buf;
  }

  /** 把已写入的数据块长度登记进写指针（配合 rawBuffer 使用） */
  advance(n: number): void {
    this.pos += n;
  }

  /**
   * 收尾：把 payload 长度写进头 [8..11]，返回可直接 send 的字节。
   * 对应 `Lq2/k->M2()` 里先 `a()` 再 write 的顺序 —— 顺序不能反。
   */
  bytes(): Uint8Array {
    this.putIntAt(8, this.pos - 12);
    return this.buf.subarray(0, this.pos);
  }

  private putIntAt(off: number, v: number): void {
    this.buf[off] = (v >>> 24) & 0xFF;
    this.buf[off + 1] = (v >>> 16) & 0xFF;
    this.buf[off + 2] = (v >>> 8) & 0xFF;
    this.buf[off + 3] = v & 0xFF;
  }

  private ensure(n: number): void {
    const need: number = this.pos + n;
    if (need <= this.buf.length) {
      return;
    }
    let cap: number = this.buf.length;
    while (cap < need) {
      cap *= 2;
    }
    if (cap > V5Enc.MAX_CAP) {
      // 到这一步说明调用方写了个异常大的字符串，属于 bug 而不是正常流量
      Log.e(TAG, `帧编码超出上限: need=${need}`);
      cap = need;
    }
    const next: Uint8Array = new Uint8Array(cap);
    next.set(this.buf.subarray(0, this.pos), 0);
    this.buf = next;
  }
}

// ==================================================================
// 解码
// ==================================================================

/**
 * 帧解码器，对应 1.35 的 `Lx1/b`。
 *
 * ⚠️ 两种读法要分清：
 *   - `cmd()/arg()/len()` 按**绝对偏移**读头字段（不受读指针影响）；
 *   - `byte()/int()/long()/string()` 是**顺序**读 payload。
 * 1.35 的服务端就是混用这两套：先用 e(0)/e(4) 取命令与文件数，再顺序读参数。
 */
export class V5Dec {
  private buf: Uint8Array;
  private pos: number;
  private limit: number;

  /** @param off 读指针起始（整帧缓冲通常传 12，裸 payload 传 0） */
  constructor(buf: Uint8Array, off: number = 12, limit: number = -1) {
    this.buf = buf;
    this.pos = off;
    this.limit = limit < 0 ? buf.length : limit;
  }

  /** 绑定新的缓冲（1.35 的 `m(int, [B)`） */
  bind(buf: Uint8Array, off: number, limit: number): void {
    this.buf = buf;
    this.pos = off;
    this.limit = limit;
  }

  /** 头 [0..3] */
  cmd(): number {
    return V5Dec.beInt(this.buf, 0);
  }

  /** 头 [4..7] */
  arg(): number {
    return V5Dec.beInt(this.buf, 4);
  }

  /** 头 [8..11] */
  len(): number {
    return V5Dec.beInt(this.buf, 8);
  }

  get remaining(): number {
    return this.limit - this.pos;
  }

  byte(): number {
    if (this.remaining < 1) {
      return 0;
    }
    const v: number = this.buf[this.pos];
    this.pos += 1;
    return v;
  }

  int(): number {
    if (this.remaining < 4) {
      return 0;
    }
    const v: number = V5Dec.beInt(this.buf, this.pos);
    this.pos += 4;
    return v;
  }

  long(): number {
    if (this.remaining < 8) {
      return -1;
    }
    const hi: number = V5Dec.beInt(this.buf, this.pos);
    const lo: number = V5Dec.beInt(this.buf, this.pos + 4);
    this.pos += 8;
    return hi * 4294967296 + (lo >>> 0);
  }

  string(): string {
    const n: number = this.int();
    if (n <= 0) {
      return '';
    }
    if (n > this.remaining) {
      Log.w(TAG, `字符串长度越界: ${n} > ${this.remaining}`);
      return '';
    }
    const s: string = UTF8_DEC.decodeToString(this.buf.subarray(this.pos, this.pos + n));
    this.pos += n;
    return s;
  }

  static beInt(b: Uint8Array, off: number): number {
    return ((b[off] << 24) | (b[off + 1] << 16) | (b[off + 2] << 8) | b[off + 3]) | 0;
  }
}

// ==================================================================
// 设备头
// ==================================================================

export class V5Header {
  /**
   * 写设备头。对应 1.35 的 `LANService->r(Device, int)`。
   *
   * @param known 已知设备表（1.35 会把它带上，让新设备"一次广播认识全网"）。
   *              传空数组是合法的 —— 只是少了这个加速，不影响互通。
   */
  static write(enc: V5Enc, self: LanDevice, known: LanDevice[]): void {
    enc.int(self.devPort);
    enc.string(self.devIp);
    enc.string(self.devName);
    enc.int(self.devMode);
    // 兼容写法：把版本拼在 uuid 后面，接收方按 '-' 拆（与 v4 同一套约定）
    enc.string(`${self.uniqueUuid}-${LanConfig.DATA_VERSION}`);
    enc.int(LanConfig.DATA_VERSION);
    enc.int(self.batteryLevel);
    enc.byte(self.chargeStatus);
    enc.int(known.length);
    for (let i = 0; i < known.length; i++) {
      enc.int(known[i].devPort);
      enc.string(known[i].devIp);
      enc.string(known[i].devName);
    }
  }

  /**
   * 读设备头。返回 null 表示字段残缺（连接会直接关掉）。
   *
   * ⚠️ 必须与 `write` 逐字段对齐：`write` 在 `chargeStatus` 之后还写了一整型
   * 「已知设备数」（`write` 里 `enc.int(known.length)`，我们的实现恒为 0）。
   * 这里默认把它读掉（consumeKnown=true），否则**紧随其后的字段
   * （encData 字节 / 消息串）会整体错位**——错位后读到的字符串长度通常是 0，
   * 消息/文件请求直接解析失败。
   *
   * @param consumeKnown true（TCP 收端）：吃掉计数位，调用方接着读 encData/消息；
   *                     false（UDP 收端）：保留计数位给 `parse` 去读已知设备表。
   */
  static read(dec: V5Dec, consumeKnown: boolean = true): LanDevice | null {
    const d: LanDevice = new LanDevice();
    d.devPort = dec.int();
    d.devIp = dec.string();
    d.devName = dec.string();
    d.devMode = dec.int();
    d.uniqueUuid = dec.string();
    d.dataVersion = dec.int();
    d.batteryLevel = dec.int();
    d.chargeStatus = dec.byte();
    // ⚠️ 吃掉「已知设备数」整型 **以及其后的整张设备表**。
    // 1.35 的 `r()`（LANService 16923-16950）在 chargeStatus 之后写的是
    // `count` + `count × (int devPort, String devIp, String devName)`。
    // 只吃 count 不清表，会让**紧随其后的 encData 字节 / 消息串整体后移** ——
    // 当对端设备表非空（count>0）时必然错位，这正是「收到 1.35 文件但大小为 0」的成因之一。
    if (consumeKnown) {
      const knownCount: number = dec.int();
      // 防御：计数只可能是 0..几十，异常值当 0 处理，避免吃穿整个 payload
      const safe: number = knownCount > 0 && knownCount <= 64 ? knownCount : 0;
      for (let i = 0; i < safe; i++) {
        dec.int();
        dec.string();
        dec.string();
      }
    }
    if (d.devIp.length === 0) {
      return null;
    }
    // uuid 形如 "<uuid>-<ver>"：以后缀为准（与 v4 解析保持一致）
    const sep: number = d.uniqueUuid.lastIndexOf('-');
    if (sep > 0) {
      const tail: string = d.uniqueUuid.substring(sep + 1);
      const parsed: number = Number.parseInt(tail, 10);
      if (!Number.isNaN(parsed)) {
        d.dataVersion = parsed;
        d.uniqueUuid = d.uniqueUuid.substring(0, sep);
      }
    }
    d.lastSeenMs = Date.now();
    return d;
  }

  /** 读完设备头之后，再读"已知设备表"（可选，读不动就当没有） */
  static readKnown(dec: V5Dec, count: number): LanDevice[] {
    const out: LanDevice[] = [];
    for (let i = 0; i < count; i++) {
      if (dec.remaining < 4) {
        break;
      }
      const d: LanDevice = new LanDevice();
      d.devPort = dec.int();
      d.devIp = dec.string();
      d.devName = dec.string();
      d.devMode = 7; // 未知来源设备，1.35 里给的是 WEB(7)
      d.lastSeenMs = Date.now();
      out.push(d);
    }
    return out;
  }
}

// ==================================================================
// UDP：MAGIC + 链式混淆
// ==================================================================

/**
 * UDP 报文的混淆（对应 1.35 的 `Lq2/k->g2`，逐字节独立，无链式依赖）。
 *
 * 编码：`b[i] = ((b[i] - 1) ^ 69) & 0xFF`   （`0x45` = 69）
 * 解码：`b[i] = ((b[i] ^ 69) + 1) & 0xFF`
 *
 * ⚠️ 这是**逐字节独立**的变换（已在 1.35 dex 的 g2 字节级确认：
 *    `sub-int/2addr v5, v4(=1)` 后 `xor-int/lit8 v4, v5, 0x45`）。
 *    之前误写成「链式 prev」是完全错误的 —— 链式写法连收发本身都还原不回来，
 *    正是 V5↔V5 互相发现不了的 root cause。
 *    编码/解码互为反函数（手算验证：((P-1)^69)^69+1 = P），自洽且可对 1.35。
 */
export class V5Udp {
  static obfuscate(b: Uint8Array, from: number, to: number): void {
    for (let i = from; i < to; i++) {
      const sub: number = ((b[i] & 0xFF) - 1) & 0xFF;
      b[i] = (sub ^ UDP_XOR) & 0xFF;
    }
  }

  static deobfuscate(b: Uint8Array, from: number, to: number): void {
    for (let i = from; i < to; i++) {
      b[i] = (((b[i] & 0xFF) ^ UDP_XOR) + 1) & 0xFF;
    }
  }

  static magicPrefix(): Uint8Array {
    const m: number = LanConfig.MAGIC_NUM;
    return new Uint8Array([(m >>> 24) & 0xFF, (m >>> 16) & 0xFF, (m >>> 8) & 0xFF, m & 0xFF]);
  }

  /**
   * 构造 UDP 数据报：MAGIC(4，明文) + 混淆后的帧。
   * @param payloadBytes 已经调用过 `V5Enc.bytes()` 的帧字节（含 12 头）
   */
  static build(cmd: number, self: LanDevice, known: LanDevice[], extra: string[] = []): Uint8Array {
    const enc: V5Enc = new V5Enc(512);
    enc.reset(cmd, 0);
    V5Header.write(enc, self, known);
    for (let i = 0; i < extra.length; i++) {
      enc.string(extra[i]);
    }
    const frame: Uint8Array = enc.bytes();
    // 复制一份再混淆：enc 内部缓冲会被复用，就地改会污染下一次编码
    const body: Uint8Array = new Uint8Array(frame.length);
    body.set(frame, 0);
    V5Udp.obfuscate(body, 0, body.length);
    const out: Uint8Array = new Uint8Array(4 + body.length);
    out.set(V5Udp.magicPrefix(), 0);
    out.set(body, 4);
    return out;
  }

  /** UDP 数据报解析结果 */
  static parse(datagram: Uint8Array): V5UdpFrame | null {
    if (datagram.length < 16) {
      return null;
    }
    if (V5Dec.beInt(datagram, 0) !== LanConfig.MAGIC_NUM) {
      return null;
    }
    const body: Uint8Array = new Uint8Array(datagram.length - 4);
    body.set(datagram.subarray(4), 0);
    V5Udp.deobfuscate(body, 0, body.length);
    const dec: V5Dec = new V5Dec(body, 12, body.length);
    const cmd: number = dec.cmd();
    const frame: V5UdpFrame = new V5UdpFrame();
    frame.cmd = cmd;
    // consumeKnown=false：保留「已知设备数」计数位，下面这一行接着读设备表
    const dev: LanDevice | null = V5Header.read(dec, false);
    if (dev === null) {
      return null;
    }
    frame.device = dev;
    // ★ v4 / v5 的分叉点（5.0.21 定案，真机复现过）
    //   「已知设备表」是 **v5（1.35 修改版）新增**的字段：
    //     设备头 8 字段 → int 已知设备数 → N×(int port, String ip, String name) → 命令参数
    //   官方 v4（`Config.DATA_VERSION = LVersion.DATA_VERSION_4`）**没有这一段**，
    //   8 个字段之后直接就是命令参数。
    //   ⚠️ 无条件读这个计数会把 v4 的 `messageEnc` 长度前缀（例如 181）当成设备数，
    //      `readKnown` 于是把整段消息吃穿 → `extras` 全空 →
    //      收到 1004 时打 "UDP 消息帧缺少密文字段" → **官方安卓发来的文字一条都收不到**。
    //      （修复前真机日志：`字符串长度越界: 825255268 > 78` ×10，随后就是上面那句）
    //   判据取**对端广播的 dataVersion**（= uuid 后缀，`V5Header.read` 已解析并剥掉）：
    //     ≤4（官方 / 更老版本）无此段；≥5（v5）有此段。
    if (dev.dataVersion >= LanConfig.V5_MIN_DATA_VERSION) {
      const knownCount: number = dec.int();
      frame.known = V5Header.readKnown(dec, Math.min(knownCount, 64));
    }
    // 剩下的都是命令专属参数（文本消息等）
    for (let i = 0; i < 8; i++) {
      if (dec.remaining < 4) {
        break;
      }
      frame.extras.push(dec.string());
    }
    return frame;
  }
}

export class V5UdpFrame {
  cmd: number = 0;
  device: LanDevice = new LanDevice();
  known: LanDevice[] = [];
  extras: string[] = [];
}
