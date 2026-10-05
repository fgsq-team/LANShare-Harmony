# -*- coding: utf-8 -*-
"""
LANShareV5 5.0.18 补丁

诉求（vivi 2026-10-01）：
  1. 消息页点「图片 / 视频」**不再跳文件页** —— 图片直接看大图、视频直接播放，
     两者都能长按存相册；其它类型文件才跳文件页。
  2. 点开图片后**长按**就能存相册（原来只能按顶栏按钮）。

做法：
  - `msgImagePath` → `msgMediaPath`（图片 + 视频都给路径）
  - 视频缩略图：`media.createAVImageGenerator()` 解首帧 PixelMap
    （`Image` 直接喂视频路径是空白 —— 图/视频解码器不是同一个）
  - 预览浮层按 `imgPreviewVideo` 分流：图片 = 缩放预览，视频 = 内置 `Video`
  - 图片预览的 GestureGroup 里加 `LongPressGesture` → `saveImageToAlbum`
  - `saveImageToAlbum` 支持 `PhotoType.VIDEO`，拷贝前让出一帧（视频几百 MB）

固定做法：内容锚点 + 断言 + 先把全部改动在内存里算完，最后统一落盘。
"""
import io
import os
import sys
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
F_INDEX = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets')
F_APP = os.path.join(ROOT, 'AppScope', 'app.json5')
BACKUP = os.path.join(ROOT, '.backup_v5018')

SENTINEL = '点击播放 · 长按存相册'


def read(p):
    return io.open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def sub(s, old, new, tag):
    """单处替换；先断言「新文本此前不存在」再断言「旧文本恰好一处」。"""
    assert s.count(new) == 0, '[%s] 新文本已存在' % tag
    assert s.count(old) == 1, '[%s] 期望 1 处，实际 %d' % (tag, s.count(old))
    return s.replace(old, new, 1)


def suball(s, old, new, tag, cnt):
    """多处替换（改名类），断言出现次数。"""
    assert s.count(new) == 0, '[%s] 新文本已存在' % tag
    assert s.count(old) == cnt, '[%s] 期望 %d 处，实际 %d' % (tag, cnt, s.count(old))
    return s.replace(old, new)


idx = read(F_INDEX)
app = read(F_APP)

if SENTINEL in idx:
    print('ALREADY APPLIED — 5.0.18 补丁此前已打过，跳过')
    sys.exit(0)

orig_lines = idx.count('\n')
print('imgPath 出现次数（改名依据）:', idx.count('imgPath'))

# ---------------------------------------------------------------------------
# S1  新增 import
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "import { picker, fileUri } from '@kit.CoreFileKit';\n"
    "import { window } from '@kit.ArkUI';\n"
    "import { photoAccessHelper } from '@kit.MediaLibraryKit';\n",
    "import { picker, fileUri, fileIo } from '@kit.CoreFileKit';\n"
    "import { window } from '@kit.ArkUI';\n"
    "import { photoAccessHelper } from '@kit.MediaLibraryKit';\n"
    "import { media } from '@kit.MediaKit';\n"
    "import { image } from '@kit.ImageKit';\n",
    'import',
)

# ---------------------------------------------------------------------------
# S2  文件头变更记录
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    '太常见了） |\n */\n',
    '太常见了） |\n'
    ' *\n'
    ' * ## 2026-10-01 第九轮（vivi 真机诉求，5.0.18）\n'
    ' * | 诉求 | 落法 |\n'
    ' * |---|---|\n'
    ' * | 消息页点图片/视频别再跳文件页 | `msgImagePath` → `msgMediaPath`（图片 + **视频**都给路径）；'
    '气泡里图片走 `Image`、视频走**解出来的首帧** `PixelMap`；点击按类型分流 —— '
    '图片进缩放预览、视频进 `Video` 播放器，**只有其它类型文件才 `openFileTab()`** |\n'
    ' * | ⚠️ 视频怎么当缩略图 | `Image` 喂视频路径只会得到空白（图/视频解码器不是同一个）。'
    '用 `media.createAVImageGenerator()` + `fdSrc` + `fetchFrameByTime(0, AV_IMAGE_QUERY_CLOSEST_SYNC)` '
    '解出首帧 `PixelMap`。⚠️ fd **必须活到 fetch 返回**；`release()` 要 await |\n'
    ' * | 点开图片后长按就能存相册 | 图片预览的 `GestureGroup` 里加 `LongPressGesture`（与捏合/拖动/双击并列，'
    'Parallel 模式下不打架）。存相册本身扩到**视频**：`PhotoType.VIDEO`；'
    '⚠️ 视频几百 MB，`copyTo` 是同步逐块读写，先弹「正在保存」并**让出一帧**再拷，否则连提示都画不出来 |\n'
    ' */\n',
    'header-notes',
)

# ---------------------------------------------------------------------------
# S3  新增字段
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "  private clickMuteUntil: number = 0;\n",
    "  private clickMuteUntil: number = 0;\n"
    "\n"
    "  // ---------------- 全屏预览：视频分支 ----------------\n"
    "  /**\n"
    "   * 全屏预览打开的是不是**视频**。\n"
    "   * `imgPreview` 只存了一个路径 —— 图片走「缩放预览」、视频走「播放器」，\n"
    "   * 靠这个标记在渲染时分流（同一个浮层，两套内容）。\n"
    "   */\n"
    "  @State imgPreviewVideo: boolean = false;\n"
    "  /** 视频播放控制器（关闭预览时显式 stop，别让声音跟着页面跑） */\n"
    "  private videoCtl: VideoController = new VideoController();\n"
    "\n"
    "  // ---------------- 视频首帧缩略图 ----------------\n"
    "  /**\n"
    "   * 视频路径 → 首帧缩略图（PixelMap）。\n"
    "   *\n"
    "   * ⚠️ 视频**必须**先解码出首帧才能当缩略图：把视频路径直接喂给 `Image`\n"
    "   *    只会得到一块空白（图/视频的解码器根本不是一个）。\n"
    "   * ⚠️ 用普通字段而不是 `@State`：ArkUI 观察不到 `Map.set()` 这种「内容变化」，\n"
    "   *    配下面的 `videoThumbTick` 计数器把重绘踢起来。\n"
    "   */\n"
    "  private videoThumbs: Map<string, image.PixelMap> = new Map<string, image.PixelMap>();\n"
    "  /** 正在解码的路径，防同一条视频被重复提交 */\n"
    "  private videoThumbBusy: Set<string> = new Set<string>();\n"
    "  /** 每解出一张缩略图就 +1；@State 变化 → 重新 build → 缩略图出现 */\n"
    "  @State videoThumbTick: number = 0;\n",
    'fields',
)

# ---------------------------------------------------------------------------
# S4  新增 isVideoName / isMediaName
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "    return ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'gif'\n"
    "      || ext === 'webp' || ext === 'bmp' || ext === 'heic' || ext === 'heif'\n"
    "      || ext === 'avif' || ext === 'ico' || ext === 'tif' || ext === 'tiff';\n"
    "  }\n",
    "    return ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'gif'\n"
    "      || ext === 'webp' || ext === 'bmp' || ext === 'heic' || ext === 'heif'\n"
    "      || ext === 'avif' || ext === 'ico' || ext === 'tif' || ext === 'tiff';\n"
    "  }\n"
    "\n"
    "  /**\n"
    "   * 文件名是不是**视频**（按扩展名判断，理由同 `isImageName`）。\n"
    "   * 这张表管两件事：① 要不要解首帧缩略图；② 点击时进播放器还是进图片预览。\n"
    "   * 解不出首帧（编码不支持）不影响播放 —— 缩略图那步失败只是留个灰色占位。\n"
    "   */\n"
    "  private isVideoName(name: string): boolean {\n"
    "    const dot: number = name.lastIndexOf('.');\n"
    "    if (dot < 0) {\n"
    "      return false;\n"
    "    }\n"
    "    const ext: string = name.substring(dot + 1).toLowerCase();\n"
    "    return ext === 'mp4' || ext === 'mov' || ext === 'mkv' || ext === 'webm'\n"
    "      || ext === 'avi' || ext === '3gp' || ext === 'm4v' || ext === 'ts'\n"
    "      || ext === 'flv' || ext === 'wmv' || ext === 'rmvb' || ext === 'mpg'\n"
    "      || ext === 'mpeg' || ext === 'ogv';\n"
    "  }\n"
    "\n"
    "  /** 图片 or 视频 —— 「能在 App 内直接打开」的那一类 */\n"
    "  private isMediaName(name: string): boolean {\n"
    "    return this.isImageName(name) || this.isVideoName(name);\n"
    "  }\n",
    'is-video-name',
)

# ---------------------------------------------------------------------------
# S5  openImagePreview → openMediaPreview（3 处）+ 置视频标记 + 注释
# ---------------------------------------------------------------------------
idx = suball(idx, 'openImagePreview', 'openMediaPreview', 'rename-open',
             idx.count('openImagePreview'))
idx = sub(
    idx,
    "  private openMediaPreview(path: string, name: string): void {\n"
    "    this.imgPreview = path;\n"
    "    this.imgPreviewName = name;\n",
    "  private openMediaPreview(path: string, name: string): void {\n"
    "    this.imgPreview = path;\n"
    "    this.imgPreviewName = name;\n"
    "    // 一个路径，两套渲染 —— 靠这个标记分流\n"
    "    this.imgPreviewVideo = this.isVideoName(name);\n",
    'open-mark-video',
)
idx = sub(
    idx,
    "  /**\n"
    "   * 点开一张图：进全屏预览。\n"
    "   *\n"
    "   * ⚠️ 入参是 `(path, name)` 而不是 `ReceivedFile`：消息页的气泡手里只有一个路径，\n"
    "   *    造不出 `ReceivedFile`（那是「文件」页列表的模型）。\n"
    "   */\n",
    "  /**\n"
    "   * 点开一个**媒体**文件（图片 / 视频）：进全屏预览。\n"
    "   *\n"
    "   * ⚠️ 入参是 `(path, name)` 而不是 `ReceivedFile`：消息页的气泡手里只有一个路径，\n"
    "   *    造不出 `ReceivedFile`（那是「文件」页列表的模型）。\n"
    "   * ⚠️ 由**扩展名**决定进哪套渲染（`imgPreviewVideo`），不靠调用方传类型 ——\n"
    "   *    消息页和文件页两个调用点都不用改。\n"
    "   */\n",
    'open-comment',
)

# ---------------------------------------------------------------------------
# S6  closeImagePreview → closeMediaPreview（3 处）+ 复位标记 + 停播放
# ---------------------------------------------------------------------------
idx = suball(idx, 'closeImagePreview', 'closeMediaPreview', 'rename-close',
             idx.count('closeImagePreview'))
idx = sub(
    idx,
    "  private closeMediaPreview(): void {\n"
    "    this.imgPreview = '';\n"
    "    this.imgPreviewName = '';\n",
    "  private closeMediaPreview(): void {\n"
    "    // 视频先停：浮层虽然会被销毁，但显式停掉更保险（别让声音多跑半秒）\n"
    "    try {\n"
    "      this.videoCtl.stop();\n"
    "    } catch (e) {\n"
    "      // 没在播放时 stop 会抛，忽略\n"
    "    }\n"
    "    this.imgPreview = '';\n"
    "    this.imgPreviewName = '';\n"
    "    this.imgPreviewVideo = false;\n",
    'close-stop',
)

# ---------------------------------------------------------------------------
# S7  saveImageToAlbum 支持视频 + 拷贝前让帧
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "    const title: string = Index.safeAlbumTitle(dot > 0 ? name.substring(0, dot) : name);\n"
    "    const ext: string = dot > 0 ? name.substring(dot + 1).toLowerCase() : 'jpg';\n",
    "    const isVideo: boolean = this.isVideoName(name);\n"
    "    const title: string = Index.safeAlbumTitle(dot > 0 ? name.substring(0, dot) : name);\n"
    "    const ext: string = dot > 0 ? name.substring(dot + 1).toLowerCase() : (isVideo ? 'mp4' : 'jpg');\n",
    'album-ext',
)
idx = sub(
    idx,
    "        photoType: photoAccessHelper.PhotoType.IMAGE\n",
    "        photoType: isVideo ? photoAccessHelper.PhotoType.VIDEO : photoAccessHelper.PhotoType.IMAGE\n",
    'album-type',
)
idx = sub(
    idx,
    "      const msg: string = ExportService.copyTo(path, uris[0], name);\n"
    "      this.toast(msg);\n",
    "      // ⚠️ 视频动辄几百 MB，`copyTo` 是**同步**逐块读写 —— 直接调用会把主线程\n"
    "      //    按住好几秒，连「正在保存」这句 toast 都画不出来（同一帧内就被阻塞了）。\n"
    "      //    先弹提示、让出一帧，再开始拷。\n"
    "      this.toast(isVideo ? '正在保存视频…' : '正在保存…');\n"
    "      await Index.yieldOnce();\n"
    "      const msg: string = ExportService.copyTo(path, uris[0], name);\n"
    "      this.toast(msg);\n",
    'album-yield',
)

# ---------------------------------------------------------------------------
# S8  新增 yieldOnce / 视频缩略图四件套（插在 safeAlbumTitle 之后）
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "    if (out.length > 200) {\n"
    "      out = out.substring(0, 200);\n"
    "    }\n"
    "    return out;\n"
    "  }\n"
    "\n"
    "  /**\n"
    "   * 全屏图片预览。\n",
    "    if (out.length > 200) {\n"
    "      out = out.substring(0, 200);\n"
    "    }\n"
    "    return out;\n"
    "  }\n"
    "\n"
    "  /**\n"
    "   * 让出一帧，给 UI 一次上屏的机会。\n"
    "   *\n"
    "   * ⚠️ 用途只有一个：`ExportService.copyTo` 是**同步**拷贝（见其实现），\n"
    "   *    视频几百 MB 会按住主线程数秒。先 toast 再让一帧，用户至少看得到「正在保存」。\n"
    "   */\n"
    "  private static async yieldOnce(): Promise<void> {\n"
    "    await new Promise<void>((resolve: (value: void) => void) => {\n"
    "      setTimeout(() => {\n"
    "        resolve();\n"
    "      }, 30);\n"
    "    });\n"
    "  }\n"
    "\n"
    "  /**\n"
    "   * 这条路径的首帧解出来了没有。\n"
    "   *\n"
    "   * ⚠️ 拆成「查询 + 取值」两个方法是为了**建立 @State 依赖**：\n"
    "   *    `videoThumbs` 是普通 Map，在渲染里读它不会让组件重绘；\n"
    "   *    这里读一下 `videoThumbTick`，解码完成（tick +1）时调用方就会重新执行。\n"
    "   */\n"
    "  private hasVideoThumb(path: string): boolean {\n"
    "    if (this.videoThumbTick < 0) {\n"
    "      return false;\n"
    "    }\n"
    "    return this.videoThumbs.has(path);\n"
    "  }\n"
    "\n"
    "  /**\n"
    "   * 取首帧。**调用前必须先用 `hasVideoThumb()` 判过。**\n"
    "   *\n"
    "   * ⚠️ 返回类型带 `undefined` 是因为 `Map.get()` 本来就能返回它 ——\n"
    "   *    渲染处用 `as image.PixelMap` 收敛（ArkTS 不做跨方法调用的类型收窄，\n"
    "   *    而 `Image()` 又不接受 `undefined`）。\n"
    "   */\n"
    "  private videoThumbOf(path: string): image.PixelMap | undefined {\n"
    "    return this.videoThumbs.get(path);\n"
    "  }\n"
    "\n"
    "  /**\n"
    "   * 预热一批视频的首帧缩略图。\n"
    "   *\n"
    "   * ⚠️ 为什么不在 `@Builder` 里按需触发：`@Builder` 每次重绘都会重新执行，\n"
    "   *    在里面启动异步解码 = 每次重绘都提交一次（虽然有 busy 表挡着，但那是治标）。\n"
    "   *    把副作用放在**数据刷新**这条路径上（`refreshReceived` 末尾），渲染就保持纯粹。\n"
    "   */\n"
    "  private prewarmVideoThumbs(list: ReceivedFile[]): void {\n"
    "    for (let i = 0; i < list.length; i++) {\n"
    "      if (this.isVideoName(list[i].name)) {\n"
    "        this.ensureVideoThumb(list[i].path);\n"
    "      }\n"
    "    }\n"
    "    // 消息里那条 `kind='file'` 记录带的是**对端发来的原名**，落盘名可能被加了\n"
    "    // 重名后缀 —— 路径走 `recvIndex` 反查（与气泡显示缩略图用的是同一张表）。\n"
    "    for (let i = 0; i < this.chat.length; i++) {\n"
    "      const m: ChatMessage = this.chat[i];\n"
    "      if (m.kind === 'file' && m.incoming && this.isVideoName(m.content)) {\n"
    "        const p: string | undefined = this.recvIndex.get(m.content);\n"
    "        if (p !== undefined) {\n"
    "          this.ensureVideoThumb(p);\n"
    "        }\n"
    "      }\n"
    "    }\n"
    "  }\n"
    "\n"
    "  /** 提交一次解码（已解过 / 正在解 / 空路径直接跳过） */\n"
    "  private ensureVideoThumb(path: string): void {\n"
    "    if (path.length === 0 || this.videoThumbBusy.has(path) || this.videoThumbs.has(path)) {\n"
    "      return;\n"
    "    }\n"
    "    this.videoThumbBusy.add(path);\n"
    "    this.decodeVideoThumb(path).catch(() => {\n"
    "      // 内部已有 try/catch，这里只兜底，避免未处理的 Promise\n"
    "    });\n"
    "  }\n"
    "\n"
    "  /**\n"
    "   * 解一条视频的首帧。\n"
    "   *\n"
    "   * ⚠️ 三个必须守住的点：\n"
    "   *    ① fd **要活到 `fetchFrameByTime` 返回**（提前 close 直接解不出来）；\n"
    "   *    ② `release()` 是 Promise，要 await；\n"
    "   *    ③ 取「离 0 最近的关键帧」而不是第 0 帧 —— 不少视频开头是纯黑，\n"
    "   *       关键帧才是真正有画面的那一帧。\n"
    "   */\n"
    "  private async decodeVideoThumb(path: string): Promise<void> {\n"
    "    let f: fileIo.File | null = null;\n"
    "    let gen: media.AVImageGenerator | null = null;\n"
    "    try {\n"
    "      f = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);\n"
    "      gen = await media.createAVImageGenerator();\n"
    "      const desc: media.AVFileDescriptor = { fd: f.fd };\n"
    "      gen.fdSrc = desc;\n"
    "      const pp: media.PixelMapParams = { width: 192, height: 192 };\n"
    "      const pm: image.PixelMap = await gen.fetchFrameByTime(\n"
    "        0, media.AVImageQueryOptions.AV_IMAGE_QUERY_CLOSEST_SYNC, pp);\n"
    "      this.videoThumbs.set(path, pm);\n"
    "      // @State 计数器自增 —— Map 本身不是可观察对象，靠它把重绘踢起来\n"
    "      this.videoThumbTick++;\n"
    "    } catch (e) {\n"
    "      const err: BusinessError = e as BusinessError;\n"
    "      Log.w(TAG, `解视频首帧失败: ${err.code} ${err.message} ${path}`);\n"
    "    } finally {\n"
    "      this.videoThumbBusy.delete(path);\n"
    "      if (gen !== null) {\n"
    "        try {\n"
    "          await gen.release();\n"
    "        } catch (e) {\n"
    "          // 忽略\n"
    "        }\n"
    "      }\n"
    "      if (f !== null) {\n"
    "        try {\n"
    "          fileIo.closeSync(f);\n"
    "        } catch (e) {\n"
    "          // 忽略\n"
    "        }\n"
    "      }\n"
    "    }\n"
    "  }\n"
    "\n"
    "  /**\n"
    "   * 全屏媒体预览（图片 = 缩放预览；视频 = 播放器）。\n",
    'video-thumb-helpers',
)

# ---------------------------------------------------------------------------
# S9  预览浮层：视频分支 + 图片长按
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "      Stack({ alignContent: Alignment.Top }) {\n"
    "        Image(this.imageUri(this.imgPreview))\n"
    "          .width('100%')\n"
    "          .height('100%')\n"
    "          .objectFit(ImageFit.Contain)\n"
    "          .scale({ x: this.imgScale, y: this.imgScale })\n",
    "      Stack({ alignContent: Alignment.Top }) {\n"
    "        if (this.imgPreviewVideo) {\n"
    "          // 视频：交给 ArkUI 内置 `Video`（同进程读自己的沙箱，不需要任何权限）。\n"
    "          // ⚠️ `src` 必须是 `fileUri.getUriFromPath()` 的沙箱 URI\n"
    "          //    （`file://<bundleName>/<沙箱路径>`）—— 官方声明里明确支持这一形态，\n"
    "          //    手拼的 `'file://' + path` 播不出来（同 `Image` 那个坑）。\n"
    "          Video({ src: this.imageUri(this.imgPreview), controller: this.videoCtl })\n"
    "            .width('100%')\n"
    "            .height('100%')\n"
    "            .objectFit(ImageFit.Contain)\n"
    "            .controls(true)\n"
    "            .autoPlay(true)\n"
    "            .loop(false)\n"
    "            .onError(() => {\n"
    "              this.toast('无法播放这个视频（编码或封装格式不支持）');\n"
    "            })\n"
    "        } else {\n"
    "        Image(this.imageUri(this.imgPreview))\n"
    "          .width('100%')\n"
    "          .height('100%')\n"
    "          .objectFit(ImageFit.Contain)\n"
    "          .scale({ x: this.imgScale, y: this.imgScale })\n",
    'preview-video',
)

idx = sub(
    idx,
    "              // 双击：>1x 复位，=1x 放大到 2.5x（看细节不用两根手指）\n"
    "              TapGesture({ count: 2 })\n"
    "                .onAction(() => {\n"
    "                  if (this.imgScale > 1) {\n"
    "                    this.imgScale = 1;\n"
    "                    this.imgPinchBase = 1;\n"
    "                    this.imgOffX = 0;\n"
    "                    this.imgOffY = 0;\n"
    "                  } else {\n"
    "                    this.imgScale = 2.5;\n"
    "                    this.imgPinchBase = 2.5;\n"
    "                  }\n"
    "                })\n"
    "            )\n"
    "          )\n"
    "\n"
    "        // 顶栏：文件名 + 关闭。文件名占满剩余宽度，放不下就省略号\n",
    "              // 双击：>1x 复位，=1x 放大到 2.5x（看细节不用两根手指）\n"
    "              TapGesture({ count: 2 })\n"
    "                .onAction(() => {\n"
    "                  if (this.imgScale > 1) {\n"
    "                    this.imgScale = 1;\n"
    "                    this.imgPinchBase = 1;\n"
    "                    this.imgOffX = 0;\n"
    "                    this.imgOffY = 0;\n"
    "                  } else {\n"
    "                    this.imgScale = 2.5;\n"
    "                    this.imgPinchBase = 2.5;\n"
    "                  }\n"
    "                }),\n"
    "              // 长按存相册（vivi 2026-10-01：「点开图片后长按就能选择保存到相册」）。\n"
    "              // 与捏合/拖动/双击并列在 Parallel 组里：长按时手指不动，\n"
    "              // PanGesture 的 distance:6 不会触发，互不打架。\n"
    "              LongPressGesture({ repeat: false, duration: 400 })\n"
    "                .onAction(() => {\n"
    "                  this.saveImageToAlbum(this.imgPreview, this.imgPreviewName);\n"
    "                })\n"
    "            )\n"
    "          )\n"
    "        }\n"
    "\n"
    "        // 顶栏：文件名 + 关闭。文件名占满剩余宽度，放不下就省略号\n",
    'preview-longpress',
)

# ---------------------------------------------------------------------------
# S10  chatFileBubble：改参数名 + 分图片/视频两路 + 文案 + 点击
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "        this.chatFileBubble(m, this.msgImagePath(m))\n",
    "        this.chatFileBubble(m, this.msgMediaPath(m))\n",
    'bubble-call',
)
n_imgpath = idx.count('imgPath')
assert n_imgpath >= 8, 'imgPath 只有 %d 处，与预期不符' % n_imgpath
idx = suball(idx, 'imgPath', 'mediaPath', 'rename-imgpath', n_imgpath)

idx = sub(
    idx,
    "      if (mediaPath.length > 0) {\n"
    "        // ⚠️ `.sourceSize()` 必须给：不压解码尺寸的话，聊天记录里每张图都会把\n"
    "        //    **整张原图**解进内存，200 条上限 = 几百 MB（同文件页的坑）。\n"
    "        Stack() {\n"
    "          Text('图片')\n"
    "            .fontSize(11)\n"
    "            .fontColor('#AAAAAA')\n"
    "          Image(this.imageUri(mediaPath))\n"
    "            .width(128)\n"
    "            .height(128)\n"
    "            .objectFit(ImageFit.Cover)\n"
    "            .sourceSize({ width: 192, height: 192 })\n"
    "        }\n",
    "      if (mediaPath.length > 0) {\n"
    "        // ⚠️ `.sourceSize()` 必须给：不压解码尺寸的话，聊天记录里每张图都会把\n"
    "        //    **整张原图**解进内存，200 条上限 = 几百 MB（同文件页的坑）。\n"
    "        Stack() {\n"
    "          if (this.isVideoName(m.content)) {\n"
    "            // 视频：首帧缩略图（`AVImageGenerator` 解出来的 PixelMap）。\n"
    "            // 还没解出来 / 解码失败 → 停在灰色占位，不显示空框。\n"
    "            Text('视频')\n"
    "              .fontSize(11)\n"
    "              .fontColor('#AAAAAA')\n"
    "            if (this.hasVideoThumb(mediaPath)) {\n"
    "              Image(this.videoThumbOf(mediaPath) as image.PixelMap)\n"
    "                .width(128)\n"
    "                .height(128)\n"
    "                .objectFit(ImageFit.Cover)\n"
    "            }\n"
    "            // 播放角标：盖在图上，一眼区分「图」和「视频」\n"
    "            Text('▶')\n"
    "              .fontSize(30)\n"
    "              .fontColor('#FFFFFF')\n"
    "          } else {\n"
    "            Text('图片')\n"
    "              .fontSize(11)\n"
    "              .fontColor('#AAAAAA')\n"
    "            Image(this.imageUri(mediaPath))\n"
    "              .width(128)\n"
    "              .height(128)\n"
    "              .objectFit(ImageFit.Cover)\n"
    "              .sourceSize({ width: 192, height: 192 })\n"
    "          }\n"
    "        }\n",
    'bubble-thumb',
)

idx = sub(
    idx,
    "        Text(mediaPath.length > 0 ? '点击看图 · 长按存相册' : '点击查看 ›')\n",
    "        Text(mediaPath.length === 0\n"
    "          ? '点击查看 ›'\n"
    "          : (this.isVideoName(m.content) ? '点击播放 · 长按存相册' : '点击看图 · 长按存相册'))\n",
    'bubble-hint',
)

# ---------------------------------------------------------------------------
# S11  消息页 / 文件页 ForEach key 带上 tick（解码完成后刷新该行）
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "          }, (m: ChatMessage) => m.id)\n",
    "            // ⚠️ key 带上 `videoThumbTick`：视频首帧是**异步**解出来的，\n"
    "            //    key 不变的话 ForEach 会复用旧行、缩略图永远不出现。\n"
    "            //    List 是懒加载的，只重建可见那几行，代价可忽略。\n"
    "          }, (m: ChatMessage) => `${m.id}|${this.videoThumbTick}`)\n",
    'chat-key',
)
idx = sub(
    idx,
    "          }, (f: ReceivedFile) => `${f.path}|${f.size}|${f.time}|${this.isFileSelected(f.path) ? 1 : 0}`)\n",
    "          }, (f: ReceivedFile) => `${f.path}|${f.size}|${f.time}|${this.isFileSelected(f.path) ? 1 : 0}|${this.videoThumbTick}`)\n",
    'file-key',
)

# ---------------------------------------------------------------------------
# S12  文件页：缩略图支持视频 + 点击支持视频
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "                } else if (this.isImageName(f.name)) {\n"
    "                  // 普通态：图片点一下进全屏预览；其它类型不做任何事（避免误触）\n"
    "                  this.openMediaPreview(f.path, f.name);\n",
    "                } else if (this.isMediaName(f.name)) {\n"
    "                  // 普通态：图片/视频点一下进全屏预览（视频走播放器）；\n"
    "                  // 其它类型不做任何事（避免误触）\n"
    "                  this.openMediaPreview(f.path, f.name);\n",
    'file-click',
)

idx = sub(
    idx,
    "                if (this.isImageName(f.name)) {\n"
    "                  Stack() {\n"
    "                    Text('图片')\n"
    "                      .fontSize(11)\n"
    "                      .fontColor('#AAAAAA')\n"
    "                    Image(this.imageUri(f.path))\n"
    "                      .width(48)\n"
    "                      .height(48)\n"
    "                      .objectFit(ImageFit.Cover)\n"
    "                      .sourceSize({ width: 96, height: 96 })\n"
    "                  }\n",
    "                if (this.isMediaName(f.name)) {\n"
    "                  Stack() {\n"
    "                    if (this.isVideoName(f.name)) {\n"
    "                      // 视频：首帧 PixelMap（异步解，解完靠 `videoThumbTick` 刷新）\n"
    "                      Text('视频')\n"
    "                        .fontSize(11)\n"
    "                        .fontColor('#AAAAAA')\n"
    "                      if (this.hasVideoThumb(f.path)) {\n"
    "                        Image(this.videoThumbOf(f.path) as image.PixelMap)\n"
    "                          .width(48)\n"
    "                          .height(48)\n"
    "                          .objectFit(ImageFit.Cover)\n"
    "                      }\n"
    "                      Text('▶')\n"
    "                        .fontSize(16)\n"
    "                        .fontColor('#FFFFFF')\n"
    "                    } else {\n"
    "                      Text('图片')\n"
    "                        .fontSize(11)\n"
    "                        .fontColor('#AAAAAA')\n"
    "                      Image(this.imageUri(f.path))\n"
    "                        .width(48)\n"
    "                        .height(48)\n"
    "                        .objectFit(ImageFit.Cover)\n"
    "                        .sourceSize({ width: 96, height: 96 })\n"
    "                    }\n"
    "                  }\n",
    'file-thumb',
)

# ---------------------------------------------------------------------------
# S13  refreshReceived 末尾预热
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "    // 消息页的图片缩略图靠它把「文件名」翻回「沙箱路径」\n"
    "    this.rebuildRecvIndex(list);\n",
    "    // 消息页的图片缩略图靠它把「文件名」翻回「沙箱路径」\n"
    "    this.rebuildRecvIndex(list);\n"
    "    // 视频首帧要解码才有（`Image` 直接喂视频路径永远是空白）—— 异步预热一遍。\n"
    "    // 内部有「已解过 / 正在解」两张表挡着，重复调用零成本。\n"
    "    this.prewarmVideoThumbs(list);\n",
    'prewarm-call',
)

# ---------------------------------------------------------------------------
# S14  msgImagePath → msgMediaPath
# ---------------------------------------------------------------------------
idx = sub(
    idx,
    "  /**\n"
    "   * 一条消息对应的沙箱图片路径；不是「收到的图片」或查不到 → 返回空串。\n"
    "   * 空串的语义是「不显示缩略图，也不给点开 / 长按的入口」。\n"
    "   */\n"
    "  private msgImagePath(m: ChatMessage): string {\n"
    "    if (m.kind !== 'file' || !m.incoming || !this.isImageName(m.content)) {\n"
    "      return '';\n"
    "    }\n",
    "  /**\n"
    "   * 一条消息对应的沙箱**媒体**路径（图片或视频）；不是「收到的媒体文件」\n"
    "   * 或查不到 → 返回空串。\n"
    "   *\n"
    "   * ⚠️ 空串的语义 = 「点了跳文件页」的那一类：不显示缩略图、不播、不给长按入口。\n"
    "   *    所以「其它类型文件才跳文件页」这条需求，就落在这一句判断上。\n"
    "   */\n"
    "  private msgMediaPath(m: ChatMessage): string {\n"
    "    if (m.kind !== 'file' || !m.incoming || !this.isMediaName(m.content)) {\n"
    "      return '';\n"
    "    }\n",
    'msg-media-path',
)

# ---------------------------------------------------------------------------
# S15  app.json5 版本号
# ---------------------------------------------------------------------------
app = sub(app, '"versionCode": 5000017', '"versionCode": 5000018', 'ver-code')
app = sub(app, '"versionName": "5.0.17"', '"versionName": "5.0.18"', 'ver-name')

# ---------------------------------------------------------------------------
# 自检（结构性断言，不写死易漂移的计数）
# ---------------------------------------------------------------------------
must_exist = [
    'isVideoName', 'isMediaName', 'hasVideoThumb', 'videoThumbOf',
    'decodeVideoThumb', 'ensureVideoThumb', 'prewarmVideoThumbs', 'yieldOnce',
    'imgPreviewVideo', 'videoCtl', 'msgMediaPath', 'PhotoType.VIDEO',
    "chatFileBubble(m: ChatMessage, mediaPath: string)",
    "点击播放 · 长按存相册", "正在保存视频…",
]
for k in must_exist:
    got = idx.count(k)
    print('  %-48s %d' % (k, got))
    assert got >= 1, '[selfcheck] 缺少 %s' % k

must_gone = ['openImagePreview', 'closeImagePreview', 'imgPath', 'this.msgImagePath(',
             'private msgImagePath(']
for k in must_gone:
    assert idx.count(k) == 0, '[selfcheck] %s 还有 %d 处残留' % (k, idx.count(k))
# 变更记录里会保留一处「`msgImagePath` → `msgMediaPath`」的对照，所以只允许 1 处
assert idx.count('msgImagePath') <= 1, '[selfcheck] msgImagePath 残留过多'

assert idx.count('videoThumbOf(mediaPath) as image.PixelMap') == 1, '消息页取值处缺失'
assert idx.count('videoThumbOf(f.path) as image.PixelMap') == 1, '文件页取值处缺失'
print('  isVideoName(name) 调用点:', idx.count('isVideoName(name)'))
assert idx.count("isVideoName(name)") >= 2, 'openMediaPreview / saveImageToAlbum 都要判视频'
assert idx.count('{') == idx.count('}'), '花括号不平：%d vs %d' % (idx.count('{'), idx.count('}'))
# 圆括号本来就「不平」：注释里有两处落单的半角 ')'（原文件 1507 vs 1509），
# 所以只校验**差值不变**，而不是要求相等。
assert idx.count(')') - idx.count('(') == 2, \
    '圆括号差值变了：%d vs %d' % (idx.count('('), idx.count(')'))

if not os.path.isdir(BACKUP):
    os.makedirs(BACKUP)
shutil.copyfile(F_INDEX, os.path.join(BACKUP, 'Index.ets'))
shutil.copyfile(F_APP, os.path.join(BACKUP, 'app.json5'))

write(F_INDEX, idx)
write(F_APP, app)

print('OK - 5.0.18 补丁已应用')
print('  Index.ets 行数: %d -> %d' % (orig_lines, idx.count('\n')))
print('  备份: %s' % BACKUP)
