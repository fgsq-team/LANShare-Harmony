#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 5.1.59（推送路径单文件直推）+「漏副本」教训写进记忆（幂等 + LF）"""
import io
import sys

LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'

S_LOG = '## 5.1.59 —— 推送路径的单文件直推（5.1.58 修错了地方）'
S_MEM = '⚠️ **只 grep 函数名（`downloadFile`）会漏** —— 两处函数名不同但行为相同。'

NOTE = """

---

## 5.1.59 —— 推送路径的单文件直推（5.1.58 修错了地方）

### 一、症状

vivi 实测：「手机浏览器单个文件还是会打包，不要让发送到网页的文件保存在沙箱里」
⇒ 5.1.58 已改、已上传，但**现象完全没变**。

### 二、真凶：同一个逻辑有两处副本，我只改了一处

| 文件 | 函数 | 触发方 | 5.1.58 是否改|
|---|---|---|---|
| `js/lanshare.min.js` | `downloadFile()` | **网页端自己**勾选文件后点下载 | ✅ 改了 |
| `js/lanshareChat.min.js` | `autoDownloadFiles(b)` | **鸿蒙端主动推送**（WebSocket `PUSH_FILES`） | ❌ **漏了** |

vivi 说的「**发送到网页**」= 鸿蒙端推送 ⇒ 命中的是**漏掉的那条**。
两个函数都无条件 `POST /compressFiles`，所以推送 1 个文件也照样先在
`cacheDir/webzip/` 生成 zip（保留 30 分钟）⇒ **正是他不想出现的「存在沙箱里」**。

### 三、修法（ArkTS 零改动）

★ **服务端早就推了 `names`**（`LanService.ets:4115`：
`{"cmd":3,"list":[路径…],"names":[文件名…]}`，**与 list 同序**），
只是网页端一直没用 ⇒ 只需改JS 读 `b.names[0]`。

```
b.list.length === 1 且拿到 names[0]
  ⇒ location.href = /file/<names[0]>?path=<list[0]>&token=…   （直推，零打包零落盘）
否则
  ⇒ 仍走 /compressFiles
```

⚠️ **兜底不可省**：`names` 缺失（老版本鸿蒙端只推 list）时**必须回退到打包**，
否则会退化成请求 `/file/undefined`。

### 四、验证（13/13 PASS）

`docs/patch_scripts/verify_web_push_5159.js`（node + 桩）：
单文件直推 URL 正确 / 多文件仍打包 / **无 names 回退打包** / 空列表无动作 /
names 空数组回退。语法另用 `vm.Script` 校验整个 chat JS。

### 五、教训（这条最值钱）

★★ **同一个「行为」在工程里有**多处副本**时，只改一处 ⇒ 现象完全不变，
而且很容易误判成「改了没生效」而去查缓存/查打包。**
⇒ ★ **动作：改某个「行为」前，grep 该行为的**契约关键字**（这里是
`/compressFiles`、`/downloadZipFile`）全工程扫一遍**，列出所有副本做成清单再逐个改。
本项目两个 JS 都调同一个 `/compressFiles`，只查 `downloadFile` 这个函数名就会漏。
⇒ 这与 MEMORY 里「新增一条处理路径要覆盖平行路径」是**同一条铁律的另一面**：
那次是「入口漏接」，这次是「**同一行为的两份实现只改了一份**」。
"""

MEM_ADD = """
## ★ 网页端「打包下载」逻辑在工程里有**两处副本**（5.1.59 血的教训）
- ★★ **同一个「行为」存在多处实现时，只改一处 ⇒ 现象完全不变**，
  且极易误判成「改了没生效」⇒ 去查缓存、查打包，白排查。
  5.1.58 改了 `lanshare.min.js` 的 `downloadFile()`（网页端自己勾选下载），
  5.1.59 才发现vivi 说的是 `lanshareChat.min.js` 的 `autoDownloadFiles()`
  （鸿蒙端经 WebSocket `PUSH_FILES` 推送）—— **两个都无条件 `POST /compressFiles`**。
- ★★ **动作：改某个「行为」前，用它的「契约关键字」全工程扫**
  （本例是 `/compressFiles` / `/downloadZipFile` 两个**接口路径**，不是函数名）
  ⇒ 列出所有副本做成清单再逐个改。
  ⚠️ **只 grep 函数名（`downloadFile`）会漏** —— 两处函数名不同但行为相同。
- ★ 这是「新增处理路径要覆盖平行路径」那条铁律的**另一面**：
  那次是**入口漏接**，这次是**同一行为的两份实现只改了一份**。根子相同：**要有清单，别靠记忆**。
- ★ **ArkTS 侧常已备好数据，只是前端没读**：推送 JSON 里早就带了 `names`（与 `list` 同序，
  `LanService.ets:4115`）⇒ 修前端零改后端。**改前端前先确认后端到底推了什么。**
- ⚠️ **兜底不可省**：对端版本更老时字段可能缺失 ⇒ 必须回退到原路径，
  否则会退化成请求 `/file/undefined` 这类坏 URL。
- ★ **网页端 JS 改动必须做两层验证**（本项目已固化）：
  ① `node -e "new vm.Script(src)"` 验语法（错了直接白屏）；
  ② node + 最小 DOM 桩**跑真实函数**验行为（本例 12/12、13/13）。
  ⚠️ 桩的坑：jQuery `.each` 回调是 `function(index, element)`，**element 是第二个参数**，
  且代码里还会 `$(element)` 再包一次 ⇒ 桩的 `$()` 必须能认出「这个参数就是那个元素」。
- ⚠️⚠️ **验证脚本绝不能放 `entry/src/main/resources/rawfile/web/js/`** ——
  那是静态资源目录，会被打进 HAP（浏览器能直接访问到测试脚本）。放`docs/patch_scripts/`。
"""


def append_once(path, sentinel, text):
    s = io.open(path, 'r', encoding='utf-8').read()
    if sentinel in s:
        print('ALREADY: %s' % path)
        return False
    s2 = s.rstrip('\n') + '\n' + text
    assert s2.count(sentinel) == 1
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK 追加 -> %s' % path)
    return True


def main():
    append_once(LOG, S_LOG, NOTE)
    append_once(MEM, S_MEM, MEM_ADD)
    return 0


if __name__ == '__main__':
    sys.exit(main())