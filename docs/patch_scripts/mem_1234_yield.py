import io, os, sys

# ---- 本次落盘（5.1.25：让帧频率 8→32，网页上传卡死+闪退的真凶）----
SENTINEL = '## 12:34 v5.1.25 让帧频率 8→32'
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if SENTINEL in s:
    print('ALREADY'); sys.exit(0)

ADD = """

## 12:34 v5.1.25 让帧频率 8→32（网页上传卡死+闪退的真凶）

commit `92c3ab6` + tag `v5.1.25`，versionCode `5000125`，HAP `LANShare-5.1.25.hap`（12:34 已推手机）。

### ★ 上一版（5.1.24）被自己的数据证伪
5.1.24 把进度上报节流从 200ms/256KB 放宽到 1000ms/4MB（**频率降 16 倍**），
**实测速度一点没变（16.5 → 16.7 MB/s）** ⇒ **进度上报不是瓶颈**，排除。

### 真凶：`UPLOAD_YIELD_EVERY = 8`（每 2 MiB 让一帧）
`[UP]` 分段计时（646MB，24 条采样）每 16 MiB 固定 ~890ms：

| 段 | 耗时 | 占比 |
|---|---|---|
| `readSome`（await 等数据）| **0 ms** | 0.0% |
| `mp.feed`（解析+2585 次 `writeSync` 落盘）| 14 ms | 1.6% |
| **其余 other** | **876 ms** | **98.4%** |

循环体里除这两项只剩「进度上报 + `yieldFrame` + `if(!mp.ok)`」。
前两项已排除 ⇒ 876ms 只能是 **8 次 `yieldFrame`** ⇒ **每次让帧 ≈ 110ms**。

**110ms 的来源**：`setTimeout(0)` 让出主线程后，**ArkUI 重建整个页面**（110ms/帧）。
每 2 MiB 付一次 ⇒ 天花板 ~17MB/s，与实测完全吻合。
⇒ **网页上传慢的根因与网络无关，是 UI 重建单帧太慢。**

### 为什么会 SIGKILL（THREAD_BLOCK_6S）
`ui_log` 里**同时有 6 个连接**在上传（浏览器并发开连接），
6 条 `serveUpload` 的让帧帧**排在同一主线程** ⇒ 连续 6×110ms 占用
⇒ XCollie 判定 THREAD_BLOCK_6S ⇒ 系统 SIGKILL（`exit with signal:9`）。
★ **两次上传都精确停在同一块**（`blk#1984`），正是这个「每 N MiB 一次的系统性停顿」被撞上。

⚠️ 现象上的一个坑：`[UP]` 日志在 THREAD_BLOCK 判定期间**仍在打印** ——
因为「让帧后 UI 重建很慢」不等于「线程没在跑」。
**不能凭「还有日志」判定主线程健康。**

### 5.1.12 为什么「没事」
它也是 `UPLOAD_YIELD_EVERY=8`（`HttpRouter.ets` 从 v5.0.47 基线起没改过），
但所有历史日志里「网页上传完成」**零记录** ⇒ 这场景**从未被测过**，不是没事而是从没试过。

### 改法
`8 → 32`（每 2 MiB → 每 8 MiB 让帧）：让帧开销 876 → 219ms，
预期 **17 → 50+ MB/s**（与 V5 接收同量级）。UI 最坏卡顿约 0.5s，可接受。
保留 `yieldFrame` 本身（不能删：否则上传期间 UI 完全冻结、按钮无响应）。

### ★★ 方法论沉淀（本轮连错四轮后的判据）
★ **上一版改动若实测无任何变化 ⇒ 它就不是瓶颈**（5.1.24 节流 16 倍 ⇒ 速度 0% 变化）。
  这是最便宜的排除法：**用「改 A 无变化」证伪 A**，而不是继续猜下一个。
★ **「让帧」类优化的代价常被忽略**：`setTimeout(0)` 本身不耗时，
  耗时的是**让出后那一帧的 UI 重建**。让帧越频繁，吞吐越低 —— 二者直接冲突。
  必须在「UI  responsiveness」与「吞吐」之间取折中，而不是一味多让。
★ **`[UP]` 分布里 `other` 占 98% 时，不要停在「other 是个黑盒」**：
  把循环体剩余语句**逐条列出来**（本例只剩 3 条），按「上一版是否已排除」筛，
  通常 1~2 轮就能锁定。
"""
s = s.rstrip('\n') + ADD + '\n'
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count('\ufffd')))
