#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 harmonyos-arkui-ui-pitfalls skill 追加「四十、ArkTS import 必须连续 + 契约变更审计入口守卫」

起因（5.1.60）：
  ① 在 import 区中间插入类定义 ⇒ `arkts-no-misplaced-imports`（10605150）
  ② 函数调用契约从「传 paths」变成「传 uris」，主分支改了但**入口守卫没改**
     ⇒ 新路径第一行就被 `if (!paths.length) return` 短路，是**跑真实函数的
        验证脚本**抓到的，否则一路带到真机。
"""
import io
import os
import shutil
import sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'
BAK = P + '.bak_20261003_5160'
SENT = '## 四十、ArkTS：`import` 必须**全部连续**，且「契约变更」要重审入口守卫'

SECTION = """
---

## 四十、ArkTS：`import` 必须**全部连续**，且「契约变更」要重审入口守卫（5.1.60 实录）

### 1. 在 import 区中间插入任何声明 ⇒ 后续 import 全部报错

```ts
import { A } from './A';
                    // ← 这里插了一个 export class X { }
import { B } from './B';   // ❌ ArkTS:10605150 arkts-no-misplaced-imports
```

**报错文案**：`"import" statements after other statements are not allowed
(arkts-no-misplaced-imports)`，位置指向**第一个被挤下来的 import**。

⇒ ★ **动作：新增类/常量/函数必须插在「最后一个 import 之后」，
不能插在某个 import 中间。** 补丁脚本里若按「某个 import 行」当锚点插入声明，
几乎必然踩这个坑——**锚点要选 import 区**结束**之后的那一行**
（本例是 `const TAG: string = ...`）。

### 2. ⚠️★ 「改了主分支」不等于「改了函数」—— 入口守卫也是改动面

**症状**：某功能的正向分支已经改对，但**线上完全不生效**，而所有局部检查都通过。

**本例**：把某个推送函数从「传 `paths`（沙箱路径数组）」改成
「传 `uris`（授权 URI）」，新分支和调用点都改对了，
但函数第一行还有上一版的守卫：

```ts
function autoDownloadFiles(paths, names, uris) {
    if (!paths || paths.length === 0) { return }   // ← 新路径不带 paths！
    if (!paths && uris && names.length === 1) { /* 新路径 */ }
    // ⚠️ 新路径在这一行就被短路了，永远走不到下面
}
```

⇒ 新形态**不传旧参数**，于是第一行就 return。

⇒ ★★★★ **纪律：函数签名或调用契约一变（尤其是「少传一个参数」），
必须回头审计函数内所有 `param.length` / `!param` / `if (!x) return`——
每一个都是入口守卫。**
这与「给函数加带默认值的新参数要查四层」同源：
**契约一变，依赖旧契约的判据全部要重审。**

⇒ ★★ **这类 bug 只有「跑真实函数」才抓得到**（读代码会觉得"对啊"）：
本例靠 node + 最小桩跑真实函数（用例是「paths 为空、只有 uris」）当场抓到，
否则会一路带到真机、表现为「改了没生效」，极易误判为要清缓存/重编。
"""

def main():
    s = io.open(P, 'r', encoding='utf-8', newline='').read()
    if SENT in s:
        print('ALREADY APPLIED')
        return 0
    s2 = s.rstrip('\n') + '\n' + SECTION.replace('\n', '\n')
    assert s2.count(SENT) == 1
    if not os.path.exists(BAK):
        shutil.copy2(P, BAK)
        print('  备份 -> %s' % BAK)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK skill 已追加第四十节')
    return 0


if __name__ == '__main__':
    sys.exit(main())