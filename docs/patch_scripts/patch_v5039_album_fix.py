# -*- coding: utf-8 -*-
"""
5.0.39：修「发 1 张图不弹保存框」+ 存完删沙箱副本 + 点气泡跳系统相册。

## 根因（5.0.38 那个 1 张不弹 / 2 张才弹）
路径是从 `recvIndex` 反查的，而 `recvIndex` 只在 `refreshReceived()` 里重建；
`refreshReceived()` 又只在「`transferText` 由非空变空」时触发 ——
**小文件一次进度都没刷过**（transferText 全程空串）就永远不触发。
1 张小图正好命中（索引是旧的 → 解析出 0 条路径 → 静默 return）；
2 张耗时够长、刷过进度 → 索引是新的 → 才弹得出来。
⇒ 修法不是「调时序」，而是**不再依赖时序**：
   入队 → 无条件先 refreshReceived() 建索引 → 解析不出就留队里等下次刷新。

## 本版三件事（vivi 2026-10-02）
1. 自动存相册改成「待存队列 + 已处理集合」，并补一次强制索引刷新
2. 存进相册成功后 **删掉沙箱副本**（不留双份）
   ⚠️ 顺序不能反：先缓存 320px 缩略图 + 记下相册 URI，**再**删
3. 消息页点图片/视频 **直接跳系统相册**（包名两套都试）

幂等：每步各用自己的哨兵串判重；先全部校验、最后统一落盘。
"""
import io, sys

IDX = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'
SVC = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/service/LanService.ets'

idx = io.open(IDX, encoding='utf-8', newline='').read()
svc = io.open(SVC, encoding='utf-8', newline='').read()
orig_idx, orig_svc = idx, svc


def rep(s, old, new, tag):
    n = s.count(old)
    if n != 1:
        print('ERROR [%s]: old 出现 %d 次（应为 1）' % (tag, n))
        sys.exit(1)
    return s.replace(old, new, 1)


def rep_block(s, start_mark, end_mark, new, tag, keep_end=False):
    """按起止标记整块替换（起标记必须唯一，终标记取其后的第一次出现）。

    ⚠️ `keep_end=True` 时终标记**保留**在文件里（用作「插在它前面」的锚点）；
       默认连同终标记一起替换掉（终标记本身就是要被删掉的旧代码尾巴）。
    """
    a = s.find(start_mark)
    if a < 0:
        print('ERROR [%s]: 找不到起始标记' % tag)
        sys.exit(1)
    if s.count(start_mark) != 1:
        print('ERROR [%s]: 起始标记出现 %d 次' % (tag, s.count(start_mark)))
        sys.exit(1)
    b = s.find(end_mark, a)
    if b < 0:
        print('ERROR [%s]: 找不到结束标记' % tag)
        sys.exit(1)
    tail_at = b if keep_end else b + len(end_mark)
    return s[:a] + new + s[tail_at:]


# ------------------------------------------------------------ 1. import Want
if "common, bundleManager, Want } from '@kit.AbilityKit'" in idx:
    print('SKIP 1: Want 已导入')
else:
    idx = rep(idx,
              "import { common, bundleManager } from '@kit.AbilityKit';",
              "import { common, bundleManager, Want } from '@kit.AbilityKit';",
              'import-want')

# ------------------------------------------------------------ 2. @State albumIndex
if '@State albumIndex: Map<string, string>' in idx:
    print('SKIP 2: albumIndex 已存在')
else:
    old = ('  /** 收到图片/视频后自动存进系统相册（持久化在 LanService，默认开） */\n'
           '  @State autoAlbum: boolean = true;\n')
    new = old + (
        '  /**\n'
        '   * 5.0.39：已存进相册的媒体 —— 消息 id -> `相册URI|缩略图缓存路径`。\n'
        '   *\n'
        '   * ⚠️ 为什么必须有这张表：存完相册后沙箱副本会**被删掉**（vivi 要求不留双份），\n'
        '   *    `recvIndex` 立刻查不到它 —— 气泡缩略图和「点击打开」就都没了来源。\n'
        '   *    所以删之前先缓存一张 320px 小图，URI 与缩略图路径一起记在这里。\n'
        '   */\n'
        '  @State albumIndex: Map<string, string> = new Map<string, string>();\n')
    idx = rep(idx, old, new, 'state-album-index')

# ------------------------------------------------------------ 3. 待存队列字段
if 'private autoSavePending: string[]' in idx:
    print('SKIP 3: 待存队列字段已存在')
else:
    old = ('  /** 上次渲染的聊天条数，用于判断"有新消息才滚到底 + 才刷新镜像" */\n'
           '  private lastChatCount: number = 0;\n')
    new = old + (
        '  /** 5.0.39：待自动存相册的消息 id 队列（解析不出路径就留着，等下一次刷新再试） */\n'
        '  private autoSavePending: string[] = [];\n'
        '  /** 5.0.39：本次会话已弹过框的消息 id —— 存了、取消了、失败了都记，绝不再弹第二次 */\n'
        '  private autoSaveHandled: Set<string> = new Set<string>();\n'
        '  /** 5.0.39：正在弹框 / 拷贝中，防重入 */\n'
        '  private autoSaveBusy: boolean = false;\n')
    idx = rep(idx, old, new, 'queue-fields')

# ------------------------------------------------------------ 4. 启动时载入相册索引
if 'this.service.loadAlbumIndex(ctx)' in idx:
    print('SKIP 4: 载入相册索引已存在')
else:
    old = '    this.service.subscribe(this.onSnapshot);\n    this.applyWindowInset(ctx);\n'
    new = ('    this.service.subscribe(this.onSnapshot);\n'
           '    // 5.0.39：相册索引要先于气泡渲染就绪 —— 沙箱副本上一轮可能就删了，缩略图全靠它\n'
           '    this.service.loadAlbumIndex(ctx).then(() => {\n'
           '      this.albumIndex = this.service.albumSnapshot();\n'
           '    });\n'
           '    this.applyWindowInset(ctx);\n')
    idx = rep(idx, old, new, 'load-album-index')

# ------------------------------------------------------------ 5. refreshReceived 末尾补一次 flush
if '    // 5.0.39：待存相册的那一批' in idx:
    print('SKIP 5: refreshReceived 挂钩已存在')
else:
    old = ('    Log.i(TAG, `文件列表刷新：${list.length} 条，共 ${ExportService.humanSize(total)}`);\n'
           '  }\n')
    new = old + ('\n'
                 '    // 5.0.39：待存相册的那一批 —— 文件这时才刚落盘、索引刚建好，再试一次\n'
                 '    this.flushAutoSave();\n'
                 '  }\n')
    idx = rep(idx, old, new, 'flush-hook')

# ------------------------------------------------------------ 6. 重写 autoSaveNewMedia
NEW_AUTOSAVE = """
  /**
   * 5.0.39：刚收到的图片/视频 -> 排进「待存相册」队列，并立刻尝试一次。
   *
   * ⚠️ 5.0.38 为什么「1 张不弹、2 张才弹」（vivi 2026-10-02 真机反馈）：
   *    路径是从 `recvIndex` 反查的，而 `recvIndex` 只在 `refreshReceived()` 里重建，
   *    `refreshReceived()` 又只在「`transferText` 由非空变空」时触发 ——
   *    **小文件一次进度都没刷过**（transferText 全程空串）就永远不触发。
   *    1 张小图正好命中（索引是旧的 → 解析出 0 条路径 → 静默 return）；
   *    2 张耗时够长、刷过进度 → 索引是新的 → 才弹得出来。
   * 修法：**不再依赖时序** —— 入队后无条件先 `refreshReceived()` 把索引建出来，
   *    解析不出路径的留在队列里，等下一次 `refreshReceived()` 再试。
   *
   * @param oldCount 本次变化的**前**一条聊天条数（新增消息 = chat[oldCount..]）
   */
  private autoSaveNewMedia(oldCount: number): void {
    if (!this.autoAlbum) {
      return;
    }
    if (oldCount >= this.chat.length) {
      return;
    }
    const now: number = Date.now();
    for (let i: number = oldCount; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (!m.incoming || m.kind !== 'file') {
        continue;
      }
      // 60 秒新鲜度：挡掉「启动恢复历史聊天」那一茬条数跳变
      if (now - m.timeMs > 60000) {
        continue;
      }
      if (this.autoSaveHandled.has(m.id) || this.autoSavePending.indexOf(m.id) >= 0) {
        continue;
      }
      this.autoSavePending.push(m.id);
    }
    if (this.autoSavePending.length === 0) {
      return;
    }
    // 关键一步：先把「文件名 -> 沙箱路径」索引建出来，再去解析 —— 不再赌刷新时序
    this.refreshReceived();
    this.flushAutoSave();
  }

  /** 队列里能解析出路径的那些 -> 一次弹框存进相册；还没落盘的继续留在队列里 */
  private flushAutoSave(): void {
    if (this.autoSaveBusy || this.autoSavePending.length === 0) {
      return;
    }
    const paths: string[] = [];
    const owners: string[] = [];
    const ready: string[] = [];
    for (let i: number = 0; i < this.autoSavePending.length; i++) {
      const id: string = this.autoSavePending[i];
      const m: ChatMessage | undefined = this.msgById(id);
      if (m === undefined) {
        this.autoSaveHandled.add(id);
        continue;
      }
      const ps: string[] = this.resolveMediaPaths(m);
      if (ps.length === 0) {
        // 文件还没进索引 —— 留在队列里，等下一次 refreshReceived
        continue;
      }
      for (let k: number = 0; k < ps.length; k++) {
        if (paths.indexOf(ps[k]) < 0) {
          paths.push(ps[k]);
          owners.push(id);
        }
      }
      ready.push(id);
    }
    if (paths.length === 0) {
      return;
    }
    this.autoSaveBusy = true;
    this.autoSaveAlbumBatch(paths, owners, ready).then(() => {
      this.autoSaveBusy = false;
    });
  }

  /** 消息 id -> 消息（聊天条数不多，线性找即可） */
  private msgById(id: string): ChatMessage | undefined {
    for (let i: number = 0; i < this.chat.length; i++) {
      if (this.chat[i].id === id) {
        return this.chat[i];
      }
    }
    return undefined;
  }

  /**
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
  }
"""

if 'private flushAutoSave(' in idx:
    print('SKIP 6: autoSaveNewMedia 已重写')
else:
    idx = rep_block(idx,
                    '  private autoSaveNewMedia(oldCount: number): void {',
                    '    this.autoSaveAlbumBatch(paths);\n  }\n',
                    NEW_AUTOSAVE.lstrip('\n') + '\n',
                    'rewrite-autosave')

# ------------------------------------------------------------ 7. 重写 autoSaveAlbumBatch
NEW_BATCH = """
  /**
   * 整批存进系统相册 —— **只弹一次**确认框。
   *
   * `showAssetsCreationDialog` 一次可以传 N 个源文件 + N 份配置，
   * 返回 N 个带写权限的媒体 URI，逐个 `ExportService.copyTo` 写字节即可。
   * ⚠️ 不需要任何权限声明（WRITE_IMAGEVIDEO 是受限权限，申请不到），
   *    前提只有一条：module.json5 的 abilities 里配了 label 和 icon，
   *    否则确认框显示不出应用名。
   *
   * 5.0.39 存完之后的两件事（vivi 2026-10-02 要求）：
   *   ① **删掉沙箱里那份** —— 相册里已经有一份，留着就是双份占空间；
   *   ② 删之前先缓存一张 320px 小图 + 记下相册 URI ——
   *      否则气泡缩略图和「点击打开相册」都失去来源。
   *      ⚠️ 顺序不能反：**先出缩略图，再删**。
   *   ③ 用户在确认框上点取消时**不删** —— 那份是唯一的一份。
   * ⚠️ 拷贝是同步逐块的，先把提示 toast 画出去（yieldOnce 让一帧）再开拷。
   */
  private async autoSaveAlbumBatch(paths: string[], owners: string[],
                                   ready: string[]): Promise<void> {
    try {
      const ctx: common.UIAbilityContext =
        this.getUIContext().getHostContext() as common.UIAbilityContext;
      const helper: photoAccessHelper.PhotoAccessHelper =
        photoAccessHelper.getPhotoAccessHelper(ctx);
      const srcUris: string[] = [];
      const cfgs: photoAccessHelper.PhotoCreationConfig[] = [];
      for (let i: number = 0; i < paths.length; i++) {
        const name: string = Index.baseName(paths[i]);
        const dot: number = name.lastIndexOf('.');
        const isVideo: boolean = this.isVideoName(name);
        const cfg: photoAccessHelper.PhotoCreationConfig = {
          title: Index.safeAlbumTitle(dot > 0 ? name.substring(0, dot) : name),
          fileNameExtension: dot > 0 ? name.substring(dot + 1).toLowerCase()
            : (isVideo ? 'mp4' : 'jpg'),
          photoType: isVideo ? photoAccessHelper.PhotoType.VIDEO
            : photoAccessHelper.PhotoType.IMAGE
        };
        cfgs.push(cfg);
        srcUris.push(this.imageUri(paths[i]));
      }
      const uris: string[] = await helper.showAssetsCreationDialog(srcUris, cfgs);
      if (uris.length === 0) {
        // 用户在确认框上点了取消 —— 系统返回空数组，不是错误
        this.toast('已跳过存入相册');
        return;
      }
      this.toast(`正在存入相册（${uris.length} 个）…`);
      await Index.yieldOnce();
      const n: number = uris.length < paths.length ? uris.length : paths.length;
      let ok: number = 0;
      for (let i: number = 0; i < n; i++) {
        const msg: string = ExportService.copyTo(paths[i], uris[i], Index.baseName(paths[i]));
        if (msg.startsWith('已保存')) {
          ok += 1;
          // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反
          const thumb: string = await this.cacheThumb(ctx, paths[i], owners[i]);
          await this.service.setAlbumIndex(owners[i], uris[i], thumb);
          const derr: string | null =
            ExportService.deleteFile(this.service.receiveRoot, paths[i]);
          if (derr !== null) {
            Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${paths[i]}`);
          }
        }
      }
      this.toast(ok > 0 ? `已存入相册 ${ok} 个` : '存入相册失败');
      Log.i(TAG, `自动存相册：${ok}/${n}`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `自动存相册失败: ${err.code} ${err.message}`);
    } finally {
      // 弹过框就结案：存了 / 取消了 / 失败了，都不再弹第二次
      for (let i: number = 0; i < ready.length; i++) {
        this.autoSaveHandled.add(ready[i]);
      }
      const rest: string[] = [];
      for (let i: number = 0; i < this.autoSavePending.length; i++) {
        if (!this.autoSaveHandled.has(this.autoSavePending[i])) {
          rest.push(this.autoSavePending[i]);
        }
      }
      this.autoSavePending = rest;
      this.albumIndex = this.service.albumSnapshot();
      this.refreshReceived();
    }
  }
"""

if 'private async autoSaveAlbumBatch(paths: string[], owners: string[]' in idx:
    print('SKIP 7: autoSaveAlbumBatch 已重写')
else:
    idx = rep_block(idx,
                    '  private async autoSaveAlbumBatch(paths: string[]): Promise<void> {',
                    '\n  /** 把文件名压成系统允许的相册 title',
                    NEW_BATCH.lstrip('\n') + '\n',
                    'rewrite-batch',
                    keep_end=True)

# ------------------------------------------------------------ 8. 新增一批方法
NEW_HELPERS = """
  /**
   * 删沙箱副本之前，先缓存一张 320px 的小图 —— 气泡缩略图之后的**唯一**来源。
   *
   * ⚠️ 为什么必须缓存：沙箱那份删掉后 `recvIndex` 里就没它了，
   *    而相册那份的 URI 是「写授权」，回头再去读不一定读得到。
   *    趁**还握着沙箱原文件**的时候把缩略图落进 `cacheDir` 最稳。
   *
   * @returns 缩略图路径；失败返回空串（气泡退回占位块，**不影响删除**）
   */
  private async cacheThumb(ctx: common.UIAbilityContext, srcPath: string,
                           id: string): Promise<string> {
    let pm: image.PixelMap | null = null;
    let gen: media.AVImageGenerator | null = null;
    let f: fileIo.File | null = null;
    try {
      if (this.isVideoName(srcPath)) {
        // 视频：取离 0 最近的关键帧当封面（与 decodeVideoThumb 同一套取法）
        f = fileIo.openSync(srcPath, fileIo.OpenMode.READ_ONLY);
        gen = await media.createAVImageGenerator();
        gen.fdSrc = { fd: f.fd };
        pm = await gen.fetchFrameByTime(
          0, media.AVImageQueryOptions.AV_IMAGE_QUERY_CLOSEST_SYNC, { width: -1, height: -1 });
      } else {
        const src: image.ImageSource = image.createImageSource(srcPath);
        const info: image.ImageInfo = src.getImageInfoSync(0);
        const w: number = info.size.width;
        const h: number = info.size.height;
        const longest: number = w > h ? w : h;
        const s: number = longest > 320 ? 320 / longest : 1;
        // desiredSize 直接按目标尺寸解码 —— 4K 原图整张进内存太贵
        pm = await src.createPixelMap({
          desiredSize: {
            width: Math.max(1, Math.round(w * s)),
            height: Math.max(1, Math.round(h * s))
          }
        });
        try {
          src.release();
        } catch (x) {
          // 释放失败不影响缩略图
        }
      }
      if (pm === null) {
        return '';
      }
      const inf: image.ImageInfo = pm.getImageInfoSync();
      const iw: number = inf.size.width;
      const ih: number = inf.size.height;
      const longest2: number = iw > ih ? iw : ih;
      if (longest2 > 320) {
        const s2: number = 320 / longest2;
        await pm.scale(s2, s2);
      }
      const packer: image.ImagePacker = image.createImagePacker();
      const buf: ArrayBuffer = await packer.packing(pm, { format: 'image/jpeg', quality: 80 });
      try {
        await packer.release();
      } catch (x) {
        // 忽略
      }
      try {
        await pm.release();
      } catch (x) {
        // 忽略
      }
      pm = null;
      const dir: string = `${ctx.cacheDir}/album_thumbs`;
      try {
        fileIo.mkdirSync(dir);
      } catch (x) {
        // 目录已存在 —— 正常情况
      }
      const out: string = `${dir}/${id}.jpg`;
      const fo: fileIo.File = fileIo.openSync(out,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);
      try {
        fileIo.writeSync(fo.fd, buf);
      } finally {
        fileIo.closeSync(fo);
      }
      // 记下真实比例：气泡的缩略图框按它算，不然又变正方形
      if (iw > 0 && ih > 0) {
        this.mediaRatio.set(out, Index.clampRatio(iw / ih));
        this.thumbTick++;
      }
      return out;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `缓存缩略图失败: ${err.code} ${err.message} ${srcPath}`);
      return '';
    } finally {
      if (gen !== null) {
        try {
          await gen.release();
        } catch (x) {
          // 忽略
        }
      }
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (x) {
          // 忽略
        }
      }
    }
  }

  /** 相册索引的第 n 段：0 = 相册 URI，1 = 缩略图缓存路径 */
  private albumPart(id: string, part: number): string {
    const raw: string = this.albumIndex.get(id) ?? '';
    if (raw.length === 0) {
      return '';
    }
    const segs: string[] = raw.split('|');
    return part >= 0 && part < segs.length ? segs[part] : '';
  }

  /** 气泡缩略图的来源：沙箱那份还在就用它，已被删（存进相册了）就用缓存的小图 */
  private bubbleMediaPath(m: ChatMessage): string {
    const p: string = this.chatMediaPaths.get(m.id) ?? '';
    if (p.length > 0) {
      return p;
    }
    return this.albumPart(m.id, 1);
  }

  /**
   * 点一下「收到文件」气泡。
   *
   * 5.0.39（vivi 要求）：已经存进相册的图/视频 -> **直接跳系统相册**；
   *   还没存的（用户当时点了取消 / 自动存关着）-> 走原来那条应用内预览；
   *   其余（非媒体、或文件找不着）-> 跳「文件」页。
   */
  private onFileBubbleClick(m: ChatMessage): void {
    const album: string = this.albumPart(m.id, 0);
    if (album.length > 0) {
      this.openInGallery(album);
      return;
    }
    const ps: string[] = this.mediaPathsOf(m.id);
    if (ps.length > 1) {
      this.openChatGallery(m.id, 0);
      return;
    }
    if (ps.length === 1 && this.isMediaName(ps[0])) {
      this.openMediaPreview(ps[0], m.content);
      return;
    }
    const p: string = this.chatMediaPaths.get(m.id) ?? '';
    if (p.length > 0 && this.isMediaName(p)) {
      this.openMediaPreview(p, m.content);
      return;
    }
    this.openFileTab();
  }

  /**
   * 跳系统相册看这一个资产。
   *
   * ⚠️ 包名两套都要试：HarmonyOS（华为手机）是 `com.huawei.hmos.photos`，
   *    OpenHarmony 是 `com.ohos.photos` —— 写死一个在另一种形态上必失败，
   *    而失败**没有任何界面提示**（startAbility 只是 reject），排查很浪费时间。
   */
  private openInGallery(uri: string): void {
    const ctx: common.UIAbilityContext =
      this.getUIContext().getHostContext() as common.UIAbilityContext;
    const p1: Record<string, Object> = { 'uri': uri };
    const w1: Want = {
      action: 'ohos.want.action.viewData',
      parameters: p1,
      bundleName: 'com.huawei.hmos.photos',
      abilityName: 'com.huawei.hmos.photos.MainAbility'
    };
    ctx.startAbility(w1).then(() => {
      Log.i(TAG, '已跳转相册');
    }).catch(() => {
      const p2: Record<string, Object> = { 'uri': uri };
      const w2: Want = {
        action: 'ohos.want.action.viewData',
        parameters: p2,
        bundleName: 'com.ohos.photos',
        abilityName: 'com.ohos.photos.MainAbility'
      };
      ctx.startAbility(w2).catch((e: BusinessError) => {
        Log.w(TAG, `跳转相册失败: ${e.code} ${e.message}`);
        this.toast('跳转相册失败');
      });
    });
  }
"""

if 'private async cacheThumb(' in idx:
    print('SKIP 8: 新增方法已存在')
else:
    idx = rep(idx,
              '  /** 把文件名压成系统允许的相册 title',
              NEW_HELPERS.lstrip('\n') + '\n  /** 把文件名压成系统允许的相册 title',
              'new-helpers')

# ------------------------------------------------------------ 9. 气泡缩略图来源
if 'this.chatFileBubble(m, this.bubbleMediaPath(m))' in idx:
    print('SKIP 9: 气泡缩略图来源已改')
else:
    idx = rep(idx,
              "          this.chatFileBubble(m, this.chatMediaPaths.get(m.id) ?? '')",
              '          this.chatFileBubble(m, this.bubbleMediaPath(m))',
              'bubble-media-path')

# ------------------------------------------------------------ 10. 点击分流
if 'this.onFileBubbleClick(m);' in idx:
    print('SKIP 10: 点击分流已改')
else:
    old = ('        // 普通态：文件消息点一下跳「文件」页；文本消息不导航\n'
           '        if (m.kind === \'file\' && m.incoming) {\n'
           '          this.openFileTab();\n'
           '        }\n')
    new = ('        // 普通态：文件消息按「是否已存进相册」分流；文本消息不导航\n'
           '        if (m.kind === \'file\' && m.incoming) {\n'
           '          this.onFileBubbleClick(m);\n'
           '        }\n')
    idx = rep(idx, old, new, 'click-route')

# ------------------------------------------------------------ 11. 气泡提示文案
if '已存入相册 · 点击打开' in idx:
    print('SKIP 11: 提示文案已改')
else:
    old = ('  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {\n'
           '    return \'点击查看 ›\';\n'
           '  }')
    new = ('  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {\n'
           '    // 5.0.39：已经在相册里了，就明确告诉用户「点一下是去相册」\n'
           '    return this.albumPart(m.id, 0).length > 0 ? \'已存入相册 · 点击打开 ›\' : \'点击查看 ›\';\n'
           '  }')
    idx = rep(idx, old, new, 'hint')

# ------------------------------------------------------------ 12. LanService 相册索引
if 'private albumMap: Map<string, string>' in svc:
    print('SKIP 12: LanService 相册索引已存在')
else:
    old = '  /**\n   * 恢复默认设备名（设备市场名）。\n'
    new = (
        '  /** 5.0.39：已存进相册的媒体 —— 消息 id -> `相册URI|缩略图缓存路径` */\n'
        '  private albumMap: Map<string, string> = new Map<string, string>();\n'
        '  private albumLoaded: boolean = false;\n'
        '\n'
        '  /** 载入相册索引（幂等，只会真正读一次） */\n'
        '  async loadAlbumIndex(ctx: common.UIAbilityContext): Promise<void> {\n'
        '    if (this.albumLoaded) {\n'
        '      return;\n'
        '    }\n'
        '    this.albumLoaded = true;\n'
        '    try {\n'
        '      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_CFG);\n'
        '      const raw: Object = await store.get(\'albumIndex\', \'\');\n'
        '      if (typeof raw === \'string\') {\n'
        '        const rows: string[] = (raw as string).split(\'\\n\');\n'
        '        for (let i: number = 0; i < rows.length; i++) {\n'
        '          const segs: string[] = rows[i].split(\'|\');\n'
        '          if (segs.length >= 2 && segs[0].length > 0) {\n'
        '            this.albumMap.set(segs[0], rows[i]);\n'
        '          }\n'
        '        }\n'
        '      }\n'
        '    } catch (e) {\n'
        '      Log.w(TAG, \'读取相册索引失败\');\n'
        '    }\n'
        '  }\n'
        '\n'
        '  /** 给 UI 的快照 —— **整体换引用**才能触发重绘（Map 本身不可观察） */\n'
        '  albumSnapshot(): Map<string, string> {\n'
        '    const m: Map<string, string> = new Map<string, string>();\n'
        '    for (const k of this.albumMap.keys()) {\n'
        '      m.set(k, this.albumMap.get(k) ?? \'\');\n'
        '    }\n'
        '    return m;\n'
        '  }\n'
        '\n'
        '  /** 记一条「已存进相册」：相册 URI + 缓存出来的缩略图路径 */\n'
        '  async setAlbumIndex(id: string, uri: string, thumb: string): Promise<void> {\n'
        '    this.albumLoaded = true;\n'
        '    this.albumMap.set(id, `${uri}|${thumb}`);\n'
        '    await this.persistAlbumIndex();\n'
        '  }\n'
        '\n'
        '  /** 删聊天记录时顺带清索引。⚠️ 相册里那一份**不动**，只清这条映射 */\n'
        '  private dropAlbumIndex(ids: string[]): void {\n'
        '    let hit: boolean = false;\n'
        '    for (let i: number = 0; i < ids.length; i++) {\n'
        '      if (this.albumMap.delete(ids[i])) {\n'
        '        hit = true;\n'
        '      }\n'
        '    }\n'
        '    if (hit) {\n'
        '      this.persistAlbumIndex().catch((e: Error) => {\n'
        '        Log.w(TAG, `清理相册索引落盘异常: ${e.message}`);\n'
        '      });\n'
        '    }\n'
        '  }\n'
        '\n'
        '  private async persistAlbumIndex(): Promise<void> {\n'
        '    if (this.ctx === null) {\n'
        '      return;\n'
        '    }\n'
        '    try {\n'
        '      const store: preferences.Preferences =\n'
        '        await preferences.getPreferences(this.ctx, PREF_CFG);\n'
        '      const rows: string[] = [];\n'
        '      for (const k of this.albumMap.keys()) {\n'
        '        rows.push(this.albumMap.get(k) ?? \'\');\n'
        '      }\n'
        '      await store.put(\'albumIndex\', rows.join(\'\\n\'));\n'
        '      await store.flush();\n'
        '    } catch (e) {\n'
        '      Log.w(TAG, \'保存相册索引失败\');\n'
        '    }\n'
        '  }\n'
        '\n' + old)
    svc = rep(svc, old, new, 'svc-album-index')

# ------------------------------------------------------------ 13. 启动时载入
if 'await this.loadAlbumIndex(ctx);' in svc:
    print('SKIP 13: startSharing 载入已存在')
else:
    svc = rep(svc,
              '    await this.loadAutoAlbumPref(ctx);\n',
              '    await this.loadAutoAlbumPref(ctx);\n'
              '    await this.loadAlbumIndex(ctx);\n',
              'svc-load')

# ------------------------------------------------------------ 14. 删聊天时清索引
if 'this.dropAlbumIndex(ids);' in svc:
    print('SKIP 14: 清索引已存在')
else:
    svc = rep(svc,
              '    this.chatRing = kept;\n    this.emit();',
              '    this.chatRing = kept;\n    this.dropAlbumIndex(ids);\n    this.emit();',
              'svc-drop')

# ------------------------------------------------------------ 落盘
if idx != orig_idx:
    io.open(IDX, 'w', encoding='utf-8', newline='').write(idx)
    print('WROTE Index.ets (+%d 字符)' % (len(idx) - len(orig_idx)))
if svc != orig_svc:
    io.open(SVC, 'w', encoding='utf-8', newline='').write(svc)
    print('WROTE LanService.ets (+%d 字符)' % (len(svc) - len(orig_svc)))
print('DONE')
