#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5.1.60 补丁②：修「零落盘路径被开头的空守卫短路」

verify_web_zero_copy_5160.js 抓到：用例 A（paths 为空、只有 uris）没走 /stagefile/。
根因：`autoDownloadFiles` 开头仍有 5.1.59 的守卫
`if (!b || b.length === 0) { return }` —— 5.1.60 的零落盘推送**不带 paths**
（服务端只推 uris + names），于是第一行就 return 了。
★ 这正是「改了主分支忘了改入口守卫」的典型。

修：入口守卫改为「paths 与 uris 都为空才return」。

纪律：幂等 + 先校验后落盘 + 保持行尾。
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
JS = os.path.join(ROOT, 'entry', 'src', 'main', 'resources', 'rawfile', 'web', 'js',
                  'lanshareChat.min.js')
BK = os.path.join(ROOT, 'docs', 'backups')

SENT = 'var hasUri = !!(d && d.length > 0);'

OLD = """function autoDownloadFiles(b, c, d) {
    if (!b || b.length === 0) {
        return
    }
    // ★ 只有 1 个文件且拿到了文件名 ⇒ 直推，零打包、零落盘。
    //   拿不到文件名（老版本鸿蒙端没推 names）时**必须回退到打包**，
    //   否则会退化成请求 /file/undefined。
    if ((!b || b.length === 0) && c && c.length === 1) {"""

NEW = """function autoDownloadFiles(b, c, d) {
    // ★ 5.1.60 修：入口守卫必须同时看 paths 与 uris。
    //   零落盘推送**只带 uris + names、不带 paths**，原先只判b.length === 0
    //   会在第一行直接 return ⇒ 零落盘路径永远走不到（verify 脚本抓出来的）。
    var hasPath = !!(b && b.length > 0);
    var hasUri = !!(d && d.length > 0);
    if (!hasPath && !hasUri) {
        return
    }
    // ★ 只有 1 个文件且拿到了文件名 ⇒ 直推，零打包、零落盘。
    //   拿不到文件名（老版本鸿蒙端没推 names）时**必须回退到打包**，
    //   否则会退化成请求 /file/undefined。
    if (!hasPath && hasUri && c && c.length === 1) {"""


def main():
    s = io.open(JS, 'r', encoding='utf-8', newline='').read()
    if SENT in s:
        print('ALREADY APPLIED')
        return 0
    assert s.count(OLD) == 1, 'anchor count=%d' % s.count(OLD)
    s2 = s.replace(OLD, NEW)
    # 后续两个分支也要改成用 hasPath（避免重复判空、语义一致）
    s2 = s2.replace("""    if (b && b.length === 1) {
        var m = (c && c.length > 0) ? c[0] : "";""",
                    """    if (hasPath && b.length === 1) {
        var m = (c && c.length > 0) ? c[0] : "";""")
    # 打包分支的 list 要容错（零落盘路径不该进这里，但别传 undefined 给JSON.stringify）
    s2 = s2.replace('url: "/compressFiles", data: JSON.stringify({list: b}), success: function (a) {',
                    'url: "/compressFiles", data: JSON.stringify({list: b || []}), success: function (a) {')
    s2 = s2.replace('lightyear.notify("手机推送了 " + b.length + " 个文件，正在打包...", "info", 1500);',
                    'lightyear.notify("手机推送了 " + (b ? b.length : 0) + " 个文件，正在打包...", "info", 1500);')
    # ---- 校验 ----
    assert SENT in s2
    assert s2.count('var hasPath =') == 1
    assert s2.count('if (!hasPath && hasUri && c && c.length === 1) {') == 1
    assert s2.count('if (hasPath && b.length === 1) {') == 1
    assert s2.count('{list: b || []}') == 1
    assert s2.count('\r\n') == s.count('\r\n')

    if not os.path.isdir(BK):
        os.makedirs(BK)
    dst = os.path.join(BK, 'lanshareChat.min.js.v5160b')
    if not os.path.exists(dst):
        shutil.copy2(JS, dst)
        print('  备份 -> %s' % dst)
    io.open(JS, 'w', encoding='utf-8', newline='').write(s2)
    print('OK 5.1.60b patched: 入口守卫同时看 paths 与 uris')
    return 0


if __name__ == '__main__':
    sys.exit(main())