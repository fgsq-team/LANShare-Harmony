# -*- coding: utf-8 -*-
"""追加 5.0.58 段到当日工作日志。幂等：哨兵判重。"""
import io, sys

P = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
SENTINEL = '### 16:45 5.0.58'

ADD = '''

### 16:45 5.0.58 — PC 端连发多图「最后一张必然失败」= ack 字节数比对端读取数多一个

**vivi**：手机连上了，看日志。多张图片会接受失败。

**先拿到的真机证据**（`ui_log.txt` 拉下来）：
- 6 张批次：第 **6/6** 失败（已收 6291420/7223157），失败前一行有 `监听套接字错误 -1 undefined`；
- 12 张批次：第 **12/12** 失败（已收 4194280/7735325），从开始到失败**正好 60 秒**；
- 1 张 / 4 张批次全部成功。
⇒ 60 秒 = `readExactly(..., 60000)` 超时；**连接没断**（断了会立刻返回）⇒ 对端活着但一个字节都不发。

**自己先复现（`tests/live-probe/v5_multifile_probe.mjs`）**：6×4=48MB、12×4=100MB **全部通过**
（每块 ack 都正常）⇒ **手机侧接收逻辑本身没问题，差异在发送端**。

**发送端定位**：`tasklist` 发现本机在跑 `LANShare.exe`（PID 14660），
且 `E:\\lanshare-harmony\\LANShare-PC-main` 有 **PC 端 C++ 源码** ⇒ 逐行取证：

- `LANShare.cpp:250` 每块后 `mtcpClient->recvo(&read, 1)` = **无超时阻塞读**，返回值**不检查**；
- `tools/TCPClient.cpp:99` `send()` 只是**裸 `::send()`**（而它自己的 `recvo()` 是**循环读满**的，
  两者不对称）⇒ Windows 阻塞 socket 的 `send()` **可能只发一部分**；
- `LANShare.cpp:245` 把「部分发送」当**硬错误** → `thatSend=-3; break` → 该文件判失败 →
  末尾改发 **FS_CLOSE**（不是 FS_END）；
- 我方 `recvBody` 正在 `readExactly(len)` 等数据体 ⇒ **FS_CLOSE 的 12 字节被当数据体吞掉** ⇒
  永远等不满 ⇒ 60 秒超时（连"对端发了 FS_CLOSE"都看不到）。

**为什么总是最后一项**：压力累积到峰值时接收窗口关闭，`::send` 部分返回概率最高。

**触发条件 —— 我方 ack 多送一个字节**：写了 `tests/live-probe/v5_pcstyle_ack_probe.mjs`
（**复刻 PC 的读取行为**：握手宣告"目标设备"的地址 = 手机自己的 IP；每块读 1 + 文件间再读 1），
在 5.0.57 上实测：

```
文件 1: ack=5, ack=5, [文件间]ack=5
文件 2: ack=2  ← 读到上一文件的 FS_END 残留！块级节流已错位
文件 3: ack=2  ← 又错一位
序列: 5,5,5,2 | 5,5,5,2 | 5,5,5,2   （我方 N+2） vs PC 读 N+1
```
⇒ 每文件多 1 字节 ⇒ 从第 2 个文件起 PC 读到残留字节 ⇒ **不再按块等 ack**（一路狂发）
⇒ 接收窗口被压满 ⇒ 触发上面的部分发送链。**与"总是最后一项"完全吻合。**

**5.0.58 三处修（都在手机侧，且判据失效时自动退回现状）**：
1. ★ `TUNE_BUFFER_SIZE` 256KB → **4MB**（接收窗口 ≥ 一个 2MB 块 ⇒ 从源头消除部分发送）；
2. ★ **按对端分流收尾 ack 字节数**：判据 = 对端宣告的地址 == 我机 IP 且 devMode ≠ ANDROID
   （PC 的 `makeDataEnc(*p1,…)` 填的是**目标设备**信息 ⇒ 宣告的是我方 IP；真 1.35 宣告它自己）。
   命中则只回 `2`（N+1）；**判错只会退回 N+2，不会弄坏 1.35**（5.0.48 那条路径）；
3. ★ `sendByte` 回传布尔 + 走 UI 日志（原来异常被吞成一行 `Log.w`，对端在无超时地等它，必须可见）。
另外补了 `v5 对端宣告：name/ip/mode/ver` 一行日志 —— 下一次直接看判据命中没有。

**产物**：`E:\\lanshare-harmony\\LANShare-5.0.58.hap`（2,447,192 B）；
`BUILD SUCCESSFUL in 1min9s`；解包搜到 `判定为 PC 端发送器` / `收尾已回 2（PC 端按 N+1 读` /
`v5 对端宣告：name=` / `块应答发送失败` / `文件级应答发送失败` / `终态应答发送失败`；
`module.json` 报 5.0.58 / 5000058。commit `7de600d`，tag `v5.0.58`，夸克网盘，
并已推到手机 `Download/LANShare-5.0.58.hap`（vivi 自己装）。

**方法论（已归档 skill `harmonyos-tcp-socket-server` 第九节）**：
★ **「自己写的探针全过」不等于对端全过** —— 探针用标准流语义（Node 的 write 会正确处理部分写），
刚好绕开对端的缺陷。**验证跨端问题时，探针必须复刻对端的*读取*行为，而不只是发送行为。**
★ 「总是最后一项失败 + 卡满一个超时周期 + 连接没断」→ 先算 **ack 字节数 vs 对端读取次数**。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.count('### 16:15 5.0.57') == 1, '找不到 5.0.57 小节'
s2 = s + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK: 日志已追加，%d -> %d' % (len(s), len(s2)))
