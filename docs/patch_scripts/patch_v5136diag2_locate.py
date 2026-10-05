# -*- coding: utf-8 -*-
"""
5.1.36-diag2 —— **定位型探针**（不是修法，不改行为）

背景：5.1.29 / .31 / .32 / .33 / .34 / .35 连续六轮改「上传循环怎么让帧」，
      全部无效（5.1.35 仍 THREAD_BLOCK_6S，崩在 424MB / 25.2s）。

关键矛盾（必须靠探针解决）：
  · `[HB]` 最差仅 774ms、吞吐稳定 16.8MB/s、每 64 块耗时恒定无恶化
  · 却被系统判「6 秒无响应」
  ⇒ 但 `[HB]` / `[UP]` 都是**主线程打出来的**，主线程真卡死时它们**根本打不出来**
    （幸存者偏差）。最后一条 [UP] 在 25251ms，之后到被杀约 6 秒**一条都没有**
    ⇒ 主线程是**突然**卡死的，不是渐进恶化。

本版唯一目的：卡死发生时，日志**最后一行**能指认卡在哪一步。
  每块两行：
    `[B123`                                  ← 进入 readSome 前（极简，开销最小）
    `[B] #123 sz=N rd=X fd=Y pg=Z yl=W`     ← 本块各段耗时
  判读：
    最后一行是 `[B123`        ⇒ 卡在 readSome（对端/网络）
    最后一行 `[B] ... fd=` 大 ⇒ 卡在 mp.feed（解析 + writeSync）
    最后一行 `[B] ... pg=` 大 ⇒ 卡在**进度上报 → emit → UI**（★ 病根在 UI 层）
    最后一行 `[B] ... yl=` 大 ⇒ 卡在让帧
  另加 `FileSink.append` 的 writeSync 计时，>100ms 单独告警 ⇒ 区分「解析」与「落盘」。

零行为改动：只加计时与日志。
"""
import io
import os
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
HR = os.path.join(ET, 'net', 'HttpRouter.ets')
FS = os.path.join(ET, 'service', 'FileStorage.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

hr = io.open(HR, encoding='utf-8', newline='').read()
fs = io.open(FS, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

SENTINEL = '[B] #'
if SENTINEL in hr:
    print('ALREADY APPLIED'); sys.exit(0)

# ============================================================
# ① HttpRouter：进入 readSome 前的极简定位标记
# ============================================================
a1 = '      const chunk: Uint8Array | null = await channel.readSome(UPLOAD_CHUNK, UPLOAD_READ_TIMEOUT_MS);'
assert hr.count(a1) == 1, 'A1 count = %d' % hr.count(a1)
hr = hr.replace(
    a1,
    '      // ★★ 5.1.36-diag2：极简定位标记 —— 打在 readSome **之前**。\n'
    '      //   若崩溃时日志最后一行停在 `[B<n>` ⇒ 卡在 readSome。\n'
    "      Log.i(TAG, `[B${chunks}`);\n" +
    a1, 1)

# ============================================================
# ② 进度上报之后取 tR3；让帧块前声明 yThis
# ============================================================
a2 = '      // ★★ 5.1.29：让帧判据 = **时间**'
assert hr.count(a2) == 1, 'A2 count = %d' % hr.count(a2)
hr = hr.replace(
    a2,
    '      const tR3: number = Date.now();\n'
    '      let yThis: number = 0;\n' +
    a2, 1)

# ============================================================
# ③ 让帧块内记录本次让帧耗时
# ============================================================
a3 = '        this.diagYieldAccMs += yDt;'
assert hr.count(a3) == 1, 'A3 count = %d' % hr.count(a3)
hr = hr.replace(a3, a3 + '\n        yThis = yDt;', 1)

# ============================================================
# ④ 循环体末尾：本块各段耗时汇总
# ============================================================
a4 = '      if (!mp.ok) {\n        break; // 解析已判定坏包，不必继续收\n      }'
assert hr.count(a4) == 1, 'A4 count = %d' % hr.count(a4)
hr = hr.replace(
    a4,
    '      // ★★ 5.1.36-diag2：本块各段耗时。崩溃时看**最后一行**即可定位：\n'
    '      //   rd= 读（readSome）  fd= 解析+落盘（mp.feed，含 writeSync）\n'
    '      //   pg= 进度上报→emit→UI     yl= 让帧\n'
    '      // ⚠️ 日志量：每块 2 行（645MB / 1MiB ≈ 645 块 ⇒ ~1290 行），可接受。\n'
    '      Log.i(TAG, `[B] #${chunks} sz=${chunk.length} rd=${tR1 - tR0} '
    'fd=${tR2 - tR1} pg=${tR3 - tR2} yl=${yThis}`);\n\n' +
    a4, 1)

# ============================================================
# ⑤ FileSink.append：writeSync 计时 + 慢写告警
# ============================================================
a5 = '      const n: number = fileIo.writeSync(this.fd, buf);'
assert fs.count(a5) == 1, 'A5 count = %d' % fs.count(a5)
fs = fs.replace(
    a5,
    '      // ★★ 5.1.36-diag2：单次 writeSync 计时。\n'
    '      //   目的：把「mp.feed 慢」进一步拆成「解析慢」还是「落盘慢」。\n'
    '      const tW0: number = Date.now();\n'
    '      const n: number = fileIo.writeSync(this.fd, buf);\n'
    '      const dtW: number = Date.now() - tW0;\n'
    '      if (dtW > FileSink.SLOW_WRITE_MS) {\n'
    '        Log.w(TAG, `[SLOW-IO] 单次 writeSync ${dtW}ms size=${data.byteLength}`);\n'
    '      }', 1)

# 静态阈值常量：挂在 class FileSink 起始处
a6 = 'class FileSink {'
assert fs.count(a6) == 1, 'A6 count = %d' % fs.count(a6)
fs = fs.replace(
    a6,
    'class FileSink {\n'
    '  /** ★ 5.1.36-diag2：单次 writeSync 超过这个毫秒数就告警（默认 100ms） */\n'
    '  private static readonly SLOW_WRITE_MS: number = 100;\n', 1)

# ============================================================
# ⑥ 版本号
# ============================================================
assert '"versionCode": 5000135' in app, 'versionCode anchor'
assert '"versionName": "5.1.35"' in app, 'versionName anchor'
app = app.replace('"versionCode": 5000135', '"versionCode": 5000136', 1)
app = app.replace('"versionName": "5.1.35"', '"versionName": "5.1.36-diag"', 1)

# ============================================================
# 统一落盘
# ============================================================
for p, s in ((HR, hr), (FS, fs), (APP, app)):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

# 复核
hr2 = io.open(HR, encoding='utf-8', newline='').read()
fs2 = io.open(FS, encoding='utf-8', newline='').read()
print('[B 进入标记     :', hr2.count('`[B${chunks}`'))
print('[B] 汇总行      :', hr2.count('`[B] #${chunks}'))
print('tR3             :', hr2.count('const tR3: number'))
print('yThis           :', hr2.count('yThis'))
print('SLOW_WRITE_MS   :', fs2.count('SLOW_WRITE_MS'))
print('[SLOW-IO]       :', fs2.count('[SLOW-IO]'))
print('[UP] 保留       :', hr2.count('[UP] blk#'))
print('[FPS] 保留      :', hr2.count('[FPS] '))
print('CRLF            :', hr2.count('\r\n') + fs2.count('\r\n'))
print('OK 5.1.36-diag2 applied')
