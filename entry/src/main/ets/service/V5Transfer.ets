/**
 * 文件传输（**v5 协议**，对齐局域网互传 1.35 修改版）
 *
 * 与 v4（service/FileTransfer.ets）不是同一套字节，两者**互不兼容**。
 * 本文件是 V5 包专用的收发实现，字段布局全部来自 1.35 dex 取证
 * （见 docs/forensics/dump_g.txt、dump_q_full.txt、dump_lo2j.txt）。
 *
 * ## 完整字节序列（发送端视角）
 * ```
 * [4B MAGIC 'fgsq']                       建连后立刻写（LanClient 已做）
 * 帧1   [1101][文件数][len]{设备头 + byte(encData)}
 * 帧2…  [-1  ][0][len]{long 长度, String 名, int 类型, String 附加
 *                       [, int children 仅 3004] [, long mediaId 仅 3001/3002]}
 * 应答   [1102][0][0] 或 [1103][0][0]     ← 只有 12 字节头，无 payload
 *
 * 每个文件：
 *   帧    [-1][0][len]{long 长度, String 名}        ← 只有两个字段，与上面那批不同
 *   数据帧 [1  写在头[0]][ ][len]{原始字节}          len 在头[8..11]
 *   结束帧 [2  写在头[0]][ ][0]                     FS_END
 *   对端回一个**裸单字节** 5(FS_NEXT) / 6(FS_BREAK)
 * ```
 *
 * ## 与 v4 的三个关键差别（改错一个就传不动）
 * | 项 | v4 | v5 |
 * |---|---|---|
 * | 请求 | 裸 int 1101 + boolean + JSON | 12 字节头帧，payload = 设备头 + byte |
 * | 清单 | 一个 JSON 带全部文件 | **每文件一帧**，且应答后还要再发一遍（只有 len+name） |
 * | 分片 | `int len + 数据` | 12 字节头（cmd 在头[0] 的**单字节**）+ 数据 |
 *
 * ## 分片大小为什么是 1MB-12 而不是 2MB-12
 * 1.35 自己用 2MB 缓冲（chunk=2097140），但它的**信令**路径只分配 1MB
 * （`LANService->q` 里 `new byte[1048576]`，payload 从偏移 12 开始写）。
 * 取 1MB-12 是两边都能收的保守值，不会踩到 1.35 的数组越界。
 *
 * ## ★ 块级应答（5.0.19 定案）—— 每收一块必须**立刻**回 1 字节
 *
 * 这是 V5 互通的**硬性时序**，不是可选优化。不遵守 = 大文件必然卡死：
 *
 *   · PC 端 `LANShare.exe`（MinGW/Qt，带完整 C++ 符号表）反汇编证据：
 *     `baseSend`（1101 路径）与 `LANShare::sendOneSeg`（1110 路径）循环体同构 ——
 *     `IOUtils::read(buf, 2097152 - headerSize)` → `setByteCmd(1)` →
 *     `TCPClient::send(块)` → `b=0` → **`TCPClient::recvo(&b, 1, 0)`** →
 *     `if (b == 6) 中止` → 才发下一块。
 *     `TCPClient::recvo(void*, unsigned long long, int)` 的真身就是裸 `::recv`
 *     循环（第 3 个参数被当 flags 传给 recv），**阻塞且无超时**。
 *     块尺寸：`movl $2097152,%ebp ; subl headerSize,%ebp` → **2097140**。
 *   · Android 1.35 同构：`docs/forensics/dump_y.txt` 238-249 行，
 *     `isNextStep() ? write(5) : write(6)` 位于**每块写盘之后**的循环体内；
 *     同文件 91 行的日志串 `" recvBuf=2097152 chunk=2097140 target="` 即块尺寸出处。
 *   · PC 收端 `baseRecv` 亦对称：`6 - isNextStep()` 写回 1 字节 / 帧。
 *
 * 旧实现只在**整份文件 / 整片收满**之后回一个字节，于是：
 *   对端发完第 1 块 → 阻塞在 `recv` 等应答 → 本端在等第 2 块 → **双向死锁**；
 *   本端 60s 后 `readExactly(12)` 超时，对端进度条停在此处：
 *   **2097140 / 文件大小 = 48%** —— 正是用户看到的现象。
 *
 * 判据实验：`tests/live-probe/v5_push_probe.mjs`（手工按 1.35 语义推 3 块、
 * 全程零应答）→ 真机 `v5 已保存 … (6291420 B, 3 片, 293ms)`，
 * 证明本端接收管线本身没有上限，缺的就是这个字节。
 *
 * ⚠️ 保留「整片/整份收满后回 5(+2)」的片级收尾不变：那是 1.35 `z()`/`B()` 的结尾语义，
 *    多余字节对端不读即丢弃；删掉反而可能破坏与 Android 端的互通。
 *
 * ## ★ 文件结束帧（5.0.20 定案）—— 每个文件收满后必须再消费一帧 FS_END
 *
 * 发送端在**每个文件**的数据块之后都补发一帧 **12 字节结束帧**：
 *   `head[0]=2 (FS_END)`、`head[4..7]=arg=0`、`head[8..11]=len=0`。
 *   · PC `baseSend`：`cmpq 80(%rax),%r14`(已发满) → `setByteCmd(2)` → `send(data,len,0)`
 *     （未发满走 `setByteCmd(3)` = FS_CLOSE）
 *   · 1.35 `LANService.D`（`docs/forensics/dump_D.txt` 320-343）：
 *     `setInt(v0,-1,0)` → `setInt(v0,0,4)` → `v0[0] = (发满 ? 2 : 3)` →
 *     `setInt(v0,0,8)` → `write(v0,0,12)`
 *   · 本机 `sendPlain` 同样补发（`endFrame.setStreamCmd(LCmd.FS_END)`）。
 *
 * 而 PC 收端 `baseRecv` **就是靠这一帧判文件结束**：
 *   `140022dd1: cmpb $1,%al ; jne 140022f48`（非数据帧）
 *   `140022f48: cmpb $2,%al ; je 140022f10`（FS_END → 退出循环，**不回 ack**）
 *
 * 旧实现 `while (subTotal < item.length)` **收满即跳出**，从不读这一帧 →
 * 它被**下一个文件的 recvBody** 当帧头读走 → `break` → `0 != item.length` →
 * 回 `FS_BREAK(6)` → **PC 一次发 ≥2 个文件时第 2 个起必失败**。
 * 真机复现（5.0.19）：`v5 接收字节数不符: 0 != 4194280（v5_multi_f2.bin）`。
 */
import { BusinessError } from '@kit.BasicServicesKit';
import { util } from '@kit.ArkTS';
// ⚠️ 历史坑（保留提醒）：`WriteOptions` 是 kit 的**顶层具名导出**，不在 `fileIo`
//   命名空间下（写成 `fileIo.WriteOptions` 会报 10505001）。
//   本文件现在改用 `fileIo.lseek(fd, pos)` + `write(fd, buf)` 显式定位，
//   不再需要 `WriteOptions` —— 原因见 `writeAtFd` 的注释。
import { fileIo } from '@kit.CoreFileKit';
import { LCmd } from '../core/LCmd';
import { Log } from '../core/Logger';
import { FileCrypto } from '../core/FileCrypto';
import { LanDevice } from '../core/DeviceCodec';
import { V5Dec, V5Enc, V5_FRAME_CONT } from '../core/V5Codec';
import { LanClient } from '../net/LanClient';
import { TcpChannel } from '../net/NativeSocket';
import { FileSink, FileSource, FileStorage, MagicType, OutgoingFile } from './FileStorage';
import { TransferReport, TransferCallback } from './FileTransfer';

const TAG: string = 'V5Transfer';

/** 分片 payload 上限：1MB - 12 字节头。见文件头说明 */
const CHUNK: number = 1024 * 1024 - 12;
const SEG_TOTAL: number = 16;

/**
 * ★★ 5.1.19：**在途量闸门**（每发 N 块让一帧）。
 *
 * ## 为什么要它
 * 5.1.17/5.1.18 把 `SO_SNDBUF` 改成「不设」，让内核自动调优 ⇒ 吞吐 35.7 → 52.9MB/s，
 * **但对端 1.35 的**大文件**传输开始失败**（小文件仍成功）。
 * 5.1.18 只保留这一处改动仍失败 ⇒ 病因就是「发送缓冲变大」本身。
 *
 * ## 机理
 * 5.1.12 显式 `SO_SNDBUF=262144`（256KB）：一块 1MiB 写进去，内核只吃下 256KB，
 * 必须等对端读走才能继续 ⇒ **在途字节量被硬压到 ~1.25MB**。
 * 改成不设之后缓冲可达数 MB ⇒ 在途量 4MB+（3 倍以上）。
 * 1.35 的块级流控有一处**按在途量做的假设**（`recvBuf=2097152` 单缓冲 +
 * `isNextStep()`），超过阈值就判错 ⇒ **大文件必踩、小文件撑得住**。
 *
 * ## 本开关的作用
 * 不再用 SO_SNDBUF 去压（在途量的同时会一并关掉内核自动调优、丢掉 48% 提速），
 * 改在**应用层**加批次闸门：每发 N 块 `await` 一帧（`setTimeout(0)`），
 * 把「一次连续 push 进内核的字节数」压到 `N × 1MiB`，
 * **间接约束在途量，同时保住内核自动调优**。
 *
 * | 值 | 含义 | 预期 |
 * |---|---|---|
 * | `0` | 不设闸门（= 5.1.17 行为）| 52.9MB/s，1.35 大文件失败 |
 * | `4` | 每 4 块让一帧（在途 ≈4MB）| 略降，可能仍失败 |
 * | `1` | 每块让一帧（在途 ≈1MB，**最接近 5.1.12**）| 1.35 应恢复 |
 *
 * ⚠️ 探测性质的版本：按 4 → 1 各测一次 1.35 大文件，反推它的真实阈值。
 */
const SEND_INFLIGHT_BLOCKS: number = 1;

/** 单帧 payload 的硬上限，超过一定是流错位了 */
const MAX_FRAME: number = 8 * 1024 * 1024;

/**
 * 发送循环用的「让帧」。
 * 注意不名用 `yieldFrame` —— 类内已有 `V5Transfer.yieldFrame`，
 * 顶层同名会让阅读与调用都发慌，改用本名。
 */
function sendYieldFrame(): Promise<void> {
  return new Promise<void>((resolve: () => void) => {
    setTimeout(resolve, 0);
  });
}

/**
 * 收满一个文件后，等对端那一帧 **FS_END 结束帧** 的时限（毫秒）。
 *
 * 正常情况对端（PC / 1.35 / 本机 `sendPlain`）在最后一块的块级 ack 之后立刻发，
 * 这里几乎不会真的等到超时；设成 5s 只是给「对端不发结束帧」的旧实现留一个
 * 快速失败的窗口 —— 超时后回退到「按字节数判结束」，功能仍然正确。
 */
const END_FRAME_WAIT_MS: number = 5000;

/**
 * 同步解密 / 落盘之间「让一帧给 UI」的时间预算（毫秒）。
 *
 * ArkTS 是**单线程**事件循环：`FileCrypto.decData` 是逐字节 JS 循环（同步），
 * 一边收文件一边解密等于把 UI 线程按住。最大的坑是帧长上限 `MAX_FRAME` = 8MB ——
 * 真按一块 8MB 来，一次解密就能把主线程占住上百毫秒；
 * 16 条连接并发时更是几乎排满，表现就是「接收文件时界面卡顿，
 * 切一下 Tab 要卡好几秒」（vivi 2026-10-01 真机反馈）：
 * Tab 切换本身有 300ms 动画，动画的每一帧都要主线程给时间，
 * 主线程被占满 → 动画被拉成好几秒。
 *
 * 做法：把一块按 {@link DEC_SLICE} 切片，切片之间检查预算，
 * 超过 {@link UI_YIELD_BUDGET} 就让出一帧（`setTimeout(0)`，与 HttpRouter
 * 里 `yieldFrame` 同一手法）。这样**单次连续占用主线程 ≤ 一片解密的时间**，
 * 而让出频率被限制在最多约 60 次/秒，吞吐损失可忽略。
 */
const UI_YIELD_BUDGET: number = 12;
/**
 * 解密切片大小。
 *
 * 取 **256KB**（vivi 2026-10-01 第三次反馈后，从 512KB 再减半）：
 * 它决定「单次连续占用主线程」的上界 —— 一片解密的耗时约 1~2ms，
 * 远低于一帧（16ms）的容忍度。**不能用 1MB/8MB 整块解**，那正是卡顿的来源。
 *
 * 为什么不再往下调（128KB / 64KB）：切片越小，让帧判断与循环本身的**相对**开销越大，
 * 实测吞吐会掉。256KB 是「主线程占用够碎」与「吞吐不掉」的折中点。
 */
const DEC_SLICE: number = 256 * 1024;

const IMG_EXT: string[] = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'heic', 'svg'];
const VID_EXT: string[] = ['mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'rmvb', '3gp', 'webm'];

/** 接收侧解析出来的一个待收条目 */
class V5Incoming {
  name: string = '';
  length: number = 0;
  fileType: number = LCmd.FILE_FILE;
}

/**
 * 一次「分段传输」（cmd=1110）的重组状态。
 *
 * 1.35 修改版把文件切成固定 16 片、**每片一条独立 TCP 连接**并发发送，
 * 所以 16 条连接必须写进**同一个文件**的**不同偏移**，靠 segId 认领同一个状态对象。
 */
class SegPart {
  /** 目标绝对路径 */
  path: string = '';
  /** 展示名 */
  name: string = '';
  /** 整份文件大小 */
  fileSize: number = 0;
  /** 分片总数（1.35 硬编码 16） */
  total: number = 0;
  /**
   * 已收到的**字节总数**，16 条并发连接**共享同一个计数器**。
   *
   * ⚠️ **不能用「已覆盖到的最大末端偏移（maxEnd）」算进度/判完成**：
   *   16 片是并发乱序到达的，「落在文件最末尾的那一片」平均在第 8 片左右就先到，
   *   它一到就把 maxEnd 顶成 fileSize → 进度条在 ~50% 处判完成并清零
   *   （vivi 2026-10-01 真机实测「进度条刚走一半传输就完成了」）。
   *   更糟的是旧实现此时还会 `segs.delete(segId)`，后到的片认领不到 → **另建一个文件**。
   *   改成累加真实收到的字节数：进度单调递增、完成判定与到达顺序无关。
   *
   * ⚠️⚠️ **必须是「每落地一块就 += flen」，不能只在「整片收满」时 += len**：
   *   只在片收满时累加的话，片**进行中**这个值根本不反映别的片收了多少 ——
   *   每条连接上报的都只是「自己那一片的局部进度」，16 片并发互相覆盖 →
   *   进度条在低区间来回跳，直到 16 片几乎同时收满、一次性跳到 100%
   *   （vivi 2026-10-01 真机实测「一直在 1%~2% 之间跳动，然后立马 100%」）。
   *   这与发送侧的 `SegSend.sent` 是同一个模型：**跨连接共享的单调计数器**。
   */
  received: number = 0;
  /** 已收到的分片下标，防重传重复计字节 */
  gotIdx: boolean[] = [];
  /** 已完成的分片数 */
  done: number = 0;
  /** 起始时间，用于耗时统计 */
  startedAt: number = 0;
  /** 是否已上报「完成」 */
  reported: boolean = false;
  /** 收齐时刻；已完成条目靠它做超时清理 */
  finishedAt: number = 0;
  /**
   * 上一次**进度上报**的时刻与百分比 —— 16 条连接**共享这一对状态**。
   *
   * ⚠️ 为什么必须共享（而不是像早期那样各连接各存一份局部变量）：
   *   16 条连接并发推进，各自都在「每落地一块」后判断要不要上报。
   *   若节流状态是**每条连接私有**的，那么当全局百分比从 N 变到 N+1 时，
   *   **16 条连接会各自上报一次**（它们私有的 lastPct 都还停在旧值）——
   *   1GB 文件凭空产生 16×100 ≈ 1600 次上报，其中 15/16 是重复值。
   *   每次上报都会走一遍 `onTransferReport` → 拼字符串 → 请求 UI 刷新，
   *   这正是「接收过程中界面卡顿」的一个主要来源（vivi 2026-10-01 真机反馈）。
   *   共享之后，同一次百分比变化只上报一次。
   */
  lastReportAt: number = 0;
  lastReportPct: number = -1;
}

/**
 * 一次「分片发送」（cmd=1110）的进度状态。
 * 16 条并发连接共享同一个对象，各自累加自己发出去的字节数。
 */
class SegSend {
  /** 本文件总字节 */
  fileSize: number = 0;
  /** 各片已发字节合计（单调递增，与到达/完成顺序无关） */
  sent: number = 0;
  /** 已成功的片数 */
  okCount: number = 0;
  /** 上次上报的百分比，用于节流 */
  lastPercent: number = -1;
}

export class V5Transfer {
  /**
   * 正在接收的分段传输，按 segId 索引。
   * 16 条并发连接靠它认出「我们是同一份文件的不同片」。
   */
  private static segs: Map<string, SegPart> = new Map<string, SegPart>();

  /** 1110 分片总数（1.35 硬编码 `const/16 v1, 0x10`） */
  static readonly SEG_TOTAL: number = 16;
  /** 走 1110 的最小文件大小 = 128MB（1.35 的 `0x8000000`，见 `send()` 注释） */
  static readonly SEG_MIN_SIZE: number = 134217728;
  /**
   * ★ 是否启用 1110 分片**发送**（5.0.27 起默认 **false**；**接收侧恒保留**）。
   *
   * 关闭原因（真机实证，非推测）：车机版安卓 1.35 在收完某一片的全部数据块、
   * 回完所有块级 ack（5）后，会**偶发直接关掉这条连接、不再发片级终态 2**。
   *   · 判据：失败片日志恒为「已跳过 N 个流控字节，本片共 N 块，连接已断」——
   *     hopCount == blocks（数据 100% 送达）+ `chan.isClosed === true`。
   *   · 已排除「本端超时误判」：`NativeSocket.readExactly` 超时只 `return null`，
   *     **不会**把 `closed` 置 true，所以这是真的对端 FIN。
   *   · 量化：片级失败率 ≈ 5%；16 片并发 ⇒ **约 60% 概率至少 1 片中招**。
   *
   * 后果：批次只要有 1 片判失败，`send()` 就把**整个文件**并入 1101 重传
   * （677MB 传两遍 = 1.35GB）—— 即 vivi 反馈的「一直连续发送 2 次」。
   * 而 1101 单连接对 1.35 是**已实机验证成功**的通道，代价只是没有并行加速。
   *
   * ⚠️ 发送侧代码（`sendSegBatch` / `sendSegFile` / `sendOneSegment`）**不删**，
   *    仍被引用链串着；将来若换到不会提前关连接的对端，把这里改回 true 即可恢复。
   */
  static readonly SEG_SEND_ENABLED: boolean = false;
  /**
   * 收齐本片所有数据块的流控 ack 后，再等「片级终态 2」的宽限窗口（毫秒）。
   * 5.0.24：对端若在收齐块 ack 后仍不回片级终态（车机 1.35 实测出现过），
   * 窗口过后即按「数据已完整送达」判定成功，不再回退 1101 把大文件重传一遍。
   * ⚠️ 不放宽总等待（vivi 实测：热点并不慢，且正常时是对端**立即**回 2），
   *    正常对端毫秒级就回，1.5s 有充足余量，原有「立即完成」行为完全不变。
   */
  static readonly SEG_TERM_GRACE_MS: number = 1500;


  // ==================================================================
  // 发送
  // ==================================================================

  /**
   * 发一批文件。按**文件大小**分流，与 1.35 修改版的资格判定对齐：
   *
   * | 条件 | 走哪条路 |
   * |---|---|
   * | 普通文件 且 `size >= 128MB` | **1110**：16 片并发（每片一条独立 TCP） |
   * | 其余（小文件 / 图片视频 / 混合批次） | **1101**：整份文件单连接顺序发 |
   *
   * 取证：1.35 `LANService` 7020-7256 的 `eligible` 判定 ——
   *   `getLength() >= 0x8000000`（128MB）才 eligible，且 `StreamInfo/UriFileInfo/MediaInfo`
   *   三类恒不 eligible；日志原文 `eligible=false reason=TOO_SMALL_FOR_SEGS len=… need=134217728 segs=16`。
   *   （该修改版里两条 `SEND-MODE parallel=…` 日志文字与分支写反了，但控制流确定：
   *    eligible → `:goto_4` → v0=0 → `:cond_1e`(8992) → 分片；全不 eligible → `:cond_8` →
   *    v0=1 → `LANService.g()`(9109) → 1101。）
   *
   * ⚠️ 与 1.35 的唯一差别：1.35 是「批次里只要有 1 个 eligible 就整批走分片」，
   *    这里保守地**逐个文件**判 —— 大文件走分片、其余仍走 1101，语义更精确且不会让
   *    图片/视频被塞进分片通道。
   */
  static async send(
    self: LanDevice,
    target: LanDevice,
    files: OutgoingFile[],
    encData: boolean,
    onReport: TransferCallback
  ): Promise<boolean> {
    const segFiles: OutgoingFile[] = [];
    const plainFiles: OutgoingFile[] = [];
    for (let i = 0; i < files.length; i++) {
      if (V5Transfer.segEligible(files[i])) {
        segFiles.push(files[i]);
      } else {
        plainFiles.push(files[i]);
      }
    }
    if (!V5Transfer.SEG_SEND_ENABLED) {
      Log.i(TAG, 'v5 发送走 1101 单连接（1110 分片发送已关闭，接收侧仍支持分片）');
    }
    let okAll: boolean = true;
    // 大文件先发（走 1110，自己开 16 条连接，与 1101 的连接互不影响）
    let segFailed: OutgoingFile[] = [];
    if (segFiles.length > 0) {
      // sendSegBatch 返回**分片失败的文件**（空数组 = 全部成功）
      segFailed = await V5Transfer.sendSegBatch(self, target, segFiles, onReport);
    }
    // 其余走原来的 1101 单连接路径（已实机验证成功，保持不动）。
    // ⚠️ 分片失败的文件也并入这里**自动回退重传**：车机版 1.35 等部分对端
    //    不支持 / 无法处理 1110 分片接收，直接走 1101 能保证大文件一定能发出去。
    const retryFiles: OutgoingFile[] = plainFiles.concat(segFailed);
    if (retryFiles.length > 0) {
      if (segFailed.length > 0) {
        Log.w(TAG, `v5 分片失败 ${segFailed.length} 个，自动回退到 1101 单连接重传`);
      }
      const okPlain: boolean = await V5Transfer.sendPlain(self, target, retryFiles, encData, onReport);
      if (!okPlain) {
        okAll = false;
      }
    }
    return okAll;
  }

  /**
   * 是否够格走 1110 分片：**普通文件**（非图片/视频）且 `size >= 128MB`。
   * 阈值与 1.35 的 `0x8000000` 逐位一致。
   */
  private static segEligible(f: OutgoingFile): boolean {
    if (!V5Transfer.SEG_SEND_ENABLED) {
      return false;   // 全局关闭 1110 发送（理由见 SEG_SEND_ENABLED 注释）；接收侧不受影响
    }
    const t: number = V5Transfer.typeOf(f.name);
    if (t !== LCmd.FILE_FILE) {
      return false;   // 1.35：MediaInfo / 媒体类恒不 eligible
    }
    return f.size >= V5Transfer.SEG_MIN_SIZE;
  }

  /** 旧路径：1101 单连接顺序发（原有实现，未改动） */
  private static async sendPlain(
    self: LanDevice,
    target: LanDevice,
    files: OutgoingFile[],
    encData: boolean,
    onReport: TransferCallback
  ): Promise<boolean> {
    const total: number = files.length;
    const client: LanClient = new LanClient();
    let phase: string = 'init';
    try {
      for (let i = 0; i < files.length; i++) {
        if (!files[i].sizeKnown) {
          V5Transfer.report(onReport, 'send', target.devName, files[i].name, i + 1, total,
            0, 0, 0, true, false, `无法读取「${files[i].name}」的大小，已中止发送`);
          return false;
        }
      }

      const connected: boolean = await client.connect(target.devIp, target.devPort);
      if (!connected) {
        const why: string = client.error.length > 0 ? `：${client.error}` : '';
        V5Transfer.report(onReport, 'send', target.devName, '', 0, total, 0, 0, 0, true, false,
          `无法连接 ${target.devName}（${target.devIp}:${target.devPort}）${why}`);
        return false;
      }
      const chan: TcpChannel | null = client.channel;
      if (chan === null) {
        return false;
      }

      // ---- 1. 请求帧：1101 + 设备头 + encData ----
      phase = '构造请求帧';
      const enc: V5Enc = new V5Enc(1024);
      enc.reset(LCmd.FS_SHARE_FILE, files.length);
      // ⚠️ **顺序由 smali 二次取证钉死：payload = [设备头][encData 字节]，设备头在「前」**。
      //   发送端：`LANService.g()` 先调 `r(Device,int)`（16820，写设备头），
      //           再调 `b(encData)`（5063）——encData 追加在设备头之后。
      //   接收端：`LANService` 14973-14978 先 `e(4)` 读 arg，设备头解析器吃掉设备头后
      //           `c()` 才读到 encData。
      // 若反过来先 `byte()` 读 encData，devPort 首字节会被当 encData 吞掉，
      // 整段设备头错位 1 字节（真机日志复现：`V5Codec: 字符串长度越界: 3633 > 78`）。
      V5Transfer.writeHeader(enc, self);
      enc.byte(encData ? 1 : 0);
      await chan.send(enc.bytes());

      // ---- 2. 每个文件一帧（四字段版：长度/名/类型/附加）----
      phase = '构造文件清单帧';
      for (let i = 0; i < files.length; i++) {
        const f: OutgoingFile = files[i];
        const t: number = V5Transfer.typeOf(f.name);
        enc.reset(V5_FRAME_CONT, 0);
        enc.long(f.size);
        enc.string(f.name);
        enc.int(t);
        enc.string('');
        // 图片/视频补一个 long mediaId：1.35 的接收端在 3001/3002 分支里
        // 「剩余 ≥8 字节才读」（smali 15226-15255：`pos+8 <= limit` 才 `h()` 读 long）。
        // 我们写 -1 表示"没有媒体库 ID"，1.35 端这时剩余正好 8 字节，能正确读走。
        if (t === LCmd.FILE_IMAGE || t === LCmd.FILE_VIDEO) {
          enc.long(-1);
        }
        await chan.send(enc.bytes());
      }
      Log.i(TAG, `v5 已发出文件清单（${files.length} 项），等待 ${target.devName} 应答`);

      // ---- 3. 等应答（12 字节头，cmd 在 [0..3]）----
      phase = '等待应答';
      const head: Uint8Array | null = await chan.readExactly(12, 15000);
      if (head === null) {
        const stage: string = chan.isClosed ? '对端在应答前就断开了连接' : '15 秒内没有收到应答';
        V5Transfer.report(onReport, 'send', target.devName, '', 0, total, 0, 0, 0, true, false,
          `${stage}（${target.devName} ${target.devIp}:${target.devPort}）`);
        return false;
      }
      const resp: number = V5Dec.beInt(head, 0);
      if (resp !== LCmd.FS_AGREE) {
        V5Transfer.report(onReport, 'send', target.devName, '', 0, total, 0, 0, 0, true, false,
          `对端拒绝接收（应答码 ${resp}）`);
        return false;
      }

      // ---- 4. 逐个文件：数据片 + FS_END ----
      // ⚠️ 普通文件**没有「第二帧 [long 长度, string 名]」**！1.35 接收端 `LANService.y()`
      //    （17573-17578）在收到 AGREE 后立刻 `iput 0xc, decoder.d`（读指针直接置 12），
      //    立即开始读数据帧。那个「两字段帧」只用于**文件夹子项**
      //    （见 `o2/j` 文件夹分支 418-479 才 `g()/i()` 读 long+name）。
      //    之前多发这一帧，1.35 会把它当数据帧解析（头[0]=0xFF 非法）→ 传输直接失败。
      phase = '发送文件体';
      const grandTotal: number = V5Transfer.sumSize(files);
      let sentBefore: number = 0;
      for (let i = 0; i < files.length; i++) {
        const item: OutgoingFile = files[i];

        phase = '发送文件数据';
        const ok: boolean = await V5Transfer.sendBody(chan, item, encData,
          (sent: number, size: number) => {
            const percent: number = grandTotal > 0
              ? Math.floor((sentBefore + sent) * 100 / grandTotal) : 0;
            V5Transfer.report(onReport, 'send', target.devName, item.name, i + 1, total,
              sent, size, percent, false, true, '');
          });
        if (!ok) {
          V5Transfer.report(onReport, 'send', target.devName, item.name, i + 1, total,
            0, item.size, 0, true, false, `发送失败：${item.name}`);
          return false;
        }
        // FS_END：头[0] 写单字节 2，长度 0
        const endFrame: V5Enc = new V5Enc(64);
        endFrame.setStreamCmd(LCmd.FS_END);
        await chan.send(endFrame.bytes());

        // 对端收完一个文件会往这条流回写单字节：5=FS_NEXT（继续）、6=FS_BREAK（中止）。
        // ⚠️ 1.35 的**发送端**（`LANService.D` 2485-2504）并不死等某个固定值，而是
        //    「available()>0 就 read()，只在读到 6 时判中止」。而且 1.35 的**接收端**
        //    每收完一个文件实际会写**两个字节**（`y()` 的 5 + `o2/j` 的 0x02 状态字节）。
        //    若这里死等「1 字节 ==5」，多文件时会读到残留的 0x02 → 误判中止。
        //    照抄 1.35 语义：首字节等 30s（确保等到对端回应），随后排空剩余字节（短超时），
        //    只有读到 6 才中止。
        let peerBreak: boolean = false;
        for (let k = 0; k < 8; k++) {
          const ack: Uint8Array | null = await chan.readExactly(1, k === 0 ? 30000 : 300);
          if (ack === null) {
            break; // 无更多数据 —— 正常
          }
          if (ack[0] === LCmd.FS_BREAK) {
            peerBreak = true;
            break;
          }
        }
        if (peerBreak) {
          Log.w(TAG, `对端回 FS_BREAK，第 ${i + 1} 个文件中止`);
          return false;
        }
        sentBefore += item.size > 0 ? item.size : 0;
      }

      const allNames: string[] = [];
      for (let i = 0; i < files.length; i++) {
        allNames.push(files[i].name);
      }
      V5Transfer.report(onReport, 'send', target.devName,
        files.length === 1 ? files[0].name : `${files.length} 个文件`,
        total, total, grandTotal, grandTotal, 100, true, true,
        `已发送 ${V5Transfer.human(grandTotal)} 到 ${target.devName}`, allNames);
      return true;
    } catch (e) {
      const err: Error = e as Error;
      const stack: string = (err as Object as ESObject).stack ?? '';
      Log.e(TAG, `v5 发送异常[阶段=${phase}]: ${err.message} | stack=${stack}`);
      V5Transfer.report(onReport, 'send', target.devName, '', 0, total, 0, 0, 0, true, false,
        `发送异常[${phase}]: ${err.message}`);
      return false;
    } finally {
      await client.close();
    }
  }

  // ==================================================================
  // 发送：分段传输（cmd = 1110，1.35 修改版的「16 分片并行」）
  // ==================================================================

  /** 逐文件走 1110 分片并发。返回**分片失败的文件列表**（空 = 全部成功），由调用方决定是否回退 1101。 */
  private static async sendSegBatch(
    self: LanDevice,
    target: LanDevice,
    files: OutgoingFile[],
    onReport: TransferCallback
  ): Promise<OutgoingFile[]> {
    let grandTotal: number = 0;
    for (let i = 0; i < files.length; i++) {
      grandTotal += files[i].size;
    }
    const failed: OutgoingFile[] = [];
    let sentBefore: number = 0;
    for (let i = 0; i < files.length; i++) {
      const ok: boolean = await V5Transfer.sendSegFile(self, target, files[i], onReport,
        i + 1, files.length, grandTotal, sentBefore);
      if (!ok) {
        failed.push(files[i]);
      }
      sentBefore += files[i].size;
    }
    if (failed.length === 0) {
      V5Transfer.report(onReport, 'send', target.devName,
        files.length === 1 ? files[0].name : `${files.length} 个文件`,
        files.length, files.length, grandTotal, grandTotal, 100, true, true,
        `已发送 ${V5Transfer.human(grandTotal)} 到 ${target.devName}（分片并发）`);
    }
    return failed;
  }

  /**
   * 把一个文件按 16 片**并发**发给对端（每片一条独立 TCP 连接）。
   *
   * 单条连接内的字节序列（逐字节对齐 1.35 `LANService.E()`，3101-3500）：
   * ```
   * MAGIC('fgsq')                             建连后立刻写（LanClient 已做）
   * 帧1  [1110][1][len] + **完整设备头** + byte(0)
   *      ← 设备头来自 `r(Device,int)`（16820），E() 是 r()→h(1110)→i(1)→b(0)
   * 帧2  [0][0][len] + long fileSize / String name / String segId
   *                    / int idx / int 16  / long start / long len
   *      ← `new q2.c([B)` 不调 g()，头部保持默认 0
   * 数据帧 头[0] 单字节 1(FS_DATA)、长度在头[8..11]、payload 原始字节
   * 应答  **循环**读裸单字节：`5`(FS_NEXT 流控) 一律**跳过**，直到拿到终态码
   *       `2` = RECV_OK（成功）/ `3` = RECV_FAIL（失败）。
   *       ⚠️ 1.35 每片写的是「5 然后 2/3」两个字节，只读 1 个会误判并触发 RST。
   * ```
   * ⚠️ 1.35 的 `E()` 在帧1 里那个 encData 字节是**写死的 0**
   *    （`int-to-byte v10, v8`，而 v8 = `const/4 v8, 0x0`）—— 1110 通道**不加密**，照抄别改成 1。
   */
  private static async sendSegFile(
    self: LanDevice,
    target: LanDevice,
    item: OutgoingFile,
    onReport: TransferCallback,
    fileIndex: number,
    fileCount: number,
    grandTotal: number,
    sentBefore: number
  ): Promise<boolean> {
    const src: FileSource | null = FileSource.open(item.uri);
    if (src === null) {
      V5Transfer.report(onReport, 'send', target.devName, item.name, fileIndex, fileCount,
        0, item.size, 0, true, false, `无法打开「${item.name}」`);
      return false;
    }
    const fileSize: number = src.size > 0 ? src.size : item.size;
    src.close();
    item.size = fileSize;

    // >=16B 恒为 16 片（对齐 1.35）；极小文件退化为「每片 1 字节」，避免出现空片
    const segTotal: number = fileSize >= V5Transfer.SEG_TOTAL
      ? V5Transfer.SEG_TOTAL : Math.max(1, Math.floor(fileSize));
    const segId: string = V5Transfer.newSegId();
    const st: SegSend = new SegSend();
    st.fileSize = fileSize;
    Log.i(TAG, `v5 分片发送开始 ${item.name} size=${fileSize} segs=${segTotal} segId=${segId}`);

    // 16 条连接共用同一个进度对象；按百分比节流上报，避免高频 emit
    const onTick: () => void = () => {
      const percent: number = grandTotal > 0
        ? Math.floor((sentBefore + st.sent) * 100 / grandTotal) : 0;
      if (percent === st.lastPercent) {
        return;
      }
      st.lastPercent = percent;
      V5Transfer.report(onReport, 'send', target.devName, item.name, fileIndex, fileCount,
        st.sent, fileSize, percent, false, true, '');
    };
    onTick();

    const tasks: Promise<boolean>[] = [];
    for (let i = 0; i < segTotal; i++) {
      // 用「等分端点」而不是「固定步长」：start = floor(i*N/T)，end = floor((i+1)*N/T)。
      // 这样 16 段无缝无叠地铺满 [0, N)，且 N >= 16 时绝不会出现空片。
      const start: number = Math.floor(i * fileSize / segTotal);
      const end: number = Math.floor((i + 1) * fileSize / segTotal);
      tasks.push(V5Transfer.sendOneSegment(self, target, item, fileSize, segId, i, segTotal,
        start, end - start, st, onTick));
    }

    let results: boolean[] = [];
    try {
      results = await Promise.all(tasks);
    } catch (e) {
      const err: Error = e as Error;
      Log.e(TAG, `v5 分片发送异常 ${item.name}: ${err.message}`);
    }
    let okCount: number = 0;
    for (let i = 0; i < results.length; i++) {
      if (results[i]) {
        okCount += 1;
      }
    }
    if (okCount === segTotal) {
      Log.i(TAG, `v5 分片发送完成 ${item.name}（${segTotal} 片，${fileSize} B）`);
      return true;
    }
    // 分片未完成：不在此处下「发送失败」定论 —— 调用方会把它并入 1101 自动回退重传。
    // 仅留一条 warn 供排查（对端可能不支持 1110 分片接收，如部分车机版 1.35）。
    Log.w(TAG, `v5 分片发送失败 ${item.name}：成功 ${okCount}/${segTotal} 片（将回退 1101）`);
    return false;
  }

  /** 发**一片**：独立 TCP 连接 → 帧1 → 帧2 → 数据帧 → 读应答 → 关闭 */
  private static async sendOneSegment(
    self: LanDevice,
    target: LanDevice,
    item: OutgoingFile,
    fileSize: number,
    segId: string,
    idx: number,
    total: number,
    start: number,
    len: number,
    st: SegSend,
    onTick: () => void
  ): Promise<boolean> {
    const client: LanClient = new LanClient();
    try {
      const connected: boolean = await client.connect(target.devIp, target.devPort);
      if (!connected) {
        const why: string = client.error.length > 0 ? `：${client.error}` : '';
        Log.w(TAG, `v5 分片[${idx + 1}/${total}] 连接失败${why}`);
        return false;
      }
      const chan: TcpChannel | null = client.channel;
      if (chan === null) {
        return false;
      }

      // ---- 帧 1：[1110][1][len] + **完整设备头** + 1 字节 encData（恒 0）----
      //
      // ⚠️⚠️ **这一帧必须带设备头** —— 这是 5.0.5 接收失败的根因。
      //
      // 1.35 的 `E()`（LANService 3266）第一步是
      //   `invoke-virtual {v4, v5, v7}, LANService;->r(Device, I)Lq2/c;`
      // 而 `r()`（16820-16950）的实现是：
      //   ```
      //   c = new q2.c(cap)
      //   c.d(devPort); c.f(devIp); c.f(devName); c.d(1);      // devMode = 1
      //   c.f(q2.k.A);  c.d(5);                                // uuid-ver / dataVersion = 5
      //   c.d(battery); c.b(charge);  c.d(knownMap.size()) …   // + 已知设备表
      //   return c                                              // ← 设备头已写进 encoder
      //   ```
      // 也就是说 `r()` 返回的是**已经写好整段设备头的 encoder**，
      // 之后才 `h(1110)`（头偏移 0）/ `i(1)`（头偏移 4）/ `b(0)`（追加 encData 字节）。
      // 所以帧1 的真实字节是：`[1110][1][len]` + 设备头 + `0x00`，len = 设备头长度 + 1。
      //
      // 接收端 `q()`（15443-15446）在 1110 分支里第一件事就是
      //   `invoke-virtual {p1}, Lx1/b;->c()B` —— 读**设备头之后**那 1 字节 encData，
      // 证明帧分发层已经把设备头消费掉了。
      //
      // 之前实现只发 `[1110][1][1] + 0x00`（少一整段设备头），
      // 1.35 读完 cmd/arg/len 后按设备头解析这 1 字节 → 立刻越界错位 → 接收失败。
      const f1: V5Enc = new V5Enc(512);
      f1.reset(LCmd.FS_SEG_FILE, 1);
      V5Transfer.writeHeader(f1, self);
      f1.byte(0);
      await chan.send(f1.bytes());

      // ---- 帧 2：分片元数据 ----
      // ⚠️ 1.35 这里用的是 `new-instance Lq2/c; … <init>([B)`（3287-3291），
      //    **没有调用 `g()`**（`g()` 才会写 h(-1)/i(0)）。而 `<init>` 只设 pos=12，
      //    头部 12 字节保持数组默认值 0 —— 所以帧2 的 cmd/arg 都是 **0**，不是 -1。
      //    接收端 `q()` 只读 `f()`(len) 与 payload，不校验 cmd，改成 0 是纯对齐。
      const f2: V5Enc = new V5Enc(1024);
      f2.reset(0, 0);
      f2.long(fileSize);
      f2.string(item.name);
      f2.string(segId);
      f2.int(idx);
      f2.int(total);
      f2.long(start);
      f2.long(len);
      await chan.send(f2.bytes());

      // ---- 数据帧 ----
      if (len > 0) {
        const src: FileSource | null = FileSource.open(item.uri);
        if (src === null) {
          return false;
        }
        try {
          if (!src.seek(start)) {
            return false;
          }
          const frame: V5Enc = new V5Enc(CHUNK + 64);
          let sent: number = 0;
          while (sent < len) {
            const want: number = Math.min(CHUNK, len - sent);
            const chunk: Uint8Array | null = src.readChunk(want);
            if (chunk === null) {
              break;
            }
            const n: number = chunk.length;
            frame.resetKeepHeader();
            frame.setStreamCmd(LCmd.FS_DATA);
            frame.rawBuffer().set(chunk.subarray(0, n), 12);
            frame.advance(n);
            await chan.send(frame.bytes());
            sent += n;
            st.sent += n;
            onTick();
          }
          if (sent !== len) {
            Log.w(TAG, `v5 分片[${idx + 1}/${total}] 只发出 ${sent}/${len}`);
            return false;
          }
        } finally {
          src.close();
        }
      }

      // ---- 片级结束帧（5.0.25 定案）----
      //
      // ⚠️⚠️ **这一帧此前一直没发，是「本机 16 片全绿、对端 1.35 却报接收失败」的根因。**
      //
      // 接收端判定「这一片结束」靠的是 **FS_END 结束帧**，不是「累计收满 len 字节」：
      //   · 本机 `receiveSegment` 的片内循环第一步就是 `if (cmd === LCmd.FS_END) break;`
      //     —— 当初就是照 1.35 的 `Lo2/n` 逐条对齐写出来的；
      //   · 1.35 侧同理：收满数据后还要再读一帧，读到 FS_END 才退出循环，
      //     然后才 `z()` 写 5、`B()` 写 2/3（片级终态）。
      //
      // 而本机发送侧（5.0.24 及更早）在发完最后一个数据块后**直接进应答循环**，
      // 从没补发这一帧 → 对端永远停在 read() 上等片尾 → 既不回 5 也不回 2
      // → 16 片全部「块已确认、终态不来」→ 5.0.24 兼容判定把它们判成成功并 close
      // → 对端 read 异常/EOF → **对端报接收失败**（本机日志却全绿）。
      //
      // 与 1101 单连接通道对齐：`sendPlain` 每个文件发完都补这一帧（sendBody 之后）。
      const segEndFrame: V5Enc = new V5Enc(64);
      segEndFrame.setStreamCmd(LCmd.FS_END);
      await chan.send(segEndFrame.bytes());

      // ---- 应答：**必须一直读到终态码为止** ----
      //
      // ⚠️⚠️ 这里踩过一个致命坑：1.35 每片写的是**两个**字节，不是一个。
      //   · `z()`  收完这片后先写 1 个 **5**（FS_NEXT，「继续」流控）—— LANService 19322-19331
      //   · `B()`  紧接着再写 1 个 **2**(FS_END/RECV_OK) 或 **3**(FS_CLOSE/RECV_FAIL)
      //            —— LANService 1844-1858：`if (ok) v0=2 else v0=3; out.write(v0); flush()`
      //
      // 而 1.35 自己的发送端 `E()` 的读法是「**循环读、把所有 5 跳过、直到拿到非 5 的终态码**」：
      //   `read() → v4`（3420）；`if (v4 == 5) goto :cond_4`（3437）；
      //   而 `:cond_4` 就是 `goto :goto_0`（3595-3598）—— 回到 read 再读一个。
      //
      // 5.0.6 只 `readExactly(1)` 拿了第 1 个字节（=5），于是：
      //   ① 把「流控 5」误判成成功；
      //   ② 真正的 2/3 还留在**本端接收缓冲**里；
      //   ③ 紧接着 `client.close()` —— 内核发现接收缓冲非空，发的是 **RST 而不是 FIN**；
      //   ④ 1.35 端随即 ECONNRESET → `u.m = true` → `SEG-DONE … status=BROKEN` → **接收失败**。
      //   （16 片各自如此，所以报错是稳定复现的，而发送侧日志却"全绿 resp=5"。）
      //
      // 结论：读到 **2** 才允许关连接；3 是失败；5 必须跳过。
      // ---- 5.0.24：对端未回片级终态时的兜底判定（避免整份大文件被重传一遍）----
      //
      // 真机实证（2026-10-01 18:43，手机热点直连车机 1.35）：
      //   16 片数据在 ~18s 内发完，每片都收到 **41 个**块级 FS_NEXT(5)
      //   —— 一片 42343850 B / CHUNK(1048564) 正好 41 块，
      //     说明对端**每个数据块都确认收到**了，却始终没有一片等到终态 2
      //   → 16 片全判失败 → 回退 1101 把 677MB **再传一遍**
      //     （表现为：进度条到 100% 后卡住，然后从头重发）。
      //
      // ⚠️ vivi 实测澄清（决定了修法方向）：
      //   · 热点**并不比局域网慢** → 不是超时问题，**不要**放宽等待；
      //   · 中午 11:57~14:00 给同一台车机发大文件是**立即完成、没有等待**的
      //     → 对端**会**回片级终态 2，不能武断认定「1.35 不回终态」。
      //   所以这里只改「判定」，不动等待时长：正常对端依旧毫秒级拿到 resp=2。
      //
      // 修法（保留 1110 发送，仅调整判定）：
      //   ① 先把本片所有数据块的 ack 收齐（hopCount >= 本片块数 blocks）；
      //   ② 收齐后只再等 SEG_TERM_GRACE_MS 短窗口等终态 2（正常对端立刻回）；
      //   ③ 窗口内仍无终态、但块已全部 ack **且连接未断** → 判定**成功**，不再回退重传。
      let status: number = -1;
      let hopCount: number = 0;
      // 本片数据块数：发送时每块最多 CHUNK 字节，对端每收一块回一个 5
      const blocks: number = len > 0 ? Math.ceil(len / CHUNK) : 0;
      const deadline: number = Date.now() + 30000;
      let graceUntil: number = 0;   // 块收齐后等终态的宽限截止时刻（0 = 尚未收齐）
      while (Date.now() < deadline) {
        if (blocks > 0 && hopCount >= blocks) {
          if (graceUntil === 0) {
            graceUntil = Date.now() + V5Transfer.SEG_TERM_GRACE_MS;
          }
          if (Date.now() >= graceUntil) {
            break;   // 宽限窗口已过：对端这次未回片级终态
          }
        }
        const remain: number = (graceUntil > 0 ? graceUntil : deadline) - Date.now();
        const one: Uint8Array | null = await chan.readExactly(1, Math.max(500, remain));
        if (one === null) {
          break;
        }
        if (one[0] === LCmd.FS_NEXT) {
          hopCount += 1;
          continue;   // 5 = 流控「继续」，跳过，继续等终态码
        }
        status = one[0];
        break;
      }
      if (status === -1) {
        // 没等到终态码：若本片所有数据块都已被对端 ack **且连接未断开**，
        // 说明数据已完整送达（TCP 保证有序），只是对端这次没回那 1 字节片级收尾 → 判成功。
        // （连接若已断，说明对端真的出问题了，照旧回退 1101 重传，不冒险。）
        if (len > 0 && blocks > 0 && hopCount >= blocks && !chan.isClosed) {
          Log.i(TAG, `v5 分片[${idx + 1}/${total}] 完成 segId=${segId} start=${start} len=${len} `
            + `对端未回片级终态，但 ${hopCount}/${blocks} 块已全部确认且连接未断（兼容模式）`);
          return true;
        }
        Log.w(TAG, `v5 分片[${idx + 1}/${total}] 未收到终态应答`
          + `（已跳过 ${hopCount} 个流控字节，本片共 ${blocks} 块，连接${chan.isClosed ? '已断' : '未断'}）`);
        return false;
      }
      if (status !== LCmd.FS_END) {
        Log.w(TAG, `v5 分片[${idx + 1}/${total}] 对端终态码 ${status}（非 RECV_OK=2），这片失败`);
        return false;
      }
      Log.i(TAG, `v5 分片[${idx + 1}/${total}] 完成 segId=${segId} start=${start} len=${len} resp=${status} 流控${hopCount}`);
      return true;
    } catch (e) {
      const err: Error = e as Error;
      Log.e(TAG, `v5 分片[${idx + 1}/${total}] 异常: ${err.message}`);
      return false;
    } finally {
      await client.close();
    }
  }

  /** segId：对齐 1.35 的 `q2/k.U0()` = `UUID.randomUUID()` 去横线（32 位十六进制） */
  private static newSegId(): string {
    try {
      return util.generateRandomUUID(false).split('-').join('');
    } catch (e) {
      // 极端兜底：UUID 不可用时用「时间戳 + 随机数」，进程内唯一即可
      const r: number = Math.floor(Math.random() * 4294967296);
      return `${Date.now().toString(16)}${r.toString(16)}`;
    }
  }

  /**
   * 发一个文件的全部字节。
   *
   * 每片都套 12 字节帧头（cmd 单字节写在头[0]，长度在头[8..11]），
   * 头与数据**一次**写出 —— 分两次会让那 12 字节独立成小包，多付一个 RTT。
   */
  private static async sendBody(
    chan: TcpChannel,
    item: OutgoingFile,
    encData: boolean,
    onChunk: (sent: number, size: number) => void
  ): Promise<boolean> {
    // ★★ 5.1.20（探针）：本版统计对端回了多少块级 ack、在第几块停止回应。
    //   1.35 是背靠背流控（每收一块回 1 字节），官方 1.2.8 不回 —— 两者行为不同，
    //   而旧实现**从不读 ack**，所以 1.35 一旦因 ack 堆积而错位，我方毫无察觉。
    let ackCount: number = 0;
    let ackBreakAt: number = -1;
    const startedAt2: number = Date.now();
    const src: FileSource | null = FileSource.open(item.uri);
    if (src === null) {
      return false;
    }
    const size: number = src.size > 0 ? src.size : item.size;
    item.size = size;
    if (size === 0) {
      src.close();
      return true;
    }
    let subTotal: number = 0;
    let lastPercent: number = 0;
    const startedAt: number = Date.now();
    let chunkCount: number = 0;
    const frame: V5Enc = new V5Enc(CHUNK + 64);
    try {
      while (subTotal < size) {
        const want: number = Math.min(CHUNK, size - subTotal);
        const chunk: Uint8Array | null = src.readChunk(want);
        if (chunk === null) {
          break;
        }
        const n: number = chunk.length;
        if (encData) {
          FileCrypto.encData(chunk, n, 0, subTotal);
        }
        frame.resetKeepHeader();
        frame.setStreamCmd(LCmd.FS_DATA);
        frame.rawBuffer().set(chunk.subarray(0, n), 12);
        frame.advance(n);
        await chan.send(frame.bytes());
        subTotal += n;
        chunkCount += 1;
        // ★★ 5.1.19：在途量闸门 —— 每发 SEND_INFLIGHT_BLOCKS 块让一帧，
        //   把「一次连续 push 进内核的字节数」压到 N × CHUNK，
        //   间接约束在途量（1.35 大文件失败的直接对策），**不碰 SO_SNDBUF**
        //   ⇒ 内核自动调优带来的提速得以保留。
        //   ⚠️ 0 = 关闭（等于 5.1.17 行为）；1 = 每块让一帧（最接近 5.1.12）。
        if (SEND_INFLIGHT_BLOCKS > 0 && chunkCount % SEND_INFLIGHT_BLOCKS === 0) {
          await sendYieldFrame();
        }
        // ★★ 5.1.20（探针）：**读掉对端的块级 ack**。
        //   1.35 每收一块回 1 字节；官方 1.2.8 不回（这里会短超时返回 null，无害）。
        //   ⚠️ 用**极短超时**（默认 0 = 立刻返回，绝不等）——
        //     不用 `readExactly(1, 0)`：它每次超时都打一条 W 日志（647 块 = 647 条噪音）。
        //   读到 6（FS_BREAK）⇒ 立刻判失败，并记下断在第几块。
        let gotAck: boolean = false;
        try {
          const a1: Uint8Array | null = await chan.readSome(1, 0);
          if (a1 !== null) {
            gotAck = true;
            ackCount += 1;
            if (a1[0] === LCmd.FS_BREAK) {
              ackBreakAt = chunkCount;
            }
          }
        } catch (e) {
          // 读不到就当没回，不影响流程
        }
        if (ackBreakAt >= 0) {
          Log.w(TAG, `v5 [ACK] 对端在第 ${ackBreakAt} 块回 FS_BREAK(6)`
            + `（已发 ${subTotal}/${size} B，共 ${chunkCount} 块，收到 ${ackCount} 个 ack）`);
          return false;
        }
        if (gotAck && chunkCount % 64 === 0) {
          Log.i(TAG, `v5 [ACK] blk#${chunkCount} 累计收到 ${ackCount} 个块级 ack`
            + `（${subTotal} / ${size} B）`);
        }
        const percent: number = Math.floor(subTotal * 100 / size);
        if (percent !== lastPercent || subTotal >= size) {
          lastPercent = percent;
          onChunk(subTotal, size);
        }
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `v5 发送文件块失败: ${err.code} ${err.message}`);
      return false;
    } finally {
      src.close();
    }
    if (subTotal !== size) {
      Log.w(TAG, `文件 ${item.name} 发送字节数不符: ${subTotal} != ${size}`);
      return false;
    }
    const ms: number = Date.now() - startedAt;
    // ★★ 5.1.20（探针）：汇总里带上 ack 统计 ——
    //   ackCount / chunkCount 就是「对端实际回了几次块级 ack」，
    //   与块数一致 ⇒ 流控正常；为 0 ⇒ 对端完全没回（官方 1.2.8 属正常）。
    Log.i(TAG, `v5 已发送 ${item.name} (${subTotal} B, ${chunkCount} 片, ${ms}ms,`
      + ` ack=${ackCount}, 耗时 ${Date.now() - startedAt2}ms)`);
    return true;
  }

  // ==================================================================
  // 接收
  // ==================================================================

  /**
   * 收一批文件。
   *
   * 调用前提：调用方已经读完第一帧（设备头已解析），`count` 取自帧头的 arg 字段。
   *
   * @param encData 由调用方从第一帧 payload 的 byte 读出后传入
   */
  static async receive(
    chan: TcpChannel,
    from: LanDevice,
    count: number,
    encData: boolean,
    storage: FileStorage,
    onReport: TransferCallback,
    onLog?: (s: string) => void,
    /**
     * ★ 5.0.58：对端是**按 N+1 读 ack** 的实现（PC 端）时为 true。
     *
     * ⚠️ 实测字节数（`tests/live-probe/v5_multifile_probe.mjs`）：
     *   我方每文件回 `5`×N（块级）+ `5` + `2` = **N+2**；
     *   而 PC 端每文件只读 N（块级，`LANShare.cpp:250`）+ 1（文件间，`598`）= **N+1**。
     *   ⇒ 每文件多送 1 字节 ⇒ 从第 2 个文件起 PC 读到的是**残留字节**，
     *     它因此不再按块等待（节流失效），一路狂发 → 把接收窗口压满 →
     *     触发上面那条「部分发送 → FS_CLOSE → 干等 60 秒」的链。
     *   命中本标志时文件收尾**只回 `2`**（N+1）；默认 false = 保持现状 `5`+`2`（N+2，
     *   1.35 Android 需要那个 5，见 5.0.48）。**判据失误只会退回现状，不会引入回归。**
     */
    pcStyleAck: boolean = false
  ): Promise<boolean> {
    try {
      // ---- 1. 逐个读条目帧（四字段版）----
      const items: V5Incoming[] = [];
      for (let i = 0; i < count; i++) {
        const body: Uint8Array | null = await V5Transfer.readFrameBody(chan);
        if (body === null) {
          return false;
        }
        const d: V5Dec = new V5Dec(body, 0);
        const it: V5Incoming = new V5Incoming();
        it.length = d.long();
        it.name = d.string();
        it.fileType = d.int();
        d.string(); // 附加字段（视频时长 / 空串）
        if (it.fileType === LCmd.FILE_FOLDER) {
          // 文件夹：子文件会在同一个流里顺序跟下来，鸿蒙侧没有对应的目录结构支持。
          // 直接拒绝比"收一半然后错位"好 —— 对端会看到明确的拒绝。
          Log.w(TAG, `v5 收到文件夹「${it.name}」，鸿蒙侧暂不支持，已拒绝`);
          await chan.send(V5Transfer.simpleFrame(LCmd.FS_NOT_AGREE));
          return false;
        }
        if (it.fileType === LCmd.FILE_IMAGE || it.fileType === LCmd.FILE_VIDEO) {
          // ⚠️ 1.35 仅在 mediaId > -1 时才写这 8 字节（smali 5474-5511 的 if-lez 分支）。
          // 大多数从文件选择器来的图片 mediaId = -1，根本不写这 8 字节。
          // 无脑读会把下一帧的字节当 mediaId 吞掉，多文件传输直接错位。
          // 仅当还有 ≥8 字节可读时才读；不够就是发送端没写，直接跳过。
          if (d.remaining >= 8) {
            d.long();
          }
        }
        items.push(it);
        Log.i(TAG, `v5 清单项[${i}] type=${it.fileType} size=${it.length} name=${it.name} rem=${d.remaining}`);
        if (onLog) {
          onLog(`v5 清单[${i + 1}/${count}] type=${it.fileType} size=${it.length} "${it.name}" 帧内剩余=${d.remaining}`);
        }
      }
      if (items.length === 0) {
        Log.w(TAG, 'v5 文件清单为空，拒绝');
        await chan.send(V5Transfer.simpleFrame(LCmd.FS_NOT_AGREE));
        return false;
      }

      // ---- 2. 同意（与原版默认行为一致：不弹确认框）----
      await chan.send(V5Transfer.simpleFrame(LCmd.FS_AGREE));
      if (onLog) {
        onLog(`v5 已回同意（AGREE），等待 ${items.length} 项数据流…`);
      }
      const names: string[] = [];
      for (let i = 0; i < items.length; i++) {
        names.push(items[i].name);
      }
      Log.i(TAG, `v5 接收来自 ${from.devName} 的 ${items.length} 项: ${names.join(', ')}`);

      // ---- 3. 逐项收：数据片 → 回 FS_NEXT（无「第二帧」，见下）----
      let grand: number = 0;
      for (let i = 0; i < items.length; i++) {
        grand += items[i].length;
      }
      let done: number = 0;
      for (let i = 0; i < items.length; i++) {
        const item: V5Incoming = items[i];
        if (onLog) {
          onLog(`v5 开始收第 ${i + 1}/${items.length} 项 "${item.name}"（${item.length} B）`);
        }
        // ⚠️ 普通文件**没有「第二帧 [long 长度, string 名]」**：1.35 发送端 `LANService.g()`
        //    每个文件只发**一帧**清单（M2 在循环尾 6438），AGREE 之后直接开始发数据帧；
        //    接收端 `LANService.y()`（17573-17578）也是 AGREE 后立即读数据帧。
        //    之前在这里多读一帧，会把 1.35 的第一个**数据帧头**当成声明长度/名字，
        //    之后全流程错位 → 收发失败 / 收到 0 字节。
        const ok: boolean = await V5Transfer.recvBody(chan, item, encData, storage,
          (got: number, size: number) => {
            const percent: number = grand > 0 ? Math.floor((done + got) * 100 / grand) : 0;
            V5Transfer.report(onReport, 'recv', from.devName, item.name, i + 1, items.length,
              got, size, percent, false, true, '');
          }, onLog);
        // 收完（无论成败）都要回一个字节：发送端在等它，不回会挂到超时。
        // ★ 5.0.62 ★ 但 pcStyleAck（PC 端每文件只读 N+1 个字节）时**不能在这里发**：
        //   下面 pcStyleAck 分支还会再发一个终态 2，两者叠加就是「每文件多发 1 字节」。
        //   后果不是简单的多 1 字节，而是**对流控的连锁破坏**：
        //     多出的 1 字节留在对端内核接收缓冲 → 第 k 项开始时已积压 k-1 字节
        //     → 对端块级 recvo(1) 前 k-1 次读到的是**过期字节**，等于不再等我们 ack
        //     → 「一块一等」流控失效 → 对端把整个文件猛灌进 socket
        //     → 对端大块（修改版 PC 实测块尺寸 = 2 MB）::send 部分返回
        //     → 对端判失败 → 发 FS_CLOSE 放弃本项 → 我们的**余数块**永远读不满
        //     → 60 秒超时。
        //   ★ 真机铁证：失败恒在**最后一项的最后一块**（已收 = n × 2097140，
        //     差的正是余数块），与文件大小无关、与**位置**强相关 —— 因为积压字节数
        //     恰好等于项序号。
        //   ★ 计数核对：块级 ack C 次 + 终态 2 一次 = C+1，与对端
        //     「循环内 C 次 + 循环外 1 次」严格相等 ⇒ 流控恢复。
        const needLevelAck: boolean = !ok || !pcStyleAck;
        if (needLevelAck) {
          const ack: Uint8Array = new Uint8Array([ok ? LCmd.FS_NEXT : LCmd.FS_BREAK]);
          // ★ 5.0.58：发送失败必须喊出来 —— 对端正阻塞等这一字节
          try {
            const ackSent: boolean = await chan.sendChecked(ack);
            if (!ackSent) {
              Log.e(TAG, 'v5 文件级应答发送失败: 通道已关');
              if (onLog) {
                onLog(`v5 "${item.name}" 文件级应答发送失败（对端会一直等）：通道已关`);
              }
            }
          } catch (se) {
            const sex: Error = se as Error;
            Log.e(TAG, `v5 文件级应答发送失败: ${sex.message}`);
            if (onLog) {
              onLog(`v5 "${item.name}" 文件级应答发送失败（对端会一直等）：${sex.message}`);
            }
          }
        }
        // 5.0.48：文件级收尾还必须再补一个终态 2（FS_END / RECV_OK），与**片级收尾**
        //   完全一致（见 receiveSegment 尾部：同样是「先 5 再 2」）。
        //   1.35 接收端文件收完时也写 2（取证 dump Lo2/j）；而 1.35 发送端读到 5 后
        //   **还会再读一个字节** —— 只回 5 时它一直阻塞到我们关连接为止。
        //   真机症状：单项「看着成功」（靠关连接收尾），多项从第 2 项起永远等不到
        //   数据（第 1 项收满后第 2 项 60s 超时、0 字节）—— 正是本行缺失导致。
        if (ok) {
          if (pcStyleAck) {
            // ★ 5.0.58：PC 端每文件只读 N+1 个字节，多送的那个 `5` 会让它的
            //   块级读取整体错位一位（详见形参注释）⇒ 这里**只回终态 2**。
            try {
              await chan.send(new Uint8Array([LCmd.FS_END]));
            } catch (se2) {
              const sex2: Error = se2 as Error;
              Log.e(TAG, `v5 终态应答发送失败: ${sex2.message}`);
              if (onLog) {
                onLog(`v5 "${item.name}" 终态应答发送失败（对端会一直等）：${sex2.message}`);
              }
            }
            if (onLog) {
              onLog(`v5 "${item.name}" 收尾已回 2（PC 端按 N+1 读，故不发多余的那个 5）`);
            }
          } else {
            try {
              await chan.send(new Uint8Array([LCmd.FS_NEXT]));
            } catch (se3) {
              const sex3: Error = se3 as Error;
              Log.e(TAG, `v5 收尾 5 发送失败: ${sex3.message}`);
            }
            try {
              await chan.send(new Uint8Array([LCmd.FS_END]));
            } catch (se4) {
              const sex4: Error = se4 as Error;
              Log.e(TAG, `v5 终态应答发送失败: ${sex4.message}`);
              if (onLog) {
                onLog(`v5 "${item.name}" 终态应答发送失败（对端会一直等）：${sex4.message}`);
              }
            }
            if (onLog) {
              onLog(`v5 "${item.name}" 收尾已回 5+2（FS_NEXT+FS_END），可继续下一项`);
            }
          }
        }
        if (!ok) {
          V5Transfer.report(onReport, 'recv', from.devName, item.name, i + 1, items.length,
            0, item.length, 0, true, false, `接收失败：${item.name}`);
          if (onLog) {
            onLog(`v5 第 ${i + 1}/${items.length} 项 "${item.name}" 接收失败，本连接结束`);
          }
          return false;
        }
        done += item.length;
      }

      // ★★★ 5.1.55：**names 也要同步改名结果**。
      //   `names` 是在**收文件之前**就 `push(items[i].name)` 填好的**副本**，
      //   回写 `items[i].name` 不会更新它 ⇒ 文件页列表（走 `fileNames`）仍显示旧名。
      for (let i = 0; i < items.length; i++) {
        names[i] = items[i].name;
      }
      V5Transfer.report(onReport, 'recv', from.devName,
        items.length === 1 ? items[0].name : `${items.length} 个文件`,
        items.length, items.length, grand, grand, 100, true, true,
        `已接收 ${items.length} 项，保存到 ${storage.describe}`, names);
      return true;
    } catch (e) {
      const err: Error = e as Error;
      Log.e(TAG, `v5 接收异常: ${err.message}`);
      V5Transfer.report(onReport, 'recv', from.devName, '', 0, 1, 0, 0, 0, true, false,
        `接收异常: ${err.message}`);
      return false;
    }
  }

  // ==================================================================
  // 接收：分段传输（cmd = 1110，1.35 修改版的「16 分片并行」）
  // ==================================================================

  /**
   * 收一个**分片**（cmd=1110）。
   *
   * 与 `receive()`（1101）的关键差别：
   *   - 首帧 payload 只有 1 字节（encData 标志），**没有设备头**；
   *   - 第二帧才是元数据：
   *     `[long 文件大小][str 名][str segId][int idx][int total][long start][long len]`；
   *   - 数据帧与 1101 **同构**（12 字节头、流命令在 head[0]、长度在 head[8..11]），
   *     但只收 `len` 个字节，且**按 `start` 随机写**（不是顺序 append）；
   *   - 16 条连接并发写同一个文件，靠 `segId` 认领同一个 SegPart。
   *
   * 应答：收完一片回**两个裸单字节** —— 先 `5`（FS_NEXT，流控「继续」），再 `2`（FS_END/RECV_OK）；
   * 失败回 `3`（FS_CLOSE/RECV_FAIL）。与 1.35 自己的分片接收端逐字一致：
   * `z()` 写 5（LANService 19322-19331），`B()` 写 2/3（1844-1858 `if(ok) v0=2 else v0=3`）。
   * ⚠️ 只回 5 不对：1.35 的发送端 `E()` 读到 5 会 `goto :cond_4` **再读一个**（3419-3437），
   *    于是对端只能靠「本端 close」来收尾，属于隐含时序依赖。
   *
   * ⚠️ **解密 index 用「分片内相对偏移」，不是文件绝对偏移**：
   *   1.35 的 `z()` 给接收线程 `o2/b` 的 `long[]` 是 `{0}`（LANService 18869-18875），
   *   而 `{start}` 那个数组只用于 `RandomAccessFile.seek`（19121-19138）。
   *   若错用 `start + got`，除第 0 片外全部字节会被多 XOR 一个 `start & 0xFF`。
   *
   * @param encData 首帧 payload 的 encData 标志
   */
  static async receiveSegment(
    chan: TcpChannel,
    encData: boolean,
    storage: FileStorage,
    fromName: string,
    onReport: TransferCallback
  ): Promise<boolean> {
    // ---- 1. 读第二帧：分片元数据 ----
    const body: Uint8Array | null = await V5Transfer.readFrameBody(chan);
    if (body === null) {
      Log.w(TAG, 'v5 分片：读取元数据帧失败');
      return false;
    }
    const d: V5Dec = new V5Dec(body, 0, body.length);
    const fileSize: number = d.long();
    const name: string = d.string();
    const segId: string = d.string();
    const idx: number = d.int();
    const total: number = d.int();
    const start: number = d.long();
    const len: number = d.long();
    Log.i(TAG, `v5 分片[${idx + 1}/${total}] segId=${segId} start=${start} len=${len} fileSize=${fileSize} name=${name} encData=${encData}`);

    if (name.length === 0 || segId.length === 0 || start < 0 || len < 0 || fileSize < 0) {
      Log.w(TAG, `v5 分片元数据非法（name=${name} segId=${segId} start=${start} len=${len}）`);
      await V5Transfer.sendByte(chan, LCmd.FS_CLOSE);
      return false;
    }

    // ---- 2. 认领/新建共享文件 ----
    let st: SegPart | undefined = V5Transfer.segs.get(segId);
    if (st === undefined) {
      V5Transfer.purgeFinished();   // 顺手清理收齐超时的旧条目，避免 Map 无限增长
      const created: SegPart | null = V5Transfer.createSegPart(storage, name, fileSize, total);
      if (created === null) {
        await V5Transfer.sendByte(chan, LCmd.FS_CLOSE);
        return false;
      }
      V5Transfer.segs.set(segId, created);
      st = created;
      Log.i(TAG, `v5 分片：新建目标 ${created.path}（${fileSize} B / ${total} 片）`);
      V5Transfer.report(onReport, 'recv', fromName, name, 1, total, 0, fileSize, 0, false, true,
        `开始接收 ${name}（分片传输 ${total} 片）`);
    }
    const part: SegPart = st;

    /**
     * 本片要不要计入「全局已收字节」。
     *
     * 16 片并发时同一 idx 不可能同时来两次（1.35 每片独占一条 TCP），
     * 这里防的是**重传**：若该 idx 之前已收齐过，就不再重复累加，
     * 否则 `part.received` 会超过 fileSize，进度条冲到 100% 之后还在涨。
     */
    const idxKnown: boolean = idx >= 0 && idx < part.gotIdx.length;
    const counts: boolean = !idxKnown || !part.gotIdx[idx];

    // ---- 3. 收本片数据，按 start 随机写 ----
    // ⚠️ 写入用「每块新开 fd」而不是共享 fd：
    //   SDK 的 `WriteOptions.offset` 语义是「当前 filePointer + offset」
    //   （@ohos.file.fs.d.ts:5738-5748）。新开的 fd filePointer=0，
    //   于是 `{offset: 文件绝对偏移}` 在「相对」与「绝对」两种实现下**都**落在同一位置，
    //   16 条并发连接也绝不会互相打架。每片通常只有 1 块，开销量可忽略。
    let got: number = 0;
    let ok: boolean = true;
    // 上一次「让帧给 UI」的时刻。见 UI_YIELD_BUDGET 的注释。
    let lastYieldAt: number = Date.now();
    // ---- 本连接**独占**的写句柄 ----
    // 一次 receiveSegment 调用 = 一条 TCP 连接 = 一整片。片内所有块共用这一个 fd，
    // 全程只 open/close 各一次。
    // ⚠️ 原来是「每块都 openSync + closeSync」：1GB 文件 ≈ 1000 次同步 open/close，
    //    全部跑在 UI 线程上（ArkTS 单线程），既拖慢落盘（进度显不出来、末段猛涨），
    //    又直接吃掉界面的响应时间（vivi 2026-10-01 真机：「界面卡顿」）。
    // ⚠️ 每个 fd 有**独立的 filePointer**，16 条连接各持一个 → 互不干扰。
    //    这正是能安全复用的前提：若 16 条连接共享同一个 fd，
    //    `write` 会各自推进同一个 filePointer，写入位置必然错乱。
    let wrFd: number = -1;
    try {
      wrFd = fileIo.openSync(part.path, fileIo.OpenMode.READ_WRITE).fd;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `v5 分片打开目标文件失败 ${part.path}: ${err.code} ${err.message}`);
      await V5Transfer.sendByte(chan, LCmd.FS_CLOSE);
      return false;
    }
    try {
      // 是否读到过「片级 FS_END」——用于区分「收满 len 退出」与「收到片尾帧退出」。
      // 前者时，对端补发的那一帧还留在流里，循环外必须消费掉（见下方）。
      let sawEnd: boolean = false;
      while (got < len) {
        const head: Uint8Array | null = await chan.readExactly(12, 60000);
        if (head === null) {
          ok = false;
          break;
        }
        const cmd: number = head[0] & 0xFF;
        const flen: number = V5Dec.beInt(head, 8);
        if (cmd === LCmd.FS_END) {
          sawEnd = true;
          break; // 发送端声明本片结束
        }
        if (cmd !== LCmd.FS_DATA) {
          Log.w(TAG, `v5 分片收到非数据帧 cmd=${cmd}`);
          ok = false;
          break;
        }
        if (flen <= 0 || flen > MAX_FRAME) {
          Log.e(TAG, `v5 分片长度异常: ${flen}`);
          ok = false;
          break;
        }
        const chunk: Uint8Array | null = await chan.readExactly(flen, 60000);
        if (chunk === null) {
          ok = false;
          break;
        }
        if (encData) {
          // ⚠️ 逐字节 JS 循环，**同步**跑在主线程上，一块最大可以到 8MB（MAX_FRAME）。
          //    整块解 = 一次按住主线程上百毫秒 → 界面/Tab 动画全被拖住。
          //    按 DEC_SLICE 切片，并在累计超过预算时让出一帧。
          //    index 用「本片内相对偏移 + 片内已收」= got + off，与发送端严格对齐。
          let off: number = 0;
          while (off < flen) {
            const slice: number = Math.min(DEC_SLICE, flen - off);
            FileCrypto.decData(chunk, slice, off, got + off);
            off += slice;
            if (Date.now() - lastYieldAt >= UI_YIELD_BUDGET) {
              lastYieldAt = Date.now();
              await V5Transfer.yieldFrame();
            }
          }
        }
        if (!await V5Transfer.writeAtFd(wrFd, chunk, start + got)) {
          ok = false;
          break;
        }
        got += flen;
        // ★ 块级应答（5.0.19）：16 片并发时每条连接各自回各自的，
        //   与下面「累加 + 节流」的共享状态互不相干。
        //   ⚠️ 必须在 `part.received += flen` **之前**：那之后到节流判断之间
        //     不能出现 await（见下方原注释），否则进度上报会交错乱跳。
        await V5Transfer.sendByte(chan, LCmd.FS_NEXT);
        // ---- 全局进度：每落地一块就累加到**跨片共享**的计数器 ----
        // ⚠️ 曾经上报的是 `part.received + got`，也就是「已完成片的字节和 + 本片自己的
        //    已收字节」。16 片是**并发同时推进**的：每条连接各自报自己的局部值，
        //    收得快的连接报大数、慢的报小数，互相覆盖 → 进度条在低区间来回跳；
        //    等 16 片几乎同时收满，`part.received` 一次性跳到 fileSize → 直接 100%。
        //    （vivi 2026-10-01 真机反馈：一直 1%~2% 跳动，然后立马 100%）
        //    改成累加共享计数器后，任何一次上报的分子都是「全局已落地字节」，
        //    必然单调递增，与哪条连接上报无关。
        //    ⚠️ 这里与 `got += flen` 之间**没有 await**，而 ArkTS 是单线程事件循环，
        //       所以两个并发片不会交错到一半 —— 累加是安全的。
        if (counts) {
          part.received += flen;
        }
        // 节流用 **SegPart 上的共享状态**（见字段注释）：
        //   · 百分比变了就报（进度连续）；
        //   · 百分比长时间不变也至少每 300ms 报一次（不让进度条"装死"）。
        // ⚠️ 从 `part.received += flen` 到这里**没有 await**，ArkTS 单线程事件循环
        //    不会在中间切走，所以「判断 + 写回 lastReportPct」是原子的：
        //    第一条通过的连接立刻把 lastReportPct 更新掉，其余 15 条看到同值自然跳过。
        const nowMs: number = Date.now();
        const pct: number = part.fileSize > 0
          ? Math.min(99, Math.floor(part.received * 100 / part.fileSize)) : 0;
        if (pct !== part.lastReportPct || nowMs - part.lastReportAt >= 300) {
          part.lastReportAt = nowMs;
          part.lastReportPct = pct;
          // ★ 5.1.44：标记这是**分片**进度（fileIndex/Count 是片数，不是文件数）
          V5Transfer.report(onReport, 'recv', fromName, part.name, part.done, total,
            part.received, part.fileSize, pct, false, true, '', [], true);
        }
        // ⚠️ 让帧必须放在「累加 + 节流判断」**之后**：
        //    那两句之间不能有 await，否则 16 条连接的累加会交错到一半，
        //    进度条又会开始乱跳（见 SegPart.received 注释）。
        if (Date.now() - lastYieldAt >= UI_YIELD_BUDGET) {
          lastYieldAt = Date.now();
          await V5Transfer.yieldFrame();
        }
      }

      // ---- 片尾 FS_END 的消费（5.0.25，与 5.0.20「文件结束帧」同构的坑）----
      //
      // 发送端（5.0.25 起，对齐 1.35）在每片数据后补发一帧 12 字节 FS_END。
      // 若本片是**收满 len** 退出的循环（没读到 FS_END），那一帧还留在接收缓冲里。
      // 不消费掉就 close：内核发现接收缓冲非空 → 发 **RST 而不是 FIN**
      // → 对端 ECONNRESET → 它那片判失败。
      // 这正是注释里记过的「只 readExactly(1) 拿走第 1 个字节就 close」的同一类事故。
      //
      // 兼容旧对端：它不发片尾帧时这里读不到（超时），照旧按字节数判成功，不影响。
      if (ok && !sawEnd && got === len) {
        try {
          const tail: Uint8Array | null = await chan.readExactly(12, 5000);
          if (tail !== null) {
            const tcmd: number = tail[0] & 0xFF;
            if (tcmd !== LCmd.FS_END) {
              Log.w(TAG, `v5 分片片尾帧异常 cmd=${tcmd}（期望 FS_END=2）`);
            }
          }
        } catch (e) {
          // 对端没补发片尾帧（旧实现）：超时/断开都忽略，交给下面的字节数校验
        }
      }
    } catch (e) {
      const err: Error = e as Error;
      Log.e(TAG, `v5 分片接收异常: ${err.message}`);
      ok = false;
    }
    // 本片收完（或失败）立刻释放本连接的 fd —— 后面的应答/统计不再碰文件
    if (wrFd >= 0) {
      try {
        fileIo.closeSync(wrFd);
      } catch (e) {
        // 已关闭，忽略
      }
    }

    if (!ok || got !== len) {
      Log.w(TAG, `v5 分片[${idx + 1}/${total}] 失败 got=${got}/${len}`);
      await V5Transfer.sendByte(chan, LCmd.FS_CLOSE);
      return false;
    }

    // 收完一片回**两个**字节（这是**片级收尾**；块级应答已在每块回过了，见文件头）。
    // 与 1.35 自己的接收端 (`z()` + `B()`) 完全一致：
    //   先 5 = FS_NEXT（「继续」流控），再 2 = FS_END（RECV_OK 终态）。
    // ⚠️ 只回 5 是不够的：1.35 的发送端 `E()`（3419-3437）读到 5 会 `goto :cond_4`
    //    再读一个字节，于是它要一直阻塞到我们 close 连接（read 返回 -1）才收尾。
    //    补上终态 2 后，对端立刻 RECV_OK 正常结束，不再依赖「对端先断开」这个隐含时序。
    await V5Transfer.sendByte(chan, LCmd.FS_NEXT);
    await V5Transfer.sendByte(chan, LCmd.FS_END);

    // ---- 4. 完成度统计 ----
    // ⚠️ 16 片并发乱序到达，用 maxEnd 判完成会**提前整整一半**就收工（见 SegPart.received 注释）。
    //    这里按 idx 去重：同一 idx 只记一次，完成判定与到达顺序无关。
    //    ⚠️ **不要在这里再 `part.received += len`** —— 字节已经在上面「每落地一块」时
    //       累加过了，这里再加一次就会翻倍。
    if (counts) {
      if (idxKnown) {
        part.gotIdx[idx] = true;
      }
      part.done += 1;
    }
    const percent: number = part.fileSize > 0
      ? Math.min(100, Math.floor(part.received * 100 / part.fileSize)) : 100;
    Log.i(TAG, `v5 分片[${idx + 1}/${total}] 完成 segId=${segId} +${len}B `
      + `已收 ${part.received}/${part.fileSize}（${percent}%，${part.done} 片）`);

    const finished: boolean = part.fileSize <= 0
      || part.received >= part.fileSize
      || (part.total > 0 && part.done >= part.total);
    if (!finished) {
      // ★ 5.1.44：同上，标记为分片进度
      V5Transfer.report(onReport, 'recv', fromName, part.name, part.done, total,
        part.received, part.fileSize, percent, false, true, '', [], true);
      return true;
    }
    if (!part.reported) {
      part.reported = true;
      part.finishedAt = Date.now();
      const ms: number = part.finishedAt - part.startedAt;
      // ⚠️ **不要在这里 segs.delete(segId)**：已完成，但可能还有片在路上；
      //    删掉条目会让后到的片认领不到 SegPart → createSegPart 另建一个 `name (1).ext`。
      //    改为保留条目并打 finishedAt，由 purgeFinished() 超时清理。
      Log.i(TAG, `v5 分片全部收齐 ${part.path}（${part.fileSize} B，${part.done} 片，${ms}ms）`);
      // ★★★ 5.1.55：**分片路径原来完全没有改名**（vivi 实测「没改成」的真凶之三）。
      //   1.35 把大文件切 16 片并发，每片一条连接 ⇒ `SegPart` 这条路径
      //   **从来没调用过 `fixExtByMagic`** ⇒ 1.8MB 这种小文件（走分片）根本不会改名。
      //   2. 必须同时回写 `part.name`（报告给 UI 的名字）与 `part.path`（磁盘路径）。
      //   3. 时机安全：只在 `!part.reported`（首次收齐）时做，
      //      此时 16 片已全部落地、条目还要留 60 秒（`purgeFinished` 才清）
      //      ⇒ 不会有后到的片再打开旧路径。
      const segBefore: string = part.path;
      part.path = MagicType.fixExtByMagic(part.path);
      if (part.path !== segBefore) {
        part.name = MagicType.baseNameOf(part.path);
        Log.i(TAG, `v5 分片改名回写：${segBefore} → ${part.path}（part.name = ${part.name}）`);
      }
      V5Transfer.report(onReport, 'recv', fromName, part.name, total, total,
        part.fileSize, part.fileSize, 100, true, true,
        `已接收 ${V5Transfer.human(part.fileSize)}，保存到 ${storage.describe}`,
        [], true);
    }
    return true;
  }

  /** 建目标文件：创建 + 预分配到整份大小，随后立即关 fd（各连接各写各的） */
  private static createSegPart(
    storage: FileStorage,
    name: string,
    fileSize: number,
    total: number
  ): SegPart | null {
    const dir: string = storage.categoryDir(name);
    const path: string = FileStorage.uniquePathIn(dir, name);
    let fd: number = -1;
    try {
      const f: fileIo.File = fileIo.openSync(
        path,
        fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC
      );
      fd = f.fd;
      try {
        // 预分配到整份大小：后到的分片可以先写尾段，不必等前面的片
        fileIo.truncateSync(fd, fileSize);
      } catch (e) {
        Log.w(TAG, 'v5 分片预分配失败（继续，写入时会按偏移自动扩展）');
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `v5 分片：创建文件失败 ${path}: ${err.code} ${err.message}`);
      return null;
    } finally {
      if (fd >= 0) {
        try {
          fileIo.closeSync(fd);
        } catch (e) {
          // 已关闭，忽略
        }
      }
    }
    const p: SegPart = new SegPart();
    p.path = path;
    p.name = name;
    p.fileSize = fileSize;
    p.total = total;
    p.startedAt = Date.now();
    // 分片下标位图：total 合理才建（1.35 恒为 16；异常值时退化为「只按字节数」判完成）
    if (total > 0 && total <= 4096) {
      const flags: boolean[] = [];
      for (let i = 0; i < total; i++) {
        flags.push(false);
      }
      p.gotIdx = flags;
    }
    return p;
  }

  /**
   * 清理**已收齐且超过 60s** 的 SegPart 条目。
   *
   * 收齐后**不能立刻删**：16 片并发，可能还有片在路上，删了会让后到的片另建文件。
   * 留 60s 足够覆盖任何迟到片，又不会让 Map 无限增长。
   */
  private static purgeFinished(): void {
    const now: number = Date.now();
    // Map 迭代中删除是安全的（ES 规范允许）
    V5Transfer.segs.forEach((v: SegPart, k: string) => {
      if (v.finishedAt > 0 && now - v.finishedAt > 60000) {
        V5Transfer.segs.delete(k);
      }
    });
  }

  /**
   * 让出一帧给 UI 线程。
   *
   * ArkTS 是单线程模型：socket 回调里的同步循环不主动让出，ArkUI 就拿不到帧时间。
   * `setTimeout(0)` 会把后续工作排到下一个事件循环，UI 得以插进来画一帧
   * （与 `net/HttpRouter.yieldFrame` 同一手法，保持工程内一致）。
   *
   * ⚠️ 不要滥用：每次让出都有一次事件循环往返的开销，
   *    所以调用点都套了「距上次让出超过 {@link UI_YIELD_BUDGET} 毫秒」的判断。
   */
  private static yieldFrame(): Promise<void> {
    return new Promise<void>((resolve: () => void) => {
      setTimeout(resolve, 0);
    });
  }

  /**
   * 在**调用方持有的 fd** 上，把 data 写到文件绝对偏移 `pos`。
   *
   * ## 为什么是 `lseek` + `write`，而不是 `write(..., {offset})`
   * SDK 对 `WriteOptions.offset` 的定义是「**当前 filePointer** + offset」
   * （`@ohos.file.fs.d.ts:5738-5748`），而 `write` 执行完会把 filePointer 往前推。
   * 于是复用同一个 fd 时，第二次写入的基准会变成「上一次写完的位置」，
   * 用 `{offset: 绝对位置}` 就会**双重偏移**。
   * 所以这里每次都显式 `lseek(fd, pos, SEEK_SET)` 把 filePointer 拉回绝对位置，
   * 再用不带 offset 的 `write` 从该位置写 —— 语义与 fd 用了多久无关。
   *
   * ## 并发安全性
   * 一个 fd 只被**一条连接**持有（见 receiveSegment），`lseek` 与 `write` 之间
   * 没有第二条流插入，因此不存在「定位被别人改掉」的竞争。
   * 16 条连接各写各的 fd，靠 `pos` 落在文件的不同区段，天然互不覆盖。
   *
   * ## 为什么必须是**异步** write
   * ArkTS 是单线程事件循环，`writeSync` 会把 UI 线程整段堵死；
   * 异步版把真正的写系统调用交给运行时工作线程，await 期间界面照常响应
   * （vivi 2026-10-01 真机反馈「接收过程中界面卡顿」）。
   */
  private static async writeAtFd(fd: number, data: Uint8Array, pos: number): Promise<boolean> {
    if (data.byteLength === 0) {
      return true;
    }
    const exact: boolean = data.byteOffset === 0 && data.byteLength === data.buffer.byteLength;
    const buf: ArrayBuffer = exact
      ? data.buffer as ArrayBuffer
      : data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;
    let off: number = 0;
    while (off < data.byteLength) {
      try {
        // whence 省略即 SEEK_SET（文件开头），正是我们要的绝对定位
        fileIo.lseek(fd, pos + off);
        const remain: ArrayBuffer = off === 0 ? buf : buf.slice(off);
        const n: number = await fileIo.write(fd, remain);
        if (n <= 0) {
          Log.e(TAG, `v5 分片写入 0 字节（pos=${pos + off}）`);
          return false;
        }
        off += n;
      } catch (e) {
        const err: BusinessError = e as BusinessError;
        Log.e(TAG, `v5 分片写文件失败（pos=${pos + off}）: ${err.code} ${err.message}`);
        return false;
      }
    }
    return true;
  }

  /**
   * 回一个裸单字节（块级应答）。
   *
   * ★ 5.0.58：改成**回传是否成功**。原来异常只打一行 Log.w 就被吞掉 ——
   *   而对端（1.35 / PC）每块之后都在**无超时地阻塞等这个字节**，
   *   它没发出去 = 对端必然卡死 → 我方 60 秒后超时。
   *   这么关键的失败必须能被调用方看见、进而写进 UI 日志。
   */
  private static async sendByte(chan: TcpChannel, b: number): Promise<boolean> {
    try {
      // ★ 5.0.62：必须走 sendChecked —— TcpChannel.send() 会把写失败吞掉
      //   （只置 closed、不抛），原来的 catch 因此**永远不会触发**，
      //   「块级应答失败」这条最关键的告警等于没写。
      const sent: boolean = await chan.sendChecked(new Uint8Array([b]));
      if (!sent) {
        Log.e(TAG, `v5 块级应答失败(byte=${b}): 通道已关`);
      }
      return sent;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `v5 块级应答失败(byte=${b}): ${err.code} ${err.message}`);
      return false;
    }
  }

  /** 收一个文件的字节流并落盘 */
  private static async recvBody(
    chan: TcpChannel,
    item: V5Incoming,
    encData: boolean,
    storage: FileStorage,
    onChunk: (got: number, size: number) => void,
    onLog?: (s: string) => void
  ): Promise<boolean> {
    const dir: string = storage.categoryDir(item.name);
    // ★ 5.1.51：改成 let —— 收完可能按魔数改名，要回写给后续日志/报告
    let path: string = FileStorage.uniquePathIn(dir, item.name);
    if (item.length <= 0) {
      return FileSink.createEmpty(path);
    }
    const sink: FileSink | null = FileSink.create(path);
    if (sink === null) {
      return false;
    }
    const startedAt: number = Date.now();
    let chunkCount: number = 0;
    /** ★ 5.0.58：「块级应答发送失败」是否已报过（同一个文件只报一次） */
    let ackWarned: boolean = false;
    let subTotal: number = 0;
    let lastPercent: number = 0;
    try {
      while (subTotal < item.length) {
        const head: Uint8Array | null = await chan.readExactly(12, 60000);
        if (head === null) {
          if (onLog) {
            onLog(`v5 "${item.name}"：等数据帧头失败（已收 ${subTotal}/${item.length} B，60s 超时或对端断开）`);
          }
          return false;
        }
        // 数据帧的流命令是**头[0] 的单字节**（1.35 用 aget-byte 读），不是整个 int
        const cmd: number = head[0] & 0xFF;
        const len: number = V5Dec.beInt(head, 8);
        if (cmd === LCmd.FS_END) {
          break; // 发送端声明本文件结束
        }
        if (cmd !== LCmd.FS_DATA) {
          Log.w(TAG, `收到非数据帧 cmd=${cmd}（FS_CLOSE=${LCmd.FS_CLOSE} 表示对端取消）`);
          return false;
        }
        if (len <= 0 || len > MAX_FRAME) {
          Log.e(TAG, `v5 分片长度异常: ${len}`);
          return false;
        }
        const chunk: Uint8Array | null = await chan.readExactly(len, 60000);
        if (chunk === null) {
          if (onLog) {
            onLog(`v5 "${item.name}"：数据块 ${len} B 读取失败（已收 ${subTotal}/${item.length}，超时或对端断开）`);
          }
          return false;
        }
        if (encData) {
          FileCrypto.decData(chunk, len, 0, subTotal);
        }
        if (!sink.append(chunk)) {
          return false;
        }
        chunkCount += 1;
        subTotal += len;
        // ★ 块级应答（5.0.19）：对端每发一块都阻塞 recv 1 字节才发下一块。
        //   放在 append 成功之后 —— 数据已落地才确认。整份文件只回一次 =
        //   对端发完第一块就永久卡在 recv（实测进度停在 2097140/4xx 万 = 48%）。
        // ★ 5.0.58：应答发失败要**响一下**（只报第一次，避免刷屏）。
        //   对端在等这一字节，失败 = 本项必然超时，日志里必须能直接看到。
        const ackOk: boolean = await V5Transfer.sendByte(chan, LCmd.FS_NEXT);
        if (!ackOk && !ackWarned) {
          ackWarned = true;
          if (onLog) {
            onLog(`v5 "${item.name}" 第 ${chunkCount} 块应答发送失败`
              + ` —— 对端在等它，本项大概率会超时`);
          }
        }
        const percent: number = Math.floor(subTotal * 100 / item.length);
        if (percent !== lastPercent || subTotal >= item.length) {
          lastPercent = percent;
          onChunk(subTotal, item.length);
        }
      }
      // ★ 文件结束帧（5.0.20）：收满后必须再消费掉对端补发的那一帧，
      //   否则它会被**下一个文件的 recvBody** 当帧头读走 → `0 != item.length`
      //   → 回 FS_BREAK → 多文件从第 2 个起必失败（真机复现见文件头）。
      //   ⚠️ 必须放在循环**之外**：循环内最后一块的块级 ack 已经回过，对端才会
      //      发这帧；顺序反过来（先等帧、后回 ack）就是双方对等死锁。
      if (subTotal === item.length) {
        if (onLog) {
          onLog(`v5 "${item.name}" 已收满 ${subTotal} B，等待结束帧…`);
        }
        const tail: Uint8Array | null = await chan.readExactly(12, END_FRAME_WAIT_MS);
        if (tail !== null) {
          const tcmd: number = tail[0] & 0xFF;
          if (tcmd === LCmd.FS_END) {
            const tlen: number = V5Dec.beInt(tail, 8);
            if (tlen > 0) {
              // 协议规定 len=0；真出现非零也要吃掉，否则残留会污染下一帧
              Log.w(TAG, `v5 结束帧带 ${tlen} 字节负载，已丢弃`);
              await chan.readExactly(tlen, 15000);
            }
          } else if (tcmd === LCmd.FS_CLOSE) {
            // 对端在文件末尾判失败（没发满）—— 按已收字节数落地，
            // 下面的一致性校验会兜底报错。
            Log.w(TAG, '对端在文件末尾回了 FS_CLOSE');
          } else {
            Log.w(TAG, `v5 结束帧命令异常 cmd=${tcmd}，帧流可能已错位`);
            return false;
          }
        }
        // tail === null：对端没补发结束帧（旧版 / 已断开）→ 交给字节数校验兜底
      }
    } finally {
      sink.close();
    }
    // ★★ 5.1.51：收完立刻按**魔数**纠正后缀
    //   （对方可能把 jpg 命名成 .png / .dat / 干脆没有后缀）。
    //   放在字节数校验**之前**；`path` 已回写 ⇒ 后面日志/报告都拿到新名。
    const before: string = path;
    path = MagicType.fixExtByMagic(path);
    // ★★★ 5.1.55：**必须把新名回写进 `item.name`**（vivi 实测「没改成」的真凶）。
    //   磁盘上改了名，但**报告给 UI 的 fileName 全部取自 `item.name`**（协议原始名）
    //   ⇒ 消息气泡 / 文件页 / 落盘分类**全都还显示旧名**，
    //      而用户看到的就是「没改名」—— 以为改名没生效，其实只是 UI 用错了字段。
    //   `item` 是可变对象，回写它一处 ⇒ 后续所有 report 自动拿到新名。
    if (path !== before) {
      item.name = MagicType.baseNameOf(path);
      Log.i(TAG, `v5 改名回写：${before} → ${path}（item.name = ${item.name}）`);
    }
    if (subTotal !== item.length) {
      Log.w(TAG, `v5 接收字节数不符: ${subTotal} != ${item.length}（${path}）`);
      if (onLog) {
        onLog(`v5 "${item.name}" 字节数不符：收到 ${subTotal} / 应收 ${item.length}`);
      }
      return false;
    }
    const ms: number = Date.now() - startedAt;
    Log.i(TAG, `v5 已保存 ${path} (${subTotal} B, ${chunkCount} 片, ${ms}ms)`);
    return true;
  }

  // ==================================================================
  // 小工具
  // ==================================================================

  /** 读一帧的 payload（先 12 字节头，再按头里的长度读体） */
  private static async readFrameBody(chan: TcpChannel): Promise<Uint8Array | null> {
    const head: Uint8Array | null = await chan.readExactly(12, 15000);
    if (head === null) {
      return null;
    }
    const len: number = V5Dec.beInt(head, 8);
    if (len < 0 || len > MAX_FRAME) {
      Log.w(TAG, `v5 帧长度异常: ${len}`);
      return null;
    }
    if (len === 0) {
      return new Uint8Array(0);
    }
    return await chan.readExactly(len, 60000);
  }

  /** 只有 12 字节头的帧（应答 1102/1103）。LanService 的拒绝路径也要用，必须公开 */
  static simpleFrame(cmd: number): Uint8Array {
    const out: Uint8Array = new Uint8Array(12);
    out[0] = (cmd >>> 24) & 0xFF;
    out[1] = (cmd >>> 16) & 0xFF;
    out[2] = (cmd >>> 8) & 0xFF;
    out[3] = cmd & 0xFF;
    // arg = 0，len = 0，其余保持 0
    return out;
  }

  /** 写设备头（发送端不带"已知设备表"，空表即可 —— 1.35 只是拿它做加速） */
  private static writeHeader(enc: V5Enc, self: LanDevice): void {
    enc.int(self.devPort);
    enc.string(self.devIp);
    enc.string(self.devName);
    enc.int(self.devMode);
    enc.string(`${self.uniqueUuid}-5`);
    enc.int(5);
    enc.int(self.batteryLevel);
    enc.byte(self.chargeStatus);
    enc.int(0);
  }

  /** v5 的文件类型：3001 图片 / 3002 视频 / 3003 普通文件 */
  private static typeOf(name: string): number {
    const dot: number = name.lastIndexOf('.');
    if (dot < 0) {
      return LCmd.FILE_FILE;
    }
    const ext: string = name.substring(dot + 1).toLowerCase();
    if (IMG_EXT.indexOf(ext) >= 0) {
      return LCmd.FILE_IMAGE;
    }
    if (VID_EXT.indexOf(ext) >= 0) {
      return LCmd.FILE_VIDEO;
    }
    return LCmd.FILE_FILE;
  }

  private static sumSize(files: OutgoingFile[]): number {
    let t: number = 0;
    for (let i = 0; i < files.length; i++) {
      t += files[i].size > 0 ? files[i].size : 0;
    }
    return t;
  }

  private static human(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    if (bytes < 1024 * 1024 * 1024) {
      return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }

  private static report(
    cb: TransferCallback,
    direction: string,
    peer: string,
    fileName: string,
    index: number,
    count: number,
    bytes: number,
    size: number,
    percent: number,
    done: boolean,
    ok: boolean,
    message: string,
    names: string[] = [],
    isSeg: boolean = false
  ): void {
    const r: TransferReport = new TransferReport();
    r.direction = direction;
    r.peer = peer;
    r.fileName = fileName;
    r.fileIndex = index;
    r.fileCount = count;
    r.bytes = bytes;
    r.fileSize = size;
    r.percent = percent;
    r.done = done;
    r.ok = ok;
    r.message = message;
    r.fileNames = names;
    r.isSeg = isSeg;
    cb(r);
  }
}
