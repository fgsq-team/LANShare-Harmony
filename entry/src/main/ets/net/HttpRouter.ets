/**
 * HTTP 路由 —— 替代 app/src/main/java/com/fgsqw/lanshare/web/LHttpServer.java
 *
 * ## 路由表（与原 LHttpServer 一一对应）
 * | 路径 | 原实现 | 鸿蒙侧 |
 * |---|---|---|
 * | GET /                    | 返回 assets/web/lanshare.html          | rawfile/web/lanshare.html ✅ 复用 |
 * | GET /css/* /js/* /images/* | 静态资源                             | rawfile/web/** ✅ 复用 |
 * | GET /favicon.ico         | 静态资源                                | rawfile 内无此文件，返回 204 |
 * | GET /files?dir=          | 列目录，返回 JSON                       | 沙箱 + 用户授权目录 |
 * | GET /file/*              | 单文件下载，支持 Range                  | 同左 |
 * | GET /media               | 媒体（图片/视频）列表                    | 待 B2 批次 |
 * | GET /wss                 | WebSocket 升级                          | WsProtocol |
 * | POST /checkPass          | 校验网页端访问密码                       | preferences |
 * | POST /initConfig         | 网页端拉取初始配置                       | 同左 |
 * | POST /updateWebName      | 网页端修改设备名                         | 同左 |
 * | POST /uploadFile         | 网页端上传单个文件                       | 待 B2 批次 |
 * | POST /chatUploadFile     | 网页端聊天上传                           | 待 B2 批次 |
 * | GET /apps, /appicon      | 已安装应用列表 + 图标                    | ⛔ 鸿蒙不开放，见下 |
 * | GET /apkfile/*           | 下载已安装应用的 APK                     | ⛔ 鸿蒙不开放 |
 * | GET /drawable            | 读取应用资源图                           | ⛔ 无等价能力 |
 * | /downloadZipFile, /compressFiles, /compressMedias | 打包下载      | ✅ compressFiles/downloadZipFile 已实现；compressMedias 因无媒体库不支持 |
 *
 * ## ⛔ 能力缺失（鸿蒙平台限制，不是实现问题）
 * 「已安装应用列表 / 分享 APK」这一整块功能在鸿蒙上**无法保留**：
 *   - 三方应用不能枚举其它已安装应用（bundleManager 需要 ohos.permission.GET_BUNDLE_INFO_PRIVILEGED，
 *     该权限仅对系统应用开放）
 *   - 也无法读取其它应用的安装包文件（沙箱隔离）
 * 产品上需要把这个入口去掉，或改为「分享本应用自己的 HAP 安装包」。
 * 详见 docs/迁移对照表.md 的「能力缺失清单」。
 */
import { util } from '@kit.ArkTS';
import { fileIo } from '@kit.CoreFileKit';
import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { BusinessError, zlib } from '@kit.BasicServicesKit';
import {
  ContentTypes, HttpRequest, HttpResponse, HttpProtocol, FileStreamSpec, ParseState
} from './HttpProtocol';
import { TcpChannel } from './NativeSocket';
import { WsProtocol } from './WsProtocol';
import { Log } from '../core/Logger';
import { LanConfig } from '../core/LanConfig';
import { JsonNode, JsonParseResult, MiniJson } from '../core/MiniJson';
import { WebClient, WebClientStore } from '../service/WebClientStore';
import { FileStorage } from '../service/FileStorage';
import { MultipartFile, MultipartStream } from '../service/MultipartStream';

const TAG: string = 'HttpRouter';

/** 网页端设置（与原 App 共用同一个 preferences 文件） */
const PREF_NAME: string = 'lanshare_web';
/** 对应原 Config.WEB_OPEN：开启后新客户端无需手机端确认 */
const PREF_WEB_OPEN: string = 'webOpen';

/** 网页客户端的随机名后缀长度，与原 mUtil.generateRandomString(6) 一致 */
const RAND_NAME_LEN: number = 6;

/**
 * 上传整体超时（毫秒）。
 *
 * 原实现直接复用 `readExactly` 的 60 秒 —— 一个 577 MB 的文件在 WiFi 上
 * 根本传不完，到点必然断，用户看到的就是「进度跑到一半然后失败」。
 * 这里放宽到 10 分钟，并且超时时把「已收到多少字节」带回给用户，
 * 让人知道是断了还是根本没在传。
 */
const UPLOAD_TIMEOUT_MS: number = 10 * 60 * 1000;

/** 流式读取的单块上限。取 256 KiB：够大能跑满吞吐，够小不会让内存抖动 */
/**
 * ★★ 5.1.35：块大小 256 KiB → **1 MiB − 12**（对齐 `V5Transfer.CHUNK`）。
 *
 * 【依据：对照实验（同一个「收大文件」场景，结果相反）】
 *    `V5Transfer`（私有协议，16 并发分片）：块 **1 MiB − 12** ⇒ 成功（32 MB/s，0 条 vsync 超时）
 *    `HttpRouter`（网页上传，单连接）      ：块 **256 KiB**    ⇒ 崩（THREAD_BLOCK_6S）
 *  唯一的显著差异就是块大小 —— 让帧预算反而不重要
 *  （V5Transfer 用 12ms、本文件用 24ms，前者更密却更稳）。
 *
 * 【为什么块大小会决定生死】
 *  对端发得比我们处理得快时，`readSome` 会**立刻**返回 ⇒ `await` 立即 resolve
 *  ⇒ 这是 **microtask**，**优先于宏任务（vsync / 定时器）**
 *  ⇒ 单连接 + 数据充足时，主线程会被这条 microtask 链几乎独占，
 *    渲染帧与让帧的定时器都排不进去（实测 `[HB]` 事件循环被推迟到 999ms~6325ms）。
 *  块变大 ⇒ **每单位数据的 await / 分配 / 循环轮数按比例减少**：
 *    每 16 MiB 的轮数 64 → 16，`hold` 的 concat/slice 与临时数组分配同步降到 1/4。
 *
 * ⚠️ 副作用：单块的同步工作量涨到 4 倍（`indexOfSeq` 扫描 + slice 拷贝），
 *    单次主线程占用会变长。总占用不变、次数减 4 倍 —— 孰优待本轮实测裁决。
 */
const UPLOAD_CHUNK: number = 1024 * 1024 - 12;

/**
 * 上传进度上报的最小间隔。
 *
 * ⚠️ 不上报节流的话，每 256 KiB 就要 emit 一次快照 → UI 每帧重建整个页面，
 * 表现就是「上传期间点什么都没反应」。200ms 上限 ≈ 每秒最多 5 次刷新，
 * 人眼看着是连续的，UI 也不会被刷死。
 */
/**
 * ★ 5.1.24：200 → **1000**（进度上报的最小时间间隔）。
 *   实测网页上传只有 17MB/s 而 V5 接收有 50MB/s，两者差别在于
 *   网页上传每次上报都 `emit()` ⇒ ArkUI 重建整页（`LanService.onWebUploadProgress`）。
 *   1000ms + 4MB 双条件 ⇒ 646MB 全程只上报约 160 次（原来约 2500 次）。
 */
const UPLOAD_PROGRESS_MIN_MS: number = 1000;
/** 相邻两次上报之间至少再收这么多字节（防止小文件时刷太密） */
/**
 * ★ 5.1.24：256KB → **4MB**（进度上报的最小字节间隔）。
 *   与 `UPLOAD_PROGRESS_MIN_MS` 是**与**关系，两者任一满足即上报；
 *   放宽后重建频率降 16 倍。终态上报不受此限制（`notifyUploadEnd` 走立即版）。
 */
const UPLOAD_PROGRESS_MIN_BYTES: number = 4 * 1024 * 1024;

/**
 * 每收几块就主动让出一次主线程（256 KiB/块）。
 *
 * ArkTS 的 socket 回调跑在 UI 线程上，而上传循环是「read → 扫描 boundary → 同步写盘」
 * 的**纯同步**工作链：只要对端一直在发，这个 while 就一直占着线程，
 * 期间 ArkUI 拿不到帧时间，按钮点了没有任何反馈（vivi 2026-09-30 反馈
 * 「发送途中鸿蒙端按钮没反应」的根因）。
 *
 * ★★ 5.1.25：**8 → 32**（每 2 MiB 让帧 → 每 8 MiB 让帧）。
 *
 * 【为什么必须调大 —— 这是网页上传卡死+闪退的真凶】
 * `[UP]` 分段计时（真机 646 MB 上传，30 条采样）：
 *     每 16 MiB 固定耗时 ~890 ms，其中
 *       readSome(await 等数据) =   0 ms (0.0%)   ← 数据早就在缓冲里
 *       mp.feed(解析+落盘)    =  14 ms (1.6%)   ← 2585 次 writeSync 也不是瓶颈
 *       其余(other)            = 876 ms (98.4%)  ← ★ 就是它
 * 循环体里除这两项之外只剩「进度上报 + yieldFrame + if(!mp.ok)」。
 * 5.1.24 已把进度上报从 200ms/256KB 放宽到 1000ms/4KB（频率降 16 倍），
 * **实测速度一点没变（16.5 → 16.7 MB/s）** ⇒ 进度上报**不是**瓶颈，已排除。
 * ⇒ 876 ms 只能是 **8 次 `yieldFrame`**，即**每次让帧代价约 110 ms**。
 *
 * 【110 ms 从哪来】`setTimeout(0)` 让出主线程后，ArkUI 要**重建整个页面**
 * （消息列表 / 文件网格 / 气泡），单帧 110 ms。这不是网络慢，是 UI 重建慢。
 * 每 2 MiB 付一次 110 ms ⇒ 天花板就只有 ~17 MB/s，与实测完全吻合。
 *
 * 【为什么会闪退】实测 `ui_log` 里**同时有 6 个连接**在上传（浏览器并发开连接），
 * 6 条 `serveUpload` 的让帧帧**排在同一个主线程**上 ⇒ 6 × 110 ms 连续占用
 * ⇒ XCollie 判定 THREAD_BLOCK_6S ⇒ 系统 SIGKILL 强杀。
 * ★ 两次上传都**精确停在同一块**，正是这个「每 N MiB 一次的系统性停顿」被撞上。
 *
 * 【为什么 5.1.12 看着没事】它也是这个 8 —— 但所有历史日志里
 * 「网页上传完成」**一次记录都没有** ⇒ 这个场景从未被测过，不是「没事」而是从没试过。
 *
 * 【调大后的收益】让帧频率降 4 倍 ⇒ 每 16 MiB 的让帧开销 876 → 219 ms
 * ⇒ 预期吞吐 ~17 → 50+ MB/s（与 V5 接收的 50 MB/s 同一量级）。
 * 32 块（8 MiB）让一次，UI 最坏卡顿约 0.5 秒，仍在「可感知但不失控」的范围内。
 */
const UPLOAD_YIELD_EVERY: number = 32;

/**
 * ★★ 5.1.29：让帧判据从「块数」改为「**时间**」。
 *
 * 【为什么块数不行】块数 != 时间。千兆网下 256KB 只要 ~2ms，
 *   32 块 = 64ms 连续占用主线程；而 5.1.26 真机实测 hblag 稳态 400~500ms、
 *   峰值 **199950ms** —— 主线程被连续占用 28 秒后进程被系统 SIGKILL。
 *   ⇒ 判据必须是「**距上次让帧过了多少毫秒**」，与网速无关。
 *
 * 【取值】24ms —— 保证每秒让出 ~40 次，单次连续占用被硬限制在 24ms 量级。
 *
 * 【⚠️ 2026-10-03 修正：此前本段写「真正的病因是消息队列被任务塞满、
 *   看门狗判活任务饿死」—— 该结论已被 5.1.36~5.1.38 实测推翻】
 *   真凶是 `MultipartStream.indexOfSeq` 对 1 MiB 块逐字节搜分隔符
 *   ≈ 53ms/块，6 条并发连接争抢主线程把渲染帧饿死。
 *   判据：「让帧不是病根」—— 5.1.26~5.1.37 十二轮调它/块大小/同步异步全无效。
 *   本常量保留仍有价值（限制单次连续占用），但别再指望靠它治崩溃。
 *   ⇒ 先量「单次主线程占用」，再决定要不要让帧。
 */
const UPLOAD_YIELD_MS: number = 24;

/**
 * ★★ 5.1.28：单次 `readSome` 的超时（毫秒）。
 *
 * 【为什么不能用 `remain`（= `UPLOAD_TIMEOUT_MS` - 已用时间，最大 10 分钟）】
 *   `TcpChannel.waitForData(timeoutMs)` 的实现是
 *   `setTimeout(() => {...}, timeoutMs)` ——
 *   传分钟级就等于**每一轮循环都挂一个超长定时器**，
 *   只因为「数据通常先到、`fire()` 提前 clear」才没出事。
 *   代价是定时器队列被反复撑大：
 *     640MB / 256KB = 2560 轮 × 6 个并发连接 ≈ **1.5 万次长定时器挂/清**。
 *   实测（5.1.27-ablate 真机 646MB）：
 *     `hblag` 从 blk#2752 的 33ms **单调递增**到 blk#3456 的 **7338ms**
 *   ⇒ 事件循环的定时器被系统性推迟，且越到后面越慢。
 *
 * 【30s 是否安全】单块 256KB 在局域网内 30s 读不到 ⇒ 链路已断，
 *   交给外层的 `UPLOAD_TIMEOUT_MS`（10 分钟总超时）判定即可，
 *   不会误杀慢速但正常的连接。
 */
const UPLOAD_READ_TIMEOUT_MS: number = 30 * 1000;

/**
 * 每发几块就让出一次主线程（下载方向）。
 *
 * 块是 8 MiB，比上传的 256 KiB 大得多，读一块的同步 IO 更重，
 * 所以让出得更勤一点（每块一次），保证「发给网页」期间 App 还能点得动。
 */
const DOWNLOAD_YIELD_EVERY: number = 1;

/**
 * 打包下载（网页端「下载文件」按钮）的临时目录名，挂在 `cacheDir` 下。
 * 用 cacheDir 是因为它本来就是"可被系统回收的临时区"，且已在 resolveSafePath 白名单里。
 */
const ZIP_TMP_DIR: string = 'webzip';
/**
 * 临时 zip 的保留时长。
 * 下载走的是「先打包 → 浏览器再发第二个请求取文件」，两步之间没有回调告诉我们取没取走，
 * 所以只能靠时间回收。30 分钟足够慢的浏览器下完，又不会让缓存无限增长。
 */
const ZIP_TMP_KEEP_MS: number = 30 * 60 * 1000;

export class HttpRouter {
  private ctx: common.UIAbilityContext | null = null;
  /** 网页客户端白名单（替代原 db/TokenDBUtil） */
  private clients: WebClientStore = new WebClientStore();
  /** 对应 Config.WEB_OPEN。true = 新客户端自动放行 */
  private webOpen: boolean = false;
  /** 有待授权的新客户端时回调（LanService 接到后展示到 UI 并落日志） */
  private newClientSink: ((c: WebClient) => void) | null = null;
  /** 连接统计，用于实况窗 */
  private servedRequests: number = 0;
  /**
   * 落盘存储。由 LanService 注入 —— 网页上传的文件必须和「对方发过来」的文件
   * 落在同一个根目录，否则用户在「已接收文件」卡片里看不到刚上传的东西。
   */
  private storage: FileStorage | null = null;

  /**
   * 上传进度回调。签名 `(已收字节, 总字节, 当前文件名)`。
   *
   * 总字节为 -1 表示对端没给 Content-Length（分块传输），
   * 这时调用方只能显示已收量，别去算百分比。
   */
  private uploadProgressSink: ((received: number, total: number, name: string) => void) | null = null;

  // ★★ 5.1.26（**纯诊断，可随时整段删掉**）：事件循环心跳。
  //
  // 【要回答的问题】XCollie 报 THREAD_BLOCK_6S，但它判「无响应」的依据是
  //   「主线程连续 6 秒没有处理事件循环」。而实测 `[UP]` 日志一直在打、
  //   打印在**主线程 tid** 上、直到 SIGKILL 前 0.55 秒 —— 两者矛盾。
  //   纯推理已连错五轮（await 次数 / concat O(n²) / writeSync / UI 重建 / 让帧），
  //   本版用**独立测量**裁决：心跳定时器自己被推迟多久，就是主线程被占多久。
  //
  // 【判读】
  //   hblag 始终 < 100ms  ⇒ 事件循环通畅 ⇒ THREAD_BLOCK 是**误报**，真凶另有其人
  //   hblag 偶发 > 3000ms ⇒ 那一瞬就是真凶，`[UP]` 行会把它记下来
  //
  // ⚠️ **只在延迟 > HEARTBEAT_ALERT_MS 时才打日志**。250ms 一次的心跳若每次都打，
  //   就是 250 次/秒的字符串拼接 + 写日志 —— 诊断本身会变成新瓶颈
  //   （5.0.68 的教训：诊断日志绝不能放在高频路径上）。
  private static readonly HEARTBEAT_MS: number = 250;
  private static readonly HEARTBEAT_ALERT_MS: number = 500;
  private hbTimer: number = -1;
  private hbLast: number = 0;
  private hbWorst: number = 0;
  private startHeartbeat(): void {
    if (this.hbTimer >= 0) {
      return;
    }
    this.hbLast = Date.now();
    this.hbTimer = setInterval(() => {
      const lag: number = Date.now() - this.hbLast;
      this.hbLast = Date.now();
      if (lag > HttpRouter.HEARTBEAT_ALERT_MS) {
        this.hbWorst = lag > this.hbWorst ? lag : this.hbWorst;
        console.warn('[HB] 事件循环被推迟 ' + lag + 'ms，历史最差 ' + this.hbWorst + 'ms');
      }
    }, HttpRouter.HEARTBEAT_MS);
  }

  private stopHeartbeat(): void {
    if (this.hbTimer >= 0) {
      clearInterval(this.hbTimer);
      this.hbTimer = -1;
    }
  }

  /** 最近一次心跳延迟（ms）—— `[UP]` 打点会附读 */
  hbLag(): number {
    return Date.now() - this.hbLast;
  }
  /**
   * 上传结束回调。`ok=false` 时 `error` 是给人看的原因。
   *
   * ⚠️ 必须同时覆盖**成功和失败**两条路：只回调成功的话，
   * 上传中途断线时 App 上的进度浮层会永远停在 43% 不消失。
   */
  private uploadEndSink:
    ((ok: boolean, names: string[], totalBytes: number, error: string) => void) | null = null;

  /**
   * 下载进度回调（本机 -> 浏览器）。签名 `(已发字节, 总字节, 展示名)`。
   *
   * 与上传进度对称：网页端「下载文件」/ 手机「发到网页端」都是浏览器来取字节，
   * 字节是从本机**发出去**的，所以叫 download（对浏览器而言是下载）。
   *
   * `total < 0` 表示这一阶段没有可计量的总量（例如正在打包 zip），
   * 调用方此时应把 `name` 当整句文案显示，别去算百分比。
   */
  private downloadProgressSink: ((sent: number, total: number, name: string) => void) | null = null;
  /** 下载结束回调：`ok=false` 时 `error` 是给人看的原因 */
  private downloadEndSink:
    ((ok: boolean, name: string, totalBytes: number, error: string) => void) | null = null;

  setStorage(storage: FileStorage): void {
    this.storage = storage;
  }

  /** 注册上传进度回调（LanService 接到后写进快照 → 应用内浮层显示） */
  setOnUploadProgress(cb: ((received: number, total: number, name: string) => void) | null): void {
    this.uploadProgressSink = cb;
  }

  /** 注册上传结束回调（成功 / 失败都会调） */
  setOnUploadEnd(
    cb: ((ok: boolean, names: string[], totalBytes: number, error: string) => void) | null
  ): void {
    this.uploadEndSink = cb;
  }

  /**
   * 注册下载进度回调（本机 -> 浏览器：网页端下载文件 / 手机发到网页端）。
   *
   * 不接的话：手机把文件推给网页时本机一点反馈都没有，用户不知道是没开始
   * 还是卡住了（vivi 2026-10-01 反馈「鸿蒙发送给网页没有进度条」）。
   */
  setOnDownloadProgress(cb: ((sent: number, total: number, name: string) => void) | null): void {
    this.downloadProgressSink = cb;
  }

  /** 注册下载结束回调（成功 / 失败都会调，保证浮层一定被收掉） */
  setOnDownloadEnd(
    cb: ((ok: boolean, name: string, totalBytes: number, error: string) => void) | null
  ): void {
    this.downloadEndSink = cb;
  }

  /** 上传目标根目录。storage 未注入时退回网页根目录，保证功能不哑火 */
  private uploadDirOf(fileName: string): string {
    if (this.storage !== null) {
      return this.storage.categoryDir(fileName);
    }
    const dir: string = this.rootPath;
    FileStorage.mkdirs(dir);
    return dir;
  }

  setContext(ctx: common.UIAbilityContext): void {
    this.ctx = ctx;
  }

  /** 注入白名单存储（由 LanService 创建并保证已 init） */
  setClientStore(store: WebClientStore): void {
    this.clients = store;
  }

  /** 网页访问是否需要手机端确认。false = 自动放行 */
  setWebOpen(open: boolean): void {
    this.webOpen = open;
  }

  /** 当前「网页免确认」状态，供 UI 显示开关 */
  get isWebOpen(): boolean {
    return this.webOpen;
  }

  setOnNewClient(fn: (c: WebClient) => void): void {
    this.newClientSink = fn;
  }

  async initPrefs(ctx: common.UIAbilityContext): Promise<void> {
    this.ctx = ctx;
    try {
      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_NAME);
      this.webOpen = await store.get(PREF_WEB_OPEN, false) as boolean;
      // ⚠️ 不要在这里读 userName 并赋默认值：
      // 设备名由 LanService.loadDeviceNamePref 从独立的 lanshare_cfg 偏好读，
      // 没设置时回退到 deviceInfo.marketName（设备市场名）。
      // 之前这里用 store.get('userName', 'LANShare') 会把默认名钉死成字面量 "LANShare"，
      // 而且它跑在 loadDeviceNamePref 之前，等于把"回退市场名"的逻辑覆盖掉 ——
      // 于是冷启动默认名永远是 LANShare（vivi 2026-09-30 反馈）。
    } catch (e) {
      Log.w(TAG, '读取网页端配置失败，使用默认值');
    }
  }

  /** 「网页」根目录 —— 网页端 hash 路由的起始目录，也必须在 resolveSafePath 允许范围内 */
  private get rootPath(): string {
    if (this.ctx === null) {
      return '/';
    }
    const dir: string = `${this.ctx.filesDir}/LANShare`;
    try {
      if (!fileIo.accessSync(dir)) {
        fileIo.mkdirSync(dir, true);
      }
    } catch (e) {
      // ignore
    }
    return dir;
  }

  get requestCount(): number {
    return this.servedRequests;
  }

  /**
   * 主入口：从已分流的通道上读请求、路由、写响应。
   * 支持 HTTP/1.1 keep-alive（同一连接处理多个请求）。
   */
  async serve(channel: TcpChannel, head: Uint8Array): Promise<void> {
    // ★★ 5.1.26（纯诊断）：连接进来就开心跳。5.1.12 也复现 ⇒ 不是我的改动引入。
    this.startHeartbeat();
    // 把判定协议时读走的 4 字节拼回缓冲区
    channel.unshift(head);

    let buffer: Uint8Array = new Uint8Array(8192);
    let used: number = 0;

    while (!channel.isClosed) {
      const req: HttpRequest = new HttpRequest();
      req.remoteIp = channel.remoteIp;
      req.remotePort = channel.remotePort;

      // ---- 读够请求头 ----
      // ParseState 是用 static readonly 常量实现的伪枚举（不是 ArkTS enum），
      // 所以它的静态成员类型就是 number，变量不能声明成 ParseState
      //
      // ★★ 5.1.22：**由「逐字节读」改为「批量读」**（vivi 12:02 修「上传大文件 ⇒ 手机卡住后闪退」）
      //   原实现每字节一次 `await readExactly(1, …)`：一个 HTTP 头 200~500 字节
      //   ⇒ **200~500 次串行 await**；浏览器上传并发开多条连接（本轮实测 5 条同时到）
      //   ⇒ 2500 次串行 await 全排在**主线程**；ArkTS 的 socket 回调与文件操作同在主线程
      //   ⇒ 主线程占满 ⇒ UI 无响应 ⇒ 系统强杀（表现为「卡住后闪退」）。
      //   现在一次读满当前缓冲，**一个头 1~2 次 await**，主线程压力降两个数量级。
      //
      // ⚠️ 语义完全不变：`readSome` 可能一次带回「header + body 前缀」，
      //   多出来的字节仍由下面的 `bodyInBuffer` 路径处理（`:300` 附近那段），
      //   所以**协议解析、body 处理、keep-alive 行为都不变**。
      let state: number = ParseState.NEED_MORE;
      while (state === ParseState.NEED_MORE) {
        if (used >= buffer.length) {
          buffer = HttpRouter.grow(buffer);
        }
        // 一次要满「缓冲剩余空间」，但至少 1 字节
        const want: number = buffer.length - used;
        const chunk: Uint8Array | null = await channel.readSome(want, 15000);
        if (chunk === null || chunk.length === 0) {
          return; // 客户端关闭或超时
        }
        buffer.set(chunk, used);
        used += chunk.length;
        state = HttpProtocol.parseHeader(buffer, used, req);
      }
      if (state === ParseState.INVALID) {
        await channel.send(HttpResponse.text(400, 'Bad Request').encodeHead());
        return;
      }

      // 头部之后可能跟了 body，先取出已缓冲部分
      const headerEnd: number = HttpProtocol.findHeaderEnd(buffer, used);
      let bodyInBuffer: Uint8Array = used > headerEnd
        ? buffer.slice(headerEnd, used)
        : new Uint8Array(0);
      const bodyLen: number = HttpProtocol.bodyLength(req);

      // ---- chunked 请求体：显式拒绝并关连接 ----
      // bodyLength() 用 -1 表示 `Transfer-Encoding: chunked`。本项目所有真实客户端
      // （浏览器 XHR / 原生 App）都会带 Content-Length，流里不会出现 chunked。
      // 但**必须显式拒绝**：若放着不管，没被读走的 chunked body 会被当成
      // 下一条请求的头部去解析，表现为莫名其妙的 400 或串包 —— 比直接报错难查得多。
      if (bodyLen < 0) {
        const r411: HttpResponse = HttpResponse.text(411, '暂不支持 chunked 请求体，请携带 Content-Length');
        r411.keepAlive = false;
        await channel.send(r411.encodeHead());
        if (r411.body.length > 0) {
          await channel.send(r411.body);
        }
        return;
      }

      // ---- 大 body：交给流式处理器，绝不整包读进内存 ----
      // /uploadFile 与 /chatUploadFile 的 body 可能几百 MB，必须边收边落盘。
      // 放在 route() 之前是因为流式处理器需要「继续从通道读」的控制权，
      // 而 route() 拿到的 req.body 早已被读满、内容全在内存里了。
      if (HttpRouter.isStreamingUpload(req)) {
        const tUp: number = Date.now();
        const up: HttpResponse = await this.serveUpload(req, channel, bodyInBuffer, bodyLen);
        up.keepAlive = false; // 上传连接不复用
        await channel.send(up.encodeHead());
        if (up.body.length > 0) {
          await channel.send(up.body);
        }
        Log.i(TAG, `${req.method} ${req.path} ${req.remoteIp} -> ${up.status} ${Date.now() - tUp}ms`);
        return;
      }

      if (bodyLen > 0) {
        if (bodyInBuffer.length < bodyLen) {
          const rest: Uint8Array | null = await channel.readExactly(bodyLen - bodyInBuffer.length, 60000);
          if (rest === null) {
            return;
          }
          bodyInBuffer = HttpRouter.concat(bodyInBuffer, rest);
        }
        req.body = bodyInBuffer.slice(0, bodyLen);
      } else if (bodyInBuffer.length > 0) {
        req.body = bodyInBuffer;
      }

      this.servedRequests += 1;

      // ---- 路由 ----
      const tRoute: number = Date.now();
      const response: HttpResponse | null = await this.route(req, channel);
      if (response === null) {
        return; // 已被其它处理器接管（如 WebSocket 升级）
      }

      await channel.send(response.encodeHead());
      if (response.body.length > 0) {
        await channel.send(response.body);
      }
      // 流式文件体。这一路是「本机 -> 浏览器」的全部字节出口：
      // 网页端下载文件、手机「发到网页端」都走这里，所以进度在这里上报，
      // 覆盖 `/file/<name>` 和 `/downloadZipFile` 两个入口，不用各写一遍。
      if (response.streamFile !== null) {
        // 进度与结束都在 sendFileRange 里上报（那里才有"发了多少"的真实计数），
        // 这里只管连接结果：失败就不再复用连接。
        const ok: boolean = await this.sendFileRange(channel, response.streamFile);
        if (!ok) {
          return;
        }
      }

      // 每个请求都留一行。网页端出问题时的第一现场就在这里 ——
      // 哪个接口慢、返回什么状态，一眼可见，不用靠猜。
      const cost: number = Date.now() - tRoute;
      if (cost >= 1000) {
        Log.w(TAG, `${req.method} ${req.path} ${req.remoteIp} -> ${response.status} `
          + `${response.body.length}B ${cost}ms  ← 慢`);
      } else {
        Log.d(TAG, `${req.method} ${req.path} ${req.remoteIp} -> ${response.status} `
          + `${response.body.length}B ${cost}ms`);
      }

      // ---- 复用连接 ----
      const conn: string = req.header('connection').toLowerCase();
      const wantClose: boolean = conn.includes('close') ||
        (req.version === 'HTTP/1.0' && !conn.includes('keep-alive'));
      if (wantClose) {
        // 把本次多读进来的字节留到下次不可能了，直接关
        return;
      }
      // 缓冲区里若还有剩余字节（下一条请求的头部），保留到下一轮
      if (used > headerEnd + bodyLen) {
        buffer = buffer.slice(headerEnd + bodyLen, used);
        used = buffer.length;
      } else {
        buffer = new Uint8Array(8192);
        used = 0;
      }
    }
  }

  /** 路由分发。返回 null 表示连接已被接管，调用方不要再写响应 */
  private async route(req: HttpRequest, channel: TcpChannel): Promise<HttpResponse | null> {
    const path: string = req.path;

    if (req.method === 'GET' || req.method === 'HEAD') {
      if (path === '/' || path === '/index.html') {
        return this.serveRawFile('web/lanshare.html');
      }
      if (path.startsWith('/css/') || path.startsWith('/js/') || path.startsWith('/images/')) {
        // 静态资源直接映射到 rawfile/web 下，路径穿越已由 urlDecodePath 归一化拦截
        return this.serveRawFile(`web${path}`);
      }
      if (path === '/favicon.ico') {
        // 原 assets/web 里没有 favicon，用 204 让浏览器停止重试
        return HttpResponse.of(204);
      }
      if (path === '/files') {
        // 网页端实际用的是 POST /files（见 js/lanshare.min.js 的 openDir）。
        // GET 保留，便于 curl / 调试。
        return this.listFiles(req);
      }
      if (path.startsWith('/file/')) {
        return this.downloadFile(req, path.substring('/file/'.length));
      }
      // ★ 5.1.60「发送到网页端」零落盘：直接流式发送 picker 的授权 URI，
      //   不经过 `saveRoot/网页待下载` 那份副本（详见 stageFile 的注释）。
      if (path.startsWith('/stagefile/')) {
        return this.stageFile(req, path.substring('/stagefile/'.length));
      }
      if (path === '/downloadZipFile') {
        // 网页端「下载文件」按钮的第二步：取走上一步打包好的 zip
        return this.serveZip(req);
      }
      if (path === '/media') {
        return this.listMedia(req);
      }
      if (path === '/wss') {
        return await this.handleWsUpgrade(req, channel);
      }
      if (path.startsWith('/apps') || path.startsWith('/appicon') || path.startsWith('/apkfile/')
        || path === '/drawable') {
        return this.platformUnsupported(path);
      }
      return HttpResponse.notFound(`no route: ${path}`);
    }

    if (req.method === 'POST') {
      if (path === '/checkPass') {
        return this.checkPass(req);
      }
      if (path === '/initConfig') {
        return this.initConfig(req);
      }
      if (path === '/updateWebName') {
        return this.updateWebName(req);
      }
      if (path === '/files') {
        return this.listFiles(req);
      }
      if (path === '/media') {
        return this.listMedia(req);
      }
      if (path === '/apps') {
        return this.appList();
      }
      if (path === '/compressFiles') {
        // 网页端「下载文件」按钮的第一步：把勾选的文件打包成一个 zip
        return await this.compressFiles(req);
      }
      if (path === '/compressMedias') {
        return this.compressMedias();
      }
      if (path === '/uploadFile' || path === '/chatUploadFile') {
        // 正常情况下走不到这里：这两个路径在 serve() 里就被流式处理器拦下了
        // （它们的 body 可能几百 MB，不能「先读满再路由」）。
        // 留这个分支是兜底 —— 万一将来有调用方绕过 serve() 直接进 route()，
        // 也应该给出明确原因，而不是默默掉进 404。
        return HttpResponse.text(500, '上传请求未经过流式处理器（内部路由错误）');
      }
      return HttpResponse.notFound(`no route: ${path}`);
    }

    return HttpResponse.text(405, 'Method Not Allowed');
  }

  // ------------------------------------------------------------------
  // 网页端上传（流式）
  // ------------------------------------------------------------------

  /** 是否为「body 可能极大、必须流式处理」的上传请求 */
  private static isStreamingUpload(req: HttpRequest): boolean {
    if (req.method !== 'POST') {
      return false;
    }
    return req.path === '/uploadFile' || req.path === '/chatUploadFile';
  }

  /**
   * 流式接收 multipart body 并落盘。
   *
   * 契约取自 rawfile/web/js/lanshare.min.js 的 uploadFile() / uploadChatFile()：
   * | 接口 | 参数 | body | 响应约定 |
   * |---|---|---|---|
   * | `POST /uploadFile` | header `token` | multipart/form-data | 2xx 正文直接弹成功提示 |
   * | `POST /chatUploadFile?address=x` | 同上 + 设备地址 | 同上 | 同上 |
   *
   * ⚠️ 响应正文是**给人看的中文句子**，不是 JSON ——
   * 网页拿到后直接 `lightyear.notify(responseText, "success")` 显示。
   * 返回 JSON 的话用户会看到一串花括号，等于没提示。
   *
   * 内存：整个过程只持有 256 KiB 的块，与文件大小无关。
   */
  private async serveUpload(req: HttpRequest, channel: TcpChannel,
                            pre: Uint8Array, bodyLen: number): Promise<HttpResponse> {
    // ★★ 5.1.28：**删掉 5.1.27 的判决性开关，恢复正常进度上报。**
    //   （5.1.27 关掉上报后 vivi 实测「传输完也没有提示」—— 浮层与浏览器提示都没了。）
    //   实验结论已拿到（关 UI 只 +7% 吞吐、但不再闪退）⇒ UI 重建不是吞吐瓶颈。

    const boundary: string = MultipartStream.boundaryOf(req.header('content-type'));
    if (boundary.length === 0) {
      await HttpRouter.drainBody(channel, pre, bodyLen);
      this.notifyUploadEnd(false, [], 0, '请求不是 multipart/form-data');
      return HttpResponse.text(400, '上传失败：请求不是 multipart/form-data（未找到 boundary）');
    }

    const mp: MultipartStream = new MultipartStream(boundary,
      (name: string): string => this.uploadDirOf(name));

    // ---- 1. 先喂已经躺在缓冲区里的那一段 ----
    let got: number = 0;
    if (pre.length > 0) {
      mp.feed(pre);
      got += pre.length;
    }

    // ---- 2. 再按块读剩下的 ----
    const total: number = bodyLen > 0 ? bodyLen : -1;
    const deadline: number = Date.now() + UPLOAD_TIMEOUT_MS;
    let lastReportAt: number = 0;
    let lastReportBytes: number = 0;
    let chunks: number = 0;
    // ★★ 5.1.29：让帧判据改为**时间**（见 `UPLOAD_YIELD_MS`）。
    //   块数判据在千兆网下等于「每 64ms 才让一次」，主线程被连续占满 ⇒ ANR。
    let lastYieldAt: number = Date.now();
    this.notifyUploadProgress(0, total, '');
    while (total < 0 || got < total) {
      const remain: number = deadline - Date.now();
      if (remain <= 0) {
        Log.w(TAG, `上传超时: 已收 ${got} B${total > 0 ? ` / ${total} B` : ''}`);
        mp.finish();
        this.notifyUploadEnd(false, [], got, '上传超时');
        return HttpResponse.serverError(
          `上传超时：已接收 ${HttpRouter.humanSize(got)} 后连接中断，请重试`);
      }
      // ★★ 5.1.28：读超时用**固定短值**而不是 `remain`（分钟级）。
      //   `waitForData` 里 `setTimeout(..., timeoutMs)` —— 传分钟级就意味着
      //   **每一轮都挂一个超长定时器**，只靠 data 事件抢先 resolve 才 clear。
      //   640MB / 256KB = 2560 轮，6 个并发连接 ⇒ 上万个长定时器反复挂/清，
      //   定时器队列调度开销把事件循环拖慢，且**越积越慢**
      //   （与 5.1.27 实测 `hblag` 从 33ms 单调涨到 7338ms 完全吻合）。
      //   这里给一个足够宽裕的固定值：单块 256KB 超过 30s 视为异常。
      const chunk: Uint8Array | null = await channel.readSome(UPLOAD_CHUNK, UPLOAD_READ_TIMEOUT_MS);
      if (chunk === null) {
        break; // 对端关闭或等待超时
      }
      got += chunk.length;
      chunks += 1;
      mp.feed(chunk);
      // 进度上报：节流到「至少间隔 200ms 且至少又收了 256 KiB」。
      // 不节流的话 UI 每块重建一次页面，用户点什么都没反馈。
      // ★★ 5.1.28：恢复无条件上报（节流参数 1000ms/4MB 不变）
      const now: number = Date.now();
      if (now - lastReportAt >= UPLOAD_PROGRESS_MIN_MS &&
        got - lastReportBytes >= UPLOAD_PROGRESS_MIN_BYTES) {
        lastReportAt = now;
        lastReportBytes = got;
        this.notifyUploadProgress(got, total, mp.currentName);
      }

      // ★★ 5.1.29：让帧判据 = **时间**（`UPLOAD_YIELD_MS` = 12ms），不再是块数。
      //
      // 【真机根因】5.1.28 及以前用「每 32 块（8MiB）」，但块数 != 时间：
      //   千兆网下 32 块只要 64ms ⇒ 主线程连续占用被拉长到几百 ms 量级，
      //   实测 hblag 峰值 **199950ms**（主线程冻死 200 秒），
      //   上传到 449MB（距起点 28 秒）时被系统按 ANR SIGKILL。
      //   ⇒ 判据必须与网速无关。
      if (Date.now() - lastYieldAt >= UPLOAD_YIELD_MS) {
        lastYieldAt = Date.now();
        await HttpRouter.yieldFrame();
      }

      if (!mp.ok) {
        break; // 解析已判定坏包，不必继续收
      }
    }

    const saved: MultipartFile[] = mp.finish();
    if (!mp.ok) {
      Log.w(TAG, `上传解析失败: ${mp.error}（已收 ${got} B）`);
      this.notifyUploadEnd(false, [], got, mp.error);
      return HttpResponse.serverError(`上传失败：${mp.error}`);
    }
    if (saved.length === 0) {
      this.notifyUploadEnd(false, [], got, '请求里没有解析到任何文件');
      return HttpResponse.serverError('上传失败：请求里没有解析到任何文件');
    }

    let totalBytes: number = 0;
    const names: string[] = [];
    for (let i = 0; i < saved.length; i++) {
      totalBytes += saved[i].size;
      names.push(saved[i].name);
      Log.i(TAG, `网页上传落盘: ${saved[i].path} (${saved[i].size} B)`);
    }
    Log.i(TAG, `网页上传完成: ${saved.length} 个文件 / ${totalBytes} B（收到 ${got} B）`);
    // 收尾也报一次 100%，否则最后一次节流之后收到的那截不会体现在浮层上
    this.notifyUploadProgress(total > 0 ? total : got, total, names[0]);
    this.notifyUploadEnd(true, names, totalBytes, '');

    if (req.path === '/chatUploadFile') {
      // ⚠️ 语义提醒：/chatUploadFile 的原意是「把这个文件发给 address 指定的设备」。
      // 跨设备转发要走私有协议的 FS 发送流程（B1 批次），目前还没迁移。
      // 这里先把文件落在本机，并在提示里**如实说清楚** ——
      // 假装成功但不转发，用户会以为对方收到了。
      const addr: string = req.queryParam('address');
      return HttpResponse.text(200,
        `已保存到本机：${names.join('、')}（${HttpRouter.humanSize(totalBytes)}）`
        + `。注意：发往 ${addr.length > 0 ? addr : '对端设备'} 的转发功能尚未实现，`
        + `文件先落在本机「已接收文件」中。`);
    }

    const hint: string = this.storage !== null ? '，可在「已接收文件」里另存到本地' : '';
    return HttpResponse.text(200,
      `已上传 ${saved.length} 个文件（${HttpRouter.humanSize(totalBytes)}）：`
      + `${names.join('、')}${hint}`);
  }

  /** 把进度交给外部（未注册回调时是空操作，不影响上传链路） */
  private notifyUploadProgress(received: number, total: number, name: string): void {
    if (this.uploadProgressSink !== null) {
      this.uploadProgressSink(received, total, name);
    }
  }

  /** 把上传结果交给外部（成功与失败都会走，保证浮层一定会被收掉） */
  private notifyUploadEnd(ok: boolean, names: string[], totalBytes: number, error: string): void {
    if (this.uploadEndSink !== null) {
      this.uploadEndSink(ok, names, totalBytes, error);
    }
  }

  /** 下载进度交给外部（未注册回调时是空操作） */
  private notifyDownloadProgress(sent: number, total: number, name: string): void {
    if (this.downloadProgressSink !== null) {
      this.downloadProgressSink(sent, total, name);
    }
  }

  /** 下载结束交给外部（成功与失败都会走） */
  private notifyDownloadEnd(ok: boolean, name: string, totalBytes: number, error: string): void {
    if (this.downloadEndSink !== null) {
      this.downloadEndSink(ok, name, totalBytes, error);
    }
  }

  /**
   * 让出一帧给 UI 线程。
   *
   * ArkTS 是单线程模型：socket 回调里的同步循环不主动让出的话，
   * ArkUI 拿不到帧时间，表现为「上传期间按钮点了没反应」。
   * `setTimeout(0)` 会把后续工作排到下一个事件循环，UI 得以插进来画一帧。
   */
  private static yieldFrame(): Promise<void> {
    // ★★ 5.1.29：**保持单次 `setTimeout`，但让帧判据改成时间**（见 `UPLOAD_YIELD_MS`）。
    //
    // 【为什么原来会 ANR】不是 `setTimeout(0)` 本身不够，而是**调用频率太低**：
    //   旧判据「每 32 块」在千兆网下 = 每 64ms 才让一次，
    //   主线程连续占用被拉长到几百 ms 量级，实测 hblag 峰值 **199950ms**
    //   ⇒ 上传 28 秒后被系统按「前台应用无响应」SIGKILL。
    //   ⇒ 修法在**调用点**（时间判据，12ms 一次），不在这个函数里。
    //
    // ⚠️ 刻意**不加第二跳 `setTimeout`**：那会把每次让帧的成本翻倍，
    //   而 12ms 一次的频率下每秒要 80+ 次 —— 纯粹浪费事件循环。
    //   一次 `setTimeout` 就已经把控制权交还给事件循环，足够让
    //   定时器与渲染插入。
    return new Promise<void>((resolve: () => void) => {
      setTimeout(resolve, 0);
    });
  }

  /**
   * 丢弃请求体。
   * 直接回 400 而不读 body 的话，浏览器还在往上发数据、服务端已经把连接关了，
   * 用户看到的是「连接被重置」而不是我们精心写好的那句错误原因。
   */
  private static async drainBody(channel: TcpChannel, pre: Uint8Array, bodyLen: number): Promise<void> {
    const total: number = bodyLen > 0 ? bodyLen : 0;
    let got: number = pre.length;
    while (got < total) {
      const c: Uint8Array | null =
        await channel.readSome(Math.min(UPLOAD_CHUNK, total - got), 10000);
      if (c === null) {
        return;
      }
      got += c.length;
    }
  }

  /** 字节数转人话，用于给用户的提示文案 */
  private static humanSize(n: number): string {
    if (n < 1024) {
      return `${n} B`;
    }
    if (n < 1024 * 1024) {
      return `${(n / 1024).toFixed(1)} KB`;
    }
    if (n < 1024 * 1024 * 1024) {
      return `${(n / 1024 / 1024).toFixed(1)} MB`;
    }
    return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }

  // ------------------------------------------------------------------
  // 静态资源：rawfile -> HTTP
  // ------------------------------------------------------------------

  /**
   * 从 rawfile 读取并返回。
   * rawfile 是 HAP 内的只读资源目录，原 assets/web 已原样搬入
   * （entry/src/main/resources/rawfile/web/**），所以网页端 UI 100% 复用。
   */
  private async serveRawFile(relPath: string): Promise<HttpResponse> {
    if (this.ctx === null) {
      return HttpResponse.serverError('context 未初始化');
    }
    // 二次防线：rawfile 路径不得含上跳
    if (relPath.includes('..')) {
      return HttpResponse.forbidden();
    }
    try {
      const data: Uint8Array = await this.ctx.resourceManager.getRawFileContent(relPath);
      const resp: HttpResponse = HttpResponse.of(200);
      resp.body = data;
      resp.set('Content-Type', ContentTypes.of(relPath));
      resp.set('Content-Length', `${data.length}`);
      resp.set('Cache-Control', 'no-cache');
      return resp;
    } catch (e) {
      Log.w(TAG, `rawfile 不存在: ${relPath}`);
      return HttpResponse.notFound(`rawfile not found: ${relPath}`);
    }
  }

  // ------------------------------------------------------------------
  // 目录与文件
  // ------------------------------------------------------------------

  /**
   * 文件列表。
   *
   * **请求**：网页端用 `POST /files`，body 是 JSON `{path, isBack}`：
   * `isBack=true` 表示「上一级」，此时 `path` 是当前目录。
   *
   * **响应**（逐字段对齐原 `LHttpServer` 的 `/files`，网页 js 直接读这些键名）：
   * ```json
   * {"path":"<进入后的绝对路径>",
   *  "list":[{"name":"a.txt","length":12,"path":"/x/a.txt",
   *           "isFile":true,"time":"2026-09-30 17:20:00","isDirectory":false}]}
   * ```
   * 少了 `isDirectory` / `name` / `path` 任一，网页渲染出来的列表就是空的。
   */
  private async listFiles(req: HttpRequest): Promise<HttpResponse> {
    let dir: string = '';
    let isBack: boolean = false;

    // ---- 1. 网页端格式：JSON body ----
    if (req.body.length > 0) {
      const text: string = new util.TextDecoder().decodeToString(req.body);
      const parsed: JsonParseResult = MiniJson.parse(text);
      if (parsed.ok && parsed.root.isObject()) {
        const p: JsonNode | null = parsed.root.field('path');
        if (p !== null) {
          dir = p.asString('');
        }
        const b: JsonNode | null = parsed.root.field('isBack');
        if (b !== null) {
          isBack = b.asBool(false);
        }
      }
    }

    // ---- 2. 兼容 GET ?dir= / ?path= 与 urlencoded body（便于 curl 调试）----
    if (dir.length === 0) {
      dir = req.queryParam('path');
    }
    if (dir.length === 0) {
      dir = req.queryParam('dir');
    }
    if (dir.length === 0) {
      dir = HttpRouter.readBodyParam(req.body, 'dir');
    }
    dir = HttpRouter.urlDecode(dir);

    // ---- 3. 定位目录 ----
    if (dir.length === 0) {
      dir = this.rootPath;
    }
    if (isBack) {
      const parent: string = HttpRouter.parentOf(dir);
      // 不准退到网页根目录之上：否则会把整个应用沙箱（filesDir）列出来给人看
      dir = parent.startsWith(this.rootPath) ? parent : this.rootPath;
    }

    const safe: string = this.resolveSafePath(dir);
    if (safe.length === 0) {
      // 走到沙箱之外时，退回根目录而不是报错，避免网页「上一级」点到底就卡住
      const fallback: string = this.resolveSafePath(this.rootPath);
      if (fallback.length === 0) {
        return HttpResponse.forbidden(`路径不在允许范围内: ${dir}`);
      }
      return this.renderDir(fallback);
    }
    return this.renderDir(safe);
  }

  /** 真正的目录枚举 + JSON 组装 */
  private renderDir(dir: string): HttpResponse {
    try {
      const names: string[] = fileIo.listFileSync(dir);
      const dirs: string[] = [];
      const files: string[] = [];
      for (let i = 0; i < names.length; i++) {
        const name: string = names[i];
        // 不展示隐藏文件。
        // （原实现的判断写成 `if (showHiddenFiles) { if (name.startsWith(".")) continue; }`，
        //   即只有开启「显示隐藏文件」时才过滤 —— 条件反了，这里按直觉修正。）
        if (name.startsWith('.')) {
          continue;
        }
        const full: string = `${dir}/${name}`;
        let stat: fileIo.Stat;
        try {
          stat = fileIo.statSync(full);
        } catch (e) {
          continue; // 断链的符号链接等，跳过而不是整表失败
        }
        const isDir: boolean = stat.isDirectory();
        const item: string =
          `{"name":${HttpRouter.jsonStr(name)},"length":${isDir ? 0 : stat.size},` +
          `"path":${HttpRouter.jsonStr(full)},"isFile":${isDir ? 'false' : 'true'},` +
          `"time":${HttpRouter.jsonStr(HttpRouter.fmtTime(stat.mtime))},` +
          `"isDirectory":${isDir ? 'true' : 'false'}}`;
        if (isDir) {
          dirs.push(item);
        } else {
          files.push(item);
        }
      }
      // 目录优先，与原 FileSearchUtils 的默认排序观感一致
      const items: string[] = dirs.concat(files);
      // ⚠️ 网页端把 `list[0]` 当成「返回上一级」：它不加勾选框、不显示时间、
      // 点击时以 `isBack=true` 去请求上一级（见 js/lanshare.min.js 的 openDir/dirClick）。
      // 不补这一条的话：① 第一个真实文件永远选不中（没勾选框 = 没法下载）；
      // ② 点列表里第一个文件夹会跳到**上一级**而不是进去。两条都是用户能撞到的。
      const back: string =
        `{"name":${HttpRouter.jsonStr('返回上一级')},"length":0,` +
        `"path":${HttpRouter.jsonStr(dir)},"isFile":false,"time":"","isDirectory":true}`;
      const all: string[] = [back].concat(items);
      const body: string = `{"path":${HttpRouter.jsonStr(dir)},"list":[${all.join(',')}]}`;
      return HttpResponse.json(200, body);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `列目录失败 ${dir}: ${err.code} ${err.message}`);
      return HttpResponse.forbidden(`无法访问目录: ${dir}`);
    }
  }

  /**
   * ★★ 5.1.60 `GET /stagefile/<文件名>?uri=<授权URI>&token=<token>` —— **零落盘**发送。
   *
   * ## 存在的理由
   *   「发送到网页端」原先必须先`stageForWeb()` 把文件整份复制进
   *   `saveRoot/网页待下载/`，只为了给浏览器一个「HTTP 能读的路径」。
   *   那个副本**没有任何清理**⇒ 文件永久留在沙箱（vivi 明确不接受）。
   *
   * ## 为什么现在可以不发
   *   `sendFileRange()` 走的是 `fileIo.openSync(spec.filePath)`，
   *   而 **`fileIo.openSync()` 能直接打开 picker 给的 `datashare://` 授权 URI**
   *   （同工程 `FileSource.open(uri)` 早就是这么用的）。
   *   ⇒ 单文件直接流式发送即可，**一个字节都不用落盘**。
   *
   * ## 安全性
   *   `/file/` 靠 `resolveSafePath()` 限定在沙箱内；本端点传的是**授权 URI**，
   *   所以必须自己把关：
   *     ① 只接受**带授权的 URI 形态**（`datashare://` / `file://` / `file.pho` / `media`…），
   *        裸绝对路径（`/data/...`）一律拒绝 —— 否则就成了「任意沙箱文件读取」；
   *     ② 授权 URI 本身带临时权限，**外部拿不到**，且 picker 的授权生命周期由系统管；
   *     ③ 仍走既有的 `serve()` token 校验（见 route之前的 checkToken）。
   *
   * ## 限制
   *   **只支持单文件**。多个文件必须打包，而 `zlib.compressFiles` 只认真实路径
   *   ⇒ 多文件仍走原来的「复制 + /compressFiles」。
   */
  private async stageFile(req: HttpRequest, encodedName: string): Promise<HttpResponse> {
    const uri: string = HttpRouter.urlDecode(req.queryParam('uri'));
    if (uri.length === 0) {
      return HttpResponse.text(400, '缺少 uri参数');
    }
    // ★ 授权 URI 形态白名单 —— 见上文「安全性 ①」
    const lower: string = uri.toLowerCase();
    const ok: boolean = lower.startsWith('datashare://') || lower.startsWith('file://')
      || lower.startsWith('file.pho') || lower.startsWith('media://')
      || lower.startsWith('content://');
    if (!ok) {
      Log.w(TAG, `stageFile 拒绝非授权 URI: ${uri}`);
      return HttpResponse.forbidden('仅支持用户授权选取的文件');
    }
    let fd: number = -1;
    let total: number = 0;
    try {
      const f: fileIo.File = fileIo.openSync(uri, fileIo.OpenMode.READ_ONLY);
      fd = f.fd;
      try {
        total = fileIo.statSync(f.fd).size;
      } catch (e) {
        total = 0;
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `stageFile 打开失败 ${err.code} ${err.message}`);
      return HttpResponse.notFound('文件读不到（授权可能已过期，请重新选择）');
    }
    // 名字以 URL 路径段为准（`/stagefile/abc.jpg`），query 里的 uri 只提供内容
    let fileName: string = HttpRouter.urlDecode(encodedName);
    if (fileName.length === 0) {
      fileName = 'file';
    }
    // 兜底：绝不让响应头里出现 CR/LF（头注入）
    fileName = fileName.replace(/[\r\n]/g, '_');
    const resp: HttpResponse = HttpResponse.of(200);
    resp.set('Content-Type', ContentTypes.of(fileName));
    resp.set('Content-Length', `${total}`);
    // 必须是 attachment：这是「下载」不是「预览」
    resp.set('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(fileName)}`);
    resp.streamFile = new FileStreamSpec(uri, total, 0, Math.max(0, total - 1), fileName);
    Log.i(TAG, `stageFile 直推（不落盘）${fileName} ${total}B`);
    return resp;
  }

  /**
   * GET /file/<绝对路径> —— 文件下载，支持 Range
   * 原实现用 CheckedOutputStream + CRC32 写过 zip 流，这里保持单文件 + Range 即可，
   * 打包下载属 B2 批次。
   */
  private async downloadFile(req: HttpRequest, encodedPath: string): Promise<HttpResponse> {
    // 网页端的调用形式是 `/file/<文件名>?path=<绝对路径>&token=<token>`
    // （见 js/lanshare.min.js:114 与 218）—— 真正的路径在 `path` 查询参数里，
    // URL 路径段只是文件名。所以优先取 `path`，取不到再退回路径段（兼容手工 curl）。
    let raw: string = HttpRouter.urlDecode(req.queryParam('path'));
    if (raw.length === 0) {
      raw = HttpRouter.urlDecode(encodedPath);
    }
    const safe: string = this.resolveSafePath(raw);
    if (safe.length === 0) {
      return HttpResponse.forbidden('路径越界');
    }

    let stat: fileIo.Stat;
    try {
      stat = fileIo.statSync(safe);
    } catch (e) {
      return HttpResponse.notFound('文件不存在');
    }
    if (stat.isDirectory()) {
      return HttpResponse.forbidden('目标是目录');
    }

    const totalSize: number = stat.size;
    const fileName: string = safe.substring(safe.lastIndexOf('/') + 1);
    const mime: string = ContentTypes.of(fileName);

    // ---- Range ----
    const rangeHeader: string = req.header('range');
    const range: number[] | null = HttpProtocol.parseRange(rangeHeader, totalSize);

    if (rangeHeader.length > 0 && range === null) {
      const r: HttpResponse = HttpResponse.of(416);
      r.set('Content-Range', `bytes */${totalSize}`);
      return r;
    }

    const resp: HttpResponse = HttpResponse.of(range === null ? 200 : 206);
    const start: number = range === null ? 0 : range[0];
    const end: number = range === null ? totalSize - 1 : range[1];

    resp.set('Content-Type', mime);
    resp.set('Accept-Ranges', 'bytes');
    resp.set('Content-Length', `${end - start + 1}`);
    // 可内联预览的类型不强制下载，否则浏览器里点图片会变成下载
    const disp: string = ContentTypes.isInline(fileName) ? 'inline' : 'attachment';
    resp.set('Content-Disposition', `${disp}; filename*=UTF-8''${encodeURIComponent(fileName)}`);
    if (range !== null) {
      resp.set('Content-Range', `bytes ${start}-${end}/${totalSize}`);
    }
    resp.streamFile = new FileStreamSpec(safe, totalSize, start, end, fileName);
    return resp;
  }

  // ------------------------------------------------------------------
  // 打包下载（网页端「下载文件」按钮）
  // ------------------------------------------------------------------

  /**
   * ★★ 5.1.61 暂存副本登记簿。
   *
   * 「发送到网页端」多文件时必须先把文件复制进沙箱（zip 只认真实路径），
   * 打包成功后要删掉。删除时**不能盲删 `safe`** ——
   * 那个数组里可能混着文件页勾选的**用户原有文件**（`pushFilesToWeb` 同一入口）。
   * ⇒ 用「本进程复制过的路径」做登记簿，只删登记在册的。
   */
  private static webStageSet: Set<string> = new Set<string>();

  /** 登记「这批路径是本进程复制出来的副本」 */
  static markWebStage(paths: string[]): void {
    for (let i = 0; i < paths.length; i++) {
      HttpRouter.webStageSet.add(paths[i]);
    }
  }

  /** 取消登记（打包失败、或用户改主意） */
  private forgetWebStage(paths: string[]): void {
    for (let i = 0; i < paths.length; i++) {
      HttpRouter.webStageSet.delete(paths[i]);
    }
  }

  /**
   * 打包成功后删副本：**只删在登记簿里的**那些。
   *
   * @param paths 本次涉及的路径（用来过滤出登记在册的）
   */
  private pruneWebStageSafe(paths: string[]): void {
    const doomed: string[] = [];
    for (let i = 0; i < paths.length; i++) {
      if (HttpRouter.webStageSet.has(paths[i])) {
        doomed.push(paths[i]);
      }
    }
    for (let i = 0; i < doomed.length; i++) {
      try {
        fileIo.unlinkSync(doomed[i]);
        HttpRouter.webStageSet.delete(doomed[i]);
        Log.i(TAG, `已删除网页待下载副本: ${doomed[i]}`);
      } catch (e) {
        // 删不掉不报错：下次打包前还会再清一次
        Log.w(TAG, `副本删除失败(保留登记): ${doomed[i]}`);
      }
    }
  }

  /**
   * `POST /compressFiles` —— 打包下载的第一步。
   *
   * 契约取自 `js/lanshare.min.js` 的 `downloadFile()`：
   * 请求体 `{"list":[<绝对路径>, ...]}`，成功时**必须**返回 `{"tempFile":"<名字>"}`，
   * 网页紧接着就 `window.location.href = "/downloadZipFile?tempFile=" + a.tempFile`。
   * 少了 `tempFile` 这个键，`a.tempFile` 是 undefined，第二步会变成下载 `...&tempFile=undefined`。
   *
   * 这两步是分开的：打包可能要几十秒（几百 MB），不能让它卡在下载响应里；
   * 而 `location.href` 又只能用 GET 触发浏览器下载，所以中间必须落一个临时文件。
   */
  private async compressFiles(req: HttpRequest): Promise<HttpResponse> {
    const wanted: string[] = HttpRouter.parsePathList(req.body);
    if (wanted.length === 0) {
      return HttpResponse.text(400, '没有可打包的文件：请先勾选文件');
    }

    const dir: string = this.zipTmpDir();
    if (dir.length === 0) {
      return HttpResponse.text(500, '临时目录不可用，无法打包');
    }

    // 逐个过安全检查：网页端传来的路径一律不可信，越界的直接丢掉而不是整批失败
    const safe: string[] = [];
    for (let i = 0; i < wanted.length; i++) {
      const p: string = this.resolveSafePath(wanted[i]);
      if (p.length === 0) {
        Log.w(TAG, `打包跳过越界路径: ${wanted[i]}`);
        continue;
      }
      try {
        if (!fileIo.accessSync(p)) {
          continue;
        }
      } catch (e) {
        continue;
      }
      safe.push(p);
    }
    if (safe.length === 0) {
      return HttpResponse.text(400, '勾选的文件都不存在或不在允许范围内');
    }

    this.pruneZipTemp(dir);
    this.pruneWebStageSafe([]);   // ★ 5.1.61：每次打包前先清上一次的残留
    const name: string = `LANShare-${Date.now().toString(36)}-${HttpRouter.randomName()}.zip`;
    const out: string = `${dir}/${name}`;
    // 打包这一步没有可计量的总量（zlib 不给回调），用 total=-1 让浮层显示整句文案。
    // 几百 MB 的打包能跑几十秒，没有提示的话用户会以为点了没反应。
    this.notifyDownloadProgress(0, -1, `正在打包 ${safe.length} 个文件…`);
    let packed: boolean = false;
    try {
      // 全部字段都可选：用默认压缩级别即可。局域网传输里压缩只是顺带，
      // 不为了省一点 CPU 去猜枚举名（不同 API 版本的枚举名不一样）。
      await zlib.compressFiles(safe, out, {});
      packed = true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `打包失败（${safe.length} 项）: ${err.code} ${err.message}`);
      this.notifyDownloadEnd(false, '', 0, `打包失败：${err.message}`);
      // ★ 5.1.61：**打包失败不删副本** —— 保留下来让用户能重试。
      //只清登记（本次没成功过，就不该有「待清理」的影子）。
      this.forgetWebStage(safe);
      return HttpResponse.text(500, `文件打包失败：${err.code} ${err.message}`);
    }
    Log.i(TAG, `已打包 ${safe.length} 项 -> ${out}`);
    // 打包完先留一句「等网页来取」，浏览器紧接着的 GET /downloadZipFile 会把它覆盖成百分比
    if (packed) {
      this.notifyDownloadProgress(0, -1, '打包完成，等待网页下载…');
    }
    // ★★ 5.1.61：**打包成功 ⇒ 立刻删掉「发送到网页端」的沙箱副本**。
    //   时机选在这里而不是 `GET /downloadZipFile` 之后：
    //     ① 此刻字节已在 zip 里，浏览器取的是 zip，不再需要副本；
    //     ② 取 zip 是**另一次请求**，可能断线/取消 ⇒ 副本会永久残留；
    //     ③ 跨请求关联两个阶段容易漏（进程被杀就再也不会有人来删）。
    //   ⚠️ 只删「网页待下载」目录下的文件（`pruneWebStage` 内部按目录前缀校验），
    //      绝不碰用户原有的接收文件。
    this.pruneWebStageSafe(safe);
    return HttpResponse.json(200, `{"tempFile":${HttpRouter.jsonStr(name)}}`);
  }

  /**
   * `POST /compressMedias` —— 「图片/视频」页的打包下载。
   *
   * 鸿蒙不开放媒体库（见本文件顶部的能力缺失清单），`/media` 返回的本来就是空数组，
   * 所以这里没有可打包的东西。给明确的 500 + 原因，而不是静默失败。
   */
  private compressMedias(): HttpResponse {
    return HttpResponse.text(500, '鸿蒙端没有媒体库能力，「图片/视频」页为空，无法打包');
  }

  /** `GET /downloadZipFile?tempFile=<名字>` —— 取走打包好的 zip */
  private serveZip(req: HttpRequest): HttpResponse {
    const name: string = req.queryParam('tempFile');
    // tempFile 直接来自 URL 查询参数：只允许纯文件名，杜绝穿越到临时目录之外
    if (name.length === 0 || name.includes('/') || name.includes('..') || name.includes('\\')) {
      return HttpResponse.text(400, 'tempFile 非法');
    }
    const dir: string = this.zipTmpDir();
    if (dir.length === 0) {
      return HttpResponse.text(500, '临时目录不可用');
    }
    const path: string = `${dir}/${name}`;
    let stat: fileIo.Stat;
    try {
      stat = fileIo.statSync(path);
    } catch (e) {
      return HttpResponse.notFound('打包文件不存在或已过期，请重新打包');
    }
    const size: number = stat.size;
    const resp: HttpResponse = HttpResponse.of(200);
    resp.set('Content-Type', 'application/zip');
    resp.set('Content-Length', `${size}`);
    resp.set('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(name)}`);
    resp.streamFile = new FileStreamSpec(path, size, 0, size - 1, name);
    return resp;
  }

  /** 临时 zip 目录（cacheDir 下），不存在就建 */
  private zipTmpDir(): string {
    if (this.ctx === null) {
      return '';
    }
    const dir: string = `${this.ctx.cacheDir}/${ZIP_TMP_DIR}`;
    try {
      if (!fileIo.accessSync(dir)) {
        fileIo.mkdirSync(dir, true);
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `临时目录创建失败: ${err.code} ${err.message}`);
      return '';
    }
    return dir;
  }

  /**
   * 回收超过保留时长的临时 zip。
   *
   * 为什么只能靠时间：打包和下载是两个独立 HTTP 请求，服务端无从知道浏览器
   * 到底取没取走，也就没有"下载完成"这个时机可以删。
   */
  private pruneZipTemp(dir: string): void {
    try {
      const names: string[] = fileIo.listFileSync(dir);
      const now: number = Date.now();
      for (let i = 0; i < names.length; i++) {
        const p: string = `${dir}/${names[i]}`;
        let stat: fileIo.Stat;
        try {
          stat = fileIo.statSync(p);
        } catch (e) {
          continue;
        }
        if (now - stat.mtime * 1000 > ZIP_TMP_KEEP_MS) {
          fileIo.unlinkSync(p);
        }
      }
    } catch (e) {
      // 清理失败不影响主流程
    }
  }

  /** 解析网页端发来的 `{"list":["/path/a","/path/b"]}` */
  private static parsePathList(body: Uint8Array): string[] {
    const out: string[] = [];
    if (body.length === 0) {
      return out;
    }
    const text: string = new util.TextDecoder().decodeToString(body);
    const res: JsonParseResult = MiniJson.parse(text);
    if (!res.ok || !res.root.isObject()) {
      return out;
    }
    const node: JsonNode | null = res.root.field('list');
    if (node === null || !node.isArray()) {
      return out;
    }
    for (let i = 0; i < node.count; i++) {
      const it: JsonNode | null = node.at(i);
      if (it === null) {
        continue;
      }
      const s: string = it.asString('');
      if (s.length > 0) {
        out.push(s);
      }
    }
    return out;
  }

  /**
   * 分块发送文件区间，8MB 一块，避免大文件一次性进内存。
   *
   * ⚠️ 本机 -> 浏览器的**全部**字节都从这里出去（`/file/<name>` 与 `/downloadZipFile`），
   * 所以下载方向的「开始 / 进度 / 结束」三件事都放在这一处上报，调用方不用各写一遍。
   */
  private async sendFileRange(channel: TcpChannel, spec: FileStreamSpec): Promise<boolean> {
    const CHUNK: number = 8 * 1024 * 1024;
    const total: number = spec.chunkSize;
    const label: string = spec.fileName.length > 0 ? spec.fileName : '文件';
    let sent: number = 0;
    let lastReportAt: number = 0;
    let chunks: number = 0;
    let file: fileIo.File | null = null;
    let ok: boolean = true;
    this.notifyDownloadProgress(0, total, label);
    try {
      file = fileIo.openSync(spec.filePath, fileIo.OpenMode.READ_ONLY);
      let offset: number = spec.start;
      const stop: number = spec.end;
      while (offset <= stop && !channel.isClosed) {
        const want: number = Math.min(CHUNK, stop - offset + 1);
        const buf: ArrayBuffer = new ArrayBuffer(want);
        const readLen: number = fileIo.readSync(file.fd, buf, { offset: offset, length: want });
        if (readLen <= 0) {
          break;
        }
        const chunk: Uint8Array = readLen === want
          ? new Uint8Array(buf)
          : new Uint8Array(buf).subarray(0, readLen);
        await channel.send(chunk);
        offset += readLen;
        sent += readLen;
        chunks += 1;

        // 进度上报：与上传同一套节流（200ms），否则 UI 每块重建一次页面。
        // 局域网内 8MB 一块几毫秒就发完了，不节流会把主线程刷满。
        const now: number = Date.now();
        if (now - lastReportAt >= UPLOAD_PROGRESS_MIN_MS) {
          lastReportAt = now;
          this.notifyDownloadProgress(sent, total, spec.fileName);
        }
        // 同样让出主线程：读块是同步 IO，让 UI 有机会画一帧、响应点击
        if (chunks % DOWNLOAD_YIELD_EVERY === 0) {
          await HttpRouter.yieldFrame();
        }
      }
      // 收尾补一次 100%：最后一次节流之后发的那截也要体现在浮层上
      this.notifyDownloadProgress(sent, total, spec.fileName);
      ok = !channel.isClosed;
      return ok;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `发送文件块失败: ${err.code} ${err.message}`);
      ok = false;
      return false;
    } finally {
      // 结束回调成功失败都发（连 catch 分支也要发）：只发成功的话，
      // 浏览器中途取消下载 / 读到一半出错时，手机上的浮层会永远停在某个百分比不消失，
      // 而「transferText 非空 → 空」这个跳变不发生，文件页的自动刷新也跟着失效。
      this.notifyDownloadEnd(ok, label, sent,
        ok ? '' : '连接中断，浏览器可能取消了下载');
      if (file !== null) {
        try {
          fileIo.closeSync(file);
        } catch (e) {
          // ignore
        }
      }
    }
  }

  /**
   * POST /media —— 图片/视频列表。
   * 网页期望拿到的是**数组**（`b.forEach(...)`），返回对象会让前端直接报错，
   * 所以这里返回空数组，媒体库能力属 B2 批次。
   */
  private async listMedia(req: HttpRequest): Promise<HttpResponse> {
    return HttpResponse.json(200, '[]');
  }

  /**
   * POST /apps —— 已安装应用列表。
   * 网页期望 `{list:[...]}`。鸿蒙不向三方应用开放「枚举已安装应用」能力，
   * 返回空列表让页面正常渲染，而不是让整个网页卡在报错上。
   */
  private appList(): HttpResponse {
    return HttpResponse.json(200, '{"list":[]}');
  }

  // ------------------------------------------------------------------
  // 网页端接口
  // ------------------------------------------------------------------

  /**
   * POST /checkPass —— 网页在「等待确认」期间每 2 秒轮询一次。
   *
   * 原实现按 `token` 查 token 表返回 `{pass}`。**字段名必须是 `pass`**：
   * 网页读的是 `b.pass`，早期实现返回 `{ok:...}` 导致判断永远为假、死循环。
   */
  private checkPass(req: HttpRequest): HttpResponse {
    const token: string = WebClientStore.normalizeToken(req.header('token'));
    const c: WebClient | null = this.clients.byToken(token);
    const pass: boolean = c !== null && c.pass;
    return HttpResponse.json(200, `{"pass":${pass ? 'true' : 'false'}}`);
  }

  /**
   * POST /initConfig —— 网页启动时拉取初始配置，也是**授权流程的入口**。
   *
   * 语义与原 `LHttpServer` 的 `/initConfig` 完全一致：
   * | 情况 | 行为 |
   * |---|---|
   * | 该 IP 已登记且 pass=1 | 直接返回 `pass:true` |
   * | 该 IP 已登记但 pass=0 | 返回 `pass:false`，并通知 UI 提示确认 |
   * | 该 IP 从未出现 | 新建记录（`pass = WEB_OPEN 开关`），若需确认则通知 UI |
   *
   * 返回体字段：`rootPath`（网页 hash 路由的起始目录）、`name`（该网页客户端的名字）、
   * `token`（后续请求都要带）、`pass`（是否已放行）。**四个缺一不可。**
   */
  private async initConfig(req: HttpRequest): Promise<HttpResponse> {
    const ip: string = req.remoteIp;
    const incoming: string = WebClientStore.normalizeToken(req.header('token'));

    let record: WebClient | null = ip.length > 0 ? this.clients.byIp(ip) : null;
    if (record === null && incoming.length > 0) {
      record = this.clients.byToken(incoming);
    }

    let needNotify: boolean = false;
    if (record === null) {
      // ---- 新客户端 ----
      const auto: boolean = this.webOpen;
      record = this.clients.add(ip, `网页设备${HttpRouter.randomName()}`, auto);
      needNotify = !auto;
      Log.i(TAG, `新网页客户端 ${ip}（token=${record.token}），自动放行=${auto}`);
    } else {
      // ---- 已知客户端：刷新地址与时间戳 ----
      this.clients.touch(record);
      if (ip.length > 0 && record.ip !== ip) {
        record.ip = ip;
      }
      if (!record.pass && this.webOpen) {
        record.pass = true;
        Log.i(TAG, `网页客户端 ${ip} 因「网页免确认」已开启而自动放行`);
      }
      needNotify = !record.pass;
    }
    await this.clients.flush();

    if (needNotify) {
      // 交给 LanService：写 UI 日志 + 渲染授权卡片
      if (this.newClientSink !== null) {
        this.newClientSink(record.clone());
      }
    }

    const body: string =
      `{"rootPath":${HttpRouter.jsonStr(this.rootPath)},` +
      `"name":${HttpRouter.jsonStr(record.name)},` +
      `"token":${HttpRouter.jsonStr(record.token)},` +
      `"pass":${record.pass ? 'true' : 'false'},` +
      // 下面几个是鸿蒙侧附加信息，网页不读，但方便 curl 自检
      `"deviceName":${HttpRouter.jsonStr(LanConfig.userName)},` +
      `"tcpPort":${LanConfig.fileServerPort}}`;
    return HttpResponse.json(200, body);
  }

  /**
   * POST /updateWebName —— 网页上改「本网页客户端的名字」。
   * 网页发的是 JSON `{webName:"..."}`（见 lanshare.min.js:170），不是 urlencoded。
   */
  private async updateWebName(req: HttpRequest): Promise<HttpResponse> {
    let name: string = '';
    if (req.body.length > 0) {
      const text: string = new util.TextDecoder().decodeToString(req.body);
      const parsed: JsonParseResult = MiniJson.parse(text);
      if (parsed.ok && parsed.root.isObject()) {
        const v: JsonNode | null = parsed.root.field('webName');
        if (v !== null) {
          name = v.asString('');
        }
        if (name.length === 0) {
          const alt: JsonNode | null = parsed.root.field('name');
          if (alt !== null) {
            name = alt.asString('');
          }
        }
      }
    }
    if (name.length === 0) {
      name = HttpRouter.readBodyParam(req.body, 'webName');
    }
    if (name.length === 0) {
      return HttpResponse.json(200, '{"pass":false}');
    }

    // 注意：改的是**该网页客户端**的名字（原 tokenDBUtil.updateName），
    // 不是本机设备名 —— 早期实现改错了对象。
    const token: string = WebClientStore.normalizeToken(req.header('token'));
    if (this.clients.updateName(token, name)) {
      await this.clients.flush();
    }
    return HttpResponse.json(200, '{"pass":true}');
  }

  /** 鸿蒙平台不开放的能力，明确返回 501 并给出原因，而不是静默 404 */
  private platformUnsupported(path: string): HttpResponse {
    const msg: string =
      `功能不可用：${path}\n` +
      '原因：HarmonyOS 不向三方应用开放「枚举已安装应用 / 读取其它应用安装包」能力\n' +
      '（bundleManager 需 ohos.permission.GET_BUNDLE_INFO_PRIVILEGED，仅系统应用可用）。\n' +
      '详见 docs/迁移对照表.md 的能力缺失清单。';
    return HttpResponse.text(501, msg);
  }

  // ------------------------------------------------------------------
  // WebSocket 升级：把连接交给 WsProtocol 的会话层
  // ------------------------------------------------------------------

  private async handleWsUpgrade(req: HttpRequest, channel: TcpChannel): Promise<HttpResponse | null> {
    if (!WsUpgradeRouter.isUpgrade(req.headers)) {
      return HttpResponse.text(400, '不是合法的 WebSocket 升级请求');
    }
    const key: string = req.header('sec-websocket-key');
    const handshake: Uint8Array = WsUpgradeRouter.handshakeResponse(key);
    await channel.send(handshake);
    // ★ 先打「已接管」标记，再交给会话层。
    //   顺序不能反：标记是给 accept 循环看的，serve() 返回后它就会执行；
    //   若晚于返回（比如放进异步回调里），连接已经被 close 了。
    channel.markDetached();
    // 交给会话层：返回 null 表示本连接的 HTTP 职责结束
    WsUpgradeRouter.detach(channel);
    return null;
  }

  // ------------------------------------------------------------------
  // 工具
  // ------------------------------------------------------------------

  /** URL 解码；失败保留原值（网页传的参数未必是合法百分号编码） */
  static urlDecode(s: string): string {
    if (s.length === 0) {
      return s;
    }
    try {
      return decodeURIComponent(s);
    } catch (e) {
      return s;
    }
  }

  /** 取父目录。末尾斜杠先归一化，已在根上则返回根 */
  static parentOf(path: string): string {
    if (path.length === 0) {
      return path;
    }
    let p: string = path;
    while (p.length > 1 && p.endsWith('/')) {
      p = p.substring(0, p.length - 1);
    }
    const i: number = p.lastIndexOf('/');
    if (i <= 0) {
      return '/';
    }
    return p.substring(0, i);
  }

  /** 文件时间格式化成 `yyyy-MM-dd HH:mm:ss`（网页直接用这个字符串显示） */
  static fmtTime(sec: number): string {
    const d: Date = new Date(sec * 1000);
    return `${d.getFullYear()}-${HttpRouter.pad2(d.getMonth() + 1)}-${HttpRouter.pad2(d.getDate())} ` +
      `${HttpRouter.pad2(d.getHours())}:${HttpRouter.pad2(d.getMinutes())}:${HttpRouter.pad2(d.getSeconds())}`;
  }

  private static pad2(n: number): string {
    return n < 10 ? `0${n}` : `${n}`;
  }

  /** 对应原 mUtil.generateRandomString —— 新网页客户端的随机名后缀 */
  private static randomName(): string {
    const chars: string = 'abcdefghijklmnopqrstuvwxyz0123456789';
    let s: string = '';
    for (let i = 0; i < RAND_NAME_LEN; i++) {
      s += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return s;
  }

  /**
   * 路径安全校验：只允许访问沙箱目录与用户显式授权的目录。
   *
   * 这一条替代 Android 的 MANAGE_EXTERNAL_STORAGE —— 鸿蒙没有"全盘访问"权限，
   * 只能访问沙箱 + 用户通过 Picker 授权的目录。越界返回空串。
   */
  private resolveSafePath(path: string): string {
    if (this.ctx === null || path.length === 0) {
      return '';
    }
    if (path.includes('..')) {
      return '';
    }
    const sandbox: string = this.ctx.filesDir;
    const cache: string = this.ctx.cacheDir;
    const allowed: string[] = [sandbox, cache];
    for (let i = 0; i < allowed.length; i++) {
      if (path === allowed[i] || path.startsWith(`${allowed[i]}/`)) {
        return path;
      }
    }
    Log.w(TAG, `拒绝越界访问: ${path}`);
    return '';
  }

  /** 把 body 当 urlencoded 表单解析取字段 */
  static readBodyParam(body: Uint8Array, key: string): string {
    if (body.length === 0) {
      return '';
    }
    const text: string = new util.TextDecoder().decodeToString(body);
    const map: Map<string, string> = new Map<string, string>();
    HttpProtocol.parseQuery(text, map);
    const v: string | undefined = map.get(key);
    return v === undefined ? '' : v;
  }

  /** 最小 JSON 字符串转义 */
  static jsonStr(s: string): string {
    let out: string = '"';
    for (let i = 0; i < s.length; i++) {
      const c: string = s.charAt(i);
      switch (c) {
        case '"': out += '\\"'; break;
        case '\\': out += '\\\\'; break;
        case '\n': out += '\\n'; break;
        case '\r': out += '\\r'; break;
        case '\t': out += '\\t'; break;
        default:
          out += c.charCodeAt(0) < 0x20 ? ' ' : c;
      }
    }
    return `${out}"`;
  }

  private static grow(buf: Uint8Array): Uint8Array {
    const next: Uint8Array = new Uint8Array(buf.length * 2);
    next.set(buf, 0);
    return next;
  }

  private static concat(a: Uint8Array, b: Uint8Array): Uint8Array {
    const out: Uint8Array = new Uint8Array(a.length + b.length);
    out.set(a, 0);
    out.set(b, a.length);
    return out;
  }
}

/**
 * WebSocket 升级的中转站。
 *
 * HttpRouter 与 WS 会话层解耦：升级成功后把通道登记在这里，
 * 由 LanService 取走并交给 WebSocketSession 处理帧。
 */
export class WsUpgradeRouter {
  /** 待接管的 WS 通道队列 */
  private static pending: TcpChannel[] = [];
  private static sink: ((channel: TcpChannel) => void) | null = null;

  static setSink(fn: (channel: TcpChannel) => void): void {
    WsUpgradeRouter.sink = fn;
    // 补交在 sink 注册前已升级的连接
    const queue: TcpChannel[] = WsUpgradeRouter.pending;
    WsUpgradeRouter.pending = [];
    for (let i = 0; i < queue.length; i++) {
      fn(queue[i]);
    }
  }

  static isUpgrade(headers: Map<string, string>): boolean {
    const upgrade: string | undefined = headers.get('upgrade');
    const key: string | undefined = headers.get('sec-websocket-key');
    return upgrade !== undefined && upgrade.toLowerCase() === 'websocket' && key !== undefined;
  }

  static handshakeResponse(clientKey: string): Uint8Array {
    return WsProtocol.handshakeResponse(clientKey);
  }

  static detach(channel: TcpChannel): void {
    if (WsUpgradeRouter.sink !== null) {
      WsUpgradeRouter.sink(channel);
    } else {
      WsUpgradeRouter.pending.push(channel);
    }
  }
}

