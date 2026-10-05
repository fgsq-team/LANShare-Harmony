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
import { DataDec, DataEnc } from './DataPacket.ts';
import { LCmd } from './LCmd.ts';
import { LanConfig } from './LanConfig.ts';
import { JsonNode, JsonParseResult, MiniJson } from './MiniJson.ts';
import { Log } from './Logger.ts';

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

export class DeviceCodec {
  /**
   * 构造本机的心跳/应答报文 payload。
   * 对应 LANService.makeDataEncUdp()。
   *
   * @param self 本机设备信息
   * @param cmd  LCmd.UDP_SET_DEVICES（心跳上报）或 UDP_GET_DEVICES（应答探测）
   */
  static buildHeartbeat(self: LanDevice, cmd: number): Uint8Array {
    // 预留 512 字节：设备名 + UUID + IP 足够，超出会自动扩容
    const enc: DataEnc = new DataEnc(512);
    enc.packData(cmd);
    enc.putInt(self.devPort);
    enc.putString(self.devIp);
    enc.putString(self.devName);
    enc.putInt(self.devMode);
    // 兼容旧版：把协议版本拼在 uuid 后面，接收方按 '-' 拆分
    enc.putString(`${self.uniqueUuid}-${LanConfig.DATA_VERSION}`);
    // 历史遗留字段，接收方会用它作为兜底 dataVersion
    enc.putInt(3);
    enc.putInt(self.batteryLevel);
    enc.putByte(self.chargeStatus);
    return enc.encodeUdp();
  }

  /** 构造"设备下线"通知（UDP_DEVICES_OFF_LINE） */
  static buildOffline(self: LanDevice): Uint8Array {
    const enc: DataEnc = new DataEnc(256);
    enc.packData(LCmd.UDP_DEVICES_OFF_LINE);
    enc.putString(self.uniqueUuid);
    enc.putString(self.devIp);
    return enc.encodeUdp();
  }

  /**
   * 解析对端心跳。对应 LANService.handleUdp()。
   *
   * @param datagram UDP 收到的原始数据报
   * @returns 解析出的设备；不是 LanShare 报文或字段残缺时返回 null
   */
  static parseHeartbeat(datagram: Uint8Array): LanDevice | null {
    const dec: DataDec | null = DataDec.fromUdp(datagram);
    if (dec === null) {
      return null;
    }
    const cmd: number = dec.getCmd();
    if (cmd !== LCmd.UDP_GET_DEVICES && cmd !== LCmd.UDP_SET_DEVICES) {
      // 其它 UDP 命令（消息广播、媒体控制等）由各自的处理器解析
      return null;
    }

    const d: LanDevice = new LanDevice();
    d.devPort = dec.readInt();
    d.devIp = dec.readString() ?? '';
    d.devName = dec.readString() ?? '';
    d.devMode = dec.readInt();
    d.uniqueUuid = dec.readString() ?? '';
    d.dataVersion = dec.readInt();
    d.batteryLevel = dec.readInt();
    d.chargeStatus = dec.readByte();
    d.lastSeenMs = Date.now();

    // 兼容旧版：uuid 形如 "<uuid>-<dataVersion>" 时以后缀为准
    const sep: number = d.uniqueUuid.lastIndexOf('-');
    if (sep > 0) {
      const versionPart: string = d.uniqueUuid.substring(sep + 1);
      const parsed: number = Number.parseInt(versionPart, 10);
      if (!Number.isNaN(parsed)) {
        d.dataVersion = parsed;
        d.uniqueUuid = d.uniqueUuid.substring(0, sep);
      }
    }

    if (d.devIp.length === 0) {
      Log.w(TAG, '心跳包缺少 IP，丢弃');
      return null;
    }
    return d;
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
