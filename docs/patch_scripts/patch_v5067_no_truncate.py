# -*- coding: utf-8 -*-
"""v5.0.67 —— 治「存相册成功后快速闪一下」。

vivi 2026-10-02 反馈（5.0.66 修完功能回归后）：存相册成功之后又快速闪一下。

★★ 排查结论：**不是 key 变，也不是重渲染次数** —— 是**缓存文件被原地覆盖**。

逐条排除（都查过代码）：
  ① `thumbSigOf` 的 `src` 变？—— 不变。`cacheThumb` 写的路径是
     `${filesDir}/album_thumbs/<key>.jpg`，**只由 key 决定 ⇒ 幂等**，
     预生成与存相册写的是**同一个路径**。
  ② `rot` 变？—— 不变。`setAlbumIndex` / `setThumbOnly` 都是
     `albumRotMap.set(thumb, rot)`，同一 thumb 路径 ⇒ 同一 rot 键。
  ③ `mediaGoneFromAlbum` 翻转？—— 不翻转。存相册后 part 0 有了 uri ⇒ 直接 false。
  ④ `groupAllMedia` / `rows` 变？—— 不变。两者都只读 `mediaNamesOf`（消息本身），
     5.0.55 定的「显示聚合 ≠ 记账聚合」边界让它们与沙箱文件无关。
  ⑤ 重渲染次数？—— 5.0.64 的闸门已把存相册收尾的 4 次换引用合成 1 次。

★★★ 真正的元凶（第 4274 行附近）：
     `cacheThumbInner` 打开输出文件用的是
       `fileIo.OpenMode.CREATE | READ_WRITE | **TRUNC**`
     而它**没有「已存在就跳过」的短路** ⇒
       预生成阶段（5.0.63 加的 `maybePrefetchThumb`）已经写好了
       `album_thumbs/<key>.jpg`，此时气泡正在显示它；
       存相册阶段又对**同一路径** cacheThumb 一次 ⇒ **文件被清空重写**；
       `Image` 正好在读这个文件 ⇒ **闪一下**。
     ⇒ 这是**文件层面的原地覆盖**，与渲染机制完全无关，所以
       「合并重渲染」「改 key」「改 rows」全都治不了它。

修法：**缓存已存在就复用，不重写**。
     在 `cacheThumbInner` 里、写文件之前加存在性检查：
     文件存在且**非空** ⇒ 直接返回该路径（不截断、不重写）。
     ⚠️ 为什么要额外判「非空」：TRUNC 打开的瞬间文件大小就是 0，
        若此刻另一个协程正在写，存在性检查会误判为「已就绪」而返回半截文件。
        判 size>0 才能保证拿到的是完整文件。
     ⚠️ 这条同时也是 5.0.45 那条注释的补全 —— 手动存图路径早就写了
        「源文件就是已有缓存缩略图时不要再 cacheThumb 一遍」，但**自动存相册
        这条路径没有同样的保护**，属于遗漏。

幂等：哨兵判重 + 全量校验后统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
VER = os.path.join(ROOT, 'AppScope', 'app.json5')

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()
if '★ 5.0.67' in s_idx:
    print('ALREADY APPLIED'); sys.exit(0)

BK = os.path.join(ROOT, r'docs\backups')
os.makedirs(BK, exist_ok=True)
for p, tag in ((IDX, 'Index.ets.v5067pre'), (VER, 'app.json5.v5067pre')):
    io.open(os.path.join(BK, tag), 'w', encoding='utf-8', newline='\n')\
      .write(io.open(p, encoding='utf-8').read())
print('备份完成')

# =====================================================================
# 改 1：cacheThumbInner 加「已存在且非空就复用」的短路
# =====================================================================
OLD1 = """      const out: string = `${dir}/${id}.jpg`;
      const fo: fileIo.File = fileIo.openSync(out,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);"""
NEW1 = """      const out: string = `${dir}/${id}.jpg`;
      // ★★★ 5.0.67：**缓存已存在且非空 ⇒ 直接复用，不截断重写。**
      //
      // 背景：预生成（5.0.63 的 maybePrefetchThumb）与存相册（autoSaveAlbumBatch
      // 里的 cacheThumb）写的是**同一个路径** `${filesDir}/album_thumbs/<key>.jpg`
      // —— 路径只由 key 决定，幂等。而下面的 openSync 带 **TRUNC**，会把已有文件
      // 清空重写；此刻气泡正在显示这张图，`Image` 读到被截断的内容 ⇒ **闪一下**。
      //   ⇒ 这是**文件层面的原地覆盖**，与 key / 重渲染次数 / rows 结构全都无关，
      //     所以那些手段一个都治不了它。只能「不覆盖」。
      //
      // ⚠️ 为什么必须额外判「非空」：TRUNC 打开的瞬间文件大小就是 0。
      //   若此刻另一个协程正在写（同 key 的预生成与存相册可能并发），
      //   只判「存在」会误判为已就绪而返回**半截文件**，比闪更糟。
      // ⚠️ 这是 5.0.45 那条注释（「源文件就是已有缓存缩略图时不要再 cacheThumb
      //   一遍，否则等于自己解码自己再写回同一路径，有把缓存图写坏的风险」）
      //   在**自动存相册**路径上的补全 —— 手动那条早有保护，自动这条一直漏着。
      try {
        const st: fileIo.Stat = fileIo.statSync(out);
        if (st.size > 0) {
          Log.i(TAG, `缓存小图已就绪，复用不重写（避免截断闪烁）: ${Index.baseName(out)}`);
          return out;
        }
      } catch (x) {
        // 不存在（或读不到）—— 正常情况，继续生成
      }
      const fo: fileIo.File = fileIo.openSync(out,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);"""

OLD2 = '"versionCode": 5000066'
NEW2 = '"versionCode": 5000067'

s2 = s_idx
assert s2.count(OLD1) == 1, '改1 锚点命中 %d' % s2.count(OLD1)
s2 = s2.replace(OLD1, NEW1, 1)

v2 = s_ver
assert v2.count(OLD2) == 1, 'versionCode 锚点异常'
v2 = v2.replace(OLD2, NEW2, 1)
assert v2.count('"versionName": "5.0.66"') == 1
v2 = v2.replace('"versionName": "5.0.66"', '"versionName": "5.0.67"', 1)

# 不变量：短路必须在 TRUNC 之前
assert s2.index('缓存小图已就绪，复用不重写') < s2.index('fileIo.OpenMode.TRUNC')
# fileIo.Stat 类型在本文件已有先例（albumAssetAlive 用过 statSync）
assert 'fileIo.statSync' in s2
assert len(s2) > len(s_idx)

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s2)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(v2)
print('OK  Index.ets %d -> %d  |  5000067' % (len(s_idx), len(s2)))
