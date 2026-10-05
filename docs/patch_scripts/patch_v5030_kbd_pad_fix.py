# -*- coding: utf-8 -*-
"""
5.0.30 —— 修「输入框离键盘一条空白」：键盘让位高度扣掉 tab 栏 + 底部安全条。

根因：keyboardVp 是「屏幕底 → 键盘顶」的距离，但 padding 加在 TabContent 上，
TabContent 的底边本来就在 tab 栏(50vp)+底部安全条(bottomInset)之上，
再垫 keyboardVp 就把输入框多抬高了 (50+bottomInset) —— 正是截图里那条空白。

修法：onKeyboardHeight 里换算后减去这两段，clamp ≥ 0。
幂等（哨兵）+ 全量校验 + 统一落盘。
"""
import io, os, sys, shutil

ROOT = r"E:\lanshare-harmony\LANShareV5"
V5 = os.path.join(ROOT, "entry", "src", "main", "ets", "service", "V5Transfer.ets")  # unused guard
IDX = os.path.join(ROOT, "entry", "src", "main", "ets", "pages", "Index.ets")
APP = os.path.join(ROOT, "AppScope", "app.json5")

SENT_KEY = "KEYBOARD_PAD_EFFECTIVE_5030"
OLD_CORE = (
    "    const vp: number = px > 0 ? this.getUIContext().px2vp(px) : 0;\n"
    "    const wasUp: boolean = this.keyboardVp > 0;\n"
    "    this.keyboardVp = vp;\n"
)
NEW_CORE = (
    "    // KEYBOARD_PAD_EFFECTIVE_5030\n"
    "    // 5.0.30：keyboardHeightChange 给的是「屏幕底→键盘顶」，但 padding 垫在 TabContent 上，\n"
    "    // TabContent 底边本就在 tab 栏(50vp, 见 .barHeight(50)) + 底部安全条(bottomInset) 之上，\n"
    "    // 不扣这两段输入框会被多抬高一条空白（vivi 2026-10-01 截图实测）。\n"
    "    const totalVp: number = px > 0 ? this.getUIContext().px2vp(px) : 0;\n"
    "    const reserved: number = 50 + this.bottomInset;\n"
    "    const vp: number = px > 0 ? Math.max(0, totalVp - reserved) : 0;\n"
    "    const wasUp: boolean = this.keyboardVp > 0;\n"
    "    this.keyboardVp = vp;\n"
    "    Log.i(TAG, `键盘: px=${px} total=${totalVp}vp 扣除=${reserved}vp 实垫=${vp}vp`);\n"
)

OLD_VER = '"versionCode": 5000029,\n    "versionName": "5.0.29"'
NEW_VER = '"versionCode": 5000030,\n    "versionName": "5.0.30"'

_doc = {}
_orig = {}

def load(p):
    with io.open(p, encoding="utf-8", newline="") as f:
        s = f.read()
    s = s.replace("\r\n", "\n")
    _orig[p] = s
    _doc[p] = s

def edit(p, old, new, tag):
    s = _doc[p]
    if SENT_KEY in s:
        print("SKIP", tag, "(already applied)")
        return
    assert s.count(old) == 1, "%s: anchor count=%d" % (tag, s.count(old))
    assert s.count(new) == 0, "%s: new text already present" % tag
    _doc[p] = s.replace(old, new)
    print("EDIT", tag, "OK")

load(IDX)
load(APP)

edit(IDX, OLD_CORE, NEW_CORE, "onKeyboardHeight 扣除 tab 栏+安全条")
edit(APP, OLD_VER, NEW_VER, "版本 5.0.30")

# ---- 落盘前全量校验 ----
idx_new = _doc[IDX]
assert SENT_KEY in idx_new, "落盘前哨兵缺失"
assert "Math.max(0, totalVp - reserved)" in idx_new, "落盘前扣除逻辑缺失"
assert idx_new.count("this.keyboardVp = vp;") == 1, "keyboardVp 赋值异常"
app_new = _doc[APP]
assert "5.0.30" in app_new and "5.0.29" not in app_new, "版本替换异常"

# ---- 统一落盘 ----
# ⚠️ 备份必须放 docs/backups/，不能放源码目录 —— hvigor 会把源码目录里的
#    任意文件打进 HAP（实测 Index.ets.backup_v5030 被打进包，+149KB）。
BK = os.path.join(ROOT, "docs", "backups")
os.makedirs(BK, exist_ok=True)
for p in (IDX, APP):
    if _doc[p] != _orig[p]:
        bak = os.path.join(BK, os.path.basename(p) + ".backup_v5030")
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            f.write(_doc[p])
        print("WRITE", p)
print("ALL DONE")
