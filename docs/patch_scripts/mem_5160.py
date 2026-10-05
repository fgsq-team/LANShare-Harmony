#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 5.1.60（发送网页端零落盘）写进记忆（幂等 + LF）"""
import io
import sys

LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'

S_LOG = '## 5.1.60 —— 发送到网页端「零落盘」（连沙箱副本也不要）'
S_MEM = '★ `fileIo.openSync()` **能直接打开 picker 的 `datashare://` 授权 URI**'

NOTE = """

---

## 5.1.60 —— 发送到网页端「零落盘」（连沙箱副本也不要）

### 一、症状

vivi：「单个文件可以直接下载了，但是鸿蒙 APP 还是会保存到沙箱一份，我不希望他保存」
⇒ 5.1.59 只解决了**网页端不打包 zip**，但**鸿蒙端自己**那份副本还在。

### 二、真凶

`LanService.stageForWeb()` 把 picker/相册选中的文件**整份复制**到
`${saveRoot}/网页待下载/`，只为了给浏览器一个「HTTP 能读的路径」，
而且**通篇没有任何清理逻辑** ⇒ 文件永久留在沙箱。

### 三、关键突破：「必须复制」这个前提**只对 zip 成立**

原注释写「必须先复制」并给了理由：
> 「HTTP 服务端打包用的是 `zlib.compressFiles`，它只认真实文件路径；
> 而 picker 给的是带临时授权的 URI（`datashare://`），打包不了。」

★ **这话对 `/compressFiles`（zip）成立，对单文件直推不成立**：
`sendFileRange()` 用的是 `fileIo.openSync(spec.filePath)`，
而 **`fileIo.openSync()` 本来就能直接打开 `datashare://` 授权 URI**
（同工程 `FileSource.open(uri)` 早就是这么用的，我却在上面忽略了这一点）。
⇒ **结论：只要单文件走「专用端点 + 流式发送」，一个字节都不用落盘。**

### 四、改法

1. **`HttpRouter`** 新增 `GET /stagefile/<名>?uri=<授权URI>&token=`
   —— `fileIo.openSync(uri)` 直接流式发送。
   ⚠️ **安全性**：`/file/` 靠 `resolveSafePath()` 限定沙箱内，而本端点传的是授权 URI，
   必须自己把关 ⇒ **只接受授权 URI 形态白名单**
   （`datashare://` / `file://` / `file.pho` / `media://` / `content://`），
   **裸绝对路径一律拒绝**（否则就成了「任意沙箱文件读取」）。
   另：文件名要 `.replace(/[\\r\\n]/g,'_')` 防响应头注入。
2. **`LanService`** 新增 `pushUrisToWeb()`：WebSocket 推 `{uris, names}`
   （**不带 paths**）；另导出 `class WebPushItem {uri, name}`。
3. **`Index.pushUrisToWeb`**：单文件走 `pushUrisToWeb`（**不再调 `stageForWeb`**）；
   多个文件仍走 `stageForWeb` + zip（浏览器只能一次下多个文件）。
4. **网页端**：`uris` 有值 ⇒ 走 `/stagefile/`；否则回退 `/file/`。
5. 「文件」页单条（文件本就在沙箱）**仍走原 `pushFilesToWeb`，零改动**。

### 五、★ 验证脚本当场抓出我一个真 bug（这轮最大的收获）

`verify_web_zero_copy_5160.js` 的用例 A（`paths` 为空、只有 `uris`）
**没走 `/stagefile/`** ⇒ 我 5.1.60 第一版把主分支改对了，
**却漏改了函数开头的入口守卫** `if (!b || b.length === 0) { return }` ——
零落盘推送**不带 paths** ⇒ 第一行就return 了。
若没做「跑真实函数」验证，这个 bug 会一路带到真机。

⇒ ★★★★ **「改了主分支」不等于「改了函数」** ——
**入口守卫 / 前置 return / 长度校验 / 空值兜底** 这些地方**也属于改动面**。
⇒ ★ **动作：函数签名或调用契约一变（比如从「传 paths」变成「传 uris」），
必须回头审计函数内**所有** `param.length` / `!param` 的判空**——
它们每一个都是入口守卫。**
（这与 MEMORY 里「新增参数要查四层」同源：**契约一变，所有依赖旧契约的判据都要重审**。）

### 六、验证

- JS：`node vm.Script` 语法 OK + 最小桩跑真实函数 **11/11 PASS**
  （零落盘走/stagefile/、老路径回归走 /file/、两者都有时优先零落盘、
  多文件仍打包、全空无动作）
- ArkTS：编译期保证；真机需另测（设备当时离线）
"""

MEM_ADD = """
★ `fileIo.openSync()` **能直接打开 picker 的 `datashare://` 授权 URI**
  （同工程 `FileSource.open(uri)` 就是这么用的，`stageForWeb` 也是靠它读 picker 文件）。
  ⇒ ★★ **别被「必须先复制进沙箱」的前提绑住**：
  本项目曾断言「picker 给的是带临时授权的 URI，打包不了，所以必须复制」——
  ★ **这句只对 `zlib.compressFiles`（zip 打包）成立**，
  对**流式发送不成立**（`sendFileRange`走 `openSync(spec.filePath)`，URI 照样能开）。
  ⇒ **动作：遇到「必须先复制/落盘才能做X」时，先分清 X 到底是「打包」还是「读字节」——
  后者往往根本不需要复制。**（5.1.60 据此新增 `/stagefile/?uri=` 端点实现零落盘。）

★★★★ **「改了主分支」不等于「改了函数」—— 入口守卫也是改动面**
  5.1.60 把推送从「传 paths」改成「传 uris」，主分支改对了，
  却漏改函数开头`if (!paths.length) return` ⇒新路径第一行就被短路。
  是**跑真实函数的验证脚本**抓到的（`verify_web_zero_copy_5160.js` 用例 A），
  否则会一路带到真机。
  ⇒ ★ **函数签名/调用契约一变（尤其是「少传一个参数」），
  必须回头审计函数内所有 `param.length` / `!param` 的判空** —— 每一个都是入口守卫。
  这与「新增参数要查四层」同源：**契约一变，依赖旧契约的判据全部要重审**。
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