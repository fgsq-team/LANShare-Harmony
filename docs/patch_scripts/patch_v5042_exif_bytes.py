# -*- coding: utf-8 -*-
"""
5.0.42：修「纵拍照片存进相册后缩略图变横」——第三次修复。

现象：弹窗那一刻（显示沙箱原图）方向正常；保存完成后（沙箱副本已删、改用 pack 出来的
     320px 小图）方向就变了。

为什么 5.0.40 / 5.0.41 都没修好：两版都假设「系统 getImageProperty(ORIENTATION) 能给出
方向」。但它的返回格式各版本/各设备不统一（'6' / 'Unknown Value 6' / 'Right-top' 都见过），
一旦解析不出就退化成 0（= 不转），于是 pack 出来的小图是**物理躺着**的，而它又不带 EXIF，
Image 也帮不上忙 —— 表现跟没改一模一样。

这次不再依赖系统 API 的返回格式：
  ① 自己读 JPEG 字节拿 EXIF Orientation（EXIF 放哪个段是标准规定的，跟设备实现无关）；
  ② pack 完把小图再读回来验一次横竖性（前面任何一环出问题都会在这里暴露）；
  ③ 万一还是不对，直接复制原文件兜底 —— 那份带 EXIF，Image 自己会转，方向必定正确。

幂等：靠哨兵串判重，重跑直接跳过。
"""
import io
import sys

P = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'

s = io.open(P, encoding='utf-8', newline='').read()

SENT = 'private static jpegExifDeg('
if SENT in s:
    print('ALREADY APPLIED')
    sys.exit(0)

orig = s


def rep(old, new, tag):
    """精确替换：old 必须恰好出现一次。"""
    cnt = s.count(old)
    if cnt != 1:
        print('ERROR [%s]: 锚点出现 %d 次' % (tag, cnt))
        sys.exit(1)
    return s.replace(old, new, 1)


def rep_block(start_mark, end_mark, new, tag):
    """按起止标记整块替换（起标记必须唯一，终标记取其后的第一次出现）。"""
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
    return s[:a] + new + s[b:]


# ---------------------------------------------------------------- 1. 新增静态方法：字节级 EXIF 解析
NEW_HELPERS = '''  /**
   * 5.0.42：自己从 JPEG 的字节里读 EXIF Orientation。
   *
   * 为什么不再只信系统 `getImageProperty(ORIENTATION)`：它返回的东西各版本/各设备不统一
   * （'6' / 'Unknown Value 6' / 'Right-top' 都见过），一旦对不上就退化成 0（= 不转），
   * 5.0.40 / 5.0.41 两版都栽在这上面。而 EXIF 放在 JPEG 的哪个段里是**标准规定的**，
   * 直接读字节跟设备实现无关。
   *
   * @returns 需要顺时针旋转的度数（0 / 90 / 180 / 270）；不是 JPEG 或没 EXIF 一律返回 0。
   */
  private static jpegExifDeg(path: string): number {
    let f: fileIo.File | null = null;
    try {
      f = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);
      // EXIF 一定在 JPEG 头部的 APP1 段里，读 128K 足够（有些机器把缩略图也塞进来）
      const head: ArrayBuffer = new ArrayBuffer(131072);
      const n: number = fileIo.readSync(f.fd, head);
      if (n < 4) {
        return 0;
      }
      const b: Uint8Array = new Uint8Array(head, 0, n);
      if (b[0] !== 0xFF || b[1] !== 0xD8) {
        return 0; // 不是 JPEG（HEIC / PNG 之类）—— 交给系统 API 那一路
      }
      let i: number = 2;
      while (i + 4 <= n) {
        if (b[i] !== 0xFF) {
          i = i + 1;
          continue;
        }
        const mk: number = b[i + 1];
        if (mk === 0xD8 || mk === 0x01 || (mk >= 0xD0 && mk <= 0xD7)) {
          i = i + 2; // 这些标记不带长度字段
          continue;
        }
        if (mk === 0xDA) {
          break; // SOS：图像数据开始了，EXIF 只可能在它之前
        }
        const segLen: number = (b[i + 2] << 8) | b[i + 3];
        if (mk === 0xE1) {
          // APP1：payload 以 "Exif\\0\\0" 开头的才是 EXIF（别的 APP1 比如 XMP 不是）
          const p: number = i + 4;
          if (p + 12 <= n && b[p] === 0x45 && b[p + 1] === 0x78 && b[p + 2] === 0x69 &&
              b[p + 3] === 0x66 && b[p + 4] === 0x00 && b[p + 5] === 0x00) {
            return Index.tiffDeg(b, p + 6, n);
          }
        }
        if (segLen < 2) {
          break;
        }
        i = i + 2 + segLen;
      }
      return 0;
    } catch (e) {
      return 0;
    } finally {
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (x) {
          // 忽略
        }
      }
    }
  }

  /** 从 EXIF 的 TIFF 头里找出 IFD0 的 Orientation（tag 0x0112） */
  private static tiffDeg(b: Uint8Array, tiff: number, n: number): number {
    if (tiff + 8 > n) {
      return 0;
    }
    const le: boolean = (b[tiff] === 0x49 && b[tiff + 1] === 0x49); // 'II' 小端
    const be: boolean = (b[tiff] === 0x4D && b[tiff + 1] === 0x4D); // 'MM' 大端
    if (!le && !be) {
      return 0;
    }
    const ifd: number = tiff + Index.u32(b, tiff + 4, le);
    if (ifd < 0 || ifd + 2 > n) {
      return 0;
    }
    const cnt: number = Index.u16(b, ifd, le);
    for (let k: number = 0; k < cnt; k++) {
      const e: number = ifd + 2 + k * 12;
      if (e + 12 > n) {
        break;
      }
      if (Index.u16(b, e, le) === 0x0112) {
        // tag = Orientation。type 是 SHORT 时值就塞在 value 字段里，取低 16 位即可
        return Index.degOfOri(Index.u16(b, e + 8, le));
      }
    }
    return 0;
  }

  /** 按字节序读 16 位无符号 */
  private static u16(b: Uint8Array, o: number, le: boolean): number {
    return le ? (b[o] | (b[o + 1] << 8)) : ((b[o] << 8) | b[o + 1]);
  }

  /** 按字节序读 32 位无符号 */
  private static u32(b: Uint8Array, o: number, le: boolean): number {
    return le ? ((b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0)
      : (((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0);
  }

  /** EXIF Orientation -> 需要顺时针转多少度（2/4/5/7 带镜像，这里只还原旋转那部分） */
  private static degOfOri(v: number): number {
    if (v === 3 || v === 4) {
      return 180;
    }
    if (v === 6 || v === 7) {
      return 90;
    }
    if (v === 5 || v === 8) {
      return 270;
    }
    return 0;
  }

'''

s = rep_block('\n  /** 这个角度会不会让宽高互换（只有 90°/270° 会，180° 不会） */',
              '\n  /** 这个角度会不会让宽高互换（只有 90°/270° 会，180° 不会） */',
              NEW_HELPERS, 'insert-exif-helpers')

# ---------------------------------------------------------------- 2. thumbOri：-1 = 带 EXIF 的原图拷贝 -> AUTO
OLD_ORI = '''    const v: number | undefined = this.mediaRot.get(path);
    if (v === undefined) {
      return ImageRotateOrientation.AUTO;
    }
'''
NEW_ORI = '''    const v: number | undefined = this.mediaRot.get(path);
    // undefined = 沙箱原图；-1 = 原图拷贝兜底（5.0.42，见 cacheThumb）—— 两者**都带 EXIF**，
    // 让 Image 自己读 EXIF 转，我们再显式给角度就是转两遍。
    if (v === undefined || v === -1) {
      return ImageRotateOrientation.AUTO;
    }
'''
s = rep(OLD_ORI, NEW_ORI, 'thumbOri')

# ---------------------------------------------------------------- 3. 整体重写 cacheThumb
NEW_THUMB = '''  /**
   * 把收到的图/视频做成 320px 小图存进 `cacheDir/album_thumbs`，
   * 供「沙箱副本已删」之后继续显示缩略图用。
   *
   * ⚠️ 5.0.42 为什么又重写一遍：5.0.40 / 5.0.41 都没修好「纵拍照片存进相册后缩略图变横」。
   *    根因是**旋转角度拿到的其实是 0** —— 系统 `getImageProperty(ORIENTATION)` 的返回值
   *    格式各版本不统一，解析不出就按「不转」处理，于是 pack 出来的小图是**物理躺着**的，
   *    而它又不带 EXIF，Image 也帮不上忙。
   *    这次不再猜：① **自己读 JPEG 字节拿 EXIF 方向**（位置是标准规定的，与设备实现无关）；
   *    ② pack 完**把小图再读回来验一次**横竖性；③ 万一还是不对，
   *    **直接复制原文件兜底**（那份带 EXIF，交给 Image 自己转）—— 宁可多占空间，也不给错方向。
   */
  private async cacheThumb(ctx: common.UIAbilityContext, srcPath: string,
                           id: string): Promise<string> {
    let pm: image.PixelMap | null = null;
    let gen: media.AVImageGenerator | null = null;
    let f: fileIo.File | null = null;
    // 这三项要带到方法末尾做「最终验证」，所以提到外层声明
    let srcW: number = 0;
    let srcH: number = 0;
    let deg: number = 0;
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
        // 5.0.40：解码**不会**应用 EXIF，而 pack 出来的 jpg 也不带 orientation，
        //         所以必须在这里把像素物理转正（见方法头注释的根因）。
        let degApi: number = 0;
        let degRaw: number = 0;
        let oriRaw: string = '';
        try {
          oriRaw = await src.getImageProperty(image.PropertyKey.ORIENTATION);
          degApi = Index.exifDeg(oriRaw);
        } catch (x) {
          // 没 EXIF / 这个格式不支持读 EXIF —— 按不转处理
          degApi = 0;
        }
        // 5.0.42：系统 API 的返回值格式在不同版本/设备上不统一，解析不出来就是 0。
        //         用「自己读 JPEG 字节」的结果补位 —— EXIF 在哪儿是标准规定的，与实现无关。
        degRaw = Index.jpegExifDeg(srcPath);
        deg = degApi !== 0 ? degApi : degRaw;
        // 三个值都打出来：下次再不对，一眼看出到底卡在哪一环
        Log.i(TAG, `EXIF ${Index.baseName(srcPath)}: api='${oriRaw}'->${degApi}, bytes=${degRaw}, use=${deg}`);
        const info: image.ImageInfo = src.getImageInfoSync(0);
        srcW = info.size.width;
        srcH = info.size.height;
        const w: number = srcW;
        const h: number = srcH;
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
          this.pendingRot = deg;
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
      // ---- 5.0.42 终极验证：把刚写出去的小图再读回来，看它的横竖性对不对 ----
      // 前面任何一环（EXIF 解析 / decode rotate / pm.rotate / packing）出问题，都会在这里暴露。
      if (srcW > 0 && srcH > 0) {
        let ok: boolean = true;
        let gw: number = 0;
        let gh: number = 0;
        try {
          const chk: image.ImageSource = image.createImageSource(out);
          const ci: image.ImageInfo = chk.getImageInfoSync(0);
          gw = ci.size.width;
          gh = ci.size.height;
          try {
            chk.release();
          } catch (x) {
            // 忽略
          }
          // 「转完之后该是竖的还是横的」：只有 90/270 会翻转横竖性，180 不会
          const wantTall: boolean = Index.isQuarter(deg) ? !(srcH > srcW) : (srcH > srcW);
          const gotTall: boolean = gh > gw;
          ok = (wantTall === gotTall);
        } catch (x) {
          // 校验本身失败就别折腾了，按成功处理（宁可不兜底，也别把能用的图丢掉）
          ok = true;
        }
        if (!ok) {
          Log.w(TAG, `缩略图方向仍未修正 ${gw}x${gh}，改用原图缓存: ${srcPath}`);
          // 兜底：直接复制沙箱原文件 —— 它**带着 EXIF**，Image 会自己转正，
          //       跟「弹窗那一刻显示沙箱原图」是完全同一条路，方向必定正确。
          //       代价是 cacheDir 里多一份原图（只在前面全失败时才会走到这儿）。
          try {
            fileIo.unlinkSync(out);
          } catch (x) {
            // 删不掉也无所谓，下面换文件名
          }
          let ext: string = '';
          const dot: number = srcPath.lastIndexOf('.');
          if (dot >= 0 && srcPath.length - dot <= 6) {
            ext = srcPath.substring(dot);
          }
          const fullPath: string = `${dir}/${id}_full${ext}`;
          try {
            fileIo.unlinkSync(fullPath);
          } catch (x) {
            // 目标不存在 —— 正常情况
          }
          try {
            fileIo.copyFileSync(srcPath, fullPath);
            const swapF: boolean = Index.isQuarter(deg);
            const fw: number = swapF ? srcH : srcW;
            const fh: number = swapF ? srcW : srcH;
            this.mediaRatio.set(fullPath, Index.clampRatio(fw / fh));
            // -1 = 这份缓存**保留了 EXIF** —— 显示层必须 AUTO，让 Image 自己转
            this.mediaRot.set(fullPath, -1);
            this.thumbTick++;
            return fullPath;
          } catch (x) {
            Log.w(TAG, `原图缓存兜底也失败，只能沿用小图: ${srcPath}`);
          }
        }
      }
      // 记下真实比例：气泡的缩略图框按它算，不然又变正方形。
      // ⚠️ 物理没转成、要靠显示层补转时，`iw/ih` 还是「躺着」的比例 ——
      //    框必须按**转完之后**的给（90/270 就是交换宽高），否则内容转了框没转，
      //    Contain 出来就是「竖图塞在横框里」。
      if (iw > 0 && ih > 0) {
        const swap: boolean = Index.isQuarter(this.pendingRot);
        const rw: number = swap ? ih : iw;
        const rh: number = swap ? iw : ih;
        this.mediaRatio.set(out, Index.clampRatio(rw / rh));
        this.thumbTick++;
      }
      // 缓存小图是「我们自己 pack 的、不带 EXIF」的图，Image 不会替我们转，
      // 所以这里必须明确告诉显示层还要不要补转（0 = 已物理转正，别再转）。
      this.mediaRot.set(out, this.pendingRot);
      this.pendingRot = 0;
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
'''

s = rep_block('\n  private async cacheThumb(ctx: common.UIAbilityContext, srcPath: string,',
              '\n  /** 相册索引的第 n 段：0 = 相册 URI，1 = 缩略图缓存路径 */',
              NEW_THUMB, 'rewrite-cacheThumb')

# ---------------------------------------------------------------- 4. 头部变更表
OLD_DOC = ' * | 留了排查入口 | `cacheThumb()` 里 `Log.i(TAG, "EXIF <名>: ori=\'<原值>\' -> N度")` —— 再不对就抓这条日志，一眼看出设备上到底返回什么 |\n'
NEW_DOC = (' * | 留了排查入口 | `cacheThumb()` 里 `Log.i(TAG, "EXIF <名>: ori=\'<原值>\' -> N度")` —— 再不对就抓这条日志，一眼看出设备上到底返回什么 |\n'
           ' * | 5.0.41 也没修好（"弹窗时正常、保存完就变"）| 说明**旋转角度拿到的还是 0**。弹窗那一刻显示的是沙箱原图，Image 自己读 EXIF 转正，所以看着正常；保存后沙箱副本被删、改用我们 pack 的小图，那张图物理躺着又没 EXIF → 变横。⚠️ 反推：**"弹窗时正常"不能证明 EXIF 读到了** —— 那时即使 EXIF 没读到，Image 也能靠 AUTO 转对，只是框比例错（留白），用户不一定察觉 |\n'
           ' * | ★ 不再靠系统 API 猜格式（5.0.42）| 三件事：① **自己读 JPEG 字节拿 EXIF**（`jpegExifDeg()`：SOI→APP1→"Exif\\0\\0"→TIFF IFD0→tag 0x0112，位置是标准规定的，与设备实现无关）；② pack 完**把小图再读回来验横竖性**（前面任一环出问题都会暴露）；③ 仍不对就**复制原文件兜底**（带 EXIF，Image 自己转正，方向必定正确，代价只是多占空间）。`mediaRot` 新增 `-1` = "这份缓存带 EXIF，显示层用 AUTO" |\n')
s = rep(OLD_DOC, NEW_DOC, 'header-doc')

if s == orig:
    print('NO CHANGE')
    sys.exit(1)

io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('PATCH OK')
