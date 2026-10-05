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
  /** 数据协议版本。Android: LVersion.DATA_VERSION_4 */
  static readonly DATA_VERSION: number = 4;

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
  /** 设备扫描/心跳间隔（秒）。Android: Config.SCANN_TIME */
  static readonly SCAN_TIME: number = 5;
  /** 设备离线判定超时（毫秒）。Android 侧由 setTime 与 System.currentTimeMillis 比较得出 */
  static readonly DEVICE_OFFLINE_MS: number = 15000;

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
