#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 5.1.56 的结论追加到当日日志（幂等 sentinel + LF）。"""
import io
import sys

P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
SENTINEL = '## 5.1.56 —— 「魔数纠错五版从未真正改名」的最终真凶'

NOTE = """

---

## 5.1.56 —— 「魔数纠错五版从未真正改名」的最终真凶

### 一、症状

vivi 实测：**「还是不行，加后缀没有成功，都没有弹保存相册的弹窗」**
（测试文件 `abc.1`，内容是 jpg）。

### 二、真凶：一行SDK 语义误用

`fileIo.accessSync(path, mode?): boolean` ——
**文件不存在时返回 `false`，不抛异常**（"不存在"写在 `@returns` 里，不在 `@throws` 里）。

而 `MagicType.fixExtByMagic` 写成了：

```ts
try {
  fileIo.accessSync(target);       // 返回 false，**什么都不抛**
  Log.w(TAG, `但目标已存在，放弃`);
  return path;                      // ← 每一次都从这里返回
} catch (e) { /* 不存在 = 正常 */ } // ← 永远走不到
fileIo.renameSync(path, target);    // ← 从未执行
```

⇒ **`renameSync` 从 5.1.51 引入那天起，一次都没被调用过。**

**同工程另外 6 处（`HttpRouter`×3 / `LanService`×2 / `dedupeName`×1）
全部用返回值判，只有这一处反了** ⇒ 「只有一处不一致」本身就是定位信号。

### 三、为什么连相册弹窗都没有（同一个根因的连招）

```
renameSync 从未执行
  → 文件名仍是 abc.1
  → isImageName() 判不出图片
  → mediaNamesOf() 返回空数组
  → autoSaveNewMedia 第 4136 行 `if (this.mediaNamesOf(m).length === 0) continue;`
  → 压根不入队 ⇒ 弹窗不可能出现
```

⇒ ★ **两个看似无关的症状（后缀没改 + 没弹窗）其实是同一条因果链**，
这给了「不用真机也能定位」的确定性。

### 四、为什么连错五版（教训）

5.1.51~5.1.55 每一版的「修法」在逻辑上都是对的：
等价组（51）、双扩展名（52）、边界口径（53/54）、回写 `item.name`（55）……
**全都在改下游，而真凶在���前面那道门。**
⇒ 「改了但没好连着两轮」的老纪律这次的表现形式是：
**每一版都能自圆其说 ⇒ 不触发警报 ⇒ 一直往错的方向深挖。**
★ **新增一条判据：改「某个功能为什么没生效」时，
第一件事是去 SDK 声明里核对该 API 的真实语义（返回值 vs 异常），
而不是先假设自己上一步改对了。**

### 五、本轮改动

| 文件 | 改动 |
|---|---|
| `FileStorage.ets` | `accessSync` 判据改用返回值；「目标已存在」不再放弃改名，改**递增去重** `base (2).jpg` |
| `FileTransfer.ets`（v4 路径） | 补回写 `item.name` + `names[i] = items[i].name`（5.1.55 在 V5侧修了，这条平行路径漏了） |
| `Index.ets` / `app.json5` | 发版体检：`ABOUT_FALLBACK_VER` + `versionCode` → 5.1.56 |

⚠️ **「目标已存在 ⇒ 放弃改名」本身也是设计缺陷**：放弃 ⇒ 同名文件第二次接收
又是非图片 ⇒ 又一次「不弹相册框」= 把同一个 bug 换个入口复现。
⇒ **递增去重才能保住不变量「纠错后后缀必然正确」。**

### 六、验证与交付

- `BUILD SUCCESSFUL`（58s）；补丁脚本均验过幂等（重跑 `ALREADY APPLIED`）
- 解包 HAP 按 **UTF-8 字节**验：新串 `魔数纠错` / `v4 改名回写` / `的候选名都被占用` 全 HIT，
  旧串 `但目标已存在，放弃` **MISS**（确认已消失），`5.1.56` HIT
- HAP **2610432 B**；commit `61bae7e` + tag `v5.1.56`
- 设备 hdc 仍**离线** ⇒ 未推送；skill `harmonyos-arkui-ui-pitfalls` 已追加**第三十九节**
"""


def main():
    s = io.open(P, 'r', encoding='utf-8').read()
    if SENTINEL in s:
        print('ALREADY APPLIED')
        return 0
    s2 = s.rstrip('\n') + '\n' + NOTE
    assert s2.count(SENTINEL) == 1
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK 当日日志已追加 5.1.56')
    return 0


if __name__ == '__main__':
    sys.exit(main())