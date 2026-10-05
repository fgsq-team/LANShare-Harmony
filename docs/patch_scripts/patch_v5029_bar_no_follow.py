# -*- coding: utf-8 -*-
"""
5.0.29 —— 底栏不跟随键盘上移（vivi 2026-10-01 需求）

5.0.28 用的是 KeyboardAvoidMode.RESIZE：顶部确实固定了，但 RESIZE 压缩的是
**整个页面高度**，于是底部 tab 栏跟着被挤到键盘上方 —— vivi 要的是「底栏留在
屏幕底部不动」(被键盘盖住即可)。

三者语义（SDK @ohos.arkui.UIContext.d.ts:4826）：
    OFFSET = 0  整页上移（默认，顶栏被顶走）
    RESIZE = 1  压缩页面高度（顶栏固定，但底栏被挤到键盘上方）
    NONE   = 2  完全不避让（页面高度不变 → 顶栏固定、底栏保持屏幕底部，被键盘遮住）

所以改 NONE，然后**自己给内容区让位**：每个 TabContent 加
`.padding({ bottom: this.keyboardVp })` —— 内容区（含输入框）上移到键盘上方，
而 tab 栏是 Tabs 的 bar、不受 TabContent 的 padding 影响，稳稳留在屏幕底部。

铁律：哨兵幂等 + 全量校验通过后才统一落盘。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IDX = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = "setKeyboardAvoidMode(KeyboardAvoidMode.NONE)"


def read(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        s = f.read()
    return s.replace('\r\n', '\n'), ('\r\n' if '\r\n' in s else '\n')


_doc = {}
_eol = {}
_orig = {}


def load(p):
    s, eol = read(p)
    _doc[p] = s
    _eol[p] = eol
    _orig[p] = s


def edit(p, old, new, expect=None, count=1):
    cur = _doc[p]
    n = cur.count(old)
    assert n == count, "锚点出现 %d 次（期望 %d）：%r" % (n, count, old[:70])
    if expect is not None:
        assert expect in old, "expect 关键字不在锚点里：%r" % expect
    _doc[p] = cur.replace(old, new)


def write_all():
    for p in _doc:
        if _doc[p] == _orig[p]:
            print("SKIP(未变) %s" % os.path.basename(p))
            continue
        with io.open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(_doc[p].replace('\n', _eol[p]))
        print("WROTE %s" % os.path.basename(p))


def main():
    load(IDX)
    load(APP)

    if SENTINEL in _doc[IDX]:
        print("ALREADY APPLIED")
        sys.exit(0)

    # ---------- 1. 避让模式 RESIZE -> NONE ----------
    edit(IDX,
         "    // ⚠️ 键盘避让默认是 KeyboardAvoidMode.OFFSET（=0，语义：整页上移），\n"
         "    //    本页是 Stack{ 标题栏 / Tabs / 底条 } + 顶部浮层，一上移顶栏和\n"
         "    //    传输进度浮层就一起被顶出屏幕（vivi 2026-10-01 真机反馈）。\n"
         "    //    改 RESIZE：只压缩页面可用高度，顶部位置纹丝不动。\n"
         "    try {\n"
         "      this.getUIContext().setKeyboardAvoidMode(KeyboardAvoidMode.RESIZE);\n"
         "    } catch (e) {\n"
         "      Log.w(TAG, `设置键盘避让模式失败: ${JSON.stringify(e)}`);\n"
         "    }\n",
         "    // ⚠️ 键盘避让模式（SDK UIContext.d.ts:4826 定义了三种）：\n"
         "    //     OFFSET=0 整页上移（默认）→ 顶栏和进度浮层被顶出屏幕；\n"
         "    //     RESIZE=1 压缩页面高度 → 顶栏固定，但**底栏被挤到键盘上方**；\n"
         "    //     NONE  =2 完全不避让  → 页面高度不变：顶栏固定、**底栏留在屏幕底部**。\n"
         "    //   vivi 要的是「顶栏不动 + 底栏也不跟着上移」⇒ 只能取 NONE，\n"
         "    //   再自己给 TabContent 加键盘高度的 bottom padding 让输入框上移\n"
         "    //   （tab 栏是 Tabs 的 bar，不吃 TabContent 的 padding，所以原地不动）。\n"
         "    try {\n"
         "      this.getUIContext().setKeyboardAvoidMode(KeyboardAvoidMode.NONE);\n"
         "    } catch (e) {\n"
         "      Log.w(TAG, `设置键盘避让模式失败: ${JSON.stringify(e)}`);\n"
         "    }\n",
         expect="KeyboardAvoidMode.RESIZE")

    # ---------- 2. 状态：布尔 -> 高度值 ----------
    edit(IDX,
         "  /** 软键盘是否弹起：弹起时收掉底部安全条（见 build() 底部那一条） */\n"
         "  @State keyboardUp: boolean = false;\n",
         "  /** 软键盘当前高度（vp，未弹起为 0）：内容区按它让位，底栏不动（见 build()） */\n"
         "  @State keyboardVp: number = 0;\n",
         expect="@State keyboardUp")

    # ---------- 3. 回调：记高度 + 键盘刚弹起时把聊天拉到底 ----------
    edit(IDX,
         "  /**\n"
         "   * 软键盘高度变化回调（px）。\n"
         "   *\n"
         "   * 只用它维护一个布尔量，不拿来做精确定位 —— 各机型/输入法报的\n"
         "   * 高度不一致，用它算偏移反而容易错；RESIZE 模式已经把布局压好了，\n"
         "   * 这里只需要知道「键盘在不在」。\n"
         "   */\n"
         "  private onKeyboardHeight(px: number): void {\n"
         "    const up: boolean = px > 0;\n"
         "    if (up !== this.keyboardUp) {\n"
         "      this.keyboardUp = up;\n"
         "    }\n"
         "  }\n",
         "  /**\n"
         "   * 软键盘高度变化回调（px）。\n"
         "   *\n"
         "   * ⚠️ 避让模式是 NONE，系统不会替我们做任何让位 —— 这个高度就是\n"
         "   *    内容区底部 padding 的唯一来源（`TabContent.padding(bottom)`）。\n"
         "   *    换算成 vp 再存（px2vp 走 UIContext，全局 px2vp() 已废弃）。\n"
         "   */\n"
         "  private onKeyboardHeight(px: number): void {\n"
         "    const vp: number = px > 0 ? this.getUIContext().px2vp(px) : 0;\n"
         "    const wasUp: boolean = this.keyboardVp > 0;\n"
         "    this.keyboardVp = vp;\n"
         "    // 键盘刚弹起、且正停在消息页：把聊天列表拉到底（跟主流聊天软件一致）。\n"
         "    // 延后一帧执行：此刻 padding 还没生效，立刻滚会停在旧的可视区底部。\n"
         "    if (vp > 0 && !wasUp && this.curTab === 1) {\n"
         "      setTimeout(() => {\n"
         "        try {\n"
         "          this.chatScroller.scrollEdge(Edge.Bottom);\n"
         "        } catch (e) {\n"
         "          // 列表还没挂载，忽略\n"
         "        }\n"
         "      }, 120);\n"
         "    }\n"
         "  }\n",
         expect="private onKeyboardHeight(px: number): void")

    # ---------- 4. 底部安全条恢复固定高度（NONE 下它被键盘盖住，无需再收） ----------
    edit(IDX,
         "        Row()\n"
         "          .width('100%')\n"
         "          // 键盘弹起时收成 0：RESIZE 下这一条会正好悬在键盘上方，\n"
         "          // 留出一段同色空档；键盘本来就该紧贴 tab 栏。\n"
         "          .height(this.keyboardUp ? 0 : this.bottomInset)\n"
         "          .backgroundColor(C_CARD)\n",
         "        Row()\n"
         "          .width('100%')\n"
         "          .height(this.bottomInset)\n"
         "          .backgroundColor(C_CARD)\n",
         expect="keyboardUp ? 0 : this.bottomInset")

    # ---------- 5. 三个 TabContent 内容区按键盘高度让位 ----------
    for name, label, idx_no in (('shareTab', '共享', 0), ('chatTab', '消息', 1), ('filesTab', '文件', 2)):
        edit(IDX,
             "          TabContent() {\n"
             "            this.%s()\n"
             "          }\n"
             "          .tabBar(this.tabBarItem('%s', %d))\n" % (name, label, idx_no),
             "          TabContent() {\n"
             "            this.%s()\n"
             "          }\n"
             "          // 键盘弹起：内容区底部让出键盘高度，输入框正好落在键盘上沿。\n"
             "          // ⚠️ 只加在 TabContent 上 —— tab 栏是 Tabs 的 bar，不吃这个 padding，\n"
             "          //    于是底栏留在屏幕底部不动（vivi 要求：不跟随键盘上移）。\n"
             "          .padding({ bottom: this.keyboardVp })\n"
             "          .tabBar(this.tabBarItem('%s', %d))\n" % (name, label, idx_no),
             expect="this.%s()" % name)

    # ---------- 6. 版本号 5.0.28 -> 5.0.29 ----------
    edit(APP, '"versionCode": 5000028', '"versionCode": 5000029', expect="5000028")
    edit(APP, '"versionName": "5.0.28"', '"versionName": "5.0.29"', expect="5.0.28")

    # ---------- 落盘前统一校验 ----------
    idx = _doc[IDX]
    app = _doc[APP]

    assert SENTINEL in idx, "落盘前 NONE 缺失"
    assert "KeyboardAvoidMode.RESIZE" not in idx, "仍残留 RESIZE"
    assert idx.count("@State keyboardVp: number = 0;") == 1, "keyboardVp 状态异常"
    assert idx.count("keyboardUp") == 0, "仍有 keyboardUp 残留"
    assert idx.count(".padding({ bottom: this.keyboardVp })") == 3, "TabContent padding 数量异常"
    assert idx.count(".height(this.bottomInset)") == 1, "底条写法异常"
    assert idx.count("private onKeyboardHeight(px: number): void") == 1, "回调定义异常"
    assert idx.count("win.on('keyboardHeightChange'") == 1, "监听丢失"
    assert idx.count("this.getUIContext().setKeyboardAvoidMode(") == 1, "避让模式调用次数异常"
    d = idx.count('{') - idx.count('}')
    d0 = _orig[IDX].count('{') - _orig[IDX].count('}')
    assert d == d0, "花括号增量变了：%d -> %d" % (d0, d)
    assert '"versionName": "5.0.29"' in app, "版本名未改"
    assert '"versionCode": 5000029' in app, "版本码未改"

    write_all()
    print("PATCH OK -> 5.0.29")


if __name__ == '__main__':
    main()
