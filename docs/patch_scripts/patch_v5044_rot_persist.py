#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5.0.44 修复：持久化缩略图旋转角度 + 手动保存也建索引 + 旧消息点击优先预览
"""
import sys
import io

ROOT = r'E:/lanshare-harmony/LANShareV5'


def read(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        return f.read()


def write(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


def patch_lan_service(s):
    # 1) albumMap 旁边加 albumRotMap + rotOf
    old1 = """  /** 5.0.39：已存进相册的媒体 —— 消息 id -> `相册URI|缩略图缓存路径` */
  private albumMap: Map<string, string> = new Map<string, string>();
  private albumLoaded: boolean = false;
"""
    new1 = """  /** 5.0.39：已存进相册的媒体 —— 消息 id -> `相册URI|缩略图缓存路径` */
  private albumMap: Map<string, string> = new Map<string, string>();
  private albumLoaded: boolean = false;

  /**
   * 5.0.44：每张缓存缩略图需要显示层补转的角度。
   * key = 缩略图绝对路径，value = 0/90/180/270/-1。
   * 必须持久化：重启后页面内存清空，否则「靠 Image.orientation() 补转」的图会躺回去。
   */
  /** 5.0.44：public —— Index 页面在 cacheThumb() 里需要直接写入 */
  albumRotMap: Map<string, number> = new Map<string, number>();

  /** UI 查询某张缓存缩略图该用哪个方向 */
  rotOf(thumb: string): number | undefined {
    return this.albumRotMap.get(thumb);
  }
"""
    assert s.count(old1) == 1, f'albumMap 段落出现 {s.count(old1)} 次'
    s = s.replace(old1, new1)

    # 2) loadAlbumIndex 末尾加 loadAlbumRot
    old2 = """      // 5.0.43：把老版本留在 cacheDir 里的缩略图搬到 filesDir 并补回索引
      await this.migrateThumbCache(ctx);
    } catch (e) {
      Log.w(TAG, '读取相册索引失败');
    }
  }
"""
    new2 = """      // 5.0.43：把老版本留在 cacheDir 里的缩略图搬到 filesDir 并补回索引
      await this.migrateThumbCache(ctx);
      // 5.0.44：缩略图旋转角度也要恢复
      await this.loadAlbumRot(ctx);
    } catch (e) {
      Log.w(TAG, '读取相册索引失败');
    }
  }

  /** 5.0.44：从 preferences 恢复缩略图旋转角度 */
  private async loadAlbumRot(ctx: common.UIAbilityContext): Promise<void> {
    try {
      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_CFG);
      const raw: Object = await store.get('albumRot', '');
      if (typeof raw === 'string') {
        const rows: string[] = (raw as string).split('\\n');
        for (let i: number = 0; i < rows.length; i++) {
          const row: string = rows[i];
          if (row.length === 0) {
            continue;
          }
          const segs: string[] = row.split('|');
          if (segs.length >= 2 && segs[0].length > 0) {
            const rot: number = Number.parseInt(segs[1], 10);
            if (!Number.isNaN(rot)) {
              this.albumRotMap.set(segs[0], rot);
            }
          }
        }
      }
    } catch (e) {
      Log.w(TAG, '读取缩略图旋转索引失败');
    }
  }
"""
    assert s.count(old2) == 1, f'loadAlbumIndex 末尾出现 {s.count(old2)} 次'
    s = s.replace(old2, new2)

    # 3) migrateThumbCache 里对 _full 兜底图设 rot=-1
    old3 = """        // uri 段留空：只补缩略图（旧索引里那个 uri 已经对不上这条消息了）
        this.albumMap.set(id, `|${newDir}/${nm}`);
        moved = moved + 1;
"""
    new3 = """        // uri 段留空：只补缩略图（旧索引里那个 uri 已经对不上这条消息了）
        this.albumMap.set(id, `|${newDir}/${nm}`);
        // 5.0.42 的 _full 兜底是原图复制，带 EXIF -> 显示层用 AUTO(-1)
        if (nm.endsWith('_full')) {
          this.albumRotMap.set(`${newDir}/${nm}`, -1);
        }
        moved = moved + 1;
"""
    assert s.count(old3) == 1, f'migrate 留空出现 {s.count(old3)} 次'
    s = s.replace(old3, new3)

    # 4) setAlbumIndex 加 rot 参数
    old4 = """  /** 记一条「已存进相册」：相册 URI + 缓存出来的缩略图路径 */
  async setAlbumIndex(id: string, uri: string, thumb: string): Promise<void> {
    this.albumLoaded = true;
    this.albumMap.set(id, `${uri}|${thumb}`);
    await this.persistAlbumIndex();
  }
"""
    new4 = """  /**
   * 记一条「已存进相册」：相册 URI + 缓存出来的缩略图路径 + 显示层补转角度。
   * @param rot 缓存缩略图需要 Image.orientation() 补转的角度：0=已物理转正，
   *            90/180/270=显示层补转，-1=原图复制兜底（带 EXIF，用 AUTO）。
   */
  async setAlbumIndex(id: string, uri: string, thumb: string, rot: number = 0): Promise<void> {
    this.albumLoaded = true;
    this.albumMap.set(id, `${uri}|${thumb}`);
    this.albumRotMap.set(thumb, rot);
    await this.persistAlbumIndex();
    await this.persistAlbumRot();
  }
"""
    assert s.count(old4) == 1, f'setAlbumIndex 出现 {s.count(old4)} 次'
    s = s.replace(old4, new4)

    # 5) persistAlbumIndex 后面加 persistAlbumRot
    old5 = """      await store.put('albumIndex', rows.join('\\n'));
      await store.flush();
    } catch (e) {
      Log.w(TAG, '保存相册索引失败');
    }
  }
"""

    new5 = """      await store.put('albumIndex', rows.join('\\n'));
      await store.flush();
    } catch (e) {
      Log.w(TAG, '保存相册索引失败');
    }
  }


  /** 5.0.44：持久化缩略图旋转角度 */
  private async persistAlbumRot(): Promise<void> {
    if (this.ctx === null) {
      return;
    }
    try {
      const store: preferences.Preferences = await preferences.getPreferences(this.ctx, PREF_CFG);
      const rows: string[] = [];
      for (const k of this.albumRotMap.keys()) {
        const v: number | undefined = this.albumRotMap.get(k);
        if (k.length > 0 && v !== undefined) {
          rows.push(`${k}|${v}`);
        }
      }
      await store.put('albumRot', rows.join('\\n'));
      await store.flush();
    } catch (e) {
      Log.w(TAG, '保存缩略图旋转索引失败');
    }
  }
"""
    assert s.count(old5) == 1, f'persistAlbumIndex 结尾出现 {s.count(old5)} 次'
    s = s.replace(old5, new5)

    return s


def patch_index(s):
    # A) 删除 mediaRot 页面 Map（保留 mediaRatio），并在 pendingRot 旁插入 imgPreviewId
    oldA = """  /**
   * 5.0.41：这张图**还需要显示层再补转多少度**（0 = 不用补）。
   *
   * 只对「我们自己 pack 出来的缓存小图」记录 —— 沙箱原图不在本表时走
   * `ImageRotateOrientation.AUTO`（Image 自己会读 EXIF，不能重复转）。
   */
  private mediaRot: Map<string, number> = new Map<string, number>();
  /** `cacheThumb()` 内部传递「这次有没有物理转成功」的中转变量（0 = 转成功，否则 = 待补转的度数） */
  private pendingRot: number = 0;
  /** 正在量尺寸的路径（防重复提交） */
  private mediaRatioBusy: Set<string> = new Set<string>();
"""
    newA = """  /** `cacheThumb()` 内部传递「这次有没有物理转成功」的中转变量（0 = 转成功，否则 = 待补转的度数） */
  private pendingRot: number = 0;
  /** 正在量尺寸的路径（防重复提交） */
  private mediaRatioBusy: Set<string> = new Set<string>();

  /** 5.0.44：预览页「存相册」时需要知道当前是哪条消息 */
  @State imgPreviewId: string = '';
"""
    assert s.count(oldA) == 1, f'pendingRot 段落出现 {s.count(oldA)} 次'
    s = s.replace(oldA, newA)
    # C) thumbOri 查 service 而不是 mediaRot
    oldC = """  /**
   * 5.0.41：这张图该用什么显示方向。
   *
   * - 表里**没有**记录 -> `AUTO`：交给 Image 按 EXIF 自己转（沙箱原图走这条）；
   * - 记录为 0 -> `UP`：缓存小图的像素**已经物理转正**了，这里强制不转，
   *   防止 pack 万一写回 EXIF 时 Image 又转一遍；
   * - 记录为 90/180/270 -> `RIGHT/DOWN/LEFT`：物理旋转没生效，显示层补一刀。
   *
   * ⚠️ 两条路互斥，`cacheThumb()` 里用「宽高有没有真的翻转」判定走哪条，
   *    绝不叠加。
   */
  private thumbOri(path: string): ImageRotateOrientation {
    const v: number | undefined = this.mediaRot.get(path);
    // undefined = 沙箱原图；-1 = 原图拷贝兜底（5.0.42，见 cacheThumb）—— 两者**都带 EXIF**，
    // 让 Image 自己读 EXIF 转，我们再显式给角度就是转两遍。
    if (v === undefined || v === -1) {
      return ImageRotateOrientation.AUTO;
    }
    if (v === 90) {
      return ImageRotateOrientation.RIGHT;
    }
    if (v === 180) {
      return ImageRotateOrientation.DOWN;
    }
    if (v === 270) {
      return ImageRotateOrientation.LEFT;
    }
    return ImageRotateOrientation.UP;
  }
"""
    newC = """  /**
   * 5.0.41：这张图该用什么显示方向。
   *
   * - 表里**没有**记录 -> `AUTO`：交给 Image 按 EXIF 自己转（沙箱原图走这条）；
   * - 记录为 0 -> `UP`：缓存小图的像素**已经物理转正**了，这里强制不转，
   *   防止 pack 万一写回 EXIF 时 Image 又转一遍；
   * - 记录为 90/180/270 -> `RIGHT/DOWN/LEFT`：物理旋转没生效，显示层补一刀。
   *
   * ⚠️ 两条路互斥，`cacheThumb()` 里用「宽高有没有真的翻转」判定走哪条，
   *    绝不叠加。
   */
  private thumbOri(path: string): ImageRotateOrientation {
    // 5.0.44：先从 service 持久化的 rot 表里查；没有才按「沙箱原图 / 旧缓存」老规则走 AUTO。
    const v: number | undefined = this.service.rotOf(path);
    // undefined = 沙箱原图；-1 = 原图拷贝兜底（5.0.42，见 cacheThumb）—— 两者**都带 EXIF**，
    // 让 Image 自己读 EXIF 转，我们再显式给角度就是转两遍。
    if (v === undefined || v === -1) {
      return ImageRotateOrientation.AUTO;
    }
    if (v === 90) {
      return ImageRotateOrientation.RIGHT;
    }
    if (v === 180) {
      return ImageRotateOrientation.DOWN;
    }
    if (v === 270) {
      return ImageRotateOrientation.LEFT;
    }
    return ImageRotateOrientation.UP;
  }
"""
    assert s.count(oldC) == 1, f'thumbOri 出现 {s.count(oldC)} 次'
    s = s.replace(oldC, newC)

    # D) cacheThumb 里 mediaRot.set 改为 service.setAlbumRot（同步设，后面 setAlbumIndex 会再持久化）
    oldD1 = """          this.mediaRatio.set(fullPath, Index.clampRatio(fw / fh));
            // -1 = 这份缓存**保留了 EXIF** —— 显示层必须 AUTO，让 Image 自己转
            this.mediaRot.set(fullPath, -1);
            this.thumbTick++;
            return fullPath;
"""
    newD1 = """          this.mediaRatio.set(fullPath, Index.clampRatio(fw / fh));
            // -1 = 这份缓存**保留了 EXIF** —— 显示层必须 AUTO，让 Image 自己转
            this.service.albumRotMap.set(fullPath, -1);
            this.thumbTick++;
            return fullPath;
"""
    assert s.count(oldD1) == 1, f'兜底 mediaRot.set 出现 {s.count(oldD1)} 次'
    s = s.replace(oldD1, newD1)

    oldD2 = """      // 缓存小图是「我们自己 pack 的、不带 EXIF」的图，Image 不会替我们转，
      // 所以这里必须明确告诉显示层还要不要补转（0 = 已物理转正，别再转）。
      this.mediaRot.set(out, this.pendingRot);
      this.pendingRot = 0;
      return out;
"""
    newD2 = """      // 缓存小图是「我们自己 pack 的、不带 EXIF」的图，Image 不会替我们转，
      // 所以这里必须明确告诉显示层还要不要补转（0 = 已物理转正，别再转）。
      // 5.0.44：把这个角度同步到 service，setAlbumIndex 会一起持久化。
      this.service.albumRotMap.set(out, this.pendingRot);
      this.pendingRot = 0;
      return out;
"""
    assert s.count(oldD2) == 1, f'末尾 mediaRot.set 出现 {s.count(oldD2)} 次'
    s = s.replace(oldD2, newD2)

    # E) autoSaveAlbumBatch 里 setAlbumIndex 传 rot
    oldE = """          const thumb: string = await this.cacheThumb(ctx, paths[i], owners[i]);
          await this.service.setAlbumIndex(owners[i], uris[i], thumb);
          const derr: string | null =
"""
    newE = """          const thumb: string = await this.cacheThumb(ctx, paths[i], owners[i]);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          await this.service.setAlbumIndex(owners[i], uris[i], thumb, rot);
          const derr: string | null =
"""
    assert s.count(oldE) == 1, f'autoSave setAlbumIndex 出现 {s.count(oldE)} 次'
    s = s.replace(oldE, newE)

    # F) saveImageToAlbum 加 id 参数，保存后 cacheThumb + setAlbumIndex
    oldF = """  private async saveImageToAlbum(path: string, name: string): Promise<void> {
    if (path.length === 0) {
      this.toast('找不到源文件');
      return;
    }
"""
    newF = """  private async saveImageToAlbum(path: string, name: string, id: string = ''): Promise<void> {
    if (path.length === 0) {
      this.toast('找不到源文件');
      return;
    }
"""
    assert s.count(oldF) == 1, f'saveImageToAlbum 签名出现 {s.count(oldF)} 次'
    s = s.replace(oldF, newF)

    oldF2 = """      const msg: string = ExportService.copyTo(path, uris[0], name);
      this.toast(msg);
      Log.i(TAG, `存相册：${msg}`);
    } catch (e) {
"""
    newF2 = """      const msg: string = ExportService.copyTo(path, uris[0], name);
      this.toast(msg);
      Log.i(TAG, `存相册：${msg}`);
      // 5.0.44：手动保存也要缓存缩略图并记相册 URI，否则沙箱原图一删就丢。
      if (msg.startsWith('已保存') && id.length > 0) {
        try {
          const thumb: string = await this.cacheThumb(ctx, path, id);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          await this.service.setAlbumIndex(id, uris[0], thumb, rot);
        } catch (x) {
          Log.w(TAG, `手动保存后缓存缩略图失败: ${path}`);
        }
      }
    } catch (e) {
"""
    assert s.count(oldF2) == 1, f'saveImageToAlbum copyTo 后出现 {s.count(oldF2)} 次'
    s = s.replace(oldF2, newF2)

    # G) 预览页顶栏按钮传 imgPreviewId
    oldG = """          Button('存相册')
            .fontSize(13)
            .height(32)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#33FFFFFF')
            .fontColor(Color.White)
            .onClick(() => this.saveImageToAlbum(this.imgPreview, this.imgPreviewName))
"""
    newG = """          Button('存相册')
            .fontSize(13)
            .height(32)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#33FFFFFF')
            .fontColor(Color.White)
            .onClick(() => this.saveImageToAlbum(this.imgPreview, this.imgPreviewName, this.imgPreviewId))
"""
    assert s.count(oldG) == 1, f'预览页存相册按钮出现 {s.count(oldG)} 次'
    s = s.replace(oldG, newG)

    # H) 预览页长按保存传 imgPreviewId
    oldH = """              LongPressGesture({ repeat: false, duration: 400 })
                .onAction(() => {
                  this.saveImageToAlbum(path, name);
                })
"""
    newH = """              LongPressGesture({ repeat: false, duration: 400 })
                .onAction(() => {
                  this.saveImageToAlbum(path, name, this.imgPreviewId);
                })
"""
    assert s.count(oldH) == 1, f'预览页长按保存出现 {s.count(oldH)} 次'
    s = s.replace(oldH, newH)

    # I) openMediaPreview 设置 imgPreviewId（再调 openMediaGallery）
    oldI = """  private openMediaPreview(path: string, name: string): void {
    this.openMediaGallery([path], [name], 0);
  }
"""
    newI = """  private openMediaPreview(path: string, name: string, id: string = ''): void {
    this.imgPreviewId = id;
    this.openMediaGallery([path], [name], 0);
  }
"""
    assert s.count(oldI) == 1, f'openMediaPreview 出现 {s.count(oldI)} 次'
    s = s.replace(oldI, newI)

    # J) openChatGallery 设置 imgPreviewId
    oldJ = """  private openChatGallery(id: string, index: number): void {
    const paths: string[] = this.mediaPathsOf(id);
    if (paths.length === 0) {
      return;
    }
    const names: string[] = [];
    for (let i = 0; i < paths.length; i++) {
      names.push(Index.baseName(paths[i]));
    }
    this.openMediaGallery(paths, names, index);
  }
"""
    newJ = """  private openChatGallery(id: string, index: number): void {
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
  }
"""
    assert s.count(oldJ) == 1, f'openChatGallery 出现 {s.count(oldJ)} 次'
    s = s.replace(oldJ, newJ)

    # K) closeMediaPreview 清空 imgPreviewId
    oldK = """  private closeMediaPreview(): void {
    // 视频先停：浮层虽然会被销毁，但显式停掉更保险（别让声音多跑半秒）
    try {
      this.videoCtl.stop();
    } catch (e) {
      // 没在播放时 stop 会抛，忽略
    }
    this.imgPreview = '';
    this.imgPreviewName = '';
    this.imgPreviewVideo = false;
    this.imgScale = 1;
    this.imgPinchBase = 1;
    this.imgOffX = 0;
    this.imgOffY = 0;
    this.galleryPaths = [];
    this.galleryNames = [];
    this.galleryIndex = 0;
  }
"""
    newK = """  private closeMediaPreview(): void {
    // 视频先停：浮层虽然会被销毁，但显式停掉更保险（别让声音多跑半秒）
    try {
      this.videoCtl.stop();
    } catch (e) {
      // 没在播放时 stop 会抛，忽略
    }
    this.imgPreview = '';
    this.imgPreviewName = '';
    this.imgPreviewId = '';
    this.imgPreviewVideo = false;
    this.imgScale = 1;
    this.imgPinchBase = 1;
    this.imgOffX = 0;
    this.imgOffY = 0;
    this.galleryPaths = [];
    this.galleryNames = [];
    this.galleryIndex = 0;
  }
"""
    assert s.count(oldK) == 1, f'closeMediaPreview 出现 {s.count(oldK)} 次'
    s = s.replace(oldK, newK)

    # L) onFileBubbleClick：没有相册 URI 但有缩略图缓存时，优先用缓存图预览而不是跳文件 tab
    oldL = """  private onFileBubbleClick(m: ChatMessage): void {
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
"""
    newL = """  private onFileBubbleClick(m: ChatMessage): void {
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
      this.openMediaPreview(ps[0], m.content, m.id);
      return;
    }
    const p: string = this.chatMediaPaths.get(m.id) ?? '';
    if (p.length > 0 && this.isMediaName(p)) {
      this.openMediaPreview(p, m.content, m.id);
      return;
    }
    // 5.0.44：旧消息沙箱原图已删、只有缓存缩略图时，点气泡用缩略图预览，
    //         而不是直接跳「文件」页（旧数据没有相册 URI 是预期行为）。
    const thumb: string = this.albumPart(m.id, 1);
    if (thumb.length > 0 && this.isMediaName(thumb)) {
      this.openMediaPreview(thumb, m.content, m.id);
      return;
    }
    this.openFileTab();
  }
"""
    assert s.count(oldL) == 1, f'onFileBubbleClick 出现 {s.count(oldL)} 次'
    s = s.replace(oldL, newL)

    # M) openMediaPreview 调用点传 m.id
    oldM1 = """    if (ps.length === 1 && this.isMediaName(ps[0])) {
      this.openMediaPreview(ps[0], m.content);
      return;
    }
    const p: string = this.chatMediaPaths.get(m.id) ?? '';
    if (p.length > 0 && this.isMediaName(p)) {
      this.openMediaPreview(p, m.content);
      return;
    }
"""
    newM1 = """    if (ps.length === 1 && this.isMediaName(ps[0])) {
      this.openMediaPreview(ps[0], m.content, m.id);
      return;
    }
    const p: string = this.chatMediaPaths.get(m.id) ?? '';
    if (p.length > 0 && this.isMediaName(p)) {
      this.openMediaPreview(p, m.content, m.id);
      return;
    }
"""
    # 注意：oldM1 跟 onFileBubbleClick 里有重复文本，但我们要替换的是 L 替换后剩下的那两处
    # 由于 L 已经替换过了，oldM1 不再存在。所以这里不需要替换。
    # 保险起见，计数校验。
    assert s.count(oldM1) == 0, f'openMediaPreview 旧调用残留 {s.count(oldM1)} 处'

    return s


def main():
    svc_path = f'{ROOT}/entry/src/main/ets/service/LanService.ets'
    idx_path = f'{ROOT}/entry/src/main/ets/pages/Index.ets'

    svc = read(svc_path)
    idx = read(idx_path)

    svc2 = patch_lan_service(svc)
    idx2 = patch_index(idx)

    write(svc_path, svc2)
    write(idx_path, idx2)
    print('PATCH 5.0.44 OK')


if __name__ == '__main__':
    main()
