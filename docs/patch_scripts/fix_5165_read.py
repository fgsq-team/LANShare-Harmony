#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.65 编译错误修正 #2：异步 read 的返回类型（幂等）

## 踩坑全过程（值得记住）

我一开始去查 `ets/api/@ohos.fileio.d.ts`，看到
  `1197: declare function read(fd, buffer, options?): Promise<ReadOut>`
  `2230: interface ReadOut { bytesRead: number }`
于是照抄成 `const out: fileIo.ReadOut = await fileIo.read(...)`。
⇒ 编译报 **`Namespace 'fileIo' has no exported member 'ReadOut'`**。

改成字面量类型 `{ bytesRead: number }` ⇒ 又报
  **`arkts-no-obj-literals-as-types`**（ArkTS 禁字面量类型）
  + **`Type 'number' is not assignable to type '{ bytesRead: number; }'`**  ← ★ 这行才是真相

## 真相
`@kit.CoreFileKit` 的 `fileIo` 实际来自 **`@ohos.file.fs`**，那里
  `2664: declare function read(fd, buffer, options?): Promise<number>`
—— **直接返回字节数，既没有 ReadOut 也没有 bytesRead 字段**。

★ **那份 `ets/api/@ohos.fileio.d.ts` 是旧命名空间，已过时**。
  ⇒ 核对签名要认准工程实际 import 的那个：
  本工程 `import { fileIo } from '@kit.CoreFileKit'`
  ⇒ 去 `kits/@kit.CoreFileKit.d.ts` 看它 re-export 自哪个，再看那个文件的签名。
  ★ **编译器报「类型不匹配」时，别急着加类型标注 —— 先看它说「实际类型是什么」**，
    那个 `is not assignable to` 的右半边就是答案。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = 'const n: number = await fileIo.read(src.fd, buf);'

OLD = """        // ★ 5.1.65：`fileIo.ReadOut` 在 ArkTS 里**不能用作显式类型标注**
        //   （编译报 `Namespace 'fileIo' has no exported member 'ReadOut'`）
        //   ⇒ 用结构相同的字面量类型。
        const out: { bytesRead: number } = await fileIo.read(src.fd, buf);
        const n: number = out.bytesRead;"""

NEW = """        // ★ 5.1.65：异步 `read` **直接返回字节数**。
        //   ⚠️ 别照抄 `ets/api/@ohos.fileio.d.ts`（**旧命名空间，已过时**）：
        //   那里写的是 `Promise<ReadOut>` + `ReadOut.bytesRead`。
        //   工程实际 import 的是 `@kit.CoreFileKit` 的 `fileIo`
        //   ⇒ 其源头 `@ohos.file.fs` 第 2664 行是
        //      `read(fd, buffer, options?): Promise<number>`
        //   所以既没有 `ReadOut` 类型，也没有 `bytesRead` 字段。
        const n: number = await fileIo.read(src.fd, buf);"""


def main():
    rel = 'entry/src/main/ets/service/ExportService.ets'
    path = os.path.join(ROOT, rel)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()
    if PROBE in src:
        print('SKIP 已应用')
        return
    if src.count(OLD) != 1:
        print('ABORT count=%d' % src.count(OLD))
        sys.exit(1)
    src = src.replace(OLD, NEW, 1)
    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(src)
    print('OK %s' % rel)


if __name__ == '__main__':
    main()
