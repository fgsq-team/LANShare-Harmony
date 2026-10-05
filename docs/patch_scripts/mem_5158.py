#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 5.1.58（网页端单选直推）记入当日日志，并纠正 MEMORY.md 里一处**说错的话**。

⚠️ 纠正内容：MEMORY.md 旧第 13 条写的是「UTD 也做不到 / 别再找 UTD」——
   那是**我基于错误理解下的结论**（误以为 `getUniformDataTypeByMIMEType` 的
   `belongsTo` 参数必填、构成循环依赖）。vivi 2026-10-03 已纠正：
   SDK 签名是 `(mimeType: string, belongsTo?: string): string` —— **带 `?` 真可选**，
   不传就按 MIME 直接查，**没有循环依赖**。⇒ 该条必须改，否则会误导后续判断。
"""
import io
import sys

LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'

S_LOG = '## 5.1.58 —— 网页端「单选直推原文件」'
S_FIX_OLD = '14. ★★ **「统一命名」要以「系统最终产物」为准，而不是自己另发明一套**（5.1.57）'
S_MEM_UTD = '## ★ UTD（`@ohos.data.uniformTypeDescriptor`）—— 我曾误判，vivi 已纠正'

NOTE = """

---

## 5.1.58 —— 网页端「单选直推原文件」（不打包、不落沙箱）

### 一、问题

vivi 问「为什么发送到网页的图片和文件会被打包成zip」。

**根因在网页端 JS（`web/js/lanshare.min.js` 的 `downloadFile()`）**：
它**无条件** `POST /compressFiles` ⇒哪怕只勾选 1 个文件，
也会先在 `cacheDir/webzip/` 生成一个 zip（`LANShare-<t>-<rand>.zip`，保留 30 分钟），
再让浏览器 `location.href=/downloadZipFile?tempFile=…` 去取。
⇒ **违反了「不希望在沙箱里存一份」**。

三个下载入口的分工（原本就分开的）：
| 入口 | 函数 | 行为 |
|---|---|---|
| 文件页勾选+下载 | `downloadFile()` → `/compressFiles` | 打包 zip |
| 媒体页勾选+下载 | `downloadMedia()` → `/compressMedias` | 打包zip（**本项目未实现**，`HttpRouter.ets:22` 标注无媒体库） |
| 单文件右键下载 | `location.href=/file/<名>?path=…` | 直推原文件 |

### 二、改法（vivi 选 A 方案）

**只改 JS，ArkTS 零改动** —— `/file/<名>?path=…&token=…` 本就完备（支持 Range +
正确的 `Content-Disposition`）。新逻辑：

```
勾选 1 个  ⇒ location.href = /file/<名>?path=…&token=…   （直推，零打包、零落盘）
勾选 ≥2 个 ⇒ 仍走 /compressFiles（浏览器不能一次下多个文件）
```

⚠️ **为什么单选用 `location.href` 而不是 `window.open`**：
右键「打开」用 `window.open(_blank)`（新标签页**预览**），
而「下载」要触发浏览器下载 ⇒ 必须用 `location.href`。

⚠️ **文件名从 `.file-item-name` 取**：列表项 `<div file-path=…>` 上**没有**
`file-name` 属性（只有 media 的右键菜单用 `file-name`/`path`）。
并额外挡掉「有勾选框但取不到文件名」的畸形项 ⇒ 防止请求 `/file/undefined`。

★ 顺手修掉一个原代码 bug：旧 `downloadFile()` 里 `filePath = $(b).attr(...)`
**漏了 `var`** ⇒ 写进隐式全局（同名变量跨目录串台）。

### 三、验证（这次做得很足，12/12 PASS）

`docs/patch_scripts/verify_web_single_5158.js` —— **node 里用最小 DOM 桩
跑真实的 `downloadFile()`**（不是读代码"觉得对"）：
单选直推 URL 正确 / 多选仍打包 / 未勾选有提示 / 畸形项被挡 / 无 loading 遮罩。
⚠️ 桩的坑：jQuery `.each` 回调是 `function(index, element)`，
   **element 是第二个参数**，且代码里还会 `$(element)` 再包一次
   ⇒ 桩的 `$()` 必须能认出「这个参数就是那个元素」。

⚠️⚠️ **验证脚本不能放在 `rawfile/web/js/` 下** —— 那里是静态资源目录，
会被打进 HAP（浏览器能直接访问到测试脚本）。已移到 `docs/patch_scripts/`。

### 四、vivi 的另一条指示

「网页端的列表里选择在鸿蒙端不适用，因为不能直接访问本地，鸿蒙端这个功能不用做」
⇒ **不做**鸿蒙端的「勾选文件推网页」。本轮只改网页端。
"""

MEM_FIX_UTD = """
## ★ UTD（`@ohos.data.uniformTypeDescriptor`）—— 我曾误判，vivi 已纠正（5.1.58）
- ⚠️⚠️ **我之前的结论是错的**：「UTD 的 `belongsTo` 参数必填 ⇒ 构成循环依赖 ⇒ 用不了」——
  vivi 2026-10-03 纠正，SDK 签名证实他是对的：
  `getUniformDataTypeByMIMEType(mimeType: string, belongsTo?: string): string`
  —— **`belongsTo` 带 `?` 是真可选**，不传就按 MIME 直接查，**没有循环依赖**。
- ★ **误解的根源：`belongsTo` 是两个不同的东西**
  | 形态 | 声明 | 语义 |
  |---|---|---|
  | **方法** | `TypeDescriptor.belongsTo(type: string): boolean` | 在**已拿到的描述符**上判断归属；`type` **必填**（省略 ⇒ 401） |
  | **可选参数** | `getUniformDataTypeBy*(name, belongsTo?)` | 查询时顺带过滤；**可选** |
  我把这两者混成一个了。
- ✅ **正确用法（vivi 给的路径，无循环）**：
  `probe()` 得到 MIME → `getUniformDataTypeByMIMEType('image/jpeg')`
  → 拿到 `general.jpeg` → `getTypeDescriptor()` → `.belongsTo('general.image')`。
  更简洁：`getUniformDataTypeByMIMEType('image/jpeg', 'general.image')` 一句搞定。
- ⚠️ **接 UTD 前必须知道的三件事**（文档措辞）：
  ① 查不到时返回**动态生成的 UTD ID，不是 `null`**（单数版）
     ——与复数版 `getUniformDataTypesBy*` 的描述不一致 ⇒ **不能靠「空」判失败**；
  ② 入参要**完整 MIME**（`image/jpeg`），而 `MagicType.probe()` 返回**裸扩展名**（`jpg`）
     ⇒ 还需一张 扩展名→MIME 映射表；
  ③ `@syscap SystemCapability.DistributedDataManager.UDMF.Core`。
- ★ **UTD 的增量价值有限**（当前判断，非定论）：它只提供 `filenameExtensions`
  （官方推荐后缀），而这正是 `MagicType.EQUIV_EXTS`（19 组）已在做的事；
  且**它本质仍是「后缀↔类型」映射**，而我们判类型用的是**魔数（读内容）**，比它更可信
  （`abc.1` 这种文件名它照样判不出）。⇒ 若接入，**只替换 `EQUIV_EXTS` 一处**，风险面最小。
- ★ **教训：「同名不同层」的东西必须分开看** —— 我因为把「同名方法」和「同名可选参数」
  当成一个东西，得出了「有循环依赖、用不了」的错误结论，并写进了记忆。
  ⇒ **凡是因为「看起来像死结」而排除某个方案，先去 SDK 声明里核对签名**
  （同一SDK 里返回型/抛异常型 API 混用极常见，参见 `accessSync` 那条）。
"""

MEM_FIX_LIST = (
    '13. ★★★★ **「这个文件到底是什么类型」⇒ 读文件头魔数，别信扩展名**'
    '（含 UTD：它本质也是「后缀↔类型」映射，后缀错了照样判错）。'
)


def append_once(path, sentinel, text):
    s = io.open(path, 'r', encoding='utf-8').read()
    if sentinel in s:
        print('ALREADY: %s' % path)
        return False
    s2 = s.rstrip('\n') + '\n' + text
    assert s2.count(sentinel) == 1, 'sentinel 计数异常'
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK 追加 -> %s' % path)
    return True


def main():
    append_once(LOG, S_LOG, NOTE)
    # 纠正 MEMORY.md 里那句错误结论（去掉「UTD 也做不到」的暗示，改为指向纠正面）
    s = io.open(MEM, 'r', encoding='utf-8').read()
    if S_MEM_UTD in s:
        print('ALREADY: MEMORY.md（UTD 纠正已存在）')
    else:
        assert MEM_FIX_LIST in s, '找不到待纠正的 MEMORY 条目'
        s2 = s.replace(MEM_FIX_LIST, S_MEM_UTD.strip() + '\n\n- ★★ '
                      '**「这个文件到底是什么类型」⇒ 读文件头魔数，别信扩展名**'
                      '（含 UTD：它本质也是「后缀↔类型」映射，后缀错了照样判错）')
        s2 = s2.rstrip('\n') + '\n' + MEM_FIX_UTD
        assert S_MEM_UTD in s2
        io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s2)
        print('OK MEMORY.md 已纠正 UTD 误判 + 追加 UTD 专节')
    return 0


if __name__ == '__main__':
    sys.exit(main())