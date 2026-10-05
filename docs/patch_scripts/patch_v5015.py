# -*- coding: utf-8 -*-
"""
LANShareV5 5.0.15 一次性补丁（行号区间替换 + 内容校验 + 幂等）。

为什么用行号区间而不是文本锚点：
  这些文件里全是中文长注释，Edit 工具在本机的中文锚点匹配反复失败。
  行号区间法配两道保险同样安全：
    · expect   —— 区间里必须出现的关键词，防止行号偏移导致误删；
    · sentinel —— 只可能出现在**补丁之后**的字符串，存在即整文件跳过（幂等）。

四个诉求：
  1) 多选态下系统返回 -> 取消多选，而不是退出应用
  2) 文件页行内加回「删除」按钮
  3) 接收期间不再整页重建 + 解密切片更细（更流畅）
  4) 设备下线提速：废弃「信任分」模型，改用 TCP 连接复核判死
"""
import sys

BASE = r"E:\lanshare-harmony\LANShareV5\entry\src\main\ets"


def load(path):
    raw = open(path, "r", encoding="utf-8", newline="").read()
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def save(path, text, crlf):
    out = text.replace("\n", "\r\n") if crlf else text
    open(path, "w", encoding="utf-8", newline="").write(out)


def splice(text, a, b, new_block, expect, tag):
    lines = text.split("\n")
    if not (1 <= a <= b <= len(lines)):
        raise AssertionError("%s: 行号越界 %d-%d (共 %d 行)" % (tag, a, b, len(lines)))
    seg = "\n".join(lines[a - 1:b])
    if expect not in seg:
        raise AssertionError("%s: 区间 %d-%d 内未找到关键字 %r\n---- 实际内容 ----\n%s"
                             % (tag, a, b, expect, seg[:600]))
    # 括号增量必须一致 —— 这条能抓住「替换块少写了收尾大括号」这类事故
    # （曾经就因为 new_block 只写到方法前半段，把 dropDevice 的收尾整段吞掉）。
    d_old = seg.count("{") - seg.count("}")
    d_new = new_block.count("{") - new_block.count("}")
    if d_old != d_new:
        raise AssertionError("%s: 区间 %d-%d 括号增量不一致（原 %+d / 新 %+d），拒绝写入"
                             % (tag, a, b, d_old, d_new))
    return "\n".join(lines[:a - 1] + new_block.split("\n") + lines[b:])


# ======================================================================
# LanConfig.ets : 106-149  探活常量组整段重写
# ======================================================================
CONFIG_NEW = '''  // ---------- 设备「快速下线」探活（vivi 2026-10-01 第二/三次反馈） ----------
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
  static readonly DEVICE_TCP_VERIFY_MAX_MISS: number = 3;'''

# ======================================================================
# LanService.ets
# ======================================================================
SVC_IMPORT_NEW = '''import { BusinessError } from '@kit.BasicServicesKit';
import { socket } from '@kit.NetworkKit';
import deviceInfo from '@ohos.deviceInfo';'''

SVC_FIELDS_NEW = '''  /**
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
  private lastTcpProbeAt: Map<string, number> = new Map<string, number>();'''

SVC_SYNCSTATS_NEW = '''      if (!this.deviceGone(d, now)) {'''

SVC_NOTE_ANSWER_NEW = ''''''

SVC_EXISTING_NEW = '''    } else {
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
    }'''

SVC_DROP_NEW = '''    this.probeSentAt.delete(d.devIp);
    this.tcpProbeBusy.delete(d.devIp);
    this.tcpProbeMiss.delete(d.devIp);
    this.tcpEverOk.delete(d.devIp);
    this.lastTcpProbeAt.delete(d.devIp);'''

SVC_PROBE_NEW = '''  /**
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
  }'''

SVC_SWEEP_NEW = '''  private sweepDevices(): void {
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
  }'''

SVC_LIST_NEW = '''      if (!this.deviceGone(d, now)) {'''

# ======================================================================
# Index.ets
# ======================================================================
IDX_SIG_NEW = '''    // ⚠️ 刻意**不**把 connections / webRequests / onlineDevices / knownDevices 放进来：
    //    前两个在接收期间会高频变化（16 条分片连接反复建立/关闭！），
    //    而界面上根本没有渲染它们（连接数、请求数都不上屏）——
    //    放进来等于让每次「有分片连上 / 断开」都触发一次**整页重建**。
    //    设备数变化由 syncDeviceList 的独立签名负责，比这里精确得多。
    const sig: string =
      `${s.state}|${s.localIp}|${s.webUrl}|${s.deviceName}` +
      `|${s.webOpen ? 1 : 0}|${s.pendingWebClients.length}|${s.wsClients}` +
      `|${s.sessionActive ? 1 : 0}|${s.message}|${s.listenDetail}|${s.saveLocation}`;'''

IDX_BACK_NEW = '''  aboutToDisappear(): void {
    this.service.unsubscribe(this.onSnapshot);
  }

  /**
   * 系统返回（返回键 / 侧滑手势）拦截。
   *
   * ⚠️ 不实现这个回调时，返回的默认行为是**退出应用** ——
   *    多选到一半误触返回就直接回桌面，勾选全丢（vivi 2026-10-01 真机反馈）。
   *    返回的语义应当是「先退掉最上层的临时状态」：
   *      多选态 → 取消多选；二维码弹窗 → 关弹窗；发文件弹窗 → 关弹窗；
   *      都不是 → 交还给系统（正常退出）。
   *
   * @returns true = 已经处理（不再往下传）；false = 交给系统默认行为
   */
  onBackPress(): boolean {
    if (this.fileSelectMode) {
      this.exitFileSelect();
      return true;
    }
    if (this.showQr) {
      this.showQr = false;
      return true;
    }
    if (this.pickStep > 0) {
      this.pickStep = 0;
      return true;
    }
    return false;
  }'''

IDX_BTN_NEW = '''                    // 单行操作只在普通态露出。多选态下批量操作在底部条，
                    // 行内不再有按钮 —— 点行任意位置即可勾选。
                    if (!this.fileSelectMode) {
                      // 推给网页端：文件已经在沙箱里，不用复制，直接通知浏览器来取
                      Button('发到网页')
                        .fontSize(12)
                        .height(30)
                        .padding({ left: 10, right: 10 })
                        .backgroundColor('#E8F0FE')
                        .fontColor(C_PRIMARY)
                        .onClick(() => this.pushOneToWeb(f))

                      Button('另存为')
                        .fontSize(12)
                        .height(30)
                        .padding({ left: 12, right: 12 })
                        .backgroundColor(C_PRIMARY)
                        .fontColor(Color.White)
                        .onClick(() => this.saveAsFile(f))

                      // 单条删除（vivi 2026-10-01：「把文件页的删除按钮加回来」）。
                      // 长按多选仍然保留 —— 删一个用这个、删一批用多选，两条路都通。
                      // ⚠️ 它落在**第二行**（元信息那一行）的右侧：文件名独占第一行，
                      //    所以第三个按钮不会再像 5.0.12 那样把文件名挤扁。
                      Button('删除')
                        .fontSize(12)
                        .height(30)
                        .padding({ left: 10, right: 10 })
                        .backgroundColor('#FDECEA')
                        .fontColor('#E84026')
                        .onClick(() => this.deleteOne(f))
                    }'''

# ======================================================================
# V5Transfer.ets
# ======================================================================
V5_BUDGET_NEW = '''const UI_YIELD_BUDGET: number = 12;'''

V5_SLICE_NEW = '''/**
 * 解密切片大小。
 *
 * 取 **256KB**（vivi 2026-10-01 第三次反馈后，从 512KB 再减半）：
 * 它决定「单次连续占用主线程」的上界 —— 一片解密的耗时约 1~2ms，
 * 远低于一帧（16ms）的容忍度。**不能用 1MB/8MB 整块解**，那正是卡顿的来源。
 *
 * 为什么不再往下调（128KB / 64KB）：切片越小，让帧判断与循环本身的**相对**开销越大，
 * 实测吞吐会掉。256KB 是「主线程占用够碎」与「吞吐不掉」的折中点。
 */
const DEC_SLICE: number = 256 * 1024;'''

# ======================================================================
# 补丁表： (文件, 哨兵, [(起行, 止行, 新内容, 区间校验关键词), ...])  行号必须降序
# ======================================================================
PATCHES = [
    (BASE + r"\core\LanConfig.ets", "DEVICE_TCP_PROBE_TIMEOUT_MS", [
        (106, 149, CONFIG_NEW, "DEVICE_PROBE_QUIET_MS"),
    ]),
    (BASE + r"\service\LanService.ets", "tcpProbeStep", [
        (1732, 1732, SVC_LIST_NEW, "deviceGone(d.devIp, d, now)"),
        (1694, 1725, SVC_SWEEP_NEW, "private sweepDevices(): void"),
        (940, 1004, SVC_PROBE_NEW, "noteProbeAnswer"),
        (930, 931, SVC_DROP_NEW, "this.probeTrust.delete(d.devIp);"),
        (903, 910, SVC_EXISTING_NEW, "existing.chargeStatus = d.chargeStatus;"),
        (861, 862, SVC_NOTE_ANSWER_NEW, "noteProbeAnswer(fromIp)"),
        (830, 830, SVC_SYNCSTATS_NEW, "deviceGone(d.devIp, d, now)"),
        (224, 233, SVC_FIELDS_NEW, "probePendingAt"),
        (25, 27, SVC_IMPORT_NEW, "import { BusinessError }"),
    ]),
    (BASE + r"\pages\Index.ets", "onBackPress", [
        (1736, 1753, IDX_BTN_NEW, "Button('另存为')"),
        (289, 291, IDX_BACK_NEW, "aboutToDisappear"),
        (261, 265, IDX_SIG_NEW, "s.onlineDevices"),
    ]),
    (BASE + r"\service\V5Transfer.ets", "const DEC_SLICE: number = 256 * 1024;", [
        (76, 82, V5_SLICE_NEW, "const DEC_SLICE"),
        (75, 75, V5_BUDGET_NEW, "const UI_YIELD_BUDGET"),
    ]),
]


def main():
    # ---- 第一阶段：逐文件判哨兵（已打过就跳过该文件）+ 在内存里构造结果 ----
    # ⚠️ 逐文件而不是整批：这样「恢复其中一个文件后重跑」也能正确只补那一个。
    staged = []
    for path, sentinel, items in PATCHES:
        text, crlf = load(path)
        if sentinel in text:
            print("[SKIP] 已打过补丁: %s" % path)
            continue
        before = len(text.split("\n"))
        for a, b, block, expect in items:      # 已按行号降序
            text = splice(text, a, b, block, expect, path)
        staged.append((path, text, crlf, before))
    if not staged:
        print("[NOTHING] 所有文件都已是补丁后的状态，未做任何修改")
        return 0
    # ---- 第二阶段：统一落盘（任一文件校验失败则一个字都不写） ----
    for path, text, crlf, before in staged:
        save(path, text, crlf)
        print("[OK] %-58s %d -> %d 行  CRLF=%s" % (path, before, len(text.split("\n")), crlf))
    print("[DONE] 补丁完成，涉及 %d 个文件" % len(staged))
    return 0


if __name__ == "__main__":
    sys.exit(main())
