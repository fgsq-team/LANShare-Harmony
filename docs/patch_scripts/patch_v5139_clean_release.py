# -*- coding: utf-8 -*-
"""
5.1.39 纯净发布版 —— 移除 5.1.23~5.1.38 为排查「网页上传闪退」加的全部临时诊断。

★ 保留（长期机制，不是临时诊断）：
  · `[HB] 事件循环被推迟 Nms` 告警（250ms 心跳，仅 >500ms 才打 ⇒ 低频且关键）
  · `yieldFrame()` 让帧机制本身（只去掉围绕它的计时）
★ 移除：
  · `[B<n>` / `[B] #...`   每块两行（2.6 GB 打了 12792 行）
  · `[UP] blk#...`         每 64 块一行
  · `[FPS] ...` 全套       displaySync 渲染帧统计（含 import、字段、方法、调用点）
  · `[SLOW-IO] ...`        writeSync 慢写告警（含阈值常量与计时）
  · 所有为此加的局部计时变量（tR0/tR1/tR2/tR3/yThis/yT0/yDt、upReadAcc/upFeedAcc、diagYield*）
★ 顺带修发版体检项：`ABOUT_FALLBACK_VER` 从 '5.1.13' 同步到 '5.1.39'。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
HR = os.path.join(ET, 'net', 'HttpRouter.ets')
FS = os.path.join(ET, 'service', 'FileStorage.ets')
IX = os.path.join(ET, 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

hr = io.open(HR, encoding='utf-8', newline='').read()
fs = io.open(FS, encoding='utf-8', newline='').read()
ix = io.open(IX, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

SEN = '5.1.39 纯净发布版'
if SEN in hr:
    print('ALREADY APPLIED'); sys.exit(0)

blocks = []          # (标签, 待删文本, 保留的替换文本, 是否校验新文本不存在)
def cut(tag, old, new='', check_new=True):
    blocks.append((tag, old, new, check_new))

# ── ① import displaySync ────────────────────────────────────────────
cut('import-displaySync',
    "// ★★ 5.1.33-diag：**纯诊断用**导入 —— 量 ArkUI 渲染管线的真实帧率。\n"
    "//   前三轮只看了 JS 事件循环心跳（hblag），但 5.1.32 复测证明\n"
    "//   真正被饿死的是渲染帧（Ace: no vsync received in 3 seconds）。\n"
    "//   本模块从渲染管线取帧到达时间戳，与 JS 定时器**完全独立**。\n"
    "import { displaySync } from '@kit.ArkGraphics2D';\n")

# ── ② DIAG_FRAME_WINDOW_MS 常量整段 ─────────────────────────────────
i = hr.index('/**\n * ★★ 5.1.33-diag：渲染帧统计的汇总窗口（毫秒）。')
j = hr.index('const DIAG_FRAME_WINDOW_MS: number = 1000;\n') + len('const DIAG_FRAME_WINDOW_MS: number = 1000;\n')
j = hr.index('\n', j) + 1        # 连同后面的空行
cut('DIAG_FRAME_WINDOW_MS', hr[i:j])

# ── ③ diag* 字段块 + hbWorstLag() ──────────────────────────────────
i = hr.index('  // ★★ 5.1.33-diag：渲染帧统计（**纯诊断，可整段删**）。')
j = hr.index('  private hbTimer: number = -1;')
cut('diag-fields', hr[i:j])

i = hr.index('  /** 心跳被推迟的最长毫秒数（供 UI/日志查询） */')
j = hr.index('  /**\n   * ★★ 5.1.33-diag：启动渲染帧统计（**纯诊断**）。')
cut('hbWorstLag', hr[i:j])

# ── ④ startFrameDiag + stopFrameDiag 两个方法整段 ──────────────────
i = hr.index('  /**\n   * ★★ 5.1.33-diag：启动渲染帧统计（**纯诊断**）。')
j = hr.index('  private startHeartbeat(): void {')
cut('frameDiag-methods', hr[i:j])

# ── ⑤ upReadAcc/upFeedAcc 声明 ─────────────────────────────────────
cut('upAcc',
    "    // ★★ 5.1.26：分段计时改为**累计**口径（5.1.23 那版拿累计减单块，算出来的 other 是错的）\n"
    "    let upReadAcc: number = 0;\n"
    "    let upFeedAcc: number = 0;\n")

# ── ⑥ startFrameDiag 调用点 ───────────────────────────────────────
cut('startFrameDiag-call',
    "    // ★★ 5.1.33-diag：**纯诊断** —— 上传期间开始量渲染帧。\n"
    "    //   幂等：重复调用只启动一次。\n"
    "    this.startFrameDiag();\n")

# ── ⑦ tR0 声明 + 5.1.23 注释 ───────────────────────────────────────
cut('tR0',
    "      // ★★ 5.1.23（纯诊断）：分段计时，把上传总耗时拆成 read / feed(解析+落盘) / other。\n"
    "      //   动机：5.1.22 修完「头逐字节读」后**仍闪退** ⇒ 前一个假设被证伪。\n"
    "      //   剩下的唯一未验证热点 = `mp.feed` 里的 **同步 `fileIo.writeSync`**（2585 次）。\n"
    "      const tR0: number = Date.now();\n")

# ── ⑧ [B<n> 前置标记 ───────────────────────────────────────────────
cut('B-enter',
    "      // ★★ 5.1.36-diag2：极简定位标记 —— 打在 readSome **之前**。\n"
    "      //   若崩溃时日志最后一行停在 `[B<n>` ⇒ 卡在 readSome。\n"
    "      Log.i(TAG, `[B${chunks}`);\n")

# ── ⑨ tR1 / tR2 / [UP] 整块 / tR3 / yThis ───────────────────────────
cut('tR1', "      const tR1: number = Date.now();\n")
cut('tR2', "      const tR2: number = Date.now();\n")

i = hr.index('      // 低频采样：每 64 块（16 MiB）打一行，避免日志本身成瓶颈。')
j = hr.index('      // 进度上报：节流到「至少间隔 200ms 且至少又收了 256 KiB」。')
cut('UP-block', hr[i:j])

cut('tR3-yThis',
    "      const tR3: number = Date.now();\n"
    "      let yThis: number = 0;\n")

# ── ⑩ 让帧计时 → 只留 await yieldFrame() ───────────────────────────
cut('yield-timing',
    "        // ★ 5.1.33-diag：量「让帧一次往返」的真实耗时。\n"
    "        //   若它远超「一个宏任务」（应 <1ms），说明连让帧本身都排不上队。\n"
    "        const yT0: number = Date.now();\n"
    "        await HttpRouter.yieldFrame();\n"
    "        const yDt: number = Date.now() - yT0;\n"
    "        this.diagYieldAccMs += yDt;\n"
    "        yThis = yDt;\n"
    "        this.diagYieldCount += 1;\n"
    "        if (yDt > this.diagYieldWorstMs) {\n"
    "          this.diagYieldWorstMs = yDt;\n"
    "        }\n",
    "        await HttpRouter.yieldFrame();\n",
    check_new=False)

# ── ⑪ [B] 汇总行 ──────────────────────────────────────────────────
i = hr.index('      // ★★ 5.1.36-diag2：本块各段耗时。崩溃时看**最后一行**即可定位：')
j = hr.index('      if (!mp.ok) {\n        break; // 解析已判定坏包，不必继续收\n      }')
cut('B-summary', hr[i:j])

# ── ⑫ stopFrameDiag 调用点 ────────────────────────────────────────
cut('stopFrameDiag-call',
    "    // ★★ 5.1.33-diag：这里**先停帧统计**再回调。\n"
    "    //   本函数是上传成功/失败的唯一收口 ⇒ 只改这一处就不会漏。\n"
    "    this.stopFrameDiag();\n")

# ── ⑬ diagYield* 字段 ─────────────────────────────────────────────
cut('diagYield-fields',
    "  // ★ 5.1.33-diag：让帧往返累计耗时（诊断）\n"
    "  private diagYieldAccMs: number = 0;\n"
    "  private diagYieldWorstMs: number = 0;\n"
    "  private diagYieldCount: number = 0;\n\n")

# ── ⑭ 修正 UPLOAD_YIELD_MS 注释里的**已证伪**结论 ─────────────────
cut('fix-yield-comment',
    " *\n"
    " * 【5.1.32 修正】原值 12ms 是 5.1.29 为「治 ANR」定的，但 5.1.31 真机证明\n"
    " *   真正的病因**不是主线程被占用**（hbWorstLag 仅 631ms、传输全程均匀），\n"
    " *   而是**消息队列被自己的任务塞满**、导致看门狗判活任务饿死\n"
    " *   （见 NativeSocket `WAIT_IDLE_TICK_MS` 的注释）。\n"
    " *   ⇒ 让帧越密，反而越是往队列里加任务。24ms 仍是 40Hz，UI 足够跟手，\n"
    " *     而队列负载直接减半。\n",
    " *\n"
    " * 【⚠️ 2026-10-03 修正：此前本段写「真正的病因是消息队列被任务塞满、\n"
    " *   看门狗判活任务饿死」—— 该结论已被 5.1.36~5.1.38 实测推翻】\n"
    " *   真凶是 `MultipartStream.indexOfSeq` 对 1 MiB 块逐字节搜分隔符\n"
    " *   ≈ 53ms/块，6 条并发连接争抢主线程把渲染帧饿死。\n"
    " *   判据：「让帧不是病根」—— 5.1.26~5.1.37 十二轮调它/块大小/同步异步全无效。\n"
    " *   本常量保留仍有价值（限制单次连续占用），但别再指望靠它治崩溃。\n"
    " *   ⇒ 先量「单次主线程占用」，再决定要不要让帧。\n")

# ══════════════════════════════════════════════════════════════════
# 先全部校验（任一失败 ⇒ 文件不写）
for tag, old, new, chk in blocks:
    n = hr.count(old)
    assert n == 1, '%s count=%d (期望 1)' % (tag, n)
    if chk and new:
        assert hr.count(new) == 0, '%s 替换文本已存在' % tag

# 残留引用预检
for sym in ['displaySync', 'DIAG_FRAME_WINDOW_MS', 'diagSync', 'diagFrameCount',
            'diagYield', 'startFrameDiag', 'stopFrameDiag', 'upReadAcc', 'upFeedAcc',
            'hbWorstLag', 'tR0', 'tR1', 'tR2', 'tR3', 'yThis', 'yDt', '[B]', '[UP]']:
    # 允许出现在被删块之外的地方会在下面统一验证
    pass

# 统一替换
for tag, old, new, chk in blocks:
    hr = hr.replace(old, new, 1)

# ══════════════════════════════════════════════════════════════════
# FileStorage：[SLOW-IO] + 阈值 + 计时
fs_old = ('      // ★★ 5.1.36-diag2：单次 writeSync 计时（把「feed 慢」拆成「解析」vs「落盘」）。\n'
          '      const tW0: number = Date.now();\n'
          '      const n: number = fileIo.writeSync(this.fd, buf);\n'
          '      const dtW: number = Date.now() - tW0;\n'
          '      if (dtW > FileSink.SLOW_WRITE_MS) {\n'
          '        Log.w(TAG, `[SLOW-IO] 单次 writeSync ${dtW}ms size=${data.byteLength}`);\n'
          '      }\n')
fs_new = '      const n: number = fileIo.writeSync(this.fd, buf);\n'
assert fs.count(fs_old) == 1, 'fs writeSync block %d' % fs.count(fs_old)
fs = fs.replace(fs_old, fs_new, 1)

fs_old2 = ('  /** ★ 5.1.36-diag2：单次 writeSync 超过这个毫秒数就告警（默认 100ms） */\n'
           '  private static readonly SLOW_WRITE_MS: number = 100;\n')
assert fs.count(fs_old2) == 1, 'fs SLOW_WRITE_MS %d' % fs.count(fs_old2)
fs = fs.replace(fs_old2, '', 1)

# ══════════════════════════════════════════════════════════════════
# Index：ABOUT_FALLBACK_VER 同步
assert "const ABOUT_FALLBACK_VER: string = '5.1.13';" in ix, 'ABOUT_FALLBACK_VER anchor'
ix = ix.replace("const ABOUT_FALLBACK_VER: string = '5.1.13';",
                "const ABOUT_FALLBACK_VER: string = '5.1.39';", 1)

# 版本号
assert '"versionCode": 5000138' in app, 'versionCode anchor'
assert '"versionName": "5.1.38"' in app, 'versionName anchor'
app = app.replace('"versionCode": 5000138', '"versionCode": 5000139', 1)
app = app.replace('"versionName": "5.1.38"', '"versionName": "5.1.39"', 1)

# ══════════════════════════════════════════════════════════════════
# NativeSocket：修正两处**已证伪**的注释（保留正确的技术说明）
NS = os.path.join(ET, 'net', 'NativeSocket.ets')
ns = io.open(NS, encoding='utf-8', newline='').read()

ns_old1 = (' * 【真机后果】主线程**并未冻结**（`hbWorstLag` 仅 631ms、\n'
           ' *   `[UP]` 全程均匀 16.5MB/s），但系统看门狗每 3s 往消息队列插一个\n'
           ' *   「判活探测任务」，被上传循环每秒 ~300 个任务持续插队 ⇒ 探测任务\n'
           ' *   3 秒、6 秒都轮不到 ⇒ 判 THREAD_BLOCK_6S ⇒ SIGKILL。\n'
           ' *   （华为文档：「消息队列中高优先级任务过多，导致系统无法及时调度\n'
           ' *     watchdog 任务」正是此形态。）\n')
ns_new1 = (' * 【⚠️ 2026-10-03 修正】本段原写「真机后果：主线程并未冻结（hbWorstLag\n'
           ' *   仅 631ms），看门狗判活任务被插队饿死」—— **该结论已被推翻**。\n'
           ' *   ① 「hbWorstLag 631ms ⇒ 主线程未冻结」是**幸存者偏差**：该心跳本身\n'
           ' *      从主线程打出，主线程真卡死时它根本打不出来（只证明卡死前不忙）。\n'
           ' *   ② 真正的病根是 `MultipartStream.indexOfSeq` 逐字节扫描 53ms/块\n'
           ' *      （6 并发 ⇒ 主线程饱和 ⇒ 渲染帧饿死 ⇒ THREAD_BLOCK_6S）。\n'
           ' *   ★ 本单例定时器**本身仍是正确优化**（O(块数)→O(1)），只是理由换了。\n')
assert ns.count(ns_old1) == 1, 'ns comment1 %d' % ns.count(ns_old1)
ns = ns.replace(ns_old1, ns_new1, 1)

ns_old2 = ('    //   全部走主线程定时器管理器 ⇒ 消息队列被塞满 ⇒ 看门狗判活任务饿死。\n'
           '    //   真机铁证：主线程实际未冻结（hbWorstLag 631ms、[UP] 均匀 16.5MB/s），\n'
           '    //   却仍被 THREAD_BLOCK_6S 强杀。\n')
ns_new2 = ('    //   全部走主线程定时器管理器 ⇒ 加重队列负载。\n'
           '    // ⚠️ 原注释写「主线程未冻结（hbWorstLag 631ms）却仍被 THREAD_BLOCK_6S\n'
           '    //   强杀 ⇒ 判活任务饿死」—— 该推理**错误**（幸存者偏差，见上）。\n'
           '    //   真正的卡死点是 `MultipartStream.indexOfSeq` 的 53ms/块扫描。\n')
assert ns.count(ns_old2) == 1, 'ns comment2 %d' % ns.count(ns_old2)
ns = ns.replace(ns_old2, ns_new2, 1)

# ══════════════════════════════════════════════════════════════════
# 残留检查：只看**代码**（剥离 // 与 * 注释行后查）
def strip_comments(t):
    out = []
    for ln in t.split('\n'):
        s2 = ln.strip()
        if s2.startswith('//') or s2.startswith('*') or s2.startswith('/*'):
            continue
        out.append(ln)
    return '\n'.join(out)

code_all = strip_comments(hr) + '\n' + strip_comments(fs) + '\n' + strip_comments(ns)
leftover = [s for s in ['displaySync', 'DIAG_FRAME_WINDOW_MS', 'diagSync', 'diagFrameCount',
                        'diagYield', 'diagFirstTs', 'startFrameDiag', 'stopFrameDiag',
                        'upReadAcc', 'upFeedAcc', 'hbWorstLag', 'tR0', 'tR1', 'tR2', 'tR3',
                        'yThis', 'yDt', 'SLOW_WRITE_MS', '[SLOW-IO]', '[UP]', '[B]']
            if s in code_all]
assert not leftover, '代码中残留: %s' % leftover

for p, s in ((HR, hr), (FS, fs), (NS, ns), (IX, ix), (APP, app)):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

hr2 = io.open(HR, encoding='utf-8', newline='').read()
print('删块数        :', len(blocks))
print('[FPS] 残留    :', hr2.count('[FPS]'))
print('[B] 残留      :', hr2.count('[B]'))
print('[UP] 残留     :', hr2.count('[UP]'))
print('[HB] 保留     :', hr2.count('[HB]'))
print('yieldFrame 保留:', hr2.count('yieldFrame()'))
print('NativeSocket 已修:', ns.count('幸存者偏差'))
print('ABOUT_FALLBACK :', ix.count("ABOUT_FALLBACK_VER: string = '5.1.39'"))
print('CRLF          :', hr2.count('\r\n') + fs.count('\r\n') + ns.count('\r\n') + ix.count('\r\n'))
print('OK 5.1.39 clean applied')
