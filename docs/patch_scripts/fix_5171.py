#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.71：存相册时**跳过缩略图解码**（改懒生成）+ 缩略图 320→224（幂等）

## 依据（vivi 2026-10-05 15:23~15:24 真机 5.1.70 计时日志）
426 张，11 批：
```
[耗时] 存相册 40 项：拷贝 3752ms + 解码缩略图 7133ms + 落盘删沙箱 99ms   ← 首批预热
[耗时] 存相册 40 项：拷贝 2152ms + 解码缩略图 1347ms + 落盘删沙箱 76ms
... 共 11 批
```
| 段 | 累计 | 占比 | 性质 |
|---|---|---|---|
| 拷贝 | 18100 ms | 50% | **IO**（540MB / 18.1s ≈ 30MB/s） |
| **解码缩略图** | **17323 ms** | **48%** | **纯 CPU**（426 张 / 17.3s ≈ 41ms/张） |
| 落盘删沙箱 | 640 ms | 2% | 一次性 |
| 合计 | 36063 ms | | |

★ **近一半是纯计算，不是 IO 下限** ⇒ **可以砍**。
（我此前判断「3.5s 是 IO 物理下限」是**错的**，计时日志推翻了它。）

## 改法
### A. 存相册时**不做 `cacheThumb`**
依据：`mediaThumbSrcOf` 的注释（5.0.63）明确写了
> 「缓存没有时统一走下方兜底（**可能返回空串 = 占位**），源**全程只有 cache 一个值**」

⇒ 缩略图**已经是懒生成**（`maybePrefetchThumb`，渲染到才补）。
所以存相册阶段跳过解码**不会导致气泡永久空白**：
  - 若沙箱副本还在（用户取消存相册 / 弹框失败）⇒ 懒生成照常补
  - 若沙箱已删 ⇒ `mediaSrcOf` 走 `albumPartOf(m.id, k, 1)` 拿不到图
    ⇒ **需要保证**：存相册时仍然记下相册 URI（part 0），
      用户点气泡能跳系统相册看大图（这是 5.0.61 起就有的能力）。
⚠️ **气泡缩略图会短暂占位**（几十 ms，懒生成补上）—— 这是**已知取舍**，
   不是新 bug（5.0.63 早就选了「宁可空拍几十 ms，也不让显示源变」）。

### B. 缩略图 320 → 224
气泡是 **48vp**；224px 足够覆盖 2~3 倍屏密度。
★ 解码耗时与像素数近似线性 ⇒ 320²/224² = 2.04 ⇒ 理论上省一半解码时间。
（真正省时间的是 A；B 是叠加的额外收益。）

## 不动的东西
- `cacheThumb` 本身（懒生成路径仍在用）
- `mediaThumbSrcOf` 的「不闪」策略（5.0.63 定案，动了会闪）
- 相册 URI 的记录（part 0 必须写，否则点图跳不了相册）
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = '5.1.71'
REL = 'entry/src/main/ets/pages/Index.ets'

EDITS = []


def edit(old, new, tag):
    EDITS.append((old, new, tag))


# ---- A1 主循环：跳过 cacheThumb ----
edit(
    """          // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反
          // ★ 5.1.70：分段计时
          const t1: number = Date.now();
          const thumb: string = await this.cacheThumb(ctx, batchPaths[i], batchKeys[i]);
          tThumb += Date.now() - t1;
          const rot: number = this.service.rotOf(thumb) ?? 0;""",
    """          // ★★ 5.1.71 A：**存相册阶段不再生成缩略图**（省 48% 的 CPU 开销）。
          //
          // 【为什么可以跳过】`mediaThumbSrcOf` 的注释（5.0.63）已定案：
          //   > 「缓存没有时统一走下方兜底（**可能返回空串 = 占位**），
          //   >  源**全程只有 cache 一个值**」
          // 而缩略图**本来就是懒生成**（`maybePrefetchThumb`，渲染到才补）。
          // ⇒ 这里跳过，气泡只是**短暂占位几十 ms**，随后懒生成补上。
          //   ⚠️ 这**不是新 bug**，5.0.63 早就选了「宁可空拍几十 ms，
          //     也不让显示源中途变一次」（变一次 ⇒ ForEach key 变 ⇒ 整屏闪）。
          //
          // 【仍然必须做的两件】
          //   ① 记**相册 URI**（part 0）⇒ 用户点气泡能跳系统相册看大图；
          //   ② 删沙箱副本（走 `toDelete`，循环外统一做）。
          //
          // 【数据依据】vivi 2026-10-05 真机 426 张计时：
          //   拷贝 18100ms(50%) + **解码缩略图 17323ms(48%)** + 落盘删沙箱 640ms(2%)
          //   ⇒ 解码是纯 CPU（41ms/张），**不是 IO 下限，可以砍**。
          //
          // 【顺带】沙箱副本若还在（用户取消存相册 / 弹框失败），
          //   `maybePrefetchThumb` 会在滚动到时正常补缩略图。
          const thumb: string = '';""",
    'A1 跳过 cacheThumb')

# ---- A2 计时：不再累加 tThumb，改为说明 ----
edit(
    """      const tDel: number = Date.now() - tDel0;
      this.service.logAuto(`[耗时] 存相册 ${gotUris.length} 项：`
        + `拷贝 ${tCopy}ms + 解码缩略图 ${tThumb}ms + 落盘删沙箱 ${tDel}ms`
        + `（让帧 ${Index.ALBUM_YIELD_EVERY} 张/次）`);""",
    """      const tDel: number = Date.now() - tDel0;
      // ★ 5.1.71 A：解码已跳过，`tThumb` 恒为 0，保留字段便于对照历史日志。
      this.service.logAuto(`[耗时] 存相册 ${gotUris.length} 项：`
        + `拷贝 ${tCopy}ms + 解码缩略图 ${tThumb}ms + 落盘删沙箱 ${tDel}ms`
        + `（让帧 ${Index.ALBUM_YIELD_EVERY} 张/次，缩略图改懒生成）`);""",
    'A2 计时说明')

# ---- B 缩略图 320 → 224 ----
edit(
    """        const longest: number = w > h ? w : h;
        const s: number = longest > 320 ? 320 / longest : 1;""",
    """        const longest: number = w > h ? w : h;
        // ★★ 5.1.71 B：320 → **224**。气泡是 48vp，224px 足够覆盖 2~3 倍屏密度。
        //   解码耗时与像素数近似线性 ⇒ (224/320)² ≈ 0.49 ⇒ 理论上省一半。
        //   （真正省时间的是「存相册阶段跳过解码」；这条是叠加收益，
        //     且**对懒生成路径同样有效** —— 滚动到时生成的缩略图也变小。）
        const s: number = longest > 224 ? 224 / longest : 1;""",
    'B1 cacheThumb 320→224')

# ⚠️ 第二处 320 在 `ensureMediaRatio` 的**视频封面**分支里（5630），
#    第一次自检就是被它抓出来的（`320 阈值仍在`）⇒ 语义自检有效。
edit(
    """            const longest: number = vw > vh ? vw : vh;
            if (longest > 320) {
              const s: number = 320 / longest;
              await pm.scale(s, s);
            }""",
    """            const longest: number = vw > vh ? vw : vh;
            // ★ 5.1.71 B：视频封面同样 320 → 224（与 cacheThumb 的图片缩略图一致）。
            //   ⚠️ 这处是**第一次语义自检抓出来的**（'320 阈值仍在'）——
            //   漏改会让视频封面仍是 320px，两类媒体的缩略图尺寸不一致。
            if (longest > 224) {
              const s: number = 224 / longest;
              await pm.scale(s, s);
            }""",
    'B2 视频封面 320→224')


def main():
    path = os.path.join(ROOT, REL)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()

    if PROBE in src:
        print('SKIP 已应用')
        return

    for old, new, tag in EDITS:
        if src.count(old) != 1:
            print('ABORT %s count=%d' % (tag, src.count(old)))
            print(repr(old[:160]))
            sys.exit(1)
        src = src.replace(old, new, 1)

    # 语义自检
    if "const thumb: string = '';" not in src:
        print('ABORT: thumb 空串未写入')
        sys.exit(1)
    if 'longest > 320' in src:
        print('ABORT: 320 阈值仍在')
        sys.exit(1)
    if 'longest > 224' not in src:
        print('ABORT: 224 未写入')
        sys.exit(1)
    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)

    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('OK %s (%d 处)' % (REL, len(EDITS)))
    print('自检: 跳过 cacheThumb ✓  224 阈值 ✓  320 已移除 ✓')


if __name__ == '__main__':
    main()
