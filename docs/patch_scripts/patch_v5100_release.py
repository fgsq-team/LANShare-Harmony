# -*- coding: utf-8 -*-
"""v5.1.0 —— 发版：① 移除 5.0.68 的临时诊断日志；② 版本号升级。

【vivi 2026-10-02 20:49 的决定】
「鸿蒙版就这样了，把 app 里相关的调试模块去掉吧，版本升级到 5.1.0」
经确认范围 = **只删 5.0.68 诊断日志**，其余一律保留：
  - ✗ 不删「复制日志」按钮与 `ui_log.txt` 落盘 —— 那是真机唯一的排障通路
  - ✗ 不删文件头的开发流水注释
  - ✗ 不删「关于」页（版本号/开源仓库/QQ群/更新地址 是产品信息）

【要删的是什么】
5.0.68 为了定位「存相册后闪一下」而临时加的观测点（**已完成使命**）：
  - `diagSnapshot()` 方法本体
  - `flushStateSwap()` 里的「落地[...]」打点
  - `autoSaveAlbumBatch` 收尾的「存相册收尾-前」打点
★ 这三处是 5.0.68~5.0.77 期间**唯一**靠「运行时观测」定案的手段；
  真凶早已查明（外层气泡 key 的 `groupAlbumSig`），留着只是白占日志空间。

【版本号】5000077 -> **5000100**（5.1.0 是次版本号，约定 `5000000 + 小版本`；
  5.0.x 阶段用 50000xx，5.1.0 用 5000100）。
⚠️ 只改 `AppScope/app.json5`；`ABOUT_FALLBACK_VER`（关于页兜底版本号）
  也要同步，否则「关于」里显示的还是旧版本（5.0.29 踩过这个坑）。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if 'diagSnapshot' not in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5100pre'), (VER, 'app.json5.v5100pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：删 flushStateSwap 里的打点
# =====================================================================
OLD1 = """    // ⚠️ 只在「至少换了一项」时打，且带上分组名 —— 否则纯接收路径会刷屏
    if (swP || swG || swC || swA) {
      const what: string = `mediaPaths=${swP ? 1 : 0} mediaGroups=${swG ? 1 : 0}`
        + ` groups=${swC ? 1 : 0} albumIndex=${swA ? 1 : 0}`;
      this.diagSnapshot(`落地[${what}]`, swP);
    }
  }"""
NEW1 = """    // ★ 5.1.0：5.0.68 的临时诊断打点已移除（真凶早已查明：外层气泡 key 的
    //   `groupAlbumSig` ⇒ 整颗气泡销毁重建，见 v5.0.71 的 commit）。
    //   `swP` 现在只用于「chatMediaPaths 落地」那一步的判断，保留以免动到逻辑。
  }"""

# =====================================================================
# 改 2：删「存相册收尾-前」打点
# =====================================================================
OLD2 = """      // ★ 5.0.68（诊断）：存相册收尾是「闪」的高发时刻，打前打后各一次
      this.diagSnapshot('存相册收尾-前', false);
"""
NEW2 = ""

# =====================================================================
# 改 3：删 diagSnapshot 方法本体
# ⚠️ **不手抄整段**（5.0.63 起栽过：「手抄长串 → 与磁盘不符 → 锚点命中 0」）
#   改用**行号区间**定位：从方法注释的 `/**` 到它的收尾 `}`，整段切掉。
#   先在 dry-run 里打印该区间确认内容，再落盘。
DIAG_START_MARK = '  private diagSnapshot(tag: string, swapped: boolean): void {'
DIAG_END_MARK = "      + ` | 签名: ${sig}`);\n  }\n"
OLD3 = '@@DIAG_BLOCK@@'   # 占位：实际用行号区间实现，见下方
NEW3 = """
  // ★ 5.1.0：`diagSnapshot()`（5.0.68 的临时诊断）已随本次发版移除。
"""

# 改 4：版本号 5000077 -> 5000100，并同步「关于」页的兜底版本号
# =====================================================================
OLD4 = '"versionCode": 5000077'
NEW4 = '"versionCode": 5000100'

# ⚠️ `ABOUT_FALLBACK_VER` 一直停在 '5.0.26'（陈旧）——「关于」页取不到
#   bundleManager 版本号时就显示它。5.0.29 踩过「关于里显示空白/旧版」的坑，
#   这里一并同步到 5.1.0。
OLD4B = "const ABOUT_FALLBACK_VER: string = '5.0.26';"
NEW4B = "const ABOUT_FALLBACK_VER: string = '5.1.0';"

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 删 flushStateSwap 打点'),
                      (OLD2, NEW2, '改2 删存相册打点')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

# ---- 改 3：按**行号区间**切掉 diagSnapshot（含它的文档注释） ----
_lines = s2.split('\n')
# 从方法体往上找注释起点（连续的 /** ... */ 块），往下找收尾 }
_end = next(i2 for i2, l in enumerate(_lines) if DIAG_START_MARK in l)
_begin = _end
while _begin > 0 and not _lines[_begin - 1].strip().startswith('/**'):
    _begin -= 1
if _begin > 0:
    _begin -= 1   # 把 /** 那行也纳入
# ★★ 定位收尾：**找下一个「顶层声明」**（缩进 2 空格 + `private`/`@`/`}` 收尾），
#   而不是靠大括号配平 —— 方法体里有大量 `{`/`}`：
#   `if (...) {`、模板串 `${sig}`、对象字面量 `{ space: 3 }` ……
#   逐行数括号必然算错（实测 _open 停在 1）。**缩进 + 声明形态**才是可靠信号。
#   收尾行 = 紧接其后的、缩进恰好 2 空格且以 `}` 开头的那一行（方法自己的大括号）。
import re as _re
_end = next(i2 for i2, l in enumerate(_lines) if DIAG_START_MARK in l)
# 往上并入文档注释（连续的 /** … */ 块）
_begin = _end
while _begin > 0 and not _lines[_begin - 1].strip().startswith('/**'):
    _begin -= 1
if _begin > 0:
    _begin -= 1
# 往下找方法自己的收尾：第一个「恰好两个空格缩进 + 以 } 开头」的行
_close = next(
    i2 for i2 in range(_end + 1, len(_lines))
    if _re.match(r'^  \}', _lines[i2])
)
# 区间自检：首行是 /** 或方法签名，末行是收尾 }
assert _lines[_close].strip() == '}', '收尾行不是纯 }：%r' % _lines[_close]
assert 'diagSnapshot' in _lines[_end], '区间起点不对'
# 连带清掉它后面紧跟的空行
_cut_to = _close + 1
if _cut_to < len(_lines) and _lines[_cut_to].strip() == '':
    _cut_to += 1
print('  diagSnapshot 区间: 行 %d..%d' % (_begin + 1, _cut_to))
print('  将删首行: %r' % _lines[_begin][:60])
print('  将删末行: %r' % _lines[_cut_to - 1][:60])
_lines[_begin:_cut_to] = NEW3.split('\n')
s2 = '\n'.join(_lines)

assert s2.count(OLD4B) == 1, 'ABOUT_FALLBACK_VER 锚点异常'
s2 = s2.replace(OLD4B, NEW4B, 1)

v2 = s_ver
assert v2.count(OLD4) == 1, 'versionCode 锚点异常'
v2 = v2.replace(OLD4, NEW4, 1)
assert v2.count('"versionName": "5.0.77"') == 1
v2 = v2.replace('"versionName": "5.0.77"', '"versionName": "5.1.0"', 1)

# ---- 不变量 ----
# 诊断代码必须彻底消失（注释里提及「diagSnapshot」是允许的，只查代码行）
_code = '\n'.join(l for l in s2.split('\n')
                  if not l.strip().startswith('//')
                  and not l.strip().startswith('*')
                  and not l.strip().startswith('/*'))
assert 'diagSnapshot' not in _code, '仍有 diagSnapshot 调用/定义'
assert 'private diagSnapshot' not in s2
assert '5.0.68诊断' not in s2, '诊断日志标记仍在'
# 保留项：日志系统、关于页、流水注释
assert '复制日志' in s2, '「复制日志」被误删'
assert 'ui_log.txt' in s2 or 'logAuto' in s2, '日志落盘被误删'
assert 'aboutDialog' in s2 or 'showAbout' in s2, '关于页被误删'
assert "const ABOUT_FALLBACK_VER: string = '5.1.0';" in s2, '关于页兜底版本号未同步'
# 关键功能仍在
assert 'probeAlbumOnEnterChat' in s2
assert 'groupGoneSig' in s2
assert 'padHint' in s2
assert len(s2) < len(s_idx), '应该变短（删了诊断代码）'

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d (-%d)  |  5000100 / 5.1.0' % (
    len(s_idx), len(s2), len(s_idx) - len(s2)))
