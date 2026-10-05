/**
 * 全局配置 —— 平移自 app/src/main/java/com/fgsqw/lanshare/config/Config.java
 *
 * 关键原则：端口、魔数、协议版本一律与 Android 端保持一致，
 * 保证鸿蒙端能与现有 Android / Windows 客户端直接互通。
 */

export class LanConfig {
  // ---------- 网络端口（与 Android 端 byte-identical） ----------
  /** 文件传输 TCP 端口。Android: Config.DEFAULT_FILE_SERVER_PORT */
  static readonly DEFAULT_FILE_SERVER_PORT: number = 5856;
  /** 设备发现 UDP 广播端口。Android: Config.DEFAULT_UDP_PORT */
  static readonly DEFAULT_UDP_PORT: number = 4573;
  /** HTTP Web 服务端口。Android 侧 LHttpServer 使用 8080 */
  static readonly DEFAULT_HTTP_PORT: number = 8080;

  // ---------- 协议常量 ----------
  /** 魔数 0x66677371 == 'fgsq' 的 ASCII。UDP/TCP 每个包头部 4 字节大端 */
  static readonly MAGIC_NUM: number = 0x66677371;
  /**
   * 数据协议版本（**本机对外广播的版本号**）。
   *
   * 这个包（LANShare）对齐的是 1.35 修改版的第 5 代协议：
   * 握手帧里写 5、帧是「12 字节头 + 二进制设备头」、文件走 1101/1110。
   *
   * ⚠️ 广播 5 只代表「我支持 v5」，**不代表只发 v5**：
   * 出站用哪套协议由对端广播的 `dataVersion` 决定（见 `V5_MIN_DATA_VERSION` 与
   * `LanService.sendFiles` 的分流）。官方版（dataVersion=4）看到 cmd=1101 会直接回
   * 「不支持的版本」并丢弃，所以对官方必须发 v4 帧。
   */
  static readonly DATA_VERSION: number = 5;

  /**
   * 「该用 v5 帧发送」的 dataVersion 门槛。
   *
   * 官方 LANShare 最高只到 v4（源码 `LVersion` 仅定义 DATA_VERSION_4），
   * v5 是 1.35 修改版引入的私有代次。因此：
   *   - 对端 dataVersion >= 5（1.35 / 本机 LANShare）→ 发 v5 帧
   *   - 对端 dataVersion <= 4（官方 1.2.x 及更早）      → 发 v4 帧
   *
   * ⚠️ 判据必须取对端**广播出来的** dataVersion，而不是本机的 DATA_VERSION：
   *    两边都是 5 却用本机值判断，就会给官方发 v5 帧 —— 那正是「官方不互通」的成因。
   */
  static readonly V5_MIN_DATA_VERSION: number = 5;

  // ---------- 加密 ----------
  /**
   * 固定密钥（AES-256-ECB）。与原 Android 端保持一致以便互通。
   *
   * ⚠️ 安全提示：这是硬编码在客户端里的对称密钥，任何拿到 APK/HAP 的人都能提取。
   * 它的真实作用只是"防止同网段其它工具的随意读取"，不构成机密性保障。
   * ECB 模式还会泄漏明文块重复特征。迁移期间为保证互通必须保持原样，
   * 但应在协议 v5 中替换为 ECDH 协商 + AES-GCM。见 docs/迁移对照表.md「安全债」。
   */
  static readonly KEY: string = '6c9b%8ErII@Rc&f';
  /**
   * 「密钥的密钥」的默认值 —— 注意它**不是**聊天消息实际使用的密钥。
   *
   * Android `Config.initPrefs()` 的第 137 行附近还有一步：
   * ```
   * String messageKey = prefUtil.getString(PreConfig.MESSAGE_KEY, Config.DEFAULT_MESSAGE_KEY);
   * Config.MESSAGE_KEY = AESUtils.decrypt(messageKey, Config.KEY);   // ← 再解一层
   * ```
   * 即先把下面这串 hex 用 KEY 解出来，得到的 32 字符才是真正的 AES-256 消息密钥。
   * 少了这一步，会和 Android 端「用 A 加密、用 B 解密」差一整层，消息永远解不开。
   */
  static readonly DEFAULT_MESSAGE_KEY: string =
    'e4be1373272c69e0932651d97187b746c6725b17bbe84ad0b0fe2d4e81fc1d6c0c633d8ebd7f0fea65a57a9d5529d214';

  /**
   * 聊天消息实际使用的 AES-256 密钥（32 字节，无需补齐）。
   *
   * 取值 = AES-ECB-PKCS5 解密(DEFAULT_MESSAGE_KEY, KEY)。已用 Python/OpenSSL 独立复算过：
   * 48 字节密文 -> 32 字节明文 + 16 字节 0x10 padding。
   * 运行时 `LanService.ensureMessageKey()` 会再解一次做自愈（万一将来 DEFAULT 改了）。
   */
  static readonly DEFAULT_MESSAGE_KEY_PLAIN: string = 'Ndsi3dklHn4ErC95z3u2QnxeAMQwkNJp';

  /** 运行时密钥（可由设置页覆盖） */
  static messageKey: string = LanConfig.DEFAULT_MESSAGE_KEY_PLAIN;

  // ---------- 业务参数 ----------
  /**
   * 设备扫描/心跳间隔（秒）。Android: Config.SCANN_TIME
   *
   * ⚠️ 本机取 3s 而不是原版的 5s（vivi 2026-10-01：「发现设备的速度」）。
   *    3s 只影响**我们主动广播**的频率，对端不受影响、协议不变 ——
   *    好处是我们对别人而言「刷新得更勤」，别人列表里我们不容易被判超时。
   */
  static readonly SCAN_TIME: number = 3;
  /** 设备离线判定超时（毫秒）。Android 侧由 setTime 与 System.currentTimeMillis 比较得出 */
  /**
   * 多久没收到某设备的心跳就判定它离线（毫秒）。
   *
   * ⚠️ 必须 **大于心跳周期 `SCAN_TIME`（5s）**：UDP 广播丢一个包是常态，
   *    超时若 ≤ 5s，对端只要漏发一次就会被误判离线、下一轮又冒出来，列表反复闪烁。
   *    8s 容忍一次丢包抖动。
   *    原值 15000 在真机上表现为「对方设备都关了，列表里还挂着十几秒」。
   *    ⚠️ 本值现在只对「无法快速探活」的设备兜底（见 DEVICE_PROBE_* 一组常量）：
   *       对端主动下线（cmd 1003）→ 立刻消失；
   *       对端主动下线（cmd 1003）→ 立刻消失；
   *       对端关掉 App / 强杀 / 拔电（**TCP 复核连得上**的设备）→ **约 2~3s** 消失；
   *       其余情况 → 本值兜底（配合 1s 巡检，≈ 8~9s）。
   */
  static readonly DEVICE_OFFLINE_MS: number = 8000;

  // ---------- 设备「快速下线」探活（vivi 2026-10-01 第二/三次反馈） ----------
  /**
   * 一条设备多久没动静，就开始对它做 **UDP 单播**探活（毫秒）。
   *
   * ## 为什么必须有它
   * 「多久没收到心跳就判离线」这个模型有一个绕不开的下界：**必须大于对端的心跳周期**。
   * 官方版心跳是 5s（`SCAN_TIME`），所以纯超时判定最快也只能做到 7~8s，
   * 再往下调就会「对端少发一个包 → 误判离线 → 下一轮又冒出来」来回闪。
   * 这就是把 15s 调到 9s、8s 之后用户仍然觉得「没什么优化」的根本原因 ——
   * 不是参数没调到位，而是**被动等待**这个模型本身到顶了。
   *
   * ## 换成主动问
   * 局域网内 UDP 单播几乎不丢包。安静超过这个时间就直接单播问一句：
   * 愿意应答的设备毫秒级回包 → `lastSeenMs` 刷新 → 永远不会被误判。
   */
  static readonly DEVICE_PROBE_QUIET_MS: number = 1200;
  /**
   * 同一台设备两次 UDP 探活的最小间隔（毫秒），防止每轮巡检（1s）都重复发。
   *
   * ⚠️ 它**不参与判死**：UDP 探活的唯一作用是「让愿意应答的设备顺手刷新在线时间」，
   *    判死交给下面的 TCP 复核。所以这里不必发得太密，1.5s 一次足够。
   */
  static readonly DEVICE_PROBE_RETRY_MS: number = 1500;

  // ---------- 设备「快速下线」的确定性凭据：TCP 复核（vivi 2026-10-01 第三次反馈） ----------
  /**
   * ## 为什么 UDP 探活靠不住
   *
   * 「单播探活 + 往返时间判据」有一个隐含前提：**对端会应答 UDP_GET_DEVICES**。
   * 真机上这个前提并不成立 —— 对端（1.35 / 官方）完全可以只按自己的周期广播心跳，
   * 对我们的探测报文不理不睬。此时 RTT 判据永远命不中（偶尔命中的那次也只是撞上了
   * 它自己的周期广播，间隔往往超过判据上限），「信任分」永远攒不起来，
   * 快速判死形同虚设，于是又退回 `DEVICE_OFFLINE_MS` 的 8s 兜底 ——
   * 这正是真机实测「对方关掉 App 十秒左右才显示下线」的原因。
   * （上一版还把信任阈值设成「连续命中 3 次」，在本机与 1.35 平板之间**从未**达成过。）
   *
   * ## 换成 TCP：连得上就是在，连不上就是不在
   *
   * 我们和对端之间本来就有一条 TCP 通道（文件端口 5856）。向它发起一次连接：
   *   · 连接成功          → 设备活着（服务在监听）
   *   · 立即 RST          → 主机活着但服务已停 → 对我们等同于下线
   *   · SYN 超时 / 不可达 → 设备不在 / 已关机 / 不在同一网段
   * 这是**应用层无法回避**的事实，不依赖对端是否"愿意回 UDP 探活"。
   * 局域网里 RST 往往几毫秒就回来，所以两次复核失败 ≈ 设备消失后 **2~3s** 判死。
   *
   * 连接建立后**不发任何字节**就关闭：对端的 accept 循环读到 EOF 自行收尾，
   * 不会被误当成一次协议握手（发了魔数才会被引到私有协议分支上）。
   */
  /** 一次 TCP 复核的连接超时（毫秒）。局域网 RST 是毫秒级，1s 已是极大方 */
  static readonly DEVICE_TCP_PROBE_TIMEOUT_MS: number = 1000;
  /** 同一台设备两次 TCP 复核的最小间隔（毫秒），防止巡检每秒都去 connect */
  static readonly DEVICE_TCP_PROBE_COOLDOWN_MS: number = 700;
  /**
   * 连续几次 TCP 复核失败才判死。
   *
   * 取 2 而不是 1：单次连接失败可能只是对端瞬间 backlog 满 / 网络抖动，
   * 而误判的代价（活着的设备从列表消失、下一轮广播又冒出来 = 列表闪烁）
   * 比晚一两秒更难受。两次连续失败已把误判概率压到可忽略。
   */
  static readonly DEVICE_TCP_PROBE_MISS_LIMIT: number = 2;
  /**
   * 「验证性复核」的最大连续失败次数（安全阀）。
   *
   * **只有 TCP 复核成功过的设备**才允许用「复核失败」判死。
   * 否则万一某台设备的文件端口本来就不可连（防火墙 / 未开共享 / 端口被改），
   * 我们就会在它明明在线时反复把它判死 → 列表持续闪烁，比"慢"更糟。
   * 验证不通时只累计失败、不判死，累计到此值后不再反复 connect，退回 8s 兜底。
   */
  static readonly DEVICE_TCP_VERIFY_MAX_MISS: number = 3;

  /** 接收文件默认落盘目录（应用沙箱内） */
  static DEFAULT_FILE_SAVE_PATH: string = '/LANShare/';
  /** 用户可见的共享目录（通过 Download 目录权限授权后映射） */
  static fileSavePath: string = LanConfig.DEFAULT_FILE_SAVE_PATH;

  static userName: string = '';
  static uniqueUuid: string = '';
  static saveMessage: boolean = true;
  static saveToGallery: boolean = true;
  static webService: boolean = true;
  static saveFilesCategory: boolean = true;
  static saveLog: boolean = false;

  static udpPort: number = LanConfig.DEFAULT_UDP_PORT;
  static fileServerPort: number = LanConfig.DEFAULT_FILE_SERVER_PORT;
  static httpPort: number = LanConfig.DEFAULT_HTTP_PORT;

  // ---------- 文件分类（平移自 Config.fileTypes） ----------
  /** [分类名, 扩展名（逗号分隔）] —— 用于接收文件时按类型落盘 */
  static readonly FILE_TYPES: string[][] = [
    ['图片', 'jpg,jpeg,png,gif,bmp,webp,heic,svg'],
    ['视频', 'mp4,avi,mkv,mov,wmv,flv,rmvb,3gp,webm'],
    ['音频', 'mp3,wav,flac,aac,ogg,m4a,ape,wma'],
    ['文档', 'txt,pdf,doc,docx,xls,xlsx,ppt,pptx,md,csv'],
    ['压缩包', 'zip,rar,7z,tar,gz,bz2,iso'],
    ['程序', 'apk,exe,msi,deb,rpm,sh,bat'],
    ['代码', 'java,kt,ets,ts,js,html,css,json,xml,py,c,cpp,h,go,rs']
  ];

  /** 目录展示名（Android: Config.FOLDER = "文件夹"） */
  static readonly FOLDER_NAME: string = '文件夹';

  // ---------- 前台运行模式（vivi 2026-09-30 决策） ----------
  /**
   * 应用退到后台时是否自动停止共享。
   *
   * 本项目不做后台保活，退到后台后系统会冻结进程、TCP 监听事实上已不可用。
   * 因此默认 `true`：退后台即主动停服，好处是**端口被干净释放、连接正常关闭**
   * （浏览器会立刻看到连接中断，而不是挂在那里等超时）。
   *
   * 若某天想验证"短暂切后台是否还能撑一会儿"，把这里改成 false 即可。
   */
  static AUTO_STOP_ON_BACKGROUND: boolean = true;

  /**
   * 共享期间是否保持屏幕常亮。
   *
   * 这是「不做后台保活」前提下最关键的一步：用户把页面停在屏上等别人连过来，
   * 唯一会打断的是息屏。等价于 Android 侧的 WakeLock。
   */
  static KEEP_SCREEN_ON_WHILE_SHARING: boolean = true;
}
