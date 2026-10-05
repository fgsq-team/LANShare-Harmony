#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.65 编译错误修正（3 处，幂等）

编译器报的三个错（`.hvigor/outputs/build-logs/build.log`）：

1. `Type 'Promise<string>' is not assignable to type 'string'` @ ExportService.ets:369
   ⇒ **漏了第三个 copyTo 调用点**：「另存为」对话框（`saveAs` 里的批量另存）
      在 ExportService **内部**调 `ExportService.copyTo`。
      ★ 教训：改函数签名时**必须 grep 全部调用点**（含同文件内部的）。
      我只 grep 了 `Index.ets` 里的 `ExportService.copyTo`，漏了 `ExportService` 内部的。

2. `Namespace 'fileIo' has no exported member 'ReadOut'` @ ExportService.ets:422
   ⇒ `ReadOut` 虽然在 `@ohos.fileio.d.ts` 第 87 行 `export { ReadOut }`，
      但 **ArkTS 里不能拿它做显式类型标注**。
      ⇒ 改用**字面量类型** `{ bytesRead: number }`（结构相同，编译器接受）。

3. `Cannot find name 'idxBatch'` @ Index.ets:4545
   ⇒ `idxBatch` / `toDelete` 声明在 `try` **块内**，而落盘+删沙箱在 `try` **块外**。
      ★ ArkTS 的块级作用域是硬性的。
      ⇒ 声明**提到 `try` 之前**（与 5.1.64 的 `cancelled/failed` 同一处理法）。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


def main():
    plans = []

    # ---- 1) ExportService 内部那个调用点加 await ----
    rel = 'entry/src/main/ets/service/ExportService.ets'
    path = os.path.join(ROOT, rel)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()
    old1 = "      const msg: string = ExportService.copyTo(files[i].path, uris[i], files[i].name);"
    new1 = "      const msg: string = await ExportService.copyTo(files[i].path, uris[i], files[i].name);"
    probe1 = 'await ExportService.copyTo(files[i].path, uris[i], files[i].name)'
    if probe1 in src:
        print('SKIP 1: 调用点已改')
    else:
        if src.count(old1) != 1:
            print('ABORT 1: count=%d' % src.count(old1))
            sys.exit(1)
        src = src.replace(old1, new1, 1)
        plans.append((path, rel, src))

    # ---- 2) ReadOut 改字面量类型 ----
    old2 = "        const out: fileIo.ReadOut = await fileIo.read(src.fd, buf);"
    new2 = ("        // ★ 5.1.65：`fileIo.ReadOut` 在 ArkTS 里**不能用作显式类型标注**\n"
            "        //   （编译报 `Namespace 'fileIo' has no exported member 'ReadOut'`）\n"
            "        //   ⇒ 用结构相同的字面量类型。\n"
            "        const out: { bytesRead: number } = await fileIo.read(src.fd, buf);")
    probe2 = "const out: { bytesRead: number } = await fileIo.read(src.fd, buf);"
    if probe2 in src:
        print('SKIP 2: ReadOut 已改')
    else:
        if src.count(old2) != 1:
            print('ABORT 2: count=%d' % src.count(old2))
            sys.exit(1)
        src = src.replace(old2, new2, 1)
        plans.append((path, rel, src))

    # ---- 3) idxBatch/toDelete 声明提到 try 之前 ----
    rel3 = 'entry/src/main/ets/pages/Index.ets'
    path3 = os.path.join(ROOT, rel3)
    s3 = io.open(path3, 'r', encoding='utf-8', newline='').read()

    old3a = """    let cancelled: boolean = false;
    let failed: boolean = false;
    try {"""
    new3a = """    let cancelled: boolean = false;
    let failed: boolean = false;
    // ★★ 5.1.65：这两个数组在 `try` **块外**也要用（落盘 + 删沙箱），
    //   ArkTS 块级作用域是硬性的 ⇒ 声明必须提到 try 之前（同 cancelled/failed）。
    const idxBatch: string[] = [];
    const toDelete: string[] = [];
    try {"""
    probe3a = '这两个数组在 `try` **块外**也要用'

    old3b = """      const missed: string[] = [];
      for (let j: number = 0; j < gotUris.length; j++) {"""
    new3b = """      const missed: string[] = [];
      // ★★ 5.1.65：整批收集，循环结束后**一次性**落盘 + 一次性删沙箱。
      //   （`idxBatch` / `toDelete` 已声明在 try 之前，见本方法开头。）
      for (let j: number = 0; j < gotUris.length; j++) {"""

    if probe3a in s3:
        print('SKIP 3: 声明已提前')
    else:
        if s3.count(old3a) != 1:
            print('ABORT 3a: count=%d' % s3.count(old3a))
            sys.exit(1)
        if s3.count(old3b) != 1:
            print('ABORT 3b: count=%d' % s3.count(old3b))
            sys.exit(1)
        s3 = s3.replace(old3a, new3a, 1).replace(old3b, new3b, 1)
        plans.append((path3, rel3, s3))

    for path, rel, content in plans:
        with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
        print('OK %s' % rel)
    print('DONE')


if __name__ == '__main__':
    main()
