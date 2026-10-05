/**
 * UDP 设备发现 —— 替代 LANService.udpServer() / udpClient 广播逻辑
 *
 * ## 鸿蒙与 Android 的差异（重要）
 * | Android                                        | 鸿蒙                                 |
 * |------------------------------------------------|--------------------------------------|
 * | WifiManager.createMulticastLock() 保持广播可达   | **不需要**，无对应 API，系统直接放行    |
 * | Cb.getSystemService(WIFI_SERVICE) 取本机 IP      | connection.getConnectionProperties() |
 * | NetworkInterface.getByName(iface)               | 同上，从 linkAddresses 取             |
 * | DatagramSocket.setBroadcast(true)               | udp.setExtraOptions({ broadcast: true }) |
 * | MulticastSocket.setNetworkInterface()           | socket.constructMulticastSocketInstance() |
 *
 * ## 广播地址的算法
 * 原 Android 从 `Device.devBrotIP` 直接取（由 NetWorkUtil 根据 IP + 掩码算出）。
 * 鸿蒙侧同样需要自己算：broadcast = ip | ~netmask。
 * 设备发现必须往**子网定向广播地址**发（如 192.168.10.255），
 * 而不是全局 255.255.255.255 —— 后者在部分路由器/多网卡环境下不出本机网卡。
 *
 * ## 后台限制提示（迁移风险评估点）
 * 鸿蒙对后台应用的组播/广播收发有额外管控。长时间无长时任务保护时，
 * 后台的 UDP 监听可能被冻结。这是必须真机实测的一项，见 docs/迁移对照表.md。
 */
import { socket } from '@kit.NetworkKit';
import { connection } from '@kit.NetworkKit';
import { fileIo } from '@kit.CoreFileKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { LanConfig } from '../core/LanConfig';
import { DeviceCodec, LanDevice, UdpFrame } from '../core/DeviceCodec';
import { LCmd } from '../core/LCmd';
import { Log } from '../core/Logger';

const TAG: string = 'LanDiscovery';

/**
 * 常见软 AP / 网络共享网段（getAllNets 拿不到接口时的兜底候选）。
 * 每条都写死在真实系统里：
 *   192.168.43.0/24  Android 与鸿蒙软 AP 的出厂默认
 *   192.168.137.0/24 Windows「移动热点」
 *   172.20.10.0/24   iOS 个人热点
 *   172.17.11.0/24   鸿蒙 anco（多设备协同共享口）
 * 这些网段的**第一个可用地址**几乎总是 AP 自己，探测它就够了。
 */
const COMMON_AP_SEGMENTS: string[] = [
  '192.168.43', '192.168.137', '172.20.10', '172.17.11',
  '192.168.8', '192.168.49', '192.168.0', '192.168.1'
];

/** 路由表条目（只需要网段与掩码） */
interface RouteEntry {
  network: string;
  mask: string;
}

/** 本机网络位置信息 */
export class LocalNetInfo {
  ip: string = '';
  netMask: string = '';
  /** 子网定向广播地址 */
  broadcastIp: string = '';
  interfaceName: string = '';
  isIPv4: boolean = true;
  /** connection.NetBearType。蜂窝网要排到最后面，见 resolveAllLocalNets */
  bearer: number = -1;

  get valid(): boolean {
    return this.ip.length > 0;
  }

  /** 一行描述，直接进日志 */
  get text(): string {
    return `${this.ip}/${this.netMask} 广播 ${this.broadcastIp} (${this.interfaceName})`;
  }
}

/** UDP 报文回调。带完整的 frame（含命令字与附加参数），见 DeviceCodec.UdpFrame */
export type DeviceFoundCallback = (frame: UdpFrame, fromIp: string, fromPort: number) => void;

export class LanDiscovery {
  private recvSocket: socket.UDPSocket | null = null;
  private sendSocket: socket.UDPSocket | null = null;
  private udpPort: number = LanConfig.DEFAULT_UDP_PORT;
  private running: boolean = false;

  /** 本机设备信息。设置后才能构造心跳包 */
  private self: LanDevice | null = null;
  private onFound: DeviceFoundCallback | null = null;
  /** 定时广播探测/心跳的句柄 */
  private timerId: number = -1;
  /** 当前正在广播的子网列表。可被 updateNets 热替换 */
  private scanNets: LocalNetInfo[] = [];
  /** 已经见过的 UDP 来源 IP（只用于日志去重） */
  private seenPeers: string[] = [];

  setSelf(self: LanDevice): void {
    this.self = self;
  }

  setOnFound(cb: DeviceFoundCallback): void {
    this.onFound = cb;
  }

  get isRunning(): boolean {
    return this.running;
  }

  /**
   * 枚举本机**所有**网络的 IPv4 位置信息。
   *
   * ## 为什么不能只取 getDefaultNet()
   * 这是「手机开热点时单向发现」的根因。
   *
   * 手机开热点（软 AP）时，它自身上网走的是**蜂窝网**，于是
   * `getDefaultNet()` 返回蜂窝网 —— 只往它的广播地址发，热点子网一个包都收不到。
   * 热点下的设备广播时，我们绑的是 0.0.0.0，收得到；我们广播时却发到了蜂窝口，
   * 对端收不到。**一来一去就成了单向可见**。
   *
   * 同理，多网卡（WiFi + 有线 + 热点）机器上只发一个子网，其它子网的设备都看不见。
   *
   * 所以这里枚举 `getAllNets()`，逐个网络取全部 IPv4 地址，
   * **每个子网各发一份**，且报文里的 devIp 用**那个子网自己的接口 IP**
   * （devIp 是对端回连我 5856 用的地址，填错就等于告诉对方一个连不上的地址）。
   *
   * 结果按优先级排序：非蜂窝 -> 蜂窝；同类里保留原顺序。
   */
  static async resolveAllLocalNets(verbose: boolean = false): Promise<LocalNetInfo[]> {
    const out: LocalNetInfo[] = [];
    try {
      const nets: connection.NetHandle[] = await connection.getAllNets();
      if (verbose) {
        Log.i(TAG, `getAllNets 返回 ${nets.length} 个网络`);
      }
      for (let n = 0; n < nets.length; n++) {
        let props: connection.ConnectionProperties;
        try {
          props = await connection.getConnectionProperties(nets[n]);
        } catch (e) {
          // 单个网络取属性失败不影响其它网络。必须打日志：
          // 软 AP 口到底是被过滤掉了、还是取属性时报错，全靠这行区分。
          const err: BusinessError = e as BusinessError;
          if (verbose) {
            Log.i(TAG, `网络 #${n} 取属性失败: ${err.code} ${err.message}`);
          }
          continue;
        }
        let bearer: number = -1;
        try {
          const caps: connection.NetCapabilities = await connection.getNetCapabilities(nets[n]);
          if (caps.bearerTypes.length > 0) {
            bearer = caps.bearerTypes[0];
          }
        } catch (e) {
          // 拿不到就不参与排序，按非蜂窝处理
        }
        const addrs: string[] = [];
        for (let i = 0; i < props.linkAddresses.length; i++) {
          addrs.push(`${props.linkAddresses[i].address.address}/${props.linkAddresses[i].prefixLength}`);
        }
        if (verbose) {
          Log.i(TAG, `网络 #${n} iface=${props.interfaceName} bearer=${bearer} 地址=[${addrs.join(', ')}]`);
        }
        // 一个网络上可能挂多个地址（WiFi + 热点常落在同一个 net 上），逐个收
        for (let i = 0; i < props.linkAddresses.length; i++) {
          const la: connection.LinkAddress = props.linkAddresses[i];
          const addr: string = la.address.address;
          const info: LocalNetInfo = LanDiscovery.buildNetInfo(addr, la.prefixLength,
            props.interfaceName, bearer);
          if (info.valid) {
            out.push(info);
          }
        }
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `枚举本机网络失败: ${err.code} ${err.message}`);
    }
    const sorted: LocalNetInfo[] = LanDiscovery.sortNets(out);
    // 补一道：软 AP / 网络共享口根本不出现在 getAllNets 里，只能自己探
    const extra: LocalNetInfo[] = await LanDiscovery.probeHiddenNets(sorted, verbose);
    if (extra.length > 0) {
      for (let i = 0; i < extra.length; i++) {
        sorted.push(extra[i]);
      }
      // 只在 verbose（首次解析）时打：周期刷新每 10s 都打一遍纯属噪音
      if (verbose) {
        Log.i(TAG, `补充探测到 ${extra.length} 个隐藏子网: ${LanDiscovery.joinNets(extra)}`);
      }
    } else if (verbose) {
      Log.i(TAG, `未探测到隐藏子网，最终 ${sorted.length} 个子网: ${LanDiscovery.joinNets(sorted)}`);
    }
    // 最后一道兜底：一个可广播子网都没确认到（典型是"只开热点、没连 WiFi"），
    // 就按常见软 AP 网段**无条件**广播。
    // 就算 devIp 猜错，对端**发现**我们也不需要 devIp 正确（收到包即可），
    // 而我们要连对端用的是对端包里那个正确的 devIp —— 所以至少能修好单向。
    if (sorted.length === 0) {
      const guess: LocalNetInfo[] = LanDiscovery.guessFallbackNets();
      for (let i = 0; i < guess.length; i++) {
        sorted.push(guess[i]);
      }
      Log.i(TAG, `未确认到任何接口，按常见软 AP 网段兜底广播: ${LanDiscovery.joinNets(guess)}`);
    }
    return sorted;
  }

  /** 未确认的兜底子网（常见软 AP 网段的首地址，掩码按 /24） */
  static guessFallbackNets(): LocalNetInfo[] {
    const out: LocalNetInfo[] = [];
    for (let i = 0; i < COMMON_AP_SEGMENTS.length; i++) {
      const info: LocalNetInfo =
        LanDiscovery.buildNetInfo(`${COMMON_AP_SEGMENTS[i]}.1`, 24, 'softap?', -1);
      if (info.valid) {
        out.push(info);
      }
    }
    return out;
  }

  /** 子网列表拼成一行，只进日志 */
  static joinNets(list: LocalNetInfo[]): string {
    const parts: string[] = [];
    for (let i = 0; i < list.length; i++) {
      parts.push(list[i].text);
    }
    return parts.join(' | ');
  }

  /**
   * 探测 `getAllNets()` **拿不到**的 IPv4 接口 —— 主要是本机开的软 AP（热点）。
   *
   * ## 为什么必须单独探
   * 真机实测（PLR-AL50，开热点 + 不连 WiFi）：
   *   wlan1     192.168.43.1/24   <- 软 AP 口，UP 且有流量
   *   rmnet0    10.98.49.159/32   <- 蜂窝，getAllNets 能拿到
   *   wlan0     UP 但**没有地址**（没连 WiFi）
   * 而 `connection.getAllNets()` 只返回能上网的网（这例里只有蜂窝），
   * 软 AP 口一个都拿不到 —— 于是我们压根不知道 192.168.43.0/24 存在，
   * 广播自然一格包都发不到热点子网，平板当然发现不了手机。
   *
   * 系统没给应用暴露软 AP 口地址，只能自己试：
   *   1. 读 `/proc/net/route` 拿**直连路由**（Gateway=0 且 Flags 含 UP），
   *      路由表里软 AP 口是有的（内核总得知道往哪发包）；
   *   2. 每个直连网段试它的第一个地址（软 AP 自己永远是网段的第一个地址）；
   *   3. 用 `UDPSocket.bind()` 试探：绑得上 = 这地址就是本机；
   *      绑不上会抛 EADDRNOTAVAIL。这是唯一能确认"某 IP 是不是我的"的手段。
   *
   * @param known 已经由 getAllNets 拿到的子网，避免重复探测
   */
  static async probeHiddenNets(known: LocalNetInfo[], verbose: boolean = false): Promise<LocalNetInfo[]> {
    const out: LocalNetInfo[] = [];
    const candidates: RouteEntry[] = [];

    // ---- 1. 路由表里的直连网段（最准） ----
    const routes: RouteEntry[] = LanDiscovery.readDirectRoutes(verbose);
    for (let i = 0; i < routes.length; i++) {
      const first: string = LanDiscovery.segmentFirstHost(routes[i].network);
      if (first.length > 0) {
        candidates.push({ network: routes[i].network, mask: routes[i].mask });
      }
    }
    // ---- 2. 常见软 AP 网段兜底（路由表读不到时） ----
    for (let i = 0; i < COMMON_AP_SEGMENTS.length; i++) {
      const seg: string = COMMON_AP_SEGMENTS[i];
      let dup: boolean = false;
      for (let j = 0; j < candidates.length; j++) {
        if (candidates[j].network === `${seg}.0`) {
          dup = true;
          break;
        }
      }
      if (!dup) {
        candidates.push({ network: `${seg}.0`, mask: '255.255.255.0' });
      }
    }

    for (let i = 0; i < candidates.length; i++) {
      const seg: RouteEntry = candidates[i];
      // 已在已知列表里的跳过（同一个网段）
      let skip: boolean = false;
      for (let k = 0; k < known.length; k++) {
        if (LanDiscovery.sameSegment(known[k].ip, seg.network, seg.mask)) {
          skip = true;
          break;
        }
      }
      if (skip) {
        continue;
      }
      const host: string = LanDiscovery.segmentFirstHost(seg.network);
      if (host.length === 0) {
        continue;
      }
      const mine: boolean = await LanDiscovery.isLocalAddress(host);
      if (!mine) {
        continue;
      }
      const info: LocalNetInfo = LanDiscovery.buildNetInfo(host, LanDiscovery.maskToPrefix(seg.mask),
        'softap', -1);
      if (info.valid) {
        // 隐藏口优先级最高：它就是别的设备真正连得上的那个地址
        out.push(info);
        Log.i(TAG, `隐藏子网命中: ${host} 属于本机（网段 ${seg.network}/${seg.mask}）`);
      }
    }
    return out;
  }

  /**
   * 读 `/proc/net/route`，返回**直连**网段。
   * 格式（十六进制小端）：
   *   Iface  Destination  Gateway  Flags  ...  Mask
   *   wlan1  002BA8C0     00000000 0001   ...  00FFFFFF
   * `002BA8C0` 反序就是 192.168.43.0。Gateway 全 0 = 直连（没有下一跳）。
   */
  static readDirectRoutes(verbose: boolean = false): RouteEntry[] {
    const res: RouteEntry[] = [];
    let fd: number = -1;
    try {
      const file: fileIo.File = fileIo.openSync('/proc/net/route', fileIo.OpenMode.READ_ONLY);
      fd = file.fd;
      const buf: ArrayBuffer = new ArrayBuffer(16384);
      const got: number = fileIo.readSync(fd, buf);
      const text: string = LanDiscovery.asciiFromBytes(new Uint8Array(buf, 0, got));
      const lines: string[] = text.split('\n');
      for (let i = 1; i < lines.length; i++) {
        const cols: string[] = LanDiscovery.splitColumns(lines[i]);
        if (cols.length < 8) {
          continue;
        }
        const dest: string = LanDiscovery.hexLeToIp(cols[1]);
        const gateway: string = LanDiscovery.hexLeToIp(cols[2]);
        const flags: number = Number.parseInt(cols[3], 16);
        const mask: string = LanDiscovery.hexLeToIp(cols[7]);
        if (dest.length === 0 || mask.length === 0) {
          continue;
        }
        // 0x0001 = RTF_UP；直连路由的特征是 Gateway 为 0.0.0.0
        if ((flags & 0x1) === 0) {
          continue;
        }
        if (gateway !== '0.0.0.0') {
          continue;
        }
        // 0.0.0.0/0 是默认路由，不算直连局域网
        if (dest === '0.0.0.0' || mask === '0.0.0.0') {
          continue;
        }
        res.push({ network: dest, mask: mask });
      }
      Log.i(TAG, `路由表读到 ${res.length} 条直连网段: ${LanDiscovery.joinRoutes(res)}`);
    } catch (e) {
      // 应用沙箱读不到 /proc/net/route 是**预期内**的，不算错误，但必须记一笔
      const err: BusinessError = e as BusinessError;
      if (verbose) {
        Log.i(TAG, `读 /proc/net/route 不可用(走常见网段兜底): ${err.code}`);
      }
    } finally {
      if (fd >= 0) {
        try {
          fileIo.closeSync(fd);
        } catch (e) {
          // ignore
        }
      }
    }
    return res;
  }

  /** 网段首个可用主机地址（192.168.43.0 -> 192.168.43.1） */
  static segmentFirstHost(network: string): string {
    const p: number[] = LanDiscovery.parseIpv4(network);
    if (p.length !== 4) {
      return '';
    }
    return `${p[0]}.${p[1]}.${p[2]}.${p[3] + 1}`;
  }

  /** ip 是否落在 network/mask 这个网段里 */
  static sameSegment(ip: string, network: string, mask: string): boolean {
    const a: number[] = LanDiscovery.parseIpv4(ip);
    const b: number[] = LanDiscovery.parseIpv4(network);
    const m: number[] = LanDiscovery.parseIpv4(mask);
    if (a.length !== 4 || b.length !== 4 || m.length !== 4) {
      return false;
    }
    for (let i = 0; i < 4; i++) {
      if ((a[i] & m[i]) !== (b[i] & m[i])) {
        return false;
      }
    }
    return true;
  }

  /** 点分掩码 -> 前缀长度 */
  static maskToPrefix(mask: string): number {
    const m: number[] = LanDiscovery.parseIpv4(mask);
    if (m.length !== 4) {
      return 24;
    }
    let n: number = 0;
    for (let i = 0; i < 4; i++) {
      let b: number = m[i];
      while (b !== 0) {
        n += b & 1;
        b = b >> 1;
      }
    }
    return n;
  }

  /**
   * 试探某个 IP 是不是本机地址。
   *
   * 原理：`bind()` 到一个不属于本机的地址会直接失败。
   * 这是拿不到接口列表时，唯一能确认"这个 IP 是不是我的"的办法 ——
   * 而 devIp 写错就等于告诉对端一个连不上的地址（原版 Android 是**照单全收**
   * 包里的 devIp 的，见 LANService.handleUdp：`device.setDevIP(devIp)`）。
   */
  static async isLocalAddress(ip: string): Promise<boolean> {
    let s: socket.UDPSocket | null = null;
    try {
      s = socket.constructUDPSocketInstance();
      await s.bind({ address: ip, port: 0, family: 1 });
      return true;
    } catch (e) {
      return false;
    } finally {
      if (s !== null) {
        try {
          s.close();
        } catch (e) {
          // ignore
        }
      }
    }
  }

  /**
   * 探测「某个网段里属于本机」的那个地址（软 AP 场景是网段的第一个地址）。
   *
   * @param network 网段首地址，如 192.168.43.0
   */
  static async probeSegment(network: string): Promise<LocalNetInfo> {
    const host: string = LanDiscovery.segmentFirstHost(network);
    if (host.length === 0) {
      return new LocalNetInfo();
    }
    const mine: boolean = await LanDiscovery.isLocalAddress(host);
    if (!mine) {
      return new LocalNetInfo();
    }
    const info: LocalNetInfo = LanDiscovery.buildNetInfo(host, 24, 'peer-learned', -1);
    if (info.valid) {
      Log.i(TAG, `按对端所在网段反查到本机地址 ${host}（${network}/24）`);
    }
    return info;
  }

  /** 十六进制小端 -> 点分十进制（002BA8C0 -> 192.168.43.0） */
  static hexLeToIp(hex: string): string {
    if (hex.length !== 8) {
      return '';
    }
    const v: number = Number.parseInt(hex, 16);
    if (Number.isNaN(v)) {
      return '';
    }
    return `${v & 0xFF}.${(v >>> 8) & 0xFF}.${(v >>> 16) & 0xFF}.${(v >>> 24) & 0xFF}`;
  }

  /** 按空白切列（不用正则，ArkTS 静态检查更稳） */
  static splitColumns(line: string): string[] {
    const raw: string[] = line.split(' ');
    const out: string[] = [];
    for (let i = 0; i < raw.length; i++) {
      const one: string = raw[i].replace('\t', '').replace('\r', '');
      if (one.length > 0) {
        out.push(one);
      }
    }
    return out;
  }

  /** Uint8Array -> ASCII 字符串（避免引入 TextDecoder） */
  static asciiFromBytes(b: Uint8Array): string {
    let s: string = '';
    for (let i = 0; i < b.length; i++) {
      s += String.fromCharCode(b[i]);
    }
    return s;
  }

  static joinRoutes(list: RouteEntry[]): string {
    const parts: string[] = [];
    for (let i = 0; i < list.length; i++) {
      parts.push(`${list[i].network}/${list[i].mask}`);
    }
    return parts.join(' | ');
  }

  /**
   * 单个地址 -> LocalNetInfo。不合法的返回 ip 为空的对象。
   *
   * 过滤规则（每一条都是真机上真会踩的）：
   *   127.x        环回，广播没有意义
   *   169.254.x    APIPA，没拿到 DHCP 时的假地址，发它只会浪费
   *   prefix >= 32 点对点接口（蜂窝网常见 /32），广播地址就是自己，等于单播
   *   广播算不出来 掩码异常
   */
  private static buildNetInfo(addr: string, prefix: number, iface: string, bearer: number): LocalNetInfo {
    const info: LocalNetInfo = new LocalNetInfo();
    if (addr.length === 0 || addr.includes(':')) {
      return info;
    }
    const parts: number[] = LanDiscovery.parseIpv4(addr);
    if (parts.length !== 4) {
      return info;
    }
    if (parts[0] === 127 || (parts[0] === 169 && parts[1] === 254) || parts[0] === 0) {
      return info;
    }
    if (prefix >= 32) {
      return info;
    }
    const mask: string = LanDiscovery.prefixToMask(prefix);
    const bcast: string = LanDiscovery.calcBroadcast(addr, mask);
    if (bcast.length === 0) {
      return info;
    }
    info.ip = addr;
    info.netMask = mask;
    info.broadcastIp = bcast;
    info.interfaceName = iface;
    info.isIPv4 = true;
    info.bearer = bearer;
    return info;
  }

  /** 非蜂窝优先。局域网互传的目标地址必须是能被对端直连的那个 */
  private static sortNets(list: LocalNetInfo[]): LocalNetInfo[] {
    const lan: LocalNetInfo[] = [];
    const cell: LocalNetInfo[] = [];
    for (let i = 0; i < list.length; i++) {
      if (list[i].bearer === 0) {
        cell.push(list[i]);
      } else {
        lan.push(list[i]);
      }
    }
    for (let i = 0; i < cell.length; i++) {
      lan.push(cell[i]);
    }
    return lan;
  }

  /**
   * 取**首选**网络（供展示与 self.devIp 用）。
   * 兼容旧的单一网络调用点；内部走 resolveAllLocalNets 取排序后的第一个。
   */
  static async resolveLocalNet(): Promise<LocalNetInfo> {
    const all: LocalNetInfo[] = await LanDiscovery.resolveAllLocalNets();
    if (all.length > 0) {
      return all[0];
    }
    // getAllNets 在某些机型上可能返回空，退回默认网络再试一次
    const fallback: LocalNetInfo = new LocalNetInfo();
    try {
      const net: connection.NetHandle = await connection.getDefaultNet();
      const props: connection.ConnectionProperties = await connection.getConnectionProperties(net);
      for (let i = 0; i < props.linkAddresses.length; i++) {
        const la: connection.LinkAddress = props.linkAddresses[i];
        const info: LocalNetInfo = LanDiscovery.buildNetInfo(
          la.address.address, la.prefixLength, props.interfaceName, -1);
        if (info.valid) {
          return info;
        }
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `取本机网络信息失败: ${err.code} ${err.message}`);
    }
    return fallback;
  }

  /**
   * 前缀长度 -> 点分十进制掩码。
   * 例：24 -> 255.255.255.0，16 -> 255.255.0.0
   *
   * 鸿蒙的 LinkAddress 只给 prefixLength，而原协议（要与 Android 端互通）
   * 传的是点分掩码，所以必须在这里换算回去。
   */
  static prefixToMask(prefix: number): string {
    if (prefix <= 0) {
      return '0.0.0.0';
    }
    if (prefix >= 32) {
      return '255.255.255.255';
    }
    // 32 位全 1 左移 (32 - prefix) 位，再按字节拆开
    const bits: number = (0xFFFFFFFF << (32 - prefix)) >>> 0;
    return `${(bits >>> 24) & 0xFF}.${(bits >>> 16) & 0xFF}.${(bits >>> 8) & 0xFF}.${bits & 0xFF}`;
  }

  /**
   * broadcast = ip | ~netmask
   * 例：192.168.10.20 / 255.255.255.0 -> 192.168.10.255
   */
  static calcBroadcast(ip: string, netMask: string): string {
    const a: number[] = LanDiscovery.parseIpv4(ip);
    const m: number[] = LanDiscovery.parseIpv4(netMask);
    if (a.length !== 4 || m.length !== 4) {
      return '';
    }
    const out: number[] = [];
    for (let i = 0; i < 4; i++) {
      out.push((a[i] | (~m[i] & 0xFF)) & 0xFF);
    }
    return `${out[0]}.${out[1]}.${out[2]}.${out[3]}`;
  }

  static parseIpv4(ip: string): number[] {
    const parts: string[] = ip.split('.');
    if (parts.length !== 4) {
      return [];
    }
    const out: number[] = [];
    for (let i = 0; i < 4; i++) {
      const n: number = Number.parseInt(parts[i], 10);
      if (Number.isNaN(n) || n < 0 || n > 255) {
        return [];
      }
      out.push(n);
    }
    return out;
  }

  /** 建立接收套接字并开始监听 */
  async start(udpPort: number = this.udpPort): Promise<boolean> {
    if (this.running) {
      return true;
    }
    this.udpPort = udpPort;
    this.seenPeers = [];
    try {
      this.recvSocket = socket.constructUDPSocketInstance();
      // 必须绑 0.0.0.0，绑具体 IP 就收不到广播
      await this.recvSocket.bind({ address: '0.0.0.0', port: this.udpPort, family: 1 });
      // 组播/广播开关，对应 Java 的 DatagramSocket.setBroadcast(true)
      await this.recvSocket.setExtraOptions({ broadcast: true, reuseAddress: true });

      this.recvSocket.on('message', (info: socket.SocketMessageInfo) => {
        this.onDatagram(info);
      });
      this.recvSocket.on('error', (e: BusinessError) => {
        Log.w(TAG, `UDP 接收错误: ${e.code} ${e.message}`);
      });

      this.sendSocket = socket.constructUDPSocketInstance();
      await this.sendSocket.bind({ address: '0.0.0.0', port: 0, family: 1 });
      await this.sendSocket.setExtraOptions({ broadcast: true });

      this.running = true;
      Log.i(TAG, `UDP 发现已启动，监听 0.0.0.0:${this.udpPort}`);
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `UDP 启动失败: ${err.code} ${err.message}`);
      this.stop();
      return false;
    }
  }

  private onDatagram(info: socket.SocketMessageInfo): void {
    const datagram: Uint8Array = new Uint8Array(info.message);
    // 每个来源 IP 只记一次。UDP 心跳是每 5s 一轮，全记会把 hilog 冲爆，
    // 但「有没有收到对端的包」恰恰是热点单向可见排障的关键证据 —— 必须能看到。
    const from: string = info.remoteInfo.address;
    if (this.seenPeers.indexOf(from) < 0) {
      this.seenPeers.push(from);
      Log.i(TAG, `收到 UDP 包: 源 ${from}:${info.remoteInfo.port}，${datagram.length} 字节`);
    }
    // 解析**完整**帧：只调 parseHeartbeat 会把 1004/1005（文本消息）丢掉
    const frame: UdpFrame | null = DeviceCodec.parseUdpFrame(datagram);
    if (frame === null) {
      return;
    }
    if (frame.cmd === LCmd.UDP_DEVICES_MESSAGE ||
      frame.cmd === LCmd.UDP_DEVICES_MESSAGE_TO_CLIPBOARD) {
      Log.i(TAG, `收到 UDP 文本消息 cmd=${frame.cmd}，来自 ${from}`);
    }
    const device: LanDevice = frame.device;
    // remoteInfo 里的地址比包里的 devIp 更可信（防伪造）。
    // 注意：这只影响**我们**怎么记；原版 Android 是照单全收包里的 devIp 的。
    if (device.devIp.length === 0) {
      device.devIp = from;
    }
    if (this.onFound !== null) {
      this.onFound(frame, from, info.remoteInfo.port);
    }
  }

  /**
   * 向子网广播地址发送一个包。
   * 对应 Android UDPTools.sendData()。
   */
  async broadcastTo(packet: Uint8Array, targetIp: string): Promise<void> {
    if (this.sendSocket === null) {
      Log.w(TAG, '发送套接字未就绪');
      return;
    }
    try {
      const buf: ArrayBuffer = packet.buffer.slice(
        packet.byteOffset, packet.byteOffset + packet.byteLength
      ) as ArrayBuffer;
      const dest: socket.NetAddress = { address: targetIp, port: this.udpPort, family: 1 };
      await this.sendSocket.send({ data: buf, address: dest });
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `广播失败 -> ${targetIp}: ${err.code} ${err.message}`);
    }
  }

  /**
   * **单播**一个包到指定 IP（端口用发现端口）。
   *
   * 用途：「收到别人的 UDP_GET_DEVICES → 立刻单播回自己的心跳」。
   * 原逻辑里双方都只按自己的 5s 周期广播，于是**互相发现最多要等一整个周期**
   * （vivi 2026-10-01：「发现设备有点慢」）。
   * 探测方主动问了，我们直接回答，一轮广播内双方就都认识了。
   */
  async sendTo(packet: Uint8Array, ip: string): Promise<void> {
    if (this.sendSocket === null) {
      Log.w(TAG, '发送套接字未就绪');
      return;
    }
    if (ip.length === 0) {
      return;
    }
    try {
      const buf: ArrayBuffer = packet.buffer.slice(
        packet.byteOffset, packet.byteOffset + packet.byteLength
      ) as ArrayBuffer;
      const dest: socket.NetAddress = { address: ip, port: this.udpPort, family: 1 };
      await this.sendSocket.send({ data: buf, address: dest });
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `单播失败 -> ${ip}:${this.udpPort}: ${err.code} ${err.message}`);
    }
  }

  /**
   * 主动探测：广播 UDP_GET_DEVICES，请在线设备立刻回心跳。
   *
   * @param nets **所有**待广播的子网。每个子网发一份，报文 devIp 用该子网的接口 IP。
   */
  async probe(nets: LocalNetInfo[]): Promise<void> {
    if (this.self === null) {
      Log.w(TAG, '未设置本机信息，无法探测');
      return;
    }
    for (let i = 0; i < nets.length; i++) {
      const net: LocalNetInfo = nets[i];
      if (!net.valid || net.broadcastIp.length === 0) {
        continue;
      }
      const packet: Uint8Array = DeviceCodec.buildHeartbeat(this.self, LCmd.UDP_GET_DEVICES, net.ip);
      // 定向广播 + 受限广播都发一份，兼容不同路由器对广播的处理策略
      await this.broadcastTo(packet, net.broadcastIp);
      await this.broadcastTo(packet, '255.255.255.255');
    }
  }

  /** 心跳上报：广播 UDP_SET_DEVICES，让对端刷新我的在线时间 */
  async heartbeat(nets: LocalNetInfo[]): Promise<void> {
    if (this.self === null) {
      return;
    }
    for (let i = 0; i < nets.length; i++) {
      const net: LocalNetInfo = nets[i];
      if (!net.valid || net.broadcastIp.length === 0) {
        continue;
      }
      const packet: Uint8Array = DeviceCodec.buildHeartbeat(this.self, LCmd.UDP_SET_DEVICES, net.ip);
      await this.broadcastTo(packet, net.broadcastIp);
    }
  }

  /** 下线通知：告诉同网段设备我要走了 */
  async announceOffline(nets: LocalNetInfo[]): Promise<void> {
    if (this.self === null) {
      return;
    }
    for (let i = 0; i < nets.length; i++) {
      const net: LocalNetInfo = nets[i];
      if (!net.valid || net.broadcastIp.length === 0) {
        continue;
      }
      const packet: Uint8Array = DeviceCodec.buildOffline(this.self, net.ip);
      await this.broadcastTo(packet, net.broadcastIp);
      await this.broadcastTo(packet, '255.255.255.255');
    }
  }

  /**
   * 启动周期性扫描：每 SCAN_TIME 秒探测一次 + 心跳一次。
   * 对应 Android 的扫描定时器（Config.SCANN_TIME = 5s）。
   *
   * @param nets 全部待广播的子网（热点 / WiFi / 有线可能同时存在）
   */
  startPeriodicScan(nets: LocalNetInfo[]): void {
    if (this.timerId !== -1) {
      return;
    }
    this.scanNets = nets;
    const tick: () => void = () => {
      this.probe(this.scanNets).then(() => {
        return this.heartbeat(this.scanNets);
      }).catch((e: Error) => {
        Log.w(TAG, `周期扫描异常: ${e.message}`);
      });
    };
    tick();
    // ---- 启动 burst：快速收敛 ----
    // 只发一次的话，对端若正好在两次广播之间、或首包丢在空口上，就要再等整整
    // SCAN_TIME(5s) 才被发现 —— 这是「刚打开应用要愣几秒才看到设备」的主因。
    // 开场 0.7s / 1.8s 各再补一轮（间隔刻意错开，不与自己形成共振），
    // 之后回到正常周期。代价只有两个额外的广播包。
    setTimeout(() => {
      this.probe(this.scanNets).then(() => this.heartbeat(this.scanNets))
        .catch((e: Error) => Log.w(TAG, `启动补探异常: ${e.message}`));
    }, 700);
    setTimeout(() => {
      this.probe(this.scanNets).then(() => this.heartbeat(this.scanNets))
        .catch((e: Error) => Log.w(TAG, `启动补探异常: ${e.message}`));
    }, 1800);
    this.timerId = setInterval(tick, LanConfig.SCAN_TIME * 1000);
    Log.i(TAG, `周期扫描已启动，间隔 ${LanConfig.SCAN_TIME}s，覆盖 ${nets.length} 个子网（开场 0.7s/1.8s 各补一轮）`);
  }

  /**
   * 换掉正在广播的子网列表（网络变化后调用，不需要重启发现服务）。
   *
   * 为什么不能只在 startPeriodicScan 时传一次：
   * 用户完全可能"先点开始共享，再打开热点"。那时我们手里一个可广播子网都没有，
   * 若列表是死的，热点网段的设备就永远发现不了我们。
   */
  updateNets(nets: LocalNetInfo[]): void {
    this.scanNets = nets;
  }

  stopPeriodicScan(): void {
    if (this.timerId !== -1) {
      clearInterval(this.timerId);
      this.timerId = -1;
    }
  }

  stop(): void {
    this.stopPeriodicScan();
    if (this.sendSocket !== null) {
      try {
        this.sendSocket.off('message');
        this.sendSocket.close();
      } catch (e) {
        // ignore
      }
      this.sendSocket = null;
    }
    if (this.recvSocket !== null) {
      try {
        this.recvSocket.off('message');
        this.recvSocket.close();
      } catch (e) {
        // ignore
      }
      this.recvSocket = null;
    }
    this.running = false;
    Log.i(TAG, 'UDP 发现已停止');
  }
}
