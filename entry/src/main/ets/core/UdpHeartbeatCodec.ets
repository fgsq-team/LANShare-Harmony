/**
 * UDP 心跳 / 设备发现帧编解码 —— 与官方 LANShare 1.2.x 字节兼容
 *
 * 官方在 UDP 上用「MAGIC + 逐字节混淆的 12 字节头帧」承载设备心跳与探测应答，
 * 本机沿用**同一套字节**（与官方 v4 源码逐字节对照：混淆、包头、12 字节头、
 * 8 个设备头字段的顺序与类型逐个相同）。TCP 上的文件与文本传输走另一套
 * （v4 裸序列化，见 ProtoIO / FileTransfer / TextMessenger），与本文件无关。
 *
 * ## 取证来源（不是推断）
 * 官方 v4 源码（`DataEnc` / `LANService.makeDataEncUdp()`）与 Android 端 dex
 * （编码器 `Lq2/c`、解码器 `Lx1/b`、设备头 `LANService->r`、
 *  UDP 混淆 `Lq2/k->g2`）对照，字段顺序与类型逐个相同。
 *
 * ### 帧结构（12 字节头，大端）
 * ```
 * [0..3]  int32  cmd     命令码（1001 探测 / 1002 上报 / 1003 下线…）
 * [4..7]  int32  arg     命令相关参数
 * [8..11] int32  len     payload 长度
 * [12...]        payload
 * ```
 * UDP 上每帧前置 MAGIC（明文 4 字节），其后整帧（头+payload）做**逐字节混淆**
 * `(b-1)^69`（见 UdpHeartbeat，与官方 DataEnc.encData 逐字节一致）。
 *
 * ### 命令帧 payload = 设备头（+ 可选已知设备表）+ 命令参数
 * ```
 * int    devPort
 * String devIp
 * String devName
 * int    devMode
 * String uniqueUuid + "-" + dataVersion
 * int    dataVersion   （本机恒 4）
 * int    batteryLevel
 * byte   chargeStatus
 * int    已知设备数      ← 可选段：仅对端 dataVersion >= 5 时出现；本机恒写 0
 *   已知设备数 × (int port, String ip, String name)
 * ```
 *
 * ⚠️ 「已知设备表」是**可选段**：官方 v4 的心跳不带它，部分修改版构建
 *    （dataVersion >= 5）才会带。本机从不发送真实表，但解析时必须按对端
 *    dataVersion 决定跳不跳 —— 无条件读会把 v4 消息的长度前缀当成设备数，
 *    把整段 payload 吃穿（真机事故见 parse 里的注释）。
 */
import { util } from '@kit.ArkTS';
import { LanConfig } from './LanConfig';
import { LanDevice } from './DeviceCodec';
import { Log } from './Logger';

const TAG: string = 'UdpHeartbeatCodec';

/**
 * 对端宣告 dataVersion >= 5 时，设备头后会多带一张「已知设备表」。
 * 官方 v4 没有这一段。本机从不发送它，但收到必须跳过，否则后续字段错位。
 */
const KNOWN_TABLE_MIN_DATA_VERSION: number = 5;

const UTF8: util.TextEncoder = new util.TextEncoder();
const UTF8_DEC: util.TextDecoder = new util.TextDecoder();

/** UDP 混淆常数（与官方 v4 的 DataEnc.encData 一致：逐字节 b[i] = ((b[i]-1)^69)） */
const UDP_XOR: number = 69;

// ==================================================================
// 编码
// ==================================================================

/**
 * 帧编码器，对应 Android 端 dex 的 `Lq2/c`。
 *
 * 用法：`new HeartbeatEnc(cap)` → `reset(cmd, arg)` → 写字段 → `bytes()`。
 * `bytes()` 会把 payload 长度补写到头 [8..11]（对应 `Lq2/c->a()`）。
 */
export class HeartbeatEnc {
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
    // 对端 dex 的 g() 先写 int -1 再被单字节覆盖，剩下 3 字节是 0xFF；
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
   * 所以空串必须特判：只写 4 字节长度 0，跳过编码。这与对端 dex 的 `f("")` 字节一致。
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
    if (cap > HeartbeatEnc.MAX_CAP) {
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
 * 帧解码器，对应 Android 端 dex 的 `Lx1/b`。
 *
 * ⚠️ 两种读法要分清：
 *   - `cmd()/arg()/len()` 按**绝对偏移**读头字段（不受读指针影响）；
 *   - `byte()/int()/long()/string()` 是**顺序**读 payload。
 * 对端服务端就是混用这两套：先用 e(0)/e(4) 取命令与文件数，再顺序读参数。
 */
export class HeartbeatDec {
  private buf: Uint8Array;
  private pos: number;
  private limit: number;

  /** @param off 读指针起始（整帧缓冲通常传 12，裸 payload 传 0） */
  constructor(buf: Uint8Array, off: number = 12, limit: number = -1) {
    this.buf = buf;
    this.pos = off;
    this.limit = limit < 0 ? buf.length : limit;
  }

  /** 绑定新的缓冲（对端 dex 的 `m(int, [B)`） */
  bind(buf: Uint8Array, off: number, limit: number): void {
    this.buf = buf;
    this.pos = off;
    this.limit = limit;
  }

  /** 头 [0..3] */
  cmd(): number {
    return HeartbeatDec.beInt(this.buf, 0);
  }

  /** 头 [4..7] */
  arg(): number {
    return HeartbeatDec.beInt(this.buf, 4);
  }

  /** 头 [8..11] */
  len(): number {
    return HeartbeatDec.beInt(this.buf, 8);
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
    const v: number = HeartbeatDec.beInt(this.buf, this.pos);
    this.pos += 4;
    return v;
  }

  long(): number {
    if (this.remaining < 8) {
      return -1;
    }
    const hi: number = HeartbeatDec.beInt(this.buf, this.pos);
    const lo: number = HeartbeatDec.beInt(this.buf, this.pos + 4);
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

export class HeartbeatHeader {
  /** 写设备头：8 个字段 + 「已知设备数」计数位（恒 0） */
  static write(enc: HeartbeatEnc, self: LanDevice): void {
    enc.int(self.devPort);
    enc.string(self.devIp);
    enc.string(self.devName);
    enc.int(self.devMode);
    // 兼容写法：把版本拼在 uuid 后面，接收方按 '-' 拆（与 v4 同一套约定）
    // ★ 跟随 self.dataVersion（LanConfig.DATA_VERSION，本机恒为 4）
    enc.string(`${self.uniqueUuid}-${self.dataVersion}`);
    enc.int(self.dataVersion);
    enc.int(self.batteryLevel);
    enc.byte(self.chargeStatus);
    // 本机从不发送「已知设备表」，恒写计数 0。
    // ⚠️ 这一位在线路上是存在的，不能省 —— 对端按同样偏移读它。
    enc.int(0);
  }

  /**
   * 读设备头（8 个字段）。返回 null 表示字段残缺。
   *
   * ⚠️ `chargeStatus` 之后那一整型「已知设备数」**不在这里读** ——
   * 它是否出现取决于对端宣告的 dataVersion，只有调用方知道该按哪套规则跳过
   * （见 `UdpHeartbeat.parse`）。
   */
  static read(dec: HeartbeatDec): LanDevice | null {
    const d: LanDevice = new LanDevice();
    d.devPort = dec.int();
    d.devIp = dec.string();
    d.devName = dec.string();
    d.devMode = dec.int();
    d.uniqueUuid = dec.string();
    d.dataVersion = dec.int();
    d.batteryLevel = dec.int();
    d.chargeStatus = dec.byte();
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

}

// ==================================================================
// UDP：MAGIC + 链式混淆
// ==================================================================

/**
 * UDP 报文的混淆（与官方 v4 的 DataEnc.encData 逐字节一致；dex 侧见 `Lq2/k->g2`，逐字节独立、无链式依赖）。
 *
 * 编码：`b[i] = ((b[i] - 1) ^ 69) & 0xFF`   （`0x45` = 69）
 * 解码：`b[i] = ((b[i] ^ 69) + 1) & 0xFF`
 *
 * ⚠️ 这是**逐字节独立**的变换（dex 的 g2 字节级确认，与官方 v4 源码一致：
 *    smali 里对应「sub-int/2addr（减 1）+ xor-int/lit8 0x45」两条指令）。
 *    之前误写成「链式 prev」是完全错误的 —— 链式写法连收发本身都还原不回来，
 *    是历史上双方互相发现不了的 root cause。
 *    编码/解码互为反函数（手算验证：((P-1)^69)^69+1 = P），自洽且与对端一致。
 */
export class UdpHeartbeat {
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
   * @param payloadBytes 已经调用过 `HeartbeatEnc.bytes()` 的帧字节（含 12 头）
   */
  static build(cmd: number, self: LanDevice, extra: string[] = []): Uint8Array {
    const enc: HeartbeatEnc = new HeartbeatEnc(512);
    enc.reset(cmd, 0);
    HeartbeatHeader.write(enc, self);
    for (let i = 0; i < extra.length; i++) {
      enc.string(extra[i]);
    }
    const frame: Uint8Array = enc.bytes();
    // 复制一份再混淆：enc 内部缓冲会被复用，就地改会污染下一次编码
    const body: Uint8Array = new Uint8Array(frame.length);
    body.set(frame, 0);
    UdpHeartbeat.obfuscate(body, 0, body.length);
    const out: Uint8Array = new Uint8Array(4 + body.length);
    out.set(UdpHeartbeat.magicPrefix(), 0);
    out.set(body, 4);
    return out;
  }

  /** UDP 数据报解析结果 */
  static parse(datagram: Uint8Array): UdpHeartbeatFrame | null {
    if (datagram.length < 16) {
      return null;
    }
    if (HeartbeatDec.beInt(datagram, 0) !== LanConfig.MAGIC_NUM) {
      return null;
    }
    const body: Uint8Array = new Uint8Array(datagram.length - 4);
    body.set(datagram.subarray(4), 0);
    UdpHeartbeat.deobfuscate(body, 0, body.length);
    const dec: HeartbeatDec = new HeartbeatDec(body, 12, body.length);
    const cmd: number = dec.cmd();
    const frame: UdpHeartbeatFrame = new UdpHeartbeatFrame();
    frame.cmd = cmd;
    const dev: LanDevice | null = HeartbeatHeader.read(dec);
    if (dev === null) {
      return null;
    }
    frame.device = dev;
    // 「已知设备表」是部分修改版构建比官方 v4 多出来的一段：
    //   设备头 8 字段 → int 已知设备数 → N×(int port, String ip, String name) → 命令参数
    // ⚠️ 无条件读这个计数会把 v4 的消息长度前缀（例如 181）当成设备数，
    //    把整段消息吃穿 → extras 全空 → 官方端发来的文字一条都收不到
    //    （修复前真机日志：`字符串长度越界: 825255268 > 78` ×10）。
    //    判据取对端广播的 dataVersion（= uuid 后缀，read 已解析并剥掉）：
    //    ≤4（官方 / 更老版本）无此段；≥5 有此段。
    // 本机从不发这段，收到也只用不存 —— 跳过以保证后续 extras 对齐。
    if (dev.dataVersion >= KNOWN_TABLE_MIN_DATA_VERSION) {
      const knownCount: number = dec.int();
      // 防御：计数只可能是 0..几十，异常值当 0 处理，避免吃穿整个 payload
      const safe: number = knownCount > 0 && knownCount <= 64 ? knownCount : 0;
      for (let i = 0; i < safe; i++) {
        dec.int();
        dec.string();
        dec.string();
      }
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

export class UdpHeartbeatFrame {
  cmd: number = 0;
  device: LanDevice = new LanDevice();
  extras: string[] = [];
}
