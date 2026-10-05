#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5.1.60 补丁③：修「WebPushItem 类定义插进了 import 区中间」

编译错误 `10605150arkts-no-misplaced-imports` @ LanService.ets:66
原因：上一版补丁把类定义插在 `import {WebSocketSession...}` 之后，
而后面还有一行 `import {TextMessenger... }` ⇒ import 不再全部连续。

修：把类定义整体挪到**最后一个 import 之后**（`const TAG` 之前）。

★ 顺带记一条铁律：ArkTS 的 import 必须**全部连续**放在文件头 ——
  在 import 区中间插入任何声明，都会把后面的 import 变成「misplaced import」。
纪律：幂等 + 先校验后落盘 + LF。
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
P = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'LanService.ets')
BK = os.path.join(ROOT, 'docs', 'backups')

SENT = "const TAG: string = 'LanService';"

OLD = """import { WebSocketSession, WS_CMD_SYNC_DEVICE_LIST, WS_CMD_SEND_MESSAGE, WS_CMD_PUSH_FILES } from './WebSocketSession';

/** ★ 5.1.60「发送到网页端」零落盘要推给网页端的一项：一个授权 URI + 它要用的文件名 */
export class WebPushItem {
  /** picker / 相册给的授权 URI（`datashare://` 等），**不是沙箱路径** */
  uri: string = '';
  /** 网页端拼下载 URL 用的文件名（含扩展名） */
  name: string = '';

  constructor(uri: string = '', name: string = '') {
    this.uri = uri;
    this.name = name;
  }
}
import { TextMessenger, TextSendResult } from './TextMessenger';

const TAG: string = 'LanService';"""

NEW = """import { WebSocketSession, WS_CMD_SYNC_DEVICE_LIST, WS_CMD_SEND_MESSAGE, WS_CMD_PUSH_FILES } from './WebSocketSession';
import { TextMessenger, TextSendResult } from './TextMessenger';

// ★★ ArkTS铁律：`import` 必须**全部连续**放在文件头。
//   在 import 区中间插入任何声明 ⇒ 后面的 import 变成 `arkts-no-misplaced-imports`（10605150）。

/** ★ 5.1.60「发送到网页端」零落盘要推给网页端的一项：一个授权 URI + 它要用的文件名 */
export class WebPushItem {
  /** picker / 相册给的授权 URI（`datashare://` 等），**不是沙箱路径** */
  uri: string = '';
  /** 网页端拼下载 URL 用的文件名（含扩展名） */
  name: string = '';

  constructor(uri: string = '', name: string = '') {
    this.uri = uri;
    this.name = name;
  }
}

const TAG: string = 'LanService';"""


def main():
    s = io.open(P, 'r', encoding='utf-8', newline='').read()
    if "// ★★ ArkTS铁律：`import` 必须**全部连续**放在文件头。" in s:
        print('ALREADY APPLIED')
        return 0
    assert s.count(OLD) == 1, 'anchor count=%d' % s.count(OLD)
    s2 = s.replace(OLD, NEW)
    assert s2.count(SENT) == 1
    assert 'arkts-no-misplaced-imports' in s2
    # 校验：import 区之后紧跟的就是 const TAG，中间只有注释与类定义
    tail = s2[:s2.index(SENT) + len(SENT)]
    assert "from './TextMessenger';" in tail
    assert tail.rindex("from './TextMessenger';") < tail.index('export class WebPushItem'), \
        '类定义仍在 import 中间'
    assert s2.count('\r\n') == s.count('\r\n')

    dst = os.path.join(BK, 'LanService.ets.v5160c')
    if not os.path.exists(dst):
        shutil.copy2(P, dst)
        print('  备份 -> %s' % dst)
    io.open(P, 'w', encoding='utf-8', newline='').write(s2)
    print('OK 5.1.60c: WebPushItem 移到 import 区之后')
    return 0


if __name__ == '__main__':
    sys.exit(main())