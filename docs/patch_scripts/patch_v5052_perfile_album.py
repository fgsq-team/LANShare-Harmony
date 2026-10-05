# -*- coding: utf-8 -*-
"""
5.0.52 补丁：相册索引从「每条消息一个槽位」改成「每一张图一个槽位」。

vivi 2026-10-02 反馈：
  ① 接收多张图片后，在系统相册里删掉第一张 —— **这一批全部**提示「已删除」；
  ② 把以前收到（并在相册里删掉）的照片再收一次，缩略图显示的却是**以前那张**，
     点击跳相册打开的也不是刚收到的那张。

根因（两处，都在「标识」上）：
  A. 相册索引 `albumMap` 的 key 是**消息 id**，而对端一次发 N 张图我们只产生
     **一条**「N 个文件」消息 ⇒ 同一批 N 张图共用一个 uri + 一份缩略图
     （`album_thumbs/<消息id>.jpg` 被后写覆盖前写）。删一张 = 全批失效。
  B. 「名字 → 沙箱路径」是多对一（同名图落盘会被加 `(1)` 后缀），谁先谁后决定
     气泡显示哪一张 ⇒ 跨消息串台。另外「文件」页打开画廊时忘了复位 `imgPreviewId`，
     会把无关的图写到上一条消息的相册条目上。

本补丁：
  A. Index.ets：新增 albumKeyOf / mediaNamesOf / albumPartOf / recvPathFor / mediaSrcOf，
     flushAutoSave + autoSaveAlbumBatch 按**媒体序号**下发 key，气泡与画廊
     （含「存相册」按钮）全部改成按每一张图各自记账。
  B. LanService.ets：dropAlbumIndex 改成前缀匹配（`id#k` + 裸 id 兼容旧数据）。
  C. 活体探针：只有「明确不存在」(13900002) 才判已删除，其它错误一律当「还在」
     —— 5.0.51 把「两个信号都失败」一律判删除，真机上媒体 URI 可能因权限读不到，
     于是**每张图**都被谎报「已从相册删除」。
"""
import io
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
F_IDX = ROOT + r'\entry\src\main\ets\pages\Index.ets'
F_SVC = ROOT + r'\entry\src\main\ets\service\LanService.ets'
F_APP = ROOT + r'\AppScope\app.json5'

SENTINEL = '5.0.52'


def load(p):
    return io.open(p, encoding='utf-8', newline='').read()


def save(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s.replace('\r\n', '\n'))


def rep(s, old, new, tag, count=1):
    got = s.count(old)
    assert got == count, '%s: 锚点命中 %d 次（期望 %d）\n---\n%s' % (tag, got, count, old[:200])
    return s.replace(old, new, count)


idx = load(F_IDX)
svc = load(F_SVC)
app = load(F_APP)

if SENTINEL in idx and 'albumKeyOf' in idx:
    print('ALREADY APPLIED')
    sys.exit(0)

# ======================================================================
# C. 活体探针：只有明确「不存在」才算被删
# ======================================================================
OLD_PROBE = """    // 两个信号**全都失败** -> 判定「已从相册删除」。原始错误码写进 UI 日志，
    //   下一次真机日志就能给出平台真相（写打开这条路已证伪，不再采信）。
    this.service.logAuto(`相册探活判定已删除（statSize=${statSize}，信号: ${codes.join(' ')}）：${uri}`);
    return false;"""
NEW_PROBE = """    // ★ 5.0.52：两个信号**都失败**时，**只有「明确不存在」(13900002) 才算真删了**。
    //   ⚠️ 5.0.51 把「都失败」一律判删除 —— 真机上 `showAssetsCreationDialog` 给的是
    //   **写授权** URI，读它可能因权限失败（≠ 文件不存在），于是**每一张图**都被
    //   谎报「已从相册删除」（vivi 2026-10-02：「删掉第一张后所有图片都提示已删除」）。
    //   宁可像 5.0.50 那样「判定不出来就照常跳相册」，也不要谎报删除。
    //   原始错误码照旧写进 UI 日志 —— 下一轮真机日志就能给出平台真相。
    const gone: boolean = codes.indexOf('stat=13900002') >= 0
      || codes.indexOf('open=13900002') >= 0;
    this.service.logAuto(`相册探活：${gone ? '已不存在' : '判定不出（按还在处理）'}`
      + `（statSize=${statSize}，信号: ${codes.join(' ')}）：${uri}`);
    return !gone;"""
idx = rep(idx, OLD_PROBE, NEW_PROBE, '探针判定')

# ======================================================================
# A-1. 新增 5 个辅助方法（插在 stripDedupeSuffix 与 syncChatMediaPaths 之间）
# ======================================================================
ANCHOR_HELPERS = """    return `${base.substring(0, lp)}${ext}`;
  }

  /**
   * 把「每条消息 -> 其媒体沙箱路径」算好存进 @State，供气泡渲染缩略图。"""

NEW_HELPERS = """    return `${base.substring(0, lp)}${ext}`;
  }

  /**
   * ★ 5.0.52：相册索引的 key —— **消息 id + 该消息里第几个媒体**（0 起）。
   *
   * ⚠️ 为什么必须带序号：对端一次发 N 张图，我们只产生**一条**「N 个文件」消息
   *    （`V5Transfer` 收完整批才回一次终态；`FileTransfer` 把名字合并成「N 个文件」）。
   *    5.0.39~5.0.51 的相册索引是 `Map<消息id, "uri|thumb">` —— **一条消息只有一个槽位**：
   *    这一批 N 张图的缩略图全写进同一个 `<消息id>.jpg`（后写覆盖前写，只剩最后一张），
   *    albumMap 也只记得最后那个 uri。
   *    真机症状（vivi 2026-10-02）：在系统相册里删掉其中一张，**这一批全部**提示
   *    「已删除」；点击打开的也不是缩略图显示的那张。改成 `消息id#序号` 之后，
   *    每张图各有一条 uri + 一份缩略图，互不影响。
   */
  private static albumKeyOf(id: string, k: number): string {
    return `${id}#${k}`;
  }

  /**
   * ★ 5.0.52：这条消息里**媒体**的名字，顺序与对端发来的一致。
   *
   * ⚠️ 关键：**只看消息本身**（`m.files` / `m.content`），**不看沙箱里还剩几个文件**。
   *    5.0.51 之前拿 `mediaPathsOf()`（沙箱里还在的路径）当下标来源 —— 自动存相册后
   *    沙箱副本被删，数组会**塌缩**：第 2 张的下标变成 0，于是「第 2 张的相册条目」
   *    被写成了「第 1 张的」（还是 5.0.48 那个「靠刷新建索引」的老病灶的另一种形态）。
   */
  private mediaNamesOf(m: ChatMessage): string[] {
    const out: string[] = [];
    if (m.files.length > 0) {
      const ns: string[] = Index.splitFileNames(m.files);
      for (let i: number = 0; i < ns.length; i++) {
        if (this.isMediaName(ns[i])) {
          out.push(ns[i]);
        }
      }
    }
    // 单发时 `files` 可能为空，名字只在 content 里
    if (out.length === 0 && this.isMediaName(m.content)) {
      out.push(m.content);
    }
    return out;
  }

  /**
   * ★ 5.0.52：读一条相册条目 —— 先按新格式 `id#k`，读不到再兜底旧格式（裸 id）。
   *
   * 旧格式只有 k=0 能兜底：那时整条消息只存了一个槽位，
   * 我们对不上它是这一批里的第几张，只能当第一张用。
   */
  private albumPartOf(id: string, k: number, part: number): string {
    const v: string = this.albumPart(Index.albumKeyOf(id, k), part);
    if (v.length > 0) {
      return v;
    }
    return k === 0 ? this.albumPart(id, part) : '';
  }

  /**
   * ★ 5.0.52：把「对端发来的名字」翻成沙箱路径 —— **按与这条消息的时间差就近取**。
   *
   * ⚠️ 为什么不能再用单纯的名字表：同名文件会跨消息串台。
   *    对端发来 `IMG_1.jpg`、沙箱里已经有一张同名的老图时，落盘名会被
   *    `FileKinds.dedupeName` 改成 `IMG_1(1).jpg` ——「名字 → 路径」是**多对一**，
   *    谁先谁后就决定了气泡显示哪一张。真机症状：删掉老图后再收同名新图，
   *    气泡显示的却是**以前那张**。
   *    现在按 `|文件时间 - 消息时间|` 就近取：每条消息只会命中**自己那一批**落下的文件。
   *    `k` 用来区分「同一条消息里同名的第 k 个」（对端真发了两张同名图时）。
   */
  private recvPathFor(name: string, k: number, msgTimeMs: number): string {
    const cands: ReceivedFile[] = [];
    for (let i: number = 0; i < this.receivedFiles.length; i++) {
      const f: ReceivedFile = this.receivedFiles[i];
      if (f.name === name || Index.stripDedupeSuffix(f.name) === name) {
        cands.push(f);
      }
    }
    if (cands.length === 0) {
      // 兜底：老表（按名字取最新）。文件已被删 / 超出列表上限时走这里。
      const hit: string | undefined = this.recvIndex.get(name);
      return hit === undefined ? '' : hit;
    }
    if (cands.length > 1) {
      cands.sort((a: ReceivedFile, b: ReceivedFile) => {
        const da: number = Math.abs(a.time - msgTimeMs);
        const db: number = Math.abs(b.time - msgTimeMs);
        return da - db;
      });
    }
    return (k >= 0 && k < cands.length ? cands[k] : cands[0]).path;
  }

  /**
   * ★ 5.0.52：这条消息第 k 个媒体**当前最好的显示源**：
   * 沙箱那份还在就用它（原图），已经被删（存进相册了）就用**这一张自己的**缓存缩略图。
   */
  private mediaSrcOf(m: ChatMessage, k: number): string {
    const names: string[] = this.mediaNamesOf(m);
    if (k < 0 || k >= names.length) {
      return '';
    }
    const p: string = this.recvPathFor(names[k], k, m.timeMs);
    if (p.length > 0) {
      return p;
    }
    return this.albumPartOf(m.id, k, 1);
  }

  /**
   * 把「每条消息 -> 其媒体沙箱路径」算好存进 @State，供气泡渲染缩略图。"""
idx = rep(idx, ANCHOR_HELPERS, NEW_HELPERS, '插入辅助方法')

# ======================================================================
# A-2. syncChatMediaPaths：改用「媒体序号 + 时间就近」
# ======================================================================
OLD_SYNC = """      if (msg.kind === 'file' && msg.incoming) {
        if (this.isMediaName(msg.content)) {
          const hit: string | undefined = this.recvIndex.get(msg.content);
          if (hit !== undefined) {
            p = hit;
          }
        }
        // 5.0.31：一批文件 —— 逐个名字反查路径，只收「能直接看」的那几类。
        // ⚠️ 去重按**路径**：同一张图被登记了两个键时别重复进画廊。
        if (msg.files.length > 0) {
          const names: string[] = Index.splitFileNames(msg.files);
          for (let k = 0; k < names.length; k++) {
            if (!this.isMediaName(names[k])) {
              continue;
            }
            const hit2: string | undefined = this.recvIndex.get(names[k]);
            if (hit2 !== undefined && !paths.includes(hit2)) {
              paths.push(hit2);
            }
          }
          if (p.length === 0 && paths.length > 0) {
            p = paths[0];
          }
        }
      }
      m.set(msg.id, p);
      g.set(msg.id, paths);
      // 5.0.32：不再同步量图片比例（消息页不再内嵌缩略图，省掉这步同步开销）
      sig += `${msg.id}:${paths.join(',')};`;"""
NEW_SYNC = """      if (msg.kind === 'file' && msg.incoming) {
        // ★ 5.0.52：下标 = **消息里的媒体序号**（`mediaNamesOf` 只看消息本身，
        //   不随沙箱副本被删而塌缩）；路径按「与这条消息的时间差」就近取，
        //   同名文件再也不会跨消息串台（见 `recvPathFor`）。
        // ⚠️ 去重按**路径**：同一张图被登记了两个键时别重复进画廊。
        const medias: string[] = this.mediaNamesOf(msg);
        for (let k: number = 0; k < medias.length; k++) {
          const hit2: string = this.recvPathFor(medias[k], k, msg.timeMs);
          if (hit2.length > 0 && !paths.includes(hit2)) {
            paths.push(hit2);
          }
          if (p.length === 0 && hit2.length > 0) {
            p = hit2;
          }
        }
      }
      m.set(msg.id, p);
      g.set(msg.id, paths);
      sig += `${msg.id}:${paths.join(',')};`;"""
idx = rep(idx, OLD_SYNC, NEW_SYNC, 'syncChatMediaPaths')

# ======================================================================
# A-3. bubbleHintOf / bubbleMediaPath
# ======================================================================
idx = rep(idx,
          "    return this.albumPart(m.id, 0).length > 0 ? '已存入相册 · 点击打开 ›' : '点击查看 ›';",
          "    return this.albumPartOf(m.id, 0, 0).length > 0 ? '已存入相册 · 点击打开 ›' : '点击查看 ›';",
          'bubbleHintOf')

OLD_BMP = """  private bubbleMediaPath(m: ChatMessage): string {
    const p: string = this.chatMediaPaths.get(m.id) ?? '';
    if (p.length > 0) {
      return p;
    }
    return this.albumPart(m.id, 1);
  }"""
NEW_BMP = """  private bubbleMediaPath(m: ChatMessage): string {
    // ★ 5.0.52：气泡显示的是**这一批里的第 1 张**，缩略图必须取第 1 张自己的那份。
    //   （5.0.51 之前取的是「这条消息那唯一一个槽位」= 一批里最后写进去的那张，
    //    于是「缩略图显示的不是刚收到的那张」。）
    return this.mediaSrcOf(m, 0);
  }"""
idx = rep(idx, OLD_BMP, NEW_BMP, 'bubbleMediaPath')

# ======================================================================
# A-4. flushAutoSave：按媒体序号下发 key
# ======================================================================
idx = rep(idx,
          """    const paths: string[] = [];
    const owners: string[] = [];
    const ready: string[] = [];""",
          """    const paths: string[] = [];
    // ★ 5.0.52：与 `paths` 一一对应的**相册 key**（`消息id#媒体序号`）——
    //   一批 N 张图各占一条条目，删其中一张不再连带全批。
    const keys: string[] = [];
    const ready: string[] = [];""",
          'flushAutoSave 声明')

OLD_BUILD = """      const ps: string[] = this.resolveMediaPaths(m);
      if (ps.length === 0) {
        // 文件还没进索引 —— 留在队列里，等下一次 refreshReceived。
        // 5.0.51：但**不能无限等** —— 见 `autoSaveTry` 上的注释。
        const n: number = (this.autoSaveTry.get(id) ?? 0) + 1;
        this.autoSaveTry.set(id, n);
        if (!this.autoSaveFirstMs.has(id)) {
          this.autoSaveFirstMs.set(id, now);
        }
        const waited: number = now - (this.autoSaveFirstMs.get(id) ?? now);
        if (n >= 6 || waited > 60000) {
          expired.push(id);
        }
        continue;
      }
      for (let k: number = 0; k < ps.length; k++) {
        if (paths.indexOf(ps[k]) < 0) {
          paths.push(ps[k]);
          owners.push(id);
        }
      }
      ready.push(id);"""
NEW_BUILD = """      // ★ 5.0.52：按 `mediaNamesOf` 的**媒体序号**逐个解析 —— 下标只取决于消息本身
      //   （不随沙箱副本被删而塌缩），相册 key 直接用这个序号。
      const medias: string[] = this.mediaNamesOf(m);
      let any: boolean = false;
      for (let k: number = 0; k < medias.length; k++) {
        const p: string = this.recvPathFor(medias[k], k, m.timeMs);
        if (p.length === 0) {
          continue;
        }
        any = true;
        if (paths.indexOf(p) >= 0) {
          continue;
        }
        paths.push(p);
        keys.push(Index.albumKeyOf(id, k));
      }
      if (!any) {
        // 文件还没进索引 —— 留在队列里，等下一次 refreshReceived。
        // 5.0.51：但**不能无限等** —— 见 `autoSaveTry` 上的注释。
        const n: number = (this.autoSaveTry.get(id) ?? 0) + 1;
        this.autoSaveTry.set(id, n);
        if (!this.autoSaveFirstMs.has(id)) {
          this.autoSaveFirstMs.set(id, now);
        }
        const waited: number = now - (this.autoSaveFirstMs.get(id) ?? now);
        if (n >= 6 || waited > 60000) {
          expired.push(id);
        }
        continue;
      }
      ready.push(id);"""
idx = rep(idx, OLD_BUILD, NEW_BUILD, 'flushAutoSave 解析')

idx = rep(idx,
          'this.autoSaveAlbumBatch(paths, owners, ready).then(() => {',
          'this.autoSaveAlbumBatch(paths, keys, ready).then(() => {',
          'flushAutoSave 调用')

# ======================================================================
# A-5. autoSaveAlbumBatch：用 key 而不是消息 id
# ======================================================================
idx = rep(idx,
          """  private async autoSaveAlbumBatch(paths: string[], owners: string[],
                                   ready: string[]): Promise<void> {""",
          """  private async autoSaveAlbumBatch(paths: string[], keys: string[],
                                   ready: string[]): Promise<void> {""",
          'autoSaveAlbumBatch 签名')

idx = rep(idx,
          '            const thumb: string = await this.cacheThumb(ctx, paths[i], owners[i]);',
          '            const thumb: string = await this.cacheThumb(ctx, paths[i], keys[i]);',
          'autoSaveAlbumBatch cacheThumb')

idx = rep(idx,
          '            await this.service.setAlbumIndex(owners[i], uris[i], thumb, rot);',
          '            await this.service.setAlbumIndex(keys[i], uris[i], thumb, rot);',
          'autoSaveAlbumBatch setAlbumIndex')

# ======================================================================
# A-6. resolveMediaPaths 已由 mediaNamesOf/recvPathFor 取代
# ======================================================================
OLD_RESOLVE = """  /**
   * 这条「收到文件」消息对应的**媒体**沙箱路径。
   *
   * ⚠️ 直接用 `recvIndex` 反查，不经过 `chatMediaPaths`：
   *    那边是 @State、为渲染服务的，赋值时机与这里并不一致（曾因此取到空串）。
   */
  private resolveMediaPaths(m: ChatMessage): string[] {
    const out: string[] = [];
    const names: string[] = [];
    if (m.files.length > 0) {
      const ns: string[] = Index.splitFileNames(m.files);
      for (let i: number = 0; i < ns.length; i++) {
        names.push(ns[i]);
      }
    }
    // 单发时 `files` 可能为空，名字只在 content 里（多发时 content 是「N 个文件」，会被下面过滤掉）
    if (m.content.length > 0 && names.indexOf(m.content) < 0) {
      names.push(m.content);
    }
    for (let i: number = 0; i < names.length; i++) {
      if (!this.isMediaName(names[i])) {
        continue;
      }
      const p: string | undefined = this.recvIndex.get(names[i]);
      if (p !== undefined && p.length > 0 && out.indexOf(p) < 0) {
        out.push(p);
      }
    }
    return out;
  }"""
NEW_RESOLVE = """  /*
   * 5.0.52：`resolveMediaPaths()` 已删除。
   *   它按**名字**反查、且只返回「沙箱里还在」的路径 —— 下标会随沙箱副本被删而塌缩，
   *   于是「第 2 张图」的下标变成 0，相册条目被写到第 1 张头上。
   *   现在统一走 `mediaNamesOf()`（下标来源）+ `recvPathFor()`（时间就近取路径）+
   *   `mediaSrcOf()`（沙箱优先、否则用这一张自己的缓存缩略图）。
   */"""
idx = rep(idx, OLD_RESOLVE, NEW_RESOLVE, '删除 resolveMediaPaths')

# ======================================================================
# A-7. onFileBubbleClick：全量重写（按每一张图记账）
# ======================================================================
OLD_CLICK = """  private onFileBubbleClick(m: ChatMessage): void {
    const album: string = this.albumPart(m.id, 0);
    if (album.length > 0) {
      // 5.0.49：先确认相册里那份**还在**。
      //   用户可能已经在系统相册里把它删了 —— 那时直接 startAbility 会跳进
      //   一个**空白相册页**，而且没有任何提示（vivi 2026-10-02 反馈）。
      if (this.albumAssetAlive(album)) {
        this.openInGallery(album);
        return;
      }
      this.toast('该文件已从相册删除');
      this.service.logAuto(`相册资产已不存在（已从相册删除），摘掉失效 URI：${m.id}`);
      this.service.clearAlbumUri(m.id);
      this.albumIndex = this.service.albumSnapshot();
      // 降级：还有缓存的 320px 小图就打开它，至少让用户看到内容
      const gone: string = this.albumPart(m.id, 1);
      if (gone.length > 0 && this.isMediaName(gone)) {
        this.openMediaPreview(gone, m.content, m.id);
      }
      return;
    }
    const ps: string[] = this.mediaPathsOf(m.id);
    if (ps.length > 1) {
      this.openChatGallery(m.id, 0);
      return;
    }
    if (ps.length === 1 && this.isMediaName(ps[0])) {
      this.openMediaPreview(ps[0], m.content, m.id);
      return;
    }
    const p: string = this.chatMediaPaths.get(m.id) ?? '';
    if (p.length > 0 && this.isMediaName(p)) {
      this.openMediaPreview(p, m.content, m.id);
      return;
    }
    // 5.0.50（vivi 要求）：**不再自动补存相册**。
    //   5.0.45 这里会把「只剩缓存缩略图」的图悄悄存回相册 ——
    //   用户在系统相册里删掉之后再点，它就被偷偷存回来了，等于删不掉。
    //   现在统一：只提示 + 用缓存小图在应用内看，绝不再写相册。
    const thumb: string = this.albumPart(m.id, 1);
    if (thumb.length > 0 && this.isMediaName(thumb)) {
      this.toast('该文件已从相册删除');
      this.openMediaPreview(thumb, m.content, m.id);
      return;
    }
    this.openFileTab();
  }"""
NEW_CLICK = """  private onFileBubbleClick(m: ChatMessage): void {
    // ★ 5.0.52：全部按**每一张图**记账（key = `消息id#媒体序号`）。
    //   气泡显示的是这一批的第 1 张，所以这里也只处理第 1 张的相册条目。
    const key0: string = Index.albumKeyOf(m.id, 0);
    const album: string = this.albumPartOf(m.id, 0, 0);
    if (album.length > 0) {
      // 5.0.49：先确认相册里那份**还在**。
      //   用户可能已经在系统相册里把它删了 —— 那时直接 startAbility 会跳进
      //   一个**空白相册页**，而且没有任何提示（vivi 2026-10-02 反馈）。
      if (this.albumAssetAlive(album)) {
        this.openInGallery(album);
        return;
      }
      this.toast('该文件已从相册删除');
      this.service.logAuto(`相册资产已不存在（已从相册删除），摘掉失效 URI：${key0}`);
      this.service.clearAlbumUri(key0);
      this.albumIndex = this.service.albumSnapshot();
      // 降级：还有缓存的 320px 小图就打开它，至少让用户看到内容
      const gone: string = this.albumPartOf(m.id, 0, 1);
      if (gone.length > 0 && this.isMediaName(gone)) {
        this.openMediaPreview(gone, m.content, key0);
      }
      return;
    }
    // 还没存相册：一张 -> 直接预览；一批 -> 进画廊左右滑（每页各自对应自己的相册条目）
    if (this.mediaNamesOf(m).length > 1) {
      if (this.openChatGallery(m.id, 0)) {
        return;
      }
      this.openFileTab();
      return;
    }
    const src: string = this.mediaSrcOf(m, 0);
    if (src.length > 0 && this.isMediaName(src)) {
      this.openMediaPreview(src, m.content, key0);
      return;
    }
    // 5.0.50（vivi 要求）：**不再自动补存相册**。
    //   5.0.45 这里会把「只剩缓存缩略图」的图悄悄存回相册 ——
    //   用户在系统相册里删掉之后再点，它就被偷偷存回来了，等于删不掉。
    //   现在统一：只提示 + 用缓存小图在应用内看，绝不再写相册。
    const thumb: string = this.albumPartOf(m.id, 0, 1);
    if (thumb.length > 0 && this.isMediaName(thumb)) {
      this.toast('该文件已从相册删除');
      this.openMediaPreview(thumb, m.content, key0);
      return;
    }
    this.openFileTab();
  }"""
idx = rep(idx, OLD_CLICK, NEW_CLICK, 'onFileBubbleClick')

# ======================================================================
# A-8. imgPreviewId -> imgPreviewKey（相册 key）
# ======================================================================
idx = rep(idx,
          """  /** 5.0.44：预览页「存相册」时需要知道当前是哪条消息 */
  @State imgPreviewId: string = '';""",
          """  /**
   * ★ 5.0.52：当前预览 / 画廊页对应的**相册索引 key**（`消息id#媒体序号`）。
   * 空串 = 不写相册索引（例如从「文件」页打开 —— 那里的图不属于任何消息）。
   * ⚠️ 原来存的是「消息 id」，而「文件」页打开画廊时**忘了复位**它 ⇒
   *   会把无关的图写到上一条消息的相册条目上（真机「点击打开的不是刚收到的那张」）。
   */
  @State imgPreviewKey: string = '';""",
          'imgPreviewKey 声明')

idx = rep(idx,
          """  private openMediaPreview(path: string, name: string, id: string = ''): void {
    this.imgPreviewId = id;
    this.openMediaGallery([path], [name], 0);
  }""",
          """  private openMediaPreview(path: string, name: string, key: string = ''): void {
    this.openMediaGallery([path], [name], 0, [key]);
  }""",
          'openMediaPreview')

# ======================================================================
# A-9. 画廊：galleryKeys + 存相册用「当前页自己的 key」
# ======================================================================
idx = rep(idx,
          """  /** 画廊当前页下标 */
  @State galleryIndex: number = 0;""",
          """  /** 画廊当前页下标 */
  @State galleryIndex: number = 0;
  /**
   * ★ 5.0.52：与 `galleryPaths` 一一对应的**相册 key**（可能比它短 / 为空）。
   * 显式存下来而不是「用下标去推」—— 画廊里跳过没有源的项时下标会错位。
   */
  @State galleryKeys: string[] = [];""",
          'galleryKeys 声明')

idx = rep(idx,
          """  private openMediaGallery(paths: string[], names: string[], index: number): void {
    if (paths.length === 0) {
      return;
    }
    this.galleryPaths = paths;
    this.galleryNames = names;""",
          """  private openMediaGallery(paths: string[], names: string[], index: number,
                           keys: string[] = []): void {
    if (paths.length === 0) {
      return;
    }
    this.galleryPaths = paths;
    this.galleryNames = names;
    this.galleryKeys = keys;""",
          'openMediaGallery 签名')

idx = rep(idx,
          """    this.galleryIndex = at;
    for (let i = 0; i < paths.length; i++) {
      if (this.isVideoName(this.galleryNameAt(i))) {""",
          """    this.galleryIndex = at;
    this.imgPreviewKey = this.galleryKeyAt(at);
    for (let i = 0; i < paths.length; i++) {
      if (this.isVideoName(this.galleryNameAt(i))) {""",
          'openMediaGallery key')

idx = rep(idx,
          """    this.galleryIndex = idx;
    this.imgPreview = this.galleryPaths[idx];""",
          """    this.galleryIndex = idx;
    this.imgPreviewKey = this.galleryKeyAt(idx);
    this.imgPreview = this.galleryPaths[idx];""",
          'onGalleryPageChanged key')

idx = rep(idx,
          """  /** 画廊第 i 项的显示名（越界时退回当前项） */
  private galleryNameAt(i: number): string {""",
          """  /**
   * ★ 5.0.52：画廊第 i 页对应的**相册 key**。
   * 越界 / 来自「文件」页（没有 key）时给空串 = 该页不写相册索引。
   */
  private galleryKeyAt(i: number): string {
    return i >= 0 && i < this.galleryKeys.length ? this.galleryKeys[i] : '';
  }

  /** 画廊第 i 项的显示名（越界时退回当前项） */
  private galleryNameAt(i: number): string {""",
          'galleryKeyAt')

idx = rep(idx,
          """    this.galleryPaths = [];
    this.galleryNames = [];
    this.galleryIndex = 0;""",
          """    this.galleryPaths = [];
    this.galleryNames = [];
    this.galleryKeys = [];
    this.galleryIndex = 0;""",
          'closeMediaPreview 复位')

OLD_OPEN_GALLERY = """  /** 消息气泡：打开这一批（从第 index 张看起） */
  private openChatGallery(id: string, index: number): void {
    const paths: string[] = this.mediaPathsOf(id);
    if (paths.length === 0) {
      return;
    }
    const names: string[] = [];
    for (let i = 0; i < paths.length; i++) {
      names.push(Index.baseName(paths[i]));
    }
    this.imgPreviewId = id;
    this.openMediaGallery(paths, names, index);
  }"""
NEW_OPEN_GALLERY = """  /**
   * 消息气泡：打开这一批（从第 index 张看起）。
   *
   * ★ 5.0.52：改两处 ——
   *  ① 源的顺序按**消息里的媒体序号**取（`mediaSrcOf`），沙箱副本被删的那些
   *     自动换成**这一张自己的**缓存缩略图，下标不再塌缩；
   *  ② 每页带上自己的相册 key，于是画廊里「存相册」永远写的是当前这一张。
   *
   * @returns true = 真的打开了（有至少一个可显示的源）
   */
  private openChatGallery(id: string, index: number): boolean {
    const m: ChatMessage | undefined = this.msgById(id);
    if (m === undefined) {
      return false;
    }
    const medias: string[] = this.mediaNamesOf(m);
    const srcs: string[] = [];
    const keys: string[] = [];
    const disp: string[] = [];
    for (let k: number = 0; k < medias.length; k++) {
      const s: string = this.mediaSrcOf(m, k);
      if (s.length === 0) {
        continue;
      }
      srcs.push(s);
      keys.push(Index.albumKeyOf(id, k));
      disp.push(medias[k]);
    }
    if (srcs.length === 0) {
      return false;
    }
    this.openMediaGallery(srcs, disp, index, keys);
    return true;
  }"""
idx = rep(idx, OLD_OPEN_GALLERY, NEW_OPEN_GALLERY, 'openChatGallery')

# 文件页画廊：**必须复位 key**（否则会把无关的图写到上一条消息的条目上）
idx = rep(idx,
          """    if (paths.length === 0) {
      this.openMediaPreview(f.path, f.name);
      return;
    }
    this.openMediaGallery(paths, names, at);
  }""",
          """    if (paths.length === 0) {
      this.openMediaPreview(f.path, f.name);
      return;
    }
    // ★ 5.0.52：这里**不传** keys —— 文件页的图不属于任何消息，绝不能写相册索引。
    //   （5.0.51 之前「当前预览对应的消息 id」在文件页不会被复位，于是文件页
    //    「存相册」会把无关的图写到上一条消息的相册条目上。）
    this.openMediaGallery(paths, names, at);
  }""",
          'openFileGallery 不复位说明')

# ======================================================================
# A-10. saveImageToAlbum：第 3 个参数改成「相册 key」
# ======================================================================
idx = rep(idx,
          "  private async saveImageToAlbum(path: string, name: string, id: string = ''): Promise<boolean> {",
          "  private async saveImageToAlbum(path: string, name: string, key: string = ''): Promise<boolean> {",
          'saveImageToAlbum 签名')

idx = rep(idx,
          """      // 5.0.44：手动保存也要缓存缩略图并记相册 URI，否则沙箱原图一删就丢。
      if (id.length > 0) {""",
          """      // 5.0.44：手动保存也要缓存缩略图并记相册 URI，否则沙箱原图一删就丢。
      // ★ 5.0.52：`key` 是**每一张图**的相册 key（`消息id#媒体序号`），空串 = 不记账。
      if (key.length > 0) {""",
          'saveImageToAlbum 判断')

idx = rep(idx,
          """          const oldThumb: string = this.albumPart(id, 1);
          const thumb: string = (oldThumb.length > 0 && oldThumb === path)
            ? path : await this.cacheThumb(ctx, path, id);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          await this.service.setAlbumIndex(id, uris[0], thumb, rot);""",
          """          const oldThumb: string = this.albumPart(key, 1);
          const thumb: string = (oldThumb.length > 0 && oldThumb === path)
            ? path : await this.cacheThumb(ctx, path, key);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          await this.service.setAlbumIndex(key, uris[0], thumb, rot);""",
          'saveImageToAlbum 记账')

idx = rep(idx,
          '            .onClick(() => this.saveImageToAlbum(this.imgPreview, this.imgPreviewName, this.imgPreviewId))',
          '            .onClick(() => this.saveImageToAlbum(this.imgPreview, this.imgPreviewName, this.imgPreviewKey))',
          '顶部存相册按钮')

# 预览页：每页带自己的 key（长按存相册用当前页的 key）
idx = rep(idx,
          '              this.mediaPreviewPage(p, this.galleryNameAt(i), i === this.galleryIndex)',
          '              this.mediaPreviewPage(p, this.galleryNameAt(i), i === this.galleryIndex,\n                this.galleryKeyAt(i))',
          'Swiper 页面调用')

idx = rep(idx,
          '          this.mediaPreviewPage(this.imgPreview, this.imgPreviewName, true)',
          '          this.mediaPreviewPage(this.imgPreview, this.imgPreviewName, true, this.imgPreviewKey)',
          '单图预览调用')

idx = rep(idx,
          '  mediaPreviewPage(path: string, name: string, active: boolean) {',
          '  mediaPreviewPage(path: string, name: string, active: boolean, key: string) {',
          'mediaPreviewPage 签名')

idx = rep(idx,
          """              LongPressGesture({ repeat: false, duration: 400 })
                .onAction(() => {
                  this.saveImageToAlbum(path, name, this.imgPreviewId);
                })""",
          """              LongPressGesture({ repeat: false, duration: 400 })
                .onAction(() => {
                  // ★ 5.0.52：用**这一页自己的** key，不是当前页的
                  this.saveImageToAlbum(path, name, key);
                })""",
          '长按存相册')

# ======================================================================
# A-11. 聊天行 key 带上相册条目，否则条目落地后气泡不会重绘
# ======================================================================
OLD_KEY = '          }, (m: ChatMessage) => `${m.id}|${this.videoThumbTick}|${this.thumbTick}|${this.mediaCountOf(m.id)}|${this.chatMediaPaths.has(m.id) ? (this.chatMediaPaths.get(m.id) ?? \'\') : \'\'}`)'
NEW_KEY = """          }, (m: ChatMessage) => `${m.id}|${this.videoThumbTick}|${this.thumbTick}|${this.mediaCountOf(m.id)}|${this.chatMediaPaths.has(m.id) ? (this.chatMediaPaths.get(m.id) ?? '') : ''}|${this.albumPartOf(m.id, 0, 0).length > 0 ? 1 : 0}|${this.albumPartOf(m.id, 0, 1)}`)"""
idx = rep(idx, OLD_KEY, NEW_KEY, '聊天行 key')

idx = rep(idx,
          """    this.imgPreviewName = '';
    this.imgPreviewId = '';""",
          """    this.imgPreviewName = '';
    this.imgPreviewKey = '';""",
          'closeMediaPreview 复位 key')

# 旧的「imgPreviewId」不允许再有残留
if 'imgPreviewId' in idx:
    pos = 0
    while True:
        pos = idx.find('imgPreviewId', pos)
        if pos < 0:
            break
        print('--- 残留 @%d ---' % pos)
        print(repr(idx[pos - 160:pos + 80]))
        pos += 1
assert 'imgPreviewId' not in idx, '仍残留 imgPreviewId'

# ======================================================================
# B. LanService.dropAlbumIndex：前缀匹配
# ======================================================================
OLD_DROP = """  /** 删聊天记录时顺带清索引。⚠️ 相册里那一份**不动**，只清这条映射 */
  private dropAlbumIndex(ids: string[]): void {
    let hit: boolean = false;
    for (let i: number = 0; i < ids.length; i++) {
      const row: string | undefined = this.albumMap.get(ids[i]);
      if (row === undefined) {
        continue;
      }
      this.albumMap.delete(ids[i]);
      hit = true;
      // 5.0.43：缩略图缓存已挪到 filesDir（不会再被系统自动清），
      //         删记录时必须自己删掉，否则会一直堆着。⚠️ 相册里那一份**不动**。
      const segs: string[] = row.split('|');
      const thumb: string = segs.length >= 2 ? segs[1] : '';
      if (thumb.length > 0) {
        try {
          fileIo.unlinkSync(thumb);
        } catch (x) {
          // 已经不在了就算了
        }
      }
    }"""
NEW_DROP = """  /** 删聊天记录时顺带清索引。⚠️ 相册里那一份**不动**，只清这条映射 */
  private dropAlbumIndex(ids: string[]): void {
    let hit: boolean = false;
    for (let i: number = 0; i < ids.length; i++) {
      const id: string = ids[i];
      // ★ 5.0.52：key 现在是 `消息id#媒体序号`，**一条消息可能有多条** —— 前缀匹配全清。
      //   裸 id 也一起带上（兼容 5.0.39~5.0.51 写下的旧行）。
      const keys: string[] = [id];
      for (const k of this.albumMap.keys()) {
        if (k.startsWith(id + '#')) {
          keys.push(k);
        }
      }
      for (let j: number = 0; j < keys.length; j++) {
        const row: string | undefined = this.albumMap.get(keys[j]);
        if (row === undefined) {
          continue;
        }
        this.albumMap.delete(keys[j]);
        hit = true;
        // 5.0.43：缩略图缓存已挪到 filesDir（不会再被系统自动清），
        //         删记录时必须自己删掉，否则会一直堆着。⚠️ 相册里那一份**不动**。
        const segs: string[] = row.split('|');
        const thumb: string = segs.length >= 2 ? segs[1] : '';
        if (thumb.length > 0) {
          try {
            fileIo.unlinkSync(thumb);
          } catch (x) {
            // 已经不在了就算了
          }
        }
      }
    }"""
svc = rep(svc, OLD_DROP, NEW_DROP, 'dropAlbumIndex')

# clearAlbumUri 的过期注释（historyToAlbum 5.0.50 已删）
svc = rep(svc,
          """   * 只清 uri 不清缩略图：气泡还能显示小图，而且下一次点击会自然走到
   * 「补存进相册」（historyToAlbum）那条路，可以自愈。""",
          """   * 只清 uri 不清缩略图：气泡还能显示小图（用缓存那份做应用内预览）。
   * ⚠️ 5.0.50 起**不会**再自动补存相册（historyToAlbum 已删）—— 用户删掉的就别再偷存回去。
   * ⚠️ 5.0.52 起 key 是 `消息id#媒体序号`（每一张图一条），调用方传的也是这个 key。""",
          'clearAlbumUri 注释')

# ======================================================================
# D. 版本号
# ======================================================================
app = rep(app, '"versionCode": 5000051,', '"versionCode": 5000052,', 'versionCode')
app = rep(app, '"versionName": "5.0.51"', '"versionName": "5.0.52"', 'versionName')

# ---- 统一落盘 ----
save(F_IDX, idx)
save(F_SVC, svc)
save(F_APP, app)
print('OK: 5.0.52 已应用')
