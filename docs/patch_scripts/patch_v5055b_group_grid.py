# -*- coding: utf-8 -*-
"""
5.0.55 ②（UI 层）：把同批的多条媒体消息**聚合成一个气泡**，显示成宫格多缩略图，
且图片/视频不再显示文件名（vivi 2026-10-02 要求）。

⚠️ 核心原则：**显示层聚合，记账层不变**。
   `ChatGroup.msgs` 里的每个元素都是 `this.chat` 里的**真实消息对象**（同一引用），
   所以「点第 k 张打开第 k 张」「删第 k 条不影响其余」「每张各有自己的相册条目」
   全部照旧 —— 5.0.53 修的东西一个都没丢。

幂等：哨兵 `chatGroupBubble`。写文件保持 LF。
"""
import io, sys

IX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
AJ = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'

SENTINEL = 'chatGroupBubble'

# ================================================================= 1. import
I_OLD = "import { LanService, ServiceSnapshot, ServiceState, ChatMessage } from '../service/LanService';"
I_NEW = ("import { LanService, ServiceSnapshot, ServiceState, ChatMessage, ChatGroup } "
         "from '../service/LanService';")

# ================================================================= 2. @State
S_OLD = """  /** 上一次算出来的分组签名，避免每次刷新都换引用（见 syncChatMediaPaths） */
  private chatMediaGroupsSig: string = '';
"""
S_NEW = """  /** 上一次算出来的分组签名，避免每次刷新都换引用（见 syncChatMediaPaths） */
  private chatMediaGroupsSig: string = '';
  /**
   * ★ 5.0.55：把消息按**批号**聚合成「气泡」后的列表 —— 同一次接收的多张图片/视频
   *   合成一个气泡（宫格多缩略图）。⚠️ 只是**显示**分组，组内每条仍各自独立记账
   *   （见 `ChatGroup` 与 `buildChatGroups` 的注释）。
   */
  @State chatGroups: ChatGroup[] = [];
  /** 分组签名 —— 没变就不换引用（避免每次刷新重建整个消息列表） */
  private chatGroupsSig: string = '';
"""

# ================================================================= 3. 调用点（两处）
C1_OLD = """      // 聊天条数变了 -> 重算每条消息的媒体路径（新收到的图/视频要能立刻出缩略图）
      this.syncChatMediaPaths();"""
C1_NEW = """      // 聊天条数变了 -> 重算每条消息的媒体路径（新收到的图/视频要能立刻出缩略图）
      this.syncChatMediaPaths();
      // ★ 5.0.55：条数变了也要重算「气泡分组」（同批的多条媒体要合成一个气泡）
      this.buildChatGroups();"""

C2_OLD = """    // 气泡长按存图依赖「文件名->沙箱路径」反查；文件一变就重算（见 syncChatMediaPaths）
    this.syncChatMediaPaths();"""
C2_NEW = """    // 气泡长按存图依赖「文件名->沙箱路径」反查；文件一变就重算（见 syncChatMediaPaths）
    this.syncChatMediaPaths();
    // ★ 5.0.55：文件列表一变，缩略图的可用来源可能变（沙箱副本被删 -> 改用缓存小图）
    this.buildChatGroups();"""

# ================================================================= 4. buildChatGroups 等方法
# 插在 syncChatMediaPaths 的收尾之后（用它的结尾做锚点）
M_OLD = """    // 分组：签名没变就不换引用（下面那张表同理）
    if (sig !== this.chatMediaGroupsSig) {
      this.chatMediaGroupsSig = sig;
      this.chatMediaGroups = g;
"""
M_NEW_PREFIX = """    // 分组：签名没变就不换引用（下面那张表同理）
    if (sig !== this.chatMediaGroupsSig) {
      this.chatMediaGroupsSig = sig;
      this.chatMediaGroups = g;
"""

# ================================================================= 5. ForEach 换数据源
F_OLD = """          ForEach(this.chat, (m: ChatMessage) => {
            ListItem() {
              this.chatBubble(m)
            }
            // ⚠️ key 带上 `videoThumbTick`：视频首帧是**异步**解出来的，
            //    key 不变的话 ForEach 会复用旧行、缩略图永远不出现。
            //    List 是懒加载的，只重建可见那几行，代价可忽略。
          }, (m: ChatMessage) => `${m.id}|${this.videoThumbTick}|${this.thumbTick}|${this.mediaCountOf(m.id)}|${this.chatMediaPaths.has(m.id) ? (this.chatMediaPaths.get(m.id) ?? '') : ''}|${this.albumPartOf(m.id, 0, 0).length > 0 ? 1 : 0}|${this.albumPartOf(m.id, 0, 1)}`)"""
F_NEW = """          // ★ 5.0.55：数据源从「每条消息」换成「每个气泡（可能含多条消息）」——
          //   同一次接收的多张图片/视频聚合成一个宫格气泡。
          ForEach(this.chatGroups, (g: ChatGroup) => {
            ListItem() {
              this.chatGroupBubble(g)
            }
            // ⚠️ key 带上 `videoThumbTick`：视频首帧是**异步**解出来的，
            //    key 不变的话 ForEach 会复用旧行、缩略图永远不出现。
            //    List 是懒加载的，只重建可见那几行，代价可忽略。
            // ★ 5.0.55：还要带上组内**每条**的媒体路径与相册条目 ——
            //   路径从空变实、相册条目从无到有，都要让这一行重建。
          }, (g: ChatGroup) => `${g.key}|${this.videoThumbTick}|${this.thumbTick}|${this.groupMediaSig(g)}|${this.groupAlbumSig(g)}`)"""

# ================================================================= 6. chatFileBubble：媒体不显示文件名
B_OLD = """      Column({ space: 2 }) {
        Text(m.incoming ? '收到文件' : '已发送文件')
          .fontSize(11)
          .fontColor(m.incoming ? C_SUB : '#DCE8FF')
        // 5.0.50：文件名**必须**带宽度上限 —— wrapContent 的 Row 会用「无限宽」
        //   测量子项，长文件名单行摊开、直接画出气泡背景之外
        //   （vivi 反馈「气泡中文件名会溢出气泡」）。
        //   `maxLines(2)` 只有拿到有限宽度才会真的折行，所以把约束一路下沉到 Text。
        Text(m.content)
          .fontSize(15)
          .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
          .maxLines(2)
          .wordBreak(WordBreak.BREAK_ALL)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .constraintSize({ maxWidth: '100%' })
"""
B_NEW = """      Column({ space: 2 }) {
        Text(m.incoming ? '收到文件' : '已发送文件')
          .fontSize(11)
          .fontColor(m.incoming ? C_SUB : '#DCE8FF')
        // ★ 5.0.55（vivi 2026-10-02）：**图片/视频不再显示文件名** ——
        //   缩略图已经说明内容了，再挂一串 `IMG_20260907_092804.jpg` 只是噪音。
        //   非媒体的文件（zip / pdf / apk…）没有缩略图，文件名是**唯一**的标识，
        //   必须保留。判据用「有没有可显示的媒体」而不是扩展名 ——
        //   后者在媒体还没落盘时会把文件名闪出来一下再消失。
        if (!(mediaPath.length > 0 && this.isMediaName(mediaPath))) {
          // 5.0.50：文件名**必须**带宽度上限 —— wrapContent 的 Row 会用「无限宽」
          //   测量子项，长文件名单行摊开、直接画出气泡背景之外
          //   （vivi 反馈「气泡中文件名会溢出气泡」）。
          //   `maxLines(2)` 只有拿到有限宽度才会真的折行，所以把约束一路下沉到 Text。
          Text(m.content)
            .fontSize(15)
            .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
            .maxLines(2)
            .wordBreak(WordBreak.BREAK_ALL)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .constraintSize({ maxWidth: '100%' })
        }
"""

# ================================================================= 7. 版本号
AJ_OLD = """    "versionCode": 5000054,
    "versionName": "5.0.54",
"""
AJ_NEW = """    "versionCode": 5000055,
    "versionName": "5.0.55",
"""


# ---------------------------------------------------------------- 新方法块
NEW_METHODS = '''
  /**
   * ★ 5.0.55：把消息列表按**批号**聚合成「气泡」列表。
   *
   *   同一次接收的多张图片/视频（5.0.53 拆成了 N 条消息、共享同一个 `batchId`）
   *   在这里合成**一个**气泡 → UI 渲染成宫格多缩略图。
   *
   * ⚠️⚠️ 只是**显示**聚合，**绝不**合并消息本身：
   *   `ChatGroup.msgs` 里的每个元素都是 `this.chat` 里的真实对象（同一引用），
   *   所以「点第 k 张打开第 k 张」「删第 k 条不影响其余」「每张各有自己的相册条目」
   *   全部照旧 —— 5.0.53 修的东西一个都没丢。
   *   如果为了「一个气泡」去把消息合并成一条，等于把 5.0.53 的修复废掉
   *   （回退到「删一张整批失效 + 点不到第 2 张」），千万别那么干。
   *
   * 空 `batchId`（单发 / 发送方向 / 文本 / 5.0.55 之前的历史数据）→ 各自一个气泡，
   * 与改动前行为完全一致。
   */
  private buildChatGroups(): void {
    const src: ChatMessage[] = this.chat;
    const out: ChatGroup[] = [];
    let i: number = 0;
    while (i < src.length) {
      const m: ChatMessage = src[i];
      const g: ChatGroup = new ChatGroup();
      g.msgs.push(m);
      let j: number = i + 1;
      // 同批消息一定是**连续**落进去的（`appendFileChat` 一个循环里连续 append），
      // 所以只往右扫、不跨消息找。
      if (m.batchId.length > 0 && m.kind === 'file') {
        while (j < src.length) {
          const n: ChatMessage = src[j];
          if (n.batchId !== m.batchId || n.kind !== 'file') {
            break;
          }
          g.msgs.push(n);
          j += 1;
        }
      }
      i = j;
      g.isFiles = m.kind === 'file';
      g.incoming = m.incoming;
      g.timeMs = m.timeMs;
      g.isMedia = this.groupAllMedia(g);
      let ids: string = '';
      for (let k: number = 0; k < g.msgs.length; k++) {
        ids += `${g.msgs[k].id},`;
      }
      g.key = ids;
      out.push(g);
    }
    // 签名没变就不换引用 —— 这个方法在每次 refreshReceived 里都会跑，
    // 无条件换引用等于每次刷新都把整个消息列表重建一遍。
    let sig: string = '';
    for (let k: number = 0; k < out.length; k++) {
      sig += `${out[k].key}|${out[k].isMedia ? 1 : 0};`;
    }
    if (sig !== this.chatGroupsSig) {
      this.chatGroupsSig = sig;
      this.chatGroups = out;
    }
  }

  /**
   * 这一组是不是「**不止一张**、全是图片/视频、且是**收到**的」——
   * 只有这种才渲染成宫格气泡。
   *
   * ⚠️ 三个条件缺一不可：
   *   - 「不止一张」：单张走原来的文件名气泡（观感不变，风险最小）；
   *   - 「全是媒体」：混批（1 张图 + 1 个 zip）在 5.0.53 就没拆，这里也不会成组；
   *   - 「收到的」：用户要的是「**接受的**图片和视频」（vivi 2026-10-02）。
   *     自己发出去的那批点气泡只是跳文件页，没有相册语义，改成宫格没意义。
   *
   * ⚠️ 判据只看**消息本身**（`mediaNamesOf` 读 `m.files` / `m.content`），
   *   不看沙箱里还剩几个文件 —— 否则「自动存相册后删掉沙箱副本」会让它
   *   中途从宫格塌回文件名气泡（5.0.52 那个「下标塌缩」的同款病因）。
   */
  private groupAllMedia(g: ChatGroup): boolean {
    if (g.msgs.length < 2 || g.msgs[0].kind !== 'file' || !g.msgs[0].incoming) {
      return false;
    }
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.mediaNamesOf(g.msgs[i]).length === 0) {
        return false;
      }
    }
    return true;
  }

  /** 组内**每条**消息的媒体路径签名（ForEach key 用，见调用点注释） */
  private groupMediaSig(g: ChatGroup): string {
    let s: string = '';
    for (let i: number = 0; i < g.msgs.length; i++) {
      const mid: string = g.msgs[i].id;
      const v: string | undefined = this.chatMediaPaths.get(mid);
      s += `${v === undefined ? '' : v},`;
    }
    return s;
  }

  /** 组内**每条**消息的相册条目签名（ForEach key 用） */
  private groupAlbumSig(g: ChatGroup): string {
    let s: string = '';
    for (let i: number = 0; i < g.msgs.length; i++) {
      const mid: string = g.msgs[i].id;
      s += `${this.albumPartOf(mid, 0, 0).length > 0 ? 1 : 0}` +
        `${this.albumPartOf(mid, 0, 1).length > 0 ? 1 : 0}`;
    }
    return s;
  }

  /** 组内**全部**消息都被勾选 */
  private isGroupFullySelected(g: ChatGroup): boolean {
    if (g.msgs.length === 0) {
      return false;
    }
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.chatSelected.indexOf(g.msgs[i].id) < 0) {
        return false;
      }
    }
    return true;
  }

  /** 组内**部分**消息被勾选（勾选圆显示成中间态） */
  private isGroupPartlySelected(g: ChatGroup): boolean {
    if (this.isGroupFullySelected(g)) {
      return false;
    }
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.chatSelected.indexOf(g.msgs[i].id) >= 0) {
        return true;
      }
    }
    return false;
  }

  /**
   * ★ 5.0.55：长按一个**宫格气泡** → 整组进多选（已在多选态则整组切换）。
   *
   * 为什么按组：用户视觉上看到的就是「一个气泡」，长按它却只选中其中一张会很怪。
   * 想只删某一张时，在多选态下**点那一张缩略图**即可单独切换（见 chatMediaGrid）。
   * ⇒ 整组删 / 单张删，两条路都通。
   */
  private enterChatGroupSelect(g: ChatGroup): void {
    const ids: string[] = [];
    for (let i: number = 0; i < g.msgs.length; i++) {
      ids.push(g.msgs[i].id);
    }
    if (!this.chatSelectMode) {
      this.chatSelectMode = true;
      this.chatSelected = ids;
      return;
    }
    const all: boolean = this.isGroupFullySelected(g);
    let out: string[] = this.chatSelected.slice();
    if (all) {
      for (let i: number = 0; i < ids.length; i++) {
        out = Index.removeStr(out, ids[i]);
      }
    } else {
      for (let i: number = 0; i < ids.length; i++) {
        if (out.indexOf(ids[i]) < 0) {
          out.push(ids[i]);
        }
      }
    }
    // ⚠️ 必须整体换引用：ArkUI 不会因为数组 push/splice 就重渲染
    this.chatSelected = out;
    if (out.length === 0) {
      this.chatSelectMode = false;
    }
  }

  /** 从字符串数组里去掉一个值（整体换引用） */
  private static removeStr(list: string[], v: string): string[] {
    const out: string[] = [];
    for (let i: number = 0; i < list.length; i++) {
      if (list[i] !== v) {
        out.push(list[i]);
      }
    }
    return out;
  }
'''

# ---------------------------------------------------------------- 新 @Builder 块
NEW_BUILDERS = '''
  /**
   * ★ 5.0.55：一个「气泡」—— 单条消息走老路径，同批多张媒体走宫格。
   *
   * ⚠️ 单条时**原样转发**给 `chatBubble`：所有既有行为（点击分流、长按多选、
   *   勾选圆、文件名气泡）完全不变，零风险。
   */
  @Builder
  chatGroupBubble(g: ChatGroup) {
    if (g.isMedia) {
      this.chatMediaBubble(g)
    } else {
      this.chatBubble(g.msgs[0])
    }
  }

  /**
   * ★ 5.0.55：宫格气泡 —— 同一次接收的多张图片/视频，一个气泡里多缩略图，
   * **不显示文件名**（vivi 2026-10-02 要求）。
   *
   * 结构与 `chatBubble` 同构（Row + Blank 顶开、左/右对齐、多选勾选圆、
   * 长按进多选），只是中间从「文件名」换成「缩略图宫格」。
   * ⚠️ 没有 `constraintSize(maxWidth:'92%')` 会重演 5.0.50 那个
   *    「百分比约束落到无限宽」的老坑 —— 所以两层都给了上限。
   */
  @Builder
  chatMediaBubble(g: ChatGroup) {
    Row() {
      if (!g.incoming) {
        Blank()
      }
      Column({ space: 3 }) {
        // 多选态：左上角勾选圆（整组全选 = ✓，部分选中 = −，与文件页一致）
        if (this.chatSelectMode) {
          Text(this.isGroupFullySelected(g) ? '✓' : (this.isGroupPartlySelected(g) ? '−' : ''))
            .fontSize(13)
            .fontColor(Color.White)
            .textAlign(TextAlign.Center)
            .width(22)
            .height(22)
            .borderRadius(11)
            .backgroundColor(this.isGroupPartlySelected(g) ? '#9AA4B0'
              : (this.isGroupFullySelected(g) ? C_PRIMARY : '#00000000'))
            .border({
              width: this.isGroupFullySelected(g) ? 0 : 1.5,
              color: '#C0C6CF'
            })
        }
        Text(`${g.incoming ? g.msgs[0].peerName : (this.snapshot.deviceName.length > 0 ? this.snapshot.deviceName : '我')} ${fmtTime(g.timeMs)}`)
          .fontSize(10)
          .fontColor(C_SUB)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        this.chatMediaGrid(g)

        if (g.incoming && !this.chatSelectMode) {
          Text(`${g.msgs.length} 张 · ${this.bubbleHintOf(g.msgs[0], '')}`)
            .fontSize(10)
            .fontColor(C_PRIMARY)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .padding({ left: 8, right: 8, top: 6, bottom: 6 })
      .backgroundColor(g.incoming ? C_CARD : C_PRIMARY)
      .borderRadius(10)
      .constraintSize({ maxWidth: '92%' })
      .onClick(() => {
        if (Date.now() < this.clickMuteUntil) {
          return;
        }
        // 多选态下点空白处 = 整组切换；想只选一张请点那张缩略图（见 chatMediaGrid）
        if (this.chatSelectMode) {
          this.enterChatGroupSelect(g);
        }
      })
      .gesture(
        LongPressGesture({ repeat: false, duration: 400 })
          .onAction(() => {
            // 普通态：长按进入多选（整组选中）
            this.clickMuteUntil = Date.now() + 800;
            this.enterChatGroupSelect(g);
          })
      )

      if (g.incoming) {
        Blank()
      }
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
  }

  /** 缩略图宫格边长（vp）。3 列 × 88 + 2×4 间距 = 272，塞得进 88% 宽的气泡 */
  private static GRID_SIDE: number = 88;

  /**
   * ★ 5.0.55：缩略图宫格（每行 3 个，`Flex.wrap` 自动换行）。
   *
   * ⚠️ **每张缩略图有自己的 `onClick`**，直接落到它**自己那条消息**上：
   *   普通态 → `onFileBubbleClick(m)`（该张自己的相册条目 / 应用内预览）；
   *   多选态 → 切换**该张**的勾选。
   *   这正是「点第 2 张就能打开第 2 张」的关键 —— 5.0.52 之前做不到，
   *   是因为那时 N 张图共用**一个**消息、只有一个点击入口。
   *
   * ⚠️ `Stack` 里垫的标记是「沙箱副本没了、但缓存缩略图还在」= 用户已在系统相册
   *   删过这张（与 `onFileBubbleClick` 的判定口径一致，只是这里只做**视觉提示**，
   *   不做实际判定 —— 真正的判定要走探活，代价高，不能挂在每次渲染上）。
   */
  @Builder
  chatMediaGrid(g: ChatGroup) {
    Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.Start }) {
      ForEach(g.msgs, (m: ChatMessage) => {
        Stack() {
          this.mediaThumb(this.mediaSrcOf(m, 0), 88)
          if (this.albumPartOf(m.id, 0, 0).length === 0
            && this.albumPartOf(m.id, 0, 1).length > 0) {
            Text('已删')
              .fontSize(10)
              .fontColor('#FFFFFF')
              .padding({ left: 4, right: 4, top: 1, bottom: 1 })
              .backgroundColor('#99000000')
              .borderRadius(4)
          }
        }
        .margin({ right: 4, bottom: 4 })
        .onClick(() => {
          if (Date.now() < this.clickMuteUntil) {
            return;
          }
          if (this.chatSelectMode) {
            this.toggleChatSelect(m.id);
            return;
          }
          this.onFileBubbleClick(m);
        })
      }, (m: ChatMessage) => `${m.id}|${this.videoThumbTick}|${this.thumbTick}|${this.mediaSrcOf(m, 0)}`)
    }
    .width('100%')
  }
'''


def apply(path, pairs, label):
    s = io.open(path, encoding='utf-8', newline='').read()
    for i, (old, new) in enumerate(pairs):
        n = s.count(old)
        assert n == 1, '%s 锚点#%d 命中 %d 次' % (label, i + 1, n)
        assert s.count(new) == 0, '%s 新文本#%d 此前已存在' % (label, i + 1)
    for old, new in pairs:
        s = s.replace(old, new)
    return s


src = io.open(IX, encoding='utf-8', newline='').read()
if SENTINEL in src:
    print('ALREADY APPLIED')
    sys.exit(0)

# 方法块插在「消息页：长按多选删除」区块标题**之前**（方法区，不是 @Builder 区）
METH_ANCHOR = """  // ------------------------------------------------------------------
  // 消息页：长按多选删除
  // ------------------------------------------------------------------
"""
assert src.count(METH_ANCHOR) == 1, '方法区锚点未命中'

# @Builder 块插在 `chatFileBubble` 定义之前
BUI_ANCHOR = """  /**
   * 「文件」消息的气泡本体（**纯展示**：缩略图 + 文件名 + 提示）。
"""
assert src.count(BUI_ANCHOR) == 1, '@Builder 锚点未命中'

new_ix = apply(IX, [(I_OLD, I_NEW), (S_OLD, S_NEW), (C1_OLD, C1_NEW), (C2_OLD, C2_NEW),
                    (F_OLD, F_NEW), (B_OLD, B_NEW)], 'Index')
new_ix = new_ix.replace(METH_ANCHOR, NEW_METHODS + '\n' + METH_ANCHOR)
new_ix = new_ix.replace(BUI_ANCHOR, NEW_BUILDERS + '\n' + BUI_ANCHOR)
new_aj = apply(AJ, [(AJ_OLD, AJ_NEW)], 'app.json5')

for sym, want in [('ChatGroup } from', 1),
                  ('@State chatGroups: ChatGroup[] = [];', 1),
                  ('private buildChatGroups(): void {', 1),
                  ('this.buildChatGroups();', 2),
                  ('private groupAllMedia(', 1),
                  ('private groupMediaSig(', 1),
                  ('private groupAlbumSig(', 1),
                  ('private isGroupFullySelected(', 1),
                  ('private isGroupPartlySelected(', 1),
                  ('private enterChatGroupSelect(', 1),
                  ('private static removeStr(', 1),
                  ('chatGroupBubble(g: ChatGroup) {', 1),
                  ('chatMediaBubble(g: ChatGroup) {', 1),
                  ('chatMediaGrid(g: ChatGroup) {', 1),
                  ('ForEach(this.chatGroups, (g: ChatGroup) => {', 1),
                  ('this.enterChatGroupSelect(g);', 2),
                  ('this.toggleChatSelect(m.id);', 3),
                  ('GRID_SIDE: number = 88;', 1),
                  ('if (!(mediaPath.length > 0 && this.isMediaName(mediaPath))) {', 1)]:
    got = new_ix.count(sym)
    assert got == want, '符号校验失败 %r: 期望 %d 实为 %d' % (sym, want, got)
    print('  OK %2d  %s' % (got, sym[:56]))

assert 'ForEach(this.chat, (m: ChatMessage) => {' not in new_ix, '旧 ForEach 仍在'
assert '5000055' in new_aj and '"5.0.55"' in new_aj

delta = {}
for ch in '{}()[]':
    delta[ch] = new_ix.count(ch) - src.count(ch)
print('Index 括号增量:', delta)

io.open(IX, 'w', encoding='utf-8', newline='\n').write(new_ix)
io.open(AJ, 'w', encoding='utf-8', newline='\n').write(new_aj)
print('OK: 5.0.55 ② UI 层已应用')
