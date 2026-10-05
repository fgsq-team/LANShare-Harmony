# -*- coding: utf-8 -*-
"""
v5.1.24 —— 修「网页上传只有 17MB/s + 进度条超级卡」（真机观测驱动）

## vivi 提供的决定性对照
| 路径 | 速度 |
|---|---|
| **安卓 1.35 → 鸿蒙**（V5 协议接收）| **50 MB/s** ✅ |
| **网页 → 鸿蒙**（HTTP multipart 接收）| **17 MB/s** ❌ |
| 安卓接收（不论鸿蒙发还是网页发）| 50 MB/s |

⇒ **同一台鸿蒙设备，V5 接收 50M、HTTP 接收 17M** ⇒ CPU/IO/网络都没问题，
  差的是**接收链路的处理方式**。

## 5.1.23 观测（`[UP]` 30 条采样，每 16MB 一行）
| 段 | 累计 | 占比 |
|---|---|---|
| `read` | 4 ms | **0.01%** |
| `feed`（解析 + 2585 次 `writeSync`）| 409 ms | **1.04%** |
| `other` | — | **~99%** |

## 根因
`onWebUploadProgress`（`LanService.ets:3547`）**每次都 `this.emit()`，无节流**：
```ts
this.snapshot.transferText = ...;
this.snapshot.transferPercent = pct;
this.emit();          // ★ 每次都触发 @State 变化 ⇒ ArkUI 重建整个页面
```
而 HTTP 上传循环里 `yieldFrame()` **每 2MB 一次** ——
让出的那一帧里，ArkUI 要**重建整个页面**（这页面有消息列表/文件网格/气泡），
耗时可达几十上百 ms ⇒ 主线程反复被占满。

★ **对照 V5 接收为什么快**：`onTransferReport`（`LanService.ets:3422`）走的是
  **`this.emitThrottled()`**（5.0.69 起加的节流版）⇒ 上传 50MB/s。
  ★ **同一个 App，V5 接收用节流、网页接收不用** —— 就差这一个词。

## 本版两处改动
1. **`onWebUploadProgress` 改用 `emitThrottled()`**（对齐 V5 接收的既有做法）
   —— 进度仍会更新（终态分支仍用立即版 `emit`，见下面注意点），但不再每次全页重建。
2. **进度节流参数放宽**：`UPLOAD_PROGRESS_MIN_MS` 200 → **1000**、
   `UPLOAD_PROGRESS_MIN_BYTES` 256KB → **4MB**
   ⇒ UI 重建频率降 16 倍（646MB 从 ~2500 次降到 ~160 次）。

⚠️ **注意点（必须保留立即 emit 的地方）**：
`notifyUploadEnd` 那侧（`onWebUploadEnd`）**仍用立即 `emit()`** ——
否则进度条会停在 99%、浮层不消失（5.0.69 当年踩过这个坑，本版不动它）。

## 不动的地方
- `yieldFrame()` 保留（它让 UI 有机会响应点击，是好东西）
- 落盘/解析路径不动（实测只占 1%）
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'

# ---------------------------------------------------------------- 1. 进度节流放宽
OLD1 = """const UPLOAD_PROGRESS_MIN_MS: number = 200;"""
NEW1 = """/**
 * ★ 5.1.24：200 → **1000**（进度上报的最小时间间隔）。
 *   实测网页上传只有 17MB/s 而 V5 接收有 50MB/s，两者差别在于
 *   网页上传每次上报都 `emit()` ⇒ ArkUI 重建整页（`LanService.onWebUploadProgress`）。
 *   1000ms + 4MB 双条件 ⇒ 646MB 全程只上报约 160 次（原来约 2500 次）。
 */
const UPLOAD_PROGRESS_MIN_MS: number = 1000;"""

OLD1B = """const UPLOAD_PROGRESS_MIN_BYTES: number = 256 * 1024;"""
NEW1B = """/**
 * ★ 5.1.24：256KB → **4MB**（进度上报的最小字节间隔）。
 *   与 `UPLOAD_PROGRESS_MIN_MS` 是**与**关系，两者任一满足即上报；
 *   放宽后重建频率降 16 倍。终态上报不受此限制（`notifyUploadEnd` 走立即版）。
 */
const UPLOAD_PROGRESS_MIN_BYTES: number = 4 * 1024 * 1024;"""

# ---------------------------------------------------------------- 2. emitThrottled
OLD2 = """    this.snapshot.transferPercent = pct;
    this.emit();
  }

  /**
   * 网页上传结束（成功与失败都会来）。"""

NEW2 = """    this.snapshot.transferPercent = pct;
    // ★★ 5.1.24（vivi 12:24 观测驱动）：**立即 emit 改为 emitThrottled**。
    //   原来每次进度上报都 emit ⇒ @State 变化 ⇒ ArkUI **重建整个页面**，
    //   而 HTTP 上传循环每 2MB 让一帧 —— 那一帧里整页重建耗时可观
    //   ⇒ 主线程反复占满 ⇒ 实测网页上传只有 17MB/s，且「进度条超级卡」。
    //
    //   ★ 对照：V5 接收的 `onTransferReport`（本文件 :3422）用的是 **emitThrottled**
    //     （5.0.69 起加的节流版）⇒ 同一台设备 V5 接收能跑 50MB/s。
    //     就差这一个词。
    //
    // ⚠️ **终态必须仍用立即版 emit**（见下面的 `onWebUploadEnd`）——
    //    否则进度条停在 99%、浮层不消失（5.0.69 踩过这个坑，本版不动它）。
    this.emitThrottled();
  }

  /**
   * 网页上传结束（成功与失败都会来）。"""

EDITS = [
    ('entry/src/main/ets/net/HttpRouter.ets', OLD1, NEW1),
    ('entry/src/main/ets/net/HttpRouter.ets', OLD1B, NEW1B),
    ('entry/src/main/ets/service/LanService.ets', OLD2, NEW2),
]

cache = {}

def load(p):
    return io.open(os.path.join(ROOT, p), encoding='utf-8').read()

for path, old, new in EDITS:
    if path not in cache:
        cache[path] = load(path)
    c = cache[path].count(old)
    assert c == 1, 'OLD 命中 %d（应 1）: %s' % (c, path)
    cache[path] = cache[path].replace(old, new, 1)

if '--dry' in sys.argv:
    print('DRY-RUN OK（%d 处）' % len(EDITS))
    raise SystemExit(0)

for _, _, new in EDITS:
    assert '\ufffd' not in new, '新增文本含坏字符'
for path, s in cache.items():
    assert '\r\n' not in s, 'CRLF: ' + path
    io.open(os.path.join(ROOT, path), 'w', encoding='utf-8', newline='\n').write(s)
    print('  已写 %s' % path)
print('APPLIED')
