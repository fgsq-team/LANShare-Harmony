# -*- coding: utf-8 -*-
"""向 skill `harmonyos-arkui-ui-pitfalls` 追加第三十节（5.0.61 的教训）。

追加型写入 —— 开头必须先做 sentinel 判重（重跑要干净跳过，不是报错）。
"""
import io
import sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'

s = io.open(P, encoding='utf-8').read()
SENT = u'## 三十、`ForEach` key 里的**全局计数器**'
if SENT in s:
    print('ALREADY APPLIED')
    sys.exit(0)

block = u'''

---

## 三十、`ForEach` key 里的**全局计数器** = 一动作动全局；显示身份别绑在「会消失的东西」上

### 症状（真实案例，LANShareV5 5.0.61）

「接收完那一刻缩略图已经生成了，点一下『存相册』，整屏缩略图又刷一遍」——
不是重复劳动：**显示源真的换了个文件**，而且 key 跟着变了，整行被销毁重建 + 重新解码。

三层成因叠在一起，缺一层都不明显：

| 层 | 机制 |
|---|---|
| ① 源真的换了 | `mediaSrcOf()` 是「沙箱原图优先、沙箱没了退缓存小图」。存相册流程会**删掉沙箱副本** ⇒ 源从原图切成 320px 小图 |
| ② 缓存小图生成得太晚 | 缓存小图**只在「存相册」时才生成** ⇒ 切换必然发生在存储**之后**，用户正好看到 |
| ③ key 粒度是全局的 | ForEach key 里塞了 `@State thumbTick`（**每生成一张缩略图就 +1**）⇒ 任何一张图有动静，**整屏**气泡的 key 全变 ⇒ 全部销毁重建 |

### 两条通用判据

1. **显示身份不能绑在「会消失的东西」上。**
   沙箱副本的生死不该决定「这张图长什么样」。凡是「先看 A、A 没了看 B」的取源函数，
   其返回值都**不适合进 key**。
2. **ForEach key 里绝不放全局计数器。**
   key 的粒度必须跟「最细的可独立变化的单位」对齐（与第二十六节同源）。

### 修法：拆成「高清源」和「稳定源」两个函数

```ts
/** 尽力高清源（沙箱原图优先）—— 全屏预览 / 画廊 / 长按存图用 */
private mediaSrcOf(m: M, k: number): string {
  const p = this.recvPathFor(...);
  return p.length > 0 ? p : this.albumPartOf(m.id, k, 1);
}

/** ★ 恒定显示源（缓存小图优先）—— 气泡缩略图 + ForEach key 用 */
private mediaThumbSrcOf(m: M, k: number): string {
  const cached = this.albumPartOf(m.id, k, 1);
  if (cached.length > 0 && !isFullCopyThumb(cached)) {
    return cached;                       // 幂等文件名 ⇒ 不会消失的显示身份
  }
  const p = this.recvPathFor(...);
  if (p.length > 0) {
    this.maybePrefetchThumb(m.id, k, p); // 渲染到才补，不做全量预热
    return p;
  }
  return cached;
}
```

**缓存文件名必须由「稳定 id」决定**（本项目是 `album_thumbs/<消息id#媒体序号>.jpg`），
这样它既是幂等的、又能在重启后靠同一套规则算出来 —— 这才撑得起「恒定身份」。

### 配套三件事（少一件就白改）

1. **预生成放在「渲染路径」上，而不是「刷新时全量遍历」。**

   ```ts
   private maybePrefetchThumb(id: string, k: number, src: string): void {
     const key = albumKeyOf(id, k);
     if (this.thumbPrepare.has(key)) { return; }   // 内存去重（+ cacheThumb 自己的单飞表）
     this.thumbPrepare.add(key);
     this.prefetchThumbInner(key, src).catch(() => { this.thumbPrepare.delete(key); });
   }
   ```

   ⚠️ `prefetchThumbInner` 里若有**同步文件 IO**（比如读 EXIF），
   开头必须 `await yieldOnce()` 先让出一拍 —— 不然这段 IO 会挤在 build 阶段里、滚动掉帧。

2. **落盘「只补缩略图」的接口绝不能覆盖已有字段。**
   预生成时用户还没点相册确认框，`uri` 必须是空的；如果直接把这行覆盖成 `|thumb`，
   就把「点图跳相册」冲掉了：

   ```ts
   async setThumbOnly(id: string, thumb: string, rot = 0): Promise<void> {
     const cur = this.albumMap.get(id);
     const segs = cur === undefined ? [] : cur.split('|');
     const curUri = segs.length > 0 ? segs[0] : '';   // ★ 保住原有 uri
     this.albumMap.set(id, curUri + '|' + thumb);
     ...
   }
   ```

3. **key 里换成本项自己的签名**：

   ```ts
   private thumbSigOf(m: M): string {
     const src = this.mediaThumbSrcOf(m, 0);
     return src.length === 0 ? m.id + ':-'
       : m.id + ':' + src + ':' + this.ratioOf(src) + ':' + (this.service.rotOf(src) ?? 0);
   }
   ```

   把「显示源 + 比例 + 补转角度」都收进签名 —— 这些正是会**异步**变化的东西
   （比例是量出来的、旋转角是解码时定的），少了它们就会出现「该重建的不重建」。

### 连带必须改的两处

- **状态标记的判据要跟着改**：本项目「已删」标记原来是
  「无相册 URI && 有缩略图 ⇒ 已删」。预生成之后**还没存过相册的图也有缩略图**了，
  这个判法会把每张新图都标成「已删」。要补上「沙箱副本也没了」这一条。
- **缩略图渲染分支不能只看路径判断媒体类型**：视频的缓存封面是普通 `.jpg`，
  看扩展名会把「视频封面」误判成图片、丢掉 ▶ 角标。把 `isVideo` 做成**形参**，
  由调用方从**消息本身**判断：

  ```ts
  if (isVideo && this.isVideoName(path)) { /* 真·视频 → 首帧 PixelMap */ }
  else { /* 图 或 视频的缓存封面 → Image 解码 */ }
  if (isVideo) { Text('▶') }   // 角标只看 isVideo，不看路径
  ```

### ⚠️ 一个刻意的例外：别把「无视觉差异」的切换也拉进来

本例里 EXIF 方向照片（`deg≠0`）走的是「**复制原图**当缓存」的兜底路，
那份缓存与原图**逐字节相同** ⇒ 切过去**视觉零变化**，用户本来就感知不到；
而预生成会让每张竖拍照片都多存一份原图（**磁盘翻倍**）。
所以恒定路径要**排除**这类路径（判据：路径里带 `_full.`）。

> 原则：**恒定化只花在「用户看得见差异」的地方。**
> 先问「这次切换在屏幕上到底有没有变化」，再决定值不值得为它建稳定身份。

### 排查清单

1. 「某个操作后整屏闪一下 / 重建」⇒ 先看那次操作改了哪些 `@State`，再 grep 这些字段
   **有没有出现在任何一个 ForEach 的 keyGenerator 里**。
2. key 里出现「全局 tick / 全局计数 / 全局版本号」⇒ 几乎必然是 bug（与第二十六节同源）。
3. 想「既有重绘能力、又不波及全局」⇒ 用**每项自己的签名**（把该项会异步变化的要素拼进去）。
4. 改完 key 之后，**逐条列出「哪些异步变化会触发重绘」**，确认没有漏项 ——
   漏项的典型症状是「改对了不再闪，但缩略图再也不出现 / 比例永远停在初始值」。
'''

io.open(P, 'a', encoding='utf-8', newline='\n').write(block)
print('APPENDED')
