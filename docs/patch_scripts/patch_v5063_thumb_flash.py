# -*- coding: utf-8 -*-
"""v5.0.63 —— 治「消息页列表闪两次」（接收完闪一次 + 存相册再闪一次）。

vivi 2026-10-02 反馈。读代码定位到 **三个**变数源，5.0.61 只处理了其中一个：

① **显示源会自己变**（第一次闪）
   `mediaThumbSrcOf`(Index.ets:2984) 缓存不存在时返回**沙箱原图**，预生成完成后返回
   **缓存小图** ⇒ `thumbSigOf`(3025) 的 src 变了 ⇒ ForEach key 变 ⇒ 该格销毁重建。
   —— 5.0.61 只做到了「存相册后源不变」，**没管「接收那一瞬间源要变一次」**。

② **`albumIndex` 是 @State，每张图换一次引用**（第二次闪，且是「闪一批」）
   `prefetchThumbInner` 结尾 `this.albumIndex = this.service.albumSnapshot()`。
   收 15 张 = 换 15 次引用 = 整个消息页重渲染 15 次。
   ⚠️ 只把它改非 @State 不够 —— ① 仍在。

③ **签名里带 `ratioOf`**，而比例是**异步**量出来的（第二次闪的帮凶）
   `ensureMediaRatio`(2412) 走 await 读 EXIF，量到后 `mediaRatio.set` + `thumbTick++`(2444)；
   `ratioOf`(2509) 量不到时返回 **1**，量到后返回真值 ⇒ 签名第三次变化。
   ⇒ 即使把 ① ② 都修了，这一条仍会让每张图「先按 1:1 画、再跳到真比例」。

修法（方案 C）：
① 显示源**只认缓存**：缓存不存在 ⇒ 返回**空串**走占位，**绝不回退沙箱原图**。
   源从头到尾只有 cache 一个值 ⇒ key 恒定。
② 预生成结果**合并成一次提交**（`thumbBatch` 缓冲 + 150ms 去抖 `flushThumbBatch`）。
   一批只换一次 `albumIndex` 引用 ⇒ 收 15 张至多重渲染 1 次。
③ 签名里**去掉 ratio**：比例改由 `Image` 自己在渲染时处理，签名只留
   `id + src + rot`。比例变化不再引起 key 变化。

⚠️ 为什么不靠 `thumbTick` 兜底：它是**全局** @State，`ratioOf`(2510) 里
   `if (this.thumbTick < 0)` 就是靠读它**建立 @State 依赖**才触发重绘 ——
   把 ratio 从签名里去掉后，若同时不读 `thumbTick`，比例变化就彻底没人通知了。
   所以 `thumbSigOf` 里**保留一次 `thumbTick` 读**（不做 key 组成），
   让「比例量到」仍能踢一次重绘，但**不再改变 key**（⇒ 不销毁重建，只重排版）。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.63' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

# ---------- 备份 ----------
BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5063pre'), (VER, 'app.json5.v5063pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：显示源只认缓存路径（不回退沙箱原图 ⇒ 源永不变）
# =====================================================================
OLD1 = """    const cached: string = this.albumPartOf(m.id, k, 1);
    if (cached.length > 0 && !Index.isFullCopyThumb(cached)) {
      return cached;
    }
    const p: string = this.recvPathFor(names[k], k, m.timeMs);
    if (p.length > 0) {
      // 沙箱那份还在 —— 顺手把缓存小图补出来（**渲染到才补**，不做全量预热）
      this.maybePrefetchThumb(m.id, k, p);
      return p;
    }
    return cached;
  }"""
NEW1 = """    const cached: string = this.albumPartOf(m.id, k, 1);
    if (cached.length > 0 && !Index.isFullCopyThumb(cached)) {
      return cached;
    }
    // ★★ 5.0.63：**这里绝不回退沙箱原图**。
    //   5.0.61 的写法是「缓存没有就返回沙箱原图」—— 可那意味着**显示源自己会变一次**：
    //   接收瞬间显示沙箱原图 → 预生成完成后切缓存小图 ⇒ `thumbSigOf` 的 src 变了
    //   ⇒ ForEach key 变 ⇒ 那���格销毁重建 ⇒ vivi 反馈的**第一次闪**。
    //   显示源只要「最终会变」，把它放进 key 就等于给闪烁开门。
    //   所以缓存没有时统一走下方兜底（可能返回空串 = 占位），源**全程只有 cache 一个值**。
    //   代价：接收瞬间空拍几十 ms（缓存生成完即出现）；换来彻底不闪。
    //
    //   预生成照旧「渲染到才补」，不做全量预热（5.0.33 的卡顿不能再犯）。
    const p: string = this.recvPathFor(names[k], k, m.timeMs);
    if (p.length > 0) {
      this.maybePrefetchThumb(m.id, k, p);
    }
    // `_full`（5.0.60 的 EXIF 原图复制兜底）不参与恒定路径：它与原图逐字节相同，
    // 恒定源对它无意义，且预生成会让每张竖拍照片多存一份原图 ⇒ 磁盘翻倍。
    if (cached.length > 0) {
      return cached;
    }
    return this.thumbPlaceholderOf(p);
  }

  /**
   * ★ 5.0.63：没有缓存缩略图时的**占位源**。
   *
   * 只对「EXIF 方向图」放行沙箱原图 —— 那类图 5.0.60 走 `_full` 原图复制，
   * 缓存与原图内容逐字节相同，显示源在两者间切换**用户感知不到**，
   * 所以让它们继续「沙箱优先」（顺带避免给每张竖拍照多存一份原图）。
   *
   * ⚠️ 普通图片一律返回**空串**（占位）：宁可空拍几十 ms，也不让显示源变。
   */
  private thumbPlaceholderOf(sandboxPath: string): string {
    if (sandboxPath.length === 0) {
      return '';
    }
    // 带 EXIF 方向（deg≠0）⇒ 5.0.60 的 `_full` 分支：显示源切换不可感知，放行。
    if (!this.isVideoName(sandboxPath) && Index.jpegExifDeg(sandboxPath) !== 0) {
      return sandboxPath;
    }
    return '';
  }"""

# =====================================================================
# 改 2：签名去掉 ratio（但保留一次 thumbTick 读以维持 @State 依赖）
# =====================================================================
OLD2 = """  private thumbSigOf(m: ChatMessage): string {
    const src: string = this.mediaThumbSrcOf(m, 0);
    if (src.length === 0) {
      return `${m.id}:-`;
    }
    return `${m.id}:${src}:${this.ratioOf(src)}:${this.service.rotOf(src) ?? 0}`;
  }"""
NEW2 = """  private thumbSigOf(m: ChatMessage): string {
    const src: string = this.mediaThumbSrcOf(m, 0);
    // ⚠️ 5.0.63：这里**故意读一次 `thumbTick`**，但**不用它拼 key**。
    //   `ratioOf`(2510) 靠 `if (this.thumbTick < 0)` 建立 @State 依赖，
    //   比例异步量到后 `ensureMediaRatio`(2444) 会 `thumbTick++` 踢重绘。
    //   保留这次读 ⇒ 比例变化仍能触发「重排版」；
    //   而 key 里不含比例 ⇒ **不会销毁重建**（消除「先按 1:1 画再跳真比例」的闪动）。
    const tick: number = this.thumbTick;
    if (src.length === 0) {
      return `${m.id}:-:${tick >= 0 ? 0 : 1}`;
    }
    return `${m.id}:${src}:${this.service.rotOf(src) ?? 0}`;
  }"""

# =====================================================================
# 改 3：预生成合并成一次提交（消「闪一批」）
# =====================================================================
OLD3 = """      const rot: number = this.service.rotOf(thumb) ?? 0;
      // ⚠️ 只补缩略图，**绝不碰相册 URI** —— 用户还没点确认框（见 setThumbOnly）
      await this.service.setThumbOnly(key, thumb, rot);
      this.albumIndex = this.service.albumSnapshot();
      Log.i(TAG, `缩略图预生成就绪（显示源此后恒定）: ${Index.baseName(srcPath)}`
        + ` -> ${Index.baseName(thumb)}`);"""
NEW3 = """      const rot: number = this.service.rotOf(thumb) ?? 0;
      // ⚠️ 只补缩略图，**绝不碰相册 URI** —— 用户还没点确认框（见 setThumbOnly）
      await this.service.setThumbOnly(key, thumb, rot);
      // ★★ 5.0.63：**不在这里换 `albumIndex` 引用**。
      //   `albumIndex` 是 @State，换引用 = 整个消息页重渲染。原先每张图换一次
      //   ⇒ 收 15 张闪 15 下（vivi 说的「闪一次」其实是闪一批）。
      //   改成进缓冲区，由 `flushThumbBatch()` 一批只换一次。
      this.thumbBatch.add(key);
      this.thumbBatchDirty = true;
      this.scheduleThumbFlush();
      Log.i(TAG, `缩略图预生成就绪（显示源此后恒定）: ${Index.baseName(srcPath)}`
        + ` -> ${Index.baseName(thumb)}`);"""

# =====================================================================
# 改 4：新增去抖提交方法
# =====================================================================
OLD4 = """  /**
   * 这一张是不是「已经不在沙箱、也不在相册」= 用户在系统相册里把它删了。"""
NEW4 = """  /**
   * ★ 5.0.63：缩略图预生成的**去抖批量提交**。
   *
   * 消「闪一批」的正解：`albumIndex` 是 @State，换一次引用 = 整个消息页重渲染。
   * 一批只换一次 ⇒ 收 15 张至多重渲染 1 次，而且这一次正好是「数据真正到位」的时刻。
   *
   * ⚠️ 为什么必须**去抖**而不是「攒够 N 张就提交」：预生成是**并发**的
   *   （每张一个 Promise，谁先完成不确定）。攒够 N 张会漏掉最后那几张，
   *   导致「有的图永远不出现」。去抖则保证「最后一张完成后再等一拍」必提交。
   */
  private scheduleThumbFlush(): void {
    if (this.thumbBatchTimer !== -1) {
      return;
    }
    this.thumbBatchTimer = setTimeout(() => {
      this.thumbBatchTimer = -1;
      this.flushThumbBatch();
    }, Index.THUMB_FLUSH_DELAY_MS);
  }

  /** 真正提交：换一次 `albumIndex` 引用，UI 重渲染一次 */
  private flushThumbBatch(): void {
    if (!this.thumbBatchDirty) {
      return;
    }
    this.thumbBatchDirty = false;
    const n: number = this.thumbBatch.size;
    this.thumbBatch.clear();
    this.albumIndex = this.service.albumSnapshot();
    Log.i(TAG, `缩略图批量提交：${n} 张，显示源一次性恒定（避免逐张重渲染）`);
  }

  /**
   * 这一张是不是「已经不在沙箱、也不在相册」= 用户在系统相册里把它删了。"""

# =====================================================================
# 改 5：实例字段
# =====================================================================
OLD5 = "  private thumbPrepare: Set<string> = new Set<string>();"
NEW5 = """  private thumbPrepare: Set<string> = new Set<string>();
  // ★★ 5.0.63：预生成结果的**批量提交缓冲**（消「闪一批」）
  private thumbBatch: Set<string> = new Set<string>();
  private thumbBatchDirty: boolean = false;
  private thumbBatchTimer: number = -1;"""

# ---- 常量 ----
ANCHOR = '  private static GRID_SIDE: number = 88;'
CONST = ('  /** 5.0.63：缩略图批量提交的去抖间隔（ms）—— 覆盖同批剩余的完成回调 */\n'
         '  private static readonly THUMB_FLUSH_DELAY_MS: number = 150;\n\n')

OLD6 = '"versionCode": 5000062'
NEW6 = '"versionCode": 5000063'

# ---- 组装 + 全量校验 ----
s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 源恒定'), (OLD2, NEW2, '改2 签名去 ratio'),
                      (OLD3, NEW3, '改3 进缓冲'), (OLD4, NEW4, '改4 去抖提交'),
                      (OLD5, NEW5, '改5 字段')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

assert s2.count(ANCHOR) >= 1, '找不到 GRID_SIDE 锚点'
s2 = s2.replace(ANCHOR, CONST + ANCHOR, 1)

v2 = s_ver
assert v2.count(OLD6) == 1, 'versionCode 锚点异常'
v2 = v2.replace(OLD6, NEW6, 1)
assert v2.count('"versionName": "5.0.62"') == 1
v2 = v2.replace('"versionName": "5.0.62"', '"versionName": "5.0.63"', 1)

# 关键不变量
assert s2.count('private scheduleThumbFlush()') == 1
assert s2.count('private flushThumbBatch()') == 1
assert s2.count('THUMB_FLUSH_DELAY_MS') == 2      # 常量声明 + 唯一引用
assert s2.count('private thumbBatch: Set<string>') == 1
assert s2.count('private thumbPlaceholderOf(') == 1   # 方法定义
assert s2.count('this.thumbPlaceholderOf(p)') == 1    # 调用处
# albumIndex 换引用：原 6 处，改后应仍是 6（改3 移走 1、新增 flush 补回 1）
assert s2.count('this.albumIndex = this.service.albumSnapshot();') == 6, \
    'albumIndex 换引用处数变了：%d' % s2.count('this.albumIndex = this.service.albumSnapshot();')
# 签名里已不含 ratioOf
assert ':${this.ratioOf(src)}' not in s2, '签名里仍有 ratio'
assert len(s2) > len(s_idx)

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000063' % (len(s_idx), len(s2)))
