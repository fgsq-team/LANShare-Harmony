import io, sys

SENTINEL = '## 12:57 5.1.26 心跳结果 —— 判决性实验版'
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if SENTINEL in s:
    print('ALREADY'); sys.exit(0)

ADD = """

## 12:57 5.1.26 心跳结果 —— 判决性实验版（5.1.27-ablate）

commit `3a77209`，HAP `LANShare-ABLATE-5.1.27.hap`（2,528,106 B，12:57 已推手机），
`versionName = 5.1.27-ablate` / `versionCode = 5000127`。

### ★ 心跳测量的决定性结果（THREAD_BLOCK **不是**误报）
`[HB]` 只在 >500ms 时打，**9 条全中**；`[UP]` 的 `hblag` 稳定 **365~524ms**
⇒ **事件循环确实被推迟约 450ms**。

累计口径（修正后的正确统计，640MB 全程）：
| 段 | 累计 | 占比 |
|---|---|---|
| `read` | **7 ms** | 0.02% |
| `feed` | **367 ms** | 1.3% |
| `other` | **28,636 ms** | **98.7%** |

**时间线（关键）**：`[UP]` 首条 `12:51:18.313`，第一次 `[HB]` `12:51:19.610`
⇒ 心跳报警**晚于上传起点 1.30 秒** ⇒ **是上传造成的，且从一开始就这样**。
★ 排除「开头快、后期慢」：实测**前 16MB 就要 0.813s**，全程恒定 ~17MB/s。

### 候选收敛到只剩一个
循环体除 `readSome`/`feed` 外只剩三件事：
1. **`notifyUploadProgress`** → `emitThrottled`（**100ms 节流**）→ **ArkUI 重建整页** ← 唯一未证伪
2. `yieldFrame`（每 8MB）← **5.1.25 已证伪**（8→32 降 4 倍，速度 16.5→16.7 零变化）
3. `if (!mp.ok) break` ← 不耗时

★★ **关键机理**：5.1.24 把上报节流从 `200ms/256KB` 放宽到 `1000ms/4KB`（**16 倍**）
之所以**完全无效**，是因为瓶颈在 **`emitThrottled` 内部那层 100ms 节流 + ArkUI 整页重建**，
不在外层那个参数。**调错了旋钮**：外层节流管「多久调一次 `emitThrottled`」，
内层 100ms 节流管「多久真的 emit 一次」⇒ 后者才是 bottleneck。

### 本版判决性实验：`UPLOAD_DIAG_DISABLE_UI = true`
进度上报与让帧**全部关闭**。⚠️ **故意牺牲 UI 响应**（进度条不动、界面卡）——
一次实验换掉「到底是 UI 重建还是协议层」这个问号。改 `false` 即回 5.1.26 行为。

| 观测结果 | 结论 |
|---|---|
| 速度飙升 50MB/s 且不崩 | 确认 ArkUI 重建是唯一瓶颈 |
| 仍 17MB/s 但不崩 | 重建是「卡」的来源，吞吐另有原因 |
| **仍崩在 40%** | 与 UI 无关 ⇒ 纯协议/对端问题（5.1.12 也崩 ⇒ **基线问题**） |

### 踩坑：ArkTS 顶层常量**不能**用 `类名.` 前缀引用
`const UPLOAD_DIAG_DISABLE_UI = true` 定义在**模块顶层**（不在 class 里），
写成 `HttpRouter.UPLOAD_DIAG_DISABLE_UI` 编译报
`Property does not exist on type 'typeof HttpRouter'`。
⇒ **模块级 `const` 用裸名；只有 `static` 类成员才加类名前缀。**

### ★ 方法论再补一条
★ **节流要分层看**：外层参数（多久调一次）与内层参数（多久生效一次）
  是**两级不同的节流**。只调外层而内层更严 ⇒ 表现为「参数调了 16 倍但零效果」。
  排查时必须把**整条调用链上所有节流点**列出来，而不是只看自己改的那一个。
"""
s = s.rstrip('\n') + ADD + '\n'
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count('\ufffd')))
