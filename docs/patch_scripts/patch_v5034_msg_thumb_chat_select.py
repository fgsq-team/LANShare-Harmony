# -*- coding: utf-8 -*-
"""
5.0.34：消息页缩略图 + 长按多选删除

改动三处（Index.ets / LanService.ets / app.json5）：
1. 消息页文件气泡：加 48vp 等比缩略图 + 文件名（与文件页同款 mediaThumb）。
2. 文件页缩略图保持原比例：在 mediaThumb 渲染时**按需**触发比例测量 / 首帧解
   （懒加载，只处理看得到的，替代 5.0.33 删掉的整批预热，性能不回退）。
3. 消息页长按气泡进入多选、点气泡切换勾选、顶栏全选/取消、底栏删除；
   删除走 LanService.deleteChatMessages（内存 + 落盘一起删）。

幂等：每个 old 串出现次数 != 1 时跳过 / 报错；先全部校验再统一落盘。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, r'entry/src/main/ets/pages/Index.ets')
SVC = os.path.join(ROOT, r'entry/src/main/ets/service/LanService.ets')
APP = os.path.join(ROOT, r'AppScope/app.json5')

SENTINEL = '5.0.34：消息页也显示小缩略图（与文件页同款 48vp'

def read(p):
    return io.open(p, encoding='utf-8', newline='').read()

def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='').write(s)

def apply(p, old, new):
    s = read(p)
    # ⚠️ 幂等关键：new 已存在于文件里就直接跳过（已应用过）。
    # 这能挡住「new 本身包含 old」的嵌套重复插入（old 仍是 new 的子串，
    # 若只按 old 计数会反复命中、越插越多）——先判 new，再判 old。
    if s.count(new) >= 1:
        print(f'  [SKIP] {os.path.basename(p)} 该改动已存在')
        return False
    c = s.count(old)
    if c == 0:
        raise SystemExit(f'!! 锚点未找到（{os.path.basename(p)}）：\n{old[:80]}')
    if c > 1:
        raise SystemExit(f'!! 锚点不唯一（{os.path.basename(p)}）出现 {c} 次')
    write(p, s.replace(old, new, 1))
    print(f'  [OK]   {os.path.basename(p)} 已应用一处')
    return True

# ======================================================================
# 1) Index.ets
# ======================================================================
print('== Index.ets ==')

# 1.1 @State：消息多选状态
apply(IDX,
"""  @State fileSelected: string[] = [];
""",
"""  @State fileSelected: string[] = [];

  /** 消息页：多选态开关（长按气泡进入） */
  @State chatSelectMode: boolean = false;
  /**
   * 多选态下已勾选的消息 **id** 列表。
   * ⚠️ 同文件页：ArkUI 不观察数组元素变化，增删必须整体换引用（见 toggleChatSelect）。
   */
  @State chatSelected: string[] = [];
""")

# 1.2 chatBubble 内层 Column：多选态勾选圆
apply(IDX,
"""      Column({ space: 3 }) {
        // 发出消息（右侧气泡）显示本机名，收到消息（左侧气泡）显示对端名。
""",
"""      Column({ space: 3 }) {
        // 多选态：左上角勾选圆（与文件页一致）
        if (this.chatSelectMode) {
          Text(this.isChatSelected(m.id) ? '✓' : '')
            .fontSize(13)
            .fontColor(Color.White)
            .textAlign(TextAlign.Center)
            .width(22)
            .height(22)
            .borderRadius(11)
            .backgroundColor(this.isChatSelected(m.id) ? C_PRIMARY : '#00000000')
            .border({ width: this.isChatSelected(m.id) ? 0 : 1.5, color: '#C0C6CF' })
        }
        // 发出消息（右侧气泡）显示本机名，收到消息（左侧气泡）显示对端名。
""")

# 1.3 chatBubble 内层 Column 收尾：接 onClick + 长按手势
apply(IDX,
"""      }
      .alignItems(m.incoming ? HorizontalAlign.Start : HorizontalAlign.End)

      if (m.incoming) {
        Blank()
      }
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
  }
""",
"""      }
      .alignItems(m.incoming ? HorizontalAlign.Start : HorizontalAlign.End)
      .onClick(() => {
        if (Date.now() < this.clickMuteUntil) {
          return;
        }
        if (this.chatSelectMode) {
          this.toggleChatSelect(m.id);
          return;
        }
        // 普通态：文件消息点一下跳「文件」页；文本消息不导航
        if (m.kind === 'file' && m.incoming) {
          this.openFileTab();
        }
      })
      .gesture(
        LongPressGesture({ repeat: false, duration: 400 })
          .onAction(() => {
            if (this.chatSelectMode) {
              this.toggleChatSelect(m.id);
              return;
            }
            // 普通态：长按进入多选（vivi 2026-10-01：消息页长按气泡多选删除）
            this.clickMuteUntil = Date.now() + 800;
            this.enterChatSelect(m.id);
          })
      )

      if (m.incoming) {
        Blank()
      }
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
  }
""")

# 1.4 chatFileBubble：改成纯展示（缩略图 + 文件名 + 提示），点击/长按交给外层
apply(IDX,
"""  /**
   * 「文件」消息的气泡本体。
   *
   * ⚠️ 单独抽成一个 @Builder 而不是在 `chatBubble` 里就地写：
   *    `@Builder` 内**不声明局部变量**最省心，把 `mediaPath` 当参数传进来，
   *    `chatBubble` 那边就只剩一行。
   *
   * 收到的**图片 / 视频**：先给 128×128 缩略图（图片靠 `sourceSize` 压解码尺寸、
   * 视频靠 `AVImageGenerator` 解首帧，理由见文件页那段注释），
   * 点一下打开（图片 = 缩放预览 / 视频 = 播放器）、长按存相册。
   * **其它类型**才「点一下跳「文件」页」；自己发出的不跳（原文件还在用户手上）。
   */
  @Builder
  chatFileBubble(m: ChatMessage, mediaPath: string) {
    Column({ space: 2 }) {
      Text(m.incoming ? '收到文件' : '已发送文件')
        .fontSize(11)
        .fontColor(m.incoming ? C_SUB : '#DCE8FF')
      // 5.0.32：消息页不再内嵌缩略图（性能 + 避免变形），文件名 + 提示即可；
      // 点一下跳「文件」页，那里图片/视频是缩略图宫格、其它文件一行一个。
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
        Text(this.bubbleHintOf(m, mediaPath))
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
      // 长按过的这一小段时间里把 click 吃掉，防「存相册」连带跳页
      if (Date.now() < this.clickMuteUntil) {
        return;
      }
      // 5.0.32：消息页只显示文件名、点击跳「文件」页，那里体验更顺
      if (m.incoming) {
        this.openFileTab();
      }
    })
    // 长按存相册。⚠️ 只对**收到的图片**有意义：自己发出去的图不在沙箱里，
    // 原图本来就在用户手上，再存一份是多余动作。
    // ⚠️ 必须走 `.gesture(LongPressGesture)` —— 这个 SDK 的 ArkUI **没有**
    //    `onLongPress` 这个 CommonMethod 属性，写 `.onLongPress()` 直接
    //    编译报 `10505001 ... does not exist on type 'ColumnAttribute'`。
    //    文件页的「长按进多选」本来就是这么写的，本轮抄漏了形态。
    .gesture(
      LongPressGesture({ repeat: false, duration: 400 })
        .onAction(() => {
          if (this.mediaCountOf(m.id) > 0) {
            this.clickMuteUntil = Date.now() + 800;
            this.saveImageToAlbum(this.mediaPathAt(m.id, 0),
              Index.baseName(this.mediaPathAt(m.id, 0)));
            return;
          }
          if (mediaPath.length === 0) {
            return;
          }
          this.clickMuteUntil = Date.now() + 800;
          this.saveImageToAlbum(mediaPath, m.content);
        })
    )
  }
""",
"""  /**
   * 「文件」消息的气泡本体（**纯展示**：缩略图 + 文件名 + 提示）。
   *
   * ⚠️ 单独抽成一个 @Builder 而不是在 `chatBubble` 里就地写：
   *    `@Builder` 内**不声明局部变量**最省心，把 `mediaPath` 当参数传进来，
   *    `chatBubble` 那边就只剩一行。
   *
   * 5.0.34：消息页也显示小缩略图（与文件页同款 48vp、保持原比例）；
   * 点一下 / 长按的处理统一交给外层 `chatBubble`（普通态跳文件页、多选态切换勾选），
   * 这里不再挂自己的 onClick / gesture，避免和外层重复触发。
   */
  @Builder
  chatFileBubble(m: ChatMessage, mediaPath: string) {
    Column({ space: 4 }) {
      Text(m.incoming ? '收到文件' : '已发送文件')
        .fontSize(11)
        .fontColor(m.incoming ? C_SUB : '#DCE8FF')
      // 5.0.34：收到的图片 / 视频给一个小缩略图（48vp、按原比例），文件名 + 提示保留
      if (mediaPath.length > 0 && this.isMediaName(m.content)) {
        this.mediaThumb(mediaPath, 48)
      }
      Text(m.content)
        .fontSize(15)
        .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
        .maxLines(2)
        .wordBreak(WordBreak.BREAK_ALL)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      if (m.incoming && !this.chatSelectMode) {
        // 只有「收到的」才给入口：收到的文件落在沙箱里，
        // 系统「文件管理」看不到，不指路用户就找不到。
        // 自己发出去的原文件还在用户自己手上，不需要跳。
        Text(this.bubbleHintOf(m, mediaPath))
          .fontSize(10)
          .fontColor(C_PRIMARY)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .constraintSize({ maxWidth: '78%' })
    .padding({ left: 12, right: 12, top: 8, bottom: 8 })
    .backgroundColor(m.incoming ? C_CARD : C_PRIMARY)
    .borderRadius(10)
  }
""")

# 1.5 mediaThumb：渲染时按需触发比例测量 / 首帧解（懒加载）
apply(IDX,
"""  @Builder
  mediaThumb(path: string, maxSide: number) {
    Stack() {
      // 占位（也是解码失败 / 还没解出来的样子），真图载入后盖住它
""",
"""  @Builder
  mediaThumb(path: string, maxSide: number) {
    // 5.0.34：渲染时**按需**触发比例测量 / 首帧解（懒加载，只处理看得到的）。
    // ⚠️ 之前在 refreshReceived 里整批预热，文件一多主线程卡（vivi 实测）；
    //    这里触发后由 busy 表 + Map 去重，重绘不会重复提交解码。
    if (path.length > 0) {
      if (this.isVideoName(path)) {
        this.ensureVideoThumb(path);
      } else {
        this.ensureMediaRatio(path);
      }
    }
    Stack() {
      // 占位（也是解码失败 / 还没解出来的样子），真图载入后盖住它
""")

# 1.6 新增消息多选方法（插在文件多选段之后、clearChatHistory 之前）
apply(IDX,
"""    this.exitFileSelect();
    this.refreshReceived();
  }

  /**
   * 清空聊天记录。
""",
"""    this.exitFileSelect();
    this.refreshReceived();
  }

  // ------------------------------------------------------------------
  // 消息页：长按多选删除
  // ------------------------------------------------------------------

  /** 进入消息多选并选中给定消息（长按气泡触发） */
  private enterChatSelect(id: string): void {
    if (!this.chatSelectMode) {
      this.chatSelectMode = true;
      this.chatSelected = [id];
      return;
    }
    this.toggleChatSelect(id);
  }

  /** 切换一条消息的勾选态；取消最后一个勾选时自动退出多选 */
  private toggleChatSelect(id: string): void {
    const out: string[] = [];
    let removed: boolean = false;
    for (let i = 0; i < this.chatSelected.length; i++) {
      if (this.chatSelected[i] === id) {
        removed = true;
      } else {
        out.push(this.chatSelected[i]);
      }
    }
    if (!removed) {
      out.push(id);
    }
    // ⚠️ 必须整体换引用：ArkUI 不会因为数组 push/splice 就重渲染
    this.chatSelected = out;
    if (out.length === 0) {
      this.chatSelectMode = false;
    }
  }

  /** 全选 / 取消全选（再点一次） */
  private toggleSelectAllChat(): void {
    if (this.chat.length === 0) {
      return;
    }
    if (this.chatSelected.length === this.chat.length) {
      this.exitChatSelect();
      return;
    }
    const out: string[] = [];
    for (let i = 0; i < this.chat.length; i++) {
      out.push(this.chat[i].id);
    }
    this.chatSelected = out;
  }

  /** 退出消息多选并清空勾选 */
  private exitChatSelect(): void {
    this.chatSelectMode = false;
    this.chatSelected = [];
  }

  /** 勾选态里是否包含某消息 id */
  private isChatSelected(id: string): boolean {
    return this.chatSelected.indexOf(id) >= 0;
  }

  /** 多选批量删除消息：一次确认、逐个从聊天记录移除并落盘 */
  private async batchDeleteChat(): Promise<void> {
    const ids: string[] = this.chatSelected.slice();
    if (ids.length === 0) {
      this.toast('请先选择要删除的消息');
      return;
    }
    const ok: boolean = await this.confirmDialog(
      '删除选中的消息', '删除后无法恢复', '删除', `共 ${ids.length} 条消息`);
    if (!ok) {
      return;
    }
    this.service.deleteChatMessages(ids);
    this.exitChatSelect();
  }

  /**
   * 清空聊天记录。
""")

# 1.7 消息多选顶栏（在「复制/清空」行之后、消息列表之前）
apply(IDX,
"""      .width('100%')
      .padding({ left: 16, right: 16 })
      .alignItems(VerticalAlign.Center)

      // ---------------- 消息列表 ----------------
      if (this.chat.length === 0) {
""",
"""      .width('100%')
      .padding({ left: 16, right: 16 })
      .alignItems(VerticalAlign.Center)

      // ---------------- 消息多选态顶栏 ----------------
      if (this.chatSelectMode) {
        Row({ space: 10 }) {
          Button('取消')
            .fontSize(13)
            .height(34)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#F2F2F2')
            .fontColor('#666666')
            .onClick(() => this.exitChatSelect())
          Text(`已选 ${this.chatSelected.length} 项`)
            .fontSize(13)
            .fontColor(C_SUB)
            .layoutWeight(1)
          Button(this.chat.length > 0 && this.chatSelected.length === this.chat.length ? '取消全选' : '全选')
            .fontSize(13)
            .height(34)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#EAF0FF')
            .fontColor(C_PRIMARY)
            .enabled(this.chat.length > 0)
            .onClick(() => this.toggleSelectAllChat())
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: 4, bottom: 8 })
      }

      // ---------------- 消息列表 ----------------
      if (this.chat.length === 0) {
""")

# 1.8 消息多选底栏（删除）+ 普通态才显示输入区
apply(IDX,
"""      // ---------------- 输入区（文本 + 加号菜单 + 发送） ----------------
      Row({ space: 8 }) {
""",
"""      // ---------------- 消息多选态底部删除条 ----------------
      if (this.chatSelectMode) {
        Row({ space: 10 }) {
          Button(this.chatSelected.length > 0 ? `删除 (${this.chatSelected.length})` : '删除')
            .fontSize(14)
            .height(38)
            .width('100%')
            .backgroundColor(this.chatSelected.length > 0 ? '#FDECEA' : '#F2F2F2')
            .fontColor(this.chatSelected.length > 0 ? '#E84026' : '#AAAAAA')
            .enabled(this.chatSelected.length > 0)
            .onClick(() => this.batchDeleteChat())
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: 8, bottom: 12 })
      } else {
      // ---------------- 输入区（文本 + 加号菜单 + 发送） ----------------
      Row({ space: 8 }) {
""")

apply(IDX,
"""      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .height('100%')
  }
""",
"""      .alignItems(VerticalAlign.Center)
      }
    }
    .width('100%')
    .height('100%')
  }
""")

# ======================================================================
# 2) LanService.ets
# ======================================================================
print('== LanService.ets ==')

apply(SVC,
"""  clearChat(): void {
    this.chatRing = [];
    this.emit();
    this.saveChatAsync().catch((e: Error) => {
      Log.w(TAG, `清空聊天记录落盘异常: ${e.message}`);
    });
  }
""",
"""  clearChat(): void {
    this.chatRing = [];
    this.emit();
    this.saveChatAsync().catch((e: Error) => {
      Log.w(TAG, `清空聊天记录落盘异常: ${e.message}`);
    });
  }

  /**
   * 删除指定 id 的聊天记录（内存 + 本地持久化一起删）。
   *
   * 与 clearChat 同理：只改内存不落盘，删完下次启动还会回来。
   */
  deleteChatMessages(ids: string[]): void {
    if (ids.length === 0) {
      return;
    }
    const drop: Set<string> = new Set<string>(ids);
    const kept: ChatMessage[] = [];
    for (let i = 0; i < this.chatRing.length; i++) {
      if (!drop.has(this.chatRing[i].id)) {
        kept.push(this.chatRing[i]);
      }
    }
    if (kept.length === this.chatRing.length) {
      return;
    }
    this.chatRing = kept;
    this.emit();
    this.saveChatAsync().catch((e: Error) => {
      Log.w(TAG, `删除聊天记录落盘异常: ${e.message}`);
    });
  }
""")

# ======================================================================
# 3) app.json5
# ======================================================================
print('== app.json5 ==')

apply(APP,
"""    "versionCode": 5000033,
    "versionName": "5.0.33",
""",
"""    "versionCode": 5000034,
    "versionName": "5.0.34",
""")

# 收尾幂等哨兵校验
s = read(IDX)
assert SENTINEL in s, '收尾校验失败：5.0.34 特征串未出现'
print('\n全部改动已应用，5.0.34 特征串校验通过。')
