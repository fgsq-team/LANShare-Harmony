/**
 * LANShare 服务编排层 —— 对应 Android 的 service/LANService.java（2571 行）
 *
 * ## 架构对照
 * ```
 * Android LANService (started Service)          HarmonyOS LanService (单例 + UIAbility 上下文)
 * ├── onStartCommand()                           ├── startSharing(ctx)
 * ├── fileServer()   ServerSocket:5856           ├── LanTcpServer（含三协议分流）
 * ├── udpServer()    DatagramSocket:4573         ├── LanDiscovery
 * ├── ipGetSocket / multicastLock                └── （鸿蒙不需要 MulticastLock）
 * ├── NotificationUtils.showBackendNotification()├── LanSession（前台会话 + 屏幕常亮）
 * ├── handleTcp() / handleUdp()                  ├── onChannel() / DeviceCodec.parseHeartbeat
 * ├── sendBroadcast(LANShareReceiver...)          ├── 直接回调 UI（鸿蒙无静态广播）
 * └── getSystemService(Context.*)                 └── 通过 UIAbilityContext 取
 *
 * 为什么不再是"Service"：鸿蒙没有前台 Service，后台只有长时任务这一条通道，
 * 而长时任务的 dataTransfer 类型带「10 分钟无进度即取消」的硬约束。
 * **本项目的决策是不做后台保活**（vivi 2026-09-30）：需要传输时手动打开应用即可。
 * 于是本类变成"由 EntryAbility 持有生命周期的单例"，只在应用可见期间提供服务。
 *
 * ## 与 Android 的互通性
 * 端口（5856 / 4573）、魔数、命令码、字段布局全部保持一致，
 * 协议层已通过 tests/protocol-bytecheck 做了字节级对拍验证。
 */
import { common } from '@kit.AbilityKit';
import { fileIo } from '@kit.CoreFileKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { socket } from '@kit.NetworkKit';
import deviceInfo from '@ohos.deviceInfo';
import { preferences } from '@kit.ArkData';
import { LanConfig } from '../core/LanConfig';
import { LCmd } from '../core/LCmd';
import { Log } from '../core/Logger';
import { DataDec, DataEnc } from '../core/DataPacket';
import { AesCodec } from '../core/AesCodec';
import { DeviceCodec, DeviceMode, LanDevice, UdpFrame } from '../core/DeviceCodec';
import { JsonNode, JsonParseResult, MiniJson } from '../core/MiniJson';
import { ChannelHandler, LanTcpServer, ListenResult, ProtocolKind } from '../net/LanTcpServer';
import { TcpChannel } from '../net/NativeSocket';
import { ProtoIO } from '../net/ProtoIO';
import { HttpRouter, WsUpgradeRouter } from '../net/HttpRouter';
import { LanDiscovery, LocalNetInfo } from '../net/LanDiscovery';
import { WsProtocol } from '../net/WsProtocol';
import { DeviceStore } from '../store/DeviceStore';
import { LanSession } from './LanSession';
import { FileSink, FileSource, FileStorage, OutgoingFile } from './FileStorage';
import { FileTransfer, TransferReport } from './FileTransfer';
import { V5Transfer } from './V5Transfer';
import { V5Dec, V5Header } from '../core/V5Codec';
import { GrantOutcome, PermissionGate } from './PermissionGate';
import { WebClient, WebClientStore } from './WebClientStore';
import { WebSocketSession, WS_CMD_SYNC_DEVICE_LIST, WS_CMD_SEND_MESSAGE, WS_CMD_PUSH_FILES } from './WebSocketSession';
import { TextMessenger, TextSendResult } from './TextMessenger';

// ★★ ArkTS铁律：`import` 必须**全部连续**放在文件头。
//   在 import 区中间插入任何声明 ⇒ 后面的 import 变成 `arkts-no-misplaced-imports`（10605150）。

/** ★ 5.1.60「发送到网页端」零落盘要推给网页端的一项：一个授权 URI + 它要用的文件名 */
export class WebPushItem {
  /** picker / 相册给的授权 URI（`datashare://` 等），**不是沙箱路径** */
  uri: string = '';
  /** 网页端拼下载 URL 用的文件名（含扩展名） */
  name: string = '';

  constructor(uri: string = '', name: string = '') {
    this.uri = uri;
    this.name = name;
  }
}

const TAG: string = 'LanService';

/** 与 HttpRouter 共用的网页端设置文件 */
const PREF_WEB: string = 'lanshare_web';
/** 对应原 Config.WEB_OPEN */
const PREF_WEB_OPEN: string = 'webOpen';
/** 本机设备名等用户可改偏好（与网页偏好分开存，避免互相 flush 干扰） */
const PREF_CFG: string = 'lanshare_cfg';
/** 把外部文件搬进沙箱时的单块大小（供推送给网页端用） */
const STAGE_CHUNK: number = 256 * 1024;

/** 服务状态 */
export class ServiceState {
  static readonly STOPPED: number = 0;
  static readonly STARTING: number = 1;
  static readonly RUNNING: number = 2;
  static readonly FAILED: number = 3;
}

/** UI 订阅的状态快照 */
export class ServiceSnapshot {
  state: number = ServiceState.STOPPED;
  /** 本机 IP */
  localIp: string = '';
  /** 网页端访问地址，例如 http://192.168.10.20:5856 */
  webUrl: string = '';
  deviceName: string = '';
  /** 已发现的在线设备 */
  onlineDevices: number = 0;
  /** 历史记录里的设备总数 */
  knownDevices: number = 0;
  /** 当前 TCP 连接数 */
  connections: number = 0;
  /** 网页端请求数 */
  webRequests: number = 0;
  /**
   * 前台会话是否在运行。
   * 注意语义：**它不代表"后台在保活"**，只代表共享服务处于开启状态。
   * 本项目不做后台保活，退出应用即停服（见 LanConfig.AUTO_STOP_ON_BACKGROUND）。
   */
  sessionActive: boolean = false;
  /** 最近一条状态/错误文案 */
  message: string = '';
  /**
   * 真实监听状态描述（含端口校验与回环自检结果）。
   * ⚠️ 专门为排查「界面显示 5856 但外部连不上」这类静默故障而加：
   * 只要这里是「监听 0.0.0.0:5856，回环自检通过」，就能确定是本机监听没问题，
   * 故障一定在网络路径上，不用再猜。
   */
  listenDetail: string = '';
  /** 正在传输时的实时文案；空闲时为空串 */
  transferText: string = '';
  /** 正在传输的整体进度 0-100（浮层进度条用） */
  transferPercent: number = 0;
  /** ★ 5.1.41：实时速度，如「28.5 MB/s」；空串 = 不显示 */
  transferSpeed: string = '';
  /** ★ 5.1.41：副信息（序号 / 已收-总量），放进度条下方，
   *   不再挤在标题行里（★ 挤在那里会被长文件名顶出可视区） */
  transferSub: string = '';
  /** ★ 5.1.50：浮层标题的动词（与文件名分两个组件渲染，见 verbText 注释） */
  verb: string = '';
  /** ★ 5.1.42：**显式**完成态标记。
   *   ★ 5.1.41 曾用「transferText 以 ✓ 开头」来推断完成态，实测失效
   *   （不变色 / 地球不消失）—— 靠字符串前缀 + getter 读 @State 都不可靠。
   *   ⇒ 完成态必须是**独立字段**，由 `showRecvDoneFloat` 负责置位。 */
  transferDone: boolean = false;
  /** 接收文件的落盘位置说明 */
  saveLocation: string = '';
  /**
   * 等待用户确认的网页客户端。
   * 对应原 Android 的 SERVICE_HTTP_NEW_CLIENT 弹框 —— 网页端会一直停在
   * 「没有访问权限，请在手机上同意之后刷新页面」，直到这里点了「允许」。
   */
  pendingWebClients: WebClient[] = [];
  /** 「网页访问免确认」（对应原 Config.WEB_OPEN） */
  webOpen: boolean = false;
  /** 已连接的网页 WebSocket 会话数（网页端聊天通道） */
  wsClients: number = 0;
  /**
   * 聊天记录（内存态，最近 MAX_CHAT 条）。
   *
   * ⚠️ 这里是**唯一**给 UI 的聊天数据源，且必须整体替换数组引用
   * （见 LanService.chatList 的注释），否则 ArkUI 检测不到变化。
   */
  chat: ChatMessage[] = [];
  /** 最近若干条日志，供 UI 展示 */
  logLines: string[] = [];
}

/** 一条聊天消息（UI 直接渲染的模型） */
export class ChatMessage {
  id: string = '';
  /** true = 收到的（左侧气泡），false = 自己发出的（右侧气泡） */
  incoming: boolean = false;
  /** 对端名称（设备名 / 网页端 IP） */
  peerName: string = '';
  /** 对端 IP（用于按设备过滤，暂时不展示） */
  peerIp: string = '';
  content: string = '';
  /** 时间戳（毫秒） */
  timeMs: number = 0;
  /** 来源：device（局域网设备）/ web（浏览器网页端）/ app（本机发出） */
  source: string = 'device';
  /**
   * ★ 5.1.47：文件消息的**副信息**（`646.1 MB · 30.2 MB/s`）——
   *   文件大小 + **平均**速度。空串 = 不显示（如纯文本消息）。
   */
  meta: string = '';
  /** 是否投递成功。仅对「本机发出」有意义 */
  delivered: boolean = true;
  /**
   * 消息类型：`text` 普通文本 / `file` 文件传输记录。
   * `file` 的气泡显示文件名且**可点击** —— 点了跳到「文件」页看刚收/刚发的文件。
   */
  kind: string = 'text';
  files: string = '';
  /**
   * ★ 5.0.55：**批号** —— 同一次传输拆出来的多条媒体消息共享同一个值。
   *
   * ⚠️ 为什么要有它：5.0.53 把「接收 N 张图」拆成了 N 条消息（为了每张各有独立的
   *   相册条目与点击入口，修「删一张整批失效」），但界面上一个气泡一条显得碎。
   *   有了批号，UI 可以把同批的 N 条**聚合成一个气泡**、显示成宫格缩略图，
   *   而组内每条仍各自独立记账 —— 显示聚合 ≠ 记账聚合。
   *   （vivi 2026-10-02：「接受的图片和视频是否可以在一个气泡里显示多个缩略图」）
   *
   * 空串 = 不属于任何批次（单发、发送方向、文本消息、以及 5.0.55 之前的历史数据），
   * 这种消息在 UI 里各自成一个气泡 —— 与改动前行为完全一致。
   */
  batchId: string = '';
}

/**
 * ★ 5.0.55：**显示层**的分组 —— 一个「气泡」对应一条或多条消息。
 *
 * ⚠️ 只是视图模型，不参与任何记账：`msgs` 里的每个元素都是 `chatRing` 里的
 *   真实消息对象（同一引用），所以点第 k 张、删第 k 条全都走各自原本的逻辑。
 */
export class ChatGroup {
  /** ForEach 的 key（由 `Index.buildChatGroups` 按「会变的量」拼出来，见其注释） */
  key: string = '';
  /** 组内消息（按时间顺序）。长度 1 = 普通消息，>1 = 同批媒体 */
  msgs: ChatMessage[] = [];
  /** 整组是否都是「文件」类消息（宫格只对这类生效） */
  isFiles: boolean = false;
  /** 组内**全部**是图片/视频 —— 决定了渲染成宫格而不是文件名气泡 */
  isMedia: boolean = false;
  /**
   * ★ 5.0.56：宫格的**行**划分 —— 每行最多 3 个（在数据层切好，不在渲染层算）。
   *
   * ⚠️ 为什么要在数据层预切：宫格此前用 `Flex({ wrap: Wrap })` + **等比宽度**的格子，
   *   一行的个数取决于"还塞不塞得下下一个不同宽度的元素" ⇒ 实测不是固定 3 个
   *   （横图/竖图/方图宽度各不相同）。改成"固定框 + 手动分行"后，
   *   **结构上**就恒定每行 3 个，与图片比例彻底无关。
   */
  rows: ChatMessage[][] = [];
  incoming: boolean = true;
  timeMs: number = 0;
}

/** 聊天记录上限，防止长时间运行把内存吃满 */
/// ★★ 5.1.63 B2：200 → 1000。
///   vivi 2026-10-05 真机：批量发 429 个文件，清单 [425/425] 全部收到并落盘，
///   但聊天记录只留下 200 条 ⇒ 前 225 条被 chatRing.shift() 挤掉
///   ⇒ 日志「[相册] 新消息 0 -> 200」⇒ 用户以为「只收到 200 张」。
///   ★ 这是**内存态环形缓冲**条数，与「文件是否落盘」无关，两者不要混。
const MAX_CHAT: number = 1000;
/**
 * 聊天记录落盘防抖窗口（ms）。
 * 消息是人手输入的，但「一条消息同时群发给 N 台设备」会连着 append N 次 ——
 * 合并成一次写盘。
 */
const CHAT_SAVE_DEBOUNCE_MS: number = 800;
/** 聊天记录文件体积上限。超过就当成坏文件丢弃，不让它拖住启动 */
const CHAT_FILE_MAX_BYTES: number = 2 * 1024 * 1024;
/** 设备下线巡检间隔（ms）。1s 足够及时，开销可忽略 */
const DEVICE_SWEEP_MS: number = 1000;
/**
 * 网络重解析间隔。10s 一次：既能较快跟上"打开热点 / 连上 WiFi"这类变化，
 * 又不至于让每次解析（含隐藏接口探测）太频繁。
 */
const NET_REFRESH_MS: number = 10000;

export class LanService implements ChannelHandler {
  private static instance: LanService | null = null;

  static get(): LanService {
    if (LanService.instance === null) {
      LanService.instance = new LanService();
    }
    return LanService.instance;
  }

  private ctx: common.UIAbilityContext | null = null;
  private tcp: LanTcpServer = new LanTcpServer();
  private discovery: LanDiscovery = new LanDiscovery();
  private session: LanSession = new LanSession();
  private router: HttpRouter = new HttpRouter();
  readonly store: DeviceStore = new DeviceStore();

  private state: number = ServiceState.STOPPED;
  private self: LanDevice = new LanDevice();
  private localNet: LocalNetInfo = new LocalNetInfo();
  /**
   * 本机**全部**子网。热点 / WiFi / 有线可能同时在线，
   * UDP 广播必须每个子网都发一份，只发一个就会出现「单向可见」。
   */
  private localNets: LocalNetInfo[] = [];
  /** 周期重解析网络的句柄。网络是会变的，见 refreshNetworks */
  private netRefreshTimer: number = -1;
  /** 已经反查过的网段（前 3 段），避免对同一网段反复 bind 探测 */
  private probeSegments: string[] = [];
  /**
   * 最近一次「应答对方探测」的时间（IP -> ms）。
   * 节流用：对端可能高频广播 UDP_GET_DEVICES，我们无条件回包会把它放大成风暴。
   */
  private probeReplyAt: Map<string, number> = new Map<string, number>();
  /** 在线设备索引：uniqueUuid -> 设备 */
  private devices: Map<string, LanDevice> = new Map<string, LanDevice>();
  /** 活跃的网页 WebSocket 会话（设备列表推送 / 聊天靠它） */
  private wsSessions: WebSocketSession[] = [];
  /** 聊天记录环形缓冲（最近 MAX_CHAT 条），UI 的聊天页直接读它 */
  private chatRing: ChatMessage[] = [];
  /** 聊天记录自增序号，用于生成稳定 key */
  private chatSeq: number = 0;
  /** 聊天记录落盘路径；空串 = 还没恢复过（见 restoreChat） */
  private chatFile: string = '';
  /** 是否已经尝试过恢复聊天记录（幂等标记，UI 可能多次进页面） */
  private chatRestored: boolean = false;
  /** 聊天记录防抖落盘的定时器句柄，-1 = 无 */
  private chatSaveTimer: number = -1;
  /** 设备下线巡检定时器句柄，-1 = 无 */
  private sweepTimer: number = -1;
  /** 上一次巡检时的「在线设备签名」，用来判断是否真的有设备上下线 */
  private lastSweepSig: string = '';
  /**
   * 上一次**发出** UDP 单播探活的时刻（IP -> ms）。
   *
   * ⚠️ 它和「是否收到应答」无关：UDP 探活只用来让愿意应答的设备顺手刷新
   *    `lastSeenMs`，**不参与判死**。判死由下面的 TCP 复核负责
   *    （见 LanConfig.DEVICE_TCP_PROBE_* 那段长注释）。
   */
  private probeSentAt: Map<string, number> = new Map<string, number>();
  /** 该 IP 是否**正在**做 TCP 复核（单飞：同一台设备不并发 connect） */
  private tcpProbeBusy: Map<string, boolean> = new Map<string, boolean>();
  /** 该 IP 连续 TCP 复核失败的次数（任何一次成功、或心跳恢复都清零） */
  private tcpProbeMiss: Map<string, number> = new Map<string, number>();
  /** 该 IP 是否**曾经** TCP 复核成功过 —— 决定它有没有资格走 TCP 快速判死（安全阀） */
  private tcpEverOk: Map<string, boolean> = new Map<string, boolean>();
  /** 上一次 TCP 复核的发起时刻（IP -> ms），用于冷却 */
  private lastTcpProbeAt: Map<string, number> = new Map<string, number>();

  private snapshot: ServiceSnapshot = new ServiceSnapshot();
  private listeners: Array<(s: ServiceSnapshot) => void> = [];
  private logRing: string[] = [];
  // ---------------- 5.0.49：日志落盘（闪退取证） ----------------
  // 背景：vivi 真机「接收图片有概率闪退，重新打开后日志就消失了」——
  //       logRing 只在内存里，进程一崩证据就全没了，只能靠猜。
  /** 本次会话的日志文件（应用沙箱内），崩溃后依然留在磁盘上 */
  private logFile: string = '';
  /** 常开的追加写句柄；-1 = 还没初始化（此期间只进内存环形缓冲） */
  private logFd: number = -1;
  /** 已写入字节数，用于超限轮转 */
  private logBytes: number = 0;
  /**
   * 「接收完成」浮层的清除定时器句柄，-1 = 没挂。
   *   必须存句柄：连着传多个文件时，前一次的定时器要作废，
   *   否则会提前抹掉后一次的完成提示。
   * ★ 5.1.40：原先只服务网页上传（故名 uploadDoneTimer），
   *   现由 `showRecvDoneFloat` 统一供**所有**接收路径使用。
   */
  private doneFloatTimer: number = -1;
  /** ★ 5.1.47：最近一次完成传输的「大小 · 平均速度」，插消息气泡时用 */
  private lastTransferSummary: string = '';
  /**
   * ★ 5.1.50：浮层标题的**动词**（`接收` / `网页接收`），与文件名**分两个元素**渲染。
   *
   * ## 为什么不能拼进 `transferText`
   *   5.1.49 把 `接收 ${nm}` 拼成一个字符串给 `Text`，ArkUI **在空格处自动折行**
   *   ⇒ 「接收」独占第一行、文件名被挤到第二行且再次截断（vivi 截图）。
   * ★ 「同一段文本」≠「视觉同一行」—— 要保证同行，必须是**两个独立组件**。
   */
  private verbText: string = '';
  /** ★ 5.1.47：本次传输的**起始时刻**，用于算完成时的**平均速度** */
  private xferStartAt: number = 0;
  /** ★ 5.1.41：速度采样点（EMA 平滑，避免速度文字乱跳） */
  private speedBytes: number = 0;
  private speedAt: number = 0;
  private speedEma: number = 0;
  /** `run.lock`：启动时写、正常退出时删。 */
  private lockFile: string = '';
  /**
   * ★ 5.1.10：`crash.flag` —— 「上一次是闪退」的**持久化标记**。
   *
   * ⚠️⚠️ **为什么不能只看 `run.lock` 存不存在**（这是 5.0.49 一直以来的 bug）：
   *   `initLogFile` 在**同一次启动的末尾**又 `openSync(run.lock, CREATE|TRUNC)`
   *   把它写回来 ⇒ 下次启动 `accessSync` **必然为 true**
   *   ⇒ `prevCrashed` **每次启动都是 true** ⇒ 提示**每次都弹**（vivi 21:5x 反馈）。
   *
   * ★ 正确口径 = 「**上次退出时没走到 `markCleanExit`**」——
   *   那正是闪退的定义。所以：**lock 存在 ⇒ 本次启动写 `crash.flag`**，
   *   而 `markCleanExit` **同时删掉 lock 与 flag**。
   *   下次启动**只看 flag**（不看 lock 的存在性）⇒ 提示只在真闪退后出现一次。
   */
  private crashFlag: string = '';
  /** 上一次会话异常退出时保留下来的「崩溃前最后若干行」 */
  private crashTail: string[] = [];
  /** 上一次会话是否异常退出（UI 用来提示用户去复制日志） */
  prevCrashed: boolean = false;

  /** 网页客户端白名单（替代原 db/TokenDBUtil） */
  private webClients: WebClientStore = new WebClientStore();
  /** 接收文件的落盘策略（下载目录 / 沙箱） */
  private storage: FileStorage = new FileStorage();
  /** 同一时刻只允许一个主动发送任务，避免两条流互相抢带宽 */
  private transferBusy: boolean = false;
  /** 当前这次传输的对端 IP。只为「消息页的文件记录」提供 peerIp，用完即清 */
  private transferPeerIp: string = '';
  /** 上一次进度回调的累计字节，用于算增量 */
  private lastReportBytes: number = 0;
  /** 上一次「进度类」UI 刷新的时间戳（ms），用于合并高频 emit */
  private lastEmitAt: number = 0;
  /**
   * ★★ 5.1.30：`emitThrottled` 排队闸门的**时间上限**（毫秒）。
   *
   * 【为什么需要】`pendingEmitTimer` 只在 `setTimeout` 回调里被清；
   *   主线程被长任务占满时定时器回调可能被推迟/丢弃 ⇒ 标志位永久 >= 0
   *   ⇒ 此后**所有** `emitThrottled()` 都被 `return` 静默吞掉。
   *   真机症状：网页上传进度条卡在 19%（122MB）不动，而传输完全正常
   *   （`[UP]` 日志持续打到 586MB）—— 同一个循环，上报死了、传输活着。
   *
   * 【修法】闸门不再只依赖回调清除：距上次真正 emit 超过本值就**强制放行**，
   *   最多晚这么多毫秒必然自愈。
   */
  private static readonly EMIT_PENDING_MAX_MS: number = 500;
  /** 已排队的合并刷新定时器句柄，-1 = 无 */
  private pendingEmitTimer: number = -1;

  // ---------------- 5.0.51：emit 同步重入保护 ----------------
  /**
   * ★★ `emit()` 是**同步**把快照推给所有监听者，而监听者（Index.onSnapshot）
   *   里又可能调回页面层方法；页面的 `flushAutoSave()` 每步都 `logAuto()`，
   *   而 `logAuto()` 是**打完日志立刻 emit()** 的。于是一条完整的同步互相递归
   *   就成立了（vivi 2026-10-02 真机实测：同一秒刷出 200 条同一句
   *   「队列 1 项暂未解析出沙箱路径」，恰好把 200 条容量的日志环整个填满，
   *   紧接着传输就彻底不动了）：
   *
   *     flushAutoSave() -> logAuto() -> emit()
   *       -> onSnapshot() -> refreshReceived() -> flushAutoSave() -> logAuto() -> ...
   *
   *   驱动它的是 `onSnapshot` 里那句 `this.lastHadTransferText = hadTransfer;`
   *   写在 `refreshReceived()` **之后** —— 重入进来的那次看到的还是「刚才有传输」，
   *   于是又走一遍同一条分支，永远退不出来。（那处顺序也照修，见 Index.ets）
   *
   *   这里做**全局**兜底：正在 emit 时再进来的 emit 只登记一次「还要再刷」，
   *   等本次发完用 setTimeout 补一次。同步递归从此不可能发生。
   */
  private emitting: boolean = false;
  private emitQueued: boolean = false;

  private constructor() {
    this.tcp.setHandler(this);
    // TCP 层的关键事件（accept / 协议分流 / 断开原因）下沉到 UI 日志。
    // 这些事件原本只进 hilog，真机上用户看不到 —— 结果就是「连不上」时只能猜。
    // 现在一条 `新连接来自 x.x.x.x:port` 就能直接证明 accept 到底有没有发生。
    this.tcp.setLogSink((line: string) => {
      this.pushLog(line);
      // ⚠️ 这里**不能**用立即版 emit：分片传输时 16 条连接会在极短时间内
      //    打出 3×16=48 条日志，每条都整页重渲染正是卡顿的主要来源之一。
      this.emitThrottled();
    });
    this.session.setOnStateChange((running: boolean, message: string) => {
      this.snapshot.sessionActive = running;
      this.pushLog(message);
      this.emit();
    });
    // 网页新客户端待授权 —— 对应原 Android 的 SERVICE_HTTP_NEW_CLIENT 弹框。
    // 没有这条通路时，浏览器只会显示「没有访问权限，请在手机上同意之后刷新页面」，
    // 而手机上根本没有任何地方可以点「同意」。
    this.router.setOnNewClient((c: WebClient) => {
      this.onNewWebClient(c);
    });
    // WebSocket 升级完成后，通道所有权转移到这里。
    // 缺了这个 sink，升级后的通道会进 pending 队列无人认领，
    // 紧接着被 accept 循环 close 掉 —— 网页表现为「连接断开，请刷新」。
    WsUpgradeRouter.setSink((ch: TcpChannel) => {
      this.adoptWsChannel(ch);
    });
  }

  // ------------------------------------------------------------------
  // UI 订阅
  // ------------------------------------------------------------------

  subscribe(fn: (s: ServiceSnapshot) => void): void {
    // 5.0.51：同一函数重复订阅只登记一次 —— 监听者被叠加 N 份时，
    //   一次 emit 会触发 N 次 onSnapshot（含 N 次 refreshReceived），
    //   是日志风暴的放大器。
    if (this.listeners.indexOf(fn) < 0) {
      this.listeners.push(fn);
    }
    fn(this.snapshot);
  }

  unsubscribe(fn: (s: ServiceSnapshot) => void): void {
    const i: number = this.listeners.indexOf(fn);
    if (i >= 0) {
      this.listeners.splice(i, 1);
    }
  }

  get currentSnapshot(): ServiceSnapshot {
    return this.snapshot;
  }

  private emit(): void {
    // 5.0.51：★ 重入保护（见 `emitting` 字段的注释）。
    //   同步回调链里任何一环再次触发 emit，都只登记「补刷」一次，
    //   绝不在当前这一层里套进去 —— 那会变成无限递归 + 把日志环刷满。
    if (this.emitting) {
      this.emitQueued = true;
      return;
    }
    this.emitting = true;
    try {
      this.emitInner();
    } finally {
      this.emitting = false;
    }
    if (this.emitQueued) {
      this.emitQueued = false;
      // 延后一帧再补：此时监听者已经把「上次有没有传输」这类状态更新完了，
      // 不会再重走同一条分支（两帧内必定收敛）。
      setTimeout(() => {
        this.emit();
      }, 0);
    }
  }

  /** 真正下发快照（**只许 `emit()` 调**，外面别直接用它，绕开重入保护） */
  private emitInner(): void {
    // 刷新派生字段
    this.snapshot.state = this.state;
    this.snapshot.localIp = this.localNet.ip;
    // 用**实际绑定端口**而不是配置值：bind 失败时系统会静默换随机端口，
    // 那时展示配置值就是骗用户。
    const shownPort: number = this.tcp.listeningPort > 0
      ? this.tcp.listeningPort : LanConfig.fileServerPort;
    this.snapshot.webUrl = this.localNet.ip.length > 0
      ? `http://${this.localNet.ip}:${shownPort}`
      : '';
    this.snapshot.deviceName = this.self.devName;
    this.snapshot.connections = this.tcp.connectionCount;
    this.snapshot.webRequests = this.router.requestCount;
    this.snapshot.webOpen = this.router.isWebOpen;
    this.snapshot.pendingWebClients = this.webClients.pending();
    this.snapshot.chat = this.chatRing;
    // 5.0.49：上次异常退出的日志尾巴排在最前面 ——
    //         「复制日志」一次就能把崩溃现场带走（真机没有 hdc，这是唯一通路）。
    this.snapshot.logLines = this.crashTail.length > 0
      ? this.crashTail.concat(this.logRing) : this.logRing;
    const list: ServiceSnapshot = this.snapshot;
    for (let i = 0; i < this.listeners.length; i++) {
      this.listeners[i](list);
    }
  }

  /**
   * **节流版 emit** —— 只给「高频进度类」刷新用，终态仍走上面的立即版。
   *
   * 背景（vivi 2026-10-01 真机：「传输过程中手机界面很卡」）：
   * `emit()` 会把整页快照重新下发（UI 侧 `this.snapshot = s` → 整页重渲染）。
   * 一次大文件传输会触发：
   *   · 进度上报：1101 路径约 100 次（每 1% 一次）；1110 路径每片 1 次 × 16
   *   · TCP 层日志：**每连接 3 条**（新连接 / 已分流 / 连接处理结束），16 片 = 48 条
   * 而 `setLogSink` 里那条回调是**每条日志都 emit** —— 合计 150~200 次全页重建，
   * UI 线程被吃满，表现就是界面卡顿。
   *
   * 这里把同一小段时间内的多次刷新合并成一次，上限约 **10 Hz**（100ms）。
   * 说明：刻意保留「串行 + 兜底定时器」而不是简单丢弃后到的调用 ——
   * 丢调用会让进度条停在某个值不动，比卡顿更难解释。
   */
  private emitThrottled(): void {
    const now: number = Date.now();
    const gap: number = now - this.lastEmitAt;
    if (gap >= 100) {
      this.lastEmitAt = now;
      this.emit();
      return;
    }
    if (this.pendingEmitTimer >= 0) {
      // ★★ 5.1.30：闸门**时间自愈**。
      //   原来这里无条件 `return`，一旦排队定时器因主线程长任务被推迟/丢弃，
      //   `pendingEmitTimer` 就永久 >= 0 ⇒ 后续刷新全被吞掉
      //   （真机：进度条卡 19% 不动，而传输正常）。
      //   现在：超过 EMIT_PENDING_MAX_MS 没真正 emit 过，就无视残留闸门强制放行。
      const sinceLast: number = now - this.lastEmitAt;
      if (sinceLast < LanService.EMIT_PENDING_MAX_MS) {
        return;   // 排队还在有效期内，靠它兜底
      }
      // 残留闸门已失效 —— 清掉旧定时器防双重，然后直接放行
      clearTimeout(this.pendingEmitTimer);
      this.pendingEmitTimer = -1;
      this.lastEmitAt = now;
      this.emit();
      return;
    }
    this.pendingEmitTimer = setTimeout(() => {
      this.pendingEmitTimer = -1;
      this.lastEmitAt = Date.now();
      this.emit();
    }, 100 - gap);
  }

  private pushLog(line: string): void {
    const ts: string = new Date().toTimeString().substring(0, 8);
    const row: string = `[${ts}] ${line}`;
    this.logRing.push(row);
    if (this.logRing.length > 200) {
      this.logRing.shift();
    }
    // 5.0.49：每行**同步落盘**。闪退是进程直接消失，内存里的日志一条都留不下；
    //         只有已经 write 出去的还在 page cache 里，重启后能读回来。
    this.appendLogFile(row);
  }

  /**
   * 5.0.49：把一行日志追加到沙箱内的日志文件。
   *
   * ⚠️ 为什么必须落盘：vivi 真机反馈「接收图片有概率闪退，重新打开后日志就消失了」
   *    —— `logRing` 只在内存里，进程一崩就全没了，等于**没有任何证据**。
   *    现在句柄常开、每行一次 writeSync（纯 syscall，微秒级，不拖慢传输），
   *    崩溃时至少能保住最后一段。
   * ⚠️ 超过 512KB 轮转一次（旧内容挪到 `.1`），避免无限增长。
   */
  private appendLogFile(row: string): void {
    if (this.logFd < 0) {
      return;   // 还没 initLogFile（启动早期）—— 这些行走内存，稍后由 initLogFile 回灌
    }
    try {
      if (this.logBytes > 512 * 1024) {
        this.rotateLogFile();
      }
      fileIo.writeSync(this.logFd, `${row}\n`);
      this.logBytes += row.length + 1;
    } catch (e) {
      // 日志写不进去绝不能影响业务
    }
  }

  /** 日志轮转：当前文件留档成 `.1`，重开一个空的 */
  private rotateLogFile(): void {
    try {
      fileIo.closeSync(this.logFd);
    } catch (e) {
      // 忽略
    }
    this.logFd = -1;
    this.logBytes = 0;
    try {
      fileIo.unlinkSync(`${this.logFile}.1`);
    } catch (e) {
      // 还没有旧的备份
    }
    try {
      fileIo.copyFileSync(this.logFile, `${this.logFile}.1`);
    } catch (e) {
      // 复制失败就算了，下面直接清空重开
    }
    try {
      const f: fileIo.File = fileIo.openSync(this.logFile,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC | fileIo.OpenMode.WRITE_ONLY);
      this.logFd = f.fd;
    } catch (e) {
      this.logFd = -1;
    }
  }

  /**
   * 5.0.49：初始化日志文件，并判断上一次会话是不是**异常退出**（闪退）。
   *
   * 判据是一个 `run.lock`：启动时写、`onDestroy`（正常退出）时删。
   * 下次启动如果它还在，说明上次是被崩掉的 —— 这时把日志文件里最后 150 行
   * 读出来当「崩溃现场」，挂在日志列表最前面，
   * 用户点一次「复制日志」就能把现场完整发出来。
   */
  initLogFile(ctx: common.UIAbilityContext): void {
    if (this.logFd >= 0) {
      return;   // 幂等：重复调用直接返回
    }
    this.logFile = `${ctx.filesDir}/ui_log.txt`;
    this.lockFile = `${ctx.filesDir}/run.lock`;
    this.crashFlag = `${ctx.filesDir}/crash.flag`;
    // ★ 5.1.10：**「上次是否闪退」只看 `crash.flag`**，不再看 `run.lock` 存不存在 ——
    //   `run.lock` 会在本次启动末尾被重写，它的存在**永远**为真
    //   ⇒ 用它当判据 = 每次启动都判成闪退（5.0.49 起的 bug，vivi 21:5x 反馈）。
    //   ★ flag 的完整生命周期（**三步缺一不可**）：
    //     ① 本行读它 —— 存在 = 上次闪退（下面进 if 取现场）
    //     ② 函数末尾写它（见 S4）—— 「本次会话已起来」
    //     ③ markCleanExit 删它 —— 「本次正常退出了」
    //   ⇒ 正常退出 → 被删 → 下次不提示；中途崩 → 留下 → 下次提示一次。
    let flagExists: boolean = false;
    try {
      flagExists = fileIo.accessSync(this.crashFlag);
    } catch (e) {
      flagExists = false;
    }
    if (flagExists) {
      this.prevCrashed = true;
      const tail: string[] = [];
      try {
        const old: string = fileIo.readTextSync(this.logFile);
        const rows: string[] = old.split('\n');
        const from: number = rows.length > 150 ? rows.length - 150 : 0;
        for (let i: number = from; i < rows.length; i++) {
          if (rows[i].length > 0) {
            tail.push(`[上次] ${rows[i]}`);
          }
        }
      } catch (e) {
        // 第一次跑 / 文件被清 —— 没有现场可留
      }
      this.crashTail = tail;
      // 现场也留一份档，避免下次启动把它覆盖掉
      try {
        fileIo.copyFileSync(this.logFile, `${this.logFile}.1`);
      } catch (e) {
        // 忽略
      }
    }
    // 新会话从空文件开始
    try {
      const f: fileIo.File = fileIo.openSync(this.logFile,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC | fileIo.OpenMode.WRITE_ONLY);
      this.logFd = f.fd;
      this.logBytes = 0;
    } catch (e) {
      this.logFd = -1;
    }
    // 把启动早期（句柄还没就绪时）攒下的日志回灌进去，别丢
    for (let i: number = 0; i < this.logRing.length; i++) {
      this.appendLogFile(this.logRing[i]);
    }
    // 打上「本次会话开始」标记 + 上次是否异常退出
    this.pushLog(this.prevCrashed
      ? '⚠️ 检测到上次异常退出（闪退），崩溃前日志已挂在列表最前面，请点「复制日志」'
      : '会话开始（上次为正常退出）');
    // 最后才写 run.lock —— 上面任何一步崩掉都不该被误判成「本次正常」
    try {
      const lf: fileIo.File = fileIo.openSync(this.lockFile,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);
      fileIo.writeSync(lf.fd, `${new Date().toString()}\n`);
      fileIo.closeSync(lf);
    } catch (e) {
      // 忽略
    }
    // ★ 5.1.10：把「本次启动已完成初始化」记到 `crash.flag` —— 它**存在即表示
    //   「上一次会话没有走到 markCleanExit」**（也就是闪退）。
    //   `markCleanExit` 正常退出时会把它删掉 ⇒ 语义闭合。
    try {
      const cf: fileIo.File = fileIo.openSync(this.crashFlag,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);
      fileIo.writeSync(cf.fd, `${new Date().toString()}\n`);
      fileIo.closeSync(cf);
    } catch (e) {
      // 忽略
    }
  }

  /**
   * 5.0.49：正常退出 —— 删掉 `run.lock`，下次启动就不会误报「异常退出」。
   * 由 EntryAbility.onDestroy 调用。
   */
  markCleanExit(): void {
    // ★ 5.1.10：**必须同时删 `crash.flag`** —— 只删 `run.lock` 的话，
    //   flag 会留下 ⇒ 下次启动仍然判成「上次闪退」⇒ 提示反复弹（vivi 21:5x）。
    if (this.crashFlag.length > 0) {
      try {
        fileIo.unlinkSync(this.crashFlag);
      } catch (e) {
        // 已经不在了
      }
    }
    if (this.lockFile.length > 0) {
      try {
        fileIo.unlinkSync(this.lockFile);
      } catch (e) {
        // 已经不在了
      }
    }
    if (this.logFd >= 0) {
      try {
        fileIo.closeSync(this.logFd);
      } catch (e) {
        // 忽略
      }
      this.logFd = -1;
    }
  }

  /**
   * 5.0.48：「收到图片/视频自动存相册」链路的诊断入口（由 Index 页面层调用）。
   * 这条路之前失败时只写 hilog，真机（无线调试不可用）抓不到，只能靠猜。
   * 现在每步都进 UI 日志。
   */
  logAuto(msg: string): void {
    this.pushLog(`[相册] ${msg}`);
    this.emit();
  }

  /**
   * 5.0.49：**未捕获异常**落盘入口 —— EntryAbility 的 errorManager 回调调它。
   * 这是「闪退」最直接的一份证据：栈顶通常就写明了崩在哪一行。
   * ⚠️ 全程 try 包裹：出错回调里再抛异常会把证据一起弄丢。
   */
  crashLog(msg: string): void {
    try {
      this.pushLog(`💥 ${msg}`);
      this.emit();
    } catch (e) {
      try {
        this.appendLogFile(`💥 ${msg}`);
      } catch (x) {
        // 实在写不进去就放弃
      }
    }
  }

  private setMessage(msg: string): void {
    this.snapshot.message = msg;
    this.pushLog(msg);
  }

  // ------------------------------------------------------------------
  // 网页访问授权（对应原 SERVICE_HTTP_NEW_CLIENT 弹框 + Config.WEB_OPEN）
  // ------------------------------------------------------------------

  /**
   * 有新的网页客户端在等确认。
   * 网页那边会一直显示「没有访问权限，请在手机上同意之后刷新页面」，
   * 所以这条日志必须写进 UI —— 否则用户根本不知道该去哪里点同意。
   */
  private onNewWebClient(c: WebClient): void {
    this.pushLog(`有新设备请求访问网页：${c.ip.length > 0 ? c.ip : '未知 IP'}（${c.name}）— 请点「允许」`);
    this.emit();
  }

  /** 等待确认的客户端列表（UI 渲染授权卡片） */
  get pendingWebClients(): WebClient[] {
    return this.webClients.pending();
  }

  /** 网页访问是否免确认 */
  get webOpen(): boolean {
    return this.router.isWebOpen;
  }

  /** 放行一个网页客户端。网页端会在 2 秒内轮询到 pass=true 并自动刷新 */
  async approveWebClient(token: string): Promise<void> {
    const c: WebClient | null = this.webClients.byToken(token);
    if (c === null) {
      this.pushLog('该客户端记录已失效，请让对方刷新页面重新申请');
      this.emit();
      return;
    }
    this.webClients.setPass(token, true);
    await this.webClients.flush();
    this.pushLog(`已允许 ${c.ip.length > 0 ? c.ip : c.name} 访问网页，对方页面会自动刷新`);
    this.emit();
  }

  /** 拒绝一个网页客户端（移除记录，对方下次访问会重新申请） */
  async denyWebClient(token: string): Promise<void> {
    const c: WebClient | null = this.webClients.byToken(token);
    if (c === null) {
      return;
    }
    this.webClients.remove(token);
    await this.webClients.flush();
    this.pushLog(`已拒绝 ${c.ip.length > 0 ? c.ip : c.name} 访问网页`);
    this.emit();
  }

  /**
   * 切换「网页访问免确认」开关（对应原 Config.WEB_OPEN）。
   * 打开时会把当前所有待确认的客户端一并放行 —— 否则用户会以为开关没生效。
   */
  async setWebOpen(open: boolean): Promise<void> {
    this.router.setWebOpen(open);
    let released: number = 0;
    if (open) {
      const pend: WebClient[] = this.webClients.pending();
      for (let i = 0; i < pend.length; i++) {
        if (this.webClients.setPass(pend[i].token, true)) {
          released += 1;
        }
      }
      if (released > 0) {
        await this.webClients.flush();
      }
    }
    if (this.ctx !== null) {
      try {
        const store: preferences.Preferences = await preferences.getPreferences(this.ctx, PREF_WEB);
        await store.put(PREF_WEB_OPEN, open);
        await store.flush();
      } catch (e) {
        Log.w(TAG, '保存「网页免确认」开关失败');
      }
    }
    if (open) {
      this.pushLog(`已开启「网页免确认」${released > 0 ? `，同时放行了 ${released} 个待确认设备` : ''}`);
    } else {
      this.pushLog('已关闭「网页免确认」，之后新设备需要手动点「允许」');
    }
    this.emit();
  }

  // ------------------------------------------------------------------
  // 设备名（用户可手动修改，持久化到 preferences）
  // ------------------------------------------------------------------

  /** 启动时把持久化的设备名读进 LanConfig.userName（startSharing 组装 self 时取用它） */
  private async loadDeviceNamePref(ctx: common.UIAbilityContext): Promise<void> {
    try {
      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_CFG);
      const saved: Object = await store.get('userName', '');
      if (typeof saved === 'string' && saved.length > 0) {
        LanConfig.userName = saved;
      }
    } catch (e) {
      Log.w(TAG, '读取设备名偏好失败');
    }
  }

  /**
   * 用户手动改设备名。立即生效：更新内存态（self.devName 会被写进下一轮 UDP 广播与
   * TCP 握手 JSON，对端下次看到的就是新名），并持久化，下次启动沿用。无需重启服务。
   */
  async setDeviceName(name: string): Promise<void> {
    const clean: string = name.trim();
    if (clean.length === 0) {
      return;
    }
    LanConfig.userName = clean;
    if (this.self !== undefined && this.self !== null) {
      this.self.devName = clean;
    }
    if (this.ctx !== null) {
      try {
        const store: preferences.Preferences = await preferences.getPreferences(this.ctx, PREF_CFG);
        await store.put('userName', clean);
        await store.flush();
      } catch (e) {
        Log.w(TAG, '保存设备名偏好失败');
      }
    }
    this.pushLog(`本机设备名已更新为：${clean}`);
    this.emit();
  }

  /**
   * 收到图片/视频后自动存相册。**默认开** —— 用户要的正是「像捷传那样」的体验。
   * 走的 `showAssetsCreationDialog` 不需要任何权限声明，弹一次确认框即可。
   */
  private autoAlbumPref: boolean = true;

  get autoAlbumOn(): boolean {
    return this.autoAlbumPref;
  }

  private async loadAutoAlbumPref(ctx: common.UIAbilityContext): Promise<void> {
    try {
      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_CFG);
      const saved: Object = await store.get('autoAlbum', true);
      if (typeof saved === 'boolean') {
        this.autoAlbumPref = saved;
      }
    } catch (e) {
      Log.w(TAG, '读取「自动存相册」偏好失败');
    }
  }

  async setAutoAlbum(on: boolean): Promise<void> {
    this.autoAlbumPref = on;
    if (this.ctx !== null) {
      try {
        const store: preferences.Preferences = await preferences.getPreferences(this.ctx, PREF_CFG);
        await store.put('autoAlbum', on);
        await store.flush();
      } catch (e) {
        Log.w(TAG, '保存「自动存相册」开关失败');
      }
    }
    this.pushLog(on ? '已开启「收到图片/视频自动存相册」' : '已关闭「自动存相册」');
    this.emit();
  }

  /** 5.0.39：已存进相册的媒体 —— 消息 id -> `相册URI|缩略图缓存路径` */
  private albumMap: Map<string, string> = new Map<string, string>();
  private albumLoaded: boolean = false;

  /**
   * ★★ 5.1.66 C2：相册索引落盘的**防抖定时器**（-1 = 无）。
   * ⚠️ 语义是「防抖」不是「节流」：**已有定时器在等就搭车，不重置**。
   * 这样连续 400 次 `setThumbOnlyBatch` 只落盘 1~2 次。
   * （参照同文件里既有的 `chatSaveTimer` 写法。）
   */
  private albumPersistTimer: number = -1;

  /**
   * ★ 5.1.2：**非媒体文件**（zip / pdf / apk）的落地状态 —— 消息 id -> 状态串。
   *
   * ⚠️ **为什么不能复用 `albumMap`**：它的 key 是「消息 id + 媒体序号」
   *   （`albumKeyOf(id,k)`）、value 是 `相册URI|缩略图路径`，语义是「媒体进了系统相册」。
   *   非媒体文件既没有相册 URI 也没有缩略图，两边都对不上。
   *
   * 值域（**中文可读串**，preferences 本来就存字符串，将来加第三种不用改判据）：
   *   `已存本地` —— 另存为成功（沙箱副本已按 5.0.53 口径删掉）
   *   `已删除`   —— 用户在文件页点了删除
   * 空串 / 查不到 = 没动过（此时显示「点击查看」）
   */
  private localMap: Map<string, string> = new Map<string, string>();

  /** ★ 5.1.2：读本地文件落地状态（空串 = 没动过）。Index 的气泡判据用它。 */
  localStateOf(id: string): string {
    if (id.length === 0) {
      return '';
    }
    return this.localMap.get(id) ?? '';
  }

  /** ★ 5.1.2：写本地文件落地状态并落盘。`state` 传空串等于取消记账。 */
  markLocalState(id: string, state: string): void {
    if (id.length === 0 || state.length === 0) {
      return;
    }
    this.localMap.set(id, state);
    this.persistLocalIndex().catch((e: Error) => {
      Log.w(TAG, `保存本地文件状态失败: ${e.message}`);
    });
  }

  /** ★ 5.1.2：落盘。格式 `id|状态`（⚠️ key 必须一起写 —— 5.0.43 踩过这个坑）。 */
  private async persistLocalIndex(): Promise<void> {
    if (this.ctx === null) {
      return;
    }
    try {
      const store: preferences.Preferences =
        await preferences.getPreferences(this.ctx, PREF_CFG);
      const rows: string[] = [];
      for (const k of this.localMap.keys()) {
        const v: string = this.localMap.get(k) ?? '';
        if (k.length > 0 && v.length > 0) {
          rows.push(`${k}|${v}`);
        }
      }
      await store.put('localFileIndex', rows.join('\n'));
      await store.flush();
    } catch (e) {
      Log.w(TAG, '保存本地文件状态索引失败');
    }
  }

  /**
   * 5.0.44：每张缓存缩略图需要显示层补转的角度。
   * key = 缩略图绝对路径，value = 0/90/180/270/-1。
   * 必须持久化：重启后页面内存清空，否则「靠 Image.orientation() 补转」的图会躺回去。
   */
  /** 5.0.44：public —— Index 页面在 cacheThumb() 里需要直接写入 */
  albumRotMap: Map<string, number> = new Map<string, number>();

  /** UI 查询某张缓存缩略图该用哪个方向 */
  rotOf(thumb: string): number | undefined {
    return this.albumRotMap.get(thumb);
  }

  /**
   * ★ 5.0.52：「相册里那份已不存在」这条判定**可不可信**。
   *
   * 媒体 URI 是 `showAssetsCreationDialog` 给的**写授权**，回头去读它（stat / 读打开）
   * 在本平台可能一律失败（≠ 文件不存在）⇒ 「两个信号都失败就判已删除」会把
   * **每一张图**都谎报成「已从相册删除」；也可能一律成功 ⇒ 删了还照常跳空白页。
   * 判定方法见 `Index.albumProbeCalibrate()`：拿**刚写进去**的资产当场试一次。
   * 一次不可信以后就不再谎报；持久化，重启也不用重试。
   */
  private albumProbeOk: boolean = true;

  probeTrusted(): boolean {
    return this.albumProbeOk;
  }

  setProbeTrusted(v: boolean): void {
    if (this.albumProbeOk === v) {
      return;
    }
    this.albumProbeOk = v;
    this.persistAlbumProbe().catch((e: Error) => {
      Log.w(TAG, `保存探针可信度失败: ${e.message}`);
    });
  }

  private async persistAlbumProbe(): Promise<void> {
    if (this.ctx === null) {
      return;
    }
    try {
      const store: preferences.Preferences = await preferences.getPreferences(this.ctx, PREF_CFG);
      await store.put('albumProbe', this.albumProbeOk ? 1 : 0);
      await store.flush();
    } catch (e) {
      Log.w(TAG, '保存探针可信度失败');
    }
  }

  private async loadAlbumProbe(ctx: common.UIAbilityContext): Promise<void> {
    try {
      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_CFG);
      const raw: Object = await store.get('albumProbe', 1);
      if (typeof raw === 'number') {
        this.albumProbeOk = (raw as number) !== 0;
      }
    } catch (e) {
      Log.w(TAG, '读取探针可信度失败');
    }
  }

  /** 载入相册索引（幂等，只会真正读一次） */
  async loadAlbumIndex(ctx: common.UIAbilityContext): Promise<void> {
    if (this.albumLoaded) {
      return;
    }
    this.albumLoaded = true;
    try {
      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_CFG);
      const raw: Object = await store.get('albumIndex', '');
      if (typeof raw === 'string') {
        const rows: string[] = (raw as string).split('\n');
        let dropped: number = 0;
        for (let i: number = 0; i < rows.length; i++) {
          const row: string = rows[i];
          if (row.length === 0) {
            continue;
          }
          const segs: string[] = row.split('|');
          if (segs.length >= 3 && segs[0].length > 0) {
            // 5.0.43：行格式 `id|uri|thumb`。存回 map 的 value 仍是 `uri|thumb`
            //         —— UI 的 `albumPart(id, 0/1)` 就是按这两段取的，不用跟着改。
            this.albumMap.set(segs[0], row.substring(segs[0].length + 1));
          } else {
            // 老版本写进去的行只有 `uri|thumb`，**没有 id**，还原不出 key ——
            // 那种行本来也查不到，留着只会让索引越来越脏，直接丢掉。
            dropped = dropped + 1;
          }
        }
        if (dropped > 0) {
          Log.i(TAG, `丢弃 ${dropped} 条缺 id 的旧相册索引（5.0.42 及更早写的）`);
        }
      }
      // ★ 5.1.2：同一次 preferences 会话里把「非媒体文件落地状态」一起读回来
      //   （不另开一次 getPreferences —— 少一次 IO，也不必再拿一次 ctx）。
      const rawLocal: Object = await store.get('localFileIndex', '');
      if (typeof rawLocal === 'string') {
        const lrows: string[] = (rawLocal as string).split('\n');
        for (let i: number = 0; i < lrows.length; i++) {
          const row: string = lrows[i];
          if (row.length === 0) {
            continue;
          }
          // 行格式 `id|状态`。老版本没有这个 key ⇒ 这里读到的是空串 ⇒ 直接跳过。
          const pos: number = row.indexOf('|');
          if (pos > 0) {
            this.localMap.set(row.substring(0, pos), row.substring(pos + 1));
          }
        }
      }
      // 5.0.43：把老版本留在 cacheDir 里的缩略图搬到 filesDir 并补回索引
      await this.migrateThumbCache(ctx);
      // 5.0.44：缩略图旋转角度也要恢复
      await this.loadAlbumRot(ctx);
      // 5.0.52：探针可信度也要恢复（不可信就别再谎报「已删除」）
      await this.loadAlbumProbe(ctx);
    } catch (e) {
      Log.w(TAG, '读取相册索引失败');
    }
  }

  /** 5.0.44：从 preferences 恢复缩略图旋转角度 */
  private async loadAlbumRot(ctx: common.UIAbilityContext): Promise<void> {
    try {
      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_CFG);
      const raw: Object = await store.get('albumRot', '');
      if (typeof raw === 'string') {
        const rows: string[] = (raw as string).split('\n');
        for (let i: number = 0; i < rows.length; i++) {
          const row: string = rows[i];
          if (row.length === 0) {
            continue;
          }
          const segs: string[] = row.split('|');
          if (segs.length >= 2 && segs[0].length > 0) {
            const rot: number = Number.parseInt(segs[1], 10);
            if (!Number.isNaN(rot)) {
              this.albumRotMap.set(segs[0], rot);
            }
          }
        }
      }
    } catch (e) {
      Log.w(TAG, '读取缩略图旋转索引失败');
    }
  }

  /**
   * 5.0.43：把 5.0.42 及更早留在 `cacheDir/album_thumbs` 里的缩略图搬到 `filesDir/album_thumbs`，
   * 并**按文件名重建索引条目**。
   *
   * 为什么要搬：那几个版本的索引行只有 `uri|thumb`、**没写消息 id**，升级后按新格式
   * （`id|uri|thumb`）读会被当脏数据丢掉 —— 那些消息就再也找不到缩略图了。
   * 好在 `cacheThumb()` 用的文件名就是消息 id（`${id}.jpg`），文件名能反推出 key。
   *
   * ⚠️ 补出来的条目**只有缩略图、没有相册 URI**（旧行的 uri 已经找不到主人），
   *    所以点击不会跳相册 —— 但至少缩略图回来了，不会再退化成「点气泡跳文件 tab」。
   */
  private async migrateThumbCache(ctx: common.UIAbilityContext): Promise<void> {
    const oldDir: string = `${ctx.cacheDir}/album_thumbs`;
    const newDir: string = `${ctx.filesDir}/album_thumbs`;
    let names: string[] = [];
    try {
      names = fileIo.listFileSync(oldDir);
    } catch (x) {
      return; // 没有旧目录 —— 全新安装，正常情况
    }
    if (names.length === 0) {
      return;
    }
    let moved: number = 0;
    try {
      fileIo.mkdirSync(newDir);
    } catch (x) {
      // 目录已存在 —— 正常情况
    }
    for (let i: number = 0; i < names.length; i++) {
      const nm: string = names[i];
      const dot: number = nm.lastIndexOf('.');
      if (dot <= 0) {
        continue;
      }
      let id: string = nm.substring(0, dot);
      // 5.0.42 的方向兜底路径用的是 `${id}_full${ext}`，去尾巴才是消息 id
      if (id.endsWith('_full')) {
        id = id.substring(0, id.length - 5);
      }
      if (id.length === 0 || this.albumMap.has(id)) {
        continue; // 新格式里已经有了就别覆盖
      }
      try {
        fileIo.copyFileSync(`${oldDir}/${nm}`, `${newDir}/${nm}`);
        // uri 段留空：只补缩略图（旧索引里那个 uri 已经对不上这条消息了）
        this.albumMap.set(id, `|${newDir}/${nm}`);
        // 5.0.42 的 _full 兜底是原图复制，带 EXIF -> 显示层用 AUTO(-1)
        if (nm.endsWith('_full')) {
          this.albumRotMap.set(`${newDir}/${nm}`, -1);
        }
        moved = moved + 1;
      } catch (x) {
        // 单个搬失败不影响其它
      }
    }
    // 搬完了就把旧目录清掉，别继续占着 cacheDir（那里本来就会被系统清）
    for (let i: number = 0; i < names.length; i++) {
      try {
        fileIo.unlinkSync(`${oldDir}/${names[i]}`);
      } catch (x) {
        // 忽略
      }
    }
    try {
      fileIo.rmdirSync(oldDir);
    } catch (x) {
      // 忽略
    }
    if (moved > 0) {
      Log.i(TAG, `迁移旧缩略图 ${moved} 个：cacheDir -> filesDir`);
      await this.persistAlbumIndex();
    }
  }

  /** 给 UI 的快照 —— **整体换引用**才能触发重绘（Map 本身不可观察） */
  albumSnapshot(): Map<string, string> {
    const m: Map<string, string> = new Map<string, string>();
    for (const k of this.albumMap.keys()) {
      m.set(k, this.albumMap.get(k) ?? '');
    }
    return m;
  }

  /**
   * 记一条「已存进相册」：相册 URI + 缓存出来的缩略图路径 + 显示层补转角度。
   * @param rot 缓存缩略图需要 Image.orientation() 补转的角度：0=已物理转正，
   *            90/180/270=显示层补转，-1=原图复制兜底（带 EXIF，用 AUTO）。
   */
  /**
   * ★★ 5.1.65：批量写相册索引 —— 存相册时**一次落盘**，不是每张一次。
   *
   * ## 为什么（vivi 2026-10-05 真机实测：426 张批量，每批点确认后卡 2~4 秒）
   *   原来每存一张图都调 `setAlbumIndex` → `persistAlbumIndex` + `persistAlbumRot`
   *   各**全量遍历** `albumMap` / `albumRotMap` 再 `flush()`。
   *   ⇒ 一批 40 张 = **160 次全量写**（表里还有 400+ 条历史），
   *     而 albumMap 只多了 40 条 ⇒ **99% 的写入是白做的**。
   *
   * ## 改法
   *   整批先写进 Map（纯内存，微秒级），**循环结束后只落盘一次**。
   *   语义等价性：调用处已改成「落盘成功后才删沙箱副本」，
   *   ⇒ 中途崩溃最坏是丢这一批索引，但沙箱副本还在 ⇒ 下次刷新能重建。
   *
   * @param items 每项格式 `${id}|${uri}|${thumb}|${rot}`
   */
  async setAlbumIndexBatch(items: string[]): Promise<void> {
    if (items.length === 0) {
      return;
    }
    this.albumLoaded = true;
    for (let i: number = 0; i < items.length; i++) {
      const parts: string[] = items[i].split('|');
      if (parts.length >= 4) {
        this.albumMap.set(parts[0], `${parts[1]}|${parts[2]}`);
        this.albumRotMap.set(parts[2], Number(parts[3]));
      }
    }
    await this.persistAlbumIndex();
    await this.persistAlbumRot();
  }

  async setAlbumIndex(id: string, uri: string, thumb: string, rot: number = 0): Promise<void> {
    this.albumLoaded = true;
    this.albumMap.set(id, `${uri}|${thumb}`);
    this.albumRotMap.set(thumb, rot);
    await this.persistAlbumIndex();
    await this.persistAlbumRot();
  }

  /**
   * ★★ 5.1.66 C2：批量补缩略图索引 —— **只进内存，落盘交给防抖**。
   *
   * ## 为什么（vivi 2026-10-05 真机：400+ 张缩略图生成时卡顿）
   *   原来每预生成一张缩略图就 `await setThumbOnly(...)`
   *   ⇒ 内部 `persistAlbumIndex` + `persistAlbumRot` 各**全量遍历** + flush
   *   ⇒ **400 张 = 800 次全量写**，而表只多了 400 条。
   *   （与 5.1.65 修掉的 `setAlbumIndex` 是同一个病，那次只修了存相册那条路径。）
   *
   * ## 改法
   *   **只写 Map，不落盘**。落盘由 `scheduleAlbumPersist()` **防抖合并**
   *   （1.5s 静默期，且**不重置**定时器）⇒ 连续 400 张最多落盘 1~2 次。
   *   ⚠️ 崩溃风险：防抖窗口内挂掉 ⇒ 丢这一批缩略图索引。可接受 ——
   *   `prefetchThumbInner` 失败会 `thumbPrepare.delete(key)`，
   *   下次渲染还会再试（见 maybePrefetchThumb 的注释）。
   *
   * @param items 每项格式 `${key}|${thumb}|${rot}`
   */
  setThumbOnlyBatch(items: string[]): void {
    if (items.length === 0) {
      return;
    }
    this.albumLoaded = true;
    for (let i: number = 0; i < items.length; i++) {
      const parts: string[] = items[i].split('|');
      if (parts.length >= 3) {
        const cur: string | undefined = this.albumMap.get(parts[0]);
        const segs: string[] = cur === undefined ? [] : cur.split('|');
        const curUri: string = segs.length > 0 ? segs[0] : '';
        // ⚠️ 绝不碰已有相册 URI（这是 setThumbOnly 的核心不变量）
        this.albumMap.set(parts[0], `${curUri}|${parts[1]}`);
        this.albumRotMap.set(parts[1], Number(parts[2]));
      }
    }
    this.scheduleAlbumPersist();
  }

  /**
   * 5.1.66 C2：相册索引落盘的**防抖合并**。
   * 已有定时器在等就直接搭车（**不重置**）⇒ 连续 N 次调用只落盘 1 次。
   * ⚠️ 与 `scheduleChatSave`（5.x）同款写法，参照它。
   */
  private scheduleAlbumPersist(): void {
    if (this.albumPersistTimer !== -1) {
      return;
    }
    this.albumPersistTimer = setTimeout(() => {
      this.albumPersistTimer = -1;
      this.persistAlbumIndex();
      this.persistAlbumRot();
    }, 1500);
  }

  /**
   * ★ 5.0.61：**只**补一条「缩略图缓存路径」，**绝不碰已有的相册 URI**。
   *
   * 用途：接收 / 渲染缩略图时**预生成**缓存小图，好让气泡的显示源从一开始就恒定
   * 指向 `album_thumbs/<key>.jpg` —— 之后存相册、删沙箱副本时源不变、ForEach key
   * 不变，缩略图**不会再整屏重刷一遍**。
   *
   * ⚠️ 与 `setAlbumIndex` 的区别只有一条，但极其关键：这条路径上**用户还没点
   *    相册确认框**，uri 必须是空的。如果直接把已有行覆盖成 `|thumb`，就把
   *    「点图跳相册」的能力冲掉了（`clearAlbumUri` 那种失效场景重演）。
   *
   * ⚠️ 5.1.66 C2：**单条**版保留「立即落盘」原语义；
   *   大批量场景（预生成缩略图）请用 `setThumbOnlyBatch`。
   */
  async setThumbOnly(id: string, thumb: string, rot: number = 0): Promise<void> {
    if (thumb.length === 0) {
      return;
    }
    this.albumLoaded = true;
    const cur: string | undefined = this.albumMap.get(id);
    const segs: string[] = cur === undefined ? [] : cur.split('|');
    const curUri: string = segs.length > 0 ? segs[0] : '';
    this.albumMap.set(id, `${curUri}|${thumb}`);
    this.albumRotMap.set(thumb, rot);
    await this.persistAlbumIndex();
    await this.persistAlbumRot();
  }

  /**
   * 5.0.49：把**已经失效**的相册 URI 从索引里摘掉，但**保留缩略图**。
   *
   * 场景（vivi 2026-10-02）：在系统相册里把那张图删了，我们记的 uri 就成了死链接 ——
   * 再点气泡会跳进一个空白相册页、还没有任何提示。
   * 只清 uri 不清缩略图：气泡还能显示小图（用缓存那份做应用内预览）。
   * ⚠️ 5.0.50 起**不会**再自动补存相册（historyToAlbum 已删）—— 用户删掉的就别再偷存回去。
   * ⚠️ 5.0.52 起 key 是 `消息id#媒体序号`（每一张图一条），调用方传的也是这个 key。
   */
  clearAlbumUri(id: string): void {
    const row: string | undefined = this.albumMap.get(id);
    if (row === undefined) {
      return;
    }
    const segs: string[] = row.split('|');
    const thumb: string = segs.length >= 2 ? segs[1] : '';
    if (thumb.length === 0) {
      this.albumMap.delete(id);
    } else {
      this.albumMap.set(id, `|${thumb}`);
    }
    this.persistAlbumIndex().catch((e: Error) => {
      Log.w(TAG, `清理失效相册 URI 落盘异常: ${e.message}`);
    });
  }

  /** 删聊天记录时顺带清索引。⚠️ 相册里那一份**不动**，只清这条映射 */
  private dropAlbumIndex(ids: string[]): void {
    let hit: boolean = false;
    for (let i: number = 0; i < ids.length; i++) {
      const id: string = ids[i];
      // ★ 5.0.52：key 现在是 `消息id#媒体序号`，**一条消息可能有多条** —— 前缀匹配全清。
      //   裸 id 也一起带上（兼容 5.0.39~5.0.51 写下的旧行）。
      const keys: string[] = [id];
      for (const k of this.albumMap.keys()) {
        if (k.startsWith(id + '#')) {
          keys.push(k);
        }
      }
      for (let j: number = 0; j < keys.length; j++) {
        const row: string | undefined = this.albumMap.get(keys[j]);
        if (row === undefined) {
          continue;
        }
        this.albumMap.delete(keys[j]);
        hit = true;
        // 5.0.43：缩略图缓存已挪到 filesDir（不会再被系统自动清），
        //         删记录时必须自己删掉，否则会一直堆着。⚠️ 相册里那一份**不动**。
        const segs: string[] = row.split('|');
        const thumb: string = segs.length >= 2 ? segs[1] : '';
        if (thumb.length > 0) {
          try {
            fileIo.unlinkSync(thumb);
          } catch (x) {
            // 已经不在了就算了
          }
        }
      }
    }
    if (hit) {
      this.persistAlbumIndex().catch((e: Error) => {
        Log.w(TAG, `清理相册索引落盘异常: ${e.message}`);
      });
    }
  }

  /**
   * ★ 5.1.69 B：这条 v5 日志是不是「逐项」日志（带进度下标，可按进度节流）。
   * 判据：含 `清单[i/`、`开始收第 i/`、`收尾已回` 三种形态之一。
   */
  private static isPerItemV5Log(s: string): boolean {
    return s.indexOf('清单[') >= 0
      || s.indexOf('开始收第') >= 0
      || s.indexOf('收尾已回') >= 0;
  }

  /**
   * ★ 5.1.69 B：从逐项日志文本里取进度下标 i。
   * 形态：`v5 清单[37/426] ...` / `v5 开始收第 37/426 项 ...`
   * ⚠️ **不通用正则**（ArkTS 与性能）—— 逐段扫数字，遇 `/` 停。
   *   找不到返回 -1（调用方按「不过滤」处理）。
   */
  private static progressIndexOf(s: string): number {
    const open: number = s.indexOf('第');
    let from: number = -1;
    if (open >= 0) {
      from = open + 1;
    } else {
      const lb: number = s.indexOf('[');
      if (lb < 0) {
        return -1;
      }
      from = lb + 1;
    }
    let n: number = 0;
    let digits: number = 0;
    for (let i: number = from; i < s.length; i++) {
      const c: number = s.charCodeAt(i);
      if (c >= 0x30 && c <= 0x39) {
        n = n * 10 + (c - 0x30);
        digits += 1;
        if (digits > 6) {
          return -1;
        }
      } else {
        break;
      }
    }
    return digits > 0 ? n : -1;
  }

  private async persistAlbumIndex(): Promise<void> {
    if (this.ctx === null) {
      return;
    }
    try {
      const store: preferences.Preferences =
        await preferences.getPreferences(this.ctx, PREF_CFG);
      const rows: string[] = [];
      for (const k of this.albumMap.keys()) {
        const v: string = this.albumMap.get(k) ?? '';
        if (k.length > 0 && v.length > 0) {
          // ⚠️ 5.0.43：行格式必须是 `id|uri|thumb` —— **key（消息 id）必须一起写进去**。
          //    5.0.39~5.0.42 只写了 `uri|thumb`，读回来时拿 uri 当 key，
          //    于是重启后 `albumPart(m.id, n)` 永远查不到 —— 缩略图丢、点击又跳回文件 tab。
          rows.push(`${k}|${v}`);
        }
      }
      await store.put('albumIndex', rows.join('\n'));
      await store.flush();
    } catch (e) {
      Log.w(TAG, '保存相册索引失败');
    }
  }


  /** 5.0.44：持久化缩略图旋转角度 */
  private async persistAlbumRot(): Promise<void> {
    if (this.ctx === null) {
      return;
    }
    try {
      const store: preferences.Preferences = await preferences.getPreferences(this.ctx, PREF_CFG);
      const rows: string[] = [];
      for (const k of this.albumRotMap.keys()) {
        const v: number | undefined = this.albumRotMap.get(k);
        if (k.length > 0 && v !== undefined) {
          rows.push(`${k}|${v}`);
        }
      }
      await store.put('albumRot', rows.join('\n'));
      await store.flush();
    } catch (e) {
      Log.w(TAG, '保存缩略图旋转索引失败');
    }
  }

  /**
   * 恢复默认设备名（设备市场名）。
   * 清除持久化的自定义名：LanConfig.userName 置空后，下一次 `localDeviceName()`
   * 会回退到 deviceInfo.marketName，对端下一轮广播即见市场名。
   * 用于"之前手动改过、现在想回到默认"的场景（vivi 2026-09-30 要求）。
   */
  async resetDeviceName(): Promise<void> {
    LanConfig.userName = '';
    const def: string = LanService.localDeviceName();
    if (this.self !== undefined && this.self !== null) {
      this.self.devName = def;
    }
    if (this.ctx !== null) {
      try {
        const store: preferences.Preferences = await preferences.getPreferences(this.ctx, PREF_CFG);
        await store.delete('userName');
        await store.flush();
      } catch (e) {
        Log.w(TAG, '清除设备名偏好失败');
      }
    }
    this.pushLog(`本机设备名已恢复为默认：${def}`);
    this.emit();
  }

  // ------------------------------------------------------------------
  // 生命周期
  // ------------------------------------------------------------------

  get isRunning(): boolean {
    return this.state === ServiceState.RUNNING;
  }

  /**
   * 启动共享。由 UI 的「开始共享」按钮触发。
   *
   * 对应 Android 的 LANService.onStartCommand() + init() 那一整套。
   * 与 Android 版的区别：**不申请任何后台权限**，退到后台即停（见 stopSharing）。
   */
  async startSharing(ctx: common.UIAbilityContext): Promise<boolean> {
    if (this.state === ServiceState.RUNNING) {
      return true;
    }
    this.ctx = ctx;
    // 5.0.49：日志立刻开始落盘 —— 崩溃取证越早开始越好
    this.initLogFile(ctx);
    this.router.setContext(ctx);
    this.state = ServiceState.STARTING;
    // 聊天用的 AES 密钥必须先就绪：TextMessenger 与 onMessageV4 都依赖它。
    // 放在这里而不是构造函数里，是因为它要用 cryptoFramework（启动早期调用有风险）。
    this.ensureMessageKey();
    this.emit();

    // ---- 1. 数据库 + 网页端配置 ----
    await this.store.init(ctx);
    await this.router.initPrefs(ctx);
    // 设备名偏好必须在组装 self.devName 之前就绪（见 startSharing 第 3 步的取用逻辑）
    await this.loadDeviceNamePref(ctx);
    await this.loadAutoAlbumPref(ctx);
    await this.loadAlbumIndex(ctx);
    // 网页客户端白名单（授权状态）。必须在 TCP 起来之前就绪，
    // 否则第一个 /initConfig 请求会落在空表上，白名单形同不存在。
    await this.webClients.init(ctx);
    this.router.setClientStore(this.webClients);
    this.pushLog(`网页访问：${this.router.isWebOpen ? '免确认（新设备直接放行）' : '新设备需在本机点「允许」'}`);

    // ---- 1.5 落盘位置：优先「下载」目录，未授权则降级到沙箱 ----
    // 这里是唯一适合申请「写下载目录」的时机：
    // 用户刚点了「开始共享」，意图明确；而真正接收文件是自动发生的，
    // 那时候再弹窗会打断正在进行中的传输。
    // 注意：局域网收发本身**不需要任何用户授权**（INTERNET 是 system_grant），
    // 这个权限只为让收到的文件出现在「下载」里而不是应用私有目录。
    const grant: GrantOutcome = await PermissionGate.ensureDownloadDirDetailed(ctx);
    this.storage.init(`${ctx.filesDir}/LANShare`);
    if (grant.granted) {
      this.storage.refreshDownloadDir();
    }
    // 网页上传的文件也要落在这个根目录下，必须和「接收文件」共用同一个
    // FileStorage 实例 —— 否则用户从网页传上来的东西不会出现在
    // 「已接收文件」卡片里，等于传了个寂寞。
    this.router.setStorage(this.storage);
    // 网页 → 手机的上传进度接到应用内浮层上。
    // 不接的话：网页传大文件时手机上完全没反馈、期间按钮还点不动，
    // 用户只能干等，不知道是卡了还是在传（vivi 2026-09-30 反馈）。
    this.router.setOnUploadProgress(
      (received: number, total: number, name: string) => {
        this.onWebUploadProgress(received, total, name);
      });
    this.router.setOnUploadEnd(
      (ok: boolean, names: string[], totalBytes: number, error: string) => {
        this.onWebUploadEnd(ok, names, totalBytes, error);
      });
    // 反方向：本机 -> 浏览器（网页端下载文件 / 手机「发到网页端」）的进度。
    // 字节是从本机发出去的，但发起方是浏览器，手机端以前完全没有反馈 ——
    // 推文件给网页时浮层一片空白，用户只能看浏览器的下载条（vivi 2026-10-01 反馈）。
    this.router.setOnDownloadProgress(
      (sent: number, total: number, name: string) => {
        this.onWebDownloadProgress(sent, total, name);
      });
    this.router.setOnDownloadEnd(
      (ok: boolean, name: string, totalBytes: number, error: string) => {
        this.onWebDownloadEnd(ok, name, totalBytes, error);
      });
    // 授权细节必须进日志。只看结果「未取得」永远定不了位：
    // -1+弹过窗 = 用户点了拒绝；-1+没弹窗 = 系统不再弹，只能去设置里改；
    // 2 = 请求非法（权限名/声明有问题）。三种处理方式完全不同。
    if (!grant.granted) {
      this.pushLog(`「下载」目录授权未通过（${grant.detail}），收到的文件将存入应用沙箱`);
    }
    this.snapshot.saveLocation = this.storage.describe;
    this.pushLog(`接收文件保存位置：${this.storage.describe}`);

    // ---- 2. 探测本机网络位置（枚举**所有**网络，见 resolveAllLocalNets 的说明）----
    // verbose=true：首次解析要把每个网络的接口/地址都打进 hilog，
    // 热点单向可见这类问题只有靠这些细节才能一次定位。
    this.probeSegments = [];
    this.localNets = await LanDiscovery.resolveAllLocalNets(true);
    this.localNet = this.localNets.length > 0 ? this.localNets[0] : new LocalNetInfo();
    // ⚠️ 拿不到局域网 IP **不再判定为启动失败**。
    // 真实场景里"暂时没有可广播的网"是常态而不是错误：
    //   - 手机只开蜂窝（没连 WiFi）：蜂窝口是 /32，广播地址就是自己，没有意义；
    //   - 刚开热点、接口还没起来；
    //   - 连了 WiFi 但 DHCP 还没下发地址。
    // 这时仍然要把 TCP/HTTP 服务拉起来（别人可以直连我的 IP），
    // 并用后台周期重解析去等网络就绪 —— 否则用户只能反复点「开始共享」。
    if (!this.localNet.valid) {
      this.pushLog('未检测到可广播的局域网（没连 WiFi？），服务仍将启动，等待网络就绪');
      this.setMessage('共享已开启，但未检测到局域网，等待网络…');
    } else {
      this.pushLog(`本机 IP ${this.localNet.ip}/${this.localNet.netMask} 广播 ${this.localNet.broadcastIp}`);
    }
    // 多子网必须如实打出来。热点场景排障全靠这一行：
    // 列出的子网数 > 1 就说明热点口被识别到了，广播会覆盖它。
    if (this.localNets.length > 1) {
      const lines: string[] = [];
      for (let i = 0; i < this.localNets.length; i++) {
        lines.push(this.localNets[i].text);
      }
      this.pushLog(`检测到 ${this.localNets.length} 个子网，广播将覆盖: ${lines.join(' | ')}`);
    }

    // ---- 3. 组装本机设备信息 ----
    this.self = new LanDevice();
    this.self.devName = LanConfig.userName.length > 0 ? LanConfig.userName : LanService.localDeviceName();
    this.self.devIp = this.localNet.ip;
    this.self.devNetMask = this.localNet.netMask;
    this.self.devBroadcastIp = this.localNet.broadcastIp;
    this.self.interfaceName = this.localNet.interfaceName;
    this.self.devPort = LanConfig.fileServerPort;
    // 关键：声明自己是鸿蒙端。原协议 Device.HARMONY_OS = 6
    this.self.devMode = DeviceMode.HARMONY_OS;
    this.self.dataVersion = LanConfig.DATA_VERSION;
    this.self.uniqueUuid = LanService.ensureUuid(ctx);
    this.self.isIPv4 = true;
    this.self.lastSeenMs = Date.now();

    // ---- 4. 拉起 TCP 服务（HTTP + 私有协议共用 5856） ----
    const listen: ListenResult = await this.tcp.start(LanConfig.fileServerPort);
    this.snapshot.listenDetail = listen.detail;
    this.pushLog(listen.detail);
    if (!listen.ok) {
      this.state = ServiceState.FAILED;
      this.setMessage(listen.detail);
      this.emit();
      return false;
    }
    // 端到端自检失败**不阻断**服务（可能只是本机回环被禁），但必须显著提示。
    // 注意这条自检是「连上 + 发 HTTP + 收到响应」三步都过才算通过——
    // 只测 TCP 握手是假绿灯，因为握手由内核完成，应用层可以是死的。
    // 自检不过 = 外部设备几乎必然也连不上，用户不该拿这个状态去试半天。
    if (!this.tcp.isSelfTestPassed) {
      this.pushLog(`⚠️ 自检未通过：${this.tcp.selfTestFailure}`);
      this.setMessage(`⚠️ 服务已启动但自检未通过：${this.tcp.selfTestFailure}`);
    }

    // ---- 5. 拉起 UDP 发现 ----
    this.discovery.setSelf(this.self);
    this.discovery.setOnFound((frame: UdpFrame, fromIp: string, fromPort: number) => {
      this.onDeviceFound(frame, fromIp, fromPort);
    });
    const udpOk: boolean = await this.discovery.start(LanConfig.udpPort);
    if (!udpOk) {
      this.pushLog('UDP 发现启动失败，仍然可以靠 IP 直连');
    } else {
      this.discovery.startPeriodicScan(this.localNets);
      // 网络是会变的：连上 WiFi、打开/关闭热点、DHCP 重新下发地址。
      // 只解析一次的话，这些变化在本次共享周期内永远不会被感知 ——
      // 于是就出现"先开应用后开热点，怎么都发现不了"这类假故障。
      // 周期重解析开销很小（几次 Binder 调用），换来的是自动适配。
      if (this.netRefreshTimer !== -1) {
        clearInterval(this.netRefreshTimer);
      }
      this.netRefreshTimer = setInterval(() => {
        this.refreshNetworks().catch((e: Error) => {
          Log.w(TAG, `网络重解析异常: ${e.message}`);
        });
      }, NET_REFRESH_MS);
    }

    // ---- 6. 前台会话（屏幕常亮 + 统计） ----
    // 不申请长时任务：本项目的使用姿势是"打开应用、停在页面上传输"，
    // 需要防的是息屏而不是退后台，setWindowKeepScreenOn 就够了。
    await this.session.startSession(ctx);

    // 设备下线巡检：UDP 是无连接的，对方关机不会通知任何人，只能靠超时判定。
    // 没有这个定时器，UI 要等下一次别人发包才刷新（见 sweepDevices 注释）。
    this.lastSweepSig = '';
    this.startDeviceSweep();

    this.state = ServiceState.RUNNING;
    // 没有可广播的局域网时，别把"浏览器访问 http://"这种空地址当成功提示
    if (this.localNet.valid) {
      this.setMessage(`共享已开启，浏览器访问 ${this.snapshot.webUrl}`);
    } else {
      this.setMessage('共享已开启，但未检测到局域网，等待网络…（可先用 IP 直连）');
    }
    this.emit();
    return true;
  }

  /**
   * 周期重解析本机网络，并把新的子网列表热替换进发现层。
   *
   * 覆盖的场景（这些都是真机上会发生的，不是理论可能）：
   *   - 先点「开始共享」、后打开热点：热点口晚于服务启动出现；
   *   - 只开蜂窝时启动：那时一个可广播子网都没有，连上 WiFi 后才出现；
   *   - 开关飞行模式 / 换 WiFi：IP 变了，继续广播旧网段等于对空气喊话。
   *
   * self.devIp 也要跟着更新 —— 它会被写进 UDP 报文和 TCP 握手 JSON，
   * 是**对端回连我的地址**（原版 Android 直接照单全收包里的 devIp）。
   * 地址过期 = 对端看得到我、却永远连不上。
   */
  private async refreshNetworks(): Promise<void> {
    if (this.state !== ServiceState.RUNNING) {
      return;
    }
    const nets: LocalNetInfo[] = await LanDiscovery.resolveAllLocalNets(false);
    const before: string = LanDiscovery.joinNets(this.localNets);
    const after: string = LanDiscovery.joinNets(nets);
    if (before === after) {
      return;
    }
    this.localNets = nets;
    this.localNet = nets.length > 0 ? nets[0] : new LocalNetInfo();
    if (this.localNet.valid) {
      this.self.devIp = this.localNet.ip;
      this.self.devNetMask = this.localNet.netMask;
      this.self.devBroadcastIp = this.localNet.broadcastIp;
      this.self.interfaceName = this.localNet.interfaceName;
    }
    // 发现层里那份列表也要换，否则还在往旧网段广播
    this.discovery.updateNets(nets);
    if (after.length > 0) {
      this.pushLog(`网络已变化，广播覆盖更新为: ${after}`);
      if (this.state === ServiceState.RUNNING) {
        this.setMessage(`共享已开启，浏览器访问 ${this.snapshot.webUrl}`);
      }
    } else {
      this.pushLog('网络已变化：当前没有可广播的局域网');
    }
    this.emit();
  }

  /**
   * 停止共享。三种触发路径：用户点停止 / 应用退到后台 / UIAbility 销毁。
   * 必须调用，否则会留下未释放的监听端口和置位的屏幕常亮。
   */
  async stopSharing(): Promise<void> {
    if (this.state !== ServiceState.RUNNING) {
      return;
    }
    this.state = ServiceState.STOPPED;
    this.stopDeviceSweep();
    if (this.netRefreshTimer !== -1) {
      clearInterval(this.netRefreshTimer);
      this.netRefreshTimer = -1;
    }
    // 先通知同网段设备下线
    if (this.localNet.valid) {
      await this.discovery.announceOffline(this.localNets);
    }
    this.discovery.stop();
    // 先关掉网页 WebSocket 长连接，否则它们会挂在已停掉的监听上
    this.closeAllWsSessions();
    // 必须 await：端口没释放就再次 start，listen 会 bind 失败并静默换随机端口
    await this.tcp.stop();
    await this.session.stopSession();
    this.snapshot.listenDetail = '';
    this.snapshot.transferText = '';
    this.setMessage('共享已停止');
    this.emit();
  }

  /**
   * 彻底关闭（UIAbility onDestroy 时调用）。
   *
   * 与 stopSharing 的区别：这里额外做**兜底复位**——
   * 即使上面某一步抛异常、或调用方漏了 stopSharing，也要保证
   * 屏幕常亮被关掉、端口被释放。否则会留下"应用已退出但屏幕不灭"的脏状态。
   */
  async shutdown(): Promise<void> {
    try {
      if (this.state === ServiceState.RUNNING) {
        await this.stopSharing();
      }
    } catch (e) {
      const err: Error = e as Error;
      Log.w(TAG, `shutdown 停服异常: ${err.message}`);
    }
    // 兜底：无论上面是否成功，都把监听、定时器和屏幕常亮复位
    this.stopDeviceSweep();
    if (this.netRefreshTimer !== -1) {
      clearInterval(this.netRefreshTimer);
      this.netRefreshTimer = -1;
    }
    try {
      this.discovery.stop();
      await this.tcp.stop();
    } catch (e) {
      // 端口可能本来就已释放，忽略
    }
    await this.session.dispose();
    this.state = ServiceState.STOPPED;
    this.emit();
    Log.i(TAG, 'LanService 已彻底关闭');
  }

  /** 把会话统计同步给会话层（供 UI 实时展示） */
  private syncStats(): void {
    const now: number = Date.now();
    let online: number = 0;
    this.devices.forEach((d: LanDevice) => {
      if (!this.deviceGone(d, now)) {
        online += 1;
      }
    });
    this.snapshot.onlineDevices = online;
    this.session.updateStats(
      online,
      this.snapshot.state === ServiceState.RUNNING ? this.transferredBytes : 0,
      this.router.requestCount
    );
  }

  /** 累计传输字节。由文件收发路径累加（B2 批次接入） */
  private transferredBytes: number = 0;

  addTransferred(bytes: number): void {
    this.transferredBytes += bytes;
  }

  /**
   * UDP 广播发现一台设备。
   *
   * ⚠️ 必须过滤自己：UDP 广播会回到本机（用的是 `SO_BROADCAST`，本机会收到自己发出去的包）。
   * 不过滤的话设备列表第一项永远是「自己」，用户很容易点到自己然后发给自己 ——
   * 真机上就出现过这一幕。判据优先用 `uniqueUUid`（唯一且稳定），
   * 退化时才用 IP + 端口比对。
   */
  private onDeviceFound(frame: UdpFrame, fromIp: string, fromPort: number): void {
    // 只要有人从某个网段发广播过来，就说明**我在那个网段也有地址**。
    // 这是比路由表更可靠的兜底：路由表应用可能读不到，但对端的包一定会到。
    this.learnSubnetFrom(fromIp);

    const d: LanDevice = frame.device;
    if (LanService.isSelf(d, this.self)) {
      return;
    }
    // 文本消息：安卓端**短消息走 UDP**（broadcastMessage 里 msg.length() <= 700 分支，
    // 命令 1004 / 1005）。早期版本只认 1001/1002，直接导致"安卓能收我的、我收不到安卓的"。
    if (frame.cmd === LCmd.UDP_DEVICES_MESSAGE ||
      frame.cmd === LCmd.UDP_DEVICES_MESSAGE_TO_CLIPBOARD) {
      this.onUdpTextMessage(frame, fromIp);
    }
    // ---- 收到「探测」立刻单播应答 ----
    // 对端广播 UDP_GET_DEVICES 就是在问「谁在线」。我们若不答，
    // 它只能等我们自己下一个 5s 周期心跳才知道有我们 —— 互相发现凭空慢半拍到一拍
    // （vivi 2026-10-01：「发现设备有点慢，官方版也很慢」）。
    // 直接单播回一个 UDP_SET_DEVICES，一轮广播之内双方就都认识了。
    if (frame.cmd === LCmd.UDP_GET_DEVICES) {
      this.replyProbe(fromIp);
    }
    const addKey: string = (d.uniqueUuid ?? '').length > 0 ? d.uniqueUuid : (d.devIp ?? '');

    // ---- 对端主动下线：立刻移除，不等超时 ----
    // ⚠️ 这是一个**缺失的协议分支**：原版 Android（1.35）在收到 1003 时会
    //    `if (device.isCanRemove()) devices.remove(key)` 立即删掉
    //    （smali: LANService.smali:14116-14157）；本工程此前只实现了**发送** 1003
    //    （`LanDiscovery.announceOffline`，对端关共享/退应用时广播），
    //    却**从来没有处理**收到的 1003 —— 于是对方正常退出也只能等 8~9s 超时。
    //    这正是「对方设备关闭后，设备列表里过一会才消失」最直接的原因。
    if (frame.cmd === LCmd.UDP_DEVICES_OFF_LINE) {
      this.dropDevice(addKey, d);
      return;
    }

    // ★ 同一 IP 只保留一条（5.0.21）：见 dropSameIpExcept 的注释。
    //   必须放在 get 之前 —— 否则同一台设备换过 uuid 就会在表里留下僵尸条目，
    //   它会因 TCP 复核（按 IP）被持续续命，群发时多投一份。
    this.dropSameIpExcept(d.devIp, addKey);
    const existing: LanDevice | undefined = this.devices.get(addKey);
    if (existing === undefined) {
      this.devices.set(addKey, d);
      // 进 hilog：热点单向可见这类问题，AI 只能靠日志自查，
      // 而 pushLog 只写界面不写 hilog，等于没有。
      Log.i(TAG, `发现设备 ${d.devName} 声明IP=${d.devIp} 实际来源=${fromIp}:${fromPort}`);
      this.pushLog(`发现设备 ${d.devName} (${d.manufacturer}) @ ${d.devIp}`);
      this.store.upsertDevice(d);
    } else {
      // 刷新在线时间与可能变化的字段
      existing.lastSeenMs = Date.now();
      existing.devIp = d.devIp;
      existing.devName = d.devName;
      existing.batteryLevel = d.batteryLevel;
      existing.chargeStatus = d.chargeStatus;
      // ⚠️ 收到包 = 它还活着的**直接证据**，TCP 复核的失败计数必须清零。
      //    否则「关掉前的最后两次复核失败」会被后来的心跳带上，
      //    它下一次刚安静 1.2s 就被判死 —— 那是在线设备被误杀。
      if (d.devIp.length > 0) {
        this.tcpProbeMiss.delete(d.devIp);
      }
    }
    // 设备上下线要立刻同步给网页，否则下拉框里还是旧列表
    this.broadcastDeviceList();
    this.syncStats();
    // ⚠️ 这里用**节流版**：多台设备在一轮广播里同时被看到时会连着进多次，
    //    每次都整页重渲染是纯浪费（界面上看到的就是"卡一下"）。
    //    设备列表的更新不差这 100ms。
    this.emitThrottled();
  }

  /**
   * 把一台设备从「在线表」里摘掉，并刷新相关派生状态。
   *
   * 注意它**不碰**任何正在进行的 TCP 传输：文件收发用的是各自独立的长连接，
   * 设备条目只是「地址簿 + 在线状态」，删掉它不会中断在途数据。
   */
  private dropDevice(key: string, d: LanDevice): boolean {
    if (!this.devices.delete(key)) {
      return false;
    }
    this.probeSentAt.delete(d.devIp);
    this.tcpProbeBusy.delete(d.devIp);
    this.tcpProbeMiss.delete(d.devIp);
    this.tcpEverOk.delete(d.devIp);
    this.lastTcpProbeAt.delete(d.devIp);
    Log.i(TAG, `设备下线：已移除 ${d.devName} @ ${d.devIp}`);
    this.pushLog(`${d.devName.length > 0 ? d.devName : d.devIp} 已下线`);
    this.broadcastDeviceList();
    this.syncStats();
    this.emit();
    return true;
  }

  /**
   * 同一 IP 只保留一个设备条目（5.0.21 定案，真机复现过）。
   *
   * ⚠️ 为什么必须做：`devices` 的 key 是 **uniqueUuid**，而 `tcpProbeStep` 的
   *    TCP 复核**只认 IP** —— 复核成功就把该条目的 `d.lastSeenMs` 刷新。
   *    于是同一台物理机只要换过 uuid（重装 App、官方版与 1.35 双版本共存、
   *    清数据），旧条目就会被新条目的存活**续命**，`DEVICE_OFFLINE_MS`(8s)
   *    永远清不掉。后果：`onlineDeviceList()` 返回多条同 IP 记录，
   *    群发消息时**同一台设备收到 N 份**。
   *    真机取证（修复前 hilog，同一秒三条）：
   *      `已发送消息到 DBY-W09（192.168.10.100:5856，协议 v4，3 字）`
   *      `已发送消息到 DBY-W09（192.168.10.100:5856，协议 v4，3 字）`
   *      `已发送消息到 DBY-W09（192.168.10.100:5856，协议 v5，3 字）`
   *
   * 局域网内一个 IP 就是一台设备，按 IP 归并是安全的。
   * ⚠️ 注意**不要**清 per-IP 的探测状态（probeSentAt / tcpEverOk / tcpProbeMiss /
   *    lastTcpProbeAt）—— 那些键是 IP，跟着保留下来的条目继续有效；
   *    清理它们是 `dropDevice`（设备**真的**下线）才该做的事。
   */
  private dropSameIpExcept(ip: string, keepKey: string): void {
    if (ip.length === 0) {
      return;
    }
    const victims: string[] = [];
    this.devices.forEach((d: LanDevice, k: string) => {
      if (k !== keepKey && d.devIp === ip) {
        victims.push(k);
      }
    });
    for (let i = 0; i < victims.length; i++) {
      const old: LanDevice | undefined = this.devices.get(victims[i]);
      this.devices.delete(victims[i]);
      Log.i(TAG, `同 IP 去重：移除旧条目 ${old !== undefined ? old.devName : '?'}`
        + ` key=${victims[i]} @ ${ip}（保留 key=${keepKey}）`);
    }
  }

  /**
   * 对某台**安静了一会儿**的设备做一次 UDP 单播探活。
   *
   * 用的是 `UDP_GET_DEVICES` —— 对端若愿意处理它就会立刻回一个心跳，
   * 天然就是一次 ping，`onDeviceFound` 顺手把 `lastSeenMs` 刷新掉。
   *
   * ⚠️ 它**不参与判死**。理由见 LanConfig.DEVICE_TCP_PROBE_* 那段：
   *    把判死挂在「对端愿不愿意回这个报文」上，等于把下线速度交给对端的实现细节。
   */
  private sendLivenessProbe(ip: string, now: number): void {
    if (ip.length === 0 || this.self.devIp.length === 0) {
      return;
    }
    const pkt: Uint8Array = DeviceCodec.buildHeartbeat(
      this.self, LCmd.UDP_GET_DEVICES, this.self.devIp);
    this.probeSentAt.set(ip, now);
    this.discovery.sendTo(pkt, ip).catch((e: Error) => {
      Log.w(TAG, `单播探活失败 -> ${ip}: ${e.message}`);
    });
  }

  /**
   * 是否判「已下线」。
   *
   * 这里**只有一条**判据：`DEVICE_OFFLINE_MS` 内没再收到任何消息。
   * 快速判死不在这里 —— 它由 {@link tcpProbeStep} 的 TCP 复核回调直接
   * `dropDevice`，因为「TCP 连不上」是个**确定性事实**，而「UDP 没回包」不是。
   */
  private deviceGone(d: LanDevice, now: number): boolean {
    return now - d.lastSeenMs > LanConfig.DEVICE_OFFLINE_MS;
  }

  /**
   * 回应对方的 `UDP_GET_DEVICES` 探测（**单播**）。
   *
   * 这是「设备发现慢」最直接的解法：原本双方都只按自己的 5s 周期广播，
   * 于是「我发一轮 → 你下一轮才回」最坏要等一整个周期。
   * 对方既然主动问了，我们当场回答即可，一轮广播内双向可见。
   *
   * @param ip 探测包的真实来源 IP（用 remoteInfo 而不是包里的 devIp，防伪造）
   */
  private replyProbe(ip: string): void {
    if (ip.length === 0 || this.self.devIp.length === 0) {
      return;
    }
    const now: number = Date.now();
    const last: number = this.probeReplyAt.get(ip) ?? 0;
    // 同一 IP 1s 内只回一次：对端若把探测打得很密，我们不至于跟着放大成风暴
    if (now - last < 1000) {
      return;
    }
    this.probeReplyAt.set(ip, now);
    // 报文的 devIp 用**本机当前地址** —— 它就是对方回连我 5856 用的地址，
    // 填错等于告诉对方一个连不上的地址（见 DeviceCodec.buildHeartbeat 注释）。
    const pkt: Uint8Array = DeviceCodec.buildHeartbeat(
      this.self, LCmd.UDP_SET_DEVICES, this.self.devIp);
    this.discovery.sendTo(pkt, ip).catch((e: Error) => {
      Log.w(TAG, `应答探测失败 -> ${ip}: ${e.message}`);
    });
  }

  /**
   * 从对端 IP 反推「我在那个网段的地址」，补进广播列表。
   *
   * 为什么需要它：`probeHiddenNets` 依赖 /proc/net/route 与常见网段猜测，
   * 两者都可能失败。但**只要对端广播过一次**，我们就知道有设备在某个网段，
   * 而它能把包递到我这里，说明我在那个网段必然也有地址 ——
   * 于是试一下网段首地址（软 AP 永远是网段的第一个地址）就能确认。
   *
   * 这正好修掉「手机开热点、平板发现不了手机」里最麻烦的那半边：
   * 只要平板在热点下跑着（它会周期广播 UDP_SET_DEVICES），
   * 我们迟早能学会 192.168.43.1 并往 192.168.43.255 广播，双向就通了。
   *
   * 每个网段只试一次（probeSegments 去重），避免每 5 秒都去 bind 探测。
   */
  private learnSubnetFrom(peerIp: string): void {
    const p: number[] = LanDiscovery.parseIpv4(peerIp);
    if (p.length !== 4 || p[0] === 127) {
      return;
    }
    const seg: string = `${p[0]}.${p[1]}.${p[2]}`;
    if (this.probeSegments.indexOf(seg) >= 0) {
      return;
    }
    // 已经广播过的网段不用学
    for (let i = 0; i < this.localNets.length; i++) {
      if (LanDiscovery.sameSegment(this.localNets[i].ip, `${seg}.0`, '255.255.255.0')) {
        return;
      }
    }
    this.probeSegments.push(seg);
    LanDiscovery.probeSegment(`${seg}.0`).then((info: LocalNetInfo) => {
      if (!info.valid) {
        return;
      }
      this.localNets.push(info);
      if (!this.localNet.valid) {
        this.localNet = info;
        this.self.devIp = info.ip;
        this.self.devNetMask = info.netMask;
        this.self.devBroadcastIp = info.broadcastIp;
        this.self.interfaceName = info.interfaceName;
      }
      this.discovery.updateNets(this.localNets);
      this.pushLog(`按对端 ${peerIp} 反查到本机地址 ${info.ip}，广播已覆盖 ${info.broadcastIp}`);
      this.emit();
    }).catch((e: Error) => {
      Log.w(TAG, `反查网段 ${seg} 异常: ${e.message}`);
    });
  }

  /**
   * UDP 文本消息（1004 / 1005）。
   * 对应 LANService.handleUdpCmd() 的 UDP_DEVICES_MESSAGE 分支：
   *   `String messageEnc = dataDec.getString();`  // AES 密文（hex）
   *   `String packageName = dataDec.getString();`
   *   `AESUtils.decrypt(messageEnc, Config.MESSAGE_KEY)`
   *
   * ⚠️ 这是安卓端**绝大多数**情况下的投递路径：
   * `broadcastMessage()` 里只有 msg.length() > 700 才走 TCP(1105)，
   * 短消息一律 UDP 单播到对端的 Config.UDP_PORT。
   * 不实现这条 = 单向能发不能收。
   */
  private onUdpTextMessage(frame: UdpFrame, fromIp: string): void {
    const d: LanDevice = frame.device;
    if (frame.extras.length === 0) {
      Log.w(TAG, `UDP 消息帧缺少密文字段，来自 ${fromIp}`);
      return;
    }
    const enc: string = frame.extras[0];
    let text: string = '';
    try {
      text = AesCodec.decrypt(enc, LanConfig.messageKey);
    } catch (e) {
      const err: Error = e as Error;
      // 解密失败也要让用户看见：静默丢弃会表现为"对面发了，我这边毫无动静"
      this.pushLog(`收到一条无法解密的消息（来自 ${d.devName}）：${err.message}`);
      Log.w(TAG, `UDP 消息解密失败: ${err.message}`);
      this.emit();
      return;
    }
    const who: string = d.devName.length > 0 ? d.devName : fromIp;
    this.pushLog(`消息 <${who}>: ${text}`);
    this.appendChat(true, who, fromIp, text, 'device');
    this.broadcastChatToWeb(who, text, true);
    this.store.insertMessage({
      msgId: `${Date.now()}-${Math.floor(Math.random() * 100000)}`,
      peerIp: fromIp,
      direction: 0,
      content: text,
      msgType: frame.cmd,
      length: text.length,
      createdAt: Date.now()
    });
    this.emit();
  }

  /** 是否就是本机自己 */
  private static isSelf(d: LanDevice, self: LanDevice): boolean {
    if (d.uniqueUuid.length > 0 && self.uniqueUuid.length > 0) {
      return d.uniqueUuid === self.uniqueUuid;
    }
    return d.devIp.length > 0 && d.devIp === self.devIp && d.devPort === self.devPort;
  }

  // ------------------------------------------------------------------
  // 网页 WebSocket 会话（GET /wss）
  // ------------------------------------------------------------------

  /**
   * 接管一条升级完成的 WebSocket 通道。
   *
   * 由 `WsUpgradeRouter.setSink` 回调进来，**必须立刻返回** ——
   * 它是在 `HttpRouter.serve()` 的收尾路径上同步调用的；
   * 若在这里 await 住帧循环，accept 侧会以为这条连接还没处理完，
   * 而它恰恰是长连接，永远等不到「处理完」的那一刻。
   */
  private adoptWsChannel(channel: TcpChannel): void {
    const s: WebSocketSession = new WebSocketSession(
      channel,
      () => this.wsDeviceListMessage(),
      (json: string, peer: string) => this.wsRelayChat(json, peer),
      (closed: WebSocketSession) => {
        const i: number = this.wsSessions.indexOf(closed);
        if (i >= 0) {
          this.wsSessions.splice(i, 1);
        }
        this.snapshot.wsClients = this.wsSessions.length;
        this.pushLog(`网页会话结束（剩余 ${this.wsSessions.length} 个）`);
        this.emit();
      });
    this.wsSessions.push(s);
    this.snapshot.wsClients = this.wsSessions.length;
    this.pushLog(`网页 WebSocket 已建立（${s.peer}），当前 ${this.wsSessions.length} 个`);
    this.emit();
    s.start();
  }

  /**
   * 设备列表消息（SYNC_DEVICE_LIST）。
   *
   * ⚠️ 字段名必须跟 rawfile/web/js/lanshareChat.min.js 对齐：
   * 它读的是 `address` / `devName` / `devIP`，少一个网页上那个下拉框就是空的。
   */
  private wsDeviceListMessage(): string {
    const list: LanDevice[] = this.onlineDeviceList();
    let arr: string = '';
    for (let i = 0; i < list.length; i++) {
      if (i > 0) {
        arr += ',';
      }
      const d: LanDevice = list[i];
      arr += `{"address":${HttpRouter.jsonStr(d.devIp)},` +
        `"devName":${HttpRouter.jsonStr(d.devName)},` +
        `"devIP":${HttpRouter.jsonStr(d.devIp)},"devType":0}`;
    }
    return `{"cmd":${WS_CMD_SYNC_DEVICE_LIST},"data":[${arr}]}`;
  }

  /**
   * 网页发来一条聊天消息 —— 转发给局域网设备，并记进本机聊天列表。
   *
   * 对应 Android `LHttpServer` 里 WebSocket 的 `cmd == WSCmd.SEND_MSSAGE` 分支：
   * ```
   * String selectedDevice = jsonObject.getString("selectedDevice");
   * if (StringUtils.isEmpty(selectedDevice)) instance.broadcastMessage(null, message, isClip, "", false);
   * else                                             instance.broadcastMessage(device, message, isClip, "", false);
   * ```
   * `broadcastMessage` 内部就是 `AESUtils.encrypt(msg, Config.MESSAGE_KEY)` 后走
   * `FileSend.sendMessage` —— 也就是 TextMessenger 那套字节序。
   *
   * ⚠️ **不回显给网页**：浏览器在发送时已经本地 `addMessage()` 画过右侧气泡了
   * （见 rawfile/web/js/lanshareChat.min.js 的 sendMessage），
   * 这里再推一次会让同一条消息在网页上出现两遍。Android 侧传的也是 shareWS=false。
   *
   * @param json 网页发来的原始 JSON
   * @param peer 网页会话标识（ip:port），用作消息来源名
   */
  private wsRelayChat(json: string, peer: string): void {
    Log.i(TAG, `网页消息: ${json}`);
    const res: JsonParseResult = MiniJson.parse(json);
    if (!res.ok) {
      this.pushLog('网页消息解析失败，已忽略');
      this.emit();
      return;
    }
    const text: string = res.root.field('message') === null
      ? '' : (res.root.field('message') as JsonNode).asString('');
    if (text.length === 0) {
      // 文件类的 cmd:1（messageType=1/2）暂未迁移：网页端把文件转成 /chatUploadFile
      // 走另一条 HTTP 通道，这里只处理纯文本，避免把文件名当聊天内容发出去。
      this.pushLog('网页发来的消息不是纯文本（可能是图片/文件消息），已跳过');
      this.emit();
      return;
    }
    const sel: JsonNode | null = res.root.field('selectedDevice');
    const selectedDevice: string = sel === null ? '' : sel.asString('');
    const clipNode: JsonNode | null = res.root.field('isClip');
    const isClip: boolean = clipNode === null ? false : clipNode.asBool(false);

    // 记进本机聊天列表（网页 → 手机：对手机来说是「收到」）
    this.appendChat(true, `网页端 ${peer}`, '', text, 'web');

    const targets: LanDevice[] = this.resolveTargets(selectedDevice);
    if (targets.length === 0) {
      this.pushLog(`网页消息没有可投递的设备（目标「${selectedDevice.length > 0 ? selectedDevice : '所有设备'}」），仅记录在手机端`);
      this.emit();
      return;
    }
    // 转发是网络动作，不能阻塞帧循环（websocket 的读循环就等在 onChat 返回）
    this.dispatchText(targets, text, isClip);
  }

  /**
   * 把消息解析成目标设备列表。
   * @param address 网页下拉框给的值。空串 = 所有在线设备（与 Android 一致）
   */
  private resolveTargets(address: string): LanDevice[] {
    const online: LanDevice[] = this.onlineDeviceList();
    if (address.length === 0) {
      return online;
    }
    const hit: LanDevice[] = [];
    for (let i = 0; i < online.length; i++) {
      const d: LanDevice = online[i];
      // 网页下拉框的 value 由 wsDeviceListMessage() 给出，目前是纯 IP；
      // 同时兼容 "ip:port" 形式（Android 的 address 就是这个格式）。
      if (d.devIp === address || `${d.devIp}:${d.devPort}` === address) {
        hit.push(d);
      }
    }
    return hit;
  }

  /** 异步把文本投递给一批设备，并把结果写回聊天列表与日志 */
  private dispatchText(targets: LanDevice[], text: string, isClip: boolean): void {
    this.deliverText(this.self, targets, text, true, isClip).catch((e: Error) => {
      Log.w(TAG, `消息投递异常: ${e.message}`);
    });
  }

  /**
   * 逐台投递文本消息。
   *
   * @param recordLocal true 时把「自己发出」也写进聊天列表（App 主动发送时用）。
   *                    网页转发进来的消息已经记过一条「收到」，这里传 false 避免重复。
   */
  private async deliverText(
    self: LanDevice, targets: LanDevice[], text: string, recordLocal: boolean, isClip: boolean
  ): Promise<void> {
    let okCount: number = 0;
    const failures: string[] = [];
    for (let i = 0; i < targets.length; i++) {
      const t: LanDevice = targets[i];
      const r: TextSendResult = await TextMessenger.send(self, t, text, isClip);
      if (r.ok) {
        okCount += 1;
        this.pushLog(`消息已送达 ${t.devName}`);
      } else {
        failures.push(`${t.devName}：${r.error}`);
        this.pushLog(`消息发送到 ${t.devName} 失败：${r.error}`);
      }
    }
    if (recordLocal) {
      this.appendChat(false, targets.length === 1 ? targets[0].devName : `所有设备（${targets.length} 台）`,
        '', okCount > 0 ? text : `${text}  〔发送失败〕`, 'app');
    }
    this.emit();
  }

  /**
   * App 主动发一条文本消息（消息页的「发送」按钮）。
   *
   * @param target 目标设备；null 表示发给所有在线设备
   * @returns 给 UI 直接 toast 的一句话
   */
  async sendTextMessage(target: LanDevice | null, text: string, isClip: boolean): Promise<string> {
    const msg: string = text.trim();
    if (msg.length === 0) {
      return '消息内容不能为空';
    }
    if (!this.isRunning) {
      return '共享未开启，请稍候重试';
    }
    const targets: LanDevice[] = target === null ? this.onlineDeviceList() : [target];
    if (targets.length === 0) {
      // 没有局域网设备时也允许发 —— 至少能推到同一个网页会话上，
      // 否则用户会以为「聊天功能坏了」，而实际只是当前没有对端设备。
      this.appendChat(false, '本机', '', msg, 'app');
      this.broadcastChatToWeb(this.self.devName.length > 0 ? this.self.devName : '手机', msg, false);
      this.pushLog('当前没有在线设备，消息已记录并推送到网页端');
      this.emit();
      return '当前没有在线设备，消息仅推送到网页端';
    }

    const who: string = targets.length === 1 ? targets[0].devName : `所有设备（${targets.length} 台）`;
    this.appendChat(false, who, '', msg, 'app');
    // 与 Android broadcastMessage(shareWS=true) 一致：本机发出的消息也同步给网页，
    // 这样「PC 网页 ←→ 手机 ←→ 安卓设备」三方能互相看见。
    this.broadcastChatToWeb(`${who} ← ${this.self.devName}`, msg, false);
    this.emit();

    let okCount: number = 0;
    const failures: string[] = [];
    for (let i = 0; i < targets.length; i++) {
      const r: TextSendResult = await TextMessenger.send(this.self, targets[i], msg, isClip);
      if (r.ok) {
        okCount += 1;
      } else {
        failures.push(r.error);
      }
    }
    this.emit();
    if (okCount === 0) {
      this.setMessage(`消息发送失败：${failures.length > 0 ? failures[0] : '未知原因'}`);
      this.emit();
      return `发送失败：${failures.length > 0 ? failures[0] : '未知原因'}`;
    }
    this.pushLog(`消息已发送到 ${targets.length} 台设备（成功 ${okCount} 台）`);
    this.emit();
    return failures.length === 0 ? '已发送' : `部分失败（成功 ${okCount}/${targets.length}）：${failures[0]}`;
  }

  /** ★ 5.0.55：批号自增计数（只要求唯一，不需要有语义） */
  private batchSeq: number = 0;

  /**
   * ★ 5.0.55：生成一个批号 —— 同一次传输拆出的多条媒体消息共享同一个值。
   * ⚠️ 不用「第一条消息的 id」当批号：那要先拿到 id 才能建后续条目，
   *    而 id 是在 `appendChat` 内部生成的，会绕成两段式写入。
   *    独立自增 + 时间戳最简单，且永不与 `c…` 形态的消息 id 相撞。
   */
  private nextBatchId(): string {
    this.batchSeq += 1;
    return `g${this.batchSeq}-${Date.now()}`;
  }

  /**
   * 新增一条聊天记录。
   * 与 Android 的 MessageContent 对齐：`incoming` 对应它的 `isLeft`。
   *
   * ★ 5.0.55：新增 `batchId`（默认空串）—— 见 `ChatMessage.batchId` 的注释。
   *   全部既有调用点都不传，行为不变。
   */
  private appendChat(
    incoming: boolean, peerName: string, peerIp: string, content: string, source: string,
    kind: string = 'text', files: string = '', batchId: string = '',
    meta: string = ''
  ): void {
    const m: ChatMessage = new ChatMessage();
    this.chatSeq += 1;
    m.id = `c${this.chatSeq}-${Date.now()}`;
    m.incoming = incoming;
    m.peerName = peerName;
    m.peerIp = peerIp;
    m.content = content;
    m.timeMs = Date.now();
    m.source = source;
    m.kind = kind;
    m.files = files;
    m.meta = meta;   // ★ 5.1.47
    m.batchId = batchId;
    this.chatRing.push(m);
    while (this.chatRing.length > MAX_CHAT) {
      this.chatRing.shift();
    }
    // 落盘（防抖合并，见 scheduleChatSave）。
    // 不落盘的话历史记录只活在内存里，退出应用即丢。
    this.scheduleChatSave();
  }

  /**
   * ★ 5.0.53（vivi 2026-10-02 要求）：一条文件传输记录 ——
   *   **接收多个图片/视频时，每个媒体一条记录**；其它情况仍合并成一条。
   *
   * ⚠️ 为什么必须拆（这是「删一张，整批失效」的真根因）：
   *   对端一次发 N 张图，本端只产生**一条**「N 个文件」消息
   *   （`V5Transfer` / `FileTransfer` 都是收完整批才回一次终态，名字合并成
   *   「N 个文件」）。于是「消息 id」这个**最粗**的标识被当成了「一张图」的
   *   标识 —— 相册 uri、缩略图文件名、旋转角全在一批里共用：
   *   删掉其中一张 ⇒ 整条记录标废 ⇒ 这一批**全部**提示「已从相册删除」；
   *   点击也只有一个入口（只能指向第 1 张），点不到第 2 张。
   *   拆成 N 条之后，每条消息天然对应一张图 —— 所有既有逻辑
   *   （缩略图 / 跳相册 / 删除 / ForEach key）自动正确，不需要再靠下标兜。
   *
   * ⚠️ **只拆接收方向**（vivi 明确要求）：自己发出去的多张图仍是一条
   *   「已发送 N 个文件」—— 发送侧点气泡只是跳「文件」页，没有相册语义，
   *   拆开只会让聊天记录变啰嗦。
   *
   * ⚠️ **整批全是媒体**才拆。混合批（1 张图 + 1 个 zip）保持一条 ——
   *   否则「图片一条、打包文件又一条」会让用户以为收了两次。
   *
   * @param label 合并后的文案（单发 = 文件名，多发 = 「N 个文件」）
   * @param names 这一批的**全部文件名**（顺序 = 传输顺序），可能为空数组
   */
  private appendFileChat(incoming: boolean, peerName: string, peerIp: string,
                         label: string, names: string[], source: string,
                         meta: string = ''): void {   // ★ 5.1.47
    if (incoming && names.length > 1 && LanService.allMedia(names)) {
      // ★ 5.0.55：这一批共用一个批号 —— UI 靠它把 N 条聚合成**一个**宫格气泡，
      //   而每条仍各自独立记账（点第 k 张 = 第 k 张，删第 k 条不影响其余）。
      const bid: string = this.nextBatchId();
      for (let i: number = 0; i < names.length; i++) {
        // 每条只带**自己那个**文件名：`content` = 名字（气泡文案）、
        // `files` = 名字（UI 靠它解析出媒体下标 0）。
        // ★ 5.1.49：补传 meta —— 5.1.47 加了 meta 参数却**忘了往下传**，
        //   导致气泡里 `m.meta` 恒为空 ⇒ 「大小 · 平均速度」永远不显示。
        this.appendChat(true, peerName, peerIp, names[i], source, 'file', names[i], bid, meta);
      }
      return;
    }
    // ★★ 5.1.4（vivi 21:28）：**非媒体也逐个文件建消息** —— vivi 要求
    //   「收到多个文件就生成多个气泡，不要再合并为一个气泡」。
    //
    //   此前这里把整批塞进**一条**消息（content=label、files=全部名字、batchId=空）
    //   ⇒ `buildChatGroups` 只按 batchId 聚合 ⇒ 空串 ⇒ **一个气泡**。
    //
    //   ⚠️⚠️ **绝不能顺手给非媒体共 batchId**：`groupAllMedia` 走 `allMedia(names)`，
    //   而 `allMedia` 对 zip/pdf 返回 **false** ⇒ `isMedia=false` ⇒ 不走宫格
    //   ⇒ **界面看起来完全没变**。**「拆成多条消息」与「聚合成一个宫格」是两个
    //   独立开关**（前者控消息条数，后者控渲染形式）—— 5.0.55 只把前者用于媒体。
    //   ⇒ 正确做法：**拆消息、batchId 留空**。
    //
    //   媒体批在上面已经 return 了，所以这里必然**不含**图片/视频。
    if (names.length > 1) {
      for (let i: number = 0; i < names.length; i++) {
        // 每条：content = 自己的文件名（气泡显示它）、files = 自己的文件名
        // （5.1.3 的 `msgCarriesFileName` 靠它反查）、batchId = 空（各自成气泡）
        // ★ 5.1.49：同上，补传 meta
        this.appendChat(incoming, peerName, peerIp, names[i], source, 'file', names[i], '', meta);
      }
      return;
    }
    this.appendChat(incoming, peerName, peerIp, label, source, 'file',
      names.join('\n'), '', meta);
  }

  /** 这一批是不是**全是**图片/视频 —— 决定要不要拆成「每个一条消息」 */
  private static allMedia(names: string[]): boolean {
    if (names.length === 0) {
      return false;
    }
    for (let i: number = 0; i < names.length; i++) {
      if (!LanService.isMediaFileName(names[i])) {
        return false;
      }
    }
    return true;
  }

  /**
   * 按扩展名判断图片/视频（表与 `Index.ets` 的 `isImageName` / `isVideoName` 完全一致）。
   *
   * ⚠️ 两边必须是**同一个判定**：这里决定「接收时拆不拆消息」，
   *   `Index.ets` 决定「显不显示缩略图 / 点开进不进预览」。
   *   一旦不一致就会出现「拆了却没缩略图」或「没拆却有缩略图」的错位。
   *   所以 `Index.isMediaName` 现在直接委托到本方法（唯一真源）。
   */
  /**
   * ★★ 5.1.48：剥掉文件名尾部的**复制/去重后缀** ` (n)`。
   *
   * ## 为什么必须剥
   *   `扫描全能王 2026-10-01 09.47.jpg (1)`（安卓相册/QQ/微信导出常见形态）
   *   直接 `lastIndexOf('.')` 取到的后缀是 `jpg (1)` ⇒ 匹配不上 `jpg`
   *   ⇒ 图片被当成普通文件：不进媒体库、消息气泡不显示缩略图、落盘归「其他」。
   *   ★ 注意这个文件名里**有两个点**（`09.47` 和 `.jpg`），所以不能简单取第一个点。
   *
   * ## 形态覆盖（只需认「空格 + 圆括号 + 纯数字 + 右括号」这一种）
   *   `a.jpg (1)` → `a.jpg`   `a (1).jpg` → 本来就对（点在括号后）
   *   `a.jpg (12)` → `a.jpg`  `a.jpg(1)` → `a.jpg`（左括号前无空格也认）
   *   `a.jpg (1) (2)` → `a.jpg`（循环剥）
   *   `report (2026).pdf` → **不剥**（括号里不是纯数字，是文件名的一部分）
   */
  /** ★ 5.1.50：去尾部空白（空格/制表符）。ArkTS 无 `trimEnd`，手写。 */
  static rtrim(s: string): string {
    let e: number = s.length;
    while (e > 0) {
      const c: number = s.charCodeAt(e - 1);
      if (c !== 0x20 && c !== 0x09 && c !== 0x0A && c !== 0x0D) {
        break;
      }
      e -= 1;
    }
    return e === s.length ? s : s.substring(0, e);
  }

  static stripCopySuffix(name: string): string {
    let n: string = name;
    // 最多剥 8 层，防御 `a (1) (2) (3) ...` 之类畸形输入
    for (let k: number = 0; k < 8; k++) {
      // ★★ 5.1.50：**先去掉尾部空白再判断**。
      //   `扫描全能王 2026-10-01 09.47.jpg (1)` 的 `(` **前面**有一个空格，
      //   剥掉 `(1)` 后剩下 `...jpg ` ⇒ ext 变成 `'jpg '`（带尾随空格）
      //   ⇒ 匹配不上 `'jpg'` ⇒ 图片仍被当普通文件（5.1.48 漏了这一步）。
      n = LanService.rtrim(n);
      if (!n.endsWith(')')) {
        return n;
      }
      const lp: number = n.lastIndexOf('(');
      if (lp < 0) {
        return n;
      }
      const inner: string = n.substring(lp + 1, n.length - 1);
      if (inner.length === 0 || inner.length > 6) {
        return n;
      }
      let allDigit: boolean = true;
      for (let i: number = 0; i < inner.length; i++) {
        const c: number = inner.charCodeAt(i);
        if (c < 0x30 || c > 0x39) {
          allDigit = false;
          break;
        }
      }
      if (!allDigit) {
        return n;
      }
      n = n.substring(0, lp);
    }
    return n;
  }

  /**
   * ★★ 5.1.48：取小写扩展名（**唯一真源**）。
   * 先剥 ` (n)` 再取点后段，避免 `xxx.jpg (1)` 这类文件名拿不到真扩展名。
   * 无扩展名时返回空串。**所有判定扩展名的地方都必须走这个函数。**
   */
  /**
   * ★★ 5.1.52：已知扩展名表 —— 用于「从右往左找哪一段才是扩展名」。
   * ⚠️ 与 `FileKinds.KNOWN_EXTS` / `MagicType.KNOWN_EXTS` 是**三份同款拷贝**
   *   （分层导致，避免循环依赖）。**改一处必须同步另外两处。**
   */
  private static readonly KNOWN_EXTS: string[] = [
    'jpg', 'jpeg', 'jfif', 'png', 'gif', 'bmp', 'webp', 'heic', 'heif',
    'avif', 'ico', 'tif', 'tiff', 'heics',
    'mp4', 'mov', 'm4v', 'mkv', 'webm', 'avi', '3gp', 'flv', 'ts',
    'wmv', 'rmvb', 'mpg', 'mpeg', 'ogv',
    'mp3', 'aac', 'm4a', 'wav', 'flac', 'ogg', 'ape',
    'zip', 'rar', '7z', 'apk', 'pdf', 'txt', 'doc', 'docx',
    'xls', 'xlsx', 'ppt', 'pptx',
  ];

  /**
   * ★★ 5.1.52：**正确**地把文件名拆成「主干 + 扩展名」。
   *
   * ## 为什么不能用 `lastIndexOf('.')`（5.1.51 实测失败的原因）
   *   `IMG_20260929_201632.jpg.1` ⇒ 旧逻辑 ext=`'1'`
   *   ⇒ ① 魔数纠错判不出该改成 jpg（**没改名**）
   *     ② 存相册 `fileNameExtension='1'` ⇒ **系统拒绝建资产**（真机失败）。
   *   `a.jpg (1)` / `x.jpg.1.1` / `报告 v1.2.pdf` 同样会被误切。
   *
   * ## 规则：从右往左找**第一个命中 KNOWN_EXTS** 的段当扩展名，左侧全部是 stem。
   *   命中不了（如 `data.2026-10-01.dat`）⇒ 空 ext，**交给魔数**判断。
   *
   * ★ 已用 11 条真实文件名在 Python 里验证过（`.jpg.1` / `.jpg (1)` / `.jpg.1.1` /
   *   `报告 v1.2.pdf` / `a.b.c.d.png` / `无扩展名文件` 等全部符合预期）。
   */
  static splitExt(fileName: string): string[] {
    const base: string = LanService.rtrim(LanService.stripCopySuffix(fileName));
    const parts: string[] = base.split('.');
    for (let i: number = parts.length - 1; i >= 1; i--) {
      const cand: string = LanService.rtrim(parts[i]).toLowerCase();
      if (LanService.KNOWN_EXTS.indexOf(cand) >= 0) {
        return [base.substring(0, base.length - parts[i].length - 1), cand];
      }
    }
    return [base, ''];
  }

  static extOf(fileName: string): string {
    // ★ 5.1.52：改走 splitExt —— 它能正确处理 `x.jpg.1` / `x.jpg (1)` / `报告 v1.2.pdf`
    return LanService.splitExt(fileName)[1];
  }

  static isMediaFileName(name: string): boolean {
    const ext: string = LanService.extOf(name);
    if (ext.length === 0) {
      return false;
    }
    return ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'gif'
      || ext === 'webp' || ext === 'bmp' || ext === 'heic' || ext === 'heif'
      || ext === 'avif' || ext === 'ico' || ext === 'tif' || ext === 'tiff'
      || ext === 'mp4' || ext === 'mov' || ext === 'mkv' || ext === 'webm'
      || ext === 'avi' || ext === '3gp' || ext === 'm4v' || ext === 'ts'
      || ext === 'flv' || ext === 'wmv' || ext === 'rmvb' || ext === 'mpg'
      || ext === 'mpeg' || ext === 'ogv';
  }

  /**
   * 把一条聊天内容推给所有网页会话。
   *
   * 字段与 rawfile/web/js/lanshareChat.min.js 的 `addMessage()` 严格对齐：
   * 少了 `messageType` 网页会走 else 分支去找图片，直接抛错。
   */
  private broadcastChatToWeb(devName: string, message: string, left: boolean): void {
    if (this.wsSessions.length === 0) {
      return;
    }
    const devType: number = 0;
    const json: string = `{"cmd":${WS_CMD_SEND_MESSAGE},` +
      `"isLeft":${left ? 'true' : 'false'},` +
      `"devName":${HttpRouter.jsonStr(devName)},` +
      `"devType":${devType},` +
      `"message":${HttpRouter.jsonStr(message)},` +
      `"messageType":0,` +
      `"filePath":"","fileSize":""}`;
    for (let i = 0; i < this.wsSessions.length; i++) {
      this.wsSessions[i].sendText(json);
    }
  }

  /**
   * 确保 `LanConfig.messageKey` 是**真正**的消息密钥。
   *
   * Android 的 `Config.initPrefs()` 拿 DEFAULT_MESSAGE_KEY 又解了一层才用，
   * 这里在启动时复算一次做自愈：万一 DEFAULT_MESSAGE_KEY 被换掉，
   * 只要 KEY 还对，就不用改代码。算不出来时保留内置常量（见 LanConfig 注释）。
   */
  private ensureMessageKey(): void {
    try {
      const derived: string = AesCodec.decrypt(LanConfig.DEFAULT_MESSAGE_KEY, LanConfig.KEY);
      if (derived.length > 0) {
        LanConfig.messageKey = derived;
        Log.i(TAG, `消息密钥已就绪（${derived.length} 字节）`);
      }
    } catch (e) {
      const err: Error = e as Error;
      Log.w(TAG, `消息密钥派生失败，沿用内置值：${err.message}`);
    }
  }

  /** 上次广播设备列表的时间戳，用于去抖 */
  private lastBroadcastMs: number = 0;

  /**
   * 设备上下线后，把最新列表推给所有网页客户端。
   *
   * ⚠️ 必须去抖：UDP 周期扫描每 5 秒会把同一批设备**逐个**回调一遍，
   * 不去抖的话真机实测 6 秒能推出 10 帧内容完全相同的设备列表
   * （`tests/live-probe/ws_upgrade_probe.mjs` 的输出可以直接看到），
   * 纯属浪费带宽和电量。
   */
  private broadcastDeviceList(): void {
    if (this.wsSessions.length === 0) {
      return;
    }
    const now: number = Date.now();
    if (now - this.lastBroadcastMs < 1000) {
      return;
    }
    this.lastBroadcastMs = now;
    for (let i = 0; i < this.wsSessions.length; i++) {
      this.wsSessions[i].pushDeviceList();
    }
  }

  /** 关闭全部网页 WebSocket 会话（停服 / 重启时用） */
  private closeAllWsSessions(): void {
    const all: WebSocketSession[] = this.wsSessions;
    this.wsSessions = [];
    this.snapshot.wsClients = 0;
    for (let i = 0; i < all.length; i++) {
      all[i].close();
    }
  }

  /**
   * 接收文件的落盘根目录。
   * 「另存为」从这里取源文件 —— 手机形态下它就是应用沙箱
   * （下载目录能力仅 PC/2in1/平板提供，见 docs/迁移对照表.md 第十三节）。
   */
  get receiveRoot(): string {
    return this.storage.saveRoot;
  }

  /** 当前聊天记录（最近 MAX_CHAT 条，按时间正序） */
  get chatList(): ChatMessage[] {
    return this.chatRing;
  }

  /**
   * 清空聊天记录（内存 + 本地持久化一起清）。
   *
   * ⚠️ 持久化必须跟着清：历史记录现在会落盘（见 restoreChat），
   *    只清内存的话用户看着列表空了、下次启动历史记录又全回来。
   */
  clearChat(): void {
    this.chatRing = [];
    this.emit();
    this.saveChatAsync().catch((e: Error) => {
      Log.w(TAG, `清空聊天记录落盘异常: ${e.message}`);
    });
  }

  /**
   * 删除指定 id 的聊天记录（内存 + 本地持久化一起删）。
   *
   * 与 clearChat 同理：只改内存不落盘，删完下次启动还会回来。
   */
  deleteChatMessages(ids: string[]): void {
    if (ids.length === 0) {
      return;
    }
    const drop: Set<string> = new Set<string>(ids);
    const kept: ChatMessage[] = [];
    for (let i = 0; i < this.chatRing.length; i++) {
      if (!drop.has(this.chatRing[i].id)) {
        kept.push(this.chatRing[i]);
      }
    }
    if (kept.length === this.chatRing.length) {
      return;
    }
    this.chatRing = kept;
    this.dropAlbumIndex(ids);
    this.emit();
    this.saveChatAsync().catch((e: Error) => {
      Log.w(TAG, `删除聊天记录落盘异常: ${e.message}`);
    });
  }

  // ------------------------------------------------------------------
  // 聊天记录持久化
  // ------------------------------------------------------------------

  /**
   * 从本地恢复聊天记录（**幂等**，只会真正加载一次）。
   *
   * 由 UI 在 `aboutToAppear` 里调用 —— 这样用户**不必先点「开始共享」**
   * 也能看到历史消息。原来聊天记录只活在 `chatRing` 这个内存数组里，
   * 退出应用即丢（vivi 2026-10-01：「消息页历史记录能不能保存？
   * 现在每次退出 app 就清空了」）。
   *
   * 位置用应用私有目录 `${filesDir}/chat_history.json`：
   *   - 一定可写（不像「下载」目录要用户授权）；
   *   - 卸载应用随之清除，不会在用户看不见的地方留数据。
   * 解析复用工程自带的 MiniJson（与 WebClientStore 同一套），坏数据一律
   * **退化为空表**，绝不让一条坏记录把消息页卡死。
   */
  async restoreChat(ctx: common.UIAbilityContext): Promise<void> {
    if (this.chatRestored) {
      return;
    }
    this.chatRestored = true;
    this.chatFile = `${ctx.filesDir}/chat_history.json`;
    let text: string = '';
    try {
      if (!fileIo.accessSync(this.chatFile)) {
        return;
      }
      const st: fileIo.Stat = fileIo.statSync(this.chatFile);
      // 体积异常（空 / 大到不合理）当作没有：不让坏文件拖住启动
      if (st.size <= 0 || st.size > CHAT_FILE_MAX_BYTES) {
        Log.w(TAG, `聊天记录文件体积异常（${st.size} 字节），忽略`);
        return;
      }
      text = fileIo.readTextSync(this.chatFile, { encoding: 'utf-8' });
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `读取聊天记录失败: ${err.code} ${err.message}`);
      return;
    }
    if (text.length === 0) {
      return;
    }
    const list: ChatMessage[] = LanService.deserializeChat(text);
    if (list.length === 0) {
      return;
    }
    this.chatRing = list;
    this.chatSeq = list.length;
    Log.i(TAG, `已恢复 ${list.length} 条聊天记录`);
    // 立刻推给 UI，否则要等下一次 emit 才显示
    this.emit();
  }

  /**
   * 防抖落盘：短时间内连来多条只写一次。
   *
   * ⚠️ `chatFile` 为空说明还没恢复过（用户从没进过 UI 的加载路径），
   *    这时不写 —— 否则会在错误的目录下建文件。
   */
  private scheduleChatSave(): void {
    if (this.chatFile.length === 0 || this.chatSaveTimer !== -1) {
      return;
    }
    this.chatSaveTimer = setTimeout(() => {
      this.chatSaveTimer = -1;
      this.saveChatAsync().catch((e: Error) => {
        Log.w(TAG, `聊天记录落盘异常: ${e.message}`);
      });
    }, CHAT_SAVE_DEBOUNCE_MS);
  }

  /** 立即把当前聊天记录写成 JSON 文件（失败只记日志，不影响聊天本身） */
  private async saveChatAsync(): Promise<void> {
    if (this.chatFile.length === 0) {
      return;
    }
    const json: string = LanService.serializeChat(this.chatRing);
    let f: fileIo.File | null = null;
    try {
      f = await fileIo.open(this.chatFile,
        fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
      const n: number = await fileIo.write(f.fd, json);
      Log.i(TAG, `聊天记录已落盘（${n} 字节 / ${this.chatRing.length} 条）`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `保存聊天记录失败: ${err.code} ${err.message}`);
    } finally {
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (x) {
          // 已关闭，忽略
        }
      }
    }
  }

  /** 手写序列化（与 WebClientStore 同一套思路，避开 JSON.stringify 的类型陷阱） */
  private static serializeChat(list: ChatMessage[]): string {
    const parts: string[] = [];
    for (let i = 0; i < list.length; i++) {
      const m: ChatMessage = list[i];
      parts.push(`{"id":${MiniJson.quote(m.id)},` +
        `"incoming":${m.incoming ? 'true' : 'false'},` +
        `"peerName":${MiniJson.quote(m.peerName)},` +
        `"peerIp":${MiniJson.quote(m.peerIp)},` +
        `"content":${MiniJson.quote(m.content)},` +
        `"timeMs":${m.timeMs},` +
        `"source":${MiniJson.quote(m.source)},` +
        `"delivered":${m.delivered ? 'true' : 'false'},` +
        `"kind":${MiniJson.quote(m.kind)},` +
        `"files":${MiniJson.quote(m.files)},` +
        // ★ 5.0.55：批号也要落盘 —— 否则重启后同一批的多条消息散成 N 个气泡
        //  （与 5.0.43「Map 落盘必须把 key 一起写」是同一类失配）
        `"batchId":${MiniJson.quote(m.batchId)},` +
        // ★ 5.1.49：meta 也要落盘 —— 否则**重启后**历史消息的大小/速度全丢
        //   （与 5.0.55「batchId 也要落盘」是同一类失配）
        `"meta":${MiniJson.quote(m.meta)}}`);
    }
    return `[${parts.join(',')}]`;
  }

  /** 解析失败一律退化为空表 */
  private static deserializeChat(raw: string): ChatMessage[] {
    const out: ChatMessage[] = [];
    const parsed: JsonParseResult = MiniJson.parse(raw);
    if (!parsed.ok || !parsed.root.isArray()) {
      Log.w(TAG, '聊天记录内容无法解析，按空表处理');
      return out;
    }
    const root: JsonNode = parsed.root;
    for (let i = 0; i < root.count; i++) {
      const n: JsonNode | null = root.at(i);
      if (n === null || !n.isObject()) {
        continue;
      }
      const m: ChatMessage = new ChatMessage();
      m.id = LanService.chatStr(n, 'id');
      m.incoming = LanService.chatBool(n, 'incoming');
      m.peerName = LanService.chatStr(n, 'peerName');
      m.peerIp = LanService.chatStr(n, 'peerIp');
      m.content = LanService.chatStr(n, 'content');
      m.timeMs = LanService.chatNum(n, 'timeMs');
      m.source = LanService.chatStr(n, 'source');
      m.delivered = LanService.chatBool(n, 'delivered');
      m.kind = LanService.chatStr(n, 'kind');
      m.files = LanService.chatStr(n, 'files');
      // ★ 5.0.55：旧数据没有这个字段 → 取到空串 → 各自成一个气泡（与改动前一致）
      m.batchId = LanService.chatStr(n, 'batchId');
      // ★ 5.1.49：旧数据没有 meta 字段 → 取到空串 → 不显示（与改动前一致）
      m.meta = LanService.chatStr(n, 'meta');
      if (m.id.length === 0) {
        m.id = `r${i}-${m.timeMs}`;
      }
      // 没有正文的条目（比如被截断的尾巴）直接丢弃，别在界面上留空气泡
      if (m.content.length > 0) {
        out.push(m);
      }
    }
    return out;
  }

  /** JsonNode.field() 返回可空，这里统一收口，避免每处都判空 */
  private static chatStr(n: JsonNode, key: string): string {
    const f: JsonNode | null = n.field(key);
    return f === null ? '' : f.asString('');
  }

  private static chatNum(n: JsonNode, key: string): number {
    const f: JsonNode | null = n.field(key);
    return f === null ? 0 : f.asNumber(0);
  }

  private static chatBool(n: JsonNode, key: string): boolean {
    const f: JsonNode | null = n.field(key);
    return f !== null && f.asString('false') === 'true';
  }

  // ------------------------------------------------------------------
  // 设备下线巡检
  // ------------------------------------------------------------------

  /**
   * 启动 1s 一次的设备巡检。
   *
   * 「设备离线」是靠「`DEVICE_OFFLINE_MS` 内没再收到心跳」判定的，而那一刻
   * **没有任何事件发生** —— 没有事件就不会 emit，UI 自然不刷新。
   * 原来只能等下一次别人发包（可能几十秒后）顺带刷新，用户看到的就是
   * 「对方设备都关了，列表里还挂着十几秒」（vivi 2026-10-01 反馈）。
   */
  private startDeviceSweep(): void {
    if (this.sweepTimer !== -1) {
      return;
    }
    this.sweepTimer = setInterval(() => {
      this.sweepDevices();
    }, DEVICE_SWEEP_MS);
  }

  private stopDeviceSweep(): void {
    if (this.sweepTimer !== -1) {
      clearInterval(this.sweepTimer);
      this.sweepTimer = -1;
    }
  }

  /**
   * 巡检一次。
   *
   * 两件事，顺序不能反：
   *   1. **先对安静下来的设备发单播探活**（活着的会立刻回包、刷新在线时间）；
   *   2. 再算「在线设备集合签名」，**只有真的变了**才广播 + 刷新 UI
   *      （每秒无脑 emit 会让整页每秒重渲染一次，纯属浪费电）。
   */
  private sweepDevices(): void {
    const now: number = Date.now();
    // ---- ① 逐台设备：先探活（可能就地判死），最后才谈 UI ----
    // ⚠️ 必须用 forEach 的第二个参数 key（uuid 或 IP）来 dropDevice ——
    //    devices 是按 key 索引的，拿 d.devIp 去删会漏删（uuid 与 IP 不是一回事）。
    this.devices.forEach((d: LanDevice, key: string) => {
      const ip: string = d.devIp;
      if (ip.length === 0) {
        return;
      }
      // 「基础超时」兜底：太久没有任何消息了（UDP 心跳、TCP 传输都不算数）
      if (this.deviceGone(d, now)) {
        this.dropDevice(key, d);
        return;
      }
      // 还在正常心跳节奏里 → 清掉 TCP 复核的失败计数（它只是"安静得不够久"）
      if (now - d.lastSeenMs < LanConfig.DEVICE_PROBE_QUIET_MS) {
        this.tcpProbeMiss.delete(ip);
        return;
      }
      // 安静够久了，两件事：
      // (a) UDP 单播探活 —— 便宜，让「愿意应答」的设备顺手刷新在线时间。
      //     同一台设备两次之间留 RETRY，免得每轮巡检（1s）都重复发。
      if (now - (this.probeSentAt.get(ip) ?? 0) >= LanConfig.DEVICE_PROBE_RETRY_MS) {
        this.sendLivenessProbe(ip, now);
      }
      // (b) TCP 复核 —— 确定性的存活凭据，也是「快速判死」的实际执行者。
      this.tcpProbeStep(key, d, now);
    });

    // ---- ② 只有「在线集合」真的变了才广播 + 刷新 UI ----
    // 每秒无脑 emit 会让整页每秒重渲染一次，纯属浪费电。
    let sig: string = '';
    this.devices.forEach((d: LanDevice) => {
      if (!this.deviceGone(d, now)) {
        sig += `${d.uniqueUuid};`;
      }
    });
    if (sig === this.lastSweepSig) {
      return;
    }
    this.lastSweepSig = sig;
    this.broadcastDeviceList();
    this.syncStats();
    this.emit();
  }

  /**
   * 一次 TCP 复核（存活凭据）。设计依据见 LanConfig.DEVICE_TCP_PROBE_* 一组长注释。
   *
   * 两条路径：
   *   · **验证路径**（该设备还没成功过）：只想弄清"它到底会不会应答 TCP"，
   *     失败**不判死** —— 见 `DEVICE_TCP_VERIFY_MAX_MISS` 安全阀。
   *   · **判死路径**（曾经成功过）：连续失败 `DEVICE_TCP_PROBE_MISS_LIMIT` 次即判死。
   */
  private tcpProbeStep(key: string, d: LanDevice, now: number): void {
    const ip: string = d.devIp;
    if (this.tcpProbeBusy.get(ip) === true) {
      return;   // 上一次复核还在路上
    }
    if (now - (this.lastTcpProbeAt.get(ip) ?? 0) < LanConfig.DEVICE_TCP_PROBE_COOLDOWN_MS) {
      return;
    }
    const verified: boolean = this.tcpEverOk.get(ip) === true;
    const miss: number = this.tcpProbeMiss.get(ip) ?? 0;
    if (!verified && miss >= LanConfig.DEVICE_TCP_VERIFY_MAX_MISS) {
      return;   // 验证不通且已试够次数：不再反复 connect，交给 8s 兜底
    }
    if (verified && miss >= LanConfig.DEVICE_TCP_PROBE_MISS_LIMIT) {
      return;   // 判决已在上一次回调里落地
    }
    const port: number = d.devPort > 0 ? d.devPort : LanConfig.DEFAULT_FILE_SERVER_PORT;
    this.tcpProbeBusy.set(ip, true);
    this.lastTcpProbeAt.set(ip, now);
    LanService.tcpPing(ip, port).then((alive: boolean) => {
      this.tcpProbeBusy.set(ip, false);
      if (alive) {
        this.tcpEverOk.set(ip, true);
        this.tcpProbeMiss.delete(ip);
        // 视为「刚刚确认在线」：重置安静计时，下一轮巡检不会立刻再复核
        d.lastSeenMs = Date.now();
        return;
      }
      const next: number = (this.tcpProbeMiss.get(ip) ?? 0) + 1;
      this.tcpProbeMiss.set(ip, next);
      // 只有「曾成功过」的设备才允许用失败判死（安全阀，见 DEVICE_TCP_VERIFY_MAX_MISS）
      if (this.tcpEverOk.get(ip) !== true || next < LanConfig.DEVICE_TCP_PROBE_MISS_LIMIT) {
        return;
      }
      Log.i(TAG, `TCP 复核失败 ${next}/${LanConfig.DEVICE_TCP_PROBE_MISS_LIMIT}，判定下线 ${d.devName} @ ${ip}:${port}`);
      this.dropDevice(key, d);
    }).catch((e: Error) => {
      this.tcpProbeBusy.set(ip, false);
      Log.w(TAG, `TCP 复核异常 ${ip}: ${e.message}`);
    });
  }

  /**
   * 一次 TCP 连接探活：**只建连、不发任何字节**，然后立刻关闭。
   *
   * 不发魔数是有意的 —— 见 LanConfig 那段注释：发了会被对端的协议分流
   * 引到私有协议分支上，等于凭空给对方造一条"半截握手"。
   * 什么都不发，对端读到 EOF 就会把这条连接正常收尾。
   */
  private static async tcpPing(ip: string, port: number): Promise<boolean> {
    let s: socket.TCPSocket | null = null;
    try {
      s = socket.constructTCPSocketInstance();
      await s.connect({
        address: { address: ip, port: port, family: 1 },
        timeout: LanConfig.DEVICE_TCP_PROBE_TIMEOUT_MS
      });
      LanService.closeQuietly(s);
      return true;
    } catch (e) {
      LanService.closeQuietly(s);
      return false;
    }
  }

  /** 关掉探活套接字；失败一律吞掉（那次连接可能压根没建立起来） */
  private static closeQuietly(s: socket.TCPSocket | null): void {
    if (s === null) {
      return;
    }
    s.close().catch((e: Error) => {
      Log.w(TAG, `关闭探活套接字失败: ${e.message}`);
    });
  }

  /** 当前在线设备快照 */
  onlineDeviceList(): LanDevice[] {
    const now: number = Date.now();
    const out: LanDevice[] = [];
    // ★ 同一 IP 只出一个（5.0.21 兜底护栏）：即使 devices 里因故残留了多条同 IP 记录，
    //   群发消息 / 网页下拉框也只会各投一份 —— 这是「同一条消息收到两次」的直接护栏。
    //   保留 `lastSeenMs` 最新的那条（有心跳、能连上的才是它）。
    //   空 IP 不参与合并（本来就不可用，但也不该被悄悄丢掉）。
    const slot: Map<string, number> = new Map<string, number>();
    this.devices.forEach((d: LanDevice) => {
      if (this.deviceGone(d, now)) {
        return;
      }
      if (d.devIp.length === 0) {
        out.push(d);
        return;
      }
      const at: number | undefined = slot.get(d.devIp);
      if (at === undefined) {
        slot.set(d.devIp, out.length);
        out.push(d);
      } else if (d.lastSeenMs > out[at].lastSeenMs) {
        out[at] = d;
      }
    });
    return out;
  }

  // ------------------------------------------------------------------
  // ChannelHandler：TCP 连接处理
  // ------------------------------------------------------------------

  /**
   * 处理一条已完成分流的 TCP 连接。
   *
   * ⚠️ **必须 await 内部的所有异步工作，并且返回 Promise。**
   * 上层（`LanTcpServer.dispatch`）是「处理返回 -> 关闭通道」的顺序，
   * 一旦这里提前返回，连接会**在业务还没开始读数据的时候就被关掉**，
   * 表现为「对端连上了但永远没有响应」。
   */
  async handle(channel: TcpChannel, kind: number, head: Uint8Array): Promise<void> {
    try {
      if (kind === ProtocolKind.WEB) {
        await this.router.serve(channel, head);
        return;
      }
      // 私有二进制协议
      await this.handlePrivateProtocol(channel);
    } catch (e) {
      const err: Error = e as Error;
      Log.w(TAG, `连接处理异常: ${err.message}`);
      channel.close();
    }
  }

  /**
   * 私有协议处理。
   *
   * 请求格式：[MAGIC 4B 已被读走] + DataEnc 包（12B 头 + payload，全段混淆）
   * 响应格式：DataEnc 包（**不带** MAGIC）
   *
   * ⚠️ 目前只完整实现了握手类命令。文件传输相关命令（FS_SHARE_FILE 等）
   * 的字段布局需要从 LANService.java 的 fsShareFile()/fsGetFileList() 继续提取，
   * 清单见 docs/迁移对照表.md 的「B1 剩余工作」。这里显式返回未实现，
   * 而不是猜一个布局 —— 猜错会静默丢文件，比明确报错危险得多。
   */
  private async handlePrivateProtocol(channel: TcpChannel): Promise<void> {
    // ---- 0. 先看 4 字节，分流「协议代次」----
    // LanShare 在魔数之后有**两套完全不同**的编码：
    //   v4   ：裸 int NEW_VERSION_4(-2) 打头，无 DataEnc 头、无 0x45 混淆
    //   老版本：一个 DataEnc 包（12B 头 + body，全段混淆）
    // 两者第一个字段就能区分，所以先读 4 字节判断，不是 v4 再放回去走老路。
    //   这一步当初漏了，导致 Android 端发文件过来被当成"未知协议流量"直接断开。
    const first4: Uint8Array | null = await channel.readExactly(4, 30000);
    if (first4 === null) {
      this.pushLog('私有协议：等待首个 4 字节超时或连接已断开');
      this.emit();
      return;
    }
    if (ProtoIO.beInt(first4) === LCmd.NEW_VERSION_4) {
      this.pushLog('协议代次：v4（裸序列化，无混淆）');
      this.emit();
      await this.handleV4(channel);
      return;
    }
    // ★ v5（局域网互传 1.35 修改版）协议：MAGIC 之后的首个 4 字节即帧命令字
    //   （1101 发文件 / 1105 文本消息）。注意：dispatch 已经把 MAGIC 这 4 字节读走，
    //   这里读到的 first4 就是 v5 帧头的命令字，与 1.35 的 Lq2/c->g/a 顺序一致。
    const firstCmd: number = ProtoIO.beInt(first4);
    // ★ 1110（FS_SEG_FILE）是 1.35 修改版「16 分片并行发文件」的入口，
    //   与 1101 是两条独立的发文件路径：图片走 1101，文件走 1110。
    //   早期只放行 1101/1105，导致 1.35 发文件时 16 条连接全被判成未知协议拒绝。
    if (firstCmd === LCmd.FS_SHARE_FILE || firstCmd === LCmd.FS_MESSAGE
      || firstCmd === LCmd.FS_SEG_FILE) {
      this.pushLog('协议代次：v5（1.35 二进制帧）');
      this.emit();
      await this.handleV5(channel, first4);
      return;
    }
    // 诊断：非 v4/v5 的首命令字也记进 hilog（排查「私有协议包长度异常」洪水来自哪种连接）
    {
      let h4: string = '';
      for (let i = 0; i < 4; i++) {
        const b: number = first4[i] & 0xFF;
        h4 += (b < 16 ? '0' : '') + b.toString(16);
      }
      Log.i(TAG, `私有协议：非 v4/v5，first4=${ProtoIO.beInt(first4)} hex=${h4}`);
    }
    this.pushLog(`协议代次：旧版（DataEnc 包头，首 4 字节 ${ProtoIO.beInt(first4)}）`);
    this.emit();
    channel.unshift(first4);

    const header: Uint8Array | null = await channel.readExactly(12, 30000);
    if (header === null) {
      return;
    }
    // 还需要 body，但 body 长度藏在（未解混淆的）头部里。
    // 与 Java 端 DataDec.decHeader() 的顺序一致：先解头，再读长度。
    const tentHeader: DataDec = DataDec.raw(header);
    tentHeader.decodeHeader();
    const bodyLen: number = tentHeader.getLength();
    if (bodyLen < 0 || bodyLen > 8 * 1024 * 1024) {
      Log.w(TAG, `私有协议包长度异常: ${bodyLen}`);
      return;
    }
    const body: Uint8Array | null = bodyLen > 0
      ? await channel.readExactly(bodyLen, 60000)
      : new Uint8Array(0);
    if (body === null) {
      return;
    }

    const whole: Uint8Array = new Uint8Array(12 + body.length);
    whole.set(header, 0);
    whole.set(body, 12);
    const dec: DataDec = DataDec.raw(whole);
    dec.decodeAll();

    const cmd: number = dec.getCmd();
    Log.d(TAG, `收到私有协议命令: ${cmd}`);

    switch (cmd) {
      case LCmd.FS_ADD_DEVICE:
        // 添加设备握手：请求体末尾带一个 isIPv6 布尔（见 LANService 320 行附近）
        await this.onAddDevice(dec, channel);
        break;
      case LCmd.FS_MESSAGE:
        await this.onTextMessage(dec, channel);
        break;
      case LCmd.FS_GET_APPS:
      case LCmd.FS_UPDATE_APPS:
      case LCmd.FS_GET_NO_SYNC_MEDIA:
      case LCmd.FS_SYNC_MEDIA:
        this.pushLog(`命令 ${cmd} 尚未迁移到鸿蒙端（B1 剩余工作），已拒绝`);
        await channel.send(LanService.errorPacket(cmd, 'not implemented on HarmonyOS yet'));
        break;
      default:
        this.pushLog(`未知命令 ${cmd}，忽略`);
        await channel.send(LanService.errorPacket(cmd, `unknown cmd ${cmd}`));
    }
  }

  /**
   * v5 协议处理入口。
   *
   * 调用前提：`handlePrivateProtocol` 已经读走了第一帧的命令字 4 字节（first4）。
   * 这里接着读「参数 4 + 长度 4 + payload(len)」把整帧拼回，再按命令字分发 ——
   * 对应 1.35 的 `Lq2/k->M2`（先写 12 字节头、再写 payload）。
   *
   * ⚠️ 帧头与 payload 必须一次性读完再分命令字处理：V5Transfer.receive 之后要
   * 从**同一个** channel 接着读文件清单帧，不能让半截头留在这里。
   */
  private async handleV5(channel: TcpChannel, first4: Uint8Array): Promise<void> {
    const tail: Uint8Array | null = await channel.readExactly(8, 30000);
    if (tail === null) {
      this.pushLog('v5：读取帧头（arg/len）超时或连接已断开');
      this.emit();
      return;
    }
    const header: Uint8Array = new Uint8Array(12);
    header.set(first4, 0);
    header.set(tail, 4);
    const cmd: number = V5Dec.beInt(header, 0);
    const arg: number = V5Dec.beInt(header, 4);
    const len: number = V5Dec.beInt(header, 8);
    if (len < 0 || len > 8 * 1024 * 1024) {
      this.pushLog(`v5：第一帧 payload 长度异常 ${len}`);
      this.emit();
      return;
    }
    const payload: Uint8Array | null = len > 0
      ? await channel.readExactly(len, 60000)
      : new Uint8Array(0);
    if (payload === null) {
      this.pushLog('v5：读取第一帧 payload 超时');
      this.emit();
      return;
    }
    // 诊断：把首帧 payload 前 48 字节打成 hex，便于核对设备头/encData 相对位置
    // （正常 1101：前 4 字节是 devPort，如 0x00001505=5381；最后 1 字节是 encData 0/1）
    const dumpN: number = Math.min(48, payload.length);
    let dumpHex: string = '';
    for (let i = 0; i < dumpN; i++) {
      const b: number = payload[i] & 0xFF;
      dumpHex += (b < 16 ? '0' : '') + b.toString(16);
    }
    Log.i(TAG, `v5 首帧 cmd=${cmd} arg=${arg} len=${len} hex=${dumpHex}`);
    switch (cmd) {
      case LCmd.FS_SHARE_FILE:
        await this.handleV5Share(channel, payload, arg);
        break;
      case LCmd.FS_MESSAGE:
        await this.handleV5Message(payload);
        break;
      case LCmd.FS_SEG_FILE:
        await this.handleV5Segment(channel, payload);
        break;
      default:
        this.pushLog(`v5：未知命令 ${cmd}，忽略`);
    }
    this.emit();
  }

  /**
   * v5 接收文件：第一帧 payload = 设备头 + encData 字节。
   * 解析出对端设备后交给 V5Transfer.receive 收清单与数据流（它自己回 FS_AGREE）。
   * 与 v4 的 onTransferReport 是同一套：成功会插一条「文件」消息到消息页。
   */
  private async handleV5Share(channel: TcpChannel, payload: Uint8Array, count: number): Promise<void> {
    const dec: V5Dec = new V5Dec(payload, 0, payload.length);
    // ⚠️ **顺序由 smali 二次取证钉死：payload = [设备头][encData 字节]，设备头在「前」**。
    //   发送端：`LANService.g()` 先 `r(Device,int)`（16820，写设备头）再 `b(encData)`（5063）。
    //   接收端：`LANService` 14973-14978 先 `e(4)` 读 arg，设备头解析器吃掉设备头后
    //           `c()` 才读到 encData。
    // 若反过来先 `byte()` 读 encData，devPort 首字节被当 encData 吞掉，
    // 整段设备头错位 1 字节（真机日志复现：`V5Codec: 字符串长度越界: 3633 > 78`）。
    const peer: LanDevice | null = V5Header.read(dec);
    if (peer === null) {
      this.pushLog('v5：设备头解析失败，已拒绝');
      await channel.send(V5Transfer.simpleFrame(LCmd.FS_NOT_AGREE));
      return;
    }
    // ★ 5.0.58：在**覆盖之前**记下对端「自己宣告」的地址与型号 —— 这是识别 PC 端的指纹。
    //   PC 端 `sendFile()` 里的 `makeDataEnc(*p1, …)` 填的是**目标设备**的信息
    //   （LANShare.cpp:474），所以它宣告的 IP **就是我方自己的 IP**；
    //   而真 1.35 Android 宣告的是它自己的 IP。两者判然可辨。
    //   ⚠️ 再加一道 devMode 不是 ANDROID 的校验：**判错只会退回默认行为（N+2），
    //      不会把 1.35 那条路径弄坏** —— 这是本判据能安全上线的唯一理由。
    const announcedIp: string = peer.devIp;
    const announcedMode: number = peer.devMode;
    if (channel.remoteIp.length > 0) {
      peer.devIp = channel.remoteIp;
    }
    this.pushLog(`v5 对端宣告：name=${peer.devName} ip=${announcedIp}`
      + ` mode=${announcedMode} uuid=${peer.uniqueUuid} ver=${peer.dataVersion}`);
    // ★ 5.0.60：判据改「**用握手 UUID 反查发现表**」—— 5.0.58 那条判据（宣告 IP == 本机 IP）
    //   在真机上**从未命中**：实测 PC 宣告的是它**自己**（`.186`），本机是 `.146`。
    //   根因在 PC 源码（`LANShare.cpp:467-474`）：`makeDataEnc(*p1, …)` 里的 `p1` 是
    //   PC **自己设备列表里「与目标同子网的某一台」** —— 可能是它自己、也可能是别的设备。
    //   ⇒ 同帧里的 `devIp / devName / devMode` **三个字段天生不可靠**。
    //   ★ 唯一可靠的是 `uniqueUuid`：取自 `config.uniqueUUid`（`LANShare.cpp:117`），
    //     是**对端自己的 UUID**，与 `p1` 无关；而本机发现表的 key 正好就是它
    //     （`devices: Map<string, LanDevice>`，见 `trackPeer`）⇒ 反查得到**真实** devMode。
    //   ⚠️ 兜底刻意保守：**查不到就按「非 PC」**（退回 N+2）—— 与现状一致，不引入回归。
    let peerMode: number = DeviceMode.UNKNOWN;
    let modeFrom: string = '未命中';
    if (peer.uniqueUuid.length > 0) {
      const known: LanDevice | undefined = this.devices.get(peer.uniqueUuid);
      if (known !== undefined) {
        peerMode = known.devMode;
        modeFrom = '发现表(uuid)';
      }
    }
    if (peerMode === DeviceMode.UNKNOWN && channel.remoteIp.length > 0) {
      // 第二道：按 TCP 对端 IP 反查（发现表里有同 IP 的那台）。同样只信发现表。
      const byIp: LanDevice[] = [];
      this.devices.forEach((d: LanDevice) => {
        if (d.devIp === channel.remoteIp) {
          byIp.push(d);
        }
      });
      if (byIp.length > 0) {
        peerMode = byIp[0].devMode;
        modeFrom = '发现表(ip)';
      }
    }
    const pcStyleAck: boolean = peerMode === DeviceMode.WINDOWS || peerMode === DeviceMode.LINUX
      || peerMode === DeviceMode.MAC_OS || peerMode === DeviceMode.WEB;
    this.pushLog(`v5 ack 分流：对端 mode=${peerMode}（${modeFrom}）⇒ 文件收尾回 `
      + `${pcStyleAck ? 'N+1（PC 端只读 N+1）' : 'N+2（Android/1.35 需要 5+2）'}`);
    // 设备头（含已知设备表）之后**紧邻**的 1 字节就是 encData（1.35 的 `b(byte)` 写在设备头末尾）
    const encData: number = dec.byte();
    this.trackPeer(peer);
    // 记下对端 IP：传输成功后 onTransferReport 要往消息页插文件记录
    this.transferPeerIp = peer.devIp;
    this.pushLog(`v5 收到来自 ${peer.devName} 的发送请求（${count} 项）`);
    // ★★ 5.1.69 B：接收逐项日志**节流**（一处包装，V5Transfer 侧零改动）。
    //
    // 【为什么】vivi 2026-10-05 真机 426 张：接收阶段打出 **1708 条** v5 日志
    //   （426 项 × 4 类：清单/开始收/已收满/收尾 + 4 条其他）。
    //   `onLog` 原本直接接 `this.pushLog`，而 `pushLog` ⇒ **emit**
    //   ⇒ `onSnapshot` ⇒ `refreshReceived`
    //   （**全量扫盘** + rebuildRecvIndex + syncChatMediaPaths + buildChatGroups）
    //   ⇒ **1708 次 O(n) 重建**，且文件列表正从 0 长到 426（每次成本都在涨）
    //   ⇒ 这才是「批量接收时界面卡」的真凶。
    //   ★ 与「收尾那 1 秒」是两件事：收尾已优化到位，但整个接收过程被拖累。
    //
    // 【怎么节流】带进度下标的三类（`清单[i/n]` / `开始收第 i/n 项` / `收尾已回`）
    //   在 `n > V5_BULK_LOG_PLAIN(20)` 时只放行 **首项 / 每 V5_BULK_LOG_STEP(25) 项 / 末项**，
    //   其余**转发到 hilog（Log.d）**，不进 UI、不 emit ⇒ 信息不丢，只是不刷屏。
    //   `已收满 N B` 不带下标、无法按进度过滤 ⇒ 保留（它本就每项只打一次）。
    //
    // ⚠️ 只节流**日志落地**，不碰协议 / 流控 / 让帧任何时序
    //   （与 5.1.29~5.1.32 证伪的那类「帧判据」无关）。
    const bulkN: number = count;
    const bulkPlain: number = 20;
    const bulkStep: number = 25;
    await V5Transfer.receive(channel, peer, count, encData !== 0, this.storage,
      (r: TransferReport) => this.onTransferReport(r),
      // 5.0.47：接收链关键事件接到 UI 日志 —— hilog 抓不到时（无线调试 Unauthorized）
      // 也能靠这行定位「多项发送卡死」卡在哪一步
      (s: string) => {
        if (bulkN > bulkPlain && LanService.isPerItemV5Log(s)) {
          // 从日志文本里取出进度下标 i（形如 `[i/n]` 或 `第 i/n 项`）
          const i: number = LanService.progressIndexOf(s);
          if (i > 0 && i !== 1 && i !== bulkN && (i % bulkStep) !== 0) {
            Log.d(TAG, s);      // 只进 hilog
            return;
          }
        }
        this.pushLog(s);
      }, pcStyleAck);
  }

  /**
   * v5 分段文件（cmd=1110）：1.35 修改版把文件切成 **16 片**，每片一条独立 TCP 连接
   * 并发发送，因此这里会被**并发**调用 16 次。
   *
   * 首帧 payload 与 1101 **不同**：只有 **1 字节 encData**，**没有设备头**。
   * 后续（元数据帧 + 数据帧 + 按 start 随机写）都在 V5Transfer.receiveSegment 里完成，
   * 16 条连接靠 segId 认领同一个目标文件。
   */
  private async handleV5Segment(channel: TcpChannel, payload: Uint8Array): Promise<void> {
    // ⚠️ 1110 的帧1 payload 与 1101 **同构**：`[设备头][encData 字节]`。
    //   发送端 `E()`（LANService 3266）先调 `r(Device,int)`（16820，写整段设备头）
    //   再 `b(0)` 追加 encData；接收端 `q()`（15443-15446）在 1110 分支里
    //   第一件事就是 `c()` 读设备头**之后**那 1 字节，说明帧分发层已消费设备头。
    //   所以这里必须先读设备头，再读 encData —— 直接取 payload[0] 会拿到 devPort 首字节。
    // 兼容性：旧版（5.0.4/5.0.5）发的是「只有 1 字节 payload」，此时
    //   `V5Header.read` 会因 devIp 为空返回 null，`dec.byte()` 读回 0 → encData=false，
    //   与旧行为一致，不会因为升级而产生新的不互通。
    const dec: V5Dec = new V5Dec(payload, 0, payload.length);
    const peer: LanDevice | null = V5Header.read(dec);
    const encData: number = dec.byte() & 0xFF;
    const ip: string = channel.remoteIp;
    if (ip.length > 0) {
      this.transferPeerIp = ip;
    }
    let who: string = ip;
    if (peer !== null && peer.devName.length > 0) {
      who = peer.devName;
    } else {
      const found: LanDevice | undefined = this.findDeviceByIp(ip);
      if (found !== undefined && found.devName.length > 0) {
        who = found.devName;
      }
    }
    await V5Transfer.receiveSegment(channel, encData !== 0, this.storage, who,
      (r: TransferReport) => this.onTransferReport(r));
  }

  /**
   * v5 文本消息：payload = 设备头 + 密文消息（**没有** v4 的 isClip 布尔位）。
   * 对齐 1.35 的 case 1105 第一条就是 readString。
   */
  private async handleV5Message(payload: Uint8Array): Promise<void> {
    const dec: V5Dec = new V5Dec(payload, 0, payload.length);
    const peer: LanDevice | null = V5Header.read(dec);
    if (peer === null) {
      this.pushLog('v5：消息设备头解析失败');
      return;
    }
    // 设备头之后紧跟的就是消息密文串（设备头已吃掉已知设备计数位）
    const cipher: string = dec.string();
    if (cipher.length === 0) {
      return;
    }
    let text: string = cipher;
    try {
      text = AesCodec.decrypt(cipher, LanConfig.messageKey);
    } catch (e) {
      const err: Error = e as Error;
      this.pushLog(`v5 消息解密失败（来自 ${peer.devName}）：${err.message}`);
      return;
    }
    const who: string = peer.devName.length > 0 ? peer.devName : peer.devIp;
    const fromIp: string = peer.devIp.length > 0 ? peer.devIp : '';
    this.pushLog(`消息 <${who}>: ${text}`);
    // ① 本机聊天列表 ② 同步推给网页端（左侧气泡）
    this.appendChat(true, who, fromIp, text, 'device');
    this.broadcastChatToWeb(who, text, true);
    await this.store.insertMessage({
      msgId: `${Date.now()}-${Math.floor(Math.random() * 100000)}`,
      peerIp: fromIp,
      direction: 0,
      content: text,
      msgType: LCmd.FS_MESSAGE,
      length: text.length,
      createdAt: Date.now()
    });
  }

  /** FS_ADD_DEVICE：回一个带上 isIPv6 标志的确认包 */
  private async onAddDevice(dec: DataDec, channel: TcpChannel): Promise<void> {
    const enc: DataEnc = new DataEnc(16);
    enc.packData(LCmd.NEW_VERSION_4);
    // Android 侧 LANService 在应答里 putBool(isIPV6)
    enc.putBoolean(this.localNet.isIPv4 === false);
    enc.putString(this.self.devName);
    await channel.send(enc.encode());
    this.pushLog('已响应设备添加握手');
  }

  /**
   * FS_MESSAGE：收一条文本消息（v4 TCP 路径）。
   *
   * 载荷必须**逐字段**对齐 FileServer.handleMessage()：
   *   `boolean isClip = inputStream.readBoolean();`
   *   `String messageEnc = inputStream.readString();`
   *   `AESUtils.decrypt(messageEnc, Config.MESSAGE_KEY)`
   *
   * ⚠️ 早期版本这里读的是"from 名字 + 明文"两个字符串，跟发送端
   * （FileSend.sendMessage 写的是 isClip + 密文）完全错位：
   * 布尔被当成字符串读、密文被当明文显示。这条路径只在**长文本**（>700 字）时
   * 被安卓端使用，所以一直没被发现。
   */
  private async onTextMessage(dec: DataDec, channel: TcpChannel): Promise<void> {
    dec.readBoolean();
    const messageEnc: string = dec.readString() ?? '';
    let text: string = '';
    try {
      text = AesCodec.decrypt(messageEnc, LanConfig.messageKey);
    } catch (e) {
      const err: Error = e as Error;
      this.pushLog(`TCP 消息解密失败（来自 ${channel.remoteIp}）：${err.message}`);
      Log.w(TAG, `TCP 消息解密失败: ${err.message}`);
      // 解密失败也要回执：发送端在等 FS_DATA_RECEIVED，不回它会一直挂到超时
      const fail: DataEnc = new DataEnc(16);
      fail.packData(LCmd.FS_DATA_RECEIVED);
      await channel.send(fail.encode());
      this.emit();
      return;
    }
    const fromIp: string = channel.remoteIp;
    const peer: LanDevice | undefined = this.findDeviceByIp(fromIp);
    const who: string = (peer !== undefined && peer.devName.length > 0) ? peer.devName : fromIp;
    this.pushLog(`消息 <${who}>: ${text}`);
    this.appendChat(true, who, fromIp, text, 'device');
    this.broadcastChatToWeb(who, text, true);
    await this.store.insertMessage({
      msgId: `${Date.now()}-${Math.floor(Math.random() * 100000)}`,
      peerIp: fromIp.length > 0 ? fromIp : who,
      direction: 0,
      content: text,
      msgType: LCmd.FS_MESSAGE,
      length: text.length,
      createdAt: Date.now()
    });
    const enc: DataEnc = new DataEnc(16);
    enc.packData(LCmd.FS_DATA_RECEIVED);
    await channel.send(enc.encode());
    this.emit();
  }

  /** 按 IP 找已发现的设备（用于给消息补一个可读的发送方名字） */
  private findDeviceByIp(ip: string): LanDevice | undefined {
    let hit: LanDevice | undefined = undefined;
    this.devices.forEach((d: LanDevice) => {
      if (d.devIp === ip) {
        hit = d;
      }
    });
    return hit;
  }

  // ------------------------------------------------------------------
  // v4 协议（NEW_VERSION_4 起头）：文件传输 / 文本消息
  // ------------------------------------------------------------------

  /**
   * 处理 v4 连接。调用前提：NEW_VERSION_4 这 4 字节已被读走。
   *
   * 字节序列见 service/FileTransfer.ets 头部注释（已与
   * FileSend.send / FileServer.handleVersion1 逐行对齐）。
   */
  private async handleV4(channel: TcpChannel): Promise<void> {
    const devJson: string | null = await ProtoIO.readString(channel, 15000);
    if (devJson === null) {
      // 走到这里只有两种可能：4 字节长度前缀不合法（>8MB 或读不全），或者对端没发完就断了。
      // 必须留痕 —— 这条路径会直接关掉连接，客户端看到的是「对端未应答（连接中断）」，
      // 不给原因的话，两端都只能猜。
      this.pushLog('v4 建链失败：设备信息长度非法或连接中断，已断开');
      this.emit();
      return;
    }
    const peer: LanDevice | null = DeviceCodec.fromJson(devJson);
    if (peer === null) {
      const head: string = devJson.length > 200 ? `${devJson.substring(0, 200)}…` : devJson;
      this.pushLog(`v4 建链失败：设备 JSON 解析不出来（${devJson.length}B）${head}`);
      this.emit();
      return;
    }
    // remoteInfo 里的来源地址比包里的 devIP 更可信
    if (channel.remoteIp.length > 0) {
      peer.devIp = channel.remoteIp;
    }
    this.trackPeer(peer);
    this.pushLog(`v4 连接来自 ${peer.devName} (${peer.devIp})`);
    this.emit();

    const cmd: number | null = await ProtoIO.readInt(channel, 15000);
    if (cmd === null) {
      this.pushLog('v4 建链后等待命令超时，已断开');
      this.emit();
      return;
    }
    this.pushLog(`v4 命令码 ${cmd}`);
    this.emit();
    switch (cmd) {
      case LCmd.FS_SHARE_FILE:
        // 记下对端 IP：传输成功后要在消息页插一条文件记录，peerIp 只有这里拿得到
        this.transferPeerIp = peer.devIp;
        await FileTransfer.receive(channel, peer, this.storage,
          (r: TransferReport) => this.onTransferReport(r));
        break;
      case LCmd.FS_MESSAGE:
        await this.onMessageV4(channel, peer);
        break;
      case LCmd.FS_GET_NO_SYNC_MEDIA:
        // 媒体同步依赖 Android 的媒体库（AnyData.mediaResult），鸿蒙端没有对应能力
        this.pushLog('对端请求媒体同步，鸿蒙端未实现媒体库，已拒绝');
        await channel.send(ProtoIO.intBytes(LCmd.FS_NOT_AGREE));
        break;
      default:
        this.pushLog(`v4 未知命令 ${cmd}，忽略`);
    }
  }

  /**
   * v4 文本消息：`boolean isClip` + `string messageEnc`。
   * Android 发送端（FileSend.sendMessage）其实写的是明文，
   * 而接收端（FileServer.handleMessage）会做 AES 解密 —— 两边不一致。
   * 这里两种都接受：先按 AES 解，解不出来就当明文用，并把原文记进日志。
   */
  private async onMessageV4(channel: TcpChannel, from: LanDevice): Promise<void> {
    const isClipRaw: boolean | null = await ProtoIO.readBoolean(channel, 15000);
    const isClip: boolean = isClipRaw === true;
    const payload: string | null = await ProtoIO.readString(channel, 15000);
    if (payload === null) {
      return;
    }
    let text: string = payload;
    // 只有"看起来像 AES 密文"才试着解：必须是偶数长度的十六进制串、
    // 且长度是 16 字节块的整数倍（32 个 hex 字符起）。
    // 不加上这个判断的话，明文 "hello" 之类也会被塞进 hexToBytes 变成乱码。
    if (LanService.looksLikeCipherHex(payload)) {
      try {
        const decoded: string = AesCodec.decrypt(payload, LanConfig.messageKey);
        if (decoded.length > 0) {
          text = decoded;
        }
      } catch (e) {
        // 解不开就按明文处理（Android 的 FileSend.sendMessage 实际发的就是明文）
        text = payload;
      }
    }
    this.pushLog(`消息 <${from.devName}>${isClip ? '（写入剪贴板）' : ''}: ${text}`);
    // ① 进本机聊天列表（手机自己看得到）② 同步推给网页（浏览器里也要出现左侧气泡）
    //    这两条对应 Android 的 addMessage() 与 LHttpServer.sendMessage(..., isLeft=true)
    this.appendChat(true, from.devName, from.devIp, text, 'device');
    this.broadcastChatToWeb(from.devName, text, true);
    await this.store.insertMessage({
      msgId: `${Date.now()}-${Math.floor(Math.random() * 100000)}`,
      peerIp: from.devIp,
      direction: 0,
      content: text,
      msgType: LCmd.FS_MESSAGE,
      length: text.length,
      createdAt: Date.now()
    });
    this.emit();
  }

  /** 组装的密文特征判断，见 onMessageV4 的用法 */
  private static looksLikeCipherHex(s: string): boolean {
    if (s.length < 32 || s.length % 32 !== 0) {
      return false;
    }
    for (let i = 0; i < s.length; i++) {
      const c: string = s.charAt(i);
      const isHex: boolean = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
      if (!isHex) {
        return false;
      }
    }
    return true;
  }

  /** 把 v4 连接里带过来的对端记进设备表，便于 UI 立刻可点 */
  private trackPeer(d: LanDevice): void {
    const key: string = d.uniqueUuid.length > 0 ? d.uniqueUuid : d.devIp;
    // ★ 同上（5.0.21）：入站连接带过来的 uuid 若与历史条目不同（重装 App），
    //   这里必须把同 IP 的旧条目清掉，否则设备列表里会出现两条同名设备。
    this.dropSameIpExcept(d.devIp, key);
    const existing: LanDevice | undefined = this.devices.get(key);
    if (existing === undefined) {
      this.devices.set(key, d);
      this.store.upsertDevice(d);
    } else {
      existing.devName = d.devName.length > 0 ? d.devName : existing.devName;
      existing.devIp = d.devIp.length > 0 ? d.devIp : existing.devIp;
      existing.devPort = d.devPort > 0 ? d.devPort : existing.devPort;
      existing.devMode = d.devMode;
      existing.lastSeenMs = Date.now();
    }
  }

  /** 传输进度 -> 快照 + 日志 */
  /**
   * ★ 5.1.41：更新实时速度（相邻两次上报的字节差 / 时间差，EMA 平滑）。
   *
   * 【为什么要 EMA】瞬时值抖动极大（网络分片到达不均），直接显示会疯狂跳字。
   * 【为什么要 200ms 门限】上报本身有节流，再密也用不上；间隔太短会让
   *   分母趋近 0 放大噪声。
   */
  private updateSpeed(bytes: number): void {
    const now: number = Date.now();
    // ★ 5.1.47：第一次采样时记下起始时刻，供完成时算平均速度。
    if (this.xferStartAt === 0) {
      this.xferStartAt = now;
    }
    if (this.speedAt === 0) {
      this.speedAt = now;
      this.speedBytes = bytes;
      return;
    }
    const dt: number = now - this.speedAt;
    if (dt < 200) {
      return;
    }
    const inst: number = Math.max(0, bytes - this.speedBytes) * 1000 / dt;
    this.speedEma = this.speedEma === 0 ? inst : (this.speedEma * 0.6 + inst * 0.4);
    this.speedBytes = bytes;
    this.speedAt = now;
    this.snapshot.transferSpeed = this.speedEma > 0
      ? `${LanService.fmtSize(Math.round(this.speedEma))}/s`
      : '';
  }

  /** ★ 5.1.41：传输结束/清空时重置速度采样，避免下一段沿用上一段的基数 */
  private resetSpeed(): void {
    this.speedBytes = 0;
    this.speedAt = 0;
    this.speedEma = 0;
    this.xferStartAt = 0;   // ★ 5.1.47：下一段传输重新计时
    this.snapshot.transferSpeed = '';
  }

  private onTransferReport(r: TransferReport): void {
    // 统计增量流量
    if (r.bytes > this.lastReportBytes) {
      this.addTransferred(r.bytes - this.lastReportBytes);
    }
    this.lastReportBytes = r.bytes;

    if (!r.done) {
      const verb: string = r.direction === 'send' ? '发送' : '接收';
      // ★ 5.1.41：标题行只放「动词 + 文件名」。
      //   百分比由浮层右侧独立显示、计数与容量移到下一行 ⇒
      //   长文件名不再把百分比顶出可视区（vivi 实测「连百分比都看不见」）。
      // ★ 5.1.43：文件名兜底 —— 为空时给个可读的兜底名，
      //   否则标题行会只剩「接收 」，且完成提示的文件名也空。
      // ★ 5.1.45：标题**只放文件名**（动词移到副行）。
      //   原来 `接收 <长文件名>` 换行后「接收」独占第一行、文件名被挤到第二行
      //   （vivi 截图），观感很差。
      const nm: string = r.fileName.length > 0 ? r.fileName : '文件';
      // ★ 5.1.50：动词**不再拼进 transferText**（拼进去 ArkUI 会在空格处折行）
      this.snapshot.verb = '接收';
      this.snapshot.transferText = nm;
      this.snapshot.transferPercent = r.percent;
      this.snapshot.transferDone = false;
      // ★ 5.1.44：**按 `isSeg` 决定要不要显示 `i/n`**（5.1.43 一刀切去掉是错的，
      //   vivi 反馈「多个文件时也不显示 i/n 了」）。
      //   · `isSeg=true`（分片）：`fileIndex/fileCount` 是**片数**（1.35 恒 16），
      //     显示 `0/16` 会被误读成 16 个文件 ⇒ 只显示容量。
      //   · `isSeg=false`（多文件）：是「第 i 个 / 共 n 个文件」⇒ 应当显示。
      const cap: string =
        `${LanService.fmtSize(r.bytes)} / ${LanService.fmtSize(r.fileSize)}`;
      // ★ 5.1.45：动词（接收/发送）移到副行，标题只留文件名。
      const seq: string = (!r.isSeg && r.fileCount > 1)
        ? `${r.fileIndex}/${r.fileCount} · `
        : '';
      this.snapshot.transferSub = `${seq}${verb} · ${cap}`;
      this.updateSpeed(r.bytes);
      // 进度类刷新走节流版（见 emitThrottled 注释）。
      // ⚠️ 下面的**终态**分支必须继续用立即版 emit —— 否则进度条会停在 99%。
      this.emitThrottled();
      return;
    }

    // ★★ 5.1.40：接收完成也给 3 秒完成提示（此前只有网页上传有）。
    //   `showRecvDoneFloat` 内部会设完成态 + emit + 3s 后清空，
    //   「非空 → 空」的跳变仍然发生 ⇒ 文件页照常自动刷新。
    // ★ 5.1.43：⚠️ 原来这里还有 `r.fileName.length > 0` 的前置条件，
    //   文件名一旦为空就**整个完成提示都不出现**（不变色）；
    //   判定只看「成功 + 接收方向」，与文件名无关。
    if (r.ok && r.direction !== 'send') {
      // ★★★ 5.1.48 修 BUG：这里**原来还有两行无条件清理**
      //   `this.snapshot.transferSub = '';` 与 `this.snapshot.transferDone = false;`
      //   写在 if/else **外面**，把 showRecvDoneFloat 刚设好的完成态又抹掉了。
      //   ⇒ showRecvDoneFloat 内部的 emit 还能弹到 Toast（状态当时是对的），
      //     但本方法末尾最后一次 emit 发出去的是 transferDone=false
      //     ⇒ UI 永远走不进完成分支 ⇒ 浮层不变色、副行不显示。
      //   ⇒ 现在只在 else（失败）分支里清理；成功分支由 showRecvDoneFloat
      //     自己的 3 秒定时器负责清空（transferText 已经是同一套机制）。
      this.showRecvDoneFloat(
        r.fileName.length > 0 ? r.fileName : '文件', r.fileSize);
    } else {
      this.snapshot.transferText = '';
      this.snapshot.transferPercent = 0;
      this.snapshot.transferSub = '';
      this.snapshot.transferDone = false;
      this.snapshot.verb = '';       // ★ 5.1.50
      this.resetSpeed();
    }
    this.lastReportBytes = 0;
    if (r.message.length > 0) {
      // 只调用 setMessage —— 它内部已经 pushLog 过了。
      // 之前这里 pushLog + setMessage 各来一次，同一条错误在日志里出现两遍，
      // 真机截图看起来像「失败了两次」，白浪费一轮排查。
      this.setMessage(r.message);
    }
    // 传输成功 -> 在「消息」页留一条文件记录，点一下能跳到「文件」页。
    // ⚠️ 只有 ok=true 才记：失败的传输本来就有 setMessage 提示，
    // 再插一条文件名气泡会让人误以为传成了。
    // 多发（files.length > 1）时 FileTransfer 给的 fileName 已经是「N 个文件」。
    if (r.ok && r.fileName.length > 0) {
      const incoming: boolean = r.direction !== 'send';
      // ★ 5.0.53：走 appendFileChat —— 接收多个图片/视频时**每个一条消息**
      // ★ 5.1.47：把「大小 · 平均速度」带进气泡。
      this.appendFileChat(incoming, r.peer, this.transferPeerIp, r.fileName,
        r.fileNames, incoming ? 'device' : 'app',
        incoming ? this.lastTransferSummary : '');
    }
    this.transferPeerIp = '';
    this.emit();
  }

  /**
   * 手动网络自检。UI 上给一个按钮，用户不用重启服务就能拿到当前的真实结论。
   * 返回的字符串同时写进日志，方便截图取证。
   */
  async runDiagnostics(): Promise<string> {
    if (!this.isRunning) {
      const msg: string = '服务未启动，请先点「开始共享」';
      this.pushLog(msg);
      this.emit();
      return msg;
    }
    const head: string =
      `自检：监听端口 ${this.tcp.listeningPort}，已接受连接 ${this.tcp.accepted} 次，` +
      `本机 ${this.localNet.ip}`;
    this.pushLog(head);
    this.emit();
    const r: string = await this.tcp.runSelfTest();
    this.emit();
    return r;
  }

  /**
   * 主动把文件发给某个设备。
   * 由 UI 的设备列表点击触发。
   *
   * @param target 目标设备（会用设备表里的最新快照覆盖 IP/端口）
   * @param files  待发文件（系统文件选择器给出的 URI）
   */
  async sendFiles(target: LanDevice, files: OutgoingFile[]): Promise<boolean> {
    if (!this.isRunning) {
      this.setMessage('请先点「开始共享」再发送');
      return false;
    }
    if (files.length === 0) {
      return false;
    }
    if (this.transferBusy) {
      this.setMessage('已有传输在进行中，请等待完成');
      return false;
    }
    // 用设备表里的最新地址，避免 UI 拿到的是过期快照
    // ⚠️ 防御：target 可能来自 UI 快照，uniqueUuid/devIp 任意一项都可能缺失
    const uid: string = target.uniqueUuid ?? '';
    const ip: string = target.devIp ?? '';
    const key: string = uid.length > 0 ? uid : ip;
    const fresh: LanDevice | undefined = key.length > 0 ? this.devices.get(key) : undefined;
    const dev: LanDevice = fresh === undefined ? target : fresh;
    if ((dev.devIp ?? '').length === 0) {
      this.setMessage('目标设备 IP 未知，无法连接');
      return false;
    }

    this.transferBusy = true;
    // 记下对端 IP：传输成功后要在消息页插一条文件记录，peerIp 只有这里拿得到
    this.transferPeerIp = dev.devIp;
    this.setMessage(`开始发送 ${files.length} 个文件到 ${dev.devName}`);
    this.emit();
    try {
      // ★ 出站协议分流：按**对端广播的** dataVersion 选协议栈。
      //   - >= 5（1.35 修改版 / 本机 LANShare） → v5 二进制帧（1101 / 1110）
      //   - <= 4（官方 1.2.x 及更早，源码 LVersion 只到 v4） → v4 裸序列化
      // 官方 handleVersion 对「cmd 不是 -2 且 dataVersion>=4」的包只会回
      // 「不支持的版本」并丢弃 —— 给官方发 v5 帧必然失败，必须分流。
      // encData 固定 false：Android 端读的是本地偏好 PreConfig.ENC_DATA，
      // 默认未开启；鸿蒙侧跟随默认值以保证互通。
      const peerVer: number = dev.dataVersion ?? 0;
      if (peerVer >= LanConfig.V5_MIN_DATA_VERSION) {
        this.pushLog(`出站协议：v5（对端 dataVersion=${peerVer}）`);
        this.emit();
        return await V5Transfer.send(this.self, dev, files, false,
          (r: TransferReport) => this.onTransferReport(r));
      }
      this.pushLog(`出站协议：v4（对端 dataVersion=${peerVer}）`);
      this.emit();
      return await FileTransfer.send(this.self, dev, files, false,
        (r: TransferReport) => this.onTransferReport(r));
    } finally {
      this.transferBusy = false;
      this.emit();
    }
  }

  /** 当前是否在传输中（UI 用来禁用按钮） */
  get isTransferring(): boolean {
    return this.transferBusy;
  }

  // ------------------------------------------------------------------
  // 网页端上传（浏览器 -> 本机）
  // ------------------------------------------------------------------

  /**
   * 网页上传进度 → 应用内浮层。
   *
   * 走的还是 `transferText` / `transferPercent` 这一对字段：
   * 浮层与文件页的「传输结束自动刷新」都是靠它俩驱动的，
   * 复用同一套就不用再给 UI 加第二条状态通道。
   */
  private onWebUploadProgress(received: number, total: number, name: string): void {
    const pct: number = total > 0 ? Math.min(100, Math.floor(received * 100 / total)) : 0;
    const who: string = name.length > 0 ? name : '文件';
    // ★ 5.1.41：同协议侧 —— 标题只留「动词 + 文件名」，其余拆到副行。
    // ★ 5.1.45：同协议侧，标题只放文件名，「网页上传」进副行。
    // ★ 5.1.50：同协议侧，动词独立成字段，不拼进 transferText
    this.snapshot.verb = '接收';
    this.snapshot.transferText = who.length > 0 ? who : '文件';
    this.snapshot.transferPercent = pct;
    this.snapshot.transferDone = false;
    this.snapshot.transferSub = `网页上传 · ` + (total > 0
      ? `${LanService.fmtSize(received)} / ${LanService.fmtSize(total)}`
      : `已收 ${LanService.fmtSize(received)}`);
    this.updateSpeed(received);
    // ★★ 5.1.24（vivi 12:24 观测驱动）：**立即 emit 改为 emitThrottled**。
    //   原来每次进度上报都 emit ⇒ @State 变化 ⇒ ArkUI **重建整个页面**，
    //   而 HTTP 上传循环每 2MB 让一帧 —— 那一帧里整页重建耗时可观
    //   ⇒ 主线程反复占满 ⇒ 实测网页上传只有 17MB/s，且「进度条超级卡」。
    //
    //   ★ 对照：V5 接收的 `onTransferReport`（本文件 :3422）用的是 **emitThrottled**
    //     （5.0.69 起加的节流版）⇒ 同一台设备 V5 接收能跑 50MB/s。
    //     就差这一个词。
    //
    // ⚠️ **终态必须仍用立即版 emit**（见下面的 `onWebUploadEnd`）——
    //    否则进度条停在 99%、浮层不消失（5.0.69 踩过这个坑，本版不动它）。
    this.emitThrottled();
  }

  /**
   * 网页上传结束（成功与失败都会来）。
   *
   * ⚠️ 这里**必须**无条件清掉 `transferText`：断线重传之类的场景下若只清成功路径，
   * 浮层会永远停在某个百分比上，`onSnapshot` 里的「非空 → 空」跳变也永远不会发生，
   * 文件页因此不再自动刷新。
   */
  /**
   * ★★ 5.1.28：**先显示完成态，1.5 秒后再清空**。
   *
   * 【为什么要改】vivi 13:04 反馈「传输完 App 没提示，网页端有」。
   *   App 端的传输提示是**浮层**（`transferFloat`），而原来这里第一行就
   *   `transferText = ''` ⇒ 浮层在结束那一瞬直接消失，**从来没有完成态**。
   *   （消息页那条 `appendFileChat(..., 'web')` 记录是另一回事，要切页才看见。）
   *   ⚠️ 这**不是** 5.1.27 引入的回归 —— 5.1.12 及以前同样没有完成提示。
   *
   * 【⚠️ 顺序契约 —— 5.0.51 踩过的坑】
   *   `transferText` 由「非空 → 空」是**传输结束、刷新文件页**的触发信号
   *   （`Index.ets` 的 `onSnapshot` 靠这个跳变调 `refreshReceived()`）。
   *   所以**清空动作必须仍然发生**，只是推迟 1.5 秒；
   *   否则文件页不会自动刷新（这正是 5.0.69「终态必须用立即版 emit」的同源问题）。
   */
  private onWebUploadEnd(ok: boolean, names: string[], totalBytes: number, error: string): void {
    if (ok) {
      const label: string = names.length === 1 ? names[0] : `${names.length} 个文件`;
      // ★ 5.1.40：改走公共完成提示（与协议侧同一套，保留 3 秒）
      this.showRecvDoneFloat(label, totalBytes);
    } else {
      this.snapshot.transferText = '';
      this.snapshot.transferPercent = 0;
      this.snapshot.transferSub = '';
      this.snapshot.transferDone = false;
      this.snapshot.verb = '';       // ★ 5.1.50
      this.resetSpeed();
    }
    if (ok) {
      const label: string = names.length === 1 ? names[0] : `${names.length} 个文件`;
      this.pushLog(`网页上传完成：${label}（${LanService.fmtSize(totalBytes)}）`);
      // 与「收到对端文件」一样在消息页留一条记录，点开可跳到文件页
      // ★ 5.0.53：同样按「媒体每个一条」拆 —— 顺便把 names 传下去，
      //   网页端上传的图/视频这才有缩略图（以前只传了合并后的 label，UI 拿不到名字）。
      // ★ 5.1.47：同样带「大小 · 平均速度」。
      this.appendFileChat(true, '网页端', '', label, names, 'web',
        this.lastTransferSummary);
    } else {
      this.pushLog(`网页上传失败：${error}`);
    }
    this.emit();
  }

  /**
   * ★ 5.1.47：算**本次传输的平均速度**（`总量 / 耗时`）。
   *
   * 【为什么不用 `speedEma`】那是**瞬时**速度（相邻两次上报的差值），
   *   抖动大，而且传输完成时会被 `resetSpeed()` 清掉 ⇒ 浮窗上什么都看不到。
   * 【为什么要 `dt >= 200` 门限】太快的小文件除出来的速度没有意义。
   *
   * @param size 本次传输的总字节数
   */
  /**
   * ★★ 5.1.53：本次传输的**平均速度**（总量 / 耗时）。
   *
   * ## 为什么调低了门限（vivi 实测「小文件不显示速度」）
   *   原来有 `if (dt < 200) return ''`，而**小文件恰恰 `dt` 极小**：
   *   19.8 KB 在局域网只要 1~5 ms、129.6 KB 约 2~8 ms
   *   ⇒ 全部被这道门槛丢掉 ⇒ 气泡里只显示大小、没有速度
   *   （646 MB 传了 17 s，`dt` 够大所以能显示 —— 掩盖了这个问题）。
   *
   * ## 新的门限：1 ms
   *   * `dt <= 0`（同一毫秒内完成）⇒ 返回空 —— 速度无意义。
   *   * `dt < 1` 会算出 18 MB/s / 123 MB/s 这种虚高值（`Date.now()` 精度所限），
   *     所以**下限取 1 ms**，宁可显示一个小值也不显示离谱的值。
   *
   * ★ 顺带：`xferStartAt` 记的是**第一次进度上报**的时刻，
   *   不是传输真正开始的时刻；小文件常常只有一次上报 ⇒ `dt` 天然极小，
   *   这正是它被旧门槛吃掉的原因。
   */
  private avgSpeedText(size: number): string {
    if (this.xferStartAt <= 0 || size <= 0) {
      return '';
    }
    const dt: number = Date.now() - this.xferStartAt;
    if (dt < 1) {
      return '';
    }
    return `${LanService.fmtSize(Math.round(size * 1000 / dt))}/s`;
  }

  /**
   * ★ 5.1.47：本次传输的「大小 + 平均速度」摘要，给浮窗副行与消息气泡共用。
   */
  private transferSummary(size: number): string {
    const sz: string = LanService.fmtSize(size);
    const avg: string = this.avgSpeedText(size);
    return avg.length > 0 ? `${sz} · ${avg}` : sz;
  }

  /** ★ 5.1.40：**所有**接收路径的完成提示统一走这里（网页上传 + v4/v5/分片/FileTransfer）。
   *
   * 【为什么要抽出来】此前只有网页上传有完成提示（1.5s），
   *   而协议侧走 `onTransferReport`，它在 `r.done` 分支第一件事就是
   *   `transferText = ''` ⇒ 完成态一闪而过，用户基本看不到。
   *   （这与 5.1.28 修的是同一个坑，当时只补了网页那条路径。）
   *
   * 【⚠️ 顺序契约 —— 5.0.51 踩过的坑，勿改】
   *   `transferText` 的「非空 → 空」跳变是**文件页自动刷新**的触发信号
   *   （`Index.ets` 的 `onSnapshot` 靠它调 `refreshReceived()`）。
   *   所以**清空动作必须仍然发生**，只是推迟 3 秒。
   *
   * 【★ 5.1.42：完成态改用显式字段 `transferDone`，不再往文案里塞 `✓` 前缀】
   *   5.1.41 曾让 UI 靠 `transferText.startsWith('✓')` 推断完成态，实测失效
   *   （浮层不变色、LoadingProgress 不消失）。
   *   ⇒ 完成与否是**状态**，不是**文案**；两者混在一起时文案一改就失效。
   *
   * @param label  文件名（多文件时传「N 个文件」）
   * @param size   字节数，用于显示大小
   */
  private showRecvDoneFloat(label: string, size: number): void {
    // ★★ 5.1.49：去掉文案里的 `✓ ` 前缀。
    //   5.1.44 把它当「不依赖状态追踪的最后兜底」写进去，但真凶是
    //   `onTransferReport` 里 if/else 外的无条件清理（5.1.48 已修）——
    //   **字段早就可靠了，字符兜底不再需要**，留着只会变成
    //   「标题前面一个大✓ + 文案里又一个小✓」（vivi 截图里就是这样）。
    //   ★ 完成态的视觉标识由**浮层第一行的静态 ✓ 图标**承担。
    this.snapshot.verb = '';   // ★ 5.1.50：完成态不显示动词
    this.snapshot.transferText = label.length > 0 ? label : '文件';
    this.snapshot.transferPercent = 100;
    this.snapshot.transferDone = true;
    // ★ 5.1.41：完成态把大小放到副行，标题行留给文件名（长度不受限）。
    // ★ 5.1.47：副行加上**平均速度**（`646.1 MB · 30.2 MB/s`）。
    this.snapshot.transferSub = `接收完成 · ${this.transferSummary(size)}`;
    // 供完成时插消息气泡用（消息页要显示同样的大小 + 平均速度）。
    this.lastTransferSummary = this.transferSummary(size);
    this.resetSpeed();
    this.emit();
    // ★ 定时器句柄存起来：连着传多个文件时，旧的定时器要作废，
    //   否则前一次的「清空」会提前把后一次的完成提示抹掉。
    if (this.doneFloatTimer >= 0) {
      clearTimeout(this.doneFloatTimer);
    }
    this.doneFloatTimer = setTimeout(() => {
      this.doneFloatTimer = -1;
      this.snapshot.transferText = '';
      this.snapshot.transferPercent = 0;
      this.snapshot.transferSub = '';
      this.snapshot.transferDone = false;
      this.snapshot.verb = '';       // ★ 5.1.50
      this.resetSpeed();
      this.emit();
    }, 5000);   // ★ 5.1.50：vivi 要求完成浮窗保留 **5 秒**（原 3000ms）
  }

  private static fmtSize(n: number): string {
    if (n < 1024) {
      return `${n} B`;
    }
    if (n < 1024 * 1024) {
      return `${(n / 1024).toFixed(1)} KB`;
    }
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }

  /**
   * 下载进度（本机 -> 浏览器）→ 应用内浮层。
   *
   * `total < 0` 是不可计量的阶段（打包中），此时 `name` 本身就是一整句文案，
   * 直接显示、百分比给 0，不要拿它去除以什么。
   */
  private onWebDownloadProgress(sent: number, total: number, name: string): void {
    if (total < 0) {
      this.snapshot.transferText = name;
      this.snapshot.transferPercent = 0;
      this.emit();
      return;
    }
    const pct: number = total > 0 ? Math.min(100, Math.floor(sent * 100 / total)) : 0;
    const who: string = name.length > 0 ? name : '文件';
    this.snapshot.transferText =
      `发送到网页 ${who} ${pct}%（${LanService.fmtSize(sent)} / ${LanService.fmtSize(total)}）`;
    this.snapshot.transferPercent = pct;
    this.emit();
  }

  /**
   * 下载结束（成功与失败都会来）。
   *
   * 与上传结束同理：必须无条件清 `transferText`，否则浏览器取消下载时
   * 浮层会永远停在某个百分比，文件页的自动刷新也再不会触发。
   */
  private onWebDownloadEnd(ok: boolean, name: string, totalBytes: number, error: string): void {
    this.snapshot.transferText = '';
    this.snapshot.transferPercent = 0;
    if (ok) {
      const label: string = name.length > 0 ? name : '文件';
      this.pushLog(`已发送到网页端：${label}（${LanService.fmtSize(totalBytes)}）`);
    } else {
      this.pushLog(`发送到网页端失败：${error}`);
    }
    this.emit();
  }

  // ------------------------------------------------------------------
  // 主动推送文件给网页端（本机 -> 浏览器）
  // ------------------------------------------------------------------

  /**
   * 让网页端把指定的沙箱文件取走。
   *
   * 这是官方网页端**没有**的方向：它只会从自己那边上传、以及拉取手机沙箱里
   * 已经存在的文件。用户想要的是「在手机上选个文件直接发给浏览器」——
   * HTTP 是请求-响应的，服务端推不了字节，所以做法是：
   * **WebSocket 推一条「快来取」的通知 + 浏览器自己走 /compressFiles 两步下载**。
   *
   * @param paths 沙箱内的绝对路径
   * @returns 推送到的网页会话数；0 = 当前没有网页端连着；-1 = 一个可推的文件都没有
   */
  /**
   * ★★ 5.1.60：把**用户授权选取的文件 URI** 直接推给网页端，**不做任何复制**。
   *
   * 为什么不再走 `stageForWeb()`：那个函数把整份文件复制到
   * `saveRoot/网页待下载/` 且**从不清理** ⇒ 沙箱里永久留下一份（vivi 明确不接受）。
   *
   * 现在网页端单文件走 `GET /stagefile/<名>?uri=…`，
   * 由 `HttpRouter.stageFile()` 用 `fileIo.openSync(uri)` 直接流式发送 ⇒ **零落盘**。
   *
   * ⚠️ **只支持单文件**：多个文件必须打包成 zip，而 `zlib.compressFiles` 只认真实路径
   * ⇒ 多文件仍由 `stageForWeb()` 复制后走 `/compressFiles`。
   *
   * @param items 每项 = { uri, name }（name 用于网页端拼下载文件名）
   * @returns 推送到的网页会话数；0 = 没有网页端连着；-1 = 一条可推的都没有
   */
  /** ★ 5.1.61：「发送到网页端」的**副本目录**（唯一的、可安全整目录清理的地方） */
  static webStageDir(saveRoot: string): string {
    return `${saveRoot}/网页待下载`;
  }

  /**
   * ★★ 5.1.61 清理「发送到网页端」的沙箱副本。
   *
   * 只删 `${saveRoot}/网页待下载/` 下的文件 —— 这个目录**只由 stageForWeb 产生**，
   * 所以整目录清理不会碰到用户原有的接收文件（那是 `saveRoot/<分类>/`）。
   * ⚠️ **绝不能按「本次推送的路径列表」盲删** —— 那些路径里可能混着
   * 文件页勾选的原有文件（`pushFilesToWeb` 也走同一入口）。
   *
   * @param keep 需要保留的路径（一般为空）
   */
  pruneWebStage(keep: string[] = []): number {
    const dir: string = LanService.webStageDir(this.storage.saveRoot);
    let names: string[] = [];
    try {
      names = fileIo.listFileSync(dir);
    } catch (e) {
      return 0;                    // 目录不存在 = 没有副本
    }
    let n: number = 0;
    for (let i = 0; i < names.length; i++) {
      const p: string = `${dir}/${names[i]}`;
      if (keep.indexOf(p) >= 0) {
        continue;
      }
      try {
        const st: fileIo.Stat = fileIo.statSync(p);
        if (st.isDirectory()) {        // 目录里不该有子目录，保险起见跳过
          continue;
        }
        fileIo.unlinkSync(p);
        n += 1;
      } catch (e) {
        // 删不掉就算了（可能正被占用），下次 prune 或下次启动再试
        Log.w(TAG, `网页待下载副本清理失败: ${p}`);
      }
    }
    if (n > 0) {
      this.pushLog(`已清理 ${n} 个网页待下载副本`);
      this.emit();
    }
    return n;
  }

  pushUrisToWeb(items: WebPushItem[]): number {
    const use: WebPushItem[] = [];
    for (let i = 0; i < items.length; i++) {
      const it: WebPushItem = items[i];
      if (it.uri.length === 0 || it.name.length === 0) {
        continue;
      }
      use.push(it);
    }
    if (use.length === 0) {
      return -1;
    }
    if (this.wsSessions.length === 0) {
      return 0;
    }
    let uriJson: string = '';
    let nameJson: string = '';
    for (let i = 0; i < use.length; i++) {
      if (i > 0) {
        uriJson += ',';
        nameJson += ',';
      }
      uriJson += HttpRouter.jsonStr(use[i].uri);
      nameJson += HttpRouter.jsonStr(use[i].name);
    }
    // 只推uri + names，**不含 paths** ⇒ 网页端据此判断「零落盘直推」
    const json: string =
      `{"cmd":${WS_CMD_PUSH_FILES},"uris":[${uriJson}],"names":[${nameJson}]}`;
    let sent: number = 0;
    for (let i = 0; i < this.wsSessions.length; i++) {
      const s: WebSocketSession = this.wsSessions[i];
      if (!s.isAlive) {
        continue;
      }
      s.sendText(json);
      sent += 1;
    }
    if (sent > 0) {
      this.pushLog(`已通知 ${sent} 个网页端直推 ${use.length} 个文件（不落盘）`);
    }
    this.emit();
    return sent;
  }

  pushFilesToWeb(paths: string[]): number {
    const safe: string[] = [];
    for (let i = 0; i < paths.length; i++) {
      const p: string = paths[i];
      if (!this.isWebSharable(p)) {
        Log.w(TAG, `拒绝推送沙箱外的文件: ${p}`);
        continue;
      }
      let exists: boolean = false;
      try {
        exists = fileIo.accessSync(p);
      } catch (e) {
        exists = false;
      }
      if (!exists) {
        Log.w(TAG, `推送跳过不存在的文件: ${p}`);
        continue;
      }
      safe.push(p);
    }
    if (safe.length === 0) {
      return -1;
    }
    if (this.wsSessions.length === 0) {
      return 0;
    }

    let listJson: string = '';
    let namesJson: string = '';
    for (let i = 0; i < safe.length; i++) {
      if (i > 0) {
        listJson += ',';
        namesJson += ',';
      }
      const nm: string = safe[i].substring(safe[i].lastIndexOf('/') + 1);
      listJson += HttpRouter.jsonStr(safe[i]);
      namesJson += HttpRouter.jsonStr(nm);
    }
    const json: string =
      `{"cmd":${WS_CMD_PUSH_FILES},"list":[${listJson}],"names":[${namesJson}]}`;

    let sent: number = 0;
    for (let i = 0; i < this.wsSessions.length; i++) {
      const s: WebSocketSession = this.wsSessions[i];
      if (!s.isAlive) {
        continue;
      }
      s.sendText(json);
      sent += 1;
    }
    if (sent > 0) {
      this.pushLog(`已通知 ${sent} 个网页端下载 ${safe.length} 个文件`);
    }
    this.emit();
    return sent;
  }

  /**
   * 只允许把沙箱内的文件推给网页端。
   * 网页端拿到的是绝对路径，放开了等于把整个私有目录暴露给局域网里的浏览器。
   */
  private isWebSharable(p: string): boolean {
    if (p.length === 0 || p.indexOf('..') >= 0) {
      return false;
    }
    const root: string = this.storage.saveRoot;
    if (root.length > 0 && p.startsWith(root)) {
      return true;
    }
    const files: string = this.ctx !== null ? this.ctx.filesDir : '';
    return files.length > 0 && p.startsWith(files);
  }

  /**
   * 把外部（相册 / 文件管理器）选中的文件搬进沙箱，好推给网页端。
   *
   * 为什么必须先复制：HTTP 服务端打包用的是 `zlib.compressFiles`，它只认
   * **真实文件路径**；而 picker 给的是带临时授权的 URI（`datashare://`），
   * 打包不了。所以「发到网页」对沙箱外的文件来说是一次复制 + 一次通知。
   *
   * @returns 落盘后的沙箱路径（失败的文件会被跳过，不中断整批）
   */
  async stageForWeb(files: OutgoingFile[]): Promise<string[]> {
    const dir: string = LanService.webStageDir(this.storage.saveRoot);
    FileStorage.mkdirs(dir);
    const out: string[] = [];
    for (let i = 0; i < files.length; i++) {
      const f: OutgoingFile = files[i];
      const src: FileSource | null = FileSource.open(f.uri);
      if (src === null) {
        this.pushLog(`读不到「${f.name}」，已跳过`);
        continue;
      }
      const dst: string = FileStorage.uniquePathIn(dir, f.name);
      const sink: FileSink | null = FileSink.create(dst);
      if (sink === null) {
        src.close();
        this.pushLog(`无法写入「${f.name}」，已跳过`);
        continue;
      }
      let okc: boolean = true;
      let guard: number = 0;
      while (guard < 100000) {
        guard += 1;
        const chunk: Uint8Array | null = src.readChunk(STAGE_CHUNK);
        if (chunk === null || chunk.length === 0) {
          break;
        }
        if (!sink.append(chunk)) {
          okc = false;
          break;
        }
      }
      src.close();
      sink.close();
      if (okc) {
        out.push(dst);
        // ★★ 5.1.61：登记「这份是本进程复制出来的副本」——
        //   打包成功后 HttpRouter 只删登记在册的，
        //   **绝不碰用户原有的接收文件**（`pushFilesToWeb` 也走这个函数）。
        HttpRouter.markWebStage([dst]);
      } else {
        this.pushLog(`写入「${f.name}」失败，已跳过`);
      }
    }
    return out;
  }

  /** 网页端 WebSocket 当前连接数（UI 用来判断「发到网页」有没有接收方） */
  get webClientCount(): number {
    return this.wsSessions.length;
  }

  /** 接收文件的落盘位置说明 */
  get saveLocation(): string {
    return this.storage.describe;
  }

  /** 组装一个"错误/未实现"应答包 */
  private static errorPacket(cmd: number, reason: string): Uint8Array {
    const enc: DataEnc = new DataEnc(reason.length + 16);
    enc.packData(LCmd.FS_BREAK);
    enc.setCount(cmd);
    enc.putString(reason);
    return enc.encode();
  }

  /** 设备唯一标识。首次启动生成后持久化，对应 Android Config.uniqueUUid */
  private static ensureUuid(ctx: common.UIAbilityContext): string {
    if (LanConfig.uniqueUuid.length > 0) {
      return LanConfig.uniqueUuid;
    }
    const seed: string = `${ctx.applicationInfo.name}-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
    // 不引入额外依赖。用两个经典乘加哈希（FNV-1a / djb2 变体）拼出 32 位十六进制串。
    //
    // ⚠️ 这里必须用 Math.imul + `>>> 0`，不能写成 `(h1 ^ c) * 16777619 % 2^32`：
    //   1) `h1 ^ c` 会把 h1 折成**有符号 int32**（2166136261 -> -2128831035），负数再乘，
    //      符号会一路带下去；
    //   2) JS 的 `%` 与 C 不同，是**保号**的，负数的模还是负数；
    //   3) `(-x).toString(16)` 输出 "-7f3a..."，`padStart(8,'0')` 对负号补位后长度也不是 8。
    // 三者叠加的后果实测就是 uuid 变成
    //   "-b98e80984aea8e470c9bf12f-6ea3f251" 这种带连字符的畸形串
    // （真机抓包已验证：这个值会被原样发给对端）。
    const MOD: number = 4294967296;
    let h1: number = 2166136261;
    let h2: number = 5381;
    for (let i = 0; i < seed.length; i++) {
      const c: number = seed.charCodeAt(i);
      // Math.imul 做的是 32 位有符号乘法，`>>> 0` 再折回无符号，两步都不可省。
      // 不改成 `* 16777619` 是因为结果可达 7.2e16，已超出 double 精确整数范围(2^53)。
      h1 = Math.imul(h1 ^ c, 16777619) >>> 0;
      h2 = (h2 * 33 + c) % MOD;
    }
    const uuid: string =
      h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0') +
      ((h1 ^ h2) >>> 0).toString(16).padStart(8, '0') +
      ((h1 + h2) >>> 0).toString(16).padStart(8, '0');
    LanConfig.uniqueUuid = uuid;
    return uuid;
  }

  /**
   * 取本机的「设备名」作为 LANShare 默认显示名。
   *
   * ⚠️ 鸿蒙普通应用拿不到用户可改的那条「设备名称」（`deviceInfo.name` 需受限权限，
   * 未上架/调试 HAP 也未必放得开），能用且无需权限的最友好名称是 `marketName`
   * （营销名，如 "HUAWEI Mate 70 Pro"）。拿不到就退到 productModel，再不行才是占位符。
   * 用户若想自定义，可在配置里覆盖 LanConfig.userName（见 startSharing 的取用逻辑）。
   */
  private static localDeviceName(): string {
    const market: string = deviceInfo.marketName;
    if (market && market.length > 0) {
      return market;
    }
    const model: string = deviceInfo.productModel;
    if (model && model.length > 0) {
      return model;
    }
    return 'HarmonyOS 设备';
  }
}
