# -*- coding: utf-8 -*-
"""
5.0.20 补丁 —— 两条独立改动一次落盘
============================================================================

改动 ①  修 `V5Transfer.recvBody()` 不吃对端 **FS_END 结束帧** 的缺陷
        （症状：PC 一次发 ≥2 个文件，第 2 个起必失败）

   字节级取证（三端一致）：
     · PC 发送端 `baseSend`：数据块发完后
         0x1400223ad: cmpq 80(%rax),%r14 ; je 0x1400224c0   (已发满)
         0x1400224c0: movl $2,%edx ; callq DataEnc::setByteCmd   -> FS_END
         0x1400223c0: ... getData()/getDataLen() -> TCPClient::send(data,len,0)
       （未发满则 0x1400223b3: movl $3 -> FS_CLOSE）
     · PC 接收端 `baseRecv`：**靠这一帧判文件结束**
         0x140022dd1: cmpb $1,%al ; jne 0x140022f48        (非数据帧)
         0x140022f48: cmpb $2,%al ; je 0x140022f10         (FS_END -> 退出循环)
       且退出路径**不回任何 ack**。
     · 1.35 发送端 `LANService.D`（docs/forensics/dump_D.txt 320-343）：
         v0 = new byte[24]; setInt(v0,-1,0)                (头[0..3] 预置 0xFF)
         setInt(v0, 0, 4)                                  (arg = 0)
         v0[0] = (thatSend == declared) ? 2 : 3            (FS_END / FS_CLOSE)
         setInt(v0, 0, 8); write(v0, 0, 12); flush()       (len = 0，写 12 字节)
     · 我方发送端 `sendPlain` 本来就补发这一帧（`endFrame.setStreamCmd(LCmd.FS_END)`）。

   而 `recvBody` 的循环条件是 `while (subTotal < item.length)` —— **字节数一收满就跳出**，
   根本不去读那一帧。于是它留在 TCP 缓冲区，被**下一个文件的 recvBody** 当帧头读走
   → `head[0] == FS_END` → `break` → `subTotal(0) != item.length` → 返回 false
   → `receive()` 回 `FS_BREAK(6)` → 整体失败。

   真机复现（5.0.19，tests/live-probe/v5_multifile_probe.mjs，2 文件 × 2 块）：
       v5 已保存 .../v5_multi_f1.bin (4194280 B, 2 片, 259ms)
       v5 接收字节数不符: 0 != 4194280（.../v5_multi_f2.bin）

改动 ②  包名 / 应用名去掉 V5（HAP 文件名里的版本号保留）
     · bundleName  com.fgsqw.lansharev5 -> com.fgsqw.lanshare
     · app_name / EntryAbility_label  LANShareV5 -> LANShare
     · push.cmd    目标文件名 LANShareV5-<ver>.hap -> LANShare-<ver>.hap
     · 源码注释里的 "本机 LANShareV5" -> "本机 LANShare"

   ⚠️ 换 bundleName 后手机上是**另一个应用**：旧 `com.fgsqw.lansharev5` 不会被覆盖，
      应用数据（聊天记录等）不会迁移，两个应用会**争抢同一个 TCP 端口 5856**，
      因此必须卸载旧的、不要同时运行。

改完版本号：versionCode 5000019 -> 5000020，versionName 5.0.19 -> 5.0.20。

----------------------------------------------------------------------------
落盘纪律（本工程铁律）
    read -> 全部在内存里校验并构造 -> **最后一步才统一 write**。
    任何一条断言失败 => 一个字都不写。每个文件都有独立的「已应用」判据，
    因此本脚本可以整体重跑（全部已应用时干净 exit 0）。
----------------------------------------------------------------------------
"""

import io
import os
import sys

SENTINEL = '## ★ 文件结束帧（5.0.20 定案）'

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

V5T = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'V5Transfer.ets')
APPJSON = os.path.join(ROOT, 'AppScope', 'app.json5')
APPSTR = os.path.join(ROOT, 'AppScope', 'resources', 'base', 'element', 'string.json')
ENTSTR = os.path.join(ROOT, 'entry', 'src', 'main', 'resources', 'base', 'element', 'string.json')
PUSHCMD = os.path.join(ROOT, 'push.cmd')

# 源码注释里作为「应用名」出现的 LANShareV5（纯注释，不影响功能，仅为一致性）
COMMENT_FILES = [
    os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'core', 'LanConfig.ets'),
    os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets'),
    os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'LanService.ets'),
    os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'TextMessenger.ets'),
]


def read(p):
    """读为 LF 规范化的文本，并回报原文件用的行尾。"""
    with io.open(p, 'r', encoding='utf-8', newline='') as f:
        s = f.read()
    crlf = '\r\n' in s
    return s.replace('\r\n', '\n'), crlf


def write(p, s, crlf):
    if crlf:
        s = s.replace('\n', '\r\n')
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


# ---------------------------------------------------------------------------
# 内存工作区：所有编辑先落在 _doc 里，最后统一落盘
# ---------------------------------------------------------------------------
_doc = {}      # path -> [text, crlf]
_orig = {}     # path -> 原始文本（用于判断是否真的改了）
_notes = []    # 人读的改动摘要
_skipped = []  # 已应用的


def load(path):
    if path not in _doc:
        t, c = read(path)
        _doc[path] = [t, c]
        _orig[path] = t
    return _doc[path]


def edit(path, old, new, what):
    """精确替换一次。双保险：旧文本恰好一处；new 不含 old 时还要求新文本此前不存在。"""
    e = load(path)
    s = e[0]
    n_old = s.count(old)
    assert n_old == 1, '[%s] 旧文本命中 %d 次（期望 1）:\n---\n%s\n---' % (what, n_old, old[:240])
    if old not in new:
        assert s.count(new) == 0, '[%s] 新文本已存在 %d 次，疑似重复应用' % (what, s.count(new))
    e[0] = s.replace(old, new, 1)


def replace_all_in(path, old, new, what):
    e = load(path)
    n = e[0].count(old)
    if n == 0:
        _skipped.append('%s: 无 %r，跳过' % (os.path.basename(path), old))
        return 0
    e[0] = e[0].replace(old, new)
    return n


# ============================================================================
# 1) V5Transfer.ets
# ============================================================================
s0, _c = read(V5T)
if SENTINEL in s0:
    _skipped.append('V5Transfer.ets: 哨兵已存在')
else:
    # 1a) 新增常量
    edit(
        V5T,
        '/** 单帧 payload 的硬上限，超过一定是流错位了 */\nconst MAX_FRAME: number = 8 * 1024 * 1024;\n',
        '/** 单帧 payload 的硬上限，超过一定是流错位了 */\n'
        'const MAX_FRAME: number = 8 * 1024 * 1024;\n'
        '\n'
        '/**\n'
        ' * 收满一个文件后，等对端那一帧 **FS_END 结束帧** 的时限（毫秒）。\n'
        ' *\n'
        ' * 正常情况对端（PC / 1.35 / 本机 `sendPlain`）在最后一块的块级 ack 之后立刻发，\n'
        ' * 这里几乎不会真的等到超时；设成 5s 只是给「对端不发结束帧」的旧实现留一个\n'
        ' * 快速失败的窗口 —— 超时后回退到「按字节数判结束」，功能仍然正确。\n'
        ' */\n'
        'const END_FRAME_WAIT_MS: number = 5000;\n',
        'V5Transfer / 新增 END_FRAME_WAIT_MS',
    )

    # 1b) 文件头补一节
    edit(
        V5T,
        ' * ⚠️ 保留「整片/整份收满后回 5(+2)」的片级收尾不变：那是 1.35 `z()`/`B()` 的结尾语义，\n'
        ' *    多余字节对端不读即丢弃；删掉反而可能破坏与 Android 端的互通。\n'
        ' */\n',
        ' * ⚠️ 保留「整片/整份收满后回 5(+2)」的片级收尾不变：那是 1.35 `z()`/`B()` 的结尾语义，\n'
        ' *    多余字节对端不读即丢弃；删掉反而可能破坏与 Android 端的互通。\n'
        ' *\n'
        ' * ## ★ 文件结束帧（5.0.20 定案）—— 每个文件收满后必须再消费一帧 FS_END\n'
        ' *\n'
        ' * 发送端在**每个文件**的数据块之后都补发一帧 **12 字节结束帧**：\n'
        ' *   `head[0]=2 (FS_END)`、`head[4..7]=arg=0`、`head[8..11]=len=0`。\n'
        ' *   · PC `baseSend`：`cmpq 80(%rax),%r14`(已发满) → `setByteCmd(2)` → `send(data,len,0)`\n'
        ' *     （未发满走 `setByteCmd(3)` = FS_CLOSE）\n'
        ' *   · 1.35 `LANService.D`（`docs/forensics/dump_D.txt` 320-343）：\n'
        ' *     `setInt(v0,-1,0)` → `setInt(v0,0,4)` → `v0[0] = (发满 ? 2 : 3)` →\n'
        ' *     `setInt(v0,0,8)` → `write(v0,0,12)`\n'
        ' *   · 本机 `sendPlain` 同样补发（`endFrame.setStreamCmd(LCmd.FS_END)`）。\n'
        ' *\n'
        ' * 而 PC 收端 `baseRecv` **就是靠这一帧判文件结束**：\n'
        ' *   `140022dd1: cmpb $1,%al ; jne 140022f48`（非数据帧）\n'
        ' *   `140022f48: cmpb $2,%al ; je 140022f10`（FS_END → 退出循环，**不回 ack**）\n'
        ' *\n'
        ' * 旧实现 `while (subTotal < item.length)` **收满即跳出**，从不读这一帧 →\n'
        ' * 它被**下一个文件的 recvBody** 当帧头读走 → `break` → `0 != item.length` →\n'
        ' * 回 `FS_BREAK(6)` → **PC 一次发 ≥2 个文件时第 2 个起必失败**。\n'
        ' * 真机复现（5.0.19）：`v5 接收字节数不符: 0 != 4194280（v5_multi_f2.bin）`。\n'
        ' */\n',
        'V5Transfer / 文件头补「文件结束帧」小节',
    )

    # 1c) recvBody 收满后消费 FS_END 帧
    edit(
        V5T,
        '        const percent: number = Math.floor(subTotal * 100 / item.length);\n'
        '        if (percent !== lastPercent || subTotal >= item.length) {\n'
        '          lastPercent = percent;\n'
        '          onChunk(subTotal, item.length);\n'
        '        }\n'
        '      }\n'
        '    } finally {\n'
        '      sink.close();\n'
        '    }\n',
        '        const percent: number = Math.floor(subTotal * 100 / item.length);\n'
        '        if (percent !== lastPercent || subTotal >= item.length) {\n'
        '          lastPercent = percent;\n'
        '          onChunk(subTotal, item.length);\n'
        '        }\n'
        '      }\n'
        '      // ★ 文件结束帧（5.0.20）：收满后必须再消费掉对端补发的那一帧，\n'
        '      //   否则它会被**下一个文件的 recvBody** 当帧头读走 → `0 != item.length`\n'
        '      //   → 回 FS_BREAK → 多文件从第 2 个起必失败（真机复现见文件头）。\n'
        '      //   ⚠️ 必须放在循环**之外**：循环内最后一块的块级 ack 已经回过，对端才会\n'
        '      //      发这帧；顺序反过来（先等帧、后回 ack）就是双方对等死锁。\n'
        '      if (subTotal === item.length) {\n'
        '        const tail: Uint8Array | null = await chan.readExactly(12, END_FRAME_WAIT_MS);\n'
        '        if (tail !== null) {\n'
        '          const tcmd: number = tail[0] & 0xFF;\n'
        '          if (tcmd === LCmd.FS_END) {\n'
        '            const tlen: number = V5Dec.beInt(tail, 8);\n'
        '            if (tlen > 0) {\n'
        '              // 协议规定 len=0；真出现非零也要吃掉，否则残留会污染下一帧\n'
        '              Log.w(TAG, `v5 结束帧带 ${tlen} 字节负载，已丢弃`);\n'
        '              await chan.readExactly(tlen, 15000);\n'
        '            }\n'
        '          } else if (tcmd === LCmd.FS_CLOSE) {\n'
        '            // 对端在文件末尾判失败（没发满）—— 按已收字节数落地，\n'
        '            // 下面的一致性校验会兜底报错。\n'
        '            Log.w(TAG, \'对端在文件末尾回了 FS_CLOSE\');\n'
        '          } else {\n'
        '            Log.w(TAG, `v5 结束帧命令异常 cmd=${tcmd}，帧流可能已错位`);\n'
        '            return false;\n'
        '          }\n'
        '        }\n'
        '        // tail === null：对端没补发结束帧（旧版 / 已断开）→ 交给字节数校验兜底\n'
        '      }\n'
        '    } finally {\n'
        '      sink.close();\n'
        '    }\n',
        'V5Transfer / recvBody 消费 FS_END 结束帧',
    )

    e = _doc[V5T]
    b0 = _orig[V5T].count('{') - _orig[V5T].count('}')
    b1 = e[0].count('{') - e[0].count('}')
    assert b0 == b1, 'V5Transfer 花括号增量不一致: %d -> %d' % (b0, b1)
    _notes.append('V5Transfer.ets        : END_FRAME_WAIT_MS + 文件头小节 + recvBody 消费 FS_END 帧')

# ============================================================================
# 2) AppScope/app.json5 —— bundleName 去 V5 + 版本号 5.0.20
# ============================================================================
sa, _ = read(APPJSON)
if 'lansharev5' not in sa and '5000020' in sa:
    _skipped.append('AppScope/app.json5: 已应用')
else:
    edit(
        APPJSON,
        '"bundleName": "com.fgsqw.lansharev5",\n'
        '    "vendor": "fgsq-team",\n'
        '    "versionCode": 5000019,\n'
        '    "versionName": "5.0.19",\n',
        '"bundleName": "com.fgsqw.lanshare",\n'
        '    "vendor": "fgsq-team",\n'
        '    "versionCode": 5000020,\n'
        '    "versionName": "5.0.20",\n',
        'app.json5 / bundleName + versionCode/Name',
    )
    _notes.append('AppScope/app.json5     : bundleName -> com.fgsqw.lanshare ; 5.0.19 -> 5.0.20 (code 5000020)')

# ============================================================================
# 3) 应用名（AppScope + entry 两处 string.json）
# ============================================================================
ss, _ = read(APPSTR)
if 'LANShareV5' not in ss:
    _skipped.append('AppScope string.json: 已应用')
else:
    n = replace_all_in(APPSTR, '"value": "LANShareV5"', '"value": "LANShare"', 'AppScope string.json')
    assert n == 1, 'AppScope string.json 期望 1 处，实际 %d' % n
    _notes.append('AppScope/.../string.json: app_name "LANShareV5" -> "LANShare"')

se, _ = read(ENTSTR)
if 'LANShareV5' not in se:
    _skipped.append('entry string.json: 已应用')
else:
    n = replace_all_in(ENTSTR, '"value": "LANShareV5"', '"value": "LANShare"', 'entry string.json')
    assert n == 1, 'entry string.json 期望 1 处，实际 %d' % n
    _notes.append('entry/.../string.json   : EntryAbility_label "LANShareV5" -> "LANShare"')

# ============================================================================
# 4) push.cmd —— 目标文件名去掉 V5，**保留版本号占位 %VER%**
# ============================================================================
sp, _ = read(PUSHCMD)
if 'set "DEST_NAME=LANShare-%VER%.hap"' in sp:
    _skipped.append('push.cmd: 已应用')
else:
    edit(
        PUSHCMD,
        'set "DEST_NAME=LANShareV5-%VER%.hap"',
        'set "DEST_NAME=LANShare-%VER%.hap"',
        'push.cmd / DEST_NAME',
    )
    edit(
        PUSHCMD,
        'REM apart on the phone (e.g. LANShareV5-5.0.1.hap). Parsed with findstr only,',
        'REM apart on the phone (e.g. LANShare-5.0.1.hap). Parsed with findstr only,',
        'push.cmd / 注释里的示例名',
    )
    _notes.append('push.cmd              : DEST_NAME -> LANShare-%VER%.hap（版本号保留）')

# ============================================================================
# 5) 源码注释里的应用名
# ============================================================================
for p in COMMENT_FILES:
    tt, _ = read(p)
    if 'LANShareV5' not in tt:
        continue
    n = replace_all_in(p, 'LANShareV5', 'LANShare', '注释')
    if n:
        _notes.append('%-21s: 注释 LANShareV5 -> LANShare (%d 处)' % (os.path.basename(p), n))

# ============================================================================
# 6) 全量校验通过 —— 现在才统一落盘
# ============================================================================
changed = [(p, v) for p, v in _doc.items() if v[0] != _orig[p]]

if not changed:
    print('ALREADY APPLIED - 所有文件都已是目标状态，未做任何写入。')
    for x in _skipped:
        print('   skip: ' + x)
    sys.exit(0)

for p, (text, crlf) in changed:
    write(p, text, crlf)

# ============================================================================
# 7) 落盘后自检
# ============================================================================
v, _ = read(V5T)
assert SENTINEL in v, '哨兵未写入 V5Transfer.ets'
assert v.count('END_FRAME_WAIT_MS') == 2, \
    'END_FRAME_WAIT_MS 应为 2 处（定义 + 使用），实际 %d' % v.count('END_FRAME_WAIT_MS')
assert v.count('V5Transfer.sendByte(') == 8, \
    'sendByte 调用点应仍为 8，实际 %d' % v.count('V5Transfer.sendByte(')

a, _ = read(APPJSON)
assert 'com.fgsqw.lanshare"' in a and 'lansharev5' not in a, 'bundleName 未改净'
assert '5000020' in a and '5.0.20' in a, '版本号未更新'

pc, _ = read(PUSHCMD)
# ⚠️ 只检查**文件名模板**：push.cmd 第 25 行的 `PROJECT_PATH=E:\lanshare-harmony\LANShareV5`
#    是工程**目录名**，不在本次改名范围内（改目录会连带打断 build.cmd / push.cmd 自身）。
assert 'LANShareV5-%VER%' not in pc, 'push.cmd 的 DEST_NAME 仍含 LANShareV5'
assert 'set "DEST_NAME=LANShare-%VER%.hap"' in pc, 'push.cmd DEST_NAME 未改到目标值'

print('OK - 5.0.20 补丁已应用（%d 个文件落盘）：' % len(changed))
for r in _notes:
    print('   ' + r)
if _skipped:
    print('   跳过：')
    for x in _skipped:
        print('     - ' + x)
print('')
print('自检：END_FRAME_WAIT_MS x2 ✓  sendByte 调用点 8 ✓  bundleName 无 v5 ✓  version 5.0.20 ✓  push.cmd 无 V5 ✓')
