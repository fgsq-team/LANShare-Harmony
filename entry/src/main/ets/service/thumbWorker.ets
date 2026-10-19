/**
 * 缩略图解码 worker（5.1.88）。
 *
 * ## 为什么需要它
 * `Index.cacheThumbInner` 里最重的一段（createImageSource -> EXIF 双路 ->
 * createPixelMap(desiredSize) -> scale -> packing -> 写盘）全在主线程同步/异步执行。
 * 批量收图（429+ 张）时这一段是主线程原生调用的主要占用源。
 * 本文件把整段搬进 taskpool 子线程，主线程只 `await taskpool.execute`。
 *
 * ## 契约（与主线程的接口，改两端必须同步改）
 * `decodeThumbTask(srcPath, tmpPath): Promise<number[]>`
 *   返回 [ok, deg, srcW, srcH, outW, outH]
 *   - ok=0：尺寸异常（>16384）或解码失败 —— 主线程跳过该图
 *   - ok=1 且 deg!=0：带 EXIF 方向，**不写文件**，主线程走「原图缓存」兜底
 *     （5.0.60 起不信任物理旋转，见 Index.cacheThumbInner 的长注释）
 *   - ok=1 且 deg=0：成功，jpg 已写入 tmpPath（主线程负责 rename 落位）
 *
 * ## ⚠️ @Concurrent 约束（2026-10-15 编译器实证，不是文档推测）
 * 1. **只能使用 import 变量或局部变量** —— 同文件的模块级函数/常量调用会被
 *    es2abc 直接拒：「Concurrent function should only use import variable or
 *    local variable」。所以纯函数与常量全部拆到 thumbExif.ets，以 import 引入；
 * 2. 不能用 this / 不依赖任何 class 实例；
 * 3. **不打日志** —— 日志模块不在本文件 import（hilog 跨线程调用未经本项目验证），
 *    诊断日志由主线程在拿到返回码后补打（EXIF 明细会少一行，已知代价）。
 */
import { image } from '@kit.ImageKit';
import { fileIo } from '@kit.CoreFileKit';
import { THUMB_SIDE, MAX_SIDE, EXIF_HEAD, exifDegOf, jpegExifDegOf } from './thumbExif';

// ---------------------------------------------------------------------------
// taskpool 入口
// ---------------------------------------------------------------------------

/**
 * 解码 srcPath 成 320px jpg 缩略图，写入 tmpPath。
 *
 * @returns [ok, deg, srcW, srcH, outW, outH]，语义见文件头「契约」
 */
@Concurrent
export async function decodeThumbTask(srcPath: string, tmpPath: string): Promise<number[]> {
  let src: image.ImageSource | null = null;
  let pm: image.PixelMap | null = null;
  let packer: image.ImagePacker | null = null;
  try {
    src = image.createImageSource(srcPath);
    // EXIF 双路：系统 API 读格式 + 自己读字节补位（5.0.40 / 5.0.42 的规则）
    let degApi: number = 0;
    try {
      const oriRaw: string = await src.getImageProperty(image.PropertyKey.ORIENTATION);
      degApi = exifDegOf(oriRaw);
    } catch (x) {
      // 没 EXIF / 这个格式不支持读 EXIF —— 按不转处理
      degApi = 0;
    }
    const degRaw: number = jpegExifDegOf(srcPath);
    const deg: number = degApi !== 0 ? degApi : degRaw;
    const info: image.ImageInfo = src.getImageInfoSync(0);
    const srcW: number = info.size.width;
    const srcH: number = info.size.height;
    // 极端尺寸保护：宽度上万的全景图即使按 320 出图，部分实现仍会先分配整张缓冲
    if (srcW <= 0 || srcH <= 0 || srcW > MAX_SIDE || srcH > MAX_SIDE) {
      return [0, 0, 0, 0, 0, 0];
    }
    if (deg !== 0) {
      // 5.0.60：带方向直接交主线程走原图缓存，不信任物理旋转
      return [1, deg, srcW, srcH, 0, 0];
    }
    // desiredSize 直接按目标尺寸解码 —— 4K 原图整张进内存太贵
    const longest: number = srcW > srcH ? srcW : srcH;
    const s: number = longest > THUMB_SIDE ? THUMB_SIDE / longest : 1;
    pm = await src.createPixelMap({
      desiredSize: {
        width: Math.max(1, Math.round(srcW * s)),
        height: Math.max(1, Math.round(srcH * s))
      },
      rotate: deg,
      editable: true
    });
    let ow: number = 0;
    let oh: number = 0;
    const inf: image.ImageInfo = pm.getImageInfoSync();
    ow = inf.size.width;
    oh = inf.size.height;
    const longest2: number = ow > oh ? ow : oh;
    if (longest2 > THUMB_SIDE) {
      await pm.scale(THUMB_SIDE / longest2, THUMB_SIDE / longest2);
      const inf2: image.ImageInfo = pm.getImageInfoSync();
      ow = inf2.size.width;
      oh = inf2.size.height;
    }
    packer = image.createImagePacker();
    const buf: ArrayBuffer = await packer.packing(pm, { format: 'image/jpeg', quality: 80 });
    // 写临时文件，主线程 rename 落位（保证 5.0.67 的「已就绪不重写」语义）
    const fo: fileIo.File = fileIo.openSync(tmpPath,
      fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);
    try {
      fileIo.writeSync(fo.fd, buf);
    } finally {
      fileIo.closeSync(fo);
    }
    return [1, 0, srcW, srcH, ow, oh];
  } catch (e) {
    return [0, 0, 0, 0, 0, 0];
  } finally {
    // 5.0.50：release 的 Promise 异常态可能永不 settle，只挂 catch、绝不 await
    if (src !== null) {
      src.release().catch(() => {
        // 释放失败 / 已释放过，都不影响结果
      });
    }
    if (pm !== null) {
      pm.release().catch(() => {
        // 释放失败 / 已释放过，都不影响结果
      });
    }
    if (packer !== null) {
      packer.release().catch(() => {
        // 释放失败 / 已释放过，都不影响结果
      });
    }
  }
}
