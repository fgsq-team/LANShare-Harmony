# -*- coding: utf-8 -*-
"""
LANShareV5 5.0.17 补丁（vivi 2026-10-01 真机诉求）

  1. 消息页的图片消息也显示缩略图，可以点开看大图
  2. 长按图片（气泡 / 全屏预览）保存到系统相册

工程约定（见 E:\\lanshare项目\\.workbuddy\\memory\\MEMORY.md）：
  * 全部用**内容锚点**定位，不用行号；
  * 每条替换同时断言「新文本此前不存在」+「旧文本恰好一处」——两道保险，
    专门挡「替换文本 new 里含 old」导致的嵌套重复插入；
  * 哨兵幂等：已打过直接 exit 0；
  * 先全部在内存里改完 + 校验，最后统一落盘（任一失败则一个字都不写）。
"""

import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
F_INDEX = os.path.join(ROOT, r'entry\src\main\ets\pages\Index.ets')
F_APP = os.path.join(ROOT, r'AppScope\app.json5')
BACKUP = os.path.join(ROOT, '.backup_v5017')

SENTINEL = 'chatFileBubble(m: ChatMessage, imgPath: string)'


def read(p):
    s = io.open(p, encoding='utf-8', newline='').read()
    return s.replace('\r\n', '\n')


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='').write(s)


def sub(s, old, new, tag):
    """唯一替换 + 双断言"""
    assert s.count(new) == 0, '[%s] 新文本此前已存在（重复插入？）' % tag
    n = s.count(old)
    assert n == 1, '[%s] 旧文本命中 %d 处（应为 1）\n--- old ---\n%s' % (tag, n, old[:400])
    return s.replace(old, new)


# ======================================================================
# 读 + 幂等判断
# ======================================================================
idx = read(F_INDEX)
app = read(F_APP)

if SENTINEL in idx:
    print('ALREADY APPLIED - 5.0.17 补丁此前已打过，跳过')
    sys.exit(0)

before_brace = idx.count('{') - idx.count('}')
assert before_brace == 0, '补丁前 Index.ets 括号就不平：%d' % before_brace


# ======================================================================
# A. 文件头变更记录
# ======================================================================
OLD_HEAD = r""" * | 多台设备在线时按「+」先选设备 | 「+」由 `bindMenu` 改为 `onClick` → `openPlus()`：已在胶囊选了设备 / 只有一台在线 → 直接进「相册或文件」；多台且选的是「所有设备」 → 先弹设备列表（`pickDialog`，两步：`pickStep` 1=选设备 2=选类型）。选完设备顺手把上方胶囊同步过去。⚠️ 菜单是静态的，做不到按设备数量分叉，所以必须换成自定义弹窗 |
 */"""

NEW_HEAD = r""" * | 多台设备在线时按「+」先选设备 | 「+」由 `bindMenu` 改为 `onClick` → `openPlus()`：已在胶囊选了设备 / 只有一台在线 → 直接进「相册或文件」；多台且选的是「所有设备」 → 先弹设备列表（`pickDialog`，两步：`pickStep` 1=选设备 2=选类型）。选完设备顺手把上方胶囊同步过去。⚠️ 菜单是静态的，做不到按设备数量分叉，所以必须换成自定义弹窗 |
 *
 * ## 2026-10-01 第八轮（vivi 真机诉求，5.0.17）
 * | 诉求 | 落法 |
 * |---|---|
 * | 消息页也要显示图片缩略图、可以点开 | `chatBubble` 里的「文件气泡」抽成 `chatFileBubble(m, imgPath)`；收到的图片消息先渲染 128×128 缩略图（同样配 `sourceSize` 压解码尺寸），点一下进**同一个**全屏预览浮层。`openImagePreview` 的入参从 `ReceivedFile` 改成 `(path, name)` —— 消息气泡手里只有一个路径，造不出「文件」页那个模型 |
 * | 图片能不能长按保存到相册 | 新增 `saveImageToAlbum()`：`photoAccessHelper.showAssetsCreationDialog`（**不需要任何权限声明**，弹系统确认框换一批带写权限的媒体 URI）+ 复用 `ExportService.copyTo` 写字节（「另存为」已在真机跑通的同一条路径）。入口两个：**长按图片气泡**、全屏预览顶栏「存相册」按钮 |
 * | ⚠️ 消息里只有文件名，路径从哪来 | `refreshReceived()` 时顺手建一张 **文件名 → 沙箱路径** 的表（`rebuildRecvIndex`）。⚠️ 必须额外登记一个「去掉重名后缀」的**别名键**：对端发来的图叫 `photo.jpg`，沙箱里已有同名时落盘会被 `FileKinds.dedupeName` 改成 `photo(1).jpg`，而气泡里存的永远是对端发来的**原名** —— 只登记真名的话，第二张同名的图就永远没有缩略图（`IMG_0001.jpg` 这种一发就是一批，太常见了） |
 */"""

idx = sub(idx, OLD_HEAD, NEW_HEAD, 'head')


# ======================================================================
# B. 新增字段（接在「图片预览」字段组之后）
# ======================================================================
OLD_FIELDS = r"""  /** 一次拖动开始时的基准位移 */
  private imgDragBaseX: number = 0;
  private imgDragBaseY: number = 0;
"""

NEW_FIELDS = r"""  /** 一次拖动开始时的基准位移 */
  private imgDragBaseX: number = 0;
  private imgDragBaseY: number = 0;

  // ---------------- 消息页图片缩略图 ----------------
  /**
   * 文件名 → 沙箱绝对路径。`refreshReceived()` 时重建（见 rebuildRecvIndex）。
   *
   * ⚠️ 为什么不把路径直接塞进 `ChatMessage`：那张表要落盘、要跨版本兼容，
   *    为一个纯「显示」用的字段去动持久化结构，收益不抵风险。
   *    用「消息里存的是对端发来的**原名**」这一点反查就够了。
   */
  private recvIndex: Map<string, string> = new Map<string, string>();
  /**
   * 长按之后的一小段时间里忽略 `onClick`。
   *
   * ArkUI 里长按命中后一般不会再补一个 click，但这个前提不值得赌：
   * 万一手势同时命中，用户「长按存相册」会连带弹出全屏预览。
   * 3 行的兜底，换掉一整类偶发怪象。
   */
  private clickMuteUntil: number = 0;
"""

idx = sub(idx, OLD_FIELDS, NEW_FIELDS, 'fields')


# ======================================================================
# C. refreshReceived 里重建索引
# ======================================================================
OLD_REFRESH = r"""  private refreshReceived(): void {
    const list: ReceivedFile[] = ExportService.listReceived(this.service.receiveRoot);
    this.receivedFiles = list;
"""

NEW_REFRESH = r"""  private refreshReceived(): void {
    const list: ReceivedFile[] = ExportService.listReceived(this.service.receiveRoot);
    this.receivedFiles = list;
    // 消息页的图片缩略图靠它把「文件名」翻回「沙箱路径」
    this.rebuildRecvIndex(list);
"""

idx = sub(idx, OLD_REFRESH, NEW_REFRESH, 'refreshReceived')


# ======================================================================
# D. 新增方法（插在「全屏图片预览」之前）
# ======================================================================
OLD_INSERT = r"""  /**
   * 全屏图片预览。
   *
   * `Image` 自身没有缩放能力，靠 `.scale()` + `.translate()` 做 ——"""

NEW_INSERT = r"""  /**
   * 重建「文件名 → 沙箱路径」索引。
   *
   * ⚠️ 关键在**别名**：对端发来的图叫 `photo.jpg`，而沙箱里已经有一张同名图时，
   *    落盘名会被 `FileKinds.dedupeName` 改成 `photo(1).jpg`，
   *    可气泡里存的永远是**对端发来的原名**。只登记真名的话，第二张同名的图
   *    在消息页就永远没有缩略图 —— 而 `IMG_0001.jpg` 这种一发就是一批，太常见。
   *    所以每个文件登记两个键：真名 + 去掉重名后缀的别名。
   *
   * ⚠️ `list` 是**按时间倒序**的，「先到先得」= 取最新的那张，符合直觉。
   */
  private rebuildRecvIndex(list: ReceivedFile[]): void {
    const m: Map<string, string> = new Map<string, string>();
    for (let i = 0; i < list.length; i++) {
      const f: ReceivedFile = list[i];
      if (!m.has(f.name)) {
        m.set(f.name, f.path);
      }
      const base: string = Index.stripDedupeSuffix(f.name);
      if (base !== f.name && !m.has(base)) {
        m.set(base, f.path);
      }
    }
    this.recvIndex = m;
  }

  /**
   * `photo(1).jpg` → `photo.jpg`。不是 `(n)` 形态就原样返回。
   *
   * 手写而不用正则：`FileKinds.dedupeName` 只会产出「数字包在圆括号里」这一种形态，
   * 逐字符判断足够，也免掉正则字面量在 ArkTS 里的转义麻烦。
   */
  private static stripDedupeSuffix(name: string): string {
    const dot: number = name.lastIndexOf('.');
    const hasExt: boolean = dot > 0;
    const base: string = hasExt ? name.substring(0, dot) : name;
    const ext: string = hasExt ? name.substring(dot) : '';
    if (!base.endsWith(')')) {
      return name;
    }
    const lp: number = base.lastIndexOf('(');
    if (lp <= 0) {
      return name;
    }
    const inner: string = base.substring(lp + 1, base.length - 1);
    if (inner.length === 0 || inner.length > 6) {
      return name;
    }
    for (let i = 0; i < inner.length; i++) {
      const c: number = inner.charCodeAt(i);
      if (c < 0x30 || c > 0x39) {
        return name;
      }
    }
    return `${base.substring(0, lp)}${ext}`;
  }

  /**
   * 一条消息对应的沙箱图片路径；不是「收到的图片」或查不到 → 返回空串。
   * 空串的语义是「不显示缩略图，也不给点开 / 长按的入口」。
   */
  private msgImagePath(m: ChatMessage): string {
    if (m.kind !== 'file' || !m.incoming || !this.isImageName(m.content)) {
      return '';
    }
    const hit: string | undefined = this.recvIndex.get(m.content);
    return hit === undefined ? '' : hit;
  }

  /**
   * 把沙箱里的一张图存进系统相册。
   *
   * ⚠️ 用 `showAssetsCreationDialog` 而不是 `createAsset` / `MediaAssetChangeRequest`：
   *    后两者要 `ohos.permission.WRITE_IMAGEVIDEO`（受限权限，普通应用申请不到），
   *    或者必须由 **SaveButton 安全控件**的点击来换临时授权 ——
   *    而我们的入口是「长按气泡 / 预览页按钮」，接不上那个控件。
   *    `showAssetsCreationDialog` **不需要任何权限声明**：它弹一个系统确认框，
   *    用户点保存后返回一批带写权限的媒体 URI，往里写字节就落相册了。
   *
   * ⚠️ 写字节直接复用 `ExportService.copyTo` —— 「另存为」用的就是它，
   *    Picker 给的 URI 与这里拿到的媒体 URI 是同一类 `file://` 地址，
   *    真机上已经跑通的路径没必要再写第二份。
   */
  private async saveImageToAlbum(path: string, name: string): Promise<void> {
    if (path.length === 0) {
      this.toast('找不到源文件');
      return;
    }
    const dot: number = name.lastIndexOf('.');
    // ⚠️ title 的硬性规则：**不能带扩展名**（扩展名单独走 fileNameExtension）、
    //    不能含 \ / : * ? " ' ` < > | { } [ ]、总长 1~255。
    const title: string = Index.safeAlbumTitle(dot > 0 ? name.substring(0, dot) : name);
    const ext: string = dot > 0 ? name.substring(dot + 1).toLowerCase() : 'jpg';
    try {
      const ctx: common.UIAbilityContext =
        this.getUIContext().getHostContext() as common.UIAbilityContext;
      const helper: photoAccessHelper.PhotoAccessHelper =
        photoAccessHelper.getPhotoAccessHelper(ctx);
      const cfg: photoAccessHelper.PhotoCreationConfig = {
        title: title,
        fileNameExtension: ext,
        photoType: photoAccessHelper.PhotoType.IMAGE
      };
      // ⚠️ 传进去的必须是 `fileUri.getUriFromPath()` 取到的沙箱 URI（见 imageUri 注释）。
      //    系统对这种 URI 的说明是「能存，但确认框里没法预览」，属已知行为。
      const uris: string[] = await helper.showAssetsCreationDialog([this.imageUri(path)], [cfg]);
      if (uris.length === 0) {
        // 用户点了取消 —— 系统返回空数组，不是错误
        this.toast('已取消保存');
        return;
      }
      const msg: string = ExportService.copyTo(path, uris[0], name);
      this.toast(msg);
      Log.i(TAG, `存相册：${msg}`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `存相册失败: ${err.code} ${err.message}`);
      this.toast(`保存失败：${err.message}`);
    }
  }

  /** 把文件名压成系统允许的相册 title（非法字符统一换成下划线） */
  private static safeAlbumTitle(raw: string): string {
    const bad: string = '\\/:*?"\'`<>|{}[]';
    let out: string = '';
    for (let i = 0; i < raw.length; i++) {
      const c: string = raw.substring(i, i + 1);
      out += bad.indexOf(c) >= 0 ? '_' : c;
    }
    if (out.length === 0) {
      out = 'image';
    }
    if (out.length > 200) {
      out = out.substring(0, 200);
    }
    return out;
  }

  /**
   * 全屏图片预览。
   *
   * `Image` 自身没有缩放能力，靠 `.scale()` + `.translate()` 做 ——"""

idx = sub(idx, OLD_INSERT, NEW_INSERT, 'methods')


# ======================================================================
# E. openImagePreview 入参改成 (path, name)（消息气泡手里没有 ReceivedFile）
# ======================================================================
OLD_OPEN = r"""  /** 点开一张图片：进全屏预览 */
  private openImagePreview(f: ReceivedFile): void {
    this.imgPreview = f.path;
    this.imgPreviewName = f.name;
"""

NEW_OPEN = r"""  /**
   * 点开一张图：进全屏预览。
   *
   * ⚠️ 入参是 `(path, name)` 而不是 `ReceivedFile`：消息页的气泡手里只有一个路径，
   *    造不出 `ReceivedFile`（那是「文件」页列表的模型）。
   */
  private openImagePreview(path: string, name: string): void {
    this.imgPreview = path;
    this.imgPreviewName = name;
"""

idx = sub(idx, OLD_OPEN, NEW_OPEN, 'openImagePreview')


# ======================================================================
# F. 文件页调用点跟进
# ======================================================================
OLD_CALL = r"""                  // 普通态：图片点一下进全屏预览；其它类型不做任何事（避免误触）
                  this.openImagePreview(f);"""

NEW_CALL = r"""                  // 普通态：图片点一下进全屏预览；其它类型不做任何事（避免误触）
                  this.openImagePreview(f.path, f.name);"""

idx = sub(idx, OLD_CALL, NEW_CALL, 'files-call')


# ======================================================================
# G. 全屏预览顶栏加「存相册」
# ======================================================================
OLD_PREV = r"""          Button('关闭')
            .fontSize(13)
            .height(32)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#33FFFFFF')
            .fontColor(Color.White)
            .onClick(() => this.closeImagePreview())"""

NEW_PREV = r"""          // 存相册放在这里而不是只挂在长按上：这是**唯一**能覆盖两个页面的入口
          // （「文件」页的行已经是长按多选了，再挂长按会打架）。
          // 长按气泡是快捷方式，这里才是兜底的那条路。
          Button('存相册')
            .fontSize(13)
            .height(32)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#33FFFFFF')
            .fontColor(Color.White)
            .onClick(() => this.saveImageToAlbum(this.imgPreview, this.imgPreviewName))
          Button('关闭')
            .fontSize(13)
            .height(32)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#33FFFFFF')
            .fontColor(Color.White)
            .onClick(() => this.closeImagePreview())"""

idx = sub(idx, OLD_PREV, NEW_PREV, 'preview-btn')


# ======================================================================
# H. chatBubble 的文件分支 → 调用新的 chatFileBubble
# ======================================================================
OLD_BUBBLE = r"""          Column({ space: 2 }) {
            Text(m.incoming ? '收到文件' : '已发送文件')
              .fontSize(11)
              .fontColor(m.incoming ? C_SUB : '#DCE8FF')
            Text(m.content)
              .fontSize(15)
              .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            if (m.incoming) {
              // 只有「收到的」才给跳转入口：收到的文件落在沙箱里，
              // 系统「文件管理」看不到，不指路用户就找不到。
              // 自己发出去的原文件还在用户自己手上，不需要跳。
              Text('点击查看 ›')
                .fontSize(10)
                .fontColor(C_PRIMARY)
            }
          }
          .alignItems(HorizontalAlign.Start)
          .constraintSize({ maxWidth: '78%' })
          .padding({ left: 12, right: 12, top: 8, bottom: 8 })
          .backgroundColor(m.incoming ? C_CARD : C_PRIMARY)
          .borderRadius(10)
          // ⚠️ 只有收到的文件才跳转：自己发出去的原文件还在用户手上，
          // 跳过去的文件页里根本没有它，点了就是死路。
          .onClick(() => {
            if (m.incoming) {
              this.openFileTab();
            }
          })
        } else {"""

NEW_BUBBLE = r"""          // 图片路径在调用点算好（`@Builder` 里不声明局部变量最省心）。
          // 非图片 / 自己发出的消息拿到的是空串，行为与改动前完全一致。
          this.chatFileBubble(m, this.msgImagePath(m))
        } else {"""

idx = sub(idx, OLD_BUBBLE, NEW_BUBBLE, 'chatBubble')


# ======================================================================
# I. 新增 chatFileBubble（插在 chatBubble 与 chatTab 之间）
# ======================================================================
OLD_TAIL = r"""    .width('100%')
    .alignItems(VerticalAlign.Top)
  }

  @Builder
  chatTab() {"""

NEW_TAIL = r"""    .width('100%')
    .alignItems(VerticalAlign.Top)
  }

  /**
   * 「文件」消息的气泡本体。
   *
   * ⚠️ 单独抽成一个 @Builder 而不是在 `chatBubble` 里就地写：
   *    `@Builder` 内**不声明局部变量**最省心，把 `imgPath` 当参数传进来，
   *    `chatBubble` 那边就只剩一行。
   *
   * 收到的图片：先给 128×128 缩略图（同样靠 `sourceSize` 压解码尺寸，
   * 理由见文件页那段注释），点一下看大图、长按存相册。
   * 非图片 / 自己发出的：维持原样（点一下跳「文件」页）。
   */
  @Builder
  chatFileBubble(m: ChatMessage, imgPath: string) {
    Column({ space: 2 }) {
      Text(m.incoming ? '收到文件' : '已发送文件')
        .fontSize(11)
        .fontColor(m.incoming ? C_SUB : '#DCE8FF')
      if (imgPath.length > 0) {
        // ⚠️ `.sourceSize()` 必须给：不压解码尺寸的话，聊天记录里每张图都会把
        //    **整张原图**解进内存，200 条上限 = 几百 MB（同文件页的坑）。
        Stack() {
          Text('图片')
            .fontSize(11)
            .fontColor('#AAAAAA')
          Image(this.imageUri(imgPath))
            .width(128)
            .height(128)
            .objectFit(ImageFit.Cover)
            .sourceSize({ width: 192, height: 192 })
        }
        .width(128)
        .height(128)
        .backgroundColor('#EFF2F6')
        .borderRadius(8)
        .clip(true)
      }
      Text(m.content)
        .fontSize(15)
        .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
        .maxLines(2)
        .wordBreak(WordBreak.BREAK_ALL)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      if (m.incoming) {
        // 只有「收到的」才给入口：收到的文件落在沙箱里，
        // 系统「文件管理」看不到，不指路用户就找不到。
        // 自己发出去的原文件还在用户自己手上，不需要跳。
        Text(imgPath.length > 0 ? '点击看图 · 长按存相册' : '点击查看 ›')
          .fontSize(10)
          .fontColor(C_PRIMARY)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .constraintSize({ maxWidth: '78%' })
    .padding({ left: 12, right: 12, top: 8, bottom: 8 })
    .backgroundColor(m.incoming ? C_CARD : C_PRIMARY)
    .borderRadius(10)
    .onClick(() => {
      // 长按过的这一小段时间里把 click 吃掉，防「存相册」连带弹出预览
      if (Date.now() < this.clickMuteUntil) {
        return;
      }
      if (imgPath.length > 0) {
        this.openImagePreview(imgPath, m.content);
        return;
      }
      if (m.incoming) {
        this.openFileTab();
      }
    })
    // 长按存相册。⚠️ 只对**收到的图片**有意义：自己发出去的图不在沙箱里，
    // 原图本来就在用户手上，再存一份是多余动作。
    .onLongPress(() => {
      if (imgPath.length === 0) {
        return;
      }
      this.clickMuteUntil = Date.now() + 800;
      this.saveImageToAlbum(imgPath, m.content);
    })
  }

  @Builder
  chatTab() {"""

idx = sub(idx, OLD_TAIL, NEW_TAIL, 'chatFileBubble')


# ======================================================================
# J. 版本号
# ======================================================================
app = sub(app, '"versionCode": 5000016,', '"versionCode": 5000017,', 'vercode')
app = sub(app, '"versionName": "5.0.16",', '"versionName": "5.0.17",', 'vername')


# ======================================================================
# 校验
# ======================================================================
after_brace = idx.count('{') - idx.count('}')
assert after_brace == 0, '补丁后 Index.ets 括号不平：%d' % after_brace

for k, want in [
    # 用足够精确的串计数，避免注释里的提及把数字顶高
    ('@Builder\n  chatFileBubble(m: ChatMessage, imgPath: string) {', 1),
    ('this.chatFileBubble(m, this.msgImagePath(m))', 1),
    ('private rebuildRecvIndex(list: ReceivedFile[]): void', 1),
    ('this.rebuildRecvIndex(list);', 1),
    ('private static stripDedupeSuffix(name: string): string', 1),
    ('Index.stripDedupeSuffix(f.name)', 1),
    ('private msgImagePath(m: ChatMessage): string', 1),
    ('this.msgImagePath(m)', 1),
    ('private async saveImageToAlbum(path: string, name: string): Promise<void>', 1),
    ('this.saveImageToAlbum(imgPath, m.content)', 1),
    ('this.saveImageToAlbum(this.imgPreview, this.imgPreviewName)', 1),
    ('private static safeAlbumTitle(raw: string): string', 1),
    ('Index.safeAlbumTitle(', 1),
    ('helper.showAssetsCreationDialog(', 1),
    ('private openImagePreview(path: string, name: string): void', 1),
    ('this.openImagePreview(f.path, f.name)', 1),
    ('this.openImagePreview(imgPath, m.content)', 1),
    ('private clickMuteUntil: number = 0;', 1),
    ('this.clickMuteUntil = Date.now() + 800;', 1),
    ('Date.now() < this.clickMuteUntil', 1),
]:
    got = idx.count(k)
    assert got == want, '校验失败：%r 出现 %d 次，期望 %d' % (k, got, want)

assert idx.count('openImagePreview(f)') == 0, '旧调用点没清干净'
assert idx.count('private openImagePreview(f: ReceivedFile): void') == 0, '旧签名没清干净'


# ======================================================================
# 备份 + 统一落盘
# ======================================================================
if not os.path.isdir(BACKUP):
    os.makedirs(BACKUP)
shutil.copyfile(F_INDEX, os.path.join(BACKUP, 'Index.ets'))
shutil.copyfile(F_APP, os.path.join(BACKUP, 'app.json5'))

n_before = read(F_INDEX).count('\n')
write(F_INDEX, idx)
write(F_APP, app)

print('OK - 5.0.17 补丁已应用')
print('  Index.ets 行数: %d -> %d' % (n_before, idx.count('\n')))
print('  备份: %s' % BACKUP)
