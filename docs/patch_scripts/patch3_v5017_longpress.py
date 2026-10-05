# -*- coding: utf-8 -*-
"""
LANShareV5 5.0.17 修补 1：

  `.onLongPress(fn)` 在 API 26 的 ArkUI 里**不是 CommonMethod 属性** ——
  编译直接报 `10505001 Property 'onLongPress' does not exist on type 'ColumnAttribute'`。
  长按只有一条路：`.gesture(LongPressGesture({...}).onAction(fn))`
  （文件页的「长按进多选」本来就是这么写的，本轮抄漏了形态）。

幂等：哨兵串判重。
"""

import io
import sys

F = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
SENTINEL = 'LongPressGesture({ repeat: false, duration: 400 })\n        .onAction(() => {\n          if (imgPath.length === 0) {'


def read(p):
    return io.open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='').write(s)


s = read(F)

if SENTINEL in s:
    print('ALREADY APPLIED - 长按修补此前已打过，跳过')
    sys.exit(0)

OLD = r"""    // 长按存相册。⚠️ 只对**收到的图片**有意义：自己发出去的图不在沙箱里，
    // 原图本来就在用户手上，再存一份是多余动作。
    .onLongPress(() => {
      if (imgPath.length === 0) {
        return;
      }
      this.clickMuteUntil = Date.now() + 800;
      this.saveImageToAlbum(imgPath, m.content);
    })
  }"""

NEW = r"""    // 长按存相册。⚠️ 只对**收到的图片**有意义：自己发出去的图不在沙箱里，
    // 原图本来就在用户手上，再存一份是多余动作。
    // ⚠️ 必须走 `.gesture(LongPressGesture)` —— 这个 SDK 的 ArkUI **没有**
    //    `onLongPress` 这个 CommonMethod 属性，写 `.onLongPress()` 直接
    //    编译报 `10505001 ... does not exist on type 'ColumnAttribute'`。
    //    文件页的「长按进多选」本来就是这么写的，本轮抄漏了形态。
    .gesture(
      LongPressGesture({ repeat: false, duration: 400 })
        .onAction(() => {
          if (imgPath.length === 0) {
            return;
          }
          this.clickMuteUntil = Date.now() + 800;
          this.saveImageToAlbum(imgPath, m.content);
        })
    )
  }"""

assert s.count('.onLongPress(') == 1, '.onLongPress 命中 %d 处（应为 1）' % s.count('.onLongPress(')
assert s.count(OLD) == 1, '旧长按块命中 %d 处（应为 1）' % s.count(OLD)
assert s.count(NEW) == 0, '新长按块此前已存在'

s = s.replace(OLD, NEW)
assert s.count('.onLongPress(() =>') == 0, '还有残留的 .onLongPress 调用'
assert s.count('{') == s.count('}'), '括号不平：%d vs %d' % (s.count('{'), s.count('}'))

write(F, s)
print('OK - 长按已改为 .gesture(LongPressGesture)')
