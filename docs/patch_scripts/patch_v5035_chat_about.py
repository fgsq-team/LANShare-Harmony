# -*- coding: utf-8 -*-
"""
LANShare V5 5.0.35 补丁：消息页气泡 / 多选返回 / 删除提示 / 复制 / 关于页
- 消息文件气泡改横排（左缩略图 + 右文件名，矮一点长一点）
- 多选态系统返回 => 取消多选（而不是回桌面）
- 删除提示窗说明「只删记录不删文件」
- 复制只复制消息正文（不含用户名/时间）；多选态新增「复制」按钮
- 关于页新增 QQ 群 + 更新链接
所有改动带哨兵/唯一锚点，可重跑幂等。
"""
import io
import sys

P = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'


def read(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        return f.read()


def write(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


def safe_replace(s, old, new, label, marker):
    """替换 old->new；marker 是「应用后才会出现」的唯一串，用于幂等判重。"""
    if old not in s:
        print('SKIP (old missing): ' + label)
        return s
    if s.count(old) != 1:
        print('ABORT (old not unique, count=%d): %s' % (s.count(old), label))
        sys.exit(1)
    if marker in s:
        print('SKIP (already applied): ' + label)
        return s
    print('APPLY: ' + label)
    return s.replace(old, new, 1)


def add_after(s, anchor, block, label, marker):
    """在 anchor 后插入 block；marker 用于幂等判重。"""
    if anchor not in s:
        print('SKIP (anchor missing): ' + label)
        return s
    if s.count(anchor) != 1:
        print('ABORT (anchor not unique, count=%d): %s' % (s.count(anchor), label))
        sys.exit(1)
    if marker in s:
        print('SKIP (already applied): ' + label)
        return s
    print('APPLY: ' + label)
    return s.replace(anchor, anchor + block, 1)


def main():
    s = read(P)

    # ---- 1. onBackPress：多选态返回取消多选 ----
    old1 = """    if (this.fileSelectMode) {
      this.exitFileSelect();
      return true;
    }
    if (this.showQr) {"""
    new1 = """    if (this.fileSelectMode) {
      this.exitFileSelect();
      return true;
    }
    if (this.chatSelectMode) {
      this.exitChatSelect();
      return true;
    }
    if (this.showQr) {"""
    s = safe_replace(s, old1, new1, 'onBackPress chatSelectMode',
                     'if (this.chatSelectMode) {\n      this.exitChatSelect();\n      return true;')

    # ---- 2. copyChat：只复制消息正文（不含用户名/时间）+ 新增 copySelectedChat / copyText ----
    old2 = """  private copyChat(): void {
    if (this.chat.length === 0) {
      this.toast('暂无聊天记录');
      return;
    }
    const lines: string[] = [];
    for (let i = 0; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      lines.push(`[${fmtTime(m.timeMs)}] ${m.peerName}: ${m.content}`);
    }
    try {
      const data: pasteboard.PasteData = pasteboard.createData(
        pasteboard.MIMETYPE_TEXT_PLAIN, lines.join('\\n'));
      pasteboard.getSystemPasteboard().setDataSync(data);
      this.toast(`已复制 ${lines.length} 条聊天记录`);
    } catch (e) {
      this.toast('复制失败');
    }
  }"""
    new2 = """  private copyChat(): void {
    // 5.0.35：只复制消息正文，不再带用户名和时间（vivi：只需要复制消息本身）
    if (this.chat.length === 0) {
      this.toast('暂无聊天记录');
      return;
    }
    const lines: string[] = [];
    for (let i = 0; i < this.chat.length; i++) {
      lines.push(this.chat[i].content);
    }
    try {
      const data: pasteboard.PasteData = pasteboard.createData(
        pasteboard.MIMETYPE_TEXT_PLAIN, lines.join('\\n'));
      pasteboard.getSystemPasteboard().setDataSync(data);
      this.toast(`已复制 ${lines.length} 条消息`);
    } catch (e) {
      this.toast('复制失败');
    }
  }

  /** 多选态复制：只复制选中消息的正文，不含用户名和时间 */
  private copySelectedChat(): void {
    const ids: string[] = this.chatSelected.slice();
    if (ids.length === 0) {
      this.toast('请先选择要复制的消息');
      return;
    }
    const want: Set<string> = new Set(ids);
    const lines: string[] = [];
    for (let i = 0; i < this.chat.length; i++) {
      if (want.has(this.chat[i].id)) {
        lines.push(this.chat[i].content);
      }
    }
    try {
      const data: pasteboard.PasteData = pasteboard.createData(
        pasteboard.MIMETYPE_TEXT_PLAIN, lines.join('\\n'));
      pasteboard.getSystemPasteboard().setDataSync(data);
      this.toast(`已复制 ${lines.length} 条消息`);
    } catch (e) {
      this.toast('复制失败');
    }
  }

  /** 复制任意一段文本到剪贴板（关于页的群号 / 更新地址等） */
  private copyText(t: string): void {
    try {
      const data: pasteboard.PasteData = pasteboard.createData(
        pasteboard.MIMETYPE_TEXT_PLAIN, t);
      pasteboard.getSystemPasteboard().setDataSync(data);
      this.toast('已复制');
    } catch (e) {
      this.toast('复制失败');
    }
  }"""
    s = safe_replace(s, old2, new2, 'copyChat content-only + helpers',
                     'private copySelectedChat(): void {')

    # ---- 3. batchDeleteChat：删除提示说明只删记录 ----
    old3 = """    const ok: boolean = await this.confirmDialog(
      '删除选中的消息', '删除后无法恢复', '删除', `共 ${ids.length} 条消息`);"""
    new3 = """    const ok: boolean = await this.confirmDialog(
      '删除选中的消息', '仅删除聊天记录，不会删除已接收的文件', '删除', `共 ${ids.length} 条消息`);"""
    s = safe_replace(s, old3, new3, 'batchDeleteChat note', '仅删除聊天记录，不会删除已接收的文件')

    # ---- 4. 多选态顶栏新增「复制」按钮 ----
    old4 = """          Text(`已选 ${this.chatSelected.length} 项`)
            .fontSize(13)
            .fontColor(C_SUB)
            .layoutWeight(1)
          Button(this.chat.length > 0 && this.chatSelected.length === this.chat.length ? '取消全选' : '全选')"""
    new4 = """          Text(`已选 ${this.chatSelected.length} 项`)
            .fontSize(13)
            .fontColor(C_SUB)
            .layoutWeight(1)
          Button('复制')
            .fontSize(13)
            .height(34)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#EAF0FF')
            .fontColor(C_PRIMARY)
            .enabled(this.chatSelected.length > 0)
            .onClick(() => this.copySelectedChat())
          Button(this.chat.length > 0 && this.chatSelected.length === this.chat.length ? '取消全选' : '全选')"""
    s = safe_replace(s, old4, new4, 'chat select bar 复制 button', '() => this.copySelectedChat()')

    # ---- 5. 文本气泡略减纵向内边距（矮一点） ----
    old5 = """          Text(m.content)
            .fontSize(15)
            .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
            .padding({ left: 12, right: 12, top: 8, bottom: 8 })
            .backgroundColor(m.incoming ? C_CARD : C_PRIMARY)
            .borderRadius(10)
            .textAlign(TextAlign.Start)"""
    new5 = """          Text(m.content)
            .fontSize(15)
            .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
            .padding({ left: 12, right: 12, top: 6, bottom: 6 })
            .backgroundColor(m.incoming ? C_CARD : C_PRIMARY)
            .borderRadius(10)
            .textAlign(TextAlign.Start)"""
    s = safe_replace(s, old5, new5, 'text bubble slimmer padding', 'top: 6, bottom: 6')

    # ---- 6. chatFileBubble：横排（左缩略图 + 右文件名），矮一点长一点 ----
    old6 = """  @Builder
  chatFileBubble(m: ChatMessage, mediaPath: string) {
    Column({ space: 4 }) {
      Text(m.incoming ? '收到文件' : '已发送文件')
        .fontSize(11)
        .fontColor(m.incoming ? C_SUB : '#DCE8FF')
      // 5.0.34：收到的图片 / 视频给一个小缩略图（48vp、按原比例），文件名 + 提示保留
      // ⚠️ 判断用 mediaPath（首张媒体路径）而非 m.content：一批图时 m.content 是「N 个文件」，
      //    按 content 判会漏掉缩略图；按路径（带扩展名）判两种都覆盖。
      if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
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
  }"""
    new6 = """  @Builder
  chatFileBubble(m: ChatMessage, mediaPath: string) {
    // 5.0.35：改横排「左缩略图 + 右文件名」（像文件页那样，但不用那么长），整体更矮。
    Row({ space: 8 }) {
      if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
        this.mediaThumb(mediaPath, 48)
      }
      Column({ space: 2 }) {
        Text(m.incoming ? '收到文件' : '已发送文件')
          .fontSize(11)
          .fontColor(m.incoming ? C_SUB : '#DCE8FF')
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
      .layoutWeight(1)
      .alignItems(HorizontalAlign.Start)
    }
    .alignItems(VerticalAlign.Center)
    .constraintSize({ maxWidth: '88%' })
    .padding({ left: 10, right: 10, top: 6, bottom: 6 })
    .backgroundColor(m.incoming ? C_CARD : C_PRIMARY)
    .borderRadius(10)
  }"""
    s = safe_replace(s, old6, new6, 'chatFileBubble horizontal', '改横排「左缩略图')

    # ---- 7. ABOUT_UPDATE 常量（接在 ABOUT_REPO 后） ----
    anchor7 = "const ABOUT_REPO: string = 'https://github.com/fgsq-team/LANShare';"
    block7 = "\nconst ABOUT_UPDATE: string = 'https://pan.quark.cn/s/04d4a2a1a13a';"
    s = add_after(s, anchor7, block7, 'ABOUT_UPDATE const', 'ABOUT_UPDATE: string')

    # ---- 8. 关于弹窗：QQ 群 + 更新地址 ----
    anchor8 = """          .width('100%')
          .padding(10)
          .backgroundColor('#F6F8FB')
          .borderRadius(10)
        }
        .width('86%')"""
    block8 = """

          // ---------------- QQ 交流群 ----------------
          Column({ space: 6 }) {
            Text('QQ 交流群')
              .fontSize(11)
              .fontColor(C_SUB)
              .width('100%')
            Row({ space: 8 }) {
              Text('538809905')
                .fontSize(13)
                .fontColor(C_TEXT)
                .layoutWeight(1)
              Text('复制')
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .onClick(() => {
                  this.copyText('538809905');
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }
          .width('100%')
          .padding(10)
          .backgroundColor('#F6F8FB')
          .borderRadius(10)

          // ---------------- 更新地址 ----------------
          Column({ space: 6 }) {
            Text('更新地址')
              .fontSize(11)
              .fontColor(C_SUB)
              .width('100%')
            Row({ space: 8 }) {
              Text(ABOUT_UPDATE)
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .layoutWeight(1)
                .maxLines(2)
                .wordBreak(WordBreak.BREAK_ALL)
              Text('复制')
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .onClick(() => {
                  this.copyText(ABOUT_UPDATE);
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }
          .width('100%')
          .padding(10)
          .backgroundColor('#F6F8FB')
          .borderRadius(10)"""
    s = add_after(s, anchor8, block8, 'about QQ group + update link', 'QQ 交流群')

    write(P, s)
    print('DONE -> ' + P)


if __name__ == '__main__':
    main()
