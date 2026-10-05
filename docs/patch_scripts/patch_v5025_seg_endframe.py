# -*- coding: utf-8 -*-
"""
5.0.25 —— 修复「本机 16 片全绿、对端 1.35 却报接收失败」

根因（dex 取证 + 本机源码交叉验证，实锤）：
  接收端判定「一片结束」靠的是 **片级 FS_END 结束帧**，不是「累计收满 len 字节」：
    · 本机 receiveSegment 片内循环第一步就是 `if (cmd === LCmd.FS_END) break;`
      —— 当初就是照 1.35 的 Lo2/n 逐条对齐写出来的；
    · 1.35 侧同理：收满数据后还要再读一帧，读到 FS_END 才退出循环，
      然后才 z() 写 5、B() 写 2/3（片级终态）。
  而本机发送侧 sendOneSegment 在发完最后一个数据块后**直接进应答循环**，
  从没补发这一帧 → 对端永远停在 read() 上等片尾 → 既不回 5 也不回 2
  → 16 片全部「块已确认、终态不来」→ 5.0.24 兼容判定把它们判成成功并 close
  → 对端 read 异常/EOF → **对端报接收失败**（本机日志却全绿）。

改三处：
  1. sendOneSegment：数据块发完后补发一帧片级 FS_END（对齐 sendPlain 433-436）
  2. receiveSegment：若因「收满 len」退出循环（没读到 FS_END），循环外补消费那一帧
     —— 否则残留字节会让 close 时内核发 RST，正是注释里记录的那个坑（同 5.0.20）
  3. app.json5：版本号 5.0.24 → 5.0.25

铁律：哨兵幂等 + 全量校验 + 最后统一落盘。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V5 = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'V5Transfer.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '片级结束帧（5.0.25 定案）'
SENT_SAW = 'let sawEnd: boolean = false;'

_doc = {}
_orig = {}


def load(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        s = f.read()
    # 规范化 CRLF -> LF，落盘时按原行尾还原
    crlf = '\r\n' in s
    s = s.replace('\r\n', '\n')
    return s, crlf


def edit(p, old, new, expect=None, count=1):
    """只改内存，不落盘。"""
    s = _doc[p]
    if expect is not None and expect not in old:
        raise AssertionError('expect 关键字不在 old 内: %r' % expect)
    if s.count(old) != count:
        raise AssertionError('锚点命中 %d 次（期望 %d）: %r' % (s.count(old), count, old[:80]))
    _doc[p] = s.replace(old, new, count)


# ---------- 加载 ----------
for p in (V5, APP):
    if not os.path.isfile(p):
        print('MISSING FILE: %s' % p)
        sys.exit(1)
    _doc[p], _crlf = load(p)
    _orig[p] = _doc[p]
    _doc[p + '__crlf'] = _crlf

if SENTINEL in _doc[V5] or SENT_SAW in _doc[V5]:
    print('ALREADY APPLIED')
    sys.exit(0)

# =========================================================
# 改动 1：sendOneSegment 数据发完后补发片级 FS_END
# =========================================================
OLD_SEND = (
    "          if (sent !== len) {\n"
    "            Log.w(TAG, `v5 分片[${idx + 1}/${total}] 只发出 ${sent}/${len}`);\n"
    "            return false;\n"
    "          }\n"
    "        } finally {\n"
    "          src.close();\n"
    "        }\n"
    "      }\n"
    "\n"
    "      // ---- 应答：**必须一直读到终态码为止** ----"
)

NEW_SEND = (
    "          if (sent !== len) {\n"
    "            Log.w(TAG, `v5 分片[${idx + 1}/${total}] 只发出 ${sent}/${len}`);\n"
    "            return false;\n"
    "          }\n"
    "        } finally {\n"
    "          src.close();\n"
    "        }\n"
    "      }\n"
    "\n"
    "      // ---- 片级结束帧（5.0.25 定案）----\n"
    "      //\n"
    "      // ⚠️⚠️ **这一帧此前一直没发，是「本机 16 片全绿、对端 1.35 却报接收失败」的根因。**\n"
    "      //\n"
    "      // 接收端判定「这一片结束」靠的是 **FS_END 结束帧**，不是「累计收满 len 字节」：\n"
    "      //   · 本机 `receiveSegment` 的片内循环第一步就是 `if (cmd === LCmd.FS_END) break;`\n"
    "      //     —— 当初就是照 1.35 的 `Lo2/n` 逐条对齐写出来的；\n"
    "      //   · 1.35 侧同理：收满数据后还要再读一帧，读到 FS_END 才退出循环，\n"
    "      //     然后才 `z()` 写 5、`B()` 写 2/3（片级终态）。\n"
    "      //\n"
    "      // 而本机发送侧（5.0.24 及更早）在发完最后一个数据块后**直接进应答循环**，\n"
    "      // 从没补发这一帧 → 对端永远停在 read() 上等片尾 → 既不回 5 也不回 2\n"
    "      // → 16 片全部「块已确认、终态不来」→ 5.0.24 兼容判定把它们判成成功并 close\n"
    "      // → 对端 read 异常/EOF → **对端报接收失败**（本机日志却全绿）。\n"
    "      //\n"
    "      // 与 1101 单连接通道对齐：`sendPlain` 每个文件发完都补这一帧（sendBody 之后）。\n"
    "      const segEndFrame: V5Enc = new V5Enc(64);\n"
    "      segEndFrame.setStreamCmd(LCmd.FS_END);\n"
    "      await chan.send(segEndFrame.bytes());\n"
    "\n"
    "      // ---- 应答：**必须一直读到终态码为止** ----"
)

edit(V5, OLD_SEND, NEW_SEND, expect='只发出')

# =========================================================
# 改动 2a：receiveSegment 增加 sawEnd 标志
# =========================================================
OLD_WHILE = "      while (got < len) {\n"
NEW_WHILE = (
    "      // 是否读到过「片级 FS_END」——用于区分「收满 len 退出」与「收到片尾帧退出」。\n"
    "      // 前者时，对端补发的那一帧还留在流里，循环外必须消费掉（见下方）。\n"
    "      let sawEnd: boolean = false;\n"
    "      while (got < len) {\n"
)
edit(V5, OLD_WHILE, NEW_WHILE, expect='while (got < len)')

# =========================================================
# 改动 2b：FS_END 分支置位 sawEnd
# =========================================================
OLD_END = (
    "        if (cmd === LCmd.FS_END) {\n"
    "          break; // 发送端声明本片结束\n"
    "        }\n"
)
NEW_END = (
    "        if (cmd === LCmd.FS_END) {\n"
    "          sawEnd = true;\n"
    "          break; // 发送端声明本片结束\n"
    "        }\n"
)
edit(V5, OLD_END, NEW_END, expect='发送端声明本片结束')

# =========================================================
# 改动 2c：循环外补消费片尾 FS_END（收满 len 退出的情形）
# =========================================================
OLD_TAIL = (
    "        if (Date.now() - lastYieldAt >= UI_YIELD_BUDGET) {\n"
    "          lastYieldAt = Date.now();\n"
    "          await V5Transfer.yieldFrame();\n"
    "        }\n"
    "      }\n"
    "    } catch (e) {\n"
    "      const err: Error = e as Error;\n"
    "      Log.e(TAG, `v5 分片接收异常: ${err.message}`);\n"
    "      ok = false;\n"
    "    }\n"
)

NEW_TAIL = (
    "        if (Date.now() - lastYieldAt >= UI_YIELD_BUDGET) {\n"
    "          lastYieldAt = Date.now();\n"
    "          await V5Transfer.yieldFrame();\n"
    "        }\n"
    "      }\n"
    "\n"
    "      // ---- 片尾 FS_END 的消费（5.0.25，与 5.0.20「文件结束帧」同构的坑）----\n"
    "      //\n"
    "      // 发送端（5.0.25 起，对齐 1.35）在每片数据后补发一帧 12 字节 FS_END。\n"
    "      // 若本片是**收满 len** 退出的循环（没读到 FS_END），那一帧还留在接收缓冲里。\n"
    "      // 不消费掉就 close：内核发现接收缓冲非空 → 发 **RST 而不是 FIN**\n"
    "      // → 对端 ECONNRESET → 它那片判失败。\n"
    "      // 这正是注释里记过的「只 readExactly(1) 拿走第 1 个字节就 close」的同一类事故。\n"
    "      //\n"
    "      // 兼容旧对端：它不发片尾帧时这里读不到（超时），照旧按字节数判成功，不影响。\n"
    "      if (ok && !sawEnd && got === len) {\n"
    "        try {\n"
    "          const tail: Uint8Array | null = await chan.readExactly(12, 5000);\n"
    "          if (tail !== null) {\n"
    "            const tcmd: number = tail[0] & 0xFF;\n"
    "            if (tcmd !== LCmd.FS_END) {\n"
    "              Log.w(TAG, `v5 分片片尾帧异常 cmd=${tcmd}（期望 FS_END=2）`);\n"
    "            }\n"
    "          }\n"
    "        } catch (e) {\n"
    "          // 对端没补发片尾帧（旧实现）：超时/断开都忽略，交给下面的字节数校验\n"
    "        }\n"
    "      }\n"
    "    } catch (e) {\n"
    "      const err: Error = e as Error;\n"
    "      Log.e(TAG, `v5 分片接收异常: ${err.message}`);\n"
    "      ok = false;\n"
    "    }\n"
)

edit(V5, OLD_TAIL, NEW_TAIL, expect='v5 分片接收异常')

# =========================================================
# 改动 3：版本号 5.0.24 -> 5.0.25
# =========================================================
edit(APP, '"versionCode": 5000024', '"versionCode": 5000025', expect='versionCode')
edit(APP, '"versionName": "5.0.24"', '"versionName": "5.0.25"', expect='versionName')

# =========================================================
# 落盘前全量校验
# =========================================================
v5_new = _doc[V5]
app_new = _doc[APP]

assert SENTINEL in v5_new, '落盘前：片级结束帧缺失'
assert v5_new.count(SENT_SAW) == 1, '落盘前：sawEnd 声明异常'
assert v5_new.count('sawEnd = true;') == 1, '落盘前：sawEnd 置位异常'
assert v5_new.count('segEndFrame.setStreamCmd(LCmd.FS_END);') == 1, '落盘前：发送侧结束帧异常'
assert v5_new.count('v5 分片片尾帧异常') == 1, '落盘前：接收侧消费异常'
assert '"versionName": "5.0.25"' in app_new, '落盘前：版本号缺失'
assert '"versionCode": 5000025' in app_new, '落盘前：versionCode 缺失'

# 括号增量一致（防止语法块被写坏）
for p in (V5, APP):
    o = _orig[p].replace('__crlf', '')
    if p.endswith('__crlf'):
        continue
for p in (V5, APP):
    a = _orig[p].count('{') - _orig[p].count('}')
    b = _doc[p].count('{') - _doc[p].count('}')
    assert a == b, '括号增量不一致: %s (%d -> %d)' % (os.path.basename(p), a, b)

# ---------- 统一落盘 ----------
for p in (V5, APP):
    if _doc[p] == _orig[p]:
        print('SKIP (no change): %s' % os.path.basename(p))
        continue
    s = _doc[p]
    if _doc[p + '__crlf']:
        s = s.replace('\n', '\r\n')
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)
    print('WROTE: %s' % os.path.basename(p))

print('PATCH 5.0.25 OK')
