# -*- coding: utf-8 -*-
"""
5.1.49
  A. 浮层标题行加回「接收」二字（vivi 要求在文件名前加"接收"）
  B. 完成态去掉文案里的 `✓ ` 前缀（只保留最前面那个大对勾图标）
  C. 去掉「传输完成」的系统 Toast（浮层已经很明显了）
  D. 修消息气泡不显示「大小 · 平均速度」—— appendFileChat 收了 meta
     却**没往 appendChat 传**，且序列化/反序列化都漏了 meta 字段
"""
import io, os, re, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
LS = os.path.join(ET, 'service', 'LanService.ets')
IX = os.path.join(ET, 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '5.1.49'
if SENTINEL in io.open(LS, encoding='utf-8', newline='').read():
    print('ALREADY APPLIED'); sys.exit(0)

ls = io.open(LS, encoding='utf-8', newline='').read()
ix = io.open(IX, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()

B = []
def rep(tag, old, new): B.append((tag, old, new))

# ═══ ① A：协议侧进度标题加回「接收 」前缀 ═══
rep('LS:progress-verb',
    """      const nm: string = r.fileName.length > 0 ? r.fileName : '文件';
      this.snapshot.transferText = nm;""",
    """      const nm: string = r.fileName.length > 0 ? r.fileName : '文件';
      // ★ 5.1.49：vivi 要求**标题行文件名前要有「接收」二字**。
      //   （5.1.45 曾把动词全移到副行、标题只留文件名，这里按要求加回来。）
      this.snapshot.transferText = `接收 ${nm}`;""")

# ═══ ② A：网页侧同样加「接收 」前缀 ═══
rep('LS:web-verb',
    """    this.snapshot.transferText = who.length > 0 ? who : '文件';
    this.snapshot.transferPercent = pct;""",
    """    // ★ 5.1.49：同协议侧，标题行加「接收」二字。
    this.snapshot.transferText = `接收 ${who.length > 0 ? who : '文件'}`;
    this.snapshot.transferPercent = pct;""")

# ═══ ③ B：完成态去掉文案里的 `✓ ` 前缀（保留最前面的大对勾图标）═══
rep('LS:done-no-tick',
    """    // ★★ 5.1.44：文案里**直接写死 `✓` 前缀**。
    //   5.1.43 把它去掉了（理由是「状态应由 transferDone 字段表达」）——
    //   但实测 `transferDone` 驱动的底色与图标连续两版不生效，
    //   于是完成提示**看起来和传输中完全一样**，用户毫无感知。
    //   ⇒ 文案里的 `✓` 是不依赖 ArkUI 状态追踪的**最后一道视觉兜底**：
    //     字段负责颜色/图标，字符负责「一定看得到完成」。
    this.snapshot.transferText = `✓ ${label.length > 0 ? label : '文件'}`;""",
    """    // ★★ 5.1.49：去掉文案里的 `✓ ` 前缀。
    //   5.1.44 把它当「不依赖状态追踪的最后兜底」写进去，但真凶是
    //   `onTransferReport` 里 if/else 外的无条件清理（5.1.48 已修）——
    //   **字段早就可靠了，字符兜底不再需要**，留着只会变成
    //   「标题前面一个大✓ + 文案里又一个小✓」（vivi 截图里就是这样）。
    //   ★ 完成态的视觉标识由**浮层第一行的静态 ✓ 图标**承担。
    this.snapshot.transferText = label.length > 0 ? label : '文件';""")

# ═══ ④ D-1：appendFileChat 三处 appendChat 调用补传 meta ═══
rep('LS:chatFile-media',
    """        this.appendChat(true, peerName, peerIp, names[i], source, 'file', names[i], bid);""",
    """        // ★ 5.1.49：补传 meta —— 5.1.47 加了 meta 参数却**忘了往下传**，
        //   导致气泡里 `m.meta` 恒为空 ⇒ 「大小 · 平均速度」永远不显示。
        this.appendChat(true, peerName, peerIp, names[i], source, 'file', names[i], bid, meta);""")

rep('LS:chatFile-multi',
    """        this.appendChat(incoming, peerName, peerIp, names[i], source, 'file', names[i]);
      }
      return;
    }
    this.appendChat(incoming, peerName, peerIp, label, source, 'file', names.join('\\n'));""",
    """        // ★ 5.1.49：同上，补传 meta
        this.appendChat(incoming, peerName, peerIp, names[i], source, 'file', names[i], '', meta);
      }
      return;
    }
    this.appendChat(incoming, peerName, peerIp, label, source, 'file',
      names.join('\\n'), '', meta);""")

# ═══ ⑤ D-2：序列化写 meta ═══
rep('LS:ser-meta',
    """        `"batchId":${MiniJson.quote(m.batchId)}}`);""",
    """        `"batchId":${MiniJson.quote(m.batchId)},` +
        // ★ 5.1.49：meta 也要落盘 —— 否则**重启后**历史消息的大小/速度全丢
        //   （与 5.0.55「batchId 也要落盘」是同一类失配）
        `"meta":${MiniJson.quote(m.meta)}}`);""")

# ═══ ⑥ D-3：反序列化读 meta ═══
rep('LS:deser-meta',
    """      m.batchId = LanService.chatStr(n, 'batchId');""",
    """      m.batchId = LanService.chatStr(n, 'batchId');
      // ★ 5.1.49：旧数据没有 meta 字段 → 取到空串 → 不显示（与改动前一致）
      m.meta = LanService.chatStr(n, 'meta');""")

# ═══ ⑦ C：去掉完成 Toast ═══
rep('IX:no-toast',
    """    if (s.transferDone && !this.tDoneToastShown) {
      this.tDoneToastShown = true;
      this.toast(`接收完成：${s.transferText}`, 3000);
    } else if (!s.transferDone) {
      this.tDoneToastShown = false;
    }
    this.transferring = this.service.isTransferring;""",
    """    // ★ 5.1.49：**去掉「传输完成」的系统 Toast**（vivi 要求）。
    //   浮层现在能可靠显示完成态（绿底 + 静态 ✓ + 「接收完成 · 大小 · 速度」），
    //   Toast 属于重复信息，且会挡住底部设备列表 3 秒。
    //   ⚠️ 5.1.44 加它时是当作「状态是否到位的自证旁路」；
    //     5.1.48 证明真凶是代码 bug（状态被无条件清空），旁路已无价值。
    this.transferring = this.service.isTransferring;""")

# ═══ ⑧ 版本号 ═══
rep('APP:ver',
    """    "versionCode": 5000148,
    "versionName": "5.1.48\"""",
    """    "versionCode": 5000149,
    "versionName": "5.1.49\"""")

# ═══ ⑨ ABOUT_FALLBACK_VER ═══
rep('IX:fallback',
    "const ABOUT_FALLBACK_VER: string = '5.1.48';",
    "const ABOUT_FALLBACK_VER: string = '5.1.49';")

# ═══ ⑩ 清理 tDoneToastShown 残留（声明 + 注释）═══
rep('IX:drop-flag',
    """  private tDoneToastShown: boolean = false;""",
    """  // ★ 5.1.49：tDoneToastShown 已随「完成 Toast」一起删除。""")

# ══════════════════════════════════════════════════════════════════
# 按文件累积 + 先全部校验
# ══════════════════════════════════════════════════════════════════
cur = {'LS': ls, 'IX': ix, 'APP': app}
owner = {'LS:progress-verb': 'LS', 'LS:web-verb': 'LS', 'LS:done-no-tick': 'LS',
         'LS:chatFile-media': 'LS', 'LS:chatFile-multi': 'LS',
         'LS:ser-meta': 'LS', 'LS:deser-meta': 'LS',
         'IX:no-toast': 'IX', 'IX:fallback': 'IX', 'IX:drop-flag': 'IX',
         'APP:ver': 'APP'}

for tag, old, new in B:
    n = cur[owner[tag]].count(old)
    assert n == 1, '%s count=%d (期望 1)' % (tag, n)
for tag, old, new in B:
    f = owner[tag]
    cur[f] = cur[f].replace(old, new, 1)

ls, ix, app = cur['LS'], cur['IX'], cur['APP']

# ── 残留检查（剥离注释）────────────────────────────
def code_only(s):
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)
    s = re.sub(r'//[^\n]*', '', s)
    return s
cl, ci = code_only(ls), code_only(ix)

assert 'tDoneToastShown' not in ci, 'tDoneToastShown 残留'
assert '接收完成：${s.transferText}' not in ci, '完成 Toast 残留'
# meta 必须三处齐全：appendFileChat 三处调用 + 序列化 + 反序列化
assert ls.count("names.join('\\n'), '', meta);") == 1, '单文件调用未补 meta'
assert ls.count("names[i], bid, meta);") == 1, '媒体批调用未补 meta'
assert ls.count("names[i], '', meta);") == 1, '多文件调用未补 meta'
assert '"meta":${MiniJson.quote(m.meta)}' in ls, '序列化缺 meta'
assert "chatStr(n, 'meta')" in ls, '反序列化缺 meta'
assert 'this.snapshot.transferText = `接收 ${nm}`;' in ls, '协议侧动词缺失'
assert 'transferText = `接收 ${who.length > 0' in ls, '网页侧动词缺失'
assert 'this.snapshot.transferText = label.length > 0' in ls, '完成文案仍有 ✓'
assert "'5.1.49'" in ix, 'ABOUT_FALLBACK 未同步'
assert '5.1.49' in app, '版本号未改'

for p, s in ((LS, ls), (IX, ix), (APP, app)):
    assert '\r' not in s, '%s 含 CR' % p
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

print('改块数 :', len(B))
print('meta 透传 :', ls.count(', meta);'))
print('序列化meta:', ls.count('"meta":${MiniJson.quote(m.meta)}'))
print('反序列化 :', ls.count("chatStr(n, 'meta')"))
print('OK 5.1.49 applied')