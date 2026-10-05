# -*- coding: utf-8 -*-
"""
5.0.28 —— 键盘弹起时顶部固定（标题栏 + 传输进度浮层不再被顶走）

问题（vivi 2026-10-01 真机反馈）：
    消息页点输入框，软键盘弹起后标题栏和传输进度浮层一起跑出屏幕上沿。

根因（查 SDK 类型定义坐实，非推测）：
    @ohos.arkui.UIContext.d.ts:4826 —— setKeyboardAvoidMode 的默认值是
    **KeyboardAvoidMode.OFFSET = 0**，语义是「页面整体上移」。
    本页是 Stack{ Column{ 标题栏 / Tabs / 底条 } + 浮层 }，整页一上移，
    标题栏和用 margin(top) 定位的进度浮层就一起被顶出去了。

修法：
    改为 KeyboardAvoidMode.RESIZE（=1）—— 只压缩页面可用高度，
    顶部位置不变。同时监听键盘高度，弹起时把底部安全条收成 0，
    免得它悬在键盘上方留一条同色空档。

铁律：哨兵幂等 + 全量校验通过后才统一落盘。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IDX = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = "KeyboardAvoidMode.RESIZE"


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
    """在内存里替换；old 必须恰好出现 count 次。"""
    cur = _doc[p]
    n = cur.count(old)
    assert n == count, "锚点出现 %d 次（期望 %d）：%r" % (n, count, old[:60])
    if expect is not None:
        assert expect in old, "expect 关键字不在锚点里：%r" % expect
    _doc[p] = cur.replace(old, new)
    return True


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

    # ---------- 1. import：加 KeyboardAvoidMode ----------
    edit(IDX,
         "import { window } from '@kit.ArkUI';",
         "import { window, KeyboardAvoidMode } from '@kit.ArkUI';",
         expect="@kit.ArkUI")

    # ---------- 2. 新增状态：键盘是否弹起 + 主窗口引用 ----------
    edit(IDX,
         "  /** 底部导航条高度（vp） */\n"
         "  @State bottomInset: number = 0;\n",
         "  /** 底部导航条高度（vp） */\n"
         "  @State bottomInset: number = 0;\n"
         "  /** 软键盘是否弹起：弹起时收掉底部安全条（见 build() 底部那一条） */\n"
         "  @State keyboardUp: boolean = false;\n"
         "  /** 主窗口引用：键盘高度监听要在 aboutToDisappear 里摘掉，否则回调悬空 */\n"
         "  private mainWin: window.Window | null = null;\n",
         expect="@State bottomInset")

    # ---------- 3. aboutToAppear：切换避让模式 ----------
    edit(IDX,
         "  aboutToAppear(): void {\n"
         "    this.loadVersion();\n",
         "  aboutToAppear(): void {\n"
         "    // ⚠️ 键盘避让默认是 KeyboardAvoidMode.OFFSET（=0，语义：整页上移），\n"
         "    //    本页是 Stack{ 标题栏 / Tabs / 底条 } + 顶部浮层，一上移顶栏和\n"
         "    //    传输进度浮层就一起被顶出屏幕（vivi 2026-10-01 真机反馈）。\n"
         "    //    改 RESIZE：只压缩页面可用高度，顶部位置纹丝不动。\n"
         "    try {\n"
         "      this.getUIContext().setKeyboardAvoidMode(KeyboardAvoidMode.RESIZE);\n"
         "    } catch (e) {\n"
         "      Log.w(TAG, `设置键盘避让模式失败: ${JSON.stringify(e)}`);\n"
         "    }\n"
         "    this.loadVersion();\n",
         expect="aboutToAppear(): void")

    # ---------- 4. applyWindowInset：挂键盘高度监听 ----------
    edit(IDX,
         "      const win: window.Window = await window.getLastWindow(ctx);\n"
         "      const sys: window.AvoidArea = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);\n",
         "      const win: window.Window = await window.getLastWindow(ctx);\n"
         "      this.mainWin = win;\n"
         "      // 键盘高度变化时联动：弹起 → 收掉底部安全条（它悬在键盘上方会留一条空档）\n"
         "      win.on('keyboardHeightChange', (h: number) => {\n"
         "        this.onKeyboardHeight(h);\n"
         "      });\n"
         "      const sys: window.AvoidArea = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);\n",
         expect="getLastWindow(ctx)")

    # ---------- 5. 新增回调方法（放在 applyWindowInset 之后） ----------
    edit(IDX,
         "  /** 未启动服务时也展示一下本机地址，降低\"不知道填什么\"的困惑 */\n",
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
         "  }\n"
         "\n"
         "  /** 未启动服务时也展示一下本机地址，降低\"不知道填什么\"的困惑 */\n",
         expect="未启动服务时也展示一下本机地址")

    # ---------- 6. aboutToDisappear：摘掉监听 ----------
    edit(IDX,
         "  aboutToDisappear(): void {\n"
         "    this.service.unsubscribe(this.onSnapshot);\n"
         "  }\n",
         "  aboutToDisappear(): void {\n"
         "    this.service.unsubscribe(this.onSnapshot);\n"
         "    try {\n"
         "      this.mainWin?.off('keyboardHeightChange');\n"
         "    } catch (e) {\n"
         "      // 窗口已销毁，忽略\n"
         "    }\n"
         "  }\n",
         expect="aboutToDisappear(): void")

    # ---------- 7. 底部安全条：键盘弹起时收掉 ----------
    edit(IDX,
         "        Row()\n"
         "          .width('100%')\n"
         "          .height(this.bottomInset)\n"
         "          .backgroundColor(C_CARD)\n",
         "        Row()\n"
         "          .width('100%')\n"
         "          // 键盘弹起时收成 0：RESIZE 下这一条会正好悬在键盘上方，\n"
         "          // 留出一段同色空档；键盘本来就该紧贴 tab 栏。\n"
         "          .height(this.keyboardUp ? 0 : this.bottomInset)\n"
         "          .backgroundColor(C_CARD)\n",
         expect="height(this.bottomInset)")

    # ---------- 8. 版本号 5.0.27 -> 5.0.28 ----------
    edit(APP, '"versionCode": 5000027', '"versionCode": 5000028', expect="5000027")
    edit(APP, '"versionName": "5.0.27"', '"versionName": "5.0.28"', expect="5.0.27")

    # ---------- 落盘前统一校验 ----------
    idx = _doc[IDX]
    app = _doc[APP]

    assert SENTINEL in idx, "落盘前 RESIZE 缺失"
    assert "KeyboardAvoidMode } from '@kit.ArkUI'" in idx, "import 未加"
    assert idx.count("@State keyboardUp: boolean = false;") == 1, "keyboardUp 状态异常"
    assert idx.count("private mainWin: window.Window | null = null;") == 1, "mainWin 成员异常"
    assert idx.count("private onKeyboardHeight(px: number): void {") == 1, "onKeyboardHeight 定义异常"
    assert idx.count("win.on('keyboardHeightChange'") == 1, "监听未挂"
    assert idx.count("this.mainWin?.off('keyboardHeightChange');") == 1, "off 未摘"
    assert idx.count(".height(this.keyboardUp ? 0 : this.bottomInset)") == 1, "底条未改"
    assert ".height(this.bottomInset)" not in idx, "仍有旧底条写法残留"
    assert idx.count("this.getUIContext().setKeyboardAvoidMode(") == 1, "RESIZE 调用次数异常"
    # 括号增量一致（防整段被吞）
    d = idx.count('{') - idx.count('}')
    d0 = _orig[IDX].count('{') - _orig[IDX].count('}')
    assert d == d0, "花括号增量变了：%d -> %d" % (d0, d)
    assert '"versionName": "5.0.28"' in app, "版本名未改"
    assert '"versionCode": 5000028' in app, "版本码未改"

    write_all()
    print("PATCH OK -> 5.0.28")


if __name__ == '__main__':
    main()
