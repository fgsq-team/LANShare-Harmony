# -*- coding: utf-8 -*-
"""
5.0.58 —— 修「PC 端连发多张图片，最后一张必然失败（干等 60 秒）」

真机取证（2026-10-02，PC LANShare.exe → 手机）：
  6 张批次：第 6/6 失败（已收 6291420/7223157）
  12 张批次：第 12/12 失败（已收 4194280/7735325，从开始到失败**正好 60 秒**）
  ⇒ 60 秒 = 接收端 `readExactly(..., 60000)` 超时；连接**没断**（断了会立刻返回），
    说明对端还活着但一个字节都没再发 —— 即**发送端卡住**了。

根因链（PC 源码 `E:\\lanshare-harmony\\LANShare-PC-main` 逐行取证）：
  ① PC `LANShare.cpp:250` 每块之后 `mtcpClient->recvo(&read, 1)` 是**无超时的阻塞读**，
     返回值**不检查**；`baseSend` 靠它做「发一块等一块」的节流。
  ② 但 `TCPClient::send()` 只是裸 `::send()`（`tools/TCPClient.cpp:99`），
     与它自己的 `recvo()`（**有 while 循环读满**）不对称 —— Windows 阻塞 socket
     的 `send()` **可能只发一部分就返回**。
  ③ `LANShare.cpp:245` 把这种「部分发送」当**硬错误**：
     `!= dataEnc.getDataLen()` → `thatSend = -3; break;` → 该文件被判失败 →
     末尾改发 **FS_CLOSE**（而不是 FS_END）。
  ④ 我方 `recvBody` 此时正在 `readExactly(len)` 等这一块的数据体 ——
     **FS_CLOSE 那 12 字节被当作数据体吞掉**，于是永远等不满 → 60 秒超时。
     （我方连「对端发了 FS_CLOSE」都看不到，因为它混在数据体里。）

为什么总是**最后一项**：压力累积到峰值时接收窗口关闭 → `::send` 部分返回的概率最高。
为什么我的探针 100MB 全过：Node 的 `write()` 正确处理部分写，不会误判。

本补丁做三件事（**都在手机侧，且失效时自动退回现状**）：
  A. ★ **放大接收缓冲**（`TUNE_BUFFER_SIZE` 256KB → 4MB）：接收窗口 ≥ 一个块（2MB）时，
     PC 一次 2MB 的 `::send()` 能被整块收下，**从源头大幅降低「部分发送」的发生**。
     纯本机内核参数，线上字节一个都不变，零兼容风险。
  B. ★ **按对端分流文件收尾的 ack 字节数**：
     实测我方每文件回 **N+2** 字节，而 PC 只读 **N+1**（每块 1 + 文件间 1，
     `LANShare.cpp:598`）⇒ 每文件多 1 字节 ⇒ 从第 2 个文件起 PC 读到的是残留字节，
     **不再按块等 ack**（节流失效，这正是把窗口压满的推手）。
     判据：**PC 的 `makeDataEnc(*p1,…)` 填的是「目标设备」的信息 ⇒
     它宣告的 IP 就是我方自己的 IP**（真 1.35 宣告的是它自己）。
     命中则文件收尾只回 `2`（N+1）；不命中一律保持现状 `5`+`2`（N+2）——
     所以判据即使失误也不会引入回归。
  C. ★ **把 ack 发送失败变响**：`sendByte` 原来把异常吞成一行 Log.w，
     现在回传布尔 + 走 UI 日志。对端在等这个字节，它失败 = 必然超时，
     必须一眼可见。

幂等：哨兵 `pcStyleAck`。写文件保持 LF。
"""
import io, sys

V5 = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\service\V5Transfer.ets'
LS = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\service\LanService.ets'
TS = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\net\LanTcpServer.ets'
AJ = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'

SENTINEL = 'pcStyleAck'

# ================================================================ A. 缓冲区
A_OLD = """const TUNE_BUFFER_SIZE: number = 262144;"""
A_NEW = """/**
 * 监听套接字的 SO_RCVBUF / SO_SNDBUF（accept 出来的连接会继承这两个值）。
 *
 * ★ 5.0.58：**256KB → 4MB**。原来只有 256KB，**比一个数据块（2MB）还小**。
 *   对端（尤其 PC 端 `TCPClient::send()` = 裸 `::send()`，**不是**循环发满）
 *   在窗口关闭时会拿到「部分发送」，而它把部分发送当硬错误 → 中止该文件并改发
 *   FS_CLOSE，我方把它当数据体吞掉 → 干等 60 秒（真机取证见补丁头）。
 *   把接收窗口放大到一个块以上，`send()` 就能一次交完，从源头消除这个触发条件。
 *   ⚠️ 纯本机内核参数，**线上字节流一个都不变**，对原版 Android / 1.35 / PC 全部照旧互通。
 *   ⚠️ 调不上去只会打一条告警（系统 rmem_max 限制），不影响功能。
 */
const TUNE_BUFFER_SIZE: number = 4 * 1024 * 1024;"""

# ================================================================ B1. sendByte 回传结果
B1_OLD = """  /** 回一个裸单字节（分片应答/拒绝） */
  private static async sendByte(chan: TcpChannel, b: number): Promise<void> {
    try {
      await chan.send(new Uint8Array([b]));
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `v5 分片回应答失败: ${err.code} ${err.message}`);
    }
  }"""
B1_NEW = """  /**
   * 回一个裸单字节（块级应答）。
   *
   * ★ 5.0.58：改成**回传是否成功**。原来异常只打一行 Log.w 就被吞掉 ——
   *   而对端（1.35 / PC）每块之后都在**无超时地阻塞等这个字节**，
   *   它没发出去 = 对端必然卡死 → 我方 60 秒后超时。
   *   这么关键的失败必须能被调用方看见、进而写进 UI 日志。
   */
  private static async sendByte(chan: TcpChannel, b: number): Promise<boolean> {
    try {
      await chan.send(new Uint8Array([b]));
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `v5 块级应答失败(byte=${b}): ${err.code} ${err.message}`);
      return false;
    }
  }"""

# ================================================================ B2. recvBody 记录 ack 失败
B2_OLD = """        await V5Transfer.sendByte(chan, LCmd.FS_NEXT);
        const percent: number = Math.floor(subTotal * 100 / item.length);"""
B2_NEW = """        // ★ 5.0.58：应答发失败要**响一下**（只报第一次，避免刷屏）。
        //   对端在等这一字节，失败 = 本项必然超时，日志里必须能直接看到。
        const ackOk: boolean = await V5Transfer.sendByte(chan, LCmd.FS_NEXT);
        if (!ackOk && !ackWarned) {
          ackWarned = true;
          if (onLog) {
            onLog(`v5 "${item.name}" 第 ${chunkCount} 块应答发送失败`
              + ` —— 对端在等它，本项大概率会超时`);
          }
        }
        const percent: number = Math.floor(subTotal * 100 / item.length);"""

B2B_OLD = """    let chunkCount: number = 0;
    let subTotal: number = 0;
    let lastPercent: number = 0;"""
B2B_NEW = """    let chunkCount: number = 0;
    /** ★ 5.0.58：「块级应答发送失败」是否已报过（同一个文件只报一次） */
    let ackWarned: boolean = false;
    let subTotal: number = 0;
    let lastPercent: number = 0;"""

# ================================================================ C. receive 收尾分流
C_OLD = """    onReport: TransferCallback,
    onLog?: (s: string) => void
  ): Promise<boolean> {
    try {
      // ---- 1. 逐个读条目帧（四字段版）----"""
C_NEW = """    onReport: TransferCallback,
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
      // ---- 1. 逐个读条目帧（四字段版）----"""

C2_OLD = """        // 收完（无论成败）都要回一个字节：发送端在等它，不回会挂到超时
        const ack: Uint8Array = new Uint8Array([ok ? LCmd.FS_NEXT : LCmd.FS_BREAK]);
        await chan.send(ack);
        // 5.0.48：文件级收尾也必须再补一个终态 2（FS_END / RECV_OK），与**片级收尾**
        //   完全一致（见 receiveSegment 尾部：同样是「先 5 再 2」）。
        //   1.35 接收端文件收完时也写 2（取证 dump Lo2/j）；而 1.35 发送端读到 5 后
        //   **还会再读一个字节** —— 只回 5 时它一直阻塞到我们关连接为止。
        //   真机症状：单项「看着成功」（靠关连接收尾），多项从第 2 项起永远等不到
        //   数据（第 1 项收满后第 2 项 60s 超时、0 字节）—— 正是本行缺失导致。
        if (ok) {
          await chan.send(new Uint8Array([LCmd.FS_END]));
          if (onLog) {
            onLog(`v5 "${item.name}" 收尾已回 5+2（FS_NEXT+FS_END），可继续下一项`);
          }
        }"""
C2_NEW = """        // 收完（无论成败）都要回一个字节：发送端在等它，不回会挂到超时
        const ack: Uint8Array = new Uint8Array([ok ? LCmd.FS_NEXT : LCmd.FS_BREAK]);
        // ★ 5.0.58：发送失败必须喊出来 —— 对端正阻塞等这一字节
        try {
          await chan.send(ack);
        } catch (se) {
          const sex: Error = se as Error;
          Log.e(TAG, `v5 文件级应答发送失败: ${sex.message}`);
          if (onLog) {
            onLog(`v5 "${item.name}" 文件级应答发送失败（对端会一直等）：${sex.message}`);
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
        }"""

# ================================================================ D. 分流判据
D_OLD = """    if (channel.remoteIp.length > 0) {
      peer.devIp = channel.remoteIp;
    }
    // 设备头（含已知设备表）之后**紧邻**的 1 字节就是 encData（1.35 的 `b(byte)` 写在设备头末尾）"""
D_NEW = """    // ★ 5.0.58：在**覆盖之前**记下对端「自己宣告」的地址与型号 —— 这是识别 PC 端的指纹。
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
      + ` mode=${announcedMode} ver=${peer.dataVersion}`);
    const myIp: string = this.localNet.ip;
    const pcStyleAck: boolean = announcedIp.length > 0 && myIp.length > 0
      && announcedIp === myIp && announcedMode !== DeviceMode.ANDROID;
    if (pcStyleAck) {
      this.pushLog('对端宣告的是本机地址 ⇒ 判定为 PC 端发送器，文件收尾按它的 N+1 读取数回');
    }
    // 设备头（含已知设备表）之后**紧邻**的 1 字节就是 encData（1.35 的 `b(byte)` 写在设备头末尾）"""

D2_OLD = """      (s: string) => this.pushLog(s));"""
D2_NEW = """      (s: string) => this.pushLog(s), pcStyleAck);"""

# ================================================================ E. 版本号
AJ_OLD = """    "versionCode": 5000057,
    "versionName": "5.0.57",
"""
AJ_NEW = """    "versionCode": 5000058,
    "versionName": "5.0.58",
"""


def apply(path, pairs, label):
    s = io.open(path, encoding='utf-8', newline='').read()
    for i, (old, new) in enumerate(pairs):
        n = s.count(old)
        assert n == 1, '%s 锚点#%d 命中 %d 次' % (label, i + 1, n)
        assert s.count(new) == 0, '%s 新文本#%d 此前已存在' % (label, i + 1)
    for old, new in pairs:
        s = s.replace(old, new)
    return s


src_v5 = io.open(V5, encoding='utf-8', newline='').read()
if SENTINEL in src_v5:
    print('ALREADY APPLIED')
    sys.exit(0)

new_v5 = apply(V5, [(B1_OLD, B1_NEW), (B2B_OLD, B2B_NEW), (B2_OLD, B2_NEW),
                    (C_OLD, C_NEW), (C2_OLD, C2_NEW)], 'V5Transfer')
src_ts = io.open(TS, encoding='utf-8', newline='').read()
new_ts = apply(TS, [(A_OLD, A_NEW)], 'LanTcpServer')
src_ls = io.open(LS, encoding='utf-8', newline='').read()
new_ls = apply(LS, [(D_OLD, D_NEW), (D2_OLD, D2_NEW)], 'LanService')
new_aj = apply(AJ, [(AJ_OLD, AJ_NEW)], 'app.json5')

for tag, s, syms in [
  ('V5', new_v5, [('pcStyleAck: boolean = false\n  ): Promise<boolean> {', 1),
                  ('const ackOk: boolean = await V5Transfer.sendByte(', 1),
                  ('let ackWarned: boolean = false;', 1),
                  ('if (!ackOk && !ackWarned) {', 1),
                  ('private static async sendByte(chan: TcpChannel, b: number): Promise<boolean> {', 1),
                  ('if (pcStyleAck) {', 1),
                  ('收尾已回 2（PC 端按 N+1 读，故不发多余的那个 5）', 1),
                  ('v5 文件级应答发送失败', 1),
                  ('v5 终态应答发送失败', 2)]),
  ('TS', new_ts, [('const TUNE_BUFFER_SIZE: number = 4 * 1024 * 1024;', 1)]),
  ('LS', new_ls, [('const announcedIp: string = peer.devIp;', 1),
                  ('const pcStyleAck: boolean = announcedIp.length > 0 && myIp.length > 0', 1),
                  ('(s: string) => this.pushLog(s), pcStyleAck);', 1),
                  ('v5 对端宣告：name=', 1),
                  ('判定为 PC 端发送器', 1)]),
]:
    for sym, want in syms:
        got = s.count(sym)
        assert got == want, '%s 符号校验失败 %r: 期望 %d 实为 %d' % (tag, sym[:46], want, got)
        print('  OK %2d  %s  %s' % (got, tag, sym[:46]))

# 1110 分片路径（receiveSegment）保留原调用 —— 那条路径的对端是 1.35，不适用 pcStyleAck
# ⚠️ 期望 3 = receiveSegment 的 2 处 + recvBody 新写的 1 处（新调用本身就是这个子串）
assert new_v5.count('await V5Transfer.sendByte(chan, LCmd.FS_NEXT);') == 3, \
  '实余 %d 处' % new_v5.count('await V5Transfer.sendByte(chan, LCmd.FS_NEXT);')
assert new_v5.count('const ackOk: boolean = await V5Transfer.sendByte(') == 1
assert 'const TUNE_BUFFER_SIZE: number = 262144;' not in new_ts, '旧缓冲常量仍在'
assert '5000058' in new_aj and '"5.0.58"' in new_aj

for tag, path, after in [('V5Transfer', V5, new_v5), ('LanTcpServer', TS, new_ts),
                         ('LanService', LS, new_ls)]:
    before = io.open(path, encoding='utf-8', newline='').read()
    d = {}
    for ch in '{}()[]':
        d[ch] = after.count(ch) - before.count(ch)
    print('%s 括号增量: %s' % (tag, d))

io.open(V5, 'w', encoding='utf-8', newline='\n').write(new_v5)
io.open(TS, 'w', encoding='utf-8', newline='\n').write(new_ts)
io.open(LS, 'w', encoding='utf-8', newline='\n').write(new_ls)
io.open(AJ, 'w', encoding='utf-8', newline='\n').write(new_aj)
print('OK: 5.0.58 已应用')
