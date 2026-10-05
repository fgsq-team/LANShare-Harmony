# -*- coding: utf-8 -*-
"""
5.0.40 —— 缩略图方向（EXIF orientation）

现象：纵向拍的照片，收到后在消息页 / 文件页的缩略图是**躺着**的。

根因（两条独立的事实，缺一不可）：
  ① ArkUI 的 `Image` 组件**会自己读 EXIF 并旋转**（华为官方 FAQ 原文：
     "HarmonyOS 的 Image 组件会读取图片中的信息并旋转"），
     所以直接显示沙箱原图那一路本来是对的；
  ② 但 `cacheThumb()` 是 `createImageSource(path).createPixelMap()` 解码成
     PixelMap 再 `packing()` 成 jpg —— **解码不应用 EXIF、pack 出来的 jpg 也不带
     orientation 字段**。于是那张 320px 小图是**物理上躺着**的，
     而且**没有任何 EXIF 告诉 Image 该转回来** -> 显示成横向。
  ③ 同时 `ensureMediaRatio()` 用的是 `getImageInfoSync()`，它返回的是**未旋转**的
     原始像素宽高 -> 框的比例也算反了（纵向图给了个横向框）。

修法（三处，各自独立又互相配合）：
  A. `cacheThumb()`：先读 EXIF orientation，解码后 `pm.rotate(deg)` 把像素**物理转
     正**再 pack。这样缓存小图本身就是正的，且不需要 EXIF（Image 读到无 EXIF 的图
     不会瞎转）。
  B. `ensureMediaRatio()`：读 EXIF，5/6/7/8（90°/270°）时**交换宽高**再算比例 ——
     因为 Image 会按 AUTO 把内容转过来显示，框必须按"转完之后"的比例给。
  C. `mediaThumb()` / `mediaPreviewPage()` 的 `Image` 加
     `.orientation(ImageRotateOrientation.AUTO)` —— 官方推荐写法，
     对没 EXIF 的缓存小图等价于 UP（不转），不会双重旋转。

⚠️ 为什么不给 Image 加 `.rotate({angle})`：Image 自己已经会转，再转一次就是转两遍。
"""

import io
import sys

P = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'

SENT = 'private static exifDeg('


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

# ---------------------------------------------------------------- 1) exifDeg / isQuarter
OLD_1 = """    if (r < 0.45) {
      return 0.45;
    }
    return r;
  }
"""
NEW_1 = """    if (r < 0.45) {
      return 0.45;
    }
    return r;
  }

  /**
   * EXIF orientation -> 需要**顺时针**旋转的角度（度）。
   *
   * 相机拍的照片像素是"躺着"存的，靠 EXIF 的 Orientation 标记告诉观看者转多少度：
   *   1 不转 / 2 水平镜像 / 3 转 180° / 4 垂直镜像
   *   5 镜像后顺时针 270° / 6 顺时针 90° / 7 镜像后顺时针 90° / 8 顺时针 270°
   *
   * ⚠️ 镜像（2/4/5/7 里的镜像那一步）**放弃还原**：手机拍出来的照片几乎只会用到
   *    1/3/6/8，前置摄像头自拍偶有镜像，为它引入翻转逻辑不值当；
   *    这里只还原"旋转"那一部分（5 -> 270、7 -> 90）。
   *
   * ⚠️ `getImageProperty` 拿不到 EXIF 时会抛错（62980123 不支持 EXIF 解码）或返回
   *    `Unknown Value x`，本函数对任何非预期输入都返回 0（= 不转），安全降级。
   */
  private static exifDeg(ori: string): number {
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

  /** 这个角度会不会让宽高互换（只有 90°/270° 会，180° 不会） */
  private static isQuarter(deg: number): boolean {
    return deg === 90 || deg === 270;
  }
"""
s = rep(s, OLD_1, NEW_1, '1-exifDeg')

# ---------------------------------------------------------------- 2) ensureMediaRatio -> async + EXIF
OLD_2 = """  private ensureMediaRatio(path: string): void {
    if (path.length === 0 || this.mediaRatio.has(path) || this.mediaRatioBusy.has(path)) {
      return;
    }
    if (this.isVideoName(path)) {
      return;
    }
    this.mediaRatioBusy.add(path);
    try {
      const src: image.ImageSource = image.createImageSource(path);
      const info: image.ImageInfo = src.getImageInfoSync(0);
      const w: number = info.size.width;
      const h: number = info.size.height;
      if (w > 0 && h > 0) {
        this.mediaRatio.set(path, Index.clampRatio(w / h));
        this.thumbTick++;
      }
      try {
        src.release();
      } catch (x) {
        // 释放失败不影响显示
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `读图片尺寸失败: ${err.code} ${path}`);
    } finally {
      this.mediaRatioBusy.delete(path);
    }
  }
"""
NEW_2 = """  private async ensureMediaRatio(path: string): Promise<void> {
    if (path.length === 0 || this.mediaRatio.has(path) || this.mediaRatioBusy.has(path)) {
      return;
    }
    if (this.isVideoName(path)) {
      return;
    }
    this.mediaRatioBusy.add(path);
    try {
      const src: image.ImageSource = image.createImageSource(path);
      // 5.0.40：先问 EXIF 要不要转。`getImageProperty` 只有异步版，
      //         这也是本方法从同步改成 async 的唯一原因。
      let deg: number = 0;
      try {
        const ori: string = await src.getImageProperty(image.PropertyKey.ORIENTATION);
        deg = Index.exifDeg(ori);
      } catch (x) {
        // 没 EXIF / 这个格式不支持读 EXIF —— 按"不转"处理，退回老行为
        deg = 0;
      }
      const info: image.ImageInfo = src.getImageInfoSync(0);
      let w: number = info.size.width;
      let h: number = info.size.height;
      // ⚠️ 框按「Image 转完之后」的宽高算：Image 会自己按 EXIF 把内容转正，
      //    但 getImageInfoSync 给的是**没转**的原始像素尺寸 -> 90/270 时必须交换
      if (Index.isQuarter(deg)) {
        const t: number = w;
        w = h;
        h = t;
      }
      if (w > 0 && h > 0) {
        this.mediaRatio.set(path, Index.clampRatio(w / h));
        this.thumbTick++;
      }
      try {
        src.release();
      } catch (x) {
        // 释放失败不影响显示
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `读图片尺寸失败: ${err.code} ${path}`);
    } finally {
      this.mediaRatioBusy.delete(path);
    }
  }
"""
s = rep(s, OLD_2, NEW_2, '2-ensureMediaRatio')

# ---------------------------------------------------------------- 3) ratioOf 调用点
OLD_3 = """    if (!this.mediaRatio.has(path) && !this.isVideoName(path)) {
      this.ensureMediaRatio(path);
    }
"""
NEW_3 = """    if (!this.mediaRatio.has(path) && !this.isVideoName(path)) {
      // 5.0.40：`ensureMediaRatio` 改 async 了（要 await 读 EXIF）。
      //         这里故意**不 await** —— 比例是异步量出来的，量到之后 `thumbTick++`
      //         会把重绘踢起来；同步等反而会卡住渲染。内部已全 try/catch，不会抛。
      void this.ensureMediaRatio(path);
    }
"""
s = rep(s, OLD_3, NEW_3, '3-ratioOf-call')

# ---------------------------------------------------------------- 4) cacheThumb：物理旋转
OLD_4 = """      } else {
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
"""
NEW_4 = """      } else {
        const src: image.ImageSource = image.createImageSource(srcPath);
        // 5.0.40：解码**不会**应用 EXIF，而 pack 出来的 jpg 也不带 orientation，
        //         所以必须在这里把像素物理转正（见方法头注释的根因）。
        let deg: number = 0;
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
      }
"""
s = rep(s, OLD_4, NEW_4, '4-cacheThumb-rotate')

# ---------------------------------------------------------------- 5) 缩略图 Image -> AUTO
OLD_5 = """        Image(this.imageUri(path))
          .width(this.thumbW(path, maxSide))
          .height(this.thumbH(path, maxSide))
          .objectFit(ImageFit.Contain)
          .sourceSize({
            width: this.thumbW(path, maxSide) * 2,
            height: this.thumbH(path, maxSide) * 2
          })
"""
NEW_5 = """        Image(this.imageUri(path))
          .width(this.thumbW(path, maxSide))
          .height(this.thumbH(path, maxSide))
          .objectFit(ImageFit.Contain)
          // 5.0.40：按 EXIF 摆正显示方向。缓存小图没 EXIF，AUTO 等价于 UP，不会转两遍
          .orientation(ImageRotateOrientation.AUTO)
          .sourceSize({
            width: this.thumbW(path, maxSide) * 2,
            height: this.thumbH(path, maxSide) * 2
          })
"""
s = rep(s, OLD_5, NEW_5, '5-thumb-AUTO')

# ---------------------------------------------------------------- 6) 全屏预览 Image -> AUTO
OLD_6 = """        Image(this.imageUri(path))
          .width('100%')
          .height('100%')
          .objectFit(ImageFit.Contain)
          .scale({ x: this.imgScale, y: this.imgScale })
"""
NEW_6 = """        Image(this.imageUri(path))
          .width('100%')
          .height('100%')
          .objectFit(ImageFit.Contain)
          // 5.0.40：同上，全屏预览也按 EXIF 摆正
          .orientation(ImageRotateOrientation.AUTO)
          .scale({ x: this.imgScale, y: this.imgScale })
"""
s = rep(s, OLD_6, NEW_6, '6-preview-AUTO')

with io.open(P, 'w', encoding='utf-8', newline='') as f:
    f.write(s)
print('PATCH_OK  5.0.40 EXIF orientation')
