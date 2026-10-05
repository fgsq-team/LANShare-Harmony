# -*- coding: utf-8 -*-
"""
向用户级 skill `harmonyos-arkui-ui-pitfalls` 追加两节（5.0.52 的通用结论）：
  二十六、一批多个文件 = 一条消息 —— 按「消息 id」记账必须加「媒体序号」
  二十七、相册 URI 是「写授权」，资产在不在**无法自证** —— 要用刚写入的资产现场自校准
幂等：按哨兵串判重，打过直接 SKIP。写文件保持 LF。
"""
import io, sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'
SENTINEL = '## 二十六、一批多个文件 = **一条**消息'

ADD = r'''

## 二十六、一批多个文件 = **一条**消息 —— 按「消息 id」记账的东西必须加「媒体序号」

### 症状

接收一组图片（N≥2）自动存相册后：

- 在系统相册里删掉**其中一张**，**其余每一张**都提示「该文件已从相册删除」；
- 把老照片删掉、再收新照片，气泡缩略图显示的**还是老照片**，点击跳相册打开的也不是刚收到的那张。

### 根因：记账粒度 比 可变化单位 粗

对端一次发 N 张图，本端**只产生一条**消息（文案是 `N 个文件`，`fileNames` 用 `\n` 分隔）。
而相册索引的 key 用的是**消息 id**：

```ts
// 错：整批共用一条记录 → 一个 uri、一个缩略图文件
albumMap.set(msg.id, `${uri}|${thumbPath}`);
cacheThumb(ctx, srcPath, msg.id);   // 同一个 id ⇒ 同一个文件 ⇒ 后写覆盖前写
```

于是「删一张」= 整条记录标废；「换一批新图」= 缩略图文件被复用/串到旧图。

### 修法 ①：key 改成 `消息id#媒体序号`

```ts
private static albumKeyOf(id: string, k: number): string { return `${id}#${k}`; }
```

删索引时必须**按前缀删整组**：

```ts
dropAlbumIndex(id: string): void {
  const keys: string[] = [id];
  for (const k of this.albumMap.keys()) { if (k.startsWith(id + '#')) { keys.push(k); } }
  for (const k of keys) { /* 删记录 + unlink 缩略图 */ }
}
```

### 修法 ②：**下标来源必须是「消息本身」**，不能是「当前还在沙箱里的文件列表」

- 「还在沙箱里的文件」会随**自动存相册后删副本**而**塌缩**：原本第 2 项，塌缩后变成第 1 项
  ⇒ 第 2 项的 uri 被写到第 1 个格子上。
- 正确来源：`m.files`（消息自带的文件名列表），过滤出图片/视频，下标才是**稳定**的。
- 「按文件名反查路径」遇同名是**多对一**（落盘时被加 `(1)` 去重后缀）
  ⇒ 必须用「**与消息时间的距离**就近取」消歧，否则跨消息串台：

```ts
cands.sort((a: ReceivedFile, b: ReceivedFile) =>
  Math.abs(a.time - msgTimeMs) - Math.abs(b.time - msgTimeMs));
return cands[k].path;
```

### 修法 ③：预览/画廊要**显式带 key**，不要从「当前选中 id」推断

一次存多张进相册时，把每张的 key 一起传出去
（`saveImageToAlbum(path, name, key)`、`openMediaGallery(paths, names, index, keys)`），
`@State imgPreviewKey` / `galleryKeys` 显式记录；**文件页的画廊不传 key**（文件页的图不属于任何消息）。

### 修法 ④：`ForEach` 的 key 要把「这一行会变的东西」都带上

```ts
`${m.id}|...|${albumPartOf(m.id, 0, 0).length > 0 ? 1 : 0}|${albumPartOf(m.id, 0, 1)}`
```

否则相册 uri / 缩略图变了，这一行**不重绘**。

### 排查口诀

- 一处失败**带倒一整批** → 先问「这一批在代码里是**一条记录**还是 N 条」。
- 「删了再收新的，显示的还是旧的」→ 查 key 是否被复用（同一个 id / 同一个缩略图文件名）。
- 「第 2 项显示成第 1 项」→ 查下标是不是来自**会被删除而塌缩**的列表。

## 二十七、相册 URI 是「写授权」—— 资产在不在**无法自证**，要用「刚写入的资产」现场自校准

### 症状

想给「已从相册删除」加提示，于是探测 uri 还在不在，结果**每一张**都提示已删除；
或者反过来把探测放宽成「一律当还在」，用户点了就跳进一个**空白相册页**。

### 为什么两头都不对

- `showAssetsCreationDialog` 返回的 URI 是**写授权**：**能写 ≠ 能读**。
- 所以 `fileIo.statSync(uri)` / `openSync(uri, READ_ONLY)` 失败**只能证明「读不到」，不能证明「不存在」**。
  把「两个信号都失败」当成「已删除」⇒ 大面积误报。
- 但写成「一律当还在」又会让「跳相册」打开空白页（体验更差）。

### 修法：多信号 + 严格错误码 + **现场自校准**

```ts
// ① 多信号：stat 有 size → 只读打开真读到 >0 字节
// ② 只有「明确的不存在」错误码才算已删，其它错误一律按「还在」
const gone: boolean = codes.indexOf('stat=13900002') >= 0 || codes.indexOf('open=13900002') >= 0;
return !(gone && this.service.probeTrusted());
```

```ts
// ③ 自校准：刚写进相册的那一刻，资产必然存在。
//    此刻若探活判「不存在」⇒ 本机探针根本不可信 ⇒ 持久化关掉这个判定（单向翻）
private albumProbeCalibrate(uri: string): void {
  if (!this.service.probeTrusted()) { return; }
  if (this.albumAssetAlive(uri)) { return; }
  this.service.setProbeTrusted(false);      // 落盘持久化，重启不改回来
  this.toast('本机无法校验相册状态，已关闭「已删除」提示');
}
```

在**每次成功写入相册之后**都调一次（自动存相册、手动长按存、历史补存都要调）。

### 设计原则（可迁移）

- **宁可少报也不误报**：拿不到确凿证据时，按「还在」处理；把「跳空白页」当可接受的降级。
- **单向翻的标志位要持久化**：一旦证明本机探针不可信，就永久关掉这类提示，别每次启动再试探一遍。
- **日志里带上判据**：把错误码列表 + `信任=1/0` 一起写进 UI 日志，否则现场只有「提示出现了」这一条信息，无法定位。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.endswith('\n'), '文件末尾不是换行，先确认再追加'
assert s.count('## 二十五、') == 1, '找不到第二十五节'
s2 = s + ADD
io.open(P, 'w', encoding='utf-8', newline='').write(s2)
print('OK: 已追加 二十六 / 二十七，长度 %d -> %d' % (len(s), len(s2)))
