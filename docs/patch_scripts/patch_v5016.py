# -*- coding: utf-8 -*-
"""5.0.16 补丁 —— vivi 2026-10-01 真机反馈两项诉求。

诉求 1：文件页点删除后，确认弹窗的文件名字体过大 → 显示不全
        → 废弃系统 showDialog，改**自绘 overlay 弹窗**（Promise resolve 模式，
          调用点写法不变）：标题固定 16fp 短文案，文件名单列一块 13fp 小字
          （BREAK_ALL + maxLines(5)），多长都能整段折行看全。

诉求 2：接收到的图片显示缩略图 + 点击打开
        → 行内 48×48 缩略图（fileUri.getUriFromPath + sourceSize(96) 压解码尺寸），
          普通态点击进全屏预览（捏合缩放 / 双击复位 / 放大后拖动 / 关闭按钮 / 返回键）。

幂等：文件里已出现 SENTINEL 则整体跳过。
保险：每条替换都断言「旧锚点恰好 1 处」「新文本此前不存在」，
      全部在内存里构造完再统一落盘（任一失败 → 一个字都不写）。
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
F_INDEX = os.path.join(ROOT, 'entry/src/main/ets/pages/Index.ets')
F_APP = os.path.join(ROOT, 'AppScope/app.json5')
BACKUP = os.path.join(ROOT, '.backup_v5016')

SENTINEL_MARKS = ['imgPreviewView', 'confirmDialogView', 'settleConfirm']


def read(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        return f.read().replace('\r\n', '\n')


def sub(s, old, new, tag):
    """整块替换：旧锚点必须恰好一处，新文本必须此前不存在。"""
    n = s.count(old)
    assert n == 1, '[%s] 旧锚点命中 %d 处（期望 1）' % (tag, n)
    assert new not in s, '[%s] 新文本已存在 —— 疑似重复应用' % tag
    return s.replace(old, new)


# ======================================================================
# Index.ets
# ======================================================================
idx = read(F_INDEX)
BASE_BALANCE = idx.count('{') - idx.count('}')

if all(m in idx for m in SENTINEL_MARKS):
    print('ALREADY APPLIED — 5.0.16 补丁此前已打过，跳过')
    sys.exit(0)

# ---- 1. import：新增 fileUri；promptAction 已无代码引用，一并摘掉 ----
idx = sub(
    idx,
    "import { picker } from '@kit.CoreFileKit';\n"
    "import { window, promptAction } from '@kit.ArkUI';",
    "import { picker, fileUri } from '@kit.CoreFileKit';\n"
    "import { window } from '@kit.ArkUI';",
    'import',
)

# ---- 2. 变更记录（插在「第六轮（5.0.14）」之前） ----
idx = sub(
    idx,
    ' * ## 2026-10-01 第六轮（5.0.14）',
    ''' * ## 2026-10-01 第八轮（5.0.16，vivi 真机实测）
 * | 诉求 | 落法 |
 * |---|---|
 * | 删除确认弹窗的文件名字体过大、显示不全 | 系统 `showDialog` 的 **title 字号固定、且不按内容折行** —— 把「删除『<长文件名>』？」整句塞进 title，长名必然被截。**改为自绘弹窗**：标题固定 16fp 短文案，文件名单独一块 **13fp** 小字（`wordBreak(BREAK_ALL)` + `maxLines(5)`），多长的名字都能整段折行看全 |
 * | 收到的图片想要缩略图、点了能看大图 | ① 按扩展名识别图片 → 行内 **48×48 缩略图**（`fileUri.getUriFromPath()` 取沙箱 URI，配 `sourceSize(96)` 压解码尺寸 —— 不压的话 40 张原图会被整张解进内存）；② 普通态**点一下进全屏预览**（双指缩放 / 双击复位 / 放大后可拖动 / 返回键或「关闭」退出） |
 *
 * ## 2026-10-01 第六轮（5.0.14）''',
    '变更记录',
)

# ---- 3. 新增状态字段 ----
idx = sub(
    idx,
    "  /** 网页地址二维码弹窗是否可见 */\n"
    "  @State showQr: boolean = false;\n",
    '''  /** 网页地址二维码弹窗是否可见 */
  @State showQr: boolean = false;

  // ---------------- 危险操作确认弹窗（自绘，替代系统 showDialog） ----------------
  /**
   * 确认弹窗是否可见。
   *
   * ⚠️ 为什么不用系统 `showDialog`（vivi 2026-10-01 真机：「删除弹窗的文件名字体过大、
   *    显示不全」）：系统对话框的 **title 字号是内部固定的，且不按内容折行**，
   *    把「删除『<长文件名>』？」整句塞进 title，长名必然被截。
   *    自绘之后文件名可以单列一块小字、按需折行 —— 想多长都能看全。
   */
  @State confirmVisible: boolean = false;
  /** 弹窗标题（**固定短文案**，如「删除文件」——长内容一律走 confirmDetail） */
  @State confirmTitle: string = '';
  /** 要重点展示全的内容（文件名 / 文件个数），小字、可折行 */
  @State confirmDetail: string = '';
  /** 副标题（风险提示之类的一句话） */
  @State confirmNote: string = '';
  /** 确认按钮文案 */
  @State confirmOkText: string = '删除';
  /** 等用户点击的那个 Promise 的 resolve —— null = 当前没有弹窗在等 */
  private confirmResolve: ((v: boolean) => void) | null = null;

  // ---------------- 图片预览 ----------------
  /** 正在全屏预览的图片路径；空串 = 没有预览 */
  @State imgPreview: string = '';
  /** 预览中的文件名（顶栏显示） */
  @State imgPreviewName: string = '';
  /** 当前缩放倍率 */
  @State imgScale: number = 1;
  /** 放大后用 translate 挪出来的位移（vp） */
  @State imgOffX: number = 0;
  @State imgOffY: number = 0;
  /** 一次捏合开始时的基准倍率（PinchGesture 给的是**相对**倍率） */
  private imgPinchBase: number = 1;
  /** 一次拖动开始时的基准位移 */
  private imgDragBaseX: number = 0;
  private imgDragBaseY: number = 0;
''',
    'state',
)

# ---- 4. onBackPress：注释 + 两个新分支 ----
idx = sub(
    idx,
    '''   *    返回的语义应当是「先退掉最上层的临时状态」：
   *      多选态 → 取消多选；二维码弹窗 → 关弹窗；发文件弹窗 → 关弹窗；
   *      都不是 → 交还给系统（正常退出）。''',
    '''   *    返回的语义应当是「先退掉最上层的临时状态」：
   *      确认弹窗 → 当「取消」结掉它；图片预览 → 关预览；多选态 → 取消多选；
   *      二维码弹窗 → 关弹窗；发文件弹窗 → 关弹窗；
   *      都不是 → 交还给系统（正常退出）。''',
    'onBackPress-doc',
)

idx = sub(
    idx,
    '''  onBackPress(): boolean {
    if (this.fileSelectMode) {
      this.exitFileSelect();
      return true;
    }''',
    '''  onBackPress(): boolean {
    // 确认弹窗在最上层 —— 必须**先把它结掉**：那个 await 还挂着，
    // 不结掉的话用户下一次点删除时，两次等待会串在同一个 Promise 上。
    if (this.confirmVisible) {
      this.settleConfirm(false);
      return true;
    }
    if (this.imgPreview.length > 0) {
      this.closeImagePreview();
      return true;
    }
    if (this.fileSelectMode) {
      this.exitFileSelect();
      return true;
    }''',
    'onBackPress-body',
)

# ---- 5. confirmDialog：系统弹窗 -> 自绘 ----
idx = sub(
    idx,
    '''  /**
   * 危险操作确认框。
   *
   * @returns true = 用户点了第二个按钮（确认/删除）
   */
  private async confirmDialog(title: string, message: string, okText: string = '删除'): Promise<boolean> {
    try {
      const buttons: promptAction.Button[] = [
        { text: '取消', color: '#666666' },
        { text: okText, color: '#E84026' }
      ];
      const res: promptAction.ShowDialogSuccessResponse =
        await this.getUIContext().getPromptAction().showDialog({
          title: title,
          message: message,
          buttons: buttons
        });
      return res.index === 1;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `确认框弹出失败: ${err.code}`);
      return false;
    }
  }''',
    '''  /**
   * 危险操作确认框（**自绘**，不是系统 `showDialog`）。
   *
   * 调用写法与 Promise 版完全一致：`const ok = await this.confirmDialog(...)`，
   * 内部把 resolve 存起来，等用户点按钮时再兑现（见 settleConfirm）。
   *
   * @param title  标题 —— **保持短**，长内容一律走 detail
   * @param note   副标题：风险提示之类的一句话
   * @param okText 确认按钮文案
   * @param detail 需要**完整展示**的内容（文件名 / 个数）：单独一块小字，可折行
   * @returns true = 用户点了确认按钮
   */
  private confirmDialog(title: string, note: string,
    okText: string = '删除', detail: string = ''): Promise<boolean> {
    // 上一次还没收尾（用户没点按钮就切走了）：先当「取消」结掉，避免 await 悬挂
    this.settleConfirm(false);
    this.confirmTitle = title;
    this.confirmDetail = detail;
    this.confirmNote = note;
    this.confirmOkText = okText;
    this.confirmVisible = true;
    return new Promise<boolean>((resolve: (v: boolean) => void) => {
      this.confirmResolve = resolve;
    });
  }

  /** 兑现并关闭确认弹窗（按钮 / 点遮罩 / 返回键，三条路都走它） */
  private settleConfirm(ok: boolean): void {
    const r: ((v: boolean) => void) | null = this.confirmResolve;
    this.confirmResolve = null;
    this.confirmVisible = false;
    if (r !== null) {
      r(ok);
    }
  }

  /**
   * 确认弹窗本体。
   *
   * 版式就是冲着「文件名字体过大显示不全」设计的：
   *   - 标题 16fp 固定短文案；
   *   - 文件名单独一块 **13fp**（比标题小一档）小字，浅底圆角与标题分层，
   *     `wordBreak(BREAK_ALL)` + `maxLines(5)` —— 无空格的长英文名 / 哈希名也能折行，
   *     5 行按 13fp 算≈110 个字符，正常文件名不可能再被截；
   *   - 遮罩点击 = 取消（危险操作默认落在安全侧）。
   */
  @Builder
  confirmDialogView() {
    if (this.confirmVisible) {
      Column() {
        Column({ space: 12 }) {
          Text(this.confirmTitle)
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor(C_TEXT)
            .width('100%')

          if (this.confirmDetail.length > 0) {
            Text(this.confirmDetail)
              .fontSize(13)
              .fontColor(C_TEXT)
              .width('100%')
              .wordBreak(WordBreak.BREAK_ALL)
              .maxLines(5)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .textAlign(TextAlign.Start)
              .padding(10)
              .backgroundColor('#F5F6F8')
              .borderRadius(8)
          }

          if (this.confirmNote.length > 0) {
            Text(this.confirmNote)
              .fontSize(12)
              .fontColor(C_SUB)
              .width('100%')
          }

          Row({ space: 10 }) {
            Button('取消')
              .fontSize(14)
              .height(38)
              .layoutWeight(1)
              .backgroundColor('#F2F2F2')
              .fontColor('#666666')
              .onClick(() => this.settleConfirm(false))
            Button(this.confirmOkText)
              .fontSize(14)
              .height(38)
              .layoutWeight(1)
              .backgroundColor('#FDECEA')
              .fontColor('#E84026')
              .onClick(() => this.settleConfirm(true))
          }
          .width('100%')
          .margin({ top: 2 })
        }
        .width('84%')
        .padding(20)
        .backgroundColor(C_CARD)
        .borderRadius(16)
        // 空 onClick：把落在卡片空白处的点击「吃掉」，免得冒泡到遮罩变成取消
        .onClick(() => {
        })
      }
      .width('100%')
      .height('100%')
      .justifyContent(FlexAlign.Center)
      .backgroundColor('rgba(0,0,0,0.45)')
      .onClick(() => this.settleConfirm(false))
    }
  }''',
    'confirmDialog',
)

# ---- 6. 图片缩略图 / 全屏预览一整节（插在 stateText 之前） ----
idx = sub(
    idx,
    '  private stateText(): string {',
    '''  // ------------------------------------------------------------------
  // 接收到的图片：缩略图 + 全屏预览
  // ------------------------------------------------------------------

  /**
   * 文件名是不是 `Image` 能直接渲染的图片（按扩展名判断）。
   *
   * 为什么按扩展名而不是按内容嗅探：接收链路**保留了原始文件名**，
   * 而按内容嗅探要么先读文件头（40 行 = 40 次 IO），要么引入解码失败路径，
   * 收益不抵成本。后缀对不上顶多是不显示缩略图，不会出错。
   */
  private isImageName(name: string): boolean {
    const dot: number = name.lastIndexOf('.');
    if (dot < 0) {
      return false;
    }
    const ext: string = name.substring(dot + 1).toLowerCase();
    return ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'gif'
      || ext === 'webp' || ext === 'bmp' || ext === 'heic' || ext === 'heif'
      || ext === 'avif' || ext === 'ico' || ext === 'tif' || ext === 'tiff';
  }

  /**
   * 沙箱路径 → 可直接喂给 `Image` 的 `file://` URI。
   *
   * ⚠️ **不能自己拼 `'file://' + path`**：沙箱 URI 的规范形态是
   *    `file://<bundleName>/<绝对路径>`，中间那段 bundleName 只有
   *    `fileUri.getUriFromPath()` 知道怎么补。手拼的地址 `Image` 认不出来，
   *    症状是缩略图恒定空白、也不报错。
   *    取不到时才退回手拼（老形态），聊胜于无。
   */
  private imageUri(path: string): string {
    try {
      return fileUri.getUriFromPath(path);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `取图片 URI 失败: ${err.code} ${path}`);
      return `file://${path}`;
    }
  }

  /** 点开一张图片：进全屏预览 */
  private openImagePreview(f: ReceivedFile): void {
    this.imgPreview = f.path;
    this.imgPreviewName = f.name;
    this.imgScale = 1;
    this.imgPinchBase = 1;
    this.imgOffX = 0;
    this.imgOffY = 0;
  }

  /** 关闭全屏预览并复位缩放 / 位移（否则下一张图会带着上一张的倍率打开） */
  private closeImagePreview(): void {
    this.imgPreview = '';
    this.imgPreviewName = '';
    this.imgScale = 1;
    this.imgPinchBase = 1;
    this.imgOffX = 0;
    this.imgOffY = 0;
  }

  /**
   * 全屏图片预览。
   *
   * `Image` 自身没有缩放能力，靠 `.scale()` + `.translate()` 做 ——
   * 所以放大后拖动的位移也要自己按倍率算（这里只做平移，不做边界回弹：
   * 照片查看器里那属于锦上添花，先保证不崩、不飘）。
   *
   * 关闭的三条路：顶栏「关闭」/ 双击复位后再点 / **系统返回键**（见 onBackPress）。
   * ⚠️ 刻意**不做**「单击任意处关闭」：放大状态下单击太容易误触，
   *    而双击复位本身就会吃掉单击。
   */
  @Builder
  imgPreviewView() {
    if (this.imgPreview.length > 0) {
      Stack({ alignContent: Alignment.Top }) {
        Image(this.imageUri(this.imgPreview))
          .width('100%')
          .height('100%')
          .objectFit(ImageFit.Contain)
          .scale({ x: this.imgScale, y: this.imgScale })
          .translate({ x: this.imgOffX, y: this.imgOffY })
          .gesture(
            GestureGroup(GestureMode.Parallel,
              // 双指捏合缩放：1x ~ 8x
              PinchGesture({ fingers: 2 })
                .onActionUpdate((e: GestureEvent) => {
                  const s: number = this.imgPinchBase * e.scale;
                  this.imgScale = s < 1 ? 1 : (s > 8 ? 8 : s);
                })
                .onActionEnd(() => {
                  this.imgPinchBase = this.imgScale;
                  // 回到 1x 附近就顺手把位移归零，免得到处飘
                  if (this.imgScale <= 1.02) {
                    this.imgScale = 1;
                    this.imgPinchBase = 1;
                    this.imgOffX = 0;
                    this.imgOffY = 0;
                  }
                }),
              // 单指拖动：只在放大后生效（1x 时拖它就是浪费手势）
              PanGesture({ fingers: 1, distance: 6 })
                .onActionStart(() => {
                  this.imgDragBaseX = this.imgOffX;
                  this.imgDragBaseY = this.imgOffY;
                })
                .onActionUpdate((e: GestureEvent) => {
                  if (this.imgScale > 1) {
                    this.imgOffX = this.imgDragBaseX + e.offsetX;
                    this.imgOffY = this.imgDragBaseY + e.offsetY;
                  }
                }),
              // 双击：>1x 复位，=1x 放大到 2.5x（看细节不用两根手指）
              TapGesture({ count: 2 })
                .onAction(() => {
                  if (this.imgScale > 1) {
                    this.imgScale = 1;
                    this.imgPinchBase = 1;
                    this.imgOffX = 0;
                    this.imgOffY = 0;
                  } else {
                    this.imgScale = 2.5;
                    this.imgPinchBase = 2.5;
                  }
                })
            )
          )

        // 顶栏：文件名 + 关闭。文件名占满剩余宽度，放不下就省略号
        Row({ space: 10 }) {
          Text(this.imgPreviewName)
            .fontSize(13)
            .fontColor('#EAEAEA')
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Button('关闭')
            .fontSize(13)
            .height(32)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#33FFFFFF')
            .fontColor(Color.White)
            .onClick(() => this.closeImagePreview())
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: this.topInset + 10 })
      }
      .width('100%')
      .height('100%')
      // 近黑底：看照片时最不干扰
      .backgroundColor('#F0000000')
    }
  }

  private stateText(): string {''',
    'img-section',
)

# ---- 7. 四个调用点 ----
idx = sub(
    idx,
    "    const ok: boolean = await this.confirmDialog(`删除「${f.name}」？`, '删除后无法恢复');",
    "    const ok: boolean = await this.confirmDialog('删除文件', '删除后无法恢复', '删除', f.name);",
    'call-deleteOne',
)

idx = sub(
    idx,
    "      await this.confirmDialog('清空接收到的文件？', `共 ${all.length} 个文件，删除后无法恢复`, '全部删除');",
    "      await this.confirmDialog('清空接收到的文件', '删除后无法恢复', '全部删除', `共 ${all.length} 个文件`);",
    'call-deleteAll',
)

idx = sub(
    idx,
    """    const ok: boolean = await this.confirmDialog(
      `删除选中的 ${paths.length} 个文件？`, '删除后无法恢复', '删除');""",
    """    const ok: boolean = await this.confirmDialog(
      '删除选中的文件', '删除后无法恢复', '删除', `共 ${paths.length} 个文件`);""",
    'call-batchDelete',
)

idx = sub(
    idx,
    "    const ok: boolean = await this.confirmDialog('清空聊天记录？', '删除后无法恢复');",
    "    const ok: boolean = await this.confirmDialog('清空聊天记录', '删除后无法恢复');",
    'call-clearChat',
)

# ---- 8. 行内缩略图 ----
idx = sub(
    idx,
    '''                Column({ space: 6 }) {
                  // ⚠️ 文件名「一行放得下就一行、放不下才两行」的正确写法**只有**''',
    '''                // 图片缩略图：只给图片类文件。
                // ⚠️ `.sourceSize()` 把解码尺寸压到 96×96 —— 不设的话 40 张
                //    1200 万像素的原图会被**整张**解进内存，列表一滚就是几百 MB。
                //    下面的 Text 是占位（也是解码完成前的样子），真图载入后盖住它。
                if (this.isImageName(f.name)) {
                  Stack() {
                    Text('图片')
                      .fontSize(11)
                      .fontColor('#AAAAAA')
                    Image(this.imageUri(f.path))
                      .width(48)
                      .height(48)
                      .objectFit(ImageFit.Cover)
                      .sourceSize({ width: 96, height: 96 })
                  }
                  .width(48)
                  .height(48)
                  .backgroundColor('#EFF2F6')
                  .borderRadius(8)
                  .clip(true)
                }

                Column({ space: 6 }) {
                  // ⚠️ 文件名「一行放得下就一行、放不下才两行」的正确写法**只有**''',
    'thumb',
)

# ---- 9. 元信息行：钉死单行，别因为多了缩略图就换行 ----
idx = sub(
    idx,
    '''                    Text(`${f.sizeText} · ${f.timeText}`)
                      .fontSize(11)
                      .fontColor(C_SUB)
                      .layoutWeight(1)''',
    '''                    // ⚠️ 钉死单行：左边多了 48vp 缩略图后，这行要是允许折行，
                    //    窄屏上会被挤成两行、把卡片撑高（见 5.0.16 说明）
                    Text(`${f.sizeText} · ${f.timeText}`)
                      .fontSize(11)
                      .fontColor(C_SUB)
                      .layoutWeight(1)
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })''',
    'meta-line',
)

# ---- 10. 行点击：普通态点图片进预览 ----
idx = sub(
    idx,
    '''              .onClick(() => {
                // 普通态点一下不做事（避免误触）；多选态才切换勾选
                if (this.fileSelectMode) {
                  this.toggleFileSelect(f.path);
                }
              })''',
    '''              .onClick(() => {
                if (this.fileSelectMode) {
                  this.toggleFileSelect(f.path);
                } else if (this.isImageName(f.name)) {
                  // 普通态：图片点一下进全屏预览；其它类型不做任何事（避免误触）
                  this.openImagePreview(f);
                }
              })''',
    'row-click',
)

# ---- 11. 根 Stack 挂两个浮层 ----
idx = sub(
    idx,
    '''      // ---------------- 网页地址二维码弹窗 ----------------
      this.qrDialog()
    }''',
    '''      // ---------------- 网页地址二维码弹窗 ----------------
      this.qrDialog()

      // ---------------- 图片全屏预览 ----------------
      this.imgPreviewView()

      // ---------------- 危险操作确认弹窗（始终最上层） ----------------
      this.confirmDialogView()
    }''',
    'root-stack',
)

# ---- 校验：符号引用数为 0 / 等于预期 ----
assert 'promptAction' not in idx.replace('// 旧写法 promptAction.showToast 已标记 deprecated（工程器会告警），', ''), \
    'promptAction 仍有代码引用'
assert idx.count('confirmDialogView()') == 2, 'confirmDialogView 挂载/定义不成对'
assert idx.count('imgPreviewView()') == 2, 'imgPreviewView 挂载/定义不成对'
assert idx.count('settleConfirm(') == 6, 'settleConfirm 调用点数量异常: %d' % idx.count('settleConfirm(')
# 更实在的检查：不允许再有「把文件名拼进标题」的旧调用形式
assert 'confirmDialog(`' not in idx, '仍有调用点用模板串拼标题（旧形式）'
assert idx.count("confirmDialog('删除文件'") == 1
assert idx.count("confirmDialog('清空接收到的文件'") == 1
assert idx.count("confirmDialog(\n      '删除选中的文件'") == 1
assert idx.count("confirmDialog('清空聊天记录'") == 1
# 括号增量一致：每一段替换本身都是配平的，整文件的花括号「收支」不该变
# （不直接比绝对数 —— 注释里本来就可能出现落单的括号，那些在改动前后抵消）
assert idx.count('{') - idx.count('}') == BASE_BALANCE, \
    '括号增量不一致：%d -> %d' % (BASE_BALANCE, idx.count('{') - idx.count('}'))

# ======================================================================
# app.json5
# ======================================================================
app = read(F_APP)
app = sub(app, '"versionCode": 5000015,', '"versionCode": 5000016,', 'app-versionCode')
app = sub(app, '"versionName": "5.0.15",', '"versionName": "5.0.16",', 'app-versionName')

# ======================================================================
# 统一落盘（先备份）
# ======================================================================
if not os.path.isdir(BACKUP):
    os.makedirs(BACKUP)
for src in (F_INDEX, F_APP):
    dst = os.path.join(BACKUP, os.path.basename(src))
    if not os.path.exists(dst):
        shutil.copyfile(src, dst)

with io.open(F_INDEX, 'w', encoding='utf-8', newline='\n') as f:
    f.write(idx)
with io.open(F_APP, 'w', encoding='utf-8', newline='\n') as f:
    f.write(app)

print('OK — 5.0.16 补丁已应用')
print('  Index.ets  %d 行' % idx.count('\n'))
print('  app.json5  versionCode 5000016 / versionName 5.0.16')
print('  备份: %s' % BACKUP)
