#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5.1.58 补丁（纯网页端 JS，不动 ArkTS）：单选时直推原文件，不打包

vivi 2026-10-03 决定：
  · 选 A 方案（单选不走 zip）
  · **不希望在沙箱里存一份**，直接推送到网页
  · 「网页端的列表里选择在鸿蒙端不适用」⇒ 鸿蒙端不做这个功能

现状（`web/js/lanshare.min.js` 的 `downloadFile()`）：
  无条件POST /compressFiles ⇒ **哪怕只勾 1 个文件也先在cacheDir/webzip
  生成一个 zip，再让浏览器去取** —— 违反「不要在沙箱里存一份」。

改法（仅 JS，ArkTS 侧 `/file/<名>?path=…&token=…` 本就完备、零改动）：
  · 勾选 **1** 个 ⇒ `window.location.href = "/file/<名>?path=…&token=…"` 直接推原文件
  · 勾选 **≥2** 个 ⇒ 仍走原来的 /compressFiles 打包（浏览器不能一次下多个文件）

⚠️ 为什么单选走 `location.href` 而不是 `window.open`：
   右键「打开」用的是 `window.open(..., "_blank")`（新标签页预览），
   而「下载」要的是浏览器下载 ⇒ 必须用 `location.href`（同标签页，触发下载）。

⚠️ 文件名从 `.file-item-name` 取：列表项 `<div file-path=…>` 上**没有** file-name 属性
   （只有 media 的右键菜单用 `file-name`/`path`）。这里取文本再 strip，避免引号/尖括号污染。

纪律：幂等 sentinel + 先校验后落盘 + UTF-8(LF 保持原样，仅替换片段)。
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
JS = os.path.join(ROOT, 'entry', 'src', 'main', 'resources', 'rawfile', 'web', 'js',
                  'lanshare.min.js')
BK = os.path.join(ROOT, 'docs', 'backups')

SENTINEL = 'function downloadOneDirect('

OLD = """function downloadFile() {
    list = [];
    $(".file-item").each(function (a, b) {
        if ($(b).find(".file-img-select").is(":checked")) {
            filePath = $(b).attr("file-path");
            list.push(filePath)
        }
    });
    lightyear.notify("文件正在打包中...", "info", 1000);
    lightyear.loading("show");
    post({
        url: "/compressFiles", data: JSON.stringify({list: list}), success: function (a) {
            lightyear.loading("hide");
            lightyear.notify("文件打包成功，开始下载", "success", 1000);
            window.location.href = "/downloadZipFile?tempFile=" + a.tempFile
        }, error: function (a) {
            console.error(a.message);
            lightyear.loading("hide");
            lightyear.notify("打包文件失败", "danger", 1000)
        }
    })
}"""

NEW = """// ★ 5.1.58：单选时「直接推原文件」，不在沙箱里生成 zip。
//   URL 形式与右键「打开」（openFile）完全一致，只是把 window.open 换成
//   location.href —— 后者才会触发浏览器下载，前者是新标签页预览。
function downloadOneDirect(b) {
    var a = $(b).attr("file-path");
    var c = $(b).find(".file-item-name").text();
    if (c === undefined || c === null) {
        c = "";
    }
    c = $.trim(c);
    if (a === undefined || a === null || a.length === 0 || c.length === 0) {
        lightyear.notify("取不到文件名，请重试", "danger", 1500);
        return false
    }
    window.location.href = "/file/" + c + "?path=" + encodeURIComponent(a)
        + "&token=" + localStorage.getItem("token");
    return true
}

function downloadFile() {
    var list = [];
    var picked = [];
    $(".file-item").each(function (a, b) {
        if ($(b).find(".file-img-select").is(":checked")) {
            var p = $(b).attr("file-path");
            var d = $.trim($(b).find(".file-item-name").text() || "");
            // 返回上一级那条（list[0]）没有勾选框，理论上进不来；
            // 这里再挡一次「有勾选框但没有文件名」的畸形项，避免请求 /file/undefined。
            if (p !== undefined && p !== null && p.length > 0 && d.length > 0) {
                list.push(p);
                picked.push(b)
            }
        }
    });
    if (list.length === 0) {
        lightyear.notify("请先勾选文件", "warning", 1500);
        return
    }
    // ★ 只有 1 个 ⇒ 直推。多个才打包（浏览器不能一次下多个文件）。
    if (list.length === 1) {
        downloadOneDirect(picked[0]);
        return
    }
    lightyear.notify("文件正在打包中...", "info", 1000);
    lightyear.loading("show");
    post({
        url: "/compressFiles", data: JSON.stringify({list: list}), success: function (a) {
            lightyear.loading("hide");
            lightyear.notify("文件打包成功，开始下载", "success", 1000);
            window.location.href = "/downloadZipFile?tempFile=" + a.tempFile
        }, error: function (a) {
            console.error(a.message);
            lightyear.loading("hide");
            lightyear.notify("打包文件失败", "danger", 1000)
        }
    })
}"""


def main():
    s = io.open(JS, 'r', encoding='utf-8', newline='').read()
    if SENTINEL in s:
        print('ALREADY APPLIED')
        return 0

    # ---- 校验 ----
    n = s.count(OLD)
    assert n == 1, 'downloadFile anchor count=%d' % n
    assert NEW not in s
    # 必须确认服务端契约没变：单文件直推用的 /file/ 入口存在
    router = io.open(os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'net',
                                  'HttpRouter.ets'), 'r', encoding='utf-8').read()
    assert "'/downloadZipFile'" in router, '/downloadZipFile 路由不见了'
    assert '/file/' in router, '/file/ 路由不见了'

    # ---- 构造 + 二次校验 ----
    s2 = s.replace(OLD, NEW)
    assert SENTINEL in s2
    assert s2.count(OLD) == 0
    assert s2.count('function downloadFile()') == 1
    assert s2.count('function downloadOneDirect(') == 1
    # 单选直推分支必须在打包分支之前
    assert s2.index('if (list.length === 1)') < s2.index('url: "/compressFiles"')
    # 不再把未声明的全局 filePath 当隐式全局用（原代码是 bug：漏 var）
    assert 'filePath = $(b).attr("file-path")' not in s2
    # 行尾未被改动（保持 CRLF/LF 原样）
    assert s2.count('\r\n') == s.count('\r\n')

    # ---- 落盘 ----
    if not os.path.isdir(BK):
        os.makedirs(BK)
    dst = os.path.join(BK, 'lanshare.min.js.v5158pre')
    if not os.path.exists(dst):
        shutil.copy2(JS, dst)
        print('  备份 -> %s' % dst)
    io.open(JS, 'w', encoding='utf-8', newline='').write(s2)
    print('OK 5.1.58 patched: lanshare.min.js（单选直推，多选仍打包）')
    return 0


if __name__ == '__main__':
    sys.exit(main())