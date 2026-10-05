# -*- coding: utf-8 -*-
"""
5.0.24（第二版，修正第一版措辞与判定）：1110 分片「对端未回片级终态」的兜底判定。

vivi 实测反馈（推翻了「放宽等待」的设想）：
  · 手机热点**不比局域网慢**，甚至更快 → 不是超时问题，**不要**放宽等待时间；
  · 中午 11:57~14:00 给同一台车机 1.35 发大文件**立即完成、没有等待** → 说明对端**会**回片级终态 2，
    只是 18:43 这次没回。所以注释不能再武断写「1.35 只回块级 5、不回片级终态」。

真正要修的点（保留 1110 发送）：
  16 片数据在 ~18s 内发完，每片收到 **41 个**块级 FS_NEXT(5)
  （一片 42343850 B / CHUNK 1048564 = 正好 41 块 → 每个数据块都被对端确认收到），
  却一片都没等到终态 2 → 16 片全判失败 → 回退 1101 把 677MB **再传一遍**
  （进度条到 100% 后卡住、然后从头重发）。
  数据其实已被完整送达（TCP 有序送达 + 每块都 ack），缺的只是那 1 字节片级收尾。

判定：收齐本片所有块 ack 后，只再等 SEG_TERM_GRACE_MS(1.5s) 等终态 2
  （正常对端毫秒级就回，1.5s 有充足余量，不影响「立即完成」的原有行为）；
  窗口内仍无终态、但块已全部 ack **且连接未断** → 判定成功，不再回退 1101 重传。

幂等：哨兵「连接未断（兼容模式）」；先全量校验、内存构造，最后统一落盘。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V5 = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'V5Transfer.ets')

SENTINEL = '连接未断（兼容模式）'


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


v5, v5_crlf = read(V5)

if SENTINEL in v5:
    print('ALREADY APPLIED')
    sys.exit(0)

# ---------------- 1. 常量注释修正 ----------------
OLD_CONST = """  /**
   * 收齐本片所有数据块的流控 ack 后，再等「片级终态 2」的宽限窗口（毫秒）。
   * 5.0.24：部分对端（车机版 1.35）只回块级 5、不回片级 2，
   * 窗口过后若块已全部 ack 就判定成功，不再死等 30s 也不再回退 1101 重传。
   */
  static readonly SEG_TERM_GRACE_MS: number = 1500;
"""
NEW_CONST = """  /**
   * 收齐本片所有数据块的流控 ack 后，再等「片级终态 2」的宽限窗口（毫秒）。
   * 5.0.24：对端若在收齐块 ack 后仍不回片级终态（车机 1.35 实测出现过），
   * 窗口过后即按「数据已完整送达」判定成功，不再回退 1101 把大文件重传一遍。
   * ⚠️ 不放宽总等待（vivi 实测：热点并不慢，且正常时是对端**立即**回 2），
   *    正常对端毫秒级就回，1.5s 有充足余量，原有「立即完成」行为完全不变。
   */
  static readonly SEG_TERM_GRACE_MS: number = 1500;
"""
assert v5.count(OLD_CONST) == 1, '常量区锚点未命中'
v5 = v5.replace(OLD_CONST, NEW_CONST)

# ---------------- 2. 应答等待注释 + 判定 ----------------
OLD_ACK = """      // ---- 5.0.24 兼容：部分对端（车机版 1.35）**只回块级流控 5、不回片级终态 2** ----
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

NEW_ACK = """      // ---- 5.0.24：对端未回片级终态时的兜底判定（避免整份大文件被重传一遍）----
      //
      // 真机实证（2026-10-01 18:43，手机热点直连车机 1.35）：
      //   16 片数据在 ~18s 内发完，每片都收到 **41 个**块级 FS_NEXT(5)
      //   —— 一片 42343850 B / CHUNK(1048564) 正好 41 块，
      //     说明对端**每个数据块都确认收到**了，却始终没有一片等到终态 2
      //   → 16 片全判失败 → 回退 1101 把 677MB **再传一遍**
      //     （表现为：进度条到 100% 后卡住，然后从头重发）。
      //
      // ⚠️ vivi 实测澄清（决定了修法方向）：
      //   · 热点**并不比局域网慢** → 不是超时问题，**不要**放宽等待；
      //   · 中午 11:57~14:00 给同一台车机发大文件是**立即完成、没有等待**的
      //     → 对端**会**回片级终态 2，不能武断认定「1.35 不回终态」。
      //   所以这里只改「判定」，不动等待时长：正常对端依旧毫秒级拿到 resp=2。
      //
      // 修法（保留 1110 发送，仅调整判定）：
      //   ① 先把本片所有数据块的 ack 收齐（hopCount >= 本片块数 blocks）；
      //   ② 收齐后只再等 SEG_TERM_GRACE_MS 短窗口等终态 2（正常对端立刻回）；
      //   ③ 窗口内仍无终态、但块已全部 ack **且连接未断** → 判定**成功**，不再回退重传。
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
            break;   // 宽限窗口已过：对端这次未回片级终态
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
        // 没等到终态码：若本片所有数据块都已被对端 ack **且连接未断开**，
        // 说明数据已完整送达（TCP 保证有序），只是对端这次没回那 1 字节片级收尾 → 判成功。
        // （连接若已断，说明对端真的出问题了，照旧回退 1101 重传，不冒险。）
        if (len > 0 && blocks > 0 && hopCount >= blocks && !chan.isClosed) {
          Log.i(TAG, `v5 分片[${idx + 1}/${total}] 完成 segId=${segId} start=${start} len=${len} `
            + `对端未回片级终态，但 ${hopCount}/${blocks} 块已全部确认且连接未断（兼容模式）`);
          return true;
        }
        Log.w(TAG, `v5 分片[${idx + 1}/${total}] 未收到终态应答`
          + `（已跳过 ${hopCount} 个流控字节，本片共 ${blocks} 块，连接${chan.isClosed ? '已断' : '未断'}）`);
        return false;
      }
"""
assert v5.count(OLD_ACK) == 1, '应答等待锚点未命中'
v5 = v5.replace(OLD_ACK, NEW_ACK)

# ---------------- 3. 落盘前终检 ----------------
assert v5.count(SENTINEL) == 1, '落盘前兼容模式判据缺失'
assert v5.count('!chan.isClosed') == 1, '连接未断判据缺失'
assert v5.count('const blocks: number = len > 0 ? Math.ceil(len / CHUNK) : 0;') == 1, 'blocks 计算缺失'
assert v5.count('const deadline: number = Date.now() + 30000;') == 1, '等待时长不应被放宽'
assert v5.count('static readonly SEG_TERM_GRACE_MS: number = 1500;') == 1, '常量缺失'

# ---------------- 4. 统一落盘 ----------------
write(V5, v5, v5_crlf)

print('PATCH OK 5.0.24 (1110 片级终态兜底判定 · 第二版)')
print('  - 注释修正：不再武断写「1.35 不回终态」')
print('  - 判定加 !chan.isClosed 保险（对端真断开仍回退 1101）')
print('  - 等待时长保持 30s 上限，未放宽')
