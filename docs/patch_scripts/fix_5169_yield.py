#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.1.69：存相册主循环「每张让帧」（幂等）

## 实测（vivi 2026-10-05 14:53~14:54，5.1.68 真机）
- 5.1.68 修好了残留：`放弃等待落盘 0`、零失败、
  且日志出现 `mmexport1451229174391(2) | mmexport1451229174391` 同批
  ⇒ 5.1.68 的 `exact/loose` 双池生效（两份同名都拿到了自己的文件）。
- 接收收尾很快：`已接收 426 项` → `本次入队 426 项` → `准备弹存相册确认框`
  **只花 0~1 秒** ⇒ 「接收到最后一张卡」这条**已解决**。
- ★ 但「保存相册卡」仍在：每批 `确认框返回 → 完成` = **3~4 秒 / 40 张**
  （第一批 10s 含额外开销）。

## 根因：主循环内**一次都不让帧**
```ts
for (let j = 0; j < gotUris.length; j++) {
  await ExportService.copyTo(...);        // 异步拷贝
  const thumb = await this.cacheThumb(...); // 完整解码 + rotate + pack 写 jpg
  idxBatch.push(...); toDelete.push(...);
}
```
循环**外面**有一次 `yieldOnce()`，**循环内 40 张连续做**：
每张 = 一次 64KB 分块异步拷贝 + 一次完整图片解码 + 一次 pack 写文件。
⇒ 主线程连续被占 3~4 秒 ⇒ **界面全冻**（用户感知就是「卡」）。
⚠️ 这些 IO **本身已经是异步的**（A3 已改），但「连续 40 次 await」之间
   没有主动让帧 ⇒ ArkUI 拿不到渲染机会。

## 修法
循环内**每 THUMB_YIELD_EVERY 张让一帧**，把单次连续占用压到 N 张的量。
★ 判据同 5.1.66 C1（探测循环内让帧）—— 那是「切消息页卡」，
  这次是「存相册卡」，**同一个病（长循环不让帧）在两条路径上**。

## 为什么不用「每张都让帧」
每张都 `yieldOnce`（setTimeout 30ms）⇒ 40 张 = 至少 1.2 秒纯等待，
反而更慢。**每 5 张让一次**：单次连续占用从 3.5s 降到 ~0.5s，
总耗时增加不超过 0.2s（8 次 × 30ms），但界面全程可响应。
"""
import io
import os
import sys

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

PROBE = '5.1.69'
REL = 'entry/src/main/ets/pages/Index.ets'

# ---- 1) 加常量 ----
OLD1 = "  private static PROBE_YIELD_EVERY: number = 20;"
NEW1 = """  private static PROBE_YIELD_EVERY: number = 20;

  /**
   * ★★ 5.1.69：存相册主循环**每处理多少张让一帧**。
   *
   * 背景（vivi 2026-10-05 真机 426 张）：`确认框返回 → 完成` = **3~4 秒 / 40 张**。
   * 根因：循环内 `await copyTo` + `await cacheThumb`（完整解码 + rotate + pack）
   * **连续 40 次，中间一次都不让帧** ⇒ 主线程被占满 3~4 秒 ⇒ 界面全冻。
   *
   * 取 5 的理由：
   * - 每张都让（`yieldOnce` 是 setTimeout 30ms）⇒ 40 张至少多等 1.2 秒，**更慢**；
   * - 每 5 张让 ⇒ 单次连续占用从 ~3.5s 压到 ~0.5s，
   *   总耗时只多 8×30ms = 0.24s，但界面全程可响应。
   * ★ 与 `PROBE_YIELD_EVERY`（探测循环，20 张/次）是**同一个病的两条路径**。
   */
  private static ALBUM_YIELD_EVERY: number = 5;"""

# ---- 2) 循环内让帧 ----
OLD2 = """      for (let j: number = 0; j < gotUris.length; j++) {
        const i: number = idxs[j];
        // 5.0.47：单文件失败（copyTo/cacheThumb 抛异常）不再中断整批
        try {"""
NEW2 = """      // ★★ 5.1.69：**循环内**周期性让帧。
      //   原来循环外有一次 `yieldOnce()`，循环内 40 张连续做
      //   （每张 = 一次分块异步拷贝 + 一次完整解码 + 一次 pack 写文件）
      //   ⇒ 主线程连续被占 3~4 秒 ⇒ 界面全冻（vivi 2026-10-05 实测）。
      //   ⇒ 每 ALBUM_YIELD_EVERY(5) 张让一帧，单次连续占用压到 ~0.5 秒。
      let sinceYield: number = 0;
      for (let j: number = 0; j < gotUris.length; j++) {
        const i: number = idxs[j];
        sinceYield += 1;
        if (sinceYield >= Index.ALBUM_YIELD_EVERY) {
          sinceYield = 0;
          await Index.yieldOnce();
        }
        // 5.0.47：单文件失败（copyTo/cacheThumb 抛异常）不再中断整批
        try {"""


def main():
    path = os.path.join(ROOT, REL)
    src = io.open(path, 'r', encoding='utf-8', newline='').read()

    if PROBE in src:
        print('SKIP 已应用')
        return

    for old, new, tag in ((OLD1, NEW1, '常量'), (OLD2, NEW2, '循环')):
        if src.count(old) != 1:
            print('ABORT %s count=%d' % (tag, src.count(old)))
            sys.exit(1)
        src = src.replace(old, new, 1)

    # 语义自检
    checks = [
        ('private static ALBUM_YIELD_EVERY: number = 5;', '常量'),
        ('let sinceYield: number = 0;', '计数变量'),
        ('if (sinceYield >= Index.ALBUM_YIELD_EVERY) {', '让帧判断'),
        ('await Index.yieldOnce();', '让帧调用'),
    ]
    for s, tag in checks:
        if s not in src:
            print('ABORT 自检失败(%s): %s' % (tag, s))
            sys.exit(1)
    if PROBE not in src:
        print('ABORT 探针未命中')
        sys.exit(1)

    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('OK %s' % REL)
    print('自检: ALBUM_YIELD_EVERY ✓  sinceYield ✓  让帧判断 ✓  yieldOnce ✓')


if __name__ == '__main__':
    main()
