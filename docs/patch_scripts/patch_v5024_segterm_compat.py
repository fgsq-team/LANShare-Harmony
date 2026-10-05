# -*- coding: utf-8 -*-
"""
5.0.24：修复 1110 分片发送「对端只回块级流控 5、不回片级终态 2」导致整片误判失败。

根因（真机实证）：
  一片 42343850 B / CHUNK(1048564) = 41 块，车机版 1.35 对每块回一个 FS_NEXT(5)，
  日志稳定出现「已跳过 41 个流控字节」，但**始终不回片级终态 RECV_OK(2)**。
  发送端原本「等不到 2 就判失败」→ 16 片全失败 → 回退 1101 把整份大文件再传一遍
  （677MB 传两遍，表现为进度条到 100% 后卡住、然后从头重发）。

修法（不关闭 1110）：
  先等「本片所有数据块都被 ack」(hopCount >= 本片块数 blocks)，
  收齐后再给一个 SEG_TERM_GRACE_MS 短窗口等终态 2；
  窗口内仍无终态、但块已全部 ack → 判定成功（数据已被 TCP 完整送达）。
  对本端(鸿蒙<->鸿蒙)行为不变：收齐后窗口内必读到片尾 5+2 → resp=2 正常成功。

幂等：哨兵 SEG_TERM_GRACE_MS；先全量校验、内存构造，最后统一落盘。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V5 = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'V5Transfer.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = 'SEG_TERM_GRACE_MS'


def read(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        s = f.read()
    crlf = '\r\n' in s
    return s.replace('\r\n', '\n'), crlf


def write(p, s, crlf):
    if crlf:
        s = s.replace('\n', '\r\n')
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


# ---------------- 1. V5Transfer.ets ----------------
v5, v5_crlf = read(V5)

if SENTINEL in v5:
    print('ALREADY APPLIED (V5Transfer)')
    sys.exit(0)

# --- 1a. 常量区：SEG_MIN_SIZE 之后插入 SEG_TERM_GRACE_MS ---
OLD_CONST = """  /** 走 1110 的最小文件大小 = 128MB（1.35 的 `0x8000000`，见 `send()` 注释） */
  static readonly SEG_MIN_SIZE: number = 134217728;
"""
NEW_CONST = """  /** 走 1110 的最小文件大小 = 128MB（1.35 的 `0x8000000`，见 `send()` 注释） */
  static readonly SEG_MIN_SIZE: number = 134217728;
  /**
   * 收齐本片所有数据块的流控 ack 后，再等「片级终态 2」的宽限窗口（毫秒）。
   * 5.0.24：部分对端（车机版 1.35）只回块级 5、不回片级 2，
   * 窗口过后若块已全部 ack 就判定成功，不再死等 30s 也不再回退 1101 重传。
   */
  static readonly SEG_TERM_GRACE_MS: number = 1500;
"""
assert v5.count(OLD_CONST) == 1, '常量区锚点未命中'
v5 = v5.replace(OLD_CONST, NEW_CONST)

# --- 1b. sendOneSegment 应答等待 + 判定 ---
OLD_ACK = """      let status: number = -1;
      let hopCount: number = 0;
      const deadline: number = Date.now() + 30000;
      while (Date.now() < deadline) {
        const one: Uint8Array | null =
          await chan.readExactly(1, Math.max(500, deadline - Date.now()));
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
        Log.w(TAG, `v5 分片[${idx + 1}/${total}] 30s 内未收到终态应答（已跳过 ${hopCount} 个流控字节）`);
        return false;
      }
"""

NEW_ACK = """      // ---- 5.0.24 兼容：部分对端（车机版 1.35）**只回块级流控 5、不回片级终态 2** ----
      //   实证：一片 41 块，日志稳定出现「已跳过 41 个流控字节」，却永远等不到终态 2，
      //   于是 16 片全判失败 → 回退 1101 把整份大文件**再传一遍**（677MB 传两遍，
      //   表现为进度条到 100% 后卡住、然后从头重发）。
      //   但每块都收到了 5，说明对端已完整收下这片数据（TCP 保证有序送达），
      //   缺的只是那 1 字节「片级收尾」的形式确认。
      //   修法：先等「本片所有数据块都被 ack」（hopCount >= 本片块数 blocks），
      //        收齐后再给一个 SEG_TERM_GRACE_MS 短窗口等终态 2；
      //        窗口内仍无终态、但块已全部 ack → 判定**成功**（不再回退重传）。
      //   对本端（鸿蒙<->鸿蒙）行为不变：收齐后窗口内必读到片尾 5+2 → resp=2 正常成功。
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
            break;   // 宽限窗口已过：对端不回片级终态
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
        // 没等到终态码：若本片所有数据块都已被对端 ack，视为成功
        // （对端只是不回片级终态，数据其实已完整收下 —— TCP 已保证有序送达）
        if (len > 0 && blocks > 0 && hopCount >= blocks) {
          Log.i(TAG, `v5 分片[${idx + 1}/${total}] 完成 segId=${segId} start=${start} len=${len} `
            + `对端未回片级终态，但 ${hopCount}/${blocks} 块已全部确认（兼容模式）`);
          return true;
        }
        Log.w(TAG, `v5 分片[${idx + 1}/${total}] 30s 内未收到终态应答`
          + `（已跳过 ${hopCount} 个流控字节，本片共 ${blocks} 块）`);
        return false;
      }
"""
assert v5.count(OLD_ACK) == 1, '应答等待锚点未命中'
v5 = v5.replace(OLD_ACK, NEW_ACK)

# ---------------- 2. app.json5 版本号 ----------------
app, app_crlf = read(APP)
assert app.count('"versionCode": 5000023') == 1, 'versionCode 锚点未命中'
assert app.count('"versionName": "5.0.23"') == 1, 'versionName 锚点未命中'
app = app.replace('"versionCode": 5000023', '"versionCode": 5000024')
app = app.replace('"versionName": "5.0.23"', '"versionName": "5.0.24"')

# ---------------- 3. 落盘前终检 ----------------
assert v5.count(SENTINEL) >= 1, '落盘前 SEG_TERM_GRACE_MS 缺失'
assert v5.count('const blocks: number = len > 0 ? Math.ceil(len / CHUNK) : 0;') == 1, 'blocks 计算缺失'
assert v5.count('graceUntil') >= 3, 'graceUntil 逻辑缺失'
assert v5.count('块已全部确认（兼容模式）') == 1, '兼容模式日志缺失'
assert app.count('"versionCode": 5000024') == 1, 'versionCode 未改'
assert app.count('"versionName": "5.0.24"') == 1, 'versionName 未改'

# ---------------- 4. 统一落盘 ----------------
write(V5, v5, v5_crlf)
write(APP, app, app_crlf)

print('PATCH OK 5.0.24 (1110 片级终态兼容)')
print('  V5Transfer.ets: +SEG_TERM_GRACE_MS, 应答判定改为「块全 ack 即成功」')
print('  app.json5: 5000023 -> 5000024, 5.0.23 -> 5.0.24')
