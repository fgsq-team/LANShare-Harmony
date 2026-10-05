#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.67 关键修正：A1/A2 的 push 被误删，导致批量落盘完整失效（幂等）

## 现象（vivi 2026-10-05 14:31 真机复测 5.1.66）
- 存相册每批仍是 `确认框返回 → 完成 = 3~4 秒`，与 5.1.64 一模一样，
  **完全没改善** ⇒ 5.1.65 的 A1/A2/A3 都没起作用。
- A4 入队日志聚合**生效了**（426 项一条日志）⇒ 说明那一处改动是好的。

## 根因（代码层证据）
`autoSaveAlbumBatch` 里：
```ts
const idxBatch: string[] = [];        // ← 声明在（try 之前，4405 行）
const toDelete: string[] = [];
...
for (let j = 0; j < gotUris.length; j++) {
  ...
  await this.service.setAlbumIndex(batchKeys[i], gotUris[j], thumb, rot);  // ★ 还是每张全量落盘
  ExportService.deleteFile(...);                                          // ★ 还是每张立刻删
  // ❌ 从来没有 idxBatch.push(...) / toDelete.push(...)
}
...
await this.service.setAlbumIndexBatch(idxBatch);   // ← 调用在，但数组永远是空的
for (... toDelete ...) { }                        // ← 同理，空转
```
⇒ **声明在、使用在、中间的 push 不在** ⇒ 两个数组恒为空 ⇒ A1/A2 完整失效。
★ 而且**编译器不会报错**（未使用的局部变量只是 warning），
  功能上等于没改 —— 与 5.1.66 漏 `sinceYield` 是同一类静默失效。

## 为什么会漏
5.1.65 的 `fix_5165_err.py` 在修「`idxBatch` 声明位置」时，
把「声明 + push」当成一整段替换，新串只写了注释、**漏了 push 两行**。

## 修法
循环内改成：只 push，不落盘、不删文件；
落盘与删沙箱统一放到循环之后（`setAlbumIndexBatch` + 删 toDelete）。
★ 顺序比原来更安全：原来「每张落盘后立刻删」中途崩溃 ⇒ 索引写了、文件没了；
  现在整批落盘成功才删 ⇒ 任一步崩溃都还能靠沙箱副本重建缩略图。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = 'idxBatch.push(`${batchKeys[i]}|${gotUris[j]}|${thumb}|${rot}`);'
REL = 'entry/src/main/ets/pages/Index.ets'

OLD = """          // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反
          const thumb: string = await this.cacheThumb(ctx, batchPaths[i], batchKeys[i]);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          await this.service.setAlbumIndex(batchKeys[i], gotUris[j], thumb, rot);
          const derr: string | null =
            ExportService.deleteFile(this.service.receiveRoot, batchPaths[i]);
          if (derr !== null) {
            Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${batchPaths[i]}`);
          }"""

NEW = """          // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反
          const thumb: string = await this.cacheThumb(ctx, batchPaths[i], batchKeys[i]);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          // ★★ 5.1.67 关键修正：这里**只进数组**。
          //   5.1.65 的 A1/A2 声明了 `idxBatch`/`toDelete`、循环后也用了，
          //   但**中间这两行 push 被误删** ⇒ 两个数组恒为空 ⇒ 批量落盘完整失效
          //   （真机复测：每批仍是 3~4 秒，与 5.1.64 一模一样）。
          //   ⚠️ 少了 push 编译器**不报错**（只是未使用变量的 warning）⇒ 静默失效。
          idxBatch.push(`${batchKeys[i]}|${gotUris[j]}|${thumb}|${rot}`);
          // ③ 删沙箱副本挪到**索引落盘之后**（见循环外）——
          //   万一进程挂掉，沙箱副本还在 ⇒ 缩略图与索引可重建，不会丢图。
          toDelete.push(batchPaths[i]);"""


def main():
    path = os.path.join(ROOT, REL)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()

    if PROBE in src:
        print('SKIP 已应用')
        return

    # 前置检查：声明与循环后使用必须都在，否则改了也是空转
    checks = [
        ('const idxBatch: string[] = [];', 'idxBatch 声明'),
        ('const toDelete: string[] = [];', 'toDelete 声明'),
        ('await this.service.setAlbumIndexBatch(idxBatch);', '循环后落盘'),
    ]
    for s, tag in checks:
        if src.count(s) < 1:
            print('ABORT: 缺少 %s（%s）—— 先补齐再改 push' % (tag, s))
            sys.exit(1)

    if src.count(OLD) != 1:
        print('ABORT count=%d' % src.count(OLD))
        sys.exit(1)

    src = src.replace(OLD, NEW, 1)

    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)
    # 关键自检：两个 push 都必须在
    if 'toDelete.push(batchPaths[i]);' not in src:
        print('ABORT: toDelete.push 未写入')
        sys.exit(1)
    # 确认老的每张落盘/每张删已移除
    if 'await this.service.setAlbumIndex(batchKeys[i], gotUris[j], thumb, rot);' in src:
        print('ABORT: 老的每张 setAlbumIndex 仍在')
        sys.exit(1)
    if 'ExportService.deleteFile(this.service.receiveRoot, batchPaths[i]);' in src:
        print('ABORT: 老的每张 deleteFile 仍在')
        sys.exit(1)

    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('OK %s' % REL)
    print('自检: idxBatch.push ✓  toDelete.push ✓  每张落盘已移除 ✓  每张删已移除 ✓')


if __name__ == '__main__':
    main()
