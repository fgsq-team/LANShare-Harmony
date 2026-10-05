# -*- coding: utf-8 -*-
"""
LANShareV5 5.0.17 文档 / 日志 / 技能沉淀

  * docs/PENDING_TEST.md          —— 新增 5.0.17 章节，5.0.16 降级为 🔵
  * E:\\lanshare项目\\.workbuddy\\memory\\2026-10-01.md  —— 追加本轮记录
  * 技能 harmonyos-arkui-ui-pitfalls/SKILL.md        —— 新增「二十三」

幂等：每个文件开头都用哨兵串判重，重跑直接跳过（见用户级 MEMORY.md 的铁律）。
"""

import io
import os
import sys

HAP_SIZE = '2086134'
HAP_SHA = '4a1fbe044f90ae1fe7e20610834f4eb375958bcf072d3f3f79a0c2de16e211b7'

PENDING = r'E:\lanshare-harmony\LANShareV5\docs\PENDING_TEST.md'
LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-01.md'
SKILL = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'


def read(p):
    return io.open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='').write(s)


def sub(s, old, new, tag):
    assert s.count(new) == 0, '[%s] 新文本此前已存在' % tag
    n = s.count(old)
    assert n == 1, '[%s] 旧文本命中 %d 处（应为 1）' % (tag, n)
    return s.replace(old, new)


# ======================================================================
# 1) PENDING_TEST.md
# ======================================================================
PENDING_ANCHOR = '## 🟢 最新待测：LANShareV5-5.0.16'
PENDING_SENTINEL = '## 🟢 最新待测：LANShareV5-5.0.17'

NEW_SECTION = '''## 🟢 最新待测：LANShareV5-5.0.17 —— **消息页图片缩略图 / 点开看大图 / 长按存相册**（2026-10-01 16:04 构建）

| 项 | 值 |
|---|---|
| 版本号 | 5.0.17（versionCode 5000017） |
| 本地 HAP | `E:/lanshare-harmony/LANShareV5/LANShareV5-5.0.17.hap` |
| 大小 | 2086134 B |
| sha256 | `4a1fbe044f90ae1fe7e20610834f4eb375958bcf072d3f3f79a0c2de16e211b7` |
| 手机落地 | ✅ **已推送** 16:04 → `Download/LANShareV5-5.0.17.hap`（USB `5BE0225610017870` + WiFi `192.168.10.146:41817`，两通道 `ls` 均 2086134 B） |
| 构建结果 | 全量重建 **BUILD SUCCESSFUL**（31s416ms，33/33 任务，32 executed），零 ArkTS ERROR（仅既有 WARN） |
| 编入验证 | 解包 `ets/modules.abc`（824240 B）：`点击看图 · 长按存相册`、`点击查看 ›`、`已取消保存`、`找不到源文件`、`存相册失败`、`存相册：`、`保存失败：`、`chatFileBubble`、`rebuildRecvIndex`、`stripDedupeSuffix`、`msgImagePath`、`saveImageToAlbum`、`safeAlbumTitle`、`showAssetsCreationDialog`、`getUriFromPath` 全部命中（`PhotoCreationConfig` 是**纯类型名**，编译期擦除，MISS 属正常） |

> 本轮为 **vivi 2026-10-01 真机诉求**（当时机上为 5.0.16）。共 3 件：缩略图、点开看大图、长按存相册。
> 5.0.16 的「文件页图片缩略图 + 全屏预览」是同一套机制的第一次落地，本轮把它接进了消息页。

---

### 诉求 1：消息页也要显示图片缩略图

**做法**：`chatBubble` 里那段「文件气泡」抽成独立的 `@Builder chatFileBubble(m, imgPath)`，
收到的图片消息先渲染 **128×128** 缩略图（同样配 `sourceSize({192,192})` 压解码尺寸 ——
聊天记录上限 200 条，不压的话每张原图都会整张解进内存）。

**⚠️ 本轮最容易踩的坑：消息里只有文件名，路径从哪来？**

消息表 `ChatMessage` 只存了 `content` = **对端发来的原名**。所以 `refreshReceived()` 时顺手建一张
`文件名 → 沙箱路径` 的表（`rebuildRecvIndex`）。**但只登记真名是不够的**：

> 对端发来的图叫 `photo.jpg`；沙箱里已经有一张同名图时，落盘名会被
> `FileKinds.dedupeName` 改成 **`photo(1).jpg`** —— 而气泡里存的永远是**原名** `photo.jpg`。
> 只登记真名的话，**第二张同名的图永远没有缩略图**。
> 而 `IMG_0001.jpg` 这种一发就是一批，重名是常态。

所以每个文件登记**两个键**：真名 + 去掉重名后缀的别名（`stripDedupeSuffix`：
`photo(1).jpg` → `photo.jpg`，只认「数字包在圆括号里」这一种形态）。
`list` 是按时间倒序的，所以「先到先得」= 取最新那张，符合直觉。

---

### 诉求 2：点开看大图

点一下图片气泡 → 进**同一个**全屏预览浮层（`imgPreviewView`，捏合缩放 / 双击复位 / 拖动 / 关闭 / 返回键）。
`openImagePreview` 的入参从 `ReceivedFile` 改成 `(path, name)` —— 消息气泡手里只有一个路径，
造不出「文件」页列表那个模型。非图片 / 自己发出的消息行为与改动前完全一致（点一下跳「文件」页）。

---

### 诉求 3：长按存相册

**关键选型**：用 `photoAccessHelper.showAssetsCreationDialog`，**不需要任何权限声明**。

| 方案 | 结论 |
|---|---|
| `createAsset` / `MediaAssetChangeRequest` | ❌ 要 `ohos.permission.WRITE_IMAGEVIDEO`（受限权限，普通应用申请不到） |
| `SaveButton` 安全控件 | ❌ 临时授权必须由**那个控件的点击**换，我们的入口是「长按气泡 / 预览页按钮」，接不上 |
| **`showAssetsCreationDialog`** | ✅ 弹一个系统确认框，用户点保存后返回一批**带写权限的媒体 URI**，往里写字节即可 |

写字节**直接复用 `ExportService.copyTo`** —— 「另存为」用的就是它，
Picker 给的 URI 和这里拿到的媒体 URI 是同一类 `file://` 地址，真机上已跑通的路径不再写第二份。

HAP 里**没有新增任何 `requestPermissions`**。

**入口两个**：
- **长按图片气泡**（气泡上写了「点击看图 · 长按存相册」的提示文案，保证可发现）；
- **全屏预览顶栏「存相册」按钮** —— 这是唯一能同时覆盖「消息页」和「文件页」的入口
  （文件页的行已经被「长按多选」占住了，再挂长按会打架）。

⚠️ `PhotoCreationConfig.title` 的硬规则：**不能带扩展名**（扩展名单独走 `fileNameExtension`）、
不能含反斜杠 / 斜杠 / 冒号 / 星号 / 问号 / 各类引号 / 反引号 / 尖括号 / 竖线 / 花括号 / 方括号、
总长 1~255 —— 所以加了个 `safeAlbumTitle()` 做字符过滤。

**验收**：

| # | 场景 | 期望 |
|---|---|---|
| ① | 收到一张图片 | 消息页对应气泡里出现**缩略图**，不是空白框 |
| ② | 点一下缩略图 | 进全屏预览；捏合放大 / 双击复位 / 拖动都正常；返回键能关 |
| ③ | 长按缩略图 | 弹**系统保存确认框** → 点「保存」→ 相册里能看到这张图，文件名正常 |
| ④ | 预览页点「存相册」 | 同上（这条在「文件」页也要能走通） |
| ⑤ | 长按之后 | **不要**同时弹出全屏预览（已用 `clickMuteUntil` 兜底，正常情况不会） |
| ⑥ | 连收两张**同名**的图 | **两张都有缩略图** ← 专门验 `stripDedupeSuffix` 那条别名逻辑 |

⚠️ 已知边界：`文件名 → 路径` 的表来自「文件」页那份扫描（上限 40 条），
所以**很久以前收到的图**（已跌出前 40）在消息页可能没有缩略图。这是刻意的取舍 ——
为一个纯显示字段去改 `ChatMessage` 的落盘结构，代价与风险都不划算。

### 构建踩坑（已修）

第一次构建失败在 **`10505001 Property 'onLongPress' does not exist on type 'ColumnAttribute'`**：

> 这个 SDK 的 ArkUI **没有** `onLongPress` 这个 CommonMethod 属性。
> 长按只有一条路：`.gesture(LongPressGesture({ repeat: false, duration: 400 }).onAction(...))`
> —— 文件页的「长按进多选」本来就是这么写的，本轮新代码抄漏了形态。
> 报错里的类型名会随组件变（`ColumnAttribute` / `TextAttribute` / …），别被误导成「只有 Column 不支持」。

---

'''

# ======================================================================
# 2) 工作区日志
# ======================================================================
LOG_SENTINEL = '## 5.0.17'
LOG_BLOCK = '''

## 5.0.17（2026-10-01 16:04）消息页图片缩略图 + 点开看大图 + 长按存相册

vivi 真机诉求 3 件，全在 `Index.ets`（+ 版本号），一次补丁 `patch_v5017.py` 落地。

- **消息页缩略图**：`chatBubble` 的「文件气泡」抽成 `@Builder chatFileBubble(m, imgPath)`；
  收到的图片消息渲染 128×128 缩略图（`sourceSize({192,192})` 压解码，聊天记录 200 条上限）。
- **路径从哪来** —— 本轮最关键的坑：`ChatMessage.content` 存的是**对端发来的原名**，
  而沙箱里重名落盘会被 `FileKinds.dedupeName` 改成 `photo(1).jpg`。
  所以 `refreshReceived()` 里建 `文件名 → 路径` 的表（`rebuildRecvIndex`），
  每个文件登记**两个键**：真名 + 去重后缀别名（`stripDedupeSuffix`），
  否则**第二张同名的图永远没有缩略图**（`IMG_0001.jpg` 一发一批，重名是常态）。
- **点开看大图**：复用同一个全屏预览浮层；`openImagePreview` 入参由 `ReceivedFile`
  改成 `(path, name)` —— 消息气泡手里只有一个路径，造不出 `ReceivedFile`。
- **长按存相册**：`photoAccessHelper.showAssetsCreationDialog`（**免任何权限声明**，
  弹系统确认框换一批带写权限的媒体 URI）+ 复用 `ExportService.copyTo` 写字节
  （「另存为」在真机已跑通的同一条路）。不用 `createAsset`（要 WRITE_IMAGEVIDEO 受限权限）
  也不用 SaveButton（临时授权必须由该控件点击换，长按接不上）。
  入口两个：长按气泡 + 全屏预览顶栏「存相册」按钮（后者是唯一同时覆盖两个页面的入口，
  文件页的行已被长按多选占住）。
  `PhotoCreationConfig.title` 硬规则：不带扩展名、不含反斜杠/斜杠/冒号/星号/问号/各类引号/尖括号/竖线/花括号/方括号
  → 配 `safeAlbumTitle()` 过滤。
- 长按后 800ms 内忽略 click（`clickMuteUntil`），防「存相册」连带弹出全屏预览。
- 版本 5.0.16 → 5.0.17（versionCode 5000017）。

补丁脚本：`docs/patch_scripts/patch_v5017.py`；改动前源码备份 `.backup_v5017/`。
'''

# ======================================================================
# 3) 技能
# ======================================================================
SKILL_SENTINEL = '## 二十三、'
SKILL_BLOCK = '''

---

## 二十三、把图片存进系统相册 —— **别申请 WRITE_IMAGEVIDEO，用 `showAssetsCreationDialog`**

### 症状 / 需求

「长按图片 → 保存到相册」。直觉是去申请 `ohos.permission.WRITE_IMAGEVIDEO`
然后 `photoAccessHelper.createAsset()` —— 这条路对普通应用**走不通**。

### 三条路的取舍

| 方案 | 结论 |
|---|---|
| `createAsset` / `MediaAssetChangeRequest.createImageAssetRequest` | ❌ 要 `ohos.permission.WRITE_IMAGEVIDEO`（受限权限，普通应用申请不到，写进 `module.json5` 也没用） |
| `SaveButton` 安全控件 | ❌ 临时授权必须由**那个控件自身的点击**换取。入口是「长按气泡 / 自定义按钮」时接不上 |
| **`photoAccessHelper.showAssetsCreationDialog(srcUris, configs)`** | ✅ **不需要任何 `requestPermissions`**：弹系统确认框，用户点保存后返回一批**带写权限的媒体 URI**，往里写字节即可。API 12+ |

```ts
const ctx: common.UIAbilityContext =
  this.getUIContext().getHostContext() as common.UIAbilityContext;
const helper: photoAccessHelper.PhotoAccessHelper =
  photoAccessHelper.getPhotoAccessHelper(ctx);
const cfg: photoAccessHelper.PhotoCreationConfig = {
  title: 'photo',                 // ⚠️ 不能带扩展名
  fileNameExtension: 'jpg',       // 单独给
  photoType: photoAccessHelper.PhotoType.IMAGE
};
const uris: string[] = await helper.showAssetsCreationDialog([srcUri], [cfg]);
if (uris.length === 0) { /* 用户取消 —— 返回空数组，不是错误 */ return; }
// uris[0] 是 file://media/... ；openSync 直接认，写字节即可
```

### 五个必踩点

1. **`srcUris` 传 `fileUri.getUriFromPath(沙箱路径)`**，不要手拼 `file://`（同第二十二节）。
   系统文档对这个形态的说明是「**能保存，但确认框里没法预览**」—— 属已知行为，不影响落地。
2. **`title` 不能带扩展名**，扩展名单独走 `fileNameExtension`；
   且不能含反斜杠 / 斜杠 / 冒号 / 星号 / 问号 / 各类引号 / 尖括号 / 竖线 / 花括号 / 方括号，总长 1~255。
   写个字符过滤函数，别赌用户的文件名。
3. **用户取消 = 返回空数组**，不是抛异常 —— 必须显式判 `length === 0`，否则会走到「保存成功」的提示。
4. **写字节别重写一套**：如果工程里已有「另存为」（Picker URI + `openSync(READ_WRITE|TRUNC)` + `readSync`/`writeSync` 循环），
   媒体 URI 与 Picker URI 是同一类 `file://` 地址，**直接复用那个函数**。
5. **返回的 URI 权限是永久的**，可以放心写。

### 配套①：这个 SDK **没有** `onLongPress` 通用属性

写 `.onLongPress(() => {})` 会直接编译报错：

```
10505001 ArkTS Compiler Error
Property 'onLongPress' does not exist on type 'ColumnAttribute'.
```

长按只有一条路 —— `.gesture(LongPressGesture(...))`：

```ts
.gesture(
  LongPressGesture({ repeat: false, duration: 400 })
    .onAction(() => { /* 长按逻辑 */ })
)
```

⚠️ 报错信息里的类型名会随组件变（`ColumnAttribute` / `TextAttribute` / …），
别被「只有 Column 不支持」误导。

### 配套②：`onLongPress`（手势）与 `onClick` 挂在同一个组件上

长按（存相册）+ 点击（看大图）经常要共存在一个气泡上。
ArkUI 里长按命中后一般不会再补一个 click，但**这个前提不值得赌** ——
用一个时间戳兜底，3 行换掉一整类偶发怪象：

```ts
private clickMuteUntil: number = 0;

.onClick(() => {
  if (Date.now() < this.clickMuteUntil) { return; }
  /* 正常点击逻辑 */
})
.gesture(
  LongPressGesture({ repeat: false, duration: 400 })
    .onAction(() => {
      this.clickMuteUntil = Date.now() + 800;
      /* 长按逻辑 */
    })
)
```
'''

# ======================================================================
# 执行
# ======================================================================
changed = []

# ---- PENDING_TEST.md ----
s = read(PENDING)
if PENDING_SENTINEL in s:
    print('PENDING_TEST.md 已更新，跳过')
else:
    section = (NEW_SECTION
               .replace('__HAP_SIZE__', HAP_SIZE)
               .replace('__HAP_SHA__', HAP_SHA))
    assert s.count(PENDING_ANCHOR) == 1, 'PENDING 锚点不唯一'
    assert section not in s, 'PENDING 新章节此前已存在'
    s = s.replace(PENDING_ANCHOR, section + '## 🔵 待测：LANShareV5-5.0.16', 1)
    write(PENDING, s)
    changed.append(PENDING)
    print('PENDING_TEST.md OK')

# ---- 工作区日志 ----
if os.path.exists(LOG):
    t = read(LOG)
    if LOG_SENTINEL in t:
        print('工作区日志已更新，跳过')
    else:
        t = t.rstrip('\n') + '\n' + LOG_BLOCK
        write(LOG, t)
        changed.append(LOG)
        print('工作区日志 OK')
else:
    print('!! 工作区日志不存在：%s' % LOG)

# ---- 技能 ----
k = read(SKILL)
if SKILL_SENTINEL in k:
    print('技能文件已更新，跳过')
else:
    assert SKILL_BLOCK not in k, '技能新章节此前已存在'
    k = k.rstrip('\n') + '\n' + SKILL_BLOCK
    write(SKILL, k)
    changed.append(SKILL)
    print('技能 harmonyos-arkui-ui-pitfalls OK')

print('---- 本次写入 ----')
for p in changed:
    print('  %s' % p)
