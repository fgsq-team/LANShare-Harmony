#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5.1.59 补丁（纯网页端 JS）：鸿蒙端推送到网页时，单个文件直推、不打包

vivi 2026-10-03 实测：「手机浏览器单个文件还是会打包」。

★ 5.1.58 修错了地方：改的是 `lanshare.min.js` 的 `downloadFile()`
  （网页端**自己**勾选文件下载）。而 vivi 说的是**鸿蒙端主动推送**那条路径 ——
  `lanshareChat.min.js` 的 `autoDownloadFiles(b)`，由 WebSocket 的 `PUSH_FILES`
  消息触发（`ws.onmessage` -> `if (b.cmd === PUSH_FILES) autoDownloadFiles(b.list)`），
  它**无条件** `POST /compressFiles` ⇒ 哪怕只推 1 个文件也先在 cacheDir/webzip
  生成 zip。⇒ **同一个「打包下载」的逻辑在工程里有两处副本，只改一处必然漏。**

修法：
  b.list.length === 1  ⇒ 用 `b.names[0]` 拼 `/file/<名>?path=…&token=…` 直推，零打包
  否则                ⇒ 仍走 /compressFiles（浏览器不能一次下多个文件）

★ 关键：服务端 `LanService` 的推送 JSON **已经带了 `names`**（与 `list` 同序，
  见 LanService.ets:4115），只是网页端一直没用 ⇒ **ArkTS 零改动**。
  若 `names` 缺失（老版本对端），必须**回退到打包**，不能退化成 `/file/undefined`。

纪律：幂等 sentinel + 先校验后落盘 + 保持原行尾。
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
JS = os.path.join(ROOT, 'entry', 'src', 'main', 'resources', 'rawfile', 'web', 'js',
                  'lanshareChat.min.js')
BK = os.path.join(ROOT, 'docs', 'backups')

SENTINEL = 'function downloadOnePushed('

OLD = """function autoDownloadFiles(b) {
    if (!b || b.length === 0) {
        return
    }
    lightyear.notify("手机推送了 " + b.length + " 个文件，正在打包...", "info", 1500);
    lightyear.loading("show");
    post({
        url: "/compressFiles", data: JSON.stringify({list: b}), success: function (a) {
            lightyear.loading("hide");
            lightyear.notify("打包完成，开始下载", "success", 1000);
            window.location.href = "/downloadZipFile?tempFile=" + a.tempFile
        }, error: function (a) {
            console.error(a.message);
            lightyear.loading("hide");
            lightyear.notify("打包文件失败", "danger", 1500)
        }
    })
}"""

NEW = """// ★ 5.1.59：单个文件直推原文件，不在沙箱里生成 zip。
//   5.1.58 改的是「网页端自己勾选下载」那条（lanshare.min.js 的 downloadFile），
//   而这里是**鸿蒙端主动推送**那条 —— 同一个「打包下载」逻辑在工程里有两处副本。
//   ⚠️ 单个文件必须用 location.href（同页触发下载）；
//      多个文件只能用 zip（浏览器不能一次下多个）。
function downloadOnePushed(b, c) {
    // b = 路径，c = 文件名（服务端 PUSH_FILES 的 names，与 list 同序）
    if (b === undefined || b === null || b.length === 0
        || c === undefined || c === null || c.length === 0) {
        return false
    }
    window.location.href = "/file/" + c + "?path=" + encodeURIComponent(b)
        + "&token=" + localStorage.getItem("token");
    return true
}

function autoDownloadFiles(b, c) {
    if (!b || b.length === 0) {
        return
    }
    // ★ 只有 1 个文件且拿到了文件名 ⇒ 直推，零打包、零落盘。
    //   拿不到文件名（老版本鸿蒙端没推 names）时**必须回退到打包**，
    //   否则会退化成请求 /file/undefined。
    if (b.length === 1) {
        var n = (c && c.length > 0) ? c[0] : "";
        if (downloadOnePushed(b[0], n)) {
            return
        }
    }
    lightyear.notify("手机推送了 " + b.length + " 个文件，正在打包...", "info", 1500);
    lightyear.loading("show");
    post({
        url: "/compressFiles", data: JSON.stringify({list: b}), success: function (a) {
            lightyear.loading("hide");
            lightyear.notify("打包完成，开始下载", "success", 1000);
            window.location.href = "/downloadZipFile?tempFile=" + a.tempFile
        }, error: function (a) {
            console.error(a.message);
            lightyear.loading("hide");
            lightyear.notify("打包文件失败", "danger", 1500)
        }
    })
}"""


def main():
    s = io.open(JS, 'r', encoding='utf-8', newline='').read()
    if SENTINEL in s:
        print('ALREADY APPLIED')
        return 0

    # ---- 校验 ----
    assert s.count(OLD) == 1, 'autoDownloadFiles anchor count=%d' % s.count(OLD)
    assert NEW not in s
    # 调用点必须同步传 names，否则拿不到文件名
    old_call = 'if (b.cmd === PUSH_FILES) { autoDownloadFiles(b.list) }'
    new_call = 'if (b.cmd === PUSH_FILES) { autoDownloadFiles(b.list, b.names) }'
    assert s.count(old_call) == 1, '调用点 anchor count=%d' % s.count(old_call)
    # 服务端必须真的推了 names（ArkTS 零改动的前提）
    svc = io.open(os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service',
                               'LanService.ets'), 'r', encoding='utf-8').read()
    assert '"names":[${namesJson}]' in svc, '服务端 PUSH_FILES 不带 names ⇒ 前提不成立'
    assert 'WS_CMD_PUSH_FILES},\\"list\\":[${listJson}],\\"names\\"' in svc or \
        '"names":[${namesJson}]' in svc, '服务端推送格式变了'

    # ---- 构造 ----
    s2 = s.replace(OLD, NEW).replace(old_call, new_call)

    # ---- 二次校验 ----
    assert SENTINEL in s2
    assert s2.count(OLD) == 0
    assert s2.count(old_call) == 0
    assert s2.count(new_call) == 1
    assert s2.count('function autoDownloadFiles(b, c)') == 1
    # 单选直推分支必须在打包分支之前
    assert s2.index('if (b.length === 1)') < s2.index('url: "/compressFiles"')
    # 回退条件必须存在（拿不到名字不许退化）
    assert 'if (downloadOnePushed(b[0], n)) {' in s2
    assert s2.count('\r\n') == s.count('\r\n')

    # ---- 落盘 ----
    if not os.path.isdir(BK):
        os.makedirs(BK)
    dst = os.path.join(BK, 'lanshareChat.min.js.v5159pre')
    if not os.path.exists(dst):
        shutil.copy2(JS, dst)
        print('  备份 -> %s' % dst)
    io.open(JS, 'w', encoding='utf-8', newline='').write(s2)
    print('OK 5.1.59 patched: lanshareChat.min.js（推送单文件直推）')
    return 0


if __name__ == '__main__':
    sys.exit(main())