# -*- coding: utf-8 -*-
"""把 MEMORY.md 里两条「诊断结论」升级成「已落地（5.0.61）」，并补上配套细节。

幂等：sentinel = '5.0.61 已落地'，打过就干净跳过。
"""
import io
import sys

P = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
s = io.open(P, encoding='utf-8', newline='').read().replace('\r\n', '\n')
if u'5.0.61 已落地' in s:
    print('ALREADY APPLIED')
    sys.exit(0)

OLD66 = u'''6. ★★ **「界面又刷一遍」类抖动 = 显示身份绑在了会消失的东西上**：缩略图 src 从「沙箱原图」切到「缓存小图」，src 一变 ForEach key 就变 ⇒ 整行重建重解码。修法 = **让显示身份独立于沙箱副本是否存在**（缓存路径只由消息 id 决定、幂等）—— 与第 4 条同一思路。'''

NEW66 = u'''6. ★★ **「界面又刷一遍」类抖动 = 显示身份绑在了会消失的东西上**（**5.0.61 已落地**）：缩略图 src 从「沙箱原图」切到「缓存小图」，src 一变 ForEach key 就变 ⇒ 整行重建重解码。定案 = 拆**两个取源函数**：① `mediaSrcOf`（沙箱原图优先）= 预览/画廊/长按存图；② `mediaThumbSrcOf`（**缓存小图优先**）= 气泡缩略图 + key。缓存文件名只由「消息 id#媒体序号」决定（幂等）⇒ **不会消失的显示身份**。配套：**渲染到就预生成**（`maybePrefetchThumb`，不做全量预热；含同步 IO 必须先 `await yieldOnce()` 让出一拍）、落盘走 `setThumbOnly`（**只补 thumb、绝不碰已有相册 uri**，否则「点图跳相册」失效）。与第 4 条同一思路。'''

OLD77 = u'''- ★ **ForEach key 的粒度 = 重建范围**：key 里放**全局 tick**（`thumbTick`）⇒ 一个动作动全局 ⇒ 可见区全量重建；正确做法 = 放「每项自己的 signature」。'''

NEW77 = u'''- ★★ **ForEach key 的粒度 = 重建范围**（**5.0.61 已落地**）：key 里放**全局 tick**（`thumbTick`）⇒ 一个动作动全局 ⇒ 可见区全量重建；定案 = 放「**每项自己的 signature**」`thumbSigOf = id:源:比例:补转角` —— 必须覆盖**所有会异步变的要素**（比例是量出来的、转角是解码时定的），漏项症状 = 不再闪但图不出现/比例停在初值。
- ★ **显示源恒定化只花在「用户看得见差异」的地方**（5.0.61）：EXIF 方向图（`deg≠0`）的 `_full` 缓存与原图**逐字节相同** ⇒ 切换视觉零变化 ⇒ **不预生成**（否则每张竖拍照片多存一份原图，磁盘翻倍）。判据 = 路径含 `_full.`。
- ★ 预生成缩略图后两处判据必须跟着改（5.0.61）：①「已删」标记要补「**沙箱副本也没了**」—— 否则还没存过相册的新图会被标成「已删」；② 缩略图渲染分支的**媒体类型做成形参**（`isVideo` 由**消息本身**判断）—— 视频的缓存封面是普通 `.jpg`，看扩展名会丢 ▶ 角标。'''

for tag, old, new in [('R66', OLD66, NEW66), ('R77', OLD77, NEW77)]:
    n = s.count(old)
    assert n == 1, '锚点命中 %d 次 [%s]' % (n, tag)
    s = s.replace(old, new, 1)

io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('MEMORY UPDATED, size =', len(s.encode('utf-8')))
