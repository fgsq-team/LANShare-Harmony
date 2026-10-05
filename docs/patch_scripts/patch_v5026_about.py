# -*- coding: utf-8 -*-
"""
5.0.26 —— 新增「关于」入口

vivi 诉求：加一个「关于」，点击显示 **版本号** 和 梦醒了 大佬的开源仓库
https://github.com/fgsq-team/LANShare ，并说明本应用是基于其开源代码移植的鸿蒙版。

落法（沿用本页既有自绘弹窗风格，与 pickDialog / qrDialog 一致）：
  1. import：AbilityKit 增加 `bundleManager`（运行时取版本号）
  2. 常量：`ABOUT_REPO`（仓库地址）、`ABOUT_FALLBACK_VER`（取不到版本时的兜底）
  3. @State：`showAbout`（弹窗开关）、`aboutVer`（版本号）
  4. `aboutToAppear()` 里 `loadVersion()`
  5. 方法：`loadVersion()`（bundleManager 取版本，失败兜底）、`copyRepo()`（复制仓库地址）
  6. @Builder `aboutDialog()`；标题栏加「关于」按钮；build() 里挂上弹窗

铁律：哨兵幂等 + 全量校验 + 最后统一落盘。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IDX = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '@Builder\n  aboutDialog()'
SENT_STATE = '@State showAbout: boolean = false;'

_doc = {}
_orig = {}


def load(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        s = f.read()
    crlf = '\r\n' in s
    return s.replace('\r\n', '\n'), crlf


def edit(p, old, new, expect=None, count=1):
    s = _doc[p]
    if expect is not None and expect not in old:
        raise AssertionError('expect 关键字不在 old 内: %r' % expect)
    if s.count(old) != count:
        raise AssertionError('锚点命中 %d 次（期望 %d）: %r' % (s.count(old), count, old[:90]))
    _doc[p] = s.replace(old, new, count)


for p in (IDX, APP):
    if not os.path.isfile(p):
        print('MISSING FILE: %s' % p)
        sys.exit(1)
    _doc[p], crlf = load(p)
    _orig[p] = _doc[p]
    _doc[p + '__crlf'] = crlf

if SENTINEL in _doc[IDX] or SENT_STATE in _doc[IDX]:
    print('ALREADY APPLIED')
    sys.exit(0)

# =========================================================
# 1. import 增加 bundleManager
# =========================================================
edit(IDX,
     "import { common } from '@kit.AbilityKit';",
     "import { common, bundleManager } from '@kit.AbilityKit';",
     expect="@kit.AbilityKit")

# =========================================================
# 2. 常量：仓库地址 + 版本兜底
# =========================================================
OLD_CONST = "/** 页面内容区底色。⚠️ 底部安全区**不能**用它，否则会和白色的 tab 栏形成色差 */\nconst C_PAGE: string = '#F1F3F5';\n"
NEW_CONST = (
    "/** 页面内容区底色。⚠️ 底部安全区**不能**用它，否则会和白色的 tab 栏形成色差 */\n"
    "const C_PAGE: string = '#F1F3F5';\n"
    "\n"
    "/** 上游开源仓库（梦醒了 大佬的 LANShare），「关于」里展示并可一键复制 */\n"
    "const ABOUT_REPO: string = 'https://github.com/fgsq-team/LANShare';\n"
    "/** 版本号兜底：运行时 bundleManager 取不到（或取到空串）时用这个，与 app.json5 同步 */\n"
    "const ABOUT_FALLBACK_VER: string = '5.0.26';\n"
)
edit(IDX, OLD_CONST, NEW_CONST, expect="const C_PAGE")

# =========================================================
# 3. @State
# =========================================================
edit(IDX,
     "  @State showQr: boolean = false;",
     "  /** 「关于」弹窗开关 */\n"
     "  @State showAbout: boolean = false;\n"
     "  /** 运行时从 bundleManager 取到的版本号；取不到则用 ABOUT_FALLBACK_VER */\n"
     "  @State aboutVer: string = '';\n"
     "  @State showQr: boolean = false;",
     expect="showQr")

# =========================================================
# 4. aboutToAppear 里取版本
# =========================================================
edit(IDX,
     "  aboutToAppear(): void {\n",
     "  aboutToAppear(): void {\n"
     "    this.loadVersion();\n",
     expect="aboutToAppear")

# =========================================================
# 5. 方法：loadVersion / copyRepo（插在 copyUrl 之前）
# =========================================================
OLD_METHOD = "  private copyUrl(): void {\n"
NEW_METHOD = (
    "  /**\n"
    "   * 取当前应用版本号。\n"
    "   *\n"
    "   * 走 `bundleManager.getBundleInfoForSelfSync`，而不是把版本号再抄一份字面量 ——\n"
    "   * 否则每次发版都要记得同步改，抄漏了「关于」里就是错的。\n"
    "   * ⚠️ 仍保留兜底常量：个别机型/时机下该 API 可能抛异常或返回空串，\n"
    "   *    总不能让「关于」里显示一个空白。\n"
    "   */\n"
    "  private loadVersion(): void {\n"
    "    try {\n"
    "      const info: bundleManager.BundleInfo = bundleManager.getBundleInfoForSelfSync(\n"
    "        bundleManager.BundleFlag.GET_BUNDLE_INFO_WITH_APPLICATION);\n"
    "      const v: string = info.versionName;\n"
    "      this.aboutVer = v.length > 0 ? v : ABOUT_FALLBACK_VER;\n"
    "    } catch (e) {\n"
    "      this.aboutVer = ABOUT_FALLBACK_VER;\n"
    "    }\n"
    "  }\n"
    "\n"
    "  /** 复制上游开源仓库地址（长按/点错都好过让用户手打 URL） */\n"
    "  private copyRepo(): void {\n"
    "    try {\n"
    "      const data: pasteboard.PasteData = pasteboard.createData(\n"
    "        pasteboard.MIMETYPE_TEXT_PLAIN, ABOUT_REPO);\n"
    "      pasteboard.getSystemPasteboard().setDataSync(data);\n"
    "      this.toast('仓库地址已复制');\n"
    "    } catch (e) {\n"
    "      this.toast('复制失败');\n"
    "    }\n"
    "  }\n"
    "\n"
    "  private copyUrl(): void {\n"
)
edit(IDX, OLD_METHOD, NEW_METHOD, expect="copyUrl")

# =========================================================
# 6. @Builder aboutDialog（插在 pickDialog 之前）
# =========================================================
OLD_BUILDER = "  @Builder\n  pickDialog() {\n"
NEW_BUILDER = (
    "  /**\n"
    "   * 「关于」弹窗：版本号 + 上游开源仓库 + 移植说明。\n"
    "   *\n"
    "   * 为什么走自绘而不是 `showDialog`：系统弹窗 title 字号固定、不按内容折行，\n"
    "   * 仓库 URL 那种长串会被截断（本页删文件弹窗已经踩过一次，见文件头记录）。\n"
    "   */\n"
    "  @Builder\n"
    "  aboutDialog() {\n"
    "    if (this.showAbout) {\n"
    "      Stack() {\n"
    "        Column()\n"
    "          .width('100%')\n"
    "          .height('100%')\n"
    "          .onClick(() => {\n"
    "            this.showAbout = false;\n"
    "          })\n"
    "\n"
    "        Column({ space: 12 }) {\n"
    "          // ---------------- 标题 + 关闭 ----------------\n"
    "          Row() {\n"
    "            Text('关于 LANShare')\n"
    "              .fontSize(16)\n"
    "              .fontWeight(FontWeight.Bold)\n"
    "              .fontColor(C_TEXT)\n"
    "              .layoutWeight(1)\n"
    "            Text('关闭')\n"
    "              .fontSize(13)\n"
    "              .fontColor(C_PRIMARY)\n"
    "              .onClick(() => {\n"
    "                this.showAbout = false;\n"
    "              })\n"
    "          }\n"
    "          .width('100%')\n"
    "          .alignItems(VerticalAlign.Center)\n"
    "\n"
    "          // ---------------- 版本号 ----------------\n"
    "          Row({ space: 8 }) {\n"
    "            Text('版本')\n"
    "              .fontSize(13)\n"
    "              .fontColor(C_SUB)\n"
    "            Text(this.aboutVer)\n"
    "              .fontSize(13)\n"
    "              .fontWeight(FontWeight.Medium)\n"
    "              .fontColor(C_TEXT)\n"
    "          }\n"
    "          .width('100%')\n"
    "          .alignItems(VerticalAlign.Center)\n"
    "\n"
    "          // ---------------- 移植说明 ----------------\n"
    "          Text('本应用是基于「梦醒了」大佬的开源项目 LANShare 移植的鸿蒙（HarmonyOS）版本。'\n"
    "            + '协议实现与核心代码均来自原开源项目，在此致谢。')\n"
    "            .fontSize(13)\n"
    "            .fontColor(C_TEXT)\n"
    "            .width('100%')\n"
    "\n"
    "          // ---------------- 开源仓库（可复制）----------------\n"
    "          Column({ space: 6 }) {\n"
    "            Text('开源仓库')\n"
    "              .fontSize(11)\n"
    "              .fontColor(C_SUB)\n"
    "              .width('100%')\n"
    "            Row({ space: 8 }) {\n"
    "              Text(ABOUT_REPO)\n"
    "                .fontSize(12)\n"
    "                .fontColor(C_PRIMARY)\n"
    "                .layoutWeight(1)\n"
    "                .maxLines(2)\n"
    "                .wordBreak(WordBreak.BREAK_ALL)\n"
    "              Text('复制')\n"
    "                .fontSize(12)\n"
    "                .fontColor(C_PRIMARY)\n"
    "                .onClick(() => {\n"
    "                  this.copyRepo();\n"
    "                })\n"
    "            }\n"
    "            .width('100%')\n"
    "            .alignItems(VerticalAlign.Center)\n"
    "          }\n"
    "          .width('100%')\n"
    "          .padding(10)\n"
    "          .backgroundColor('#F6F8FB')\n"
    "          .borderRadius(10)\n"
    "        }\n"
    "        .width('86%')\n"
    "        .padding(16)\n"
    "        .backgroundColor(C_CARD)\n"
    "        .borderRadius(14)\n"
    "        .shadow({ radius: 24, color: '#33000000', offsetX: 0, offsetY: 8 })\n"
    "        .onClick(() => {\n"
    "          // 吃掉点击，避免穿透到遮罩把弹窗关掉\n"
    "        })\n"
    "      }\n"
    "      .width('100%')\n"
    "      .height('100%')\n"
    "      .backgroundColor('#80000000')\n"
    "    }\n"
    "  }\n"
    "\n"
    "  @Builder\n"
    "  pickDialog() {\n"
)
edit(IDX, OLD_BUILDER, NEW_BUILDER, expect="pickDialog")

# =========================================================
# 7. 标题栏加「关于」按钮
# =========================================================
OLD_TITLE = (
    "          Text('LANShare')\n"
    "            .fontSize(22)\n"
    "            .fontWeight(FontWeight.Bold)\n"
    "            .fontColor(C_TEXT)\n"
    "          Blank()\n"
    "          this.stateChip()\n"
)
NEW_TITLE = (
    "          Text('LANShare')\n"
    "            .fontSize(22)\n"
    "            .fontWeight(FontWeight.Bold)\n"
    "            .fontColor(C_TEXT)\n"
    "          Blank()\n"
    "          // 「关于」入口：版本号 + 上游开源仓库 + 移植说明\n"
    "          Text('关于')\n"
    "            .fontSize(13)\n"
    "            .fontColor(C_PRIMARY)\n"
    "            .padding({ left: 10, right: 10, top: 4, bottom: 4 })\n"
    "            .onClick(() => {\n"
    "              this.showAbout = true;\n"
    "            })\n"
    "          this.stateChip()\n"
)
edit(IDX, OLD_TITLE, NEW_TITLE, expect="stateChip")

# =========================================================
# 8. build() 里挂上弹窗
# =========================================================
OLD_BUILD = (
    "      // ---------------- 网页地址二维码弹窗 ----------------\n"
    "      this.qrDialog()\n"
)
NEW_BUILD = (
    "      // ---------------- 网页地址二维码弹窗 ----------------\n"
    "      this.qrDialog()\n"
    "\n"
    "      // ---------------- 「关于」弹窗（版本号 / 开源仓库 / 移植说明）----------------\n"
    "      this.aboutDialog()\n"
)
edit(IDX, OLD_BUILD, NEW_BUILD, expect="qrDialog")

# =========================================================
# 9. 版本号 5.0.25 -> 5.0.26
# =========================================================
edit(APP, '"versionCode": 5000025', '"versionCode": 5000026', expect='versionCode')
edit(APP, '"versionName": "5.0.25"', '"versionName": "5.0.26"', expect='versionName')

# =========================================================
# 落盘前全量校验
# =========================================================
idx_new = _doc[IDX]
app_new = _doc[APP]

assert SENTINEL in idx_new, '落盘前：aboutDialog 缺失'
assert SENT_STATE in idx_new, '落盘前：showAbout 缺失'
assert idx_new.count("import { common, bundleManager } from '@kit.AbilityKit';") == 1, 'import 未改'
assert idx_new.count("const ABOUT_REPO: string = 'https://github.com/fgsq-team/LANShare';") == 1, '仓库常量缺失'
assert idx_new.count('this.loadVersion();') == 1, 'loadVersion 调用异常'
assert idx_new.count('private loadVersion(): void') == 1, 'loadVersion 定义异常'
assert idx_new.count('private copyRepo(): void') == 1, 'copyRepo 定义异常'
assert idx_new.count("this.aboutDialog()") == 1, 'aboutDialog 挂载异常'
assert idx_new.count("this.showAbout = true;") == 1, '关于按钮点击异常'
assert '"versionName": "5.0.26"' in app_new, '版本名未改'
assert '"versionCode": 5000026' in app_new, 'versionCode 未改'

for p in (IDX, APP):
    a = _orig[p].count('{') - _orig[p].count('}')
    b = _doc[p].count('{') - _doc[p].count('}')
    assert a == b, '括号增量不一致: %s (%d -> %d)' % (os.path.basename(p), a, b)

# ---------- 统一落盘 ----------
for p in (IDX, APP):
    if _doc[p] == _orig[p]:
        print('SKIP (no change): %s' % os.path.basename(p))
        continue
    s = _doc[p]
    if _doc[p + '__crlf']:
        s = s.replace('\n', '\r\n')
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)
    print('WROTE: %s' % os.path.basename(p))

print('PATCH 5.0.26 OK')
