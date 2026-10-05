# -*- coding: utf-8 -*-
"""
5.0.32 补丁：消息页去内嵌缩略图 + 文件页媒体宫格
- 消息页气泡只显示文件名，点击跳「文件」页（不再内嵌缩略图，避免变形+卡顿）
- 文件页把图片/视频抽成缩略图宫格（MediaTile 滑到才解视频首帧，模块级缓存去重）
- 其它文件仍一行一个（沿用旧列表）
- refreshReceived 不再「刷新就同步算全部」（prewarmVideoThumbs / ensureMediaRatio 全量循环）→ 砍掉卡顿根因
幂等：检测特征串，已打过直接跳过。
"""
import io, os, sys

IDX = r"E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets"
APP = r"E:\lanshare-harmony\LANShareV5\AppScope\app.json5"

SENTINEL = "5.0.32：媒体拆出来走宫格"

def read(p):
    return io.open(p, encoding="utf-8", newline="").read()

def write(p, s):
    io.open(p, "w", encoding="utf-8", newline="").write(s)

def apply(src, edits):
    """edits: list of (old, new, label). 每个 old 必须恰好出现一次。"""
    for old, new, label in edits:
        c = src.count(old)
        assert c == 1, f"[{label}] 锚点出现 {c} 次（必须=1）:\n{old[:80]}"
        src = src.replace(old, new)
    return src

# ---------------- Index.ets 编辑 ----------------
edits = []

# A. 新增 mediaItems / fileItems @State
edits.append((
    "  @State receivedFiles: ReceivedFile[] = [];\n"
    "  /** 当前页签：0=共享 1=消息 2=日志。⚠️ 不能叫 tabIndex —— 与 CustomComponent 基类的同名属性冲突 */\n"
    "  @State curTab: number = 0;",
    "  @State receivedFiles: ReceivedFile[] = [];\n"
    "  /** 文件页：图片/视频（走缩略图宫格）；与 receivedFiles 同步刷新 */\n"
    "  @State mediaItems: ReceivedFile[] = [];\n"
    "  /** 文件页：其它类型（一行一个，沿用旧列表） */\n"
    "  @State fileItems: ReceivedFile[] = [];\n"
    "  /** 当前页签：0=共享 1=消息 2=日志。⚠️ 不能叫 tabIndex —— 与 CustomComponent 基类的同名属性冲突 */\n"
    "  @State curTab: number = 0;",
    "A-state"
))

# B. refreshReceived：去掉预热 + 量比例，拆媒体/文件
edits.append((
    "    // 消息页的图片缩略图靠它把「文件名」翻回「沙箱路径」\n"
    "    this.rebuildRecvIndex(list);\n"
    "    // 视频首帧要解码才有（`Image` 直接喂视频路径永远是空白）—— 异步预热一遍。\n"
    "    // 内部有「已解过 / 正在解」两张表挡着，重复调用零成本。\n"
    "    this.prewarmVideoThumbs(list);\n"
    "    // 5.0.31：缩略图按原图比例出框，先把比例量好（同步读头信息，不解码整图）\n"
    "    for (let i = 0; i < list.length; i++) {\n"
    "      if (this.isMediaName(list[i].name)) {\n"
    "        this.ensureMediaRatio(list[i].path);\n"
    "      }\n"
    "    }\n"
    "    // 消息气泡缩略图依赖「文件名->沙箱路径」反查；文件一变就重算（见 syncChatMediaPaths）\n"
    "    this.syncChatMediaPaths();",
    "    // 消息页的图片缩略图靠它把「文件名」翻回「沙箱路径」（保留：气泡长按存图仍要用）\n"
    "    this.rebuildRecvIndex(list);\n"
    "    // 5.0.32：媒体拆出来走宫格、其它走列表。⚠️ **不再**预热视频首帧 / 量图片比例 ——\n"
    "    //   那两套都是「刷新就把全部文件同步算一遍」，文件一多主线程被卡住（vivi 实测卡顿）。\n"
    "    //   视频首帧改为**宫格瓦片滑到才解**（见 MediaTile.aboutToAppear，模块级缓存去重），\n"
    "    //   图片交给 `Image(uri)` 框架按需解码，都不在主路径上。\n"
    "    this.mediaItems = list.filter((f: ReceivedFile) => this.isMediaName(f.name));\n"
    "    this.fileItems = list.filter((f: ReceivedFile) => !this.isMediaName(f.name));\n"
    "    // 气泡长按存图依赖「文件名->沙箱路径」反查；文件一变就重算（见 syncChatMediaPaths）\n"
    "    this.syncChatMediaPaths();",
    "B-refresh"
))

# C. syncChatMediaPaths：去掉 ensureMediaRatio 全量量比例（性能）
edits.append((
    "      // 缩放框要按真实比例出，先把比例量出来（同步读头信息，不解码）\n"
    "      if (p.length > 0) {\n"
    "        this.ensureMediaRatio(p);\n"
    "      }\n"
    "      for (let k = 0; k < paths.length; k++) {\n"
    "        this.ensureMediaRatio(paths[k]);\n"
    "      }\n"
    "      sig += `${msg.id}:${paths.join(',')};`;",
    "      // 5.0.32：不再同步量图片比例（消息页不再内嵌缩略图，省掉这步同步开销）\n"
    "      sig += `${msg.id}:${paths.join(',')};`;",
    "C-syncmedia"
))

# D1. chatFileBubble：去掉内嵌缩略图分支
edits.append((
    "      if (this.mediaCountOf(m.id) > 0) {\n"
    "        // 5.0.31：对端一次发来 N 张 —— **只出第一张**缩略图 + 「共 N 张」角标，\n"
    "        // 点开进画廊左右滑。一张一个气泡会把整屏刷满，这也是 vivi 要的形态。\n"
    "        Stack({ alignContent: Alignment.BottomEnd }) {\n"
    "          this.mediaThumb(this.mediaPathAt(m.id, 0), 128)\n"
    "          if (this.mediaCountOf(m.id) > 1) {\n"
    "            Text(`共 ${this.mediaCountOf(m.id)} 张`)\n"
    "              .fontSize(10)\n"
    "              .fontColor(Color.White)\n"
    "              .padding({ left: 6, right: 6, top: 2, bottom: 2 })\n"
    "              .borderRadius(9)\n"
    "              .backgroundColor('#99000000')\n"
    "              .margin({ right: 4, bottom: 4 })\n"
    "          }\n"
    "        }\n"
    "      } else if (mediaPath.length > 0) {\n"
    "        this.mediaThumb(mediaPath, 128)\n"
    "      }\n",
    "      // 5.0.32：消息页不再内嵌缩略图（性能 + 避免变形），文件名 + 提示即可；\n"
    "      // 点一下跳「文件」页，那里图片/视频是缩略图宫格、其它文件一行一个。\n",
    "D1-thumb"
))

# D2. chatFileBubble：onClick 改为一律跳文件页（收到的）
edits.append((
    "    .onClick(() => {\n"
    "      // 长按过的这一小段时间里把 click 吃掉，防「存相册」连带弹出预览\n"
    "      if (Date.now() < this.clickMuteUntil) {\n"
    "        return;\n"
    "      }\n"
    "      if (this.mediaCountOf(m.id) > 0) {\n"
    "        this.openChatGallery(m.id, 0);\n"
    "        return;\n"
    "      }\n"
    "      if (mediaPath.length > 0) {\n"
    "        this.openMediaPreview(mediaPath, m.content);\n"
    "        return;\n"
    "      }\n"
    "      if (m.incoming) {\n"
    "        this.openFileTab();\n"
    "      }\n"
    "    })",
    "    .onClick(() => {\n"
    "      // 长按过的这一小段时间里把 click 吃掉，防「存相册」连带跳页\n"
    "      if (Date.now() < this.clickMuteUntil) {\n"
    "        return;\n"
    "      }\n"
    "      // 5.0.32：消息页只显示文件名、点击跳「文件」页，那里体验更顺\n"
    "      if (m.incoming) {\n"
    "        this.openFileTab();\n"
    "      }\n"
    "    })",
    "D2-onclick"
))

# E. bubbleHintOf 简化
edits.append((
    "  /** 气泡底部那行提示（一批 / 单个 / 无缩略图三种） */\n"
    "  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {\n"
    "    const n: number = this.mediaCountOf(m.id);\n"
    "    if (n > 1) {\n"
    "      return `点击查看 ${n} 张 · 长按存相册`;\n"
    "    }\n"
    "    if (n === 1 || mediaPath.length > 0) {\n"
    "      const nm: string = mediaPath.length > 0 ? mediaPath : m.content;\n"
    "      return this.isVideoName(nm) ? '点击播放 · 长按存相册' : '点击看图 · 长按存相册';\n"
    "    }\n"
    "    return '点击查看 ›';\n"
    "  }",
    "  /** 气泡底部那行提示：消息页只显示文件名、点击跳「文件」页，统一成「点击查看 ›」 */\n"
    "  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {\n"
    "    return '点击查看 ›';\n"
    "  }",
    "E-hint"
))

# F. 文件页：加宫格 + 列表改迭代 fileItems
edits.append((
    "      } else {\n"
    "        List({ space: 8 }) {\n"
    "          ForEach(this.receivedFiles, (f: ReceivedFile) => {",
    "      } else {\n"
    "        List({ space: 8 }) {\n"
    "          // 5.0.32：图片/视频先排成缩略图宫格（MediaTile 滑到才解视频首帧）\n"
    "          if (this.mediaItems.length > 0) {\n"
    "            ListItem() {\n"
    "              this.mediaGrid()\n"
    "            }\n"
    "          }\n"
    "          ForEach(this.fileItems, (f: ReceivedFile) => {",
    "F-files"
))

# G. 新增 mediaGrid() / mediaGridHeight() @Builder（插在 targetChip 前）
edits.append((
    "  /** 目标设备胶囊。value 用设备 IP —— 与网页端下拉框的 address 保持同一套标识 */\n"
    "  @Builder\n"
    "  targetChip(label: string, value: string) {",
    "  /**\n"
    "   * 5.0.32：文件页的「图片/视频缩略图宫格」。\n"
    "   *\n"
    "   * ⚠️ 性能要点：用 `ForEach` + 自定义 `MediaTile`，**不**在主路径预热任何视频帧 ——\n"
    "   *    `Grid`/`List` 对子项是窗口化懒加载的，滑到才建 `MediaTile`、\n"
    "   *    它的 `aboutToAppear` 才去解这一条视频的首帧（模块级缓存去重，已解的不再解）。\n"
    "   *    图片直接 `Image(uri)`，框架按需解码。彻底砍掉 5.0.31「刷新就同步算全部」的卡顿。\n"
    "   */\n"
    "  @Builder\n"
    "  mediaGrid() {\n"
    "    if (this.mediaItems.length > 0) {\n"
    "      Grid() {\n"
    "        ForEach(this.mediaItems, (f: ReceivedFile) => {\n"
    "          GridItem() {\n"
    "            MediaTile({\n"
    "              path: f.path,\n"
    "              name: f.name,\n"
    "              isVideo: this.isVideoName(f.name),\n"
    "              onTap: () => this.openFileGallery(f)\n"
    "            })\n"
    "          }\n"
    "          .aspectRatio(1)\n"
    "        }, (f: ReceivedFile) => `${f.path}`)\n"
    "      }\n"
    "      .columnsTemplate('104vp 104vp 104vp')\n"
    "      .rowsGap(6)\n"
    "      .columnsGap(6)\n"
    "      .width('100%')\n"
    "      .height(this.mediaGridHeight())\n"
    "      .padding({ left: 4, right: 4 })\n"
    "    }\n"
    "  }\n"
    "\n"
    "  /** 宫格高度：3 列，每行高 = 瓦片宽(104) + 行距(6) */\n"
    "  private mediaGridHeight(): number {\n"
    "    const rows: number = Math.ceil(this.mediaItems.length / 3);\n"
    "    return rows * 104 + Math.max(0, rows - 1) * 6;\n"
    "  }\n"
    "\n"
    "  /** 目标设备胶囊。value 用设备 IP —— 与网页端下拉框的 address 保持同一套标识 */\n"
    "  @Builder\n"
    "  targetChip(label: string, value: string) {",
    "G-grid"
))

# H1. 新增静态 fileUriOf（插在 baseName 后）
edits.append((
    "  /** 绝对路径 -> 文件名 */\n"
    "  private static baseName(path: string): string {\n"
    "    const s: number = path.lastIndexOf('/');\n"
    "    return s >= 0 ? path.substring(s + 1) : path;\n"
    "  }",
    "  /** 绝对路径 -> 文件名 */\n"
    "  private static baseName(path: string): string {\n"
    "    const s: number = path.lastIndexOf('/');\n"
    "    return s >= 0 ? path.substring(s + 1) : path;\n"
    "  }\n"
    "\n"
    "  /** 绝对路径 -> 文件 URI（图片/视频预览都吃这个，手拼 file:// 播不出来） */\n"
    "  private static fileUriOf(path: string): string {\n"
    "    try {\n"
    "      return fileUri.getUriFromPath(path);\n"
    "    } catch (e) {\n"
    "      return `file://${path}`;\n"
    "    }\n"
    "  }",
    "H1-fileuri"
))

src = read(IDX)
if SENTINEL in src:
    print("ALREADY APPLIED (Index.ets)")
else:
    src = apply(src, edits)
    write(IDX, src)
    print("Index.ets patched:", len(edits), "edits")

# ---------------- 文件末尾追加模块级 MediaTile / 视频首帧缓存 ----------------
MODULE = r"""

// ================= 5.0.32：文件页宫格的媒体瓦片 =================
// 模块级视频首帧缓存：path -> PixelMap。宫格瓦片滑到才解、解过就复用，
// 不在任何刷新路径上同步解码（vivi 实测「刷新卡顿」的根因是 5.0.31 的预热）。
const videoFrameCache: Map<string, image.PixelMap> = new Map<string, image.PixelMap>();
const videoFrameBusy: Set<string> = new Set<string>();

/**
 * 解一条视频的首帧（带模块级缓存）。返回 null = 解不出（调用方显示 ▶ 占位）。
 * 逻辑与页面里 `decodeVideoThumb` 一致，但结果落在模块缓存、供宫格瓦片复用。
 */
async function decodeVideoFrame(path: string): Promise<image.PixelMap | null> {
  const cached: image.PixelMap | undefined = videoFrameCache.get(path);
  if (cached !== undefined) {
    return cached;
  }
  if (videoFrameBusy.has(path)) {
    return null;
  }
  videoFrameBusy.add(path);
  let f: fileIo.File | null = null;
  let gen: media.AVImageGenerator | null = null;
  try {
    f = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);
    gen = await media.createAVImageGenerator();
    const desc: media.AVFileDescriptor = { fd: f.fd };
    gen.fdSrc = desc;
    let pm: image.PixelMap | null = await gen.fetchFrameByTime(
      0, media.AVImageQueryOptions.AV_IMAGE_QUERY_CLOSEST_SYNC, { width: -1, height: -1 });
    if (pm === null) {
      pm = await gen.fetchFrameByTime(
        0, media.AVImageQueryOptions.AV_IMAGE_QUERY_CLOSEST_SYNC, { width: 192, height: 192 });
    }
    if (pm !== null) {
      try {
        const info: image.ImageInfo = pm.getImageInfoSync();
        const vw: number = info.size.width;
        const vh: number = info.size.height;
        if (vw > 0 && vh > 0) {
          const longest: number = vw > vh ? vw : vh;
          if (longest > 320) {
            const s: number = 320 / longest;
            await pm.scale(s, s);
          }
        }
      } catch (x) {
        // 量不到比例就按原样，不影响显示
      }
      videoFrameCache.set(path, pm);
      return pm;
    }
    return null;
  } catch (e) {
    const err: BusinessError = e as BusinessError;
    Log.w('MediaTile', `解视频首帧失败: ${err.code} ${err.message} ${path}`);
    return null;
  } finally {
    videoFrameBusy.delete(path);
    if (gen !== null) {
      try {
        await gen.release();
      } catch (e) {
        // 忽略
      }
    }
    if (f !== null) {
      try {
        fileIo.closeSync(f);
      } catch (e) {
        // 忽略
      }
    }
  }
}

/** 文件页宫格里的一块：图片=原图(框架懒解码)、视频=首帧(滑到才解) */
@Component
struct MediaTile {
  @Prop path: string = '';
  @Prop name: string = '';
  @Prop isVideo: boolean = false;
  @State poster: image.PixelMap | null = null;
  onTap: () => void = () => {};

  aboutToAppear(): void {
    if (this.isVideo) {
      if (videoFrameCache.has(this.path)) {
        this.poster = videoFrameCache.get(this.path)!;
      } else {
        decodeVideoFrame(this.path).then((pm: image.PixelMap | null) => {
          this.poster = pm;
        }).catch(() => {
          this.poster = null;
        });
      }
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      if (this.isVideo) {
        if (this.poster !== null) {
          Image(this.poster)
            .width('100%')
            .height('100%')
            .objectFit(ImageFit.Cover)
        } else {
          Column() {
            Text('▶')
              .fontSize(34)
              .fontColor('#FFFFFF')
          }
          .width('100%')
          .height('100%')
          .backgroundColor('#2A2D33')
          .justifyContent(FlexAlign.Center)
        }
      } else {
        Image(Index.fileUriOf(this.path))
          .width('100%')
          .height('100%')
          .objectFit(ImageFit.Cover)
      }
    }
    .width('100%')
    .height('100%')
    .borderRadius(8)
    .clip(true)
    .onClick(() => this.onTap())
  }
}
"""

if "struct MediaTile" not in src:
    # 文件末尾追加（src 此时是已 patch 的内容）
    if not src.endswith("\n"):
        src += "\n"
    src += MODULE
    write(IDX, src)
    print("module MediaTile appended")
else:
    print("module MediaTile already present")

# ---------------- app.json5 升版本 ----------------
app = read(APP)
if '"versionCode": 5000032' in app and '"versionName": "5.0.32"' in app:
    print("app.json5 already 5.0.32")
else:
    assert '"versionCode": 5000031' in app, "app.json5 未找到 5000031"
    assert '"versionName": "5.0.31"' in app, "app.json5 未找到 5.0.31"
    app = app.replace('"versionCode": 5000031', '"versionCode": 5000032')
    app = app.replace('"versionName": "5.0.31"', '"versionName": "5.0.32"')
    write(APP, app)
    print("app.json5 -> 5.0.32")

print("DONE")
