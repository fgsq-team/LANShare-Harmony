# -*- coding: utf-8 -*-
"""
patch_v5022_msgthumb.py
让「消息」页收到的图片/视频气泡可靠地显示缩略图。

根因：
  `recvIndex` 是普通 Map，气泡首次渲染时它可能还没建好（订阅回调可能先于
  refreshReceived 触发，或文件刚落盘），于是 `msgMediaPath` 算出空串后**再也不重算**
  —— 图片缩略图永久空白（视频靠解码完成的 videoThumbTick 触发了重绘，所以只有图片中招）。
  文件页用 `f.path` 每次列表刷新换引用，故不受影响。

修复：
  另立一张 @State 的 `chatMediaPaths`（每条消息 id -> 其媒体沙箱路径），
  recvIndex 或聊天条数一变就整体换引用重绘；气泡 key 带上本表里的路径，
  于是「路径从空变实」的那一行单独重建，其余行 key 不变、滚动位置不跳。

幂等：已应用（syncChatMediaPaths 存在且 msgMediaPath 不存在）时直接退出。
全量校验：所有 old 串必须恰好出现一次、new 串必须不存在，才会统一落盘。
"""
import io
import os
import sys

SRC = r"E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets"
APP = r"E:\lanshare-harmony\LANShareV5\AppScope\app.json5"
BAK_DIR = r"E:\lanshare-harmony\LANShareV5\.backup_v5022"

SENT_APPLIED = "syncChatMediaPaths"
SENT_GONE = "private msgMediaPath("


def read_text(p):
    with io.open(p, "r", encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def write_text(p, s):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def do_replace(s, old, new, label):
    cnt = s.count(old)
    if cnt != 1:
        raise AssertionError(f"[{label}] old 出现 {cnt} 次（期望 1）\n---OLD---\n{old}")
    if new in s:
        raise AssertionError(f"[{label}] new 已存在，可能重复应用\n---NEW---\n{new}")
    return s.replace(old, new, 1)


def main():
    # ---------------- 幂等哨兵 ----------------
    cur = read_text(SRC)
    if SENT_APPLIED in cur and SENT_GONE not in cur:
        print("ALREADY APPLIED: syncChatMediaPaths 已存在且 msgMediaPath 已移除，跳过。")
        sys.exit(0)

    # ---------------- 1) 新增 @State chatMediaPaths 字段 ----------------
    old1 = "  @State videoThumbTick: number = 0;\n"
    new1 = (
        "  @State videoThumbTick: number = 0;\n"
        "  /** 每条消息 id -> 其「收到的图片/视频」沙箱路径；空串 = 无缩略图。见 syncChatMediaPaths */\n"
        "  @State chatMediaPaths: Map<string, string> = new Map<string, string>();\n"
    )
    cur = do_replace(cur, old1, new1, "field")

    # ---------------- 2) msgMediaPath -> syncChatMediaPaths ----------------
    old2 = (
        "  /**\n"
        "   * 一条消息对应的沙箱**媒体**路径（图片或视频）；不是「收到的媒体文件」\n"
        "   * 或查不到 → 返回空串。\n"
        "   *\n"
        "   * ⚠️ 空串的语义 = 「点了跳文件页」的那一类：不显示缩略图、不播、不给长按入口。\n"
        "   *    所以「其它类型文件才跳文件页」这条需求，就落在这一句判断上。\n"
        "   */\n"
        "  private msgMediaPath(m: ChatMessage): string {\n"
        "    if (m.kind !== 'file' || !m.incoming || !this.isMediaName(m.content)) {\n"
        "      return '';\n"
        "    }\n"
        "    const hit: string | undefined = this.recvIndex.get(m.content);\n"
        "    return hit === undefined ? '' : hit;\n"
        "  }\n"
    )
    new2 = (
        "  /**\n"
        "   * 把「每条消息 -> 其媒体沙箱路径」算好存进 @State，供气泡渲染缩略图。\n"
        "   *\n"
        "   * ⚠️ 为什么另立一张表而不是在气泡里直接 `recvIndex.get`：\n"
        "   *    `recvIndex` 是普通 Map，气泡渲染它不会触发重绘；而气泡**首次**渲染时\n"
        "   *    `recvIndex` 常常还没建好（订阅回调可能先于 `refreshReceived` 跑，或文件刚落盘），\n"
        "   *    于是路径算出空串后**再也不重算** —— 图片缩略图永远空白。\n"
        "   *    （视频靠解码完成的 `videoThumbTick` 触发了重绘，所以只有图片中招。）\n"
        "   *    这里把结果写进 @State 的 Map：recvIndex 一变 / 聊天条数一变就整体换引用 →\n"
        "   *    组件重绘、气泡 key 带上本表里的路径 → 路径从空变实的那一行单独重建，\n"
        "   *    其余行 key 不变、列表滚动位置不跳。\n"
        "   */\n"
        "  private syncChatMediaPaths(): void {\n"
        "    const m: Map<string, string> = new Map<string, string>();\n"
        "    for (let i = 0; i < this.chat.length; i++) {\n"
        "      const msg: ChatMessage = this.chat[i];\n"
        "      let p: string = '';\n"
        "      if (msg.kind === 'file' && msg.incoming && this.isMediaName(msg.content)) {\n"
        "        const hit: string | undefined = this.recvIndex.get(msg.content);\n"
        "        if (hit !== undefined) {\n"
        "          p = hit;\n"
        "        }\n"
        "      }\n"
        "      m.set(msg.id, p);\n"
        "    }\n"
        "    // 内容没变就不换引用，避免无谓重绘（文件页刷新很频繁）\n"
        "    if (this.chatMediaPaths.size === m.size) {\n"
        "      let same: boolean = true;\n"
        "      for (const key of m.keys()) {\n"
        "        if (this.chatMediaPaths.get(key) !== m.get(key)) {\n"
        "          same = false;\n"
        "          break;\n"
        "        }\n"
        "      }\n"
        "      if (same) {\n"
        "        return;\n"
        "      }\n"
        "    }\n"
        "    this.chatMediaPaths = m;\n"
        "  }\n"
    )
    cur = do_replace(cur, old2, new2, "method")

    # ---------------- 3) refreshReceived 末尾触发同步 ----------------
    old3 = (
        "    this.prewarmVideoThumbs(list);\n"
        "    // 打一条汇总：真机上「列表里的 size」和「文件实际大小」对不上时，\n"
    )
    new3 = (
        "    this.prewarmVideoThumbs(list);\n"
        "    // 消息气泡缩略图依赖「文件名->沙箱路径」反查；文件一变就重算（见 syncChatMediaPaths）\n"
        "    this.syncChatMediaPaths();\n"
        "    // 打一条汇总：真机上「列表里的 size」和「文件实际大小」对不上时，\n"
    )
    cur = do_replace(cur, old3, new3, "refreshReceived")

    # ---------------- 4) onSnapshot 聊天条数变化时同步 ----------------
    old4 = (
        "      this.lastChatCount = s.chat.length;\n"
        "      this.chat = s.chat.slice();\n"
        "      if (this.curTab === 1) {\n"
    )
    new4 = (
        "      this.lastChatCount = s.chat.length;\n"
        "      this.chat = s.chat.slice();\n"
        "      // 聊天条数变了 -> 重算每条消息的媒体路径（新收到的图/视频要能立刻出缩略图）\n"
        "      this.syncChatMediaPaths();\n"
        "      if (this.curTab === 1) {\n"
    )
    cur = do_replace(cur, old4, new4, "onSnapshot")

    # ---------------- 5) chatBubble 调用改读 chatMediaPaths ----------------
    old5 = "          this.chatFileBubble(m, this.msgMediaPath(m))\n"
    new5 = "          this.chatFileBubble(m, this.chatMediaPaths.get(m.id) ?? '')\n"
    cur = do_replace(cur, old5, new5, "caller")

    # ---------------- 6) 聊天 ForEach key 带上媒体路径 ----------------
    old6 = "          }, (m: ChatMessage) => `${m.id}|${this.videoThumbTick}`)\n"
    new6 = (
        "          }, (m: ChatMessage) => "
        "`${m.id}|${this.videoThumbTick}|${this.chatMediaPaths.has(m.id) ? (this.chatMediaPaths.get(m.id) ?? '') : ''}`)\n"
    )
    cur = do_replace(cur, old6, new6, "foreach-key")

    # ---------------- 校验落盘前状态 ----------------
    assert SENT_APPLIED in cur, "落盘前 syncChatMediaPaths 缺失"
    assert SENT_GONE not in cur, "落盘前 msgMediaPath 方法仍在"
    assert cur.count("this.chatFileBubble(m, this.chatMediaPaths.get(m.id) ?? '')") == 1, "caller 替换异常"
    assert cur.count("syncChatMediaPaths(): void") == 1, "syncChatMediaPaths 定义异常"
    assert cur.count("this.syncChatMediaPaths();") == 2, "syncChatMediaPaths 调用次数异常"
    # 真正的代码引用（方法定义 / 调用）必须消失；第 123 行设计注释里的旧名是历史说明，可保留
    assert cur.count("this.msgMediaPath") == 0, "仍有 msgMediaPath 调用残留"
    assert cur.count("private msgMediaPath(") == 0, "仍有 msgMediaPath 定义残留"

    # ---------------- 统一落盘 ----------------
    os.makedirs(BAK_DIR, exist_ok=True)
    write_text(os.path.join(BAK_DIR, "Index.ets"), read_text(SRC))
    write_text(SRC, cur)
    print("[OK] Index.ets patched -> chatMediaPaths + syncChatMediaPaths")

    # ---------------- app.json5 升版本 5.0.21 -> 5.0.22 ----------------
    app = read_text(APP)
    app_o1, app_n1 = '    "versionCode": 5000021,', '    "versionCode": 5000022,'
    app_o2, app_n2 = '    "versionName": "5.0.21",', '    "versionName": "5.0.22",'
    if app_o1 in app and app_o2 in app:
        app = app.replace(app_o1, app_n1, 1).replace(app_o2, app_n2, 1)
        write_text(os.path.join(BAK_DIR, "app.json5"), read_text(APP))
        write_text(APP, app)
        print("[OK] app.json5 -> 5.0.22 (5000022)")
    else:
        print("[SKIP] app.json5 版本号已是目标值或格式不符，未改动")


if __name__ == "__main__":
    main()
