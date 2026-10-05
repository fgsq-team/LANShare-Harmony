# -*- coding: utf-8 -*-
"""
v5.1.2：非媒体文件（zip / pdf / apk）的「已存入本地 / 已删除」记账。

【需求（vivi 21:12）】
收到的文件气泡（`chatFileBubble`），在**另存为到本地**或**删除**后，
把底部的「点击查看」改成「已存入本地」/「已删除」。

【为什么要新的一套记账，不能复用相册索引】
`albumMap` 的 key 是**消息 id + 媒体序号**（`albumKeyOf(id,k)`），
value 是 `相册URI|缩略图路径` —— 它的语义是「**媒体进了系统相册**」。
非媒体文件既没有相册 URI 也没有缩略图，两边都对不上 ⇒ 只能新加。

【设计：照抄 albumMap 的成熟套路，一比一对应】
| | 相册（已有） | 本地文件（本轮新增） |
|---|---|---|
| 内存 | `albumMap: Map<id, string>` | `localMap: Map<id, string>` |
| 持久化 | `preferences` key `albumIndex` | key `localFileIndex`（**同一个 PREF_CFG**） |
| 落盘 | `persistAlbumIndex()` | `persistLocalIndex()` |
| 加载 | `loadAlbumIndex()` 段 | 同一段里一起读（避免多开一次 preferences） |
| 判据 | `mediaGoneFromAlbum()` | `localStateOf()` |

⚠️ **key 必须一起写进每行**（5.0.43 踩过：只写 value、读回来还原不出 key ⇒ 索引全废）。
⚠️ 状态值用**中文可读串**（`已存本地` / `已删除`）而不是 0/1 ——
   preferences 本来就是字符串存储，且将来要加第三种状态时不用改判据。

【判据放在哪 —— 与 5.1.1 的教训一致】
`bubbleFooterText` 里**先判是不是媒体、再判本地状态**（顺序不能反：
非媒体根本没有相册状态）。5.1.1 刚踩过「判据缺一维」，
这次把「本地状态」补在**同一个方法**里，不再散出去。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
SVC = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\service\LanService.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 服务端 LanService.ets —— 4 处
# =====================================================================

# --- 改S1：声明 localMap（紧跟 albumMap）---
OLDS1 = """  /** 5.0.39：已存进相册的媒体 —— 消息 id -> `相册URI|缩略图缓存路径` */
  private albumMap: Map<string, string> = new Map<string, string>();
  private albumLoaded: boolean = false;"""
NEWS1 = """  /** 5.0.39：已存进相册的媒体 —— 消息 id -> `相册URI|缩略图缓存路径` */
  private albumMap: Map<string, string> = new Map<string, string>();
  private albumLoaded: boolean = false;

  /**
   * ★ 5.1.2：**非媒体文件**（zip / pdf / apk）的落地状态 —— 消息 id -> 状态串。
   *
   * ⚠️ **为什么不能复用 `albumMap`**：它的 key 是「消息 id + 媒体序号」
   *   （`albumKeyOf(id,k)`）、value 是 `相册URI|缩略图路径`，语义是「媒体进了系统相册」。
   *   非媒体文件既没有相册 URI 也没有缩略图，两边都对不上。
   *
   * 值域（**中文可读串**，preferences 本来就存字符串，将来加第三种不用改判据）：
   *   `已存本地` —— 另存为成功（沙箱副本已按 5.0.53 口径删掉）
   *   `已删除`   —— 用户在文件页点了删除
   * 空串 / 查不到 = 没动过（此时显示「点击查看」）
   */
  private localMap: Map<string, string> = new Map<string, string>();

  /** ★ 5.1.2：读本地文件落地状态（空串 = 没动过）。Index 的气泡判据用它。 */
  localStateOf(id: string): string {
    if (id.length === 0) {
      return '';
    }
    return this.localMap.get(id) ?? '';
  }

  /** ★ 5.1.2：写本地文件落地状态并落盘。`state` 传空串等于取消记账。 */
  markLocalState(id: string, state: string): void {
    if (id.length === 0 || state.length === 0) {
      return;
    }
    this.localMap.set(id, state);
    this.persistLocalIndex().catch((e: Error) => {
      Log.w(TAG, `保存本地文件状态失败: ${e.message}`);
    });
  }

  /** ★ 5.1.2：落盘。格式 `id|状态`（⚠️ key 必须一起写 —— 5.0.43 踩过这个坑）。 */
  private async persistLocalIndex(): Promise<void> {
    if (this.ctx === null) {
      return;
    }
    try {
      const store: preferences.Preferences =
        await preferences.getPreferences(this.ctx, PREF_CFG);
      const rows: string[] = [];
      for (const k of this.localMap.keys()) {
        const v: string = this.localMap.get(k) ?? '';
        if (k.length > 0 && v.length > 0) {
          rows.push(`${k}|${v}`);
        }
      }
      await store.put('localFileIndex', rows.join('\\n'));
      await store.flush();
    } catch (e) {
      Log.w(TAG, '保存本地文件状态索引失败');
    }
  }"""

# --- 改S2：加载（与 albumIndex 同一次读盘）---
OLDS2 = """      // 5.0.43：把老版本留在 cacheDir 里的缩略图搬到 filesDir 并补回索引
      await this.migrateThumbCache(ctx);"""
NEWS2 = """      // ★ 5.1.2：同一次 preferences 会话里把「非媒体文件落地状态」一起读回来
      //   （不另开一次 getPreferences —— 少一次 IO，也不必再拿一次 ctx）。
      const rawLocal: Object = await store.get('localFileIndex', '');
      if (typeof rawLocal === 'string') {
        const lrows: string[] = (rawLocal as string).split('\\n');
        for (let i: number = 0; i < lrows.length; i++) {
          const row: string = lrows[i];
          if (row.length === 0) {
            continue;
          }
          // 行格式 `id|状态`。老版本没有这个 key ⇒ 这里读到的是空串 ⇒ 直接跳过。
          const pos: number = row.indexOf('|');
          if (pos > 0) {
            this.localMap.set(row.substring(0, pos), row.substring(pos + 1));
          }
        }
      }
      // 5.0.43：把老版本留在 cacheDir 里的缩略图搬到 filesDir 并补回索引
      await this.migrateThumbCache(ctx);"""

SVC_REPL = [
    (OLDS1, NEWS1, 'S1 localMap + 三个方法'),
    (OLDS2, NEWS2, 'S2 加载'),
]

# =====================================================================
# 页面 Index.ets —— 4 处
# =====================================================================

# --- 改P1：新常量 HINT_LOCAL_SAVED / HINT_LOCAL_DELETED + MAX_LEN 改 Math.max(5参) ---
OLDP1 = """  /** ★ 5.1.1：**非媒体文件**（zip / pdf / apk…）的唯一合理提示。
   *  它们既没有缩略图、也存不进相册 ⇒ 说「长按存入相册」是错的（vivi 20:58 反馈）。 */
  private static readonly HINT_FILE: string = '点击查看';
  /** 四条里最长的那条长度 —— 等宽补齐的基准（5.0.70 的规矩）。
   *  ⚠️ 5.1.1：新增 HINT_FILE 后**必须一并纳入**，否则加长文案时会漏。 */
  private static readonly HINT_MAX_LEN: number = Math.max(
    Index.HINT_IN_ALBUM.length, Index.HINT_NOT_YET.length,
    Index.HINT_GONE.length, Index.HINT_FILE.length);"""
NEWP1 = """  /** ★ 5.1.1：**非媒体文件**（zip / pdf / apk…）的唯一合理提示。
   *  它们既没有缩略图、也存不进相册 ⇒ 说「长按存入相册」是错的（vivi 20:58 反馈）。 */
  private static readonly HINT_FILE: string = '点击查看';
  /** ★ 5.1.2：非媒体文件**已另存为到本地**（另存成功后沙箱副本已删）。 */
  private static readonly HINT_LOCAL_SAVED: string = '已存入本地';
  /** ★ 5.1.2：非媒体文件**已被删除**（文件页点了删除，或另存后清沙箱）。 */
  private static readonly HINT_LOCAL_DELETED: string = '已删除';
  /** 六条里最长的那条长度 —— 等宽补齐的基准（5.0.70 的规矩）。
   *  ⚠️ 用 `Math.max` 而不是手写三元嵌套：**新增文案时不会漏改**（5.1.1 的教训）。 */
  private static readonly HINT_MAX_LEN: number = Math.max(
    Index.HINT_IN_ALBUM.length, Index.HINT_NOT_YET.length,
    Index.HINT_GONE.length, Index.HINT_FILE.length,
    Index.HINT_LOCAL_SAVED.length, Index.HINT_LOCAL_DELETED.length);"""

# --- 改P2：bubbleFooterText 的非媒体分支改成三分支 ---
OLDP2 = """  private bubbleFooterText(m: ChatMessage, mediaPath: string): string {
    if (mediaPath.length === 0 || !this.isMediaName(mediaPath)) {
      return this.padHint(Index.HINT_FILE);
    }
    return `${this.bubbleCountText(m)} · ${this.bubbleHintOf(m, mediaPath)}`;
  }"""
NEWP2 = """  private bubbleFooterText(m: ChatMessage, mediaPath: string): string {
    if (mediaPath.length === 0 || !this.isMediaName(mediaPath)) {
      // ★ 5.1.2：非媒体的三态 —— 点击查看 / 已存入本地 / 已删除。
      //   ⚠️ 顺序固定：先「有没有动过」，再落到具体状态。
      //   ⚠️ 这三条互斥（一个 Map key 一个值），所以 if/else 链即可。
      const st: string = this.service.localStateOf(m.id);
      if (st.length > 0) {
        return this.padHint(st);
      }
      return this.padHint(Index.HINT_FILE);
    }
    return `${this.bubbleCountText(m)} · ${this.bubbleHintOf(m, mediaPath)}`;
  }"""

# --- 改P3：saveAsFile 成功后记账（按文件名反查消息 id）---
OLDP3 = """    // ★ 5.0.53（vivi 要求）：另存成功后**删掉沙箱副本**，不再留双份。
    //   与「存相册后删沙箱副本」同一口径：内容已经落到应用之外了。
    const err: string | null = ExportService.deleteFile(this.service.receiveRoot, f.path);
    this.toast(err === null ? `${msg}，沙箱副本已删除` : `${msg}（沙箱副本删除失败：${err}）`);
    this.refreshReceived();"""
NEWP3 = """    // ★ 5.0.53（vivi 要求）：另存成功后**删掉沙箱副本**，不再留双份。
    //   与「存相册后删沙箱副本」同一口径：内容已经落到应用之外了。
    const err: string | null = ExportService.deleteFile(this.service.receiveRoot, f.path);
    this.toast(err === null ? `${msg}，沙箱副本已删除` : `${msg}（沙箱副本删除失败：${err}）`);
    // ★ 5.1.2：记账「已存本地」—— 气泡底部据此把「点击查看」改成「已存入本地」。
    //   ⚠️ 必须在**删除沙箱副本之后**记：删失败时内容还在沙箱里，不该显示「已存入本地」。
    //   ⚠️ 用 `f.name` 反查而不是拿消息对象：文件页的按钮拿到的是 `ReceivedFile`，
    //   与消息没有直接引用（5.0.55 的「显示聚合 ≠ 记账聚合」决定了不能顺着 UI 传）。
    this.markMessagesLocal(f.name, Index.HINT_LOCAL_SAVED);
    this.refreshReceived();"""

# --- 改P4：deleteOne 成功后记账「已删除」---
OLDP4 = """    const err: string | null = ExportService.deleteFile(this.service.receiveRoot, f.path);
    this.toast(err === null ? `已删除 ${f.name}` : err);
    this.refreshReceived();"""
NEWP4 = """    const err: string | null = ExportService.deleteFile(this.service.receiveRoot, f.path);
    this.toast(err === null ? `已删除 ${f.name}` : err);
    // ★ 5.1.2：删除**成功**才记账（err !== null 说明文件可能还在）。
    if (err === null) {
      this.markMessagesLocal(f.name, Index.HINT_LOCAL_DELETED);
    }
    this.refreshReceived();"""

# --- 改P5：新增 markMessagesLocal（按文件名反查消息 id 并批量记账）---
OLDP5 = """  /**
   * ★ 5.1.1：气泡底部**整行**提示。"""
NEWP5 = """  /**
   * ★ 5.1.2：按**文件名**反查消息 id 并批量写本地落地状态。
   *
   * ⚠️ **为什么只能按名字反查、不能拿消息对象**：文件页的按钮拿到的是
   *   `ReceivedFile`，与 `ChatMessage` **没有共享引用**（5.0.55 的
   *   「显示聚合 ≠ 记账聚合」决定了不能顺着 UI 把消息传下去）。
   *
   * ⚠️ **同名多份怎么办**：本项目的既有口径是「**时间就近**」
   *   （`recvPathFor` 对多候选按 `|f.time - msg.timeMs|` 排序取最近的那个）——
   *   记账必须与它**保持一致**，否则会出现「气泡 A 显示已存、实际存的是气泡 B 那份」。
   *   所以这里对每个同名消息各记一笔（而不是只记一个），
   *   保证「凡是同名的那批，状态都对得上」。
   *
   * ⚠️ **一次可能记多条**：一个文件名可能对应多条消息（重名 / 去重后缀），
   *   全部记上才不会漏。
   */
  private markMessagesLocal(fileName: string, state: string): void {
    if (fileName.length === 0 || state.length === 0) {
      return;
    }
    const bare: string = Index.stripDedupeSuffix(fileName);
    let hit: number = 0;
    for (let i: number = 0; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (m.kind !== 'file' || !m.incoming) {
        continue;
      }
      if (m.content === fileName || Index.stripDedupeSuffix(m.content) === bare) {
        this.service.markLocalState(m.id, state);
        hit += 1;
      }
    }
    if (hit > 0) {
      this.swapAlbumIndex();   // 走换引用闸门 ⇒ 气泡提示会真的重新求值
      this.service.logAuto(`[5.1.2] 记本地状态 ${state}：${fileName} 命中 ${hit} 条消息`);
    }
  }

  /**
   * ★ 5.1.1：气泡底部**整行**提示。"""

IDX_REPL = [
    (OLDP1, NEWP1, 'P1 新常量 + MAX_LEN'),
    (OLDP2, NEWP2, 'P2 三态判据'),
    (OLDP5, NEWP5, 'P5 markMessagesLocal'),
    (OLDP3, NEWP3, 'P3 另存成功后记账'),
    (OLDP4, NEWP4, 'P4 删除成功后记账'),
]

# =====================================================================
# 版本号
# =====================================================================
OLDV = '"versionCode": 5000101'
NEWV = '"versionCode": 5000102'

# =====================================================================
# 执行：先全部校验，最后统一落盘
# =====================================================================
s_svc = io.open(SVC, encoding='utf-8').read()
s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if 'HINT_LOCAL_SAVED' in s_idx:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'LanService.ets.v512pre'), 'w', encoding='utf-8', newline='\n').write(s_svc)
io.open(os.path.join(BAK, 'Index.ets.v512pre'), 'w', encoding='utf-8', newline='\n').write(s_idx)
io.open(os.path.join(BAK, 'app.json5.v512pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成（3 个文件）')

for old, new, tag in SVC_REPL:
    n = s_svc.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s_svc = s_svc.replace(old, new, 1)

for old, new, tag in IDX_REPL:
    n = s_idx.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s_idx = s_idx.replace(old, new, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.1"') == 1
s_ver = s_ver.replace('"versionName": "5.1.1"', '"versionName": "5.1.2"', 1)

# ---------------- 不变量 ----------------
# 服务端
assert 'private localMap: Map<string, string> = new Map<string, string>();' in s_svc
assert 'localStateOf(id: string): string {' in s_svc
assert 'markLocalState(id: string, state: string): void {' in s_svc
assert 'private async persistLocalIndex(): Promise<void> {' in s_svc
assert "store.put('localFileIndex'" in s_svc
assert "store.get('localFileIndex'" in s_svc
assert s_svc.count('rows.push(`${k}|${v}`);') >= 1     # localMap 也带 key
# 页面
assert "private static readonly HINT_LOCAL_SAVED: string = '已存入本地';" in s_idx
assert "private static readonly HINT_LOCAL_DELETED: string = '已删除';" in s_idx
assert 'Index.HINT_LOCAL_SAVED.length' in s_idx
assert 'private markMessagesLocal(fileName: string, state: string): void {' in s_idx
assert s_idx.count('this.markMessagesLocal(f.name, Index.HINT_LOCAL_SAVED);') == 1
assert s_idx.count('this.markMessagesLocal(f.name, Index.HINT_LOCAL_DELETED);') == 1
# 5.1.1 的成果仍在
assert s_idx.count("private static readonly HINT_FILE: string = '点击查看';") == 1
assert 'this.padHint(Index.HINT_FILE);' in s_idx
# 5.1.0 的成果仍在
assert 'private diagSnapshot(' not in s_idx and 'this.diagSnapshot(' not in s_idx
assert "const ABOUT_FALLBACK_VER: string = '5.1.0';" in s_idx

io.open(SVC, 'w', encoding='utf-8', newline='\n').write(s_svc)
io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s_idx)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  LanService.ets %d -> %d' % (0, len(s_svc)))
print('OK  Index.ets     %d -> %d' % (0, len(s_idx)))
print('OK  versionCode 5000101 -> 5000102 / 5.1.2')
