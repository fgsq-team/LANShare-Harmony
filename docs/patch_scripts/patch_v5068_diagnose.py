# -*- coding: utf-8 -*-
"""v5.0.68 —— **纯诊断版**：不修，只抓事实。

背景：vivi 反馈 5.0.67 之后症状未变（存相册成功后仍快速闪一下）。
我上一轮（5.0.67）把原因判成「缓存文件被 TRUNC 原地覆盖」并修了，**但没治好**
⇒ 说明那个排除法有漏洞，或真凶另有其人。
⚠️ 连续两轮「改了但没好」之后，正确做法是**停止猜测、加观测**。

本版只做一件事：在「状态落地时刻」把**到底什么变了**打进 UI 日志。
读日志时能直接分辨下面四种可能，一次到位：

  ① 只有 albumIndex 变了        ⇒ 是 albumIndex 换引用触发重渲染
  ② chatMediaPaths 变了          ⇒ 是路径表收缩导致格子内容变
  ③ chatGroups 变了              ⇒ 是分组/行结构变（整组重建）
  ④ 全都没变                     ⇒ 根本不是状态问题（回去查资源/文件层，
                                  也就是 5.0.67 那条路，但需要更细的证据）
另外逐条打印**消息级签名**（src/rot/已删角标），能定位到「是哪一格在闪」。

⚠️ 关键：`logLines` 有 512KB 上限，所以**只在存相册收尾这一处打**，
   绝不放在渲染路径上（否则一次接收能刷出几百条，把真线索挤掉 ——
   这正是 5.0.51 那个日志风暴的教训）。
⚠️ 这些日志用 `logAuto` 进 `ui_log.txt`，vivi 用「复制日志」即可拿到。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.68' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5068pre'), (VER, 'app.json5.v5068pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：新增 snapshotDiagnostics() —— 打印「这一刻到底什么变了」
# =====================================================================
OLD1 = """  /**
   * ★ 5.0.63：缩略图预生成的**去抖批量提交**。"""
NEW1 = """  /**
   * ★ 5.0.68（**纯诊断，勿当修复**）：在状态落地时刻打印「到底什么变了」。
   *
   * 背景：5.0.67 修了「缓存文件被 TRUNC 覆盖」，**症状未变** ⇒ 那个判断不对。
   *   连续两轮「改了没好」之后不再猜，改用观测：下一次复现，这一行日志
   *   就能把四种可能一次分开（只有 albumIndex / chatMediaPaths / chatGroups /
   *   全都没变）。
   *
   * ⚠️ 只在存相册收尾调用（低频），**绝不放在渲染路径上** ——
   *   渲染路径每帧都走，放那里会一次接收刷几百条、把真线索挤掉
   *   （5.0.51 日志风暴的教训）。
   */
  private diagSnapshot(tag: string, swapped: boolean): void {
    let paths: string = '-';
    if (swapped) {
      paths = `n=${this.chatMediaPaths.size}`;
      let miss: number = 0;
      for (const k of this.chatMediaPaths.keys()) {
        if ((this.chatMediaPaths.get(k) ?? '').length === 0) {
          miss += 1;
        }
      }
      paths = `${paths} 空=${miss}`;
    }
    // 消息级签名：定位「是哪一格在闪」
    let sig: string = '';
    let shown: number = 0;
    for (let i: number = 0; i < this.chat.length && shown < 6; i++) {
      const m: ChatMessage = this.chat[i];
      if (m.kind !== 'file' || !m.incoming) {
        continue;
      }
      const src: string = this.mediaThumbSrcOf(m, 0);
      sig += `[${Index.baseName(src)}|rot${this.service.rotOf(src) ?? 0}`
        + `|gone${this.mediaGoneFromAlbum(m, 0) ? 1 : 0}]`;
      shown += 1;
    }
    this.service.logAuto(`[5.0.68诊断] ${tag} swap=${swapped ? 'Y' : 'N'}`
      + ` | albumIndex=${this.albumIndex.size}`
      + ` | mediaPaths=${paths}`
      + ` | groups=${this.chatGroups.length}`
      + ` | 签名: ${sig}`);
  }

  /**
   * ★ 5.0.63：缩略图预生成的**去抖批量提交**。"""

# =====================================================================
# 改 2：flushStateSwap 里逐项记录「换了哪些」
# =====================================================================
OLD2 = """  private flushStateSwap(): void {
    // ⚠️ 5.0.66：`receivedFiles` 与 `chat` 改为**立即落地**（见 swapChat 的注释），
    //   这里不再需要它们的缓冲字段。
    if (this.chatMediaPathsNext !== null) {
      this.chatMediaPaths = this.chatMediaPathsNext;
      this.chatMediaPathsNext = null;
    }
    if (this.chatMediaGroupsNext !== null) {
      this.chatMediaGroups = this.chatMediaGroupsNext;
      this.chatMediaGroupsNext = null;
    }
    if (this.chatGroupsNext !== null) {
      this.chatGroups = this.chatGroupsNext;
      this.chatGroupsNext = null;
    }
    if (this.albumIndexNext !== null) {
      this.albumIndex = this.albumIndexNext;
      this.albumIndexNext = null;
    }
  }"""
NEW2 = """  private flushStateSwap(): void {
    // ⚠️ 5.0.66：`receivedFiles` 与 `chat` 改为**立即落地**（见 swapChat 的注释），
    //   这里不再需要它们的缓冲字段。
    // ★★ 5.0.68（诊断）：逐项记录「换了哪些」，让下一次复现能一锤定音。
    const swP: boolean = this.chatMediaPathsNext !== null;
    const swG: boolean = this.chatMediaGroupsNext !== null;
    const swC: boolean = this.chatGroupsNext !== null;
    const swA: boolean = this.albumIndexNext !== null;
    if (swP) {
      this.chatMediaPaths = this.chatMediaPathsNext as Map<string, string>;
      this.chatMediaPathsNext = null;
    }
    if (swG) {
      this.chatMediaGroups = this.chatMediaGroupsNext as Map<string, string[]>;
      this.chatMediaGroupsNext = null;
    }
    if (swC) {
      this.chatGroups = this.chatGroupsNext as ChatGroup[];
      this.chatGroupsNext = null;
    }
    if (swA) {
      this.albumIndex = this.albumIndexNext as Map<string, string>;
      this.albumIndexNext = null;
    }
    // ⚠️ 只在「至少换了一项」时打，且带上分组名 —— 否则纯接收路径会刷屏
    if (swP || swG || swC || swA) {
      const what: string = `mediaPaths=${swP ? 1 : 0} mediaGroups=${swG ? 1 : 0}`
        + ` groups=${swC ? 1 : 0} albumIndex=${swA ? 1 : 0}`;
      this.diagSnapshot(`落地[${what}]`, swP);
    }
  }"""

# =====================================================================
# 改 3：存相册收尾前后各打一次（闪发生在这一刻附近）
# =====================================================================
OLD3 = """      this.autoSavePending = rest;
      // ★ 5.0.64：整段包进换引用闸门 —— 原先这里是「换 albumIndex」+"""
NEW3 = """      this.autoSavePending = rest;
      // ★ 5.0.68（诊断）：存相册收尾是「闪」的高发时刻，打前打后各一次
      this.diagSnapshot('存相册收尾-前', false);
      // ★ 5.0.64：整段包进换引用闸门 —— 原先这里是「换 albumIndex」+"""

OLD4 = '"versionCode": 5000067'
NEW4 = '"versionCode": 5000068'

s2 = s_idx
for old, new, tag in ((OLD1, NEW1, '改1 诊断方法'), (OLD2, NEW2, '改2 flush 逐项记录'),
                      (OLD3, NEW3, '改3 存相册收尾打点')):
    assert s2.count(old) == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, s2.count(old))
    s2 = s2.replace(old, new, 1)

v2 = s_ver
assert v2.count(OLD4) == 1
v2 = v2.replace(OLD4, NEW4, 1)
assert v2.count('"versionName": "5.0.67"') == 1
v2 = v2.replace('"versionName": "5.0.67"', '"versionName": "5.0.68"', 1)

# 不变量：诊断方法存在且只在低频处调用
assert s2.count('private diagSnapshot(tag: string, swapped: boolean): void {') == 1
assert s2.count('this.diagSnapshot(') == 2, s2.count('this.diagSnapshot(')   # flushStateSwap + 存相册收尾
assert '5.0.68诊断' in s2
# 原生产物必须没被破坏：TRUNC 短路仍在
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')
# 5.0.66 的立即落地仍在
assert 'this.chat = v;' in s2
assert 'receivedFilesNext' not in '\n'.join(
    l for l in s2.split('\n') if not l.strip().startswith('*') and not l.strip().startswith('//'))

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000068（诊断版，不改行为）' % (len(s_idx), len(s2)))
