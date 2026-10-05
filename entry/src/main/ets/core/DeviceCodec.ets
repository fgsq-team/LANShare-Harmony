/**
 * 设备模型与 UDP 心跳报文编解码
 *
 * 平移自：
 *   app/src/main/java/com/fgsqw/lanshare/pojo/Device.java
 *   app/src/main/java/com/fgsqw/lanshare/service/LANService.java  的 udpServer()/handleUdp()
 *
 * ## UDP 心跳报文 payload 布局（大端，字段顺序已从 makeDataEncUdp + handleUdp 双向核对）
 * ```
 * putInt     devPort              文件服务 TCP 端口
 * putString  devIp                设备 IP
 * putString  devName              设备显示名
 * putInt     devMode              平台代号，见 DeviceMode
 * putString  uniqueUuid + "-" + DATA_VERSION     兼容旧版的拼接写法
 * putInt     DATA_VERSION_3       历史遗留字段（读取方会用 uuid 后缀覆盖它）
 * putInt     batteryLevel         电量 0-100，-1 表示未知
 * putByte    chargeStatus         充电状态，-1 表示未知
 * ```
 * 外层再套 DataPacket 的 12 字节头 + MAGIC(4)。
 *
 * ## 注意
 * `devName` 在 Android 端由 `getDevName()` 提供，可能与心跳里携带的名字不同
 * （发送端用 `device.getDevName()`，接收端用包里的 `devName`）——迁移时保持一致即可。
 */
import { DataDec, DataEnc } from './DataPacket';
import { LCmd } from './LCmd';
import { LanConfig } from './LanConfig';
import { JsonNode, JsonParseResult, MiniJson } from './MiniJson';
import { Log } from './Logger';
import { V5Udp, V5UdpFrame } from './V5Codec';

const TAG: string = 'DeviceCodec';

/** 平台代号。与 Android Device.java 的常量数值完全一致 —— 不可改动 */
export class DeviceMode {
  static readonly UNKNOWN: number = -1;
  static readonly ANDROID: number = 1;
  static readonly WINDOWS: number = 2;
  static readonly LINUX: number = 3;
  static readonly MAC_OS: number = 4;
  static readonly IOS: number = 5;
  /** 鸿蒙。原协议里已经预留了这个槽位（Device.HARMONY_OS = 6） */
  static readonly HARMONY_OS: number = 6;
  /** 浏览器端 */
  static readonly WEB: number = 7;
}

/** 平台代号 -> 厂商展示名。对应 Device.getManufacturer() */
export function manufacturerOf(mode: number): string {
  switch (mode) {
    case DeviceMode.ANDROID: return 'Android';
    case DeviceMode.IOS: return 'ios';
    case DeviceMode.WINDOWS: return 'Windows';
    case DeviceMode.LINUX: return 'Linux';
    case DeviceMode.MAC_OS: return 'Mac OS';
    case DeviceMode.HARMONY_OS: return 'Harmony OS';
    case DeviceMode.WEB: return 'Web';
    default: return 'Unknow';
  }
}

/**
 * 局域网内的一个对端设备。
 * 字段与 Android Device.java 对齐；去掉了 UI 相关的引用（webSocketServer）。
 */
export class LanDevice {
  devName: string = '';
  devIp: string = '';
  devNetMask: string = '';
  devBroadcastIp: string = '';
  uniqueUuid: string = '';
  devPort: number = LanConfig.DEFAULT_FILE_SERVER_PORT;
  devMode: number = DeviceMode.UNKNOWN;
  /** 最后一次心跳的本地时间戳（毫秒）。替代 Android 的 setTime */
  lastSeenMs: number = 0;
  dataVersion: number = 0;
  isIPv4: boolean = true;
  canRemove: boolean = true;
  interfaceName: string = '';
  batteryLevel: number = -1;
  chargeStatus: number = -1;

  constructor(devName: string = '', devIp: string = '', devPort: number = 0) {
    this.devName = devName;
    this.devIp = devIp;
    this.devPort = devPort;
  }

  get manufacturer(): string {
    return manufacturerOf(this.devMode);
  }

  /** 是否已判定离线。对应 Android 侧 setTime 超时判断 */
  isOffline(nowMs: number): boolean {
    return nowMs - this.lastSeenMs > LanConfig.DEVICE_OFFLINE_MS;
  }

  clone(): LanDevice {
    const d: LanDevice = new LanDevice(this.devName, this.devIp, this.devPort);
    d.devNetMask = this.devNetMask;
    d.devBroadcastIp = this.devBroadcastIp;
    d.uniqueUuid = this.uniqueUuid;
    d.devMode = this.devMode;
    d.lastSeenMs = this.lastSeenMs;
    d.dataVersion = this.dataVersion;
    d.isIPv4 = this.isIPv4;
    d.canRemove = this.canRemove;
    d.interfaceName = this.interfaceName;
    d.batteryLevel = this.batteryLevel;
    d.chargeStatus = this.chargeStatus;
    return d;
  }
}

/**
 * 一个 UDP 数据报解析结果。
 *
 * ⚠️ 为什么不能只返回 device：原协议里**所有** UDP 命令共用同一段设备头
 * （`makeDataEncUdp` 的 8 个字段），命令字不同只体现在**头后面多出来的参数**上：
 *   1004/1005 文本消息   -> 头 + 密文消息 + 包名
 *   1006~1010 媒体控制   -> 头（无附加）
 *   1011     位置消息     -> 头 + 内容
 * 早期实现只认 1001/1002，其余一律 return null —— 直接后果就是
 * **安卓端发过来的短文本（走 UDP 1004）一格都收不到**。
 */
export class UdpFrame {
  device: LanDevice = new LanDevice();
  cmd: number = 0;
  /** 设备头之后剩下的字符串参数（按出现顺序） */
  extras: string[] = [];
  /** v5 新增：对端附带的「已知设备表」。收到后可以用来提前认识全网设备 */
  known: LanDevice[] = [];
}

export class DeviceCodec {
  /**
   * 解析任意 UDP 数据报：设备头 + 命令字 + 附加字符串参数。
   * 对应 LANService.handleUdp() 的前半段（读 8 个设备字段），
   * 附加参数留给各命令的处理器（对应 handleUdpCmd 里的 dataDec.getString()）。
   */
  /**
   * 解析任意 UDP 数据报（**v5 格式**）。
   *
   * ⚠️ 与 v4 的实现已经不是同一套字节：v5 是「MAGIC + 链式混淆(12 帧头 + 设备头)」，
   * 设备头里还多了一张「已知设备表」。这里整体切到 `V5Udp`，签名保持不变，
   * 上层（LanDiscovery）不用改。
   */
  static parseUdpFrame(datagram: Uint8Array): UdpFrame | null {
    const v5: V5UdpFrame | null = V5Udp.parse(datagram);
    if (v5 === null) {
      return null;
    }
    const frame: UdpFrame = new UdpFrame();
    frame.cmd = v5.cmd;
    frame.device = v5.device;
    frame.extras = v5.extras;
    frame.known = v5.known;
    return frame;
  }
  /**
   * 构造本机的心跳/应答报文 payload。
   * 对应 LANService.makeDataEncUdp()。
   *
   * @param self 本机设备信息
   * @param cmd  LCmd.UDP_SET_DEVICES（心跳上报）或 UDP_GET_DEVICES（应答探测）
   * @param ipOverride 强制写入报文的 IP。多网卡时必须按「往哪个子网发」填对应接口的 IP。
   *
   * ⚠️ 为什么要这个参数：包里的 devIp 是**对端回连我 5856 端口用的地址**。
   *    手机开热点时，`getDefaultNet()` 通常是蜂窝网（热点共享的就是它），
   *    若照抄这个 IP 广播出去，热点下的设备拿到的是 10.x 蜂窝地址，
   *    连不上我 —— 现象就是「我能发现你，你发现不了我」。
   *    所以每个子网必须用**那个子网自己的接口 IP** 各发一份。
   */
  /**
   * 构造本机的心跳/应答报文（**v5 格式**）。
   *
   * 与 v4 的三处差别：`DATA_VERSION` 写 5、设备头是二进制不是 DataEnc、
   * 整帧做链式混淆且前置 MAGIC。心跳的字段顺序本身没变。
   *
   * @param known 附带出去的已知设备表。1.35 用它做「一次广播认识全网」，
   *              传空数组完全合法 —— 只是少了这个加速。
   */
  static buildHeartbeat(self: LanDevice, cmd: number, ipOverride: string = '',
    known: LanDevice[] = []): Uint8Array {
    // ipOverride 是「往哪个子网发就填那个子网的接口 IP」，必须盖掉包里的 devIp
    const copy: LanDevice = self.clone();
    if (ipOverride.length > 0) {
      copy.devIp = ipOverride;
    }
    return V5Udp.build(cmd, copy, known);
  }

  /**
   * 构造"设备下线"通知（UDP_DEVICES_OFF_LINE）。ipOverride 含义同 buildHeartbeat。
   *
   * ⚠️ 载荷必须是**完整的 8 字段设备头**，不能只写 uuid + ip：
   * 原版 `noticeDeviceStateByIp()` 对上线/下线用的是同一个 `makeDataEncUdp()`
   * （见 LANService 1746 行），只改命令字。而接收端 `handleUdp()` 是无条件
   * 按 8 个字段读的 —— 少了字段就是对端解析错位，表现为"我下线了对方还留着我"。
   */
  static buildOffline(self: LanDevice, ipOverride: string = ''): Uint8Array {
    return DeviceCodec.buildHeartbeat(self, LCmd.UDP_DEVICES_OFF_LINE, ipOverride);
  }

  /**
   * 解析对端心跳。对应 LANService.handleUdp()。
   *
   * @param datagram UDP 收到的原始数据报
   * @returns 解析出的设备；不是 LanShare 报文或字段残缺时返回 null
   */
  static parseHeartbeat(datagram: Uint8Array): LanDevice | null {
    const frame: UdpFrame | null = DeviceCodec.parseUdpFrame(datagram);
    if (frame === null) {
      return null;
    }
    if (frame.cmd !== LCmd.UDP_GET_DEVICES && frame.cmd !== LCmd.UDP_SET_DEVICES) {
      // 其它 UDP 命令（消息广播、媒体控制等）不再在这里丢弃 ——
      // 调用方请改用 parseUdpFrame，否则会像早期版本那样漏掉 UDP 文本消息。
      return null;
    }
    if (frame.device.devIp.length === 0) {
      Log.w(TAG, '心跳包缺少 IP，丢弃');
      return null;
    }
    return frame.device;
  }

  /**
   * TCP 建链握手：客户端连上后先写 4 字节魔数。
   * 对应 LANService.makeSocket() —— 服务端也在第一个包里做协议分流。
   */
  static magicPrefix(): Uint8Array {
    return new Uint8Array([
      (LanConfig.MAGIC_NUM >>> 24) & 0xFF,
      (LanConfig.MAGIC_NUM >>> 16) & 0xFF,
      (LanConfig.MAGIC_NUM >>> 8) & 0xFF,
      LanConfig.MAGIC_NUM & 0xFF
    ]);
  }

  /**
   * 设备 -> JSON。字段名**逐字**对齐 Device.toJsonObject()，
   * 包括原代码里的两个拼写（devBrotIP / uniqueUUid）—— 改一个字
   * 对端就取不到值，而且是静默取不到（getString 返回 null）。
   *
   * v4 协议建链第二步就要发它（sendNewVersionFlag）。
   */
  static toJson(d: LanDevice): string {
    return '{'
      + `"devName":${MiniJson.quote(d.devName)},`
      + `"devIP":${MiniJson.quote(d.devIp)},`
      + `"devNetMask":${MiniJson.quote(d.devNetMask)},`
      + `"devBrotIP":${MiniJson.quote(d.devBroadcastIp)},`
      + `"uniqueUUid":${MiniJson.quote(d.uniqueUuid)},`
      + `"devPort":${d.devPort},`
      + `"devMode":${d.devMode},`
      + `"dataVersion":${d.dataVersion},`
      + `"isIPv4":${d.isIPv4 ? 'true' : 'false'},`
      + `"batteryLevel":${d.batteryLevel},`
      + `"chargeStatus":${d.chargeStatus}`
      + '}';
  }

  /**
   * JSON -> 设备。对应 Device.fromJsonString()。
   * 解析失败返回 null；字段缺失走默认值（与原实现的 JSONObject.getString 返回 null 一致，
   * 但我们用空串/0 更安全，避免后续拼接出 "null:5856" 这种地址）。
   */
  static fromJson(json: string): LanDevice | null {
    const res: JsonParseResult = MiniJson.parse(json);
    if (!res.ok) {
      Log.w(TAG, `设备 JSON 解析失败: ${res.error}`);
      return null;
    }
    const root: JsonNode = res.root;
    const d: LanDevice = new LanDevice();
    d.devName = DeviceCodec.field(root, 'devName');
    d.devIp = DeviceCodec.field(root, 'devIP');
    d.devNetMask = DeviceCodec.field(root, 'devNetMask');
    d.devBroadcastIp = DeviceCodec.field(root, 'devBrotIP');
    d.uniqueUuid = DeviceCodec.field(root, 'uniqueUUid');
    d.devPort = DeviceCodec.numField(root, 'devPort', LanConfig.DEFAULT_FILE_SERVER_PORT);
    d.devMode = DeviceCodec.numField(root, 'devMode', DeviceMode.UNKNOWN);
    d.dataVersion = DeviceCodec.numField(root, 'dataVersion', 0);
    d.isIPv4 = true;
    d.batteryLevel = DeviceCodec.numField(root, 'batteryLevel', -1);
    d.chargeStatus = DeviceCodec.numField(root, 'chargeStatus', -1);
    d.lastSeenMs = Date.now();
    return d;
  }

  private static field(root: JsonNode, key: string): string {
    const n: JsonNode | null = root.field(key);
    return n === null ? '' : n.asString('');
  }

  private static numField(root: JsonNode, key: string, def: number): number {
    const n: JsonNode | null = root.field(key);
    return n === null ? def : n.asNumber(def);
  }
}
