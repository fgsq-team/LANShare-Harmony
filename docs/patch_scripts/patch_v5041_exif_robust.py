# -*- coding: utf-8 -*-
"""
5.0.41 —— 缩略图方向「修了但没修好」的二次修复

5.0.40 为什么没生效？两个各自独立、都足以让整件事静默失效的原因：

  ⚠️ ① **`getImageProperty(PropertyKey.ORIENTATION)` 的返回值格式不统一**。
        SDK 的 d.ts 只说「以字符串返回」，并提到读不到时返回 `Unknown Value x`；
        但华为官方 FAQ 的示例代码里比的是 **`'Right-top'` / `'Bottom-right'` 这类
        语义串**（不是 `'6'`）。也就是说**同一份代码在不同设备/版本上拿到的可能是
        `'6'` 也可能是 `'Right-top'`**。5.0.40 的 `exifDeg()` 只认数字 → 命中语义串
        时返回 0 → 啥也没转 → 跟 5.0.39 长得一模一样（正是 vivi 看到的现象）。

  ⚠️ ② **`createPixelMap()` 没传 `editable: true`**。SDK 注释原文：
        "If this option is set to **false**, the image cannot be edited again, and
         operations such as writing pixels will fail." —— `rotate()` 属于这类操作，
        不可编辑的 PixelMap 上调用可能直接失败。5.0.40 把异常 catch 掉只 Log.w，
        于是静默失效。

本版的三条保险（**自动切换，绝不双重旋转**）：
  A. `exifDeg()` 同时认三种写法：数字 `'6'`、兜底文本 `'Unknown Value 6'`、
     语义串 `'Right-top'`。
  B. 解码时**直接传 `rotate: deg`** 一步到位，并开 `editable: true`。
  C. **运行时验证有没有真转**：拿解码结果的方向跟原图方向比 —— 90/270 时
     「横竖性」必须翻转。没翻转 → 再补一次 `pm.rotate(deg)`；仍不生效 →
     记进 `mediaRot`，由 `Image.orientation()` 在**显示层**补转。
     物理转成功时 `mediaRot` 记为 0，显示层强制 `UP`（不转）——
     这样既躲开「pack 时万一写回 EXIF 被 Image 二次旋转」，也不会两头都不转。

⚠️ 为什么沙箱原图仍用 `AUTO` 而不是显式角度：ArkUI `Image` **会自己读 EXIF 并旋转**
   （官方 FAQ 原文），再显式给角度就是转两遍。缓存小图是我们自己 pack 的、不带 EXIF，
   所以只有它需要我们指定方向。
"""

import io
import sys

P = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'

SENT = 'private static exifDegFromText('


def rd():
    with io.open(P, encoding='utf-8', newline='') as f:
        return f.read()


def rep(s, old, new, tag):
    if s.count(old) != 1:
        print('ERROR [%s]: old 出现 %d 次（应为 1）' % (tag, s.count(old)))
        sys.exit(1)
    return s.replace(old, new, 1)


s = rd()
if SENT in s:
    print('ALREADY APPLIED')
    sys.exit(0)

# ------------------------------------------------------- 1) exifDeg 兼容三种写法
OLD_1 = """  private static exifDeg(ori: string): number {
    if (ori === '3') {
      return 180;
    }
    if (ori === '6' || ori === '7') {
      return 90;
    }
    if (ori === '5' || ori === '8') {
      return 270;
    }
    return 0;
  }
"""
NEW_1 = """  private static exifDeg(ori: string): number {
    if (ori.length === 0) {
      return 0;
    }
    // ① 语义串：部分版本/设备返回 'Right-top' 这种（华为官方 FAQ 示例就是比这个）
    if (ori === 'Bottom-right') {
      return 180;
    }
    if (ori === 'Right-top' || ori === 'Right-bottom') {
      return 90;
    }
    if (ori === 'Left-top' || ori === 'Left-bottom') {
      return 270;
    }
    if (ori === 'Top-left' || ori === 'Top-right' || ori === 'Bottom-left') {
      return 0;
    }
    // ② 数字：'6'，以及读不到时官方返回的 'Unknown Value 6' —— 一律取串里第一个数字
    return Index.exifDegFromText(ori);
  }

  /** 从 `'6'` / `'Unknown Value 6'` 这类文本里取出方向数字再换算角度 */
  private static exifDegFromText(ori: string): number {
    let n: number = -1;
    for (let i: number = 0; i < ori.length; i++) {
      const code: number = ori.charCodeAt(i);
      if (code >= 48 && code <= 57) {
        n = code - 48;
        break;
      }
    }
    if (n === 3) {
      return 180;
    }
    if (n === 6 || n === 7) {
      return 90;
    }
    if (n === 5 || n === 8) {
      return 270;
    }
    return 0;
  }
"""
s = rep(s, OLD_1, NEW_1, '1-exifDeg')

# ------------------------------------------------------- 2) mediaRot 状态
OLD_2 = """  private mediaRatio: Map<string, number> = new Map<string, number>();
"""
NEW_2 = """  private mediaRatio: Map<string, number> = new Map<string, number>();
  /**
   * 5.0.41：这张图**还需要显示层再补转多少度**（0 = 不用补）。
   *
   * 只对「我们自己 pack 出来的缓存小图」记录 —— 沙箱原图不在本表时走
   * `ImageRotateOrientation.AUTO`（Image 自己会读 EXIF，不能重复转）。
   */
  private mediaRot: Map<string, number> = new Map<string, number>();
"""
s = rep(s, OLD_2, NEW_2, '2-mediaRot')

# ------------------------------------------------------- 3) thumbOri 方法（挂在 thumbH 后）
OLD_3 = """  /** 缩略图框高：最长边 = maxSide，按原图比例算 */
  private thumbH(path: string, maxSide: number): number {
    const r: number = this.ratioOf(path);
    return r >= 1 ? Math.round(maxSide / r) : maxSide;
  }
"""
NEW_3 = """  /** 缩略图框高：最长边 = maxSide，按原图比例算 */
  private thumbH(path: string, maxSide: number): number {
    const r: number = this.ratioOf(path);
    return r >= 1 ? Math.round(maxSide / r) : maxSide;
  }

  /**
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
    if (v === undefined) {
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
s = rep(s, OLD_3, NEW_3, '3-thumbOri')

# ------------------------------------------------------- 4) cacheThumb：三重保险
OLD_4 = """        let deg: number = 0;
        try {
          const ori: string = await src.getImageProperty(image.PropertyKey.ORIENTATION);
          deg = Index.exifDeg(ori);
        } catch (x) {
          deg = 0;
        }
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
        // 转正（90/270 时宽高会互换，后面 `pm.getImageInfoSync()` 读到的是转完的尺寸）
        if (pm !== null && deg !== 0) {
          try {
            await pm.rotate(deg);
          } catch (x) {
            // 转不动就保持原样，总比整张崩掉强
            Log.w(TAG, `缩略图旋转失败: ${deg} ${srcPath}`);
          }
        }
"""
NEW_4 = """        let deg: number = 0;
        let oriRaw: string = '';
        try {
          oriRaw = await src.getImageProperty(image.PropertyKey.ORIENTATION);
          deg = Index.exifDeg(oriRaw);
        } catch (x) {
          // 没 EXIF / 这个格式不支持读 EXIF —— 按不转处理
          deg = 0;
        }
        // 5.0.41：留一条可抓的日志，下次再不对直接看这里拿到的到底是个啥
        Log.i(TAG, `EXIF ${Index.baseName(srcPath)}: ori='${oriRaw}' -> ${deg}度`);
        const info: image.ImageInfo = src.getImageInfoSync(0);
        const w: number = info.size.width;
        const h: number = info.size.height;
        const longest: number = w > h ? w : h;
        const s: number = longest > 320 ? 320 / longest : 1;
        // desiredSize 直接按目标尺寸解码 —— 4K 原图整张进内存太贵。
        // ⚠️ editable 必须给 true：不可编辑的 PixelMap 上写像素类操作（含 rotate）会失败。
        pm = await src.createPixelMap({
          desiredSize: {
            width: Math.max(1, Math.round(w * s)),
            height: Math.max(1, Math.round(h * s))
          },
          rotate: deg,
          editable: true
        });
        try {
          src.release();
        } catch (x) {
          // 释放失败不影响缩略图
        }
        // ---- 运行时验证：解码时那一步 rotate 到底生效没有 ----
        // 判据：90/270 时「横竖性」必须翻转（原来是横的就得变竖的）。
        let turned: boolean = false;
        if (pm !== null && Index.isQuarter(deg)) {
          try {
            const after: image.ImageInfo = pm.getImageInfoSync();
            turned = (after.size.width > after.size.height) !== (w > h);
          } catch (x) {
            turned = false;
          }
        }
        if (pm !== null && deg !== 0 && !turned) {
          // 解码那步没转 -> 补一次显式 rotate，再验一次
          try {
            await pm.rotate(deg);
            if (Index.isQuarter(deg)) {
              const after2: image.ImageInfo = pm.getImageInfoSync();
              turned = (after2.size.width > after2.size.height) !== (w > h);
            } else {
              turned = true;
            }
          } catch (x) {
            Log.w(TAG, `缩略图物理旋转失败，改用显示层补转: ${deg} ${srcPath}`);
          }
        }
        if (deg !== 0 && !turned) {
          // 两条物理路都不通 —— 记下来，交给 Image.orientation() 在显示层补
          Log.w(TAG, `物理旋转均未生效，显示层补转 ${deg}度: ${srcPath}`);
        }
"""
s = rep(s, OLD_4, NEW_4, '4-cacheThumb')

# ------------------------------------------------------- 5) 记 mediaRot（写盘之后）
OLD_5 = """      // 记下真实比例：气泡的缩略图框按它算，不然又变正方形
      if (iw > 0 && ih > 0) {
        this.mediaRatio.set(out, Index.clampRatio(iw / ih));
        this.thumbTick++;
      }
"""
NEW_5 = """      // 记下真实比例：气泡的缩略图框按它算，不然又变正方形。
      // ⚠️ 5.0.41：物理没转成、要靠显示层补转时，`iw/ih` 还是「躺着」的比例 ——
      //    框必须按**转完之后**的给（90/270 就是交换宽高），否则内容转了框没转，
      //    Contain 出来就是「竖图塞在横框里」。
      if (iw > 0 && ih > 0) {
        const swap: boolean = Index.isQuarter(this.pendingRot);
        const rw: number = swap ? ih : iw;
        const rh: number = swap ? iw : ih;
        this.mediaRatio.set(out, Index.clampRatio(rw / rh));
        this.thumbTick++;
      }
      // 5.0.41：缓存小图是「我们自己 pack 的、不带 EXIF」的图，Image 不会替我们转，
      //         所以这里必须明确告诉显示层还要不要补转（0 = 已物理转正，别再转）。
      this.mediaRot.set(out, this.pendingRot);
      this.pendingRot = 0;
"""
s = rep(s, OLD_5, NEW_5, '5-record-rot')

# ------------------------------------------------------- 6) pendingRot 字段 + 赋值
OLD_6 = """  private mediaRot: Map<string, number> = new Map<string, number>();
"""
NEW_6 = """  private mediaRot: Map<string, number> = new Map<string, number>();
  /** `cacheThumb()` 内部传递「这次有没有物理转成功」的中转变量（0 = 转成功，否则 = 待补转的度数） */
  private pendingRot: number = 0;
"""
s = rep(s, OLD_6, NEW_6, '6-pendingRot')

# 把 cacheThumb 里算出的待补转度数写进 pendingRot
OLD_7 = """        if (deg !== 0 && !turned) {
          // 两条物理路都不通 —— 记下来，交给 Image.orientation() 在显示层补
          Log.w(TAG, `物理旋转均未生效，显示层补转 ${deg}度: ${srcPath}`);
        }
"""
NEW_7 = """        if (deg !== 0 && !turned) {
          // 两条物理路都不通 —— 记下来，交给 Image.orientation() 在显示层补
          Log.w(TAG, `物理旋转均未生效，显示层补转 ${deg}度: ${srcPath}`);
          this.pendingRot = deg;
        }
"""
s = rep(s, OLD_7, NEW_7, '7-pendingRot-assign')

# ------------------------------------------------------- 7) 缩略图 Image：AUTO -> thumbOri
OLD_8 = """          // 5.0.40：按 EXIF 摆正显示方向。缓存小图没 EXIF，AUTO 等价于 UP，不会转两遍
          .orientation(ImageRotateOrientation.AUTO)
"""
NEW_8 = """          // 5.0.41：缓存小图按 `mediaRot` 补转；沙箱原图不在表里 -> AUTO（Image 自己读 EXIF）
          .orientation(this.thumbOri(path))
"""
s = rep(s, OLD_8, NEW_8, '8-thumb-ori')

# ------------------------------------------------------- 8) 全屏预览同理
OLD_9 = """          // 5.0.40：同上，全屏预览也按 EXIF 摆正
          .orientation(ImageRotateOrientation.AUTO)
"""
NEW_9 = """          // 5.0.41：同上（预览可能显示沙箱原图，也可能是缓存小图，同一套判定）
          .orientation(this.thumbOri(path))
"""
s = rep(s, OLD_9, NEW_9, '9-preview-ori')

with io.open(P, 'w', encoding='utf-8', newline='') as f:
    f.write(s)
print('PATCH_OK  5.0.41 EXIF 二次修复（三重保险）')
