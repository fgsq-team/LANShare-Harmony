# -*- coding: utf-8 -*-
"""
5.0.18 沉淀脚本：源码注释校正 + PENDING_TEST + 工作区日志 + 技能。

幂等：每个目标都有独立哨兵；已写过就跳过。先全部算完再统一落盘。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
F_INDEX = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets')
F_PENDING = os.path.join(ROOT, 'docs', 'PENDING_TEST.md')
F_LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-01.md'
F_SKILL = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'

HAP_SIZE = '__HAP_SIZE__'
HAP_SHA = '__HAP_SHA__'


def read(p):
    return io.open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def sub(s, old, new, tag):
    assert s.count(new) == 0, '[%s] 新文本已存在' % tag
    assert s.count(old) == 1, '[%s] 期望 1 处，实际 %d' % (tag, s.count(old))
    return s.replace(old, new, 1)


# ---------------------------------------------------------------------------
# 1. Index.ets 两处过时注释
# ---------------------------------------------------------------------------
idx = read(F_INDEX)

if '图片 / 视频缩略图：能在 App 内直接打开的' not in idx:
    idx = sub(
        idx,
        "                // 图片缩略图：只给图片类文件。\n",
        "                // 图片 / 视频缩略图：能在 App 内直接打开的那两类。\n"
        "                // 视频走 `AVImageGenerator` 解首帧（异步），所以下面多了「解出来没有」\n"
        "                // 的分支 —— 没解出来就停在灰色占位。\n",
        'file-thumb-comment',
    )
    idx = sub(
        idx,
        "   * 收到的图片：先给 128×128 缩略图（同样靠 `sourceSize` 压解码尺寸，\n"
        "   * 理由见文件页那段注释），点一下看大图、长按存相册。\n"
        "   * 非图片 / 自己发出的：维持原样（点一下跳「文件」页）。\n",
        "   * 收到的**图片 / 视频**：先给 128×128 缩略图（图片靠 `sourceSize` 压解码尺寸、\n"
        "   * 视频靠 `AVImageGenerator` 解首帧，理由见文件页那段注释），\n"
        "   * 点一下打开（图片 = 缩放预览 / 视频 = 播放器）、长按存相册。\n"
        "   * **其它类型**才「点一下跳「文件」页」；自己发出的不跳（原文件还在用户手上）。\n",
        'bubble-comment',
    )
    write(F_INDEX, idx)
    print('Index.ets 注释已校正')
else:
    print('Index.ets 注释已是最新，跳过')

# ---------------------------------------------------------------------------
# 2. PENDING_TEST.md —— 新增 5.0.18，5.0.17 降级
# ---------------------------------------------------------------------------
pend = read(F_PENDING)

if 'LANShareV5-5.0.18' not in pend:
    new_section = (
        '---\n'
        '## \U0001f7e2 最新待测：LANShareV5-5.0.18 —— '
        '**消息页图片/视频直接打开（不再跳文件页）+ 预览页长按存相册**（2026-10-01 16:2x 构建）\n'
        '\n'
        '| 项 | 值 |\n'
        '|---|---|\n'
        '| 版本号 | 5.0.18（versionCode 5000018） |\n'
        '| 本地 HAP | `E:/lanshare-harmony/LANShareV5/LANShareV5-5.0.18.hap` |\n'
        '| 大小 | ' + HAP_SIZE + ' B |\n'
        '| sha256 | `' + HAP_SHA + '` |\n'
        '| 手机落地 | \u2705 **已推送** \u2192 `Download/LANShareV5-5.0.18.hap` |\n'
        '| 构建结果 | 全量重建 **BUILD SUCCESSFUL**（33/33 任务），零 ArkTS ERROR |\n'
        '| 编入验证 | 解包 `ets/modules.abc` 探针：`点击播放 \u00b7 长按存相册`、`正在保存视频\u2026`、'
        '`解视频首帧失败`、`无法播放这个视频（编码或封装格式不支持）`、`点击看图 \u00b7 长按存相册`、'
        '`点击查看 \u203a`、`存相册：`、`已取消保存` |\n'
        '\n'
        '> vivi 2026-10-01 真机诉求（当时机上为 5.0.17）\n'
        '> ① 消息页点图片/视频**不要跳文件页**，「直接显示缩略图、可以打开、可以存相册」，'
        '其它文件才跳；\n'
        '> ② 点开图片后**长按**就能存相册（原来只能按顶栏按钮）。\n'
        '\n'
        '---\n'
        '\n'
        '### 诉求 1：图片/视频直接在消息页打开，只有「其它文件」才跳文件页\n'
        '\n'
        '改动落在**一处判断**上：`msgImagePath` \u2192 `msgMediaPath`，判据从 `isImageName` 放宽到\n'
        '`isMediaName`（图片 **或** 视频）。返回空串的语义就是「这一类点了跳文件页」。\n'
        '\n'
        '| 类型 | 气泡里显示 | 点一下 | 长按 |\n'
        '|---|---|---|---|\n'
        '| 图片 | 128\u00d7128 缩略图 | 全屏预览（捏合/双击/拖动） | 存相册 |\n'
        '| **视频** | 128\u00d7128 **首帧** + \u25b6 角标 | **全屏播放器**（内置 `Video`，带进度条） | 存相册 |\n'
        '| 其它（zip/apk/pdf\u2026） | 只有文件名 | 跳「文件」页 | \u2014 |\n'
        '\n'
        '**视频缩略图是本轮唯一的硬骨头**：把视频路径直接喂给 `Image` 只会得到**一块空白**\n'
        '（图/视频的解码器根本不是一个）。\n'
        '\n'
        '正解是 `media.createAVImageGenerator()`：\n'
        '\n'
        '```ts\n'
        'f = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);   // fd 要活到 fetch 返回\n'
        'gen = await media.createAVImageGenerator();\n'
        'gen.fdSrc = { fd: f.fd } as media.AVFileDescriptor;\n'
        'const pm = await gen.fetchFrameByTime(\n'
        '  0, media.AVImageQueryOptions.AV_IMAGE_QUERY_CLOSEST_SYNC, { width: 192, height: 192 });\n'
        'await gen.release();\n'
        '```\n'
        '\n'
        '三个必守点：**fd 必须活到 `fetchFrameByTime` 返回**（提前 close 直接解不出来）；\n'
        '**`release()` 是 Promise，要 await**；**取「离 0 最近的关键帧」而不是第 0 帧**\n'
        '（不少视频开头是纯黑，关键帧才有画面）。\n'
        '\n'
        '**异步结果的可见性坑**：`videoThumbs` 是普通 `Map`，ArkUI 观察不到 `Map.set()`。\n'
        '所以配了一个 `@State videoThumbTick` 计数器，每解出一张 +1；并且**消息页 / 文件页两个\n'
        '`ForEach` 的 key 都要带上 tick** —— key 不变的话 ForEach 会复用旧行，缩略图永远不出现。\n'
        '（`List` 是懒加载的，只重建可见那几行，代价可忽略。）\n'
        '\n'
        '另一条纪律：解码**不在 `@Builder` 里触发**（`@Builder` 每次重绘都会重新执行，\n'
        '在里面起异步任务等于每次重绘提交一次）。统一放在 `refreshReceived()` 末尾预热，\n'
        '渲染保持纯粹。\n'
        '\n'
        '### 诉求 2：点开图片后长按就能存相册\n'
        '\n'
        '预览浮层里那个 `Image` 上已经挂了 `GestureGroup(Parallel, 捏合 / 拖动 / 双击)`，\n'
        '**直接往这个组里再塞一个 `LongPressGesture` 即可**：长按时手指不动，\n'
        '`PanGesture` 的 `distance: 6` 不会被触发，互不打架。\n'
        '\n'
        '配套把 `saveImageToAlbum` 扩到**视频**：`PhotoType.VIDEO` + 扩展名缺省 `mp4`。\n'
        '\u26a0\ufe0f 视频动辄几百 MB，而 `ExportService.copyTo` 是**同步**逐块读写 —— 直接调用会把\n'
        '主线程按住好几秒，连「正在保存」这句 toast 都画不出来（同一帧内就被阻塞）。\n'
        '所以先 `toast` + `await yieldOnce()`（`setTimeout(30)`）让出一帧，再开始拷。\n'
        '\n'
        '### 顺带\n'
        '\n'
        '- 全屏预览浮层现在支持**两种形态**：`imgPreviewVideo` 为真走内置 `Video`\n'
        '  （`src` 用同一个 `fileUri.getUriFromPath()` 沙箱 URI，官方声明明确支持这一形态），\n'
        '  否则走原来的缩放 `Image`。关闭时显式 `videoCtl.stop()`。\n'
        '- **「文件」页也一并支持视频**（48\u00d748 首帧缩略图 + 点击播放）—— 同一套机制，\n'
        '  不加的话同一个视频在两个页面的行为会不一致。\n'
        '- 新增权限：**零**。`Video` 同进程读自己的沙箱，`showAssetsCreationDialog` 免权限。\n'
        '\n'
        '### 验收\n'
        '\n'
        '| # | 操作 | 期望 |\n'
        '|---|---|---|\n'
        '| ① | 消息页收到**视频** | 气泡里出现**首帧缩略图** + \u25b6 角标（不是空白、不是灰框） |\n'
        '| ② | 点视频缩略图 | **直接全屏播放**（不再跳「文件」页），有进度条可拖 |\n'
        '| ③ | 点图片缩略图 | 全屏预览，捏合缩放 / 拖动 / 返回键关闭正常 |\n'
        '| ④ | **图片预览里长按** | 弹系统保存确认框 \u2192 相册能看到这张图 |\n'
        '| ⑤ | 点「其它文件」（zip/apk\u2026）气泡 | **仍然跳「文件」页**（这条不能回归） |\n'
        '| ⑥ | 「文件」页的视频行 | 也有缩略图，点一下能播 |\n'
        '\n'
        '\u26a0\ufe0f 已知边界：`recvIndex` 那张「文件名 \u2192 路径」表来自「文件」页扫描（上限 40 条），\n'
        '**很久以前收到**的视频/图片（已跌出前 40）在消息页可能没有缩略图（点击仍会跳文件页）。\n'
        '这是刻意取舍：为一个纯显示字段去改 `ChatMessage` 的落盘结构，代价与风险都不划算。\n'
        '\n'
    )
    pend = sub(
        pend,
        '---\n## \U0001f7e2 最新待测：LANShareV5-5.0.17',
        new_section + '---\n## \U0001f535 待测：LANShareV5-5.0.17',
        'pending-new-section',
    )
    write(F_PENDING, pend)
    print('PENDING_TEST.md 已新增 5.0.18 章节')
else:
    print('PENDING_TEST.md 已有 5.0.18，跳过')

# ---------------------------------------------------------------------------
# 3. 工作区日志
# ---------------------------------------------------------------------------
log = read(F_LOG)
if '## 5.0.18' not in log:
    log = sub(
        log,
        '补丁脚本：`docs/patch_scripts/patch_v5017.py`；改动前源码备份 `.backup_v5017/`。\n',
        '补丁脚本：`docs/patch_scripts/patch_v5017.py`；改动前源码备份 `.backup_v5017/`。\n'
        '\n'
        '## 5.0.18（2026-10-01 16:2x）消息页图片/视频直接打开 + 预览页长按存相册\n'
        '\n'
        '- vivi 诉求：① 消息页点图片/视频**不跳文件页**，直接显示缩略图、可打开、可存相册，\n'
        '  其它文件才跳；② 点开图片后**长按**就能存相册（原来只有顶栏按钮）。\n'
        '- **一处判断定全局**：`msgImagePath` → `msgMediaPath`，判据 `isImageName` → `isMediaName`。\n'
        '  返回空串 = 「点了跳文件页」的那一类。\n'
        '- **视频首帧缩略图**（本轮硬骨头）：`Image` 喂视频路径 = 永久空白（解码器不同）。\n'
        '  用 `media.createAVImageGenerator()` + `fdSrc` + `fetchFrameByTime(0,\n'
        '  AV_IMAGE_QUERY_CLOSEST_SYNC, {192,192})` 解 PixelMap。三个必守点：\n'
        '  **fd 活到 fetch 返回**、**`release()` 要 await**、**取关键帧不取第 0 帧**\n'
        '  （不少视频开头纯黑）。\n'
        '- **ArkUI 观察不到 `Map.set()`**：配 `@State videoThumbTick` 计数器，且\n'
        '  **消息页/文件页两个 `ForEach` 的 key 都要带上 tick** —— 否则 key 不变、ForEach 复用旧行、\n'
        '  缩略图永远不出现。（List 懒加载，只重建可见行，代价可忽略。）\n'
        '- 解码**不在 `@Builder` 里触发**（每次重绘都会重新执行），统一放 `refreshReceived()` 末尾预热。\n'
        '- **长按存相册**：直接往预览页那个 `GestureGroup(Parallel, 捏合/拖动/双击)` 里再塞一个\n'
        '  `LongPressGesture` —— 长按手指不动，`PanGesture(distance:6)` 不会被触发。\n'
        '  `saveImageToAlbum` 扩到视频：`PhotoType.VIDEO`；⚠️ `copyTo` 是同步逐块读写，\n'
        '  视频几百 MB 会按住主线程，先 `toast` + `await yieldOnce()` 让出一帧再拷。\n'
        '- 全屏浮层改双形态：`imgPreviewVideo` 为真走内置 `Video`\n'
        '  （`src` 同样是 `fileUri.getUriFromPath()` 的沙箱 URI，官方明确支持）；\n'
        '  关闭时显式 `videoCtl.stop()`。「文件」页也一并支持视频（同一套机制）。\n'
        '- **新增权限：零**。\n'
        '- 版本 5.0.17 → 5.0.18（versionCode 5000018）。\n'
        '\n'
        '补丁脚本：`docs/patch_scripts/patch_v5018.py` / `patch2_v5018_notes.py`；\n'
        '改动前源码备份 `.backup_v5018/`。\n',
        'log-5018',
    )
    write(F_LOG, log)
    print('工作区日志已追加 5.0.18')
else:
    print('工作区日志已有 5.0.18，跳过')

# ---------------------------------------------------------------------------
# 4. 技能：新增第二十四节
# ---------------------------------------------------------------------------
skill = read(F_SKILL)
if '## 二十四、' not in skill:
    skill = skill.rstrip('\n') + '\n\n' + (
        '## 二十四、视频缩略图 + 「一个浮层两种形态」的媒体预览\n'
        '\n'
        '### 症状\n'
        '\n'
        '列表里要给视频显示缩略图，`Image(this.imageUri(videoPath))` —— **不报错、不抛异常，\n'
        '就是永远空白**。\n'
        '\n'
        '**根因**：图片和视频的解码器根本不是一个。`Image` 只认图片；视频要先把某一帧**解码成位图**。\n'
        '\n'
        '### 正解：`AVImageGenerator`\n'
        '\n'
        '```ts\n'
        "import { media } from '@kit.MediaKit';\n"
        "import { image } from '@kit.ImageKit';\n"
        "import { fileIo } from '@kit.CoreFileKit';\n"
        '\n'
        'let f: fileIo.File | null = null;\n'
        'let gen: media.AVImageGenerator | null = null;\n'
        'try {\n'
        '  f = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);\n'
        '  gen = await media.createAVImageGenerator();\n'
        '  const desc: media.AVFileDescriptor = { fd: f.fd };\n'
        '  gen.fdSrc = desc;\n'
        '  const pp: media.PixelMapParams = { width: 192, height: 192 };\n'
        '  const pm: image.PixelMap = await gen.fetchFrameByTime(\n'
        '    0, media.AVImageQueryOptions.AV_IMAGE_QUERY_CLOSEST_SYNC, pp);\n'
        '  // pm 直接喂 Image(pm) 即可\n'
        '} finally {\n'
        '  if (gen !== null) { try { await gen.release(); } catch (e) {} }\n'
        '  if (f !== null) { try { fileIo.closeSync(f); } catch (e) {} }\n'
        '}\n'
        '```\n'
        '\n'
        '三个必守点（每一条都踩过）：\n'
        '\n'
        '| # | 规则 | 违反的后果 |\n'
        '|---|---|---|\n'
        '| ① | **fd 必须活到 `fetchFrameByTime` 返回** | 提前 `closeSync` → 解不出来（还容易是静默失败） |\n'
        '| ② | **`release()` 是 `Promise<void>`，要 `await`** | 忘了 await 会泄漏 native 实例 |\n'
        '| ③ | **取「离 0 最近的关键帧」**（`AV_IMAGE_QUERY_CLOSEST_SYNC`），不是第 0 帧 | 不少视频开头是纯黑，第 0 帧就是块黑图 |\n'
        '\n'
        '> `PixelMapParams.width/height` 若大于原视频尺寸，**不会报错**，只是不缩放（返回原始尺寸）。\n'
        '> 传 192×192 对手机视频足够。\n'
        '\n'
        '### 坑：ArkUI **观察不到 `Map.set()`**\n'
        '\n'
        '解码是异步的，结果存在 `Map<string, PixelMap>` 里 —— 但普通字段的 `Map.set()`\n'
        '**不会触发重绘**。两条一起做才行：\n'
        '\n'
        '```ts\n'
        'private videoThumbs: Map<string, image.PixelMap> = new Map();\n'
        '@State videoThumbTick: number = 0;      // 每解出一张 +1\n'
        '\n'
        'private hasVideoThumb(path: string): boolean {\n'
        '  if (this.videoThumbTick < 0) { return false; }   // 读一下，建立 @State 依赖\n'
        '  return this.videoThumbs.has(path);\n'
        '}\n'
        '```\n'
        '\n'
        '```ts\n'
        '// ⚠️ 光有 tick 还不够：ForEach 的 key 不带 tick 的话会复用旧行，缩略图永远不出现\n'
        'ForEach(this.list, (it: Item) => { /* ... */ },\n'
        '  (it: Item) => `${it.path}|${this.videoThumbTick}`)\n'
        '```\n'
        '\n'
        '`List` 是懒加载的，tick 变化只重建**可见那几行**，代价可忽略。\n'
        '\n'
        '### 纪律：异步副作用别放 `@Builder`\n'
        '\n'
        '`@Builder` 每次重绘都会重新执行。在里面起异步解码 = 每次重绘提交一次任务\n'
        '（用 busy 表挡只是治标）。**把副作用放在数据刷新那条路径上**（列表刷新函数末尾统一预热），\n'
        '渲染保持纯粹。\n'
        '\n'
        '### 沙箱 URI 的适用范围\n'
        '\n'
        '`fileUri.getUriFromPath(path)` 产出的 `file://<bundleName>/<沙箱路径>`：\n'
        '**`Image` 和 `Video` 都支持**（`Video` 的官方声明里明确写了这一形态）。\n'
        '手拼 `' + chr(39) + 'file://' + chr(39) + ' + path 两边都用不了 —— 且**都是静默失败**（空白/不播，不报错）。\n'
        '\n'
        '### 「一个浮层两种形态」\n'
        '\n'
        '全屏预览想同时支持图片和视频，不必写两个浮层 —— 一个 `@State` 布尔分流即可：\n'
        '\n'
        '```ts\n'
        '@State previewVideo: boolean = false;\n'
        'private videoCtl: VideoController = new VideoController();\n'
        '\n'
        '// 打开：previewVideo = isVideoName(name)   ← 由扩展名判定，调用方不用传类型\n'
        '// 渲染：if (previewVideo) { Video({ src: uri, controller: this.videoCtl })\n'
        '//           .controls(true).autoPlay(true).onError(...) } else { Image(...) }\n'
        '// 关闭：this.videoCtl.stop()   ← 显式停，别让声音多跑半秒\n'
        '```\n'
        '\n'
        '### 配套：`LongPressGesture` 可以并进已有的 `GestureGroup`\n'
        '\n'
        '图片预览上已经挂了捏合 / 拖动 / 双击，再加一个长按不用另开手势链 ——\n'
        '直接往同一个 `GestureGroup(GestureMode.Parallel, ...)` 里追加：\n'
        '\n'
        '```ts\n'
        'GestureGroup(GestureMode.Parallel,\n'
        '  PinchGesture({ fingers: 2 }).onActionUpdate(/* ... */),\n'
        '  PanGesture({ fingers: 1, distance: 6 }).onActionUpdate(/* ... */),\n'
        '  TapGesture({ count: 2 }).onAction(/* ... */),\n'
        '  LongPressGesture({ repeat: false, duration: 400 })   // ← 追加即可\n'
        '    .onAction(() => { /* 存相册 */ }),\n'
        ')\n'
        '```\n'
        '\n'
        '长按时手指不动，`PanGesture` 的 `distance` 阈值不会被触发，几条手势互不打架。\n'
        '\n'
        '### 大文件写盘前先让一帧\n'
        '\n'
        '把沙箱文件写进相册用的是同步逐块拷贝。视频几百 MB 会把主线程按住好几秒，\n'
        '连「正在保存」这句 toast 都画不出来（同一帧内就被阻塞）。\n'
        '\n'
        '```ts\n'
        "this.toast('正在保存视频…');\n"
        'await Index.yieldOnce();     // setTimeout(30) 让出一帧\n'
        'const msg = ExportService.copyTo(path, dstUri, name);\n'
        'this.toast(msg);\n'
        '```\n'
    ) + '\n'
    write(F_SKILL, skill)
    print('技能已新增第二十四节')
else:
    print('技能已有第二十四节，跳过')

print('OK - 5.0.18 沉淀完成')
