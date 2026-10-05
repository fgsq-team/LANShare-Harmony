#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.68 根因验证：stripDedupeSuffix 让「两份同名不同容」的文件互相串台

vivi 2026-10-05 14:41 复测 5.1.67：沙箱仍残留 15 张，1+3+11=15 全是「放弃等待落盘」。

## 铁证（真机日志 + 设备 ls）
- 清单 426 项，其中 28 项带 `(2)` 后缀（内容与原名**完全相同**，size 一致）
  例：`清单[241] size=14210 "X(2).jpg"` 与 `清单[242] size=14210 "X.jpg"`
- 落盘名 28 个 `X(2).jpg`（`v5 "X(2).jpg" 收尾已回`）
- 沙箱「图片」目录残留 **15 个，全部是「原名那份」，且全部有 `(2)` 配对**
- 存相册提交 title 里 **只有 34 个带 `(2)`**（不是 28×N，说明处理过）

## 机制
`recvPathFor(name, k, msgTimeMs)`：
```ts
if (f.name === name || Index.stripDedupeSuffix(f.name) === name) { cands.push(f); }
```
而 `stripDedupeSuffix('X(2).jpg') === 'X.jpg'`。

⇒ 查 `X.jpg` 时，**两份都被收进 `cands`** = [X.jpg, X(2).jpg]
⇒ 两份各自是**独立的单文件消息**，`k` 都是 0
⇒ 都取 `cands[0]` = **同一个文件**
⇒ 一份被 `copyTo` + 删沙箱，另一份的 `recvPathFor` 拿到的是**已删的路径**
⇒ `p.length` 看似有值但文件已不在 ⇒ 下一轮 stat 失败 ⇒ 「未解析出路径」
   ⇒ 重试 6 次 / 60 秒后「放弃等待落盘」⇒ **固定丢一批**

## 为什么数量是 15 附近而不是 28
`(2)` 对里，**哪一份进相册取决于 cands 排序**（按 |文件时间 - 消息时间| 就近）。
两页消息时间几乎相同 ⇒ 谁在 `cands[0]` 不确定 ⇒ 每轮测试残留的具体文件不同
（14:30 那轮剩 14 个、14:41 这轮剩 15 个，文件名单也不同）。

## 修法方向
`recvPathFor` 的 `stripDedupeSuffix` 匹配是为了兼容「协议名 vs 落盘名带去重后缀」，
但它让**真·同名**的两份互相串台。
⇒ 匹配必须**先精确、再退化**，且退化时**只接受「本条消息自己落下的那个」**。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = '5.1.68'
REL = 'entry/src/main/ets/pages/Index.ets'

OLD = """  private recvPathFor(name: string, k: number, msgTimeMs: number): string {
    const cands: ReceivedFile[] = [];
    for (let i: number = 0; i < this.receivedFiles.length; i++) {
      const f: ReceivedFile = this.receivedFiles[i];
      if (f.name === name || Index.stripDedupeSuffix(f.name) === name) {
        cands.push(f);
      }
    }"""

NEW = """  private recvPathFor(name: string, k: number, msgTimeMs: number): string {
    // ★★ 5.1.68：拆成「精确匹配」与「退化匹配」**两个候选池**。
    //
    // ## 为什么（vivi 2026-10-05 真机：426 张里固定残留 15 张在沙箱）
    //   原实现是 `f.name === name || stripDedupeSuffix(f.name) === name`，
    //   而 `stripDedupeSuffix('X(2).jpg') === 'X.jpg'`。
    //   PC 端发来的这批里**有 28 对「同名但内容相同」的文件**：
    //     清单[241] size=14210 "X(2).jpg"  ≡  清单[242] size=14210 "X.jpg"
    //   两份**各自是独立的单文件消息**，`k` 都是 0。
    //   ⇒ 查 `X.jpg` 时两份都被收进同一个 `cands`
    //   ⇒ 都取 `cands[0]`（同一个文件）
    //   ⇒ 一份被 copyTo + 删沙箱，另一份拿到的是**已删的路径**
    //   ⇒ stat 失败 ⇒「未解析出路径」⇒ 重试 6 次/60 秒 ⇒「放弃等待落盘」
    //   ⇒ **每轮固定丢一批**（14:30 丢 14 个、14:41 丢 15 个，名单还不同）
    //
    // ## 修法
    //   精确命中优先：只有 `f.name === name` 的才算「同名同容的候选」。
    //   退化匹配（剥掉去重后缀）**仅在没有精确命中时使用**，用于兼容
    //   「协议原始名 vs 落盘时被 dedupeName 改成 X (2).jpg」的单份场景。
    //   ⇒ 两份同名时**不再互相串台**：查 X.jpg 只命中 X.jpg。
    const exact: ReceivedFile[] = [];
    const loose: ReceivedFile[] = [];
    for (let i: number = 0; i < this.receivedFiles.length; i++) {
      const f: ReceivedFile = this.receivedFiles[i];
      if (f.name === name) {
        exact.push(f);
      } else if (Index.stripDedupeSuffix(f.name) === name) {
        loose.push(f);
      }
    }
    // 精确命中优先；没有才退化（loose 已被设计成「至多一份」）
    const cands: ReceivedFile[] = exact.length > 0 ? exact : loose;"""


def main():
    path = os.path.join(ROOT, REL)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()

    if PROBE in src:
        print('SKIP 已应用')
        return

    if src.count(OLD) != 1:
        print('ABORT count=%d' % src.count(OLD))
        sys.exit(1)

    src = src.replace(OLD, NEW, 1)

    # 语义自检
    if 'const cands: ReceivedFile[] = exact.length > 0 ? exact : loose;' not in src:
        print('ABORT: cands 三元未写入')
        sys.exit(1)
    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)

    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('OK %s' % REL)
    print('自检: exact/loose 双池 ✓  cands 三元 ✓')


if __name__ == '__main__':
    main()
