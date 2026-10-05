#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 5.1.61（打包后自动删副本）写进记忆（幂等 + LF）"""
import io
import sys

LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'

S_LOG = '## 5.1.61 —— 多文件「先复制、打包完即删」'
S_MEM = '★ **写「登记/置位」却忘写调用点时，校验要 grep 函数名而非只查方法定义**'

NOTE = """

---

## 5.1.61 —— 多文件「先复制、打包完即删」

### 一、需求

vivi：「那就先复制到沙箱，再自动删除」
⇒ 接受 5.1.60 那个限制（**多文件 zip 只能走真实路径**），
但要求副本**不长期占沙箱**。

### 二、删除时机：选在「打包成功之后」，不是「zip 被取走之后」

`POST /compressFiles` 里 `await zlib.compressFiles(safe, out, {})` 返回那一刻，
字节已在 zip 里 ⇒ 副本使命完成，立刻删。

★ **为什么不拖到 `GET /downloadZipFile` 之后**：
1. 取zip 是**另一次请求**，可能断线/被取消 ⇒ 副本永久残留；
2. 跨两个请求关联「谁该删」容易漏（进程被杀就再没人来删）。

### 三、★★ 安全性：登记簿（这是本轮最关键的设计）

⚠️⚠️ **`stageForWeb` 与「文件页单条推送」共用同一个入口** ⇒
若按「本次 `safe` 列表」盲删，**会把用户原有的接收文件删掉 = 数据丢失**。

解法：**登记簿**（进程内 `Set<string> webStageSet`）
- `stageForWeb()` 复制成功后 `HttpRouter.markWebStage([dst])` 登记；
- `compressFiles()` 打包成功后 `pruneWebStageSafe(safe)`：
  **只删登记在册的**（`webStageSet.has(p)`），删完清登记；
- 打包**失败**走 `forgetWebStage(safe)`：只清登记、**不删文件**（留作重试）。

⇒ ★★★ **判据：「这个文件是我创建的临时副本吗？」必须有可查的凭据（本例是登记簿），
不能靠「看起来像临时文件」。**
★ 这与 MEMORY 里「资产生死探测无法自证可信」同源：**要删东西，必须有独立的身份凭据。**

### 四、双层兜底

1. `pruneWebStageSafe([])`：每次 `/compressFiles` **开头**先清上一次的残留
   （覆盖「上次进程被杀、没走到删除」）。
2. `LanService.pruneWebStage()`：整目录清 `saveRoot/网页待下载/`
   （这个目录**只由 stageForWeb 产生**，所以整目录清不会碰到
   `saveRoot/<分类>/` 里的接收文件）；跳过 `isDirectory()`。

### 五、★ 一个自己写出来的 bug（补丁脚本层面）

第一版补丁**写了 `markWebStage` 却从没用它** ⇒ 登记簿永远为空 ⇒ **副本永远删不掉**。
是我在写二次校验时逐条 grep 新方法名才发现的。
⇒ ★ **动作：给函数写了「登记/置位」却没写「调用点」时，校验要grep **函数名**，
而不是只 grep 方法定义。**

### 六、验证

`docs/patch_scripts/verify_stage_cleanup_5161.js` —— **14/14 PASS**，
逐条断言安全性：只删登记在册的 / 删除在「已打包」日志之后 /
打包失败分支里**没有** `unlinkSync` / 复制成功后**在 `okc` 分支内**登记 /
整目录清理跳过目录项。
⚠️ 本轮是**静态结构检查**（ArkTS 无法在 node 里跑），
真机行为仍需装完实测（设备当时离线）。
"""

MEM_ADD = """
★★★「程序自己创建的临时文件」必须**登记 + 用完即删**
  - **登记**：创建一个可查的凭据（本项目 = 进程内 `Set<string>` 登记簿 + 专用子目录）。
    ⚠️⚠️ **绝不能靠「看起来像临时文件」判** —— 本项目 `stageForWeb()` 与
    「文件页单条推送」**共用同一个入口**，若按「本次路径列表」盲删，
    **会把用户原有的接收文件删掉 = 数据丢失**。
    ⇒ ★ **判据「这文件是我创建的吗」必须有独立凭据**（登记簿 / 专用目录前缀），
      与「资产生死探测无法自证可信」同源：**要删东西，必须有可验证的身份**。
  - **用完即删，且删在「最后一道复制完成」之后**：
    打包成功的那一刻字节已在 zip 里 ⇒ 立刻删。
    ★ **不要拖到「zip 被取走之后」**：取 zip 是**另一次请求**，
    可能断线/取消 ⇒ 副本永久残留；且跨请求关联「谁该删」容易漏
    （进程被杀就再没人来删）。
  - **失败路径只清登记、不删文件**（留作重试）—— 这两个动作必须分开写。
  - **兜底两层**：每次操作入口清上一次残留 + 专用子目录整目录清（跳过 `isDirectory()`）。
  ★ **写「登记/置位」却忘写调用点时，校验要 grep 函数名而非只查方法定义**
    （5.1.61 第一版就犯了这个错⇒ 登记簿永远空、副本永远删不掉）。
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