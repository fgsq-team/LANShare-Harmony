import io, sys

SENTINEL = '## 13:07 5.1.28 正式修法（判决实验出结论）'
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if SENTINEL in s:
    print('ALREADY'); sys.exit(0)

ADD = """

## 13:07 5.1.28 正式修法（判决性实验出结论）

commit `989977b` + tag `v5.1.28`，versionCode `5000128`，
HAP `LANShare-5.1.28.hap`（2,529,396 B，13:07 已推手机）。

### ★★★ 判决性实验结论（5.1.27-ablate，真机 646MB 一次成功）
| 版本 | 速度 | 心跳报警 | 结果 |
|---|---|---|---|
| 5.1.26（有 UI）| 16.6 MB/s | **9 条** | **崩在 480MB** |
| 5.1.27（关 UI）| 17.7 MB/s | 1 条 | **646MB 全部完成** ✓ |

⇒ **ArkUI 重建不是吞吐瓶颈**（我 5.1.27 的猜测被自己的实验否掉了）。
⇒ 关掉 UI 后不崩 ⇒ UI 相关，但不是限速项。
⇒ `ui_log` 确认服务端**确实完整落盘**：「网页上传完成：xxx（646.1 MB）」。

### ★★ 真正的信号：`hblag` 单调递增（本轮唯一硬发现）
```
blk#2752  502.4MB  hblag=33
blk#2816  515.3MB  hblag=83
blk#2944  541.6MB  hblag=1347
blk#3072  565.1MB  hblag=2749
blk#3456  638.7MB  hblag=7338   ← 7.3 秒
```
累计口径 646MB 全程：`read 21ms(0.06%)` / `feed 502ms(1.39%)` / `other 98.55%`
⇒ 上传循环**几乎没在干活**，时间全在「等」；
⇒ 事件循环定时器被**系统性推迟、越积越慢** = 「40% 卡住 → 6s 无响应 → SIGKILL」的机制。

### 根因：`readSome` 每次挂一个「分钟级」定时器
`readSome(256KB, remain)` 的 `remain` = **整次上传剩余超时（最大 10 分钟）**，
而 `waitForData(timeoutMs)` 内部就是 `setTimeout(..., timeoutMs)`
⇒ **每轮循环挂一个超长定时器**，只因「数据通常先到、`fire()` 提前 clear」才没出事。
代价：640MB/256KB = 2560 轮 × 6 个并发连接 ≈ **1.5 万次长定时器挂/清**，
定时器队列被反复撑大 ⇒ 事件循环调度越积越慢。

**修法**：单次 `readSome` 传固定 `UPLOAD_READ_TIMEOUT_MS = 30s`；
外层 10 分钟总超时不变 ⇒ 不误杀慢速连接。

### 修法 A：App 端完成提示（vivi「网页有提示，App 没有」）
**根因不是 5.1.27 的回归** —— 5.1.12 及以前就没有完成提示：
App 的传输提示是**浮层** `transferFloat`（靠 `snapshot.transferText` 驱动），
而 `onWebUploadEnd` **第一行**就 `transferText = ''`
⇒ 浮层在结束那一瞬直接消失，**从来没有完成态**。
（消息页那条 `appendFileChat(..., 'web')` 记录是另一回事，要切页才看见。）

**改法**：完成时先置 `✓ 网页上传完成：xxx（646.1 MB）` + `percent=100` 并 emit，
**1.5 秒后**再清空。定时器句柄存 `uploadDoneTimer`（连传多文件时旧的要作废）。

★⚠️ **顺序契约（5.0.51 踩过）**：`transferText` 由非空变空是
**「传输结束、刷新文件页」**的触发信号（`Index.ets` 的 `onSnapshot` 靠它调
`refreshReceived`）⇒ **清空动作必须仍发生**，只推迟 1.5 秒，
否则文件页不自动刷新。

### ★★★ 方法论沉淀（本轮六轮，最贵的两条）
1. ★ **判决性实验（ablation）比推理强一个数量级**。
   本轮前五轮全靠读代码猜，全错；一次「关掉可疑项」的对照实验立刻定案：
   **关掉 UI 只 +7% 吞吐、但不再崩** ⇒ 这个组合本身就把答案锁死了。
   下次遇到「多候选、无差别」的场景，**别再猜第 N 个，直接做消融实验**。
2. ★ **单调递增的观测量指向「累积性负载」，指向「瞬时尖峰」**。
   `hblag` 从 33ms 一路涨到 7338ms —— 这个**形状**比它的数值更重要：
   说明是**定时器队列被反复撑大**这类累积效应，
   而不是某处代码偶尔慢一次。**看趋势形状，不要只看单点值。**
"""
s = s.rstrip('\n') + ADD + '\n'
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count('\ufffd')))
