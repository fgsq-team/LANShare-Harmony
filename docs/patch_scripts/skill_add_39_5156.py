#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 harmonyos-arkui-ui-pitfalls skill 追加「三十九、fileIo.accessSync 返回
boolean 而不是抛异常」一节（5.1.56 真凶）。

纪律：sentinel 判重 + 先校验后落盘 + LF。
"""
import io
import os
import sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'
BAK = P + '.bak_20261003_5156'

SENTINEL = '## 三十九、`fileIo.accessSync()` **返回 boolean**，不是抛异常'
HEAD = '\n---\n\n' + SENTINEL

SECTION = """
---

## 三十九、`fileIo.accessSync()` **返回 boolean**，不是抛异常（5.1.56 真凶实录）

### 症状

「按魔数纠正文件后缀」这个功能**连续五版（5.1.51~5.1.55）全都没生效**，
而每 一版的「修法」在逻辑上都对：回写 `item.name`、修等价组、补全所有接收路径……
症状极具欺骗性：**磁盘上、UI 上、消息气泡上，全都看不出任何变化**，
看起来像「改了但没好」，于是继续在下游找原因。

真凶在**最前面那道门**，一行：

```ts
// ❌ 错：以为「不存在会抛异常」
try {
  fileIo.accessSync(target);        // 文件不存在时返回 false，什么都不抛！
  Log.w(TAG, `但目标已存在，放弃`);
  return path;                       // ← 每一次都从这里返回
} catch (e) {
  // 不存在 = 正常，继续改名        // ← 这条分支永远走不到
}
fileIo.renameSync(path, target);     // ← 从来没执行过
```

### SDK 声明（`@ohos.file.fs.d.ts`）

```ts
declare function accessSync(path: string, mode?: AccessModeType): boolean;
// returns: true  = 本地文件且有相应权限
//          false = 文件不存在 / 在云端 / 在分布式设备上
// throws : 401 参数错误、13900012 Permission denied、13900005 I/O error …
// ⚠️ 注意「文件不存在」在【返回值】里，不在【异常】里。
```

### 正解

```ts
let exists: boolean = false;
try {
  exists = fileIo.accessSync(target);   // 用返回值判
} catch (e) {
  exists = false;   // 查不到就当作不存在，交给 renameSync 裁决
}
if (exists) { /* 换名/放弃 */ }
```

### 三条可迁移纪律

1. ★★★ **「文件存在性判断」必须按 SDK 声明的语义写** ——
   `accessSync` 返回 boolean、`access` 抛异常，两个API **名字只差一个字母、
   语义完全相反**。⇒ 拿不准就去 `ets/api/@ohos.file.fs.d.ts` 搜声明，
   **不要凭直觉**。同一 SDK 里返回型与抛异常型 API 混用极常见
   （`mkdirSync`/`accessSync` 返回、`openSync`/`unlinkSync` 抛）。

2. ★★★★ **改「存在性判断」这类门之后，必须验「被保护的那行代码真的执行了」** ——
   本次 `renameSync` 后面本来就有成功日志，但**没人去看**。
   ⇒ **动作：grep 被门挡住的调用点 + 在真机日志里搜它的成功串，确认 HIT。**
   一个「静默 return」的门可以 让下游五个版本全部白改而毫无察觉。

3. ★★★★ **同一个 SDK 语义，全工程扫一遍，只有一处写反 = 强信号** ——
   本工程另外 6 处（`HttpRouter` ×3、`LanService` ×2、`dedupeName` ×1）
   **全都用返回值判**，只有新写的那一处反了。
   ⇒ ★ **动作：写新的平台 API 调用时，grep 全工程同款用法对齐写法；
     写完再 grep 一遍「同款 API 是否有两种写法并存」。**
   不一致的位置就是 bug 的位置。

⚠️ 附带一条：**「目标已存在就放弃改名」本身也是设计缺陷** ——
放弃 ⇒ 同名文件第二次接收时又是非图片 ⇒ 又一次「不弹存相册框」，
等于把同一个 bug 换个入口复现。⇒ 需要保住不变量（「纠错后后缀必然正确」）时，
应**递增去重**（`base (2).jpg`）而不是放弃。
"""


def main():
    s = io.open(P, 'r', encoding='utf-8').read()
    if SENTINEL in s:
        print('ALREADY APPLIED')
        return 0
    assert SENTINEL not in s
    # 先构造后落盘
    s2 = s.rstrip('\n') + '\n' + SECTION
    assert SENTINEL in s2
    assert s2.count(SENTINEL) == 1
    if not os.path.exists(BAK):
        os.replace(P, BAK) if False else None
        import shutil
        shutil.copy2(P, BAK)
        print('  备份 -> %s' % BAK)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK skill 已追加第三十九节')
    return 0


if __name__ == '__main__':
    sys.exit(main())